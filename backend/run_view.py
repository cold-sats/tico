"""A task's run panel: every attempt that worked the task and what happened to it, the subagents each one started,
the background shells and monitors it left running, and the task's checkpoint.

`GET /api/v2/tasks/{id}/run-view` reads only what the hub already records: `turns` (one per attempt, by task),
`attempts` and `jobs` (a job's attempts are its tries), the audit events that record a recovery decision or a lease
grace, and the attempt's `tool` events. A tool event carries the call's name, the file or program it acts on and,
for a subagent, its type and model; never the call's arguments or output, so none can reach this view.
"""

import json

from fastapi import Request

from .store import H
from . import task_privacy as privacy
from .turns import TOOL_START, TOOL_BACKGROUNDED, clip, seconds

ATTEMPT_LIMIT, NODE_LIMIT, SUMMARY_CHARS = 20, 50, 120
LIVE = ("leased", "running")
# What a person or the hub decided about a stopped attempt, and the lease events that kept or lost it.
DECISIONS = ("job.reconcile", "job.auto_reconcile")
LEASE = {"attempt.lease-grace": "grace", "attempt.lease-restored": "restored"}


def failure_reason(state, result_json):
    if state not in ("failed", "expired"):
        return None
    try:
        result = json.loads(result_json or "{}") or {}
    except (ValueError, TypeError):
        result = {}
    reason = result.get("error") or result.get("reason") or result.get("message")
    return clip(reason, 280) if reason else (
        "Lease expired before completion" if state == "expired" else "Attempt failed before completion")


def work(rows, live):
    """The subagents and background calls in one attempt's tool events, in the order they started. A call is
    `running` only while its attempt is: a call still open when the attempt ended reports no end."""
    agents, shells = {}, {}
    for p, at in rows:
        key = p.get("item_id")
        if not key:
            continue
        status = str(p.get("status") or "").lower()
        agent = p.get("subagent") if isinstance(p.get("subagent"), dict) else None
        if agent:
            node = agents.setdefault(key, {"id": key, "parent_id": agent.get("parent_id") or p.get("parent_id"),
                                           "type": None, "model": None, "status": None, "background": False,
                                           "tool_uses": None, "duration_ms": None, "started": at, "ended": None})
            node["type"] = clip(agent.get("type") or node["type"] or "agent", 60)
            node["model"] = clip(agent.get("model"), 80) or node["model"]
            for field in ("tool_uses", "duration_ms"):
                if isinstance(agent.get(field), (int, float)):
                    node[field] = agent[field]
            node["background"] = node["background"] or bool(p.get("background"))
            if status not in TOOL_START:
                node["status"], node["ended"] = status, at
        elif p.get("background"):
            if key not in shells and status in TOOL_START:
                shells[key] = {"id": key, "tool": clip(p.get("tool") or "tool", 60), "summary": clip(p.get("summary"), SUMMARY_CHARS),
                               "parent_id": p.get("parent_id"), "status": None, "started": at, "ended": None}
            elif key in shells and status not in TOOL_START and status != TOOL_BACKGROUNDED:
                shells[key]["status"], shells[key]["ended"] = status, at
        elif status == TOOL_BACKGROUNDED and key in agents:
            agents[key]["background"] = True
        elif status == TOOL_BACKGROUNDED:
            # A call moved to the background while it ran; its start line named it but not as background.
            shells[key] = {"id": key, "tool": clip(p.get("tool") or "tool", 60), "summary": "", "parent_id": p.get("parent_id"),
                           "status": None, "started": at, "ended": None}
    for node in (*agents.values(), *shells.values()):
        node["running"] = node["ended"] is None and live
        if node["ended"] is None and not live:
            node["status"] = "no end reported"
        if node.get("duration_ms") is None and "tool_uses" in node and node["ended"]:
            took = seconds(node["started"], node["ended"])
            node["duration_ms"] = took * 1000 if took is not None else None
    return list(agents.values())[:NODE_LIMIT], list(shells.values())[:NODE_LIMIT]


def next_step(attempt, tries, job, decisions, retries):
    """What followed an attempt: a recorded decision, a person's retry, the hub's own retry, or a wait."""
    decided = decisions.get(attempt["id"])
    if decided:
        return decided
    later = [t for t in tries if t["created"] > attempt["created"]]
    if later:
        nxt = later[0]["created"]
        by = next((r for r in retries if (attempt["finished"] or attempt["created"]) <= r["at"] <= nxt), None)
        if by:
            return {"kind": "retried", "by": by["by"], "at": by["at"], "note": "Run again by hand."}
        return {"kind": "retried", "by": H.KEEPER, "at": nxt, "note": "Run again automatically."}
    if attempt["state"] in LIVE:
        return None
    if job["state"] == "uncertain":
        return {"kind": "waiting", "by": None, "at": None,
                "note": "Stopped partway after it may have acted: waiting for a person to decide whether to run it again."}
    if job["state"] in ("queued", "leased"):
        return {"kind": "queued", "by": None, "at": None, "note": "Queued to run again."}
    return None


def run_view(c, who, tid):
    actor = privacy.actor(who)
    turns = [r for r in H._rows(c.execute(
        "SELECT t.id,t.bot,t.exit,a.job_id,a.state,a.created,a.started,a.finished,a.lease_until,a.result_json "
        "FROM turns t JOIN attempts a ON a.id=t.id WHERE t.task_id=? ORDER BY a.created DESC LIMIT ?",
        (tid, ATTEMPT_LIMIT))) if privacy.attempt_readable(c, actor, r["id"])]
    ids = [r["id"] for r in turns]
    jobs = sorted({r["job_id"] for r in turns})
    task = c.execute("SELECT checkpoint,checkpoint_at,checkpoint_by FROM tasks WHERE id=?", (tid,)).fetchone()
    checkpoint = ({"text": task["checkpoint"], "at": task["checkpoint_at"], "by": task["checkpoint_by"]}
                  if task and (task["checkpoint"] or "").strip() else None)
    if not ids:
        return {"task_id": tid, "checkpoint": checkpoint, "attempts": []}
    marks, job_marks = ",".join("?" * len(ids)), ",".join("?" * len(jobs))
    job_rows = {r["id"]: r for r in H._rows(c.execute(f"SELECT id,state FROM jobs WHERE id IN ({job_marks})", jobs))}
    # Tries are counted over every attempt of the job, not only the ones this page shows.
    tries = {}
    for r in H._rows(c.execute(f"SELECT id,job_id,created FROM attempts WHERE job_id IN ({job_marks}) ORDER BY created",
                               jobs)):
        tries.setdefault(r["job_id"], []).append(r)
    since = min(r["created"] for r in turns)
    decisions, retries, lease = {}, {}, {}
    for e in c.execute(f"SELECT ts,actor,action,target,detail_json FROM events WHERE ts>=? AND (("
                       f"action IN ('job.reconcile','job.auto_reconcile','job.retry') AND target IN ({job_marks})) OR "
                       f"(action IN ('attempt.lease-grace','attempt.lease-restored') AND target IN ({marks}))) ORDER BY ts",
                       (since, *jobs, *ids)):
        detail = json.loads(e["detail_json"] or "{}") or {}
        if e["action"] in DECISIONS and detail.get("attempt_id"):
            decisions[detail["attempt_id"]] = {
                "kind": "resumed" if detail.get("decision") == "resume" else "dismissed",
                "by": e["actor"], "at": e["ts"], "note": clip(detail.get("note"), 400)}
        elif e["action"] == "job.retry":
            retries.setdefault(e["target"], []).append({"by": e["actor"], "at": e["ts"]})
        elif e["action"] in LEASE:
            lease.setdefault(e["target"], []).append({"kind": LEASE[e["action"]], "at": e["ts"]})
    events = {aid: [] for aid in ids}
    for r in c.execute(f"SELECT attempt_id,kind,payload_json,created FROM attempt_events WHERE attempt_id IN ({marks}) "
                       "AND kind='tool' AND (json_extract(payload_json,'$.subagent') IS NOT NULL OR "
                       "json_extract(payload_json,'$.background') IS NOT NULL OR "
                       "json_extract(payload_json,'$.status')=?) ORDER BY attempt_id,seq", (*ids, TOOL_BACKGROUNDED)):
        if privacy.content_readable(c, actor, dict(r)):
            events[r["attempt_id"]].append((json.loads(r["payload_json"]), r["created"]))
    from .usage_records import ran_on
    made = ran_on(c, ids)
    out = []
    for r in turns:
        job_tries = tries.get(r["job_id"], [])
        live = r["state"] in LIVE
        subagents, background = work(events[r["id"]], live)
        out.append({
            "run": r["id"], "bot": r["bot"], "job": r["job_id"],
            "try": next((n for n, t in enumerate(job_tries, 1) if t["id"] == r["id"]), 1), "tries": len(job_tries),
            "state": r["state"], "outcome": r["exit"], "created": r["created"], "started": r["started"],
            "finished": r["finished"], "took_s": seconds(r["started"], r["finished"]), "ran_on": made.get(r["id"]),
            "lease_until": r["lease_until"] if live else None, "lease": lease.get(r["id"], []),
            "reason": failure_reason(r["state"], r["result_json"]),
            "next": next_step(r, job_tries, job_rows.get(r["job_id"]) or {"state": None}, decisions,
                              retries.get(r["job_id"], [])),
            "subagents": subagents, "background": background})
    return {"task_id": tid, "checkpoint": checkpoint, "attempts": out}


def install(app, store, auth):
    @app.get("/api/v2/tasks/{tid}/run-view")
    def task_run_view(request: Request, tid: str):
        """The task's attempts, subagents, background work and checkpoint. Readable by whoever can read the task;
        an attempt the reader cannot read on its own (it carried a private task they cannot see) is left out."""
        who = request.state.identity
        with store.read() as c:
            tid = auth.resolve_task(c, who, tid)
            auth.task(c, who, tid)
            return run_view(c, who, tid)
