"""Engine (PLAN §7, scenarios 22-31): schedule and Find, bot turns, switched-off steps, paths in order and their limits,
the run log, versions, built-ins, a time zone across DST, and webhook triggers. Every automation is a real POST to
/api/v2/automations and every check reads the run the engine wrote. A check that needs a run waits on its automation
(wave 3), so an empty listing never passes."""
import datetime as dt
import json
from zoneinfo import ZoneInfo

from ..fakes import ReplayJudge, attach_judge, hook, stripe_sig
from ..harness import (CHRIS, CHRIS_ID, CHRIS_REF, CLAUDE, CLAUDE_ID, CLAUDE_REF, LEAD, W3, Check, Reply, Scenario, Unmet,
                       automation, auto_id, body, edit_auto, got, replied, rows, run_now, send, setup, untestable)

SCHEDULE = {"type": "schedule", "cron": "0 9 * * *", "tz": "UTC"}
BUCKET = {"bucket": {"type": "choice", "instructions": "Where does it go?",
                     "criteria": {"reply": "answer it", "archive": "noise"}}}
NY, UTC = ZoneInfo("America/New_York"), dt.timezone.utc
HOOK = {"type": "webhook", "id": "hook-31", "secret": "s3cret-31"}
PAYLOAD = {"order": 42}
GOOD_PATH, BAD_PATH = "/api/v2/hooks/hook-31/s3cret-31", "/api/v2/hooks/hook-31/wrong-secret"


# ---------------------------------------------------------------------------------------------- shared steps
def note(sid, text, enabled=True):
    return {"id": sid, "type": "action", "enabled": enabled, "do": "note", "args": {"text": text}}


def cond(field, op, value, **extra):
    return {"field": field, "op": op, "value": value, **extra}


def runs_of(org, facts, key="auto"):
    return org.api("get", f"/api/v2/automations/{auto_id(facts, key)}/runs", wave=W3)


def versions_of(org, facts, key="auto"):
    return org.api("get", f"/api/v2/automations/{auto_id(facts, key)}/versions", wave=W3)


def current(org, facts, key="auto"):
    return org.api("get", f"/api/v2/automations/{auto_id(facts, key)}", wave=W3)


def restore(org, facts, n, key="auto"):
    return org.api("post", f"/api/v2/automations/{auto_id(facts, key)}/versions/{n}/restore", {}, wave=W3)


def listing(org):
    return org.api("get", "/api/v2/automations", wave=W3)


def until(org, when):
    """Moves the fake clock to `when` in one jump, then lets the scheduler run what is due. The clock is shifted directly:
    World.advance steps 50 seconds at a time with a heartbeat each, which is ~53,000 steps for 31 days."""
    org.clock.shift((when - org.now()).total_seconds())
    org.scheduler_pass()
    return when


def incoming(org, path, payload, headers=None):
    """An outside delivery to an incoming address: no bearer token, the secret is in the path (backend/triggers.py)."""
    if not org._registered("post", path):
        raise Unmet(W3, f"no route POST {path}")
    response = hook(org.client, path, json.dumps(payload).encode(), headers)
    try:
        data = response.json()
    except ValueError:
        data = response.text
    reply = Reply(response.status_code, data, W3)
    org.log.append(f"POST {path} (incoming) -> {reply.status} {reply.excerpt()}")
    return reply


def signed_good(org):
    """The good secret, with a Stripe-style signature made from it: accepted whether or not the scheme is checked."""
    raw = json.dumps(PAYLOAD).encode()
    return incoming(org, GOOD_PATH, PAYLOAD, {"Stripe-Signature": stripe_sig("s3cret-31", raw, 1700000000)})


# ---------------------------------------------------------------------------------------------- reading runs
def fresh(f, before, after):
    """The runs the `after` listing has that the `before` listing did not."""
    seen = {r.get("id") for r in rows(body(f, before))}
    return [r for r in rows(body(f, after)) if r.get("id") not in seen]


def step_row(run, sid):
    return next((s for s in run.get("steps", []) if s.get("id") == sid), None)


def ran_ok(run, sid):
    row = step_row(run, sid)
    return bool(row) and row.get("status") == "ok"


def started(run):
    """The run's start as an aware time; a naive one is read as UTC."""
    when = dt.datetime.fromisoformat(str(run["started"]).replace("Z", "+00:00"))
    return when if when.tzinfo else when.replace(tzinfo=UTC)


def unwrap(data):
    return data.get("automation", data) if isinstance(data, dict) else {}


def branch(f, before, after, ran_ids, held_ids):
    """Exactly one run in the window; every id in `ran_ids` ran (ok) and none in `held_ids` did. The branches' step ids
    are the markers, so this reads which path ran without naming the paths output field (CONTRACT: "the path taken")."""
    setup(f, "auto", before, after)
    runs = fresh(f, before, after)
    if len(runs) != 1:
        return False, f"{len(runs)} new run(s), want 1"
    ran = [sid for sid in ran_ids if ran_ok(runs[0], sid)]
    extra = [sid for sid in held_ids if ran_ok(runs[0], sid)]
    return ran == list(ran_ids) and not extra, f"ran {ran}, also ran {extra}"


# ---------------------------------------------------------------------------------------------- 22 find
def s22_steps(org, f):
    org.step(f, "auto", automation, org, "Task digest · chris", CHRIS_REF, trigger=SCHEDULE, steps=[
        {"id": "look", "type": "find", "enabled": True, "source": "tasks", "query": "Scenario item",
         "since": "last_run", "limit": 10},
        note("each", "seen")])
    org.step(f, "runs0", runs_of, org, f)
    for n in (1, 2, 3):
        org.step(f, f"item{n}", send, org, CLAUDE, CHRIS_ID, f"Scenario item {n}")
    org.step(f, "run1", run_now, org, f, "auto")
    org.step(f, "runs1", runs_of, org, f)
    org.step(f, "run2", run_now, org, f, "auto")
    org.step(f, "runs2", runs_of, org, f)


def found_three(f):
    setup(f, "auto", "runs0", "runs1")
    runs = fresh(f, "runs0", "runs1")
    if len(runs) != 1:
        return False, f"{len(runs)} new run(s), want 1"
    items = ((step_row(runs[0], "look") or {}).get("outputs") or {}).get("items") or []
    return len(items) == 3, f"{len(items)} item(s) found, want 3"


def once_per_item(f):
    setup(f, "auto", "runs0", "runs1")
    runs = fresh(f, "runs0", "runs1")
    if len(runs) != 1:
        return False, f"{len(runs)} new run(s), want 1"
    each = [s for s in runs[0].get("steps", []) if s.get("id") == "each"]
    return len(each) == 3, f"{len(each)} row(s) of the per-item step, want 3"


def empty_second(f):
    setup(f, "auto", "runs1", "runs2")
    runs = fresh(f, "runs1", "runs2")
    if len(runs) != 1:
        return False, f"{len(runs)} new run(s), want 1"
    return runs[0].get("status") == "empty", f"status {runs[0].get('status')}, want empty"


# ---------------------------------------------------------------------------------------------- 23 bot turn
def s23_steps(org, f):
    org.step(f, "auto", automation, org, "Build check · builder-claude", CLAUDE_REF, trigger=SCHEDULE, steps=[
        {"id": "act", "type": "bot_turn", "enabled": True, "bot": CLAUDE_ID, "prompt": "Check the build"}])
    org.step(f, "run", run_now, org, f, "auto")
    org.step(f, "turn1", org.turn, CLAUDE_ID)
    org.step(f, "turn2", org.turn, CLAUDE_ID)


def turn_claimed(f):
    setup(f, "auto", "run")
    turn = got(f, "turn1")
    return bool(turn), "one turn claimed on builder-claude" if turn else "no turn claimed for the run"


def second_held(f):
    setup(f, "auto", "run")
    if not got(f, "turn1"):
        return False, "no first turn to compare with"
    return got(f, "turn2") is None, "the second turn is held: none claimed"


# ---------------------------------------------------------------------------------------------- 24 switched off
def s24_steps(org, f):
    org.step(f, "judge", attach_judge, org, ReplayJudge())
    org.step(f, "auto", automation, org, "Triage · chris", CHRIS_REF, trigger=SCHEDULE, steps=[
        {"id": "gate", "type": "filter", "enabled": True, "rules": []},
        {"id": "rank", "type": "decide", "enabled": False, "questions": BUCKET, "level": "low", "out": "d1"},
        note("note", "ran")])
    org.step(f, "run", run_now, org, f, "auto")
    org.step(f, "runs", runs_of, org, f)


def off_logged(f):
    setup(f, "auto", "run", "runs")
    runs = rows(body(f, "runs"))
    if not runs:
        return False, "no run logged"
    row = step_row(runs[0], "rank")
    ok = bool(row) and row.get("status") == "skipped" and not row.get("outputs")
    return ok, f"rank logged {(row or {}).get('status')}, want skipped with no outputs"


def judge_untouched(f):
    setup(f, "auto", "run", "runs")
    if not rows(body(f, "runs")):
        return False, "no run logged"
    calls = got(f, "judge").calls
    return calls == [], f"{len(calls)} judge call(s), want 0"


def enabled_ran(f):
    setup(f, "auto", "run", "runs")
    runs = rows(body(f, "runs"))
    if not runs:
        return False, "no run logged"
    row = step_row(runs[0], "note")
    return bool(row) and row.get("status") == "ok", f"note {(row or {}).get('status')}"


# ---------------------------------------------------------------------------------------------- 25 paths
def s25_steps(org, f):
    org.step(f, "auto", automation, org, "Urgent first · chris", CHRIS_REF,
             trigger={"type": "task_received", "to": CHRIS_REF}, steps=[
                 {"id": "fork", "type": "paths", "enabled": True,
                  "paths": [{"name": "urgent", "when": [cond("task.title", "contains", "urgent")],
                             "steps": [note("u", "urgent")]},
                            {"name": "prod", "when": [cond("task.title", "contains", "prod")],
                             "steps": [note("p", "prod")]}],
                  "otherwise": {"steps": [note("o", "otherwise")]}}])
    org.step(f, "runs0", runs_of, org, f)
    org.step(f, "both", send, org, CLAUDE, CHRIS_ID, "urgent: prod down")
    org.step(f, "runs1", runs_of, org, f)
    org.step(f, "none", send, org, CLAUDE, CHRIS_ID, "lunch?")
    org.step(f, "runs2", runs_of, org, f)


# ---------------------------------------------------------------------------------------------- 26 limits
def wide(n):
    """One paths step with n branches (CONTRACT: at most 10 per fork)."""
    return [{"id": "fork", "type": "paths", "enabled": True,
             "paths": [{"name": f"p{i}", "when": [cond("task.title", "contains", str(i))], "steps": [note(f"n{i}", "x")]}
                       for i in range(n)],
             "otherwise": {"steps": []}}]


def nested(depth):
    """`depth` paths forks, each inside the branch of the one before (CONTRACT: at most 3 levels)."""
    steps = [note("leaf", "deep")]
    for level in range(depth):
        steps = [{"id": f"fork{level}", "type": "paths", "enabled": True,
                  "paths": [{"name": "in", "when": [cond("task.title", "contains", "x")], "steps": steps}],
                  "otherwise": {"steps": []}}]
    return steps


def s26_steps(org, f):
    org.step(f, "ten", automation, org, "Ten paths", CHRIS_REF, steps=wide(10))
    org.step(f, "eleven", automation, org, "Eleven paths", CHRIS_REF, steps=wide(11))
    org.step(f, "three", automation, org, "Three forks", CHRIS_REF, steps=nested(3))
    org.step(f, "deep", automation, org, "Four forks", CHRIS_REF, steps=nested(4))
    org.step(f, "listing", listing, org)


def not_listed(f):
    setup(f, "listing", "ten", "three")   # the accepted control flows must be listed, or the check has nothing to show
    names = {r.get("name") for r in rows(body(f, "listing"))}
    gone = {"Eleven paths", "Four forks"} & names
    return not gone and {"Ten paths", "Three forks"} <= names, f"listed: {sorted(n for n in names if n)}"


# ---------------------------------------------------------------------------------------------- 27 run log
def s27_steps(org, f):
    org.step(f, "auto", automation, org, "Task log · chris", CHRIS_REF,
             trigger={"type": "task_received", "to": CHRIS_REF}, steps=[note("kept", "kept")])
    org.step(f, "runs0", runs_of, org, f)
    org.step(f, "hit", send, org, CLAUDE, CHRIS_ID, "Weekly newsletter")
    org.step(f, "runs1", runs_of, org, f)
    org.step(f, "old", until, org, org.now() + dt.timedelta(days=31))
    org.step(f, "runs2", runs_of, org, f)


def step_rows_carry_cost(f):
    setup(f, "auto", "runs0", "runs1")
    runs = fresh(f, "runs0", "runs1")
    if len(runs) != 1:
        return False, f"{len(runs)} new run(s) for the matching task, want 1"
    steps = runs[0].get("steps") or []
    return bool(steps) and all("status" in s and "cost" in s for s in steps), f"{len(steps)} step row(s)"


def pruned_after_30(f):
    setup(f, "auto", "runs0", "runs1", "runs2")
    got(f, "old")   # the clock has moved 31 days
    hit = fresh(f, "runs0", "runs1")
    if len(hit) != 1:
        return False, "the matching task made no run to check"
    after = next((r for r in rows(body(f, "runs2")) if r.get("id") == hit[0].get("id")), None)
    if after is None:
        return False, "the run row itself was pruned"
    left = after.get("steps") or []
    return bool(hit[0].get("steps")) and not left, f"{len(left)} step row(s) left after 31 days"


# ---------------------------------------------------------------------------------------------- 28 versions
def s28_steps(org, f):
    org.step(f, "auto", automation, org, "Versions · chris", CHRIS_REF, steps=[note("one", "one")])
    org.step(f, "edit", edit_auto, org, f, "auto", CHRIS, steps=[note("two", "two")])
    org.step(f, "versions", versions_of, org, f)
    org.step(f, "restore", restore, org, f, 1)
    org.step(f, "after", current, org, f)
    org.step(f, "versions2", versions_of, org, f)


def versions_recorded(f):
    setup(f, "auto", "edit", "versions")
    vs = rows(body(f, "versions"))
    ns = sorted(v.get("n") for v in vs)
    ok = ns[:2] == [1, 2] and all(v.get("actor") and v.get("at") for v in vs[:2])
    return ok, f"versions {ns}, each with actor and time"


def restored(f):
    setup(f, "restore", "after", "versions2")
    steps = unwrap(body(f, "after")).get("steps") or []
    text = (steps[0].get("args") or {}).get("text") if steps else None
    count = len(rows(body(f, "versions2")))
    return text == "one" and count == 3, f"flow says {text!r}, {count} version(s), want 'one' and 3"


# ---------------------------------------------------------------------------------------------- 29 built-in
def s29_steps(org, f):
    # CONTRACT names no create path for built-ins (gap g): this posts builtin true to the automation route.
    org.step(f, "builtin", org.api, "post", "/api/v2/automations", {
        "name": "Inbox · chris", "owner": CHRIS_REF, "enabled": True, "builtin": True, "trigger": SCHEDULE,
        "steps": [{"id": "gate", "type": "filter", "enabled": True, "rules": []}]}, wave=W3)
    org.step(f, "lead_pause", edit_auto, org, f, "builtin", LEAD, enabled=False)
    org.step(f, "chris_pause", edit_auto, org, f, "builtin", CHRIS, enabled=False)
    org.step(f, "delete", lambda: org.api("delete", f"/api/v2/automations/{auto_id(f, 'builtin')}", wave=W3))


def chris_pause_warns(f):
    setup(f, "builtin", "chris_pause")
    reply = got(f, "chris_pause")
    warned = "warn" in json.dumps(reply.body, default=str).lower()   # the warning's field is not named
    return reply.status == 200 and warned, f"{reply.status}, warning {warned}"


# ---------------------------------------------------------------------------------------------- 30 DST
# Oct 31 is EDT, Nov 1 is the change (02:00 EDT back to EST), Nov 2 is EST: 09:00 New York is 13:00 UTC, then 14:00 UTC.
DAYS = [dt.datetime(2026, 10, 30, 9, tzinfo=NY), dt.datetime(2026, 10, 31, 9, tzinfo=NY),
        dt.datetime(2026, 11, 1, 9, tzinfo=NY), dt.datetime(2026, 11, 2, 9, tzinfo=NY)]


def s30_steps(org, f):
    org.step(f, "auto", automation, org, "Daily digest · chris", CHRIS_REF,
             trigger={"type": "schedule", "cron": "0 9 * * *", "tz": "America/New_York"}, steps=[note("d", "digest")])
    for n, when in enumerate(DAYS):   # one day at a time, so the scheduler fires each day in turn
        org.step(f, f"to{n}", until, org, when)
        org.step(f, f"runs{n}", runs_of, org, f)


def fired_on(f, before, after, local_day, utc_hour):
    """Exactly one run started in the window, at 09:00 New York on `local_day`, which is `utc_hour` UTC."""
    setup(f, "auto", before, after)
    new = fresh(f, before, after)
    starts = [started(r) for r in new]
    hits = [t for t in starts if t.astimezone(NY).date().isoformat() == local_day
            and t.astimezone(NY).hour == 9 and t.astimezone(UTC).hour == utc_hour]
    return len(new) == 1 and len(hits) == 1, \
        f"started {[t.isoformat() for t in starts]}, want 09:00 New York on {local_day} ({utc_hour}:00 UTC)"


def one_a_day(f):
    setup(f, "auto", "runs0", "runs3")
    new = fresh(f, "runs0", "runs3")
    days = sorted(started(r).astimezone(NY).date().isoformat() for r in new)
    want = ["2026-10-31", "2026-11-01", "2026-11-02"]
    return days == want, f"runs on {days}, want one each on {want}"


# ---------------------------------------------------------------------------------------------- 31 webhooks
def s31_steps(org, f):
    org.step(f, "auto", automation, org, "Failed payments · chris", CHRIS_REF, trigger=HOOK, steps=[note("h", "hooked")])
    org.step(f, "runs0", runs_of, org, f)
    org.step(f, "bad", incoming, org, BAD_PATH, PAYLOAD)
    org.step(f, "runs_bad", runs_of, org, f)
    org.step(f, "good", signed_good, org)
    org.step(f, "runs_good", runs_of, org, f)


def bad_refused(f):
    ok, text = replied(f, "bad", 401, 403, 404, needs=("auto", "runs0"))
    if not ok:
        return ok, text
    fired = fresh(f, "runs0", "runs_bad")
    return not fired, f"{text}; {len(fired)} run(s) started"


def good_runs(f):
    ok, text = replied(f, "good", 200, 201, 202, needs=("auto", "runs0"))
    if not ok:
        return ok, text
    fired = fresh(f, "runs0", "runs_good")
    return len(fired) == 1, f"{text}; {len(fired)} run(s), want 1"


SCENARIOS = [
    Scenario(22, "engine-find", "Schedule + Find: items since the last run, steps once per item, empty run logged",
             s22_steps, [
                 Check("find pulls the three tasks sent since the last run", W3, found_three),
                 Check("the per-item step runs once for each item", W3, once_per_item),
                 Check("with nothing new, the second run is logged empty", W3, empty_second),
             ]),
    Scenario(23, "engine-bot-turn", "Schedule + Bot turn: one turn on the chosen bot with its prompt", s23_steps, [
        Check("the run claims one turn on builder-claude", W3, turn_claimed),
        Check("the claimed turn carries the prompt and builder-claude's tools", W3,
              untestable("CONTRACT names no field on a claimed job that carries a bot_turn's prompt or tool set")),
        Check("a second turn for the same run is held", W3, second_held),
    ]),
    Scenario(24, "engine-step-off", "Step switched off: skipped and logged; its model is never called", s24_steps, [
        Check("the switched-off decide is logged as skipped, with no outputs", W3, off_logged),
        Check("the judge is never called for it", W3, judge_untouched),
        Check("the enabled steps still run", W3, enabled_ran),
    ]),
    Scenario(25, "engine-paths-order", "Paths run in order: the first match wins; otherwise when none match", s25_steps, [
        Check("two paths match: the first (urgent) runs", W3, lambda f: branch(f, "runs0", "runs1", ["u"], [])),
        Check("the second matching path (prod) does not run", W3,
              lambda f: branch(f, "runs0", "runs1", ["u"], ["p"])),
        Check("no path matches: the otherwise path runs", W3,
              lambda f: branch(f, "runs1", "runs2", ["o"], ["u", "p"])),
    ]),
    Scenario(26, "engine-path-limits", "11th path or 4th nesting level refused on save", s26_steps, [
        Check("ten paths (the limit) are saved", W3, lambda f: replied(f, "ten", 200, 201)),
        Check("an 11th path is refused on save (400, 409 or 422)", W3,
              lambda f: replied(f, "eleven", 400, 409, 422, needs=("ten",))),
        Check("three nesting levels (the limit) are saved", W3, lambda f: replied(f, "three", 200, 201)),
        Check("a fourth nesting level is refused on save", W3,
              lambda f: replied(f, "deep", 400, 409, 422, needs=("three",))),
        Check("the refused flows are not listed; the accepted ones are", W3, not_listed),
    ]),
    Scenario(27, "engine-run-log", "Run log: each step's result and cost; dropped runs counted only; pruned after 30 days",
             s27_steps, [
                 Check("a task makes one run whose steps carry a status and a cost", W3, step_rows_carry_cost),
                 Check("a trigger the filters drop writes no run row", W3,
                       untestable("CONTRACT drops a trigger through its filters, named only on message triggers")),
                 Check("the daily count for dropped triggers goes up",
                       W3, untestable("CONTRACT names no read for the daily count of filter-dropped triggers")),
                 Check("after 31 days the step detail is pruned and the run row stays", W3, pruned_after_30),
             ]),
    Scenario(28, "engine-versions", "Each save makes a version; restore brings back the old flow", s28_steps, [
        Check("two saves make versions 1 and 2, with actor and time", W3, versions_recorded),
        Check("restore brings the first flow back as a new version", W3, restored),
    ]),
    Scenario(29, "engine-builtin", "Built-in automation: paused by the top only, with a warning; delete refused",
             s29_steps, [
                 Check("a lead cannot pause the built-in (403)", W3, lambda f: replied(f, "lead_pause", 403, needs=("builtin",))),
                 Check("Chris pauses it and gets a warning", W3, chris_pause_warns),
                 Check("delete is refused for everyone (403 or 409)", W3,
                       lambda f: replied(f, "delete", 403, 409, needs=("builtin",))),
             ]),
    Scenario(30, "engine-dst", "Schedule in a time zone fires at local time across the DST change", s30_steps, [
        Check("fires at 09:00 New York on Oct 31 (13:00 UTC, EDT)", W3,
              lambda f: fired_on(f, "runs0", "runs1", "2026-10-31", 13)),
        Check("fires at 09:00 New York on Nov 2 (14:00 UTC, EST)", W3,
              lambda f: fired_on(f, "runs2", "runs3", "2026-11-02", 14)),
        Check("one run each local day across the change, Nov 1 included", W3, one_a_day),
    ]),
    Scenario(31, "engine-webhook", "Webhook trigger: a bad secret refused, the good one runs, the rate limit holds",
             s31_steps, [
                 Check("a bad secret is refused (401, 403 or 404) and starts no run", W3, bad_refused),
                 Check("the good secret starts one run", W3, good_runs),
                 Check("a forged Stripe-style signature under the good secret is refused", W3,
                       untestable("CONTRACT names no signature scheme for webhook triggers, only the path secret")),
                 Check("a burst over the rate limit is held", W3,
                       untestable("CONTRACT names no per-trigger rate limit or the number")),
             ]),
]
