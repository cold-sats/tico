"""Coverage matrix (TESTING.md L2b): every row of the seeded all-pairs plan (evals/redesign/matrix.py) is built as a
real automation through POST /api/v2/automations, fired with run input through POST /{id}/run {"input": ...} (CONTRACT
§2 Feeding input, the product's "Test with sample"), and read back from GET /{id}/runs. Every trigger kind is fired:
email from a mail the mail sync published first (so mail actions have a real message to act on), Slack, task, webhook
(on a real incoming trigger), listening (to a real destination) and event (a catalog event) from their sample, and a
schedule with no input. All the mail is published before any automation exists, so the sync fires none. The universal
invariants run over the combinations that produced a run. A combination whose route is not registered is Unmet on that
combination only; a check with no run at all raises Unmet, and one that finds nothing to check fails.

Reading the run: a failed step ends its thread, and an llm step whose turn is still held does too until the turn answers
(automation_engine.py), so the steps after either have no record yet; a `find` runs the steps after it once per item, so
the per-step checks count each item's records separately. The matrix never answers a held turn, so no action after an
llm step is exercised.

Limits, stated so a pass is read for what it is: a schedule has no input, so its condition is never met; the spend-cap
outcome sets a 0.01 cap but does not spend first, so the cap is only reached if the engine spends on its own; the action
args are empty for every action (CONTRACT names none). The sender's session is the one the task sample names (CONTRACT
names no field for it): builder-claude's live session, which a warm-up turn opens before any automation exists."""
from ..fakes import ReplayJudge, attach_judge
from ..harness import (DANA_REF, CLAUDE_ID, CLAUDE_REF, LEAD_ID, W3, Check, Reply, Scenario, Unmet, body, mail_message,
                       publish_mail, replied, rows, run_now, setup, turn_of, work)
from ..matrix import coverage, feasible_pairs, lower_bound, pairs_of, plan
from .engine import nested, wide
from .inboxes import BUCKET

INBOX = "dana@acme.example"
DESTINATION = "matrix-leads"
SENDER_SESSION = "redesign"   # the thread every turn in the harness starts on (Org.turn): builder-claude's live session
WORKERS = ("llm", "bot_turn")
ACTION = {"archive": "archive", "leave-for-you": "leave_for_you", "draft-reply": "draft_reply",
          "send-reply": "send_reply", "create-task": "create_task", "label": "label", "forward": "forward",
          "wake-bot": "wake_bot", "note": "note", "post-update": "post_update", "call-webhook": "call_webhook",
          "assign": "assign"}
# CONTRACT §2 Runs: a step is ok, skipped, failed, spend_cap or waiting (a queued mail action, or a turn still held).
STATUSES = {"ok", "skipped", "failed", "spend_cap", "waiting"}
# The trigger field a text condition reads, per kind: the field the kind's input carries its text in. A schedule has no
# input, so its condition is never met (see Limits).
TEXT = {"task": "task.title", "email": "message.subject", "slack": "message.text", "webhook": "body.title",
        "listening": "item.content", "event": "event.data.title", "schedule": "task.title"}
SPEC = {   # condition value -> (field, op, value, min); TEXT stands for the kind's text field
    "is": (TEXT, "is", "urgent", None),
    "is-min": ("d1.bucket", "is", "reply", 0.7),
    "is-not": (TEXT, "is_not", "lunch", None),
    "is-not-min": ("d1.bucket", "is_not", "archive", 0.7),
    "gte": ("d1.urgency", ">=", 3, None),
    "lte": ("d1.urgency", "<=", 3, None),
    "contains": (TEXT, "contains", "urgent", None),
    "matches": (TEXT, "matches", "^urgent", None),
}


# ---------------------------------------------------------------------------------------------- flow pieces
def node(sid, kind, **fields):
    return {"id": sid, "type": kind, "enabled": True, **fields}


def condition_node(name, kind):
    field, op, value, minimum = SPEC[name]
    field = TEXT[kind] if field is TEXT else field
    return {"field": field, "op": op, "value": value, **({"min": minimum} if minimum is not None else {})}


def marker(sid):
    return node(sid, "action", do="note", args={})


def worker_node(kind, sid):
    if kind == "llm-assistant":
        return node(sid, "llm", **{"as": "assistant:dana"}, prompt="Matrix", out=sid)
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


def fork_for(row, cond, never):
    """The paths step for a non-straight shape, and its fork groups (the ids of the branches, one group per fork)."""
    shape = row["shape"]
    if shape in ("two-paths", "four-paths"):
        count = 2 if shape == "two-paths" else 4
        paths = [{"name": f"p{k}", "when": [cond if k == 0 else never],
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
    kind = row["trigger"]
    cond = condition_node(row["condition"], kind)
    never = {"field": TEXT[kind], "op": "is", "value": "never-sent"}   # the paths that must not match
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
        fork, groups = fork_for(row, cond, never)
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


# ---------------------------------------------------------------------------------------------- triggers and input
def text_of(row):
    return "lunch" if row["outcome"] == "no-match" else "urgent"


def event_for(n):
    """A catalog event whose payload carries a title, picked by the combination's number: (name, its example data)."""
    from backend.event_catalog import EVENTS
    named = sorted(name for name, event in EVENTS.items() if "title" in event.example)
    return named[n % len(named)], dict(EVENTS[named[n % len(named)]].example)


def trigger_for(kind, n):
    """The trigger for one combination (CONTRACT §2 trigger types; Slack is a message trigger on slack:dm)."""
    if kind == "email":
        return {"type": "message", "inbox": INBOX}
    if kind == "slack":
        return {"type": "message", "inbox": "slack:dm"}
    if kind == "task":
        return {"type": "task_received", "to": DANA_REF}
    if kind == "schedule":
        return {"type": "schedule", "cron": "0 9 * * *", "tz": "UTC"}
    if kind == "webhook":
        return {"type": "webhook", "id": f"matrix-{n}"}
    if kind == "listening":
        return {"type": "listening", "destination": DESTINATION}
    return {"type": "event", "name": event_for(n)[0]}


def mail_for(n, row):
    return mail_message(f"matrix-{n}", "omar@acme.example", text_of(row), body="Matrix mail.")


def sample_for(kind, n, row, mails):
    """The trigger's output for the run input (CONTRACT §2 Feeding input): message, task, item, event or body. None for
    a schedule, which has no input."""
    text = text_of(row)
    if kind == "email":
        return {"message": mails[n]}
    if kind == "slack":
        return {"message": {"channel": "dm", "from": "omar@acme.example", "text": text, "ts": f"1700000000.{n:06d}"}}
    if kind == "task":
        return {"task": {"title": text, "body": "Matrix task.", "owner": DANA_REF, "requester": CLAUDE_REF,
                         "session": SENDER_SESSION}}
    if kind == "webhook":
        return {"body": {"title": text}}
    if kind == "listening":
        return {"item": {"source": "forum", "native_id": f"matrix-{n}", "url": f"https://forum.acme.example/t/{n}",
                         "author": "omar", "content": text}}
    if kind == "event":
        name, data = event_for(n)
        return {"event": {"name": name, "version": 1, "data": {**data, "title": text}}}
    return None


def label_of(n, row):
    keys = ("trigger", "first", "shape", "worker", "action", "condition", "outcome")
    return f"#{n} " + "/".join(row[k] for k in keys)


def run_combo(org, n, row, mails):
    """Builds one combination as an automation, fires it with its run input, reads back its one run, then switches it
    off so no later combination's actions fire it. Returns the record the checks read. Raises Unmet when a route is not
    registered."""
    kind, outcome = row["trigger"], row["outcome"]
    steps, groups, top, off = build(row, outcome)
    if kind == "webhook":   # the incoming trigger the automation listens on (CONTRACT §2 Webhook trigger)
        made = org.api("post", "/api/v2/triggers", {"name": f"Matrix {n}", "id": f"matrix-{n}"}, wave=W3)
        if made.status >= 300:
            raise Unmet(W3, f"trigger matrix-{n}: {made.status} {made.excerpt()}")
    payload = {"name": f"Matrix {n} · dana", "owner": DANA_REF, "enabled": True, "builtin": False,
               "trigger": trigger_for(kind, n), "steps": steps}
    if outcome == "spend-cap":
        payload["spend_cap"] = {"per_30m": 0.01}
    if "decide" in row["first"]:
        attach_judge(org, judge_for(row, outcome != "no-match"))
    made = org.api("post", "/api/v2/automations", payload, wave=W3)
    record = {"label": label_of(n, row), "saved": 200 <= made.status < 300, "groups": groups, "top": top,
              "outcome": outcome, "disabled": [off] if off else [], "run": None, "runs": 0,
              "sender_session": SENDER_SESSION if kind == "task" else None}
    if not record["saved"]:
        record["label"] += f" (create {made.status})"
        return record
    created = made.body if isinstance(made.body, dict) else {}
    auto = created.get("automation") or created
    facts = {"auto": Reply(made.status, auto, W3)}
    fired = run_now(org, facts, "auto", sample=sample_for(kind, n, row, mails))
    record["fired"] = fired.status
    runs = rows(org.api("get", f"/api/v2/automations/{auto.get('id')}/runs", wave=W3).body)
    record["run"] = runs[0] if len(runs) == 1 else None
    record["runs"] = len(runs)
    try:
        org.api("patch", f"/api/v2/automations/{auto.get('id')}", {"enabled": False}, wave=W3)
    except Unmet:
        pass   # tidying only: the record is already read
    return record


# ---------------------------------------------------------------------------------------------- invariants
def row_of(run, sid):
    return [s for s in run.get("steps") or [] if s.get("id") == sid]


def no_run(r):
    if not r["saved"]:
        return "not saved"
    return f"{r['runs']} run(s) logged for one input, want 1 (run answered {r.get('fired')})"


def items_of(run):
    """The items a run's steps ran for: a `find` gives each item its own steps (CONTRACT §2 find); otherwise just None."""
    return {s.get("item") for s in run.get("steps") or []}


def one_path(r):
    if r["run"] is None:
        return no_run(r)
    for group in r["groups"]:
        for item in items_of(r["run"]):
            won = [sid for sid in group
                   if any(s.get("status") == "ok" and s.get("item") == item for s in row_of(r["run"], sid))]
            if len(won) > 1:
                return f"{won} all ran in one fork" + (f" for item {item}" if item is not None else "")
    return ""


def stop_index(run, ids):
    """Where the run's top-level thread stopped in `ids`: its first failed step, or an llm step whose turn is still held
    (the steps after it run when the turn answers). None when every top-level step was reached."""
    for i, sid in enumerate(ids):
        for s in row_of(run, sid):
            if s.get("status") == "failed" or (s.get("type") == "llm" and s.get("status") == "waiting"):
                return i
    return None


def top_logged(r):
    """Every top-level step the run reached is logged with a status; the steps after where it stopped are not reached
    yet and have no record."""
    if r["run"] is None:
        return no_run(r)
    ids = r["top"]
    stop = stop_index(r["run"], ids)
    reached = ids if stop is None else ids[:stop + 1]
    unreached = [] if stop is None else ids[stop + 1:]
    missing = [sid for sid in reached if not row_of(r["run"], sid)]
    logged_after = [sid for sid in unreached if row_of(r["run"], sid)]
    bad = [s.get("id") for s in r["run"].get("steps") or [] if s.get("id") in ids and s.get("status") not in STATUSES]
    if missing or logged_after or bad:
        return f"not logged {missing}, logged after the run stopped {logged_after}, bad status {bad}"
    return ""


def failure_ends_run(r):
    """A step-fails row makes its Decide fail, and a failed step ends the run as failed (CONTRACT §2 Runs)."""
    if r["outcome"] != "step-fails":
        return ""
    if r["run"] is None:
        return no_run(r)
    return "" if r["run"].get("status") == "failed" else f"run status {r['run'].get('status')!r}, want 'failed'"


def action_once(r):
    if r["run"] is None:
        return no_run(r)
    ran = [(s.get("id"), s.get("item")) for s in r["run"].get("steps") or []
           if str(s.get("id", "")).startswith("act") and s.get("status") == "ok"]
    twice = sorted({key for key in ran if ran.count(key) > 1}, key=str)   # (step id, item): once per item
    return f"action ran more than once (step, item): {twice}" if twice else ""


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


def turn_origin(r):
    """Every LLM or Bot turn step that ran names its turn (CONTRACT §2 Turn origin: {bot, task, session}), and that
    turn is not in the sender's session."""
    if r["run"] is None:
        return no_run(r)
    for step in r["run"].get("steps") or []:
        worker = step.get("type") in WORKERS or str(step.get("id", "")).startswith("w")
        if not worker or step.get("status") != "ok":
            continue
        turn = turn_of(step)
        if not turn or not turn.get("bot") or not turn.get("task") or "session" not in turn:
            return f"{step.get('id')} ran with no turn {{bot, task, session}}: {turn}"
        if r["sender_session"] and turn.get("session") == r["sender_session"]:
            return f"{step.get('id')} ran in the sender's session {turn.get('session')!r}"
    return ""


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
        head = f"{len(done) - len(bad)} of {len(done)} clean, {len(stuck)} not built"
        if bad:
            return False, f"{head}; first: {bad[0][0]}: {bad[0][1]} ({len(bad)} failing)"
        return True, head
    return check


def all_saved(f):
    done, stuck = gate(f)
    refused = [r["label"] for r in done if not r["saved"]]
    return not refused, f"{len(done) - len(refused)} of {len(done)} saved; {len(stuck)} not built; refused: {refused[:3]}"


def probes_refused(f):
    """Two flows over the limits (11 paths, 4 nesting levels) are refused (422) and not listed."""
    setup(f, "listing")
    ok_11, text_11 = replied(f, "probe_11", 422)
    ok_deep, text_deep = replied(f, "probe_deep", 422)
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
    return {"name": name, "owner": DANA_REF, "enabled": True, "builtin": False,
            "trigger": {"type": "schedule", "cron": "0 9 * * *", "tz": "UTC"}, "steps": steps}


def matrix_scenario(seed):
    rows_ = plan(seed)

    def steps(org, f):
        # Before any automation exists: builder-claude's live session (the task sender's), the listening destination,
        # and every email combination's mail, published once through the mail sync.
        org.step(f, "warm", work, org, CLAUDE_ID, "Matrix warm-up")
        org.step(f, "destination", org.api, "put", f"/api/v2/listening/destinations/{DESTINATION}",
                 {"category": "lead", "threshold": 0.7, "receiver": LEAD_ID, "what": "Matrix leads"}, wave=W3)
        mails = {n: mail_for(n, row) for n, row in enumerate(rows_) if row["trigger"] == "email"}
        org.step(f, "mail", publish_mail, org, INBOX, list(mails.values()))
        for n, row in enumerate(rows_):
            org.step(f, f"c{n}", run_combo, org, n, row, mails)
        org.step(f, "probe_11", org.api, "post", "/api/v2/automations",
                 probe_payload("Matrix probe 11", wide(11)), wave=W3)
        org.step(f, "probe_deep", org.api, "post", "/api/v2/automations",
                 probe_payload("Matrix probe deep", nested(4)), wave=W3)
        org.step(f, "listing", org.api, "get", "/api/v2/automations", wave=W3)

    checks = [
        Check("every dimension value is in at least one combination", W3, lambda f: plan_values(rows_)),
        Check("every feasible pair is in at least one combination", W3, lambda f: pairs_covered(rows_)),
        Check("the combination count is at least the all-pairs floor", W3, lambda f: combo_floor(rows_)),
        Check("the inputs are in place: the email combinations' mail is published", W3,
              lambda f: replied(f, "mail", 200, 201)),
        Check("every valid combination is saved as an automation", W3, all_saved),
        Check("exactly one path runs per fork", W3, across(one_path)),
        Check("every top-level step is logged with a status", W3, across(top_logged)),
        Check("a step that fails ends the run as failed", W3, across(failure_ends_run)),
        Check("each action runs at most once per item", W3, across(action_once)),
        Check("costs add up: the run's cost is the sum of its steps", W3, across(costs_add)),
        Check("a disabled step never runs", W3, across(disabled_silent)),
        Check("every LLM or Bot turn step names its turn, never in the sender's session", W3, across(turn_origin)),
        Check("a refused flow is never saved (11 paths, 4 nesting levels: 422)", W3, probes_refused),
    ]
    return Scenario(0, f"matrix-seed-{seed}",
                    f"All-pairs coverage matrix, seed {seed}: {len(rows_)} combinations", steps, checks)
