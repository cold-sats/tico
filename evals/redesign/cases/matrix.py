"""Coverage matrix (TESTING.md L2b): every row of the seeded all-pairs plan (evals/redesign/matrix.py) is built as a real
automation through POST /api/v2/automations, fired with a fake input, and read back. The universal invariants run over
the combinations that produced a run. A combination the product cannot build, or whose input has no named route, is
Unmet on that combination only; a check with no run at all raises Unmet, and one that finds nothing to check fails.

Limits, stated so a pass is read for what it is: a condition on a task field can only hold for a task, so schedule and
webhook combinations run with their condition unmet; the spend-cap outcome sets a 0.01 cap but does not spend first, so
the cap is only reached if the engine spends on its own; the action args are empty for every action (CONTRACT names
none)."""
from ..harness import CHRIS_ID, CHRIS_REF, CLAUDE, CLAUDE_ID, CLAUDE_REF, GAP, W3, Check, Scenario, Unmet, \
    body, replied, rows, send, setup, untestable
from ..fakes import ReplayJudge, attach_judge
from ..matrix import coverage, feasible_pairs, lower_bound, pairs_of, plan
from .engine import incoming, nested, wide
from .inboxes import BUCKET

# Kinds with no named route in the CONTRACT: each is untestable, and nothing is created for it.
NO_FIRE = {
    "slack": "CONTRACT names no Slack inbox reference (gap i)",
    "email": "CONTRACT names no route that delivers a received mail to a message trigger (gap a)",
    "listening": "CONTRACT names no route that delivers a listening match to a listening trigger (gap a)",
    "event": "CONTRACT names no route that delivers a catalog event to an event trigger (gap a)",
}
ACTION = {"archive": "archive", "leave-for-you": "leave_for_you", "draft-reply": "draft_reply",
          "send-reply": "send_reply", "create-task": "create_task", "label": "label", "forward": "forward",
          "wake-bot": "wake_bot", "note": "note", "post-update": "post_update", "call-webhook": "call_webhook",
          "assign": "assign"}
STATUSES = {"ok", "skipped", "failed", "spend_cap"}
NEVER = {"field": "task.title", "op": "is", "value": "never-sent"}   # the paths that must not match
SPEC = {   # condition value -> (field, op, value, min)
    "is": ("task.title", "is", "urgent", None),
    "is-min": ("d1.bucket", "is", "reply", 0.7),
    "is-not": ("task.title", "is_not", "lunch", None),
    "is-not-min": ("d1.bucket", "is_not", "archive", 0.7),
    "gte": ("d1.urgency", ">=", 3, None),
    "lte": ("d1.urgency", "<=", 3, None),
    "contains": ("task.title", "contains", "urgent", None),
    "matches": ("task.title", "matches", "^urgent", None),
}


# ---------------------------------------------------------------------------------------------- flow pieces
def node(sid, kind, **fields):
    return {"id": sid, "type": kind, "enabled": True, **fields}


def condition_node(name):
    field, op, value, minimum = SPEC[name]
    return {"field": field, "op": op, "value": value, **({"min": minimum} if minimum is not None else {})}


def marker(sid):
    return node(sid, "action", do="note", args={})


def worker_node(kind, sid):
    if kind == "llm-assistant":
        return node(sid, "llm", **{"as": "assistant:chris"}, prompt="Matrix", out=sid)
    if kind == "llm-bot":
        return node(sid, "llm", **{"as": CLAUDE_REF}, prompt="Matrix", out=sid)
    return node(sid, "bot_turn", bot=CLAUDE_ID, prompt="Matrix")


def branch_steps(row, prefix):
    """The worker (if any) and the action, with ids made from `prefix` so no two nodes share an id."""
    steps = []
    if row["worker"] != "none":
        steps.append(worker_node(row["worker"], f"w{prefix}"))
    steps.append(node(f"act{prefix}", "action", do=ACTION[row["action"]], args={}))
    return steps


def fork_for(row, cond):
    """The paths step for a non-straight shape, and its fork groups (the ids of the branches, one group per fork)."""
    shape = row["shape"]
    if shape in ("two-paths", "four-paths"):
        count = 2 if shape == "two-paths" else 4
        paths = [{"name": f"p{k}", "when": [cond if k == 0 else NEVER],
                  "steps": [marker(f"p{k}")] + branch_steps(row, str(k))} for k in range(count)]
        otherwise = {"steps": [marker("po")] + branch_steps(row, "y")}
        return node("fork", "paths", paths=paths, otherwise=otherwise), [[f"p{k}" for k in range(count)] + ["po"]]
    inner = node("inner", "paths",   # a fork inside the first branch of the outer one
                 paths=[{"name": "q0", "when": [cond], "steps": [marker("q0")] + branch_steps(row, "0")}],
                 otherwise={"steps": [marker("qo")] + branch_steps(row, "x")})
    outer = node("fork", "paths", paths=[{"name": "p0", "when": [cond], "steps": [marker("p0"), inner]}],
                 otherwise={"steps": [marker("po")] + branch_steps(row, "y")})
    return outer, [["p0", "po"], ["q0", "qo"]]


def disable(steps, target):
    """Switches off the step with id `target`, wherever it sits (inside paths too)."""
    for step in steps:
        if step.get("id") == target:
            step["enabled"] = False
        for path in step.get("paths", []):
            disable(path.get("steps", []), target)
        if "otherwise" in step:
            disable(step["otherwise"].get("steps", []), target)


def build(row, outcome):
    """The flow for one row: (steps, fork groups, top-level step ids, the id switched off or None)."""
    cond = condition_node(row["condition"])
    straight = row["shape"] == "straight"
    first = []
    if row["first"] == "find":
        first.append(node("look", "find", source="tasks", query="matrix", since="last_run", limit=5))
    else:
        if "decide" in row["first"]:
            first.append(node("rank", "decide", questions=BUCKET, level="medium", out="d1"))
        if "filter" in row["first"]:
            rules = [{"when": [cond], "match": "all", "then": [], "stop": False}] if straight else []
            first.append(node("gate", "filter", rules=rules))
    if straight:
        tail, groups = branch_steps(row, ""), []
    else:
        fork, groups = fork_for(row, cond)
        tail = [fork]
    steps = first + tail
    top = [s["id"] for s in first] if row["first"] == "find" else [s["id"] for s in steps]
    off = None
    if outcome == "switched-off":
        if "rank" in top:
            off = "rank"
        elif "gate" in top:
            off = "gate"
        elif row["first"] == "find":
            off = "look"
        elif row["worker"] != "none":
            off = "w" if straight else "w0"
        else:
            off = "act" if straight else "act0"
        disable(steps, off)
    return steps, groups, top, off


def judge_for(row, matched):
    """The answers the judge gives for this decide: a clear reply or archive, and an urgency score on the right side
    of the row's comparison. Used only when the row's first steps include a Decide."""
    if row["outcome"] == "step-fails":
        return ReplayJudge(fail=RuntimeError("judge unavailable"))
    urgency = (2 if matched else 5) if row["condition"] == "lte" else (4 if matched else 1)
    answer = {"bucket": {"type": "choice", "choice": "reply" if matched else "archive",
                         "confidence": 0.9 if matched else 0.3,
                         "probabilities": {"reply": 0.9 if matched else 0.1, "archive": 0.1 if matched else 0.7}},
              "urgency": {"type": "score", "score": urgency}}
    return ReplayJudge(script=[answer])


def trigger_for(kind, n):
    """The trigger for a kind with a named route. The NO_FIRE kinds never reach here: run_combo stops before this."""
    if kind == "task":
        return {"type": "task_received", "to": CHRIS_REF}
    if kind == "schedule":
        return {"type": "schedule", "cron": "0 9 * * *", "tz": "UTC"}
    return {"type": "webhook", "id": f"hook-m{n}", "secret": f"secret-m{n}"}


def fire(org, kind, n, aid, matched):
    """The fake input for one combination. Each kind has its own route; the rest are untestable (see NO_FIRE)."""
    if kind == "task":
        return send(org, CLAUDE, CHRIS_ID, "urgent" if matched else "lunch")
    if kind == "schedule":
        return org.api("post", f"/api/v2/automations/{aid}/run", wave=W3)
    return incoming(org, f"/api/v2/hooks/hook-m{n}/secret-m{n}", {"title": "urgent" if matched else "lunch"})


def label_of(n, row):
    keys = ("trigger", "first", "shape", "worker", "action", "condition", "outcome")
    return f"#{n} " + "/".join(row[k] for k in keys)


def run_combo(org, n, row):
    """Builds one combination as an automation, fires it, and reads back its one run. Returns the record the checks read.
    Raises Unmet before anything is created when the kind has no named route, and when a route is not registered."""
    kind, outcome = row["trigger"], row["outcome"]
    if kind in NO_FIRE:
        raise Unmet(GAP, NO_FIRE[kind])
    matched = outcome != "no-match"
    steps, groups, top, off = build(row, outcome)
    payload = {"name": f"Matrix {n} · chris", "owner": CHRIS_REF, "enabled": True, "builtin": False,
               "trigger": trigger_for(kind, n), "steps": steps}
    if outcome == "spend-cap":
        payload["spend_cap"] = {"per_30m": 0.01}
    if "decide" in row["first"]:
        attach_judge(org, judge_for(row, matched))
    made = org.api("post", "/api/v2/automations", payload, wave=W3)
    record = {"label": label_of(n, row), "saved": 200 <= made.status < 300, "groups": groups, "top": top,
              "disabled": [off] if off else [], "run": None}
    if not record["saved"]:
        record["label"] += f" (create {made.status})"
        return record
    created = made.body if isinstance(made.body, dict) else {}
    aid = (created.get("automation") or created).get("id")
    fire(org, kind, n, aid, matched)
    runs = rows(org.api("get", f"/api/v2/automations/{aid}/runs", wave=W3).body)
    record["run"] = runs[0] if len(runs) == 1 else None
    record["runs"] = len(runs)
    return record


# ---------------------------------------------------------------------------------------------- invariants
def row_of(run, sid):
    return [s for s in run.get("steps") or [] if s.get("id") == sid]


def no_run(r):
    return "not saved" if not r["saved"] else f"no run logged ({r.get('runs', 0)} runs)"


def one_path(r):
    if r["run"] is None:
        return no_run(r)
    for group in r["groups"]:
        won = [sid for sid in group if any(s.get("status") == "ok" for s in row_of(r["run"], sid))]
        if len(won) > 1:
            return f"{won} all ran in one fork"
    return ""


def top_logged(r):
    if r["run"] is None:
        return no_run(r)
    missing = [sid for sid in r["top"] if not row_of(r["run"], sid)]
    bad = [s.get("id") for s in r["run"].get("steps") or [] if s.get("id") in r["top"] and s.get("status") not in STATUSES]
    if missing or bad:
        return f"not logged {missing}, bad status {bad}"
    return ""


def action_once(r):
    if r["run"] is None:
        return no_run(r)
    ran = [s.get("id") for s in r["run"].get("steps") or []
           if str(s.get("id", "")).startswith("act") and s.get("status") == "ok"]
    return f"action ran {len(ran)} times: {ran}" if len(ran) > 1 else ""


def costs_add(r):
    if r["run"] is None:
        return no_run(r)
    cost = r["run"].get("cost")
    total = sum(float(s.get("cost") or 0) for s in r["run"].get("steps") or [])
    if cost is None:
        return "run has no cost"
    return "" if abs(float(cost) - total) < 1e-6 else f"run cost {cost}, its steps add to {total}"


def disabled_silent(r):
    if r["run"] is None:
        return no_run(r)
    ran = [sid for sid in r["disabled"] if any(s.get("status") == "ok" for s in row_of(r["run"], sid))]
    return f"switched-off step ran: {ran}" if ran else ""


# ---------------------------------------------------------------------------------------------- gathering
def records(f):
    keys = sorted((k for k in f if k.startswith("c") and k[1:].isdigit()), key=lambda k: int(k[1:]))
    return [f[k] for k in keys]


def gate(f):
    """(combinations that produced a record, the Unmet of those that did not). Raises when none produced one."""
    recs = records(f)
    done = [r for r in recs if isinstance(r, dict)]
    stuck = [r for r in recs if isinstance(r, Unmet)]
    if not done:
        if stuck:
            raise Unmet(stuck[0].wave, f"0 of {len(recs)} combinations ran; first: {stuck[0].what}")
        raise Unmet(W3, "no combinations were built")
    return done, stuck


def across(rule):
    def check(f):
        done, stuck = gate(f)
        bad = [(r["label"], why) for r in done if (why := rule(r))]
        head = f"{len(done) - len(bad)} of {len(done)} clean, {len(stuck)} untestable"
        if bad:
            return False, f"{head}; first: {bad[0][0]}: {bad[0][1]} ({len(bad)} failing)"
        return True, head
    return check


def all_saved(f):
    done, stuck = gate(f)
    refused = [r["label"] for r in done if not r["saved"]]
    return not refused, f"{len(done) - len(refused)} of {len(done)} saved; {len(stuck)} untestable; refused: {refused[:3]}"


def probes_refused(f):
    """Two flows over the limits (11 paths, 4 nesting levels) are refused and not listed."""
    setup(f, "listing")
    ok_11, text_11 = replied(f, "probe_11", 400, 409, 422)
    ok_deep, text_deep = replied(f, "probe_deep", 400, 409, 422)
    names = {r.get("name") for r in rows(body(f, "listing"))}
    listed = {"Matrix probe 11", "Matrix probe deep"} & names
    return ok_11 and ok_deep and not listed, f"11 paths: {text_11}; 4 levels: {text_deep}; listed {sorted(listed)}"


def plan_values(rows_):
    _, unseen = coverage(rows_)
    return bool(rows_) and not unseen, f"{len(rows_)} combinations; values never used: {unseen}"


def pairs_covered(rows_):
    covered = set()
    for row in rows_:
        covered.update(pairs_of(row))
    need, _ = feasible_pairs()
    missing = need - covered
    return bool(need) and not missing, f"{len(need) - len(missing)} of {len(need)} feasible pairs in some combination"


def combo_floor(rows_):
    floor = lower_bound(feasible_pairs()[0])
    return bool(rows_) and len(rows_) >= floor, f"{len(rows_)} combinations, all-pairs floor {floor}"


def probe_payload(name, steps):
    return {"name": name, "owner": CHRIS_REF, "enabled": True, "builtin": False,
            "trigger": {"type": "schedule", "cron": "0 9 * * *", "tz": "UTC"}, "steps": steps}


def matrix_scenario(seed):
    rows_ = plan(seed)

    def steps(org, f):
        for n, row in enumerate(rows_):
            org.step(f, f"c{n}", run_combo, org, n, row)
        org.step(f, "probe_11", org.api, "post", "/api/v2/automations",
                 probe_payload("Matrix probe 11", wide(11)), wave=W3)
        org.step(f, "probe_deep", org.api, "post", "/api/v2/automations",
                 probe_payload("Matrix probe deep", nested(4)), wave=W3)
        org.step(f, "listing", org.api, "get", "/api/v2/automations", wave=W3)

    checks = [
        Check("every dimension value is in at least one combination", W3, lambda f: plan_values(rows_)),
        Check("every feasible pair is in at least one combination", W3, lambda f: pairs_covered(rows_)),
        Check("the combination count is at least the all-pairs floor", W3, lambda f: combo_floor(rows_)),
        Check("every valid combination is saved as an automation", W3, all_saved),
        Check("exactly one path runs per fork", W3, across(one_path)),
        Check("every top-level step is logged with a status", W3, across(top_logged)),
        Check("each action runs at most once", W3, across(action_once)),
        Check("costs add up: the run's cost is the sum of its steps", W3, across(costs_add)),
        Check("a disabled step never runs", W3, across(disabled_silent)),
        Check("a refused flow is never saved (11 paths, 4 nesting levels)", W3, probes_refused),
        Check("no LLM or Bot turn runs in a sender's session", W3,
              untestable("CONTRACT names no read of which session ran a turn (gap e)")),
    ]
    return Scenario(0, f"matrix-seed-{seed}",
                    f"All-pairs coverage matrix, seed {seed}: {len(rows_)} combinations", steps, checks)
