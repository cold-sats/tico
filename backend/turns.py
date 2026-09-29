"""What a bot's turn did, for the chat under its reply (#524).

A reply carries `refs.turn_id`, its attempt. `annotate` adds two things a person reading the room
may see: the titles of the tasks a message refers to, and `run` on a reply: the hub work the turn
did while it ran (tasks handed out, links filed, questions and messages sent, refusals) and the
size of its work (steps, tool calls, time). `GET /api/v2/turns/{id}/steps` is that work line by
line, read when someone opens it. Everything is read from what the hub already records; a row
the reader could not open on its own (a task or a conversation outside their reach) is left out.
"""

import json

from fastapi import Request

from .store import H, Problem

SAID_CHARS, THINKING_CHARS, STEP_LIMIT = 280, 2000, 300
# A tool event that opens a call; the next event for the same call closes it.
TOOL_START = {"started", "start", "running", "pending", "in_progress", "tool_execution_start"}
TOOL_QUIET = {"", "completed", "done", "success", "succeeded", "tool_execution_end"}
# Text deltas are the reply being typed and tokens/status are bookkeeping: none is a step.
STEP_EVENTS = ("(kind IN ('tool','message','error') OR "
               "(kind='delta' AND json_extract(payload_json,'$.delta_kind')='thought'))")


def clip(text, limit):
    text = " ".join(str(text or "").split())
    return text if len(text) <= limit else text[:limit - 1] + "…"


def build_steps(rows):
    """One line per thing the turn did, from its attempt events: (kind, payload, created)."""
    steps, calls, thinking = [], {}, None
    final = next((str(p.get("text") or "") for kind, p, _ in reversed(rows) if kind == "message" and p.get("final")), "")
    for kind, p, at in rows:
        if kind == "delta":       # the model's thinking arrives in pieces; one run of them is one step
            if not thinking:
                thinking = {"kind": "thinking", "tool": "", "text": "", "at": at}
                steps.append(thinking)
            thinking["text"] += str(p.get("text") or "")
            continue
        thinking = None
        if kind == "tool":
            name = str(p.get("tool") or p.get("name") or "tool")
            status = str(p.get("status") or p.get("state") or p.get("phase") or "").lower()
            key = p.get("item_id") or name
            if key in calls and status not in TOOL_START:
                calls.pop(key)["text"] = "" if status in TOOL_QUIET else status
                continue
            step = {"kind": "tool", "tool": name, "text": "" if status in TOOL_QUIET | TOOL_START else status, "at": at}
            steps.append(step)
            if status in TOOL_START:
                calls[key] = step
        elif kind == "message" and not p.get("final"):
            text = str(p.get("text") or "")
            if text.strip() and text.strip() != final.strip():
                steps.append({"kind": "said", "tool": "", "text": clip(text, SAID_CHARS), "at": at})
        elif kind == "error":
            steps.append({"kind": "error", "tool": "", "text": clip(p.get("error") or p.get("text"), SAID_CHARS), "at": at})
    for step in steps:
        if step["kind"] == "thinking":
            step["text"] = clip(step["text"], THINKING_CHARS)
    return steps[:STEP_LIMIT]


def seconds(start, end):
    a, b = H.parse_ts(start), H.parse_ts(end)
    return int((b - a).total_seconds()) if a and b else None


def readable(fn):
    try:
        fn()
        return True
    except Problem:
        return False


def task_refs(message):
    for key, values in (message.get("refs") or {}).items():
        if "task" in key.lower():
            yield from (v for v in (values if isinstance(values, list) else [values]) if isinstance(v, str) and v)


def annotate(c, auth, who, messages):
    """Add `ref_tasks` and, on a bot's reply, `run` to messages this reader may already see."""
    titles = {}
    for tid in {v for m in messages for v in task_refs(m)}:
        row = H.task(c, tid)
        if row and readable(lambda: auth.task_row(c, who, row)):
            titles[tid] = {"title": row["title"], "owner": row["owner"], "status": row["status"]}
    for m in messages:
        known = {v: titles[v] for v in task_refs(m) if v in titles}
        if known:
            m["ref_tasks"] = known
    replies = {m["refs"]["turn_id"]: m for m in messages
               if str(m.get("from_actor", "")).startswith("bot:") and (m.get("refs") or {}).get("turn_id")}
    if not replies:
        return messages
    marks = ",".join("?" * len(replies))
    turns = {r["id"]: dict(r) for r in c.execute(
        f"SELECT id,bot,created,started,finished FROM attempts WHERE id IN ({marks})", tuple(replies))}
    # What a bot did to answer is its run log: Read. Someone who may only write to it gets the answer.
    access = auth.bot_accesses(c, who, sorted({t["bot"] for t in turns.values()}))
    turns = {aid: t for aid, t in turns.items() if access.get(t["bot"], auth.FULL)["read"]}
    replies = {aid: m for aid, m in replies.items() if aid in turns}
    if not turns:
        return messages
    for t in turns.values():
        t["from"], t["to"] = t["started"] or t["created"], t["finished"] or H.now()
    actors = sorted({"bot:" + t["bot"] for t in turns.values()})
    lo, hi = min(t["from"] for t in turns.values()), max(t["to"] for t in turns.values())
    who_marks = ",".join("?" * len(actors))

    def owner_of(actor, at):
        return next((aid for aid, t in turns.items() if "bot:" + t["bot"] == actor and t["from"] <= at <= t["to"]), None)

    did = {aid: [] for aid in turns}
    for row in c.execute(f"SELECT * FROM tasks WHERE requester IN ({who_marks}) AND created BETWEEN ? AND ?",
                         (*actors, lo, hi)):
        aid = owner_of(row["requester"], row["created"])
        if aid and readable(lambda: auth.task_row(c, who, row)):
            did[aid].append({"kind": "task", "task_id": row["id"], "title": row["title"], "owner": row["owner"],
                             "at": row["created"]})
    for row in c.execute(f"SELECT l.*,t.owner,t.requester,t.id AS tid FROM task_links l JOIN tasks t ON t.id=l.task_id "
                         f"WHERE l.added_by IN ({who_marks}) AND l.created BETWEEN ? AND ?", (*actors, lo, hi)):
        aid = owner_of(row["added_by"], row["created"])
        if aid and readable(lambda: auth.task_row(c, who, {"id": row["tid"], "owner": row["owner"], "requester": row["requester"]})):
            did[aid].append({"kind": "link", "url": row["url"], "title": row["title"] or "", "at": row["created"]})
    rooms_of = {aid: replies[aid]["conversation_id"] for aid in turns}
    for row in c.execute(f"SELECT id,conversation_id,from_actor,to_actor,kind,body,created FROM messages "
                         f"WHERE from_actor IN ({who_marks}) AND kind IN ('ask','say') AND created BETWEEN ? AND ?",
                         (*actors, lo, hi)):
        aid = owner_of(row["from_actor"], row["created"])
        if not aid or row["conversation_id"] == rooms_of[aid] or row["to_actor"] == row["from_actor"]:
            continue
        if readable(lambda: auth.conversation(c, who, row["conversation_id"])):
            did[aid].append({"kind": row["kind"], "to": row["to_actor"], "text": clip(row["body"], 160), "at": row["created"]})
    for row in c.execute(f"SELECT ts,actor,rule,detail_json FROM refusals WHERE actor IN ({who_marks}) AND ts BETWEEN ? AND ?",
                         (*actors, lo, hi)):
        aid = owner_of(row["actor"], row["ts"])
        if aid:
            detail = (json.loads(row["detail_json"] or "{}") or {}).get("detail") or ""
            did[aid].append({"kind": "refused", "rule": row["rule"], "text": clip(detail, 200), "at": row["ts"]})
    events = {aid: [] for aid in turns}
    for row in c.execute(f"SELECT attempt_id,kind,payload_json,created FROM attempt_events WHERE attempt_id IN "
                         f"({','.join('?' * len(turns))}) AND {STEP_EVENTS} ORDER BY attempt_id,seq", tuple(turns)):
        events[row["attempt_id"]].append((row["kind"], json.loads(row["payload_json"]), row["created"]))
    for aid, t in turns.items():
        steps = build_steps(events[aid])
        replies[aid]["run"] = {"did": sorted(did[aid], key=lambda d: d["at"]), "steps": len(steps),
                               "tool_calls": sum(s["kind"] == "tool" for s in steps),
                               "took_s": seconds(t["started"], t["finished"])}
    return messages


def install(app, store, auth):
    @app.get("/api/v2/turns/{aid}/steps")
    def turn_steps(request: Request, aid: str):
        """A turn's work, one line per step. Readable by whoever can read the room it answered."""
        who = request.state.identity
        with store.read() as c:
            row = c.execute("SELECT a.*,m.conversation_id FROM attempts a JOIN jobs j ON j.id=a.job_id "
                            "JOIN messages m ON m.id=j.message_id WHERE a.id=?", (aid,)).fetchone()
            if not row:
                raise Problem("not_found", "Turn not found", 404)
            auth.conversation(c, who, row["conversation_id"])
            auth.require_read(c, who, row["bot"])
            events = [(r["kind"], json.loads(r["payload_json"]), r["created"]) for r in c.execute(
                f"SELECT kind,payload_json,created FROM attempt_events WHERE attempt_id=? AND {STEP_EVENTS} ORDER BY seq",
                (aid,))]
            steps = build_steps(events)
            return {"turn_id": aid, "started": row["started"], "finished": row["finished"],
                    "took_s": seconds(row["started"], row["finished"]),
                    "tool_calls": sum(s["kind"] == "tool" for s in steps), "steps": steps}
