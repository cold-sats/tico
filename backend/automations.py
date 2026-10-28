"""Automations (CONTRACT §2): saved flows, their versions and runs, who may change them, and how a trigger runs one.

Dormant unless the team turned the redesign on (backend/redesign.py): the routes answer 404 and every hook returns.

A trigger never runs a flow inside its own write. `fire` checks the trigger's filters there (a run they drop only
counts toward the day, `automation_daily`) and queues a run; a doorbell after the commit has the request that caused
it, or the scheduler's next tick, `drain` the queue. Draining claims one run at a time and hands its flow to the pure
executor (backend/automation_engine.py) with `HubServices`, whose judge calls and actions each take their own short
transaction. A run that waits (an llm turn, a batch time) is saved with its threads; the turn's end
(`turn_done`) or the tick puts it back in the queue. A run claimed but never saved (the server stopped) is failed by
the tick, never run twice.

Mail actions are carried out by the computer that reads the mailbox: it claims them (a lease of MAIL_LEASE_MINUTES,
MAIL_TRIES claims at most) and reports each result; their step and run wait until then (`settle_mail`).

The run state keeps every step's outputs for 30 days; after that `prune` keeps the status, cost and times only.
"""
import asyncio
import contextvars
import json
import threading
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from pydantic import Field

from . import automation_actions as A
from . import automation_engine as E
from . import automation_flow as F
from . import people as P
from .models import Contract
from . import audit_log, redesign
from .store import H, Problem

SCHEMA = (
    "CREATE TABLE IF NOT EXISTS automations(id TEXT PRIMARY KEY, name TEXT NOT NULL, owner TEXT NOT NULL, "
    "grp TEXT, trigger_type TEXT NOT NULL, enabled INTEGER NOT NULL, builtin INTEGER NOT NULL DEFAULT 0, "
    "flow_json TEXT NOT NULL, version INTEGER NOT NULL, created TEXT NOT NULL, created_by TEXT NOT NULL, "
    "updated TEXT NOT NULL, deleted_at TEXT, next_due TEXT, found_since TEXT)",
    "CREATE INDEX IF NOT EXISTS automations_trigger ON automations(trigger_type, enabled) WHERE deleted_at IS NULL",
    "CREATE TABLE IF NOT EXISTS automation_versions(automation_id TEXT NOT NULL, n INTEGER NOT NULL, actor TEXT NOT NULL, "
    "at TEXT NOT NULL, flow_json TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'active', summary TEXT, "
    "PRIMARY KEY(automation_id, n))",
    "CREATE TABLE IF NOT EXISTS automation_runs(id TEXT PRIMARY KEY, automation_id TEXT NOT NULL, version INTEGER NOT NULL, "
    "trigger_ref TEXT NOT NULL DEFAULT '', started TEXT NOT NULL, finished TEXT, status TEXT NOT NULL, "
    "cost REAL NOT NULL DEFAULT 0, state_json TEXT, claimed_at TEXT, wake_at TEXT, chain_json TEXT NOT NULL DEFAULT '[]')",
    "CREATE INDEX IF NOT EXISTS automation_runs_of ON automation_runs(automation_id, started)",
    "CREATE INDEX IF NOT EXISTS automation_runs_queue ON automation_runs(status, started)",
    "CREATE TABLE IF NOT EXISTS automation_daily(automation_id TEXT NOT NULL, day TEXT NOT NULL, "
    "runs INTEGER NOT NULL DEFAULT 0, dropped INTEGER NOT NULL DEFAULT 0, PRIMARY KEY(automation_id, day))",
    "CREATE TABLE IF NOT EXISTS automation_mail_actions(id TEXT PRIMARY KEY, automation_id TEXT NOT NULL, run_id TEXT, "
    "mailbox TEXT NOT NULL, msg_id TEXT NOT NULL, action TEXT NOT NULL, args_json TEXT NOT NULL, state TEXT NOT NULL, "
    "created TEXT NOT NULL, claimed_at TEXT, claimed_by TEXT, result_json TEXT, attempts INTEGER NOT NULL DEFAULT 0)",
    "CREATE INDEX IF NOT EXISTS automation_mail_queue ON automation_mail_actions(mailbox, state, created)",
    # An inbox's send switch (on unless a row says off): off, send_reply saves a draft instead.
    "CREATE TABLE IF NOT EXISTS automation_inboxes(inbox TEXT PRIMARY KEY, send INTEGER NOT NULL, updated TEXT NOT NULL, "
    "updated_by TEXT NOT NULL)",
)
KEEP_DAYS = 30           # step detail; the daily counts and the run rows stay
TURN_WAIT_DAYS = 1
STALE_MINUTES = 15       # a claimed run not saved by then was cut off: failed, never run twice
MAX_CHAIN = 3            # automations started by automations: at most this deep, never the same one twice
LIST_BYTES = 262_144
RUN_BYTES = 524_288
VALUES_BYTES = 60_000    # what a judge call is shown of a run's values
MAIL_LEASE_MINUTES = 5   # a claimed mail action not reported by then goes back to the queue
MAIL_TRIES = 3           # claims a mail action gets before it fails
HELPER = "bot:automations-bot"   # the Automations Bot: sees every automation, changes none, proposes versions
VERSIONED = ("trigger", "steps", "batch")   # what the automation does; a change here is a new version
# The automations a write in this context comes from: their own actions never start them again.
CHAIN = contextvars.ContextVar("automation_chain", default=())
_BELL = threading.Event()


def ensure(c):
    for statement in SCHEMA:
        c.execute(statement)


def _require_on(c):
    if not redesign.on(c):
        raise Problem("not_found", "Not found", 404)


def _via(who):
    """Who acted for the actor, for the audit row: the Assistant, or a personal token's assistant."""
    return who.via or (f"token:{who.token_label}" if who.via_token and who.token_label else None)


# ---------------------------------------------------------------------------------------------------- the rows
def _row(c, aid):
    row = c.execute("SELECT * FROM automations WHERE id=? AND deleted_at IS NULL", (aid,)).fetchone()
    return dict(row) if row else None


def flow_of(row):
    return json.loads(row["flow_json"])


def view(c, row, who=None, detail=False):
    """An automation as its readers get it: `can_edit` for `who`, and with `detail` each Decide step that names a set
    carries that set's questions (read-only: a write sends `set` or `questions`, never both)."""
    flow = flow_of(row)
    if detail:
        flow["steps"] = _with_questions(flow["steps"])
    last = c.execute("SELECT id, status, started, finished FROM automation_runs WHERE automation_id=? "
                     "ORDER BY started DESC LIMIT 1", (row["id"],)).fetchone()
    out = {"id": row["id"], **flow, "version": row["version"], "created": row["created"],
           "created_by": row["created_by"], "updated": row["updated"], "last_run": dict(last) if last else None}
    if detail:
        today = c.execute("SELECT runs, dropped FROM automation_daily WHERE automation_id=? AND day=?",
                          (row["id"], H.now()[:10])).fetchone()
        out["counts"] = {"today": {"runs": today["runs"] if today else 0, "dropped": today["dropped"] if today else 0}}
        if flow["trigger"]["type"] == "schedule":
            out["next_run"] = row["next_due"] or _iso(_due(flow["trigger"], datetime.now(timezone.utc)))
    if who is not None:
        out["can_edit"] = may_change(c, who, flow)
    return out


def _with_questions(steps):
    out = []
    for step in steps:
        step = dict(step)
        if step.get("type") == "decide" and step.get("set"):
            try:
                step["questions"] = F.question_set(step["set"])
            except F.Invalid:
                pass   # the set was removed since the save: the step shows its name only
        if step.get("type") == "paths":
            step["paths"] = [{**path, "steps": _with_questions(path.get("steps") or [])} for path in step["paths"]]
            if step.get("otherwise") is not None:
                step["otherwise"] = {"steps": _with_questions(step["otherwise"].get("steps") or [])}
        out.append(step)
    return out


def _versioned(flow):
    return {key: flow[key] for key in VERSIONED if flow.get(key) is not None}


def _next_n(c, aid):
    """Versions are numbered in the order they were written, proposals included, so a proposal keeps its number."""
    row = c.execute("SELECT max(n) FROM automation_versions WHERE automation_id=?", (aid,)).fetchone()
    return (row[0] or 0) + 1


def _save(c, actor, aid, flow, before, *, current=None, summary=None, new_version=False, via=None):
    """Write the automation, with its audit row. A change to what it does (trigger, steps, batch) is a new version; a
    rename, pause or cap is not. `current` makes that pending version the current one instead; `new_version` writes
    one even when nothing it does changed (restoring an old version)."""
    now, prior = H.now(), c.execute("SELECT version FROM automations WHERE id=?", (aid,)).fetchone()
    n = prior["version"] if prior else None
    if current is not None:
        n = current
        c.execute("UPDATE automation_versions SET status='active' WHERE automation_id=? AND n=?", (aid, n))
    elif new_version or prior is None or _versioned(flow) != _versioned(before or {}):
        n = _next_n(c, aid)
        c.execute("INSERT INTO automation_versions(automation_id,n,actor,at,flow_json,status,summary) "
                  "VALUES(?,?,?,?,?,'active',?)", (aid, n, actor, now, json.dumps(_versioned(flow), sort_keys=True),
                                                    summary))
    columns = (flow["name"], flow["owner"], flow.get("group") or None, flow["trigger"]["type"], int(flow["enabled"]),
               int(flow["builtin"]), json.dumps(flow, sort_keys=True), n, now)
    if prior:
        c.execute("UPDATE automations SET name=?,owner=?,grp=?,trigger_type=?,enabled=?,builtin=?,flow_json=?,version=?,"
                  "updated=?,next_due=NULL WHERE id=?", (*columns, aid))
    else:
        c.execute("INSERT INTO automations(name,owner,grp,trigger_type,enabled,builtin,flow_json,version,updated,id,"
                  "created,created_by,found_since) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)", (*columns, aid, now, actor, now))
    audit_log.write(c, actor, "automation:" + aid, before, flow, via)
    return _row(c, aid)


def follow(c, owner, old, new):
    """A teammate moved group: its automations in the old group go with it (backend/groups.py calls this)."""
    if old == new or not old or not redesign.on(c):
        return
    for row in c.execute("SELECT * FROM automations WHERE owner=? AND grp=? AND deleted_at IS NULL",
                         (owner, "group:" + old)).fetchall():
        before = flow_of(row)
        flow = {k: v for k, v in before.items() if k != "group"} | ({"group": "group:" + new} if new else {})
        _save(c, H.KEEPER, row["id"], flow, before, via="group:" + (new or old))


def _propose(c, actor, aid, flow, before, summary):
    """A bot's change it may not make itself: kept as a pending version that a person with edit rights restores."""
    n = _next_n(c, aid)
    c.execute("INSERT INTO automation_versions(automation_id,n,actor,at,flow_json,status,summary) "
              "VALUES(?,?,?,?,?,'pending',?)", (aid, n, actor, H.now(), json.dumps(_versioned(flow), sort_keys=True),
                                                summary))
    return n


# ---------------------------------------------------------------------------------------------------- who may
def _key(ref):
    """A person, bot or group ref as the org chart keys it (`p:`, `b:`, `g:`)."""
    kind, _, ident = F.owner_ref(ref).partition(":")
    return {"person": "p:", "bot": "b:", "group": "g:"}.get(kind, "?:") + ident


class Chart:
    """The org chart as the permission rule reads it: who is above whom, and who leads a group."""

    def __init__(self, c):
        from . import views
        self.roster, self.employees = views.roster(c), views.entries(c)
        self.archived = {row["slug"] for row in H.bots(c) if row.get("state") == "archived"}
        self.groups = self.roster.get("org_groups") or {}

    def up(self, key):
        head, _, rest = key.partition(":")
        if head == "g":
            group = self.groups.get(rest) or {}
            lead = self.lead(rest)
            return lead or ("p:" + group["reports_to"] if group.get("reports_to") else "")
        kind = {"p": "person", "b": "bot"}.get(head)
        return P.org_parent(kind, rest, self.roster, self.employees, self.archived) if kind else ""

    def above(self, key):
        """Every key above this one, nearest first."""
        out, at = [], self.up(key)
        while at and at not in out and at != key:
            out.append(at)
            at = self.up(at)
        return out

    def lead(self, gid):
        """The group's lead (CONTRACT §3 `lead`), else the person it reports to."""
        group = self.groups.get(gid) or {}
        if group.get("lead"):
            lead = F.owner_ref(group["lead"])
            return _key(lead if ":" in lead else "person:" + lead)
        return "p:" + group["reports_to"] if group.get("reports_to") else ""

    def leads(self, gid):
        return [lead for g in P.group_chain(gid, self.roster) for lead in [self.lead(g)] if lead]


def may_change(c, who, flow, chart=None):
    """The one rule for the UI, the CLI and MCP: the top of the org; the owner; anyone above the owner; the lead of the
    automation's group (or of a group it is in) and anyone above that lead. A peer is refused. Seeing follows it."""
    if who.role == "owner":
        return True
    if who.role not in ("human", "bot"):
        return False
    me = _key("person:" + H.actor_id(who.actor) if who.role == "human" else who.actor)
    chart, owner = chart or Chart(c), _key(flow["owner"])
    gid = (flow.get("group") or "").partition(":")[2] or (owner[2:] if owner.startswith("g:") else "")
    heads = ([] if owner.startswith("g:") else [owner]) + (chart.leads(gid) if gid else [])
    return any(me == head or me in chart.above(head) for head in heads)


def may_see(c, who, flow):
    """Seeing follows the change rule; the Automations Bot sees every automation so it can propose changes."""
    return who.actor == HELPER or may_change(c, who, flow)


def _require(c, who, flow, what="change this automation"):
    if not may_change(c, who, flow):
        raise Problem("forbidden", f"Only its owner, the people above its owner or its group's lead may {what}", 403)


def _owner_known(c, owner):
    kind, _, ident = owner.partition(":")
    if kind == "person":
        from . import views
        return P.person(ident, views.roster(c)) is not None
    if kind == "bot":
        return H.bot(c, ident) is not None
    from . import views
    return ident in (views.roster(c).get("org_groups") or {})


def _checked(c, flow):
    try:
        flow = F.check(flow)
    except F.Invalid as exc:
        raise Problem("invalid", str(exc), 422)
    for ref in (flow["owner"], flow.get("group")):
        if ref and not _owner_known(c, ref):
            raise Problem("invalid", f"{ref} is not on the team", 422)
    return flow


# ---------------------------------------------------------------------------------------------------- built-ins
# The automations Tico ships, made by the hub on the scheduler's pass (its first runs at startup) once the redesign is
# on, never by POST. Each is {key, name, owner, trigger, steps}. The system jobs move here with their migration; until then the old
# jobs run as they do and this list is empty.
BUILTINS = ()


def ensure_builtins(c, catalog=None):
    """Make each built-in that does not exist yet; one already made is left as its people changed it."""
    made = []
    for spec in BUILTINS if catalog is None else catalog:
        aid = "auto_builtin_" + spec["key"]
        if c.execute("SELECT 1 FROM automations WHERE id=?", (aid,)).fetchone():
            continue
        flow = F.check({**{k: v for k, v in spec.items() if k != "key"}, "builtin": True, "enabled": True})
        _save(c, H.KEEPER, aid, flow, None)
        made.append(aid)
    return made


# ---------------------------------------------------------------------------------------------------- triggers
def _count(c, aid, field):
    c.execute(f"INSERT INTO automation_daily(automation_id,day,{field}) VALUES(?,?,1) "
              f"ON CONFLICT(automation_id,day) DO UPDATE SET {field}={field}+1", (aid, H.now()[:10]))


def _ring(c):
    if hasattr(c, "after_commit"):
        c.after_commit.append(_BELL.set)
    else:
        _BELL.set()


def queue(c, row, payload, ref="", *, manual=False, chain=()):
    """A queued run of this automation's current version."""
    rid = "run_" + H.new_id()
    state = E.start(payload, manual=manual)
    c.execute("INSERT INTO automation_runs(id,automation_id,version,trigger_ref,started,status,state_json,chain_json) "
              "VALUES(?,?,?,?,?,'queued',?,?)", (rid, row["id"], row["version"], str(ref or "")[:200], H.now(),
                                                  json.dumps(state, default=str), json.dumps(list(chain))))
    _count(c, row["id"], "runs")
    _ring(c)
    return rid


def fire(c, kind, payload, ref="", match=None):
    """Queue a run of every enabled automation on a `kind` trigger that `match(trigger)` takes and whose trigger
    filters hold; one they drop counts toward its day. Returns the queued run ids. Never raises: an automation
    problem must not undo the write that triggered it."""
    try:
        if not redesign.on(c):
            return []
        chain = CHAIN.get()
        if len(chain) >= MAX_CHAIN:
            return []
        queued = []
        for row in c.execute("SELECT * FROM automations WHERE deleted_at IS NULL AND enabled=1 AND trigger_type=? "
                             "ORDER BY created", (kind,)).fetchall():
            row = dict(row)
            if row["id"] in chain:
                continue
            trigger = flow_of(row)["trigger"]
            if match and not match(trigger):
                continue
            if not F.all_hold(trigger.get("filters") or [], payload):
                _count(c, row["id"], "dropped")
                continue
            queued.append(queue(c, row, payload, ref, chain=(*chain, row["id"])))
        return queued
    except Exception:  # noqa: BLE001 - logged, never raised into the trigger's write
        import logging
        logging.getLogger(__name__).warning("automation trigger %s failed", kind, exc_info=True)
        return []


def hub_checks(c, task):
    """Hook point for the task flow's own checks before a task_received automation runs (CONTRACT §2). Nothing yet:
    every task passes."""
    return True


def on_event(c, type_, subject, data, actor):
    """A catalog event (backend/event_catalog.py): `event` automations on it, and `task_received` on a task that now
    has an owner."""
    if not redesign.on(c):
        return
    from . import event_catalog as CAT
    name = CAT.canonical(type_) or type_
    facts = data() if callable(data) else (data or {})
    payload = {"event": {"name": name, "subject": subject, "actor": actor, **({"data": facts} if facts else {})}}
    fire(c, "event", payload, f"{name}:{subject}", lambda t: CAT.matches(t["name"], name) or t["name"] == name)
    if name in ("task.created", "task.assigned") and isinstance(facts, dict) and facts.get("owner"):
        task = H.task(c, subject)
        if task and not H.task_private(c, task) and hub_checks(c, task):
            # task.assigned is told before the owner column is written: the new owner is the event's.
            task = {**{k: task.get(k) for k in ("id", "title", "body", "status", "requester", "step_id", "type")},
                    "owner": facts["owner"]}
            owner = F.owner_ref(facts["owner"])
            fire(c, "task_received", {"task": task, "event": {"name": name}}, f"task:{subject}:{name}",
                 lambda t: F.owner_ref(t["to"]) == owner)


def on_mail(c, mailbox, message):
    """A new message in a person's mailbox (the mail connector's copy)."""
    payload = {"message": {"source": "mail", "mailbox": mailbox, "id": message.msg_id, "thread": message.thread_id,
                           "from": message.from_addr, "to": list(message.to or []), "subject": message.subject,
                           "snippet": message.snippet, "body": (message.body or "")[:8000],
                           "labels": list(message.labels or []), "list_id": message.list_id,
                           "internal": bool(message.is_internal), "date": message.date}}
    return fire(c, "message", payload, f"mail:{mailbox}:{message.msg_id}",
                lambda t: str(t["inbox"]).lower() == str(mailbox).lower())


def on_slack(c, event, person, channel=None):
    """A Slack message the gateway let in: queued for a `message` automation on its inbox, `slack:dm` for a direct
    message or `slack:#<channel>`. Returns the run ids; any means the automation handles it and the gateway's own
    routing does not."""
    channel = channel or {}
    dm = event.get("channel_kind") == "im" or channel.get("kind") == "im"
    inbox = "slack:dm" if dm else "slack:#" + str(channel.get("name") or event.get("channel") or "").lstrip("#").lower()
    payload = {"message": {"source": "slack", "inbox": inbox, "channel": str(event.get("channel") or ""),
                           "ts": event.get("ts"), "thread_ts": event.get("thread_ts") or event.get("ts"),
                           "from": "person:" + person["id"], "text": str(event.get("text") or "")[:8000]}}
    return fire(c, "message", payload, f"slack:{event.get('channel')}:{event.get('ts')}",
                lambda t: str(t["inbox"]).lower() == inbox)


def on_webhook(c, trigger_id, name, type_, delivery, payload, content):
    """A call to an incoming trigger (backend/triggers.py), after its secret, dedupe and rate limit."""
    queued = fire(c, "webhook", {"webhook": {"id": trigger_id, "name": name, "type": type_, "delivery": delivery,
                                             "data": payload, "content": content}},
                  f"webhook:{trigger_id}:{delivery}", lambda t: t["id"] == trigger_id)
    return [{"outcome": "automation", "target": rid, "ok": True, "detail": "run queued"} for rid in queued]


def on_listening(c, intake, post):
    """A listening post routed to a destination (backend/listening.py `route`)."""
    payload = {"listening": {"id": intake["id"], "destination": intake["destination"], "url": post.get("url"),
                             "author": post.get("author"), "content": str(post.get("content") or "")[:8000],
                             "source": post.get("source")}}
    return fire(c, "listening", payload, f"listening:{intake['id']}", lambda t: t["destination"] == intake["destination"])


def turn_done(c, attempt, outcome, text):
    """A bot's turn ended (after `H.turn_finish` priced it): the run that started it (its notice carries
    `automation_run`) is charged its cost, which counts toward the spend cap, and a run waiting on it takes its answer
    and is queued."""
    if not redesign.on(c):
        return
    job = c.execute("SELECT message_id FROM jobs WHERE id=?", (attempt["job_id"],)).fetchone() if attempt["job_id"] else None
    msg = H.message(c, job["message_id"]) if job and job["message_id"] else None
    rid = ((msg or {}).get("refs") or {}).get("automation_run")
    run = c.execute("SELECT * FROM automation_runs WHERE id=?", (rid,)).fetchone() if rid else None
    if not run:
        return
    priced = c.execute("SELECT est_cost_usd FROM turns WHERE id=?", (attempt["id"],)).fetchone()
    cost = float((priced and priced[0]) or 0)
    state = json.loads(run["state_json"]) if run["state_json"] else None
    if state and run["status"] == "waiting" and E.answer(state, msg["id"], text or "", cost, ok=outcome == "completed"):
        c.execute("UPDATE automation_runs SET status='queued',state_json=?,cost=? WHERE id=?",
                  (json.dumps(state, default=str), state["cost"], rid))
        _ring(c)
    elif state and E.charge(state, msg["id"], cost):
        c.execute("UPDATE automation_runs SET state_json=?,cost=? WHERE id=?",
                  (json.dumps(state, default=str), state["cost"], rid))
    elif cost:
        c.execute("UPDATE automation_runs SET cost=round(cost+?,6) WHERE id=?", (cost, rid))


# ---------------------------------------------------------------------------------------------------- running
def _next_batch(flow, now):
    zone = ZoneInfo((flow.get("batch") or {}).get("tz") or "UTC")
    local = now.astimezone(zone)
    times = sorted((flow.get("batch") or {}).get("times") or ["00:00"])
    for days in (0, 1):
        day = (local + timedelta(days=days)).date()
        for t in times:
            hour, minute = map(int, t.split(":"))
            at = datetime(day.year, day.month, day.day, hour, minute, tzinfo=zone)
            if at > local:
                return at.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f") + "Z"
    return H.now()


def _trim(values, cap=VALUES_BYTES):
    """A run's values as the judge sees them: long text cut until the whole is under `cap` bytes."""
    values = json.loads(json.dumps(values, default=str))
    limit = 4000
    while len(json.dumps(values)) > cap and limit > 50:
        values = _cut(values, limit)
        limit //= 2
    return values


def _cut(node, limit):
    if isinstance(node, str):
        return node if len(node) <= limit else node[:limit] + " … (cut)"
    if isinstance(node, dict):
        return {k: _cut(v, limit) for k, v in node.items()}
    if isinstance(node, list):
        return [_cut(v, limit) for v in node[:50]]
    return node


class HubServices:
    """The executor's services in the hub. Each call with an effect takes its own short transaction."""

    def __init__(self, hub, row, flow, run_id, chain):
        self.hub, self.row, self.flow, self.run_id, self.chain = hub, row, flow, run_id, chain
        self.auto = {"id": row["id"], "flow": flow, "assistant_bot": hub.settings.assistant_bot}

    def _write(self, fn):
        token = CHAIN.set(self.chain)
        try:
            with self.hub.store.transaction() as c:
                return fn(c)
        finally:
            CHAIN.reset(token)

    def now(self):
        return H.now()

    def next_batch(self):
        return _next_batch(self.flow, datetime.now(timezone.utc))

    def spent_30m(self):
        with self.hub.store.read() as c:
            row = c.execute("SELECT coalesce(sum(cost),0) FROM automation_runs WHERE automation_id=? AND id<>? "
                            "AND started>=?", (self.row["id"], self.run_id, H.shift(H.now(), minutes=-30))).fetchone()
        return float(row[0] or 0)

    def question_set(self, ref):
        return F.question_set(ref)

    def judge(self, values, questions, label, level):
        from clients import judge as J
        from .judge import audit_detail, server_engine
        store = self.hub.store
        with store.read() as c:
            engine = server_engine(store, c, self.hub.app.state.judge)
        if engine is None:   # no decision model, or the month's decision cap is reached
            return None
        J.validate(values, questions, label)
        import inspect
        takes_level = "level" in inspect.signature(engine).parameters
        result = engine(_trim(values), questions, label, **({"level": level} if takes_level else {}))
        actor = A.actor_of(self.flow["owner"])
        self._write(lambda c: H.event(c, actor, "judge.call", label, {
            "label": label, "automation": self.row["id"], "run": self.run_id, "level": level,
            **audit_detail(result), "answers": J.summary(result["answers"])}))
        return result

    def act(self, do, args, ctx):
        return self._write(lambda c: A.run(c, self.auto, self.run_id, do, args, ctx["values"]))

    def start_turn(self, who, prompt, ctx, wait):
        return self._write(lambda c: A.start_turn(c, self.auto, self.run_id, ctx["step"], who, prompt,
                                                  self.hub.settings.assistant_bot))

    def find(self, source, query, limit):
        def work(c):
            since = (c.execute("SELECT found_since FROM automations WHERE id=?", (self.row["id"],)).fetchone() or {})
            items = A.find(c, self.auto, source, query, limit, since["found_since"] or "")
            if items:
                c.execute("UPDATE automations SET found_since=? WHERE id=?", (items[-1]["at"], self.row["id"]))
            return items
        return self._write(work)


class Hub:
    """What draining needs: the store, the settings and the app's judge."""

    def __init__(self, app, store):
        self.app, self.store, self.settings = app, store, store.settings
        self.lock = threading.Lock()

    def claim(self):
        with self.store.transaction() as c:
            row = c.execute("SELECT id FROM automation_runs WHERE status='queued' ORDER BY started LIMIT 1").fetchone()
            if not row:
                return None
            c.execute("UPDATE automation_runs SET status='running',claimed_at=? WHERE id=? AND status='queued'",
                      (H.now(), row["id"]))
            return row["id"]

    def drain(self, limit=200):
        """Run queued runs until none is left (or `limit`, so one request never drains forever)."""
        done = 0
        while done < limit:
            rid = self.claim()
            if not rid:
                return done
            self.go(rid)
            done += 1
        return done

    def go(self, rid):
        with self.store.read() as c:
            run = dict(c.execute("SELECT * FROM automation_runs WHERE id=?", (rid,)).fetchone())
            row = c.execute("SELECT * FROM automations WHERE id=?", (run["automation_id"],)).fetchone()
            version = c.execute("SELECT flow_json FROM automation_versions WHERE automation_id=? AND n=?",
                                (run["automation_id"], run["version"])).fetchone()
        state = json.loads(run["state_json"] or "{}")
        try:
            # What it does comes from the run's version; its owner, cap and the rest are as they are now.
            flow = {**{k: v for k, v in flow_of(row).items() if k not in VERSIONED}, **json.loads(version["flow_json"])}
            services = HubServices(self, dict(row), flow, rid, tuple(json.loads(run["chain_json"] or "[]")))
            state = E.advance(flow, state, services)
        except Exception as exc:  # noqa: BLE001 - a bug in a run fails that run, not the drain
            state = {**state, "status": "failed", "error": (str(exc) or type(exc).__name__)[:300]}
        waits = [t["wait"]["until"] for t in state.get("threads", []) if (t.get("wait") or {}).get("kind") == "batch"]
        with self.store.transaction() as c:
            settle_mail(c, state)   # in the same write as the save, so a result reported meanwhile is not lost
            c.execute("UPDATE automation_runs SET status=?,cost=?,state_json=?,finished=?,wake_at=? WHERE id=?",
                      (state["status"], state.get("cost", 0), json.dumps(state, default=str),
                       None if state["status"] == "waiting" else H.now(), min(waits) if waits else None, rid))


# ---------------------------------------------------------------------------------------------------- mail actions
def _entries(record):
    """The action results in a step record: an action step's own, a filter rule's each."""
    outputs = record.get("outputs") or {}
    acts = outputs.get("actions") if record.get("type") == "filter" else [outputs]
    return [a for a in acts or [] if isinstance(a, dict)]


def settle_mail(c, state):
    """The run's queued mail actions as their computer reported them: a step waits while one of its actions is out
    and is ok or failed by the results, and a run with nothing else to wait for waits while a step does. Returns the
    run's status."""
    pending = failed = False
    for record in state.get("steps") or []:
        acts = _entries(record)
        mail = [a for a in acts if a.get("mail_action")]
        if not mail or record.get("status") not in ("ok", "waiting", "failed"):
            continue
        for entry in mail:
            row = c.execute("SELECT state, result_json FROM automation_mail_actions WHERE id=?",
                            (entry["mail_action"],)).fetchone()
            now = row["state"] if row else "failed"
            entry["queued"] = now in ("queued", "claimed")
            if entry["queued"]:
                continue
            result = json.loads((row and row["result_json"]) or "{}")
            entry["ok"] = now == "done"
            entry["detail"] = ("send_off" if entry["ok"] and result.get("send_off")
                               else str(result.get("detail") or ("done" if entry["ok"] else "no such mail action")))
            entry.update({k: result[k] for k in ("message", "draft", "thread", "send_off") if result.get(k)})
        record["status"] = ("waiting" if any(a["queued"] for a in mail)
                            else "failed" if any(not a.get("ok") for a in acts) else "ok")
        pending |= record["status"] == "waiting"
        failed |= record["status"] == "failed"
    if state.get("status") in ("ok", "waiting") and not any(t.get("state") == E.WAITING
                                                            for t in state.get("threads") or []):
        state["status"] = "waiting" if pending else "failed" if failed else "ok"
    return state.get("status")


def _settle_run(c, run_id):
    """A mail action's result reached its run. A run being advanced settles as it is saved (Hub.go)."""
    run = c.execute("SELECT status, state_json, finished FROM automation_runs WHERE id=?", (run_id,)).fetchone()
    if not run or not run["state_json"] or run["status"] in ("queued", "running"):
        return
    state = json.loads(run["state_json"])
    status = settle_mail(c, state)
    status = "failed" if run["status"] == "failed" else status   # the tick gave up on it: it stays failed
    c.execute("UPDATE automation_runs SET status=?, state_json=?, finished=? WHERE id=?",
              (status, json.dumps(state, default=str),
               run["finished"] or (None if status == "waiting" else H.now()), run_id))


def restate(c, run_id, key, value, changes):
    """Amend a step result the run recorded (the one whose `key` is `value`), when what happened changed after
    the step: a Slack reply held by the send switch."""
    run = c.execute("SELECT state_json FROM automation_runs WHERE id=?", (run_id,)).fetchone() if run_id else None
    if not run or not run["state_json"]:
        return
    state = json.loads(run["state_json"])
    for record in state.get("steps") or []:
        for entry in _entries(record):
            if entry.get(key) == value:
                entry.update({k: v for k, v in changes.items() if v is not None})
                c.execute("UPDATE automation_runs SET state_json=? WHERE id=?", (json.dumps(state, default=str), run_id))
                return


def _mail_report(c, row, state, result):
    c.execute("UPDATE automation_mail_actions SET state=?, result_json=? WHERE id=?",
              (state, json.dumps(result, default=str), row["id"]))
    if state in ("done", "failed") and row["run_id"]:
        _settle_run(c, row["run_id"])


def tick(store, at=None):
    """The scheduler's pass: due schedules fire, batch waits whose time came and answered turns go back in the
    queue, runs cut off are failed, and the queue is drained."""
    hub = getattr(store, "automations", None)
    with store.read() as c:
        if not redesign.on(c):
            return 0
    at = at or datetime.now(timezone.utc)
    now = at.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f") + "Z"
    with store.transaction() as c:
        ensure_builtins(c)
        from .scheduler import next_due
        for row in c.execute("SELECT * FROM automations WHERE deleted_at IS NULL AND enabled=1 "
                             "AND trigger_type='schedule'").fetchall():
            trigger = flow_of(row)["trigger"]
            zone = trigger.get("tz") or "UTC"
            if not row["next_due"]:
                due = next_due(trigger["cron"], at, zone)
                c.execute("UPDATE automations SET next_due=? WHERE id=?", (_iso(due), row["id"]))
                continue
            if row["next_due"] > now:
                continue
            queue(c, dict(row), {"schedule": {"at": row["next_due"], "cron": trigger["cron"], "tz": zone}},
                  f"schedule:{row['next_due']}")
            c.execute("UPDATE automations SET next_due=? WHERE id=?", (_iso(next_due(trigger["cron"], at, zone)), row["id"]))
        c.execute("UPDATE automation_runs SET status='queued',wake_at=NULL WHERE status='waiting' AND wake_at<=?", (now,))
        c.execute("UPDATE automation_runs SET status='failed',finished=? WHERE status='running' AND claimed_at<?",
                  (now, H.shift(now, minutes=-STALE_MINUTES)))
        # A turn that never answered (its bot gone, its job cancelled) would hold the run waiting for ever.
        c.execute("UPDATE automation_runs SET status='failed',finished=? WHERE status='waiting' AND wake_at IS NULL "
                  "AND started<?", (now, H.shift(now, days=-TURN_WAIT_DAYS)))
    return hub.drain() if hub else 0


def _due(trigger, at):
    """The schedule's next time after `at`, in its zone's wall clock, so 09:00 stays 09:00 across a DST change."""
    from .scheduler import next_due
    return next_due(trigger["cron"], at, trigger.get("tz") or "UTC")


def _iso(at):
    return at.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f") + "Z"


def prune(c, now):
    """Step detail keeps KEEP_DAYS: older finished runs keep their status, cost and times."""
    c.execute("UPDATE automation_runs SET state_json=NULL WHERE state_json IS NOT NULL AND finished IS NOT NULL "
              "AND finished<?", (H.shift(now, days=-KEEP_DAYS),))


# ---------------------------------------------------------------------------------------------------- routes
class AutomationIn(Contract):
    name: str = Field(min_length=1, max_length=120)
    owner: str = Field(min_length=1, max_length=80)
    group: str | None = Field(default=None, max_length=80)
    enabled: bool = True
    builtin: bool = False
    spend_cap: dict | None = None
    batch: dict | None = None
    trigger: dict
    steps: list = Field(default_factory=list)


class AutomationPatch(Contract):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    owner: str | None = Field(default=None, min_length=1, max_length=80)
    group: str | None = Field(default=None, max_length=80)
    enabled: bool | None = None
    spend_cap: dict | None = None
    batch: dict | None = None
    trigger: dict | None = None
    steps: list | None = None
    summary: str | None = Field(default=None, max_length=200)   # a few words on a new version or proposal


class Empty(Contract):
    pass


class InboxSend(Contract):
    send: bool


class RunNow(Contract):
    input: dict = Field(default_factory=dict)   # shaped like the trigger's output: message, task, item, event, body


FLOW_KEYS = ("name", "owner", "group", "enabled", "builtin", "spend_cap", "batch", "trigger", "steps")


def page(rows, limit, offset, cap):
    out, used = [], 256
    for row in rows:
        size = len(json.dumps(row, default=str).encode()) + 1
        if len(out) >= limit or used + size > cap:
            return out, offset + len(out)
        used += size
        out.append(row)
    return out, None


def _summary(state):
    """A few words for the run's row: where it failed, else the paths it took, else what the cap stopped."""
    steps = state.get("steps") or []
    failed = next((s["id"] for s in steps if s["status"] == "failed"), None)
    if failed:
        return f"failed at {failed}"
    taken = list(dict.fromkeys(str(s["outputs"].get("path")) for s in steps
                               if s["type"] == "paths" and s["outputs"].get("path")))
    capped = sum(s["status"] == "spend_cap" for s in steps)
    words = (["path " + ", ".join(taken)] if taken else []) + ([f"{capped} stopped by the spend cap"] if capped else [])
    return "; ".join(words)[:120] or None


def run_view(run, detail=True):
    state = json.loads(run["state_json"]) if run["state_json"] else None
    out = {"id": run["id"], "automation_id": run["automation_id"], "version": run["version"],
           "trigger_ref": run["trigger_ref"], "started": run["started"], "finished": run["finished"],
           "status": run["status"], "cost": run["cost"]}
    if state:
        out["summary"] = _summary(state)
    if detail:
        out["steps"] = (state or {}).get("steps") if state else None   # None: pruned after KEEP_DAYS
        if state and state.get("error"):
            out["error"] = state["error"]
    return out


def install(app, store, auth, mutate):
    from fastapi import Request

    hub = Hub(app, store)
    store.automations = hub

    @app.middleware("http")
    async def automation_doorbell(request, call_next):
        response = await call_next(request)
        if _BELL.is_set():
            _BELL.clear()
            await asyncio.to_thread(hub.drain)
        return response

    def found(c, who, aid, what="see this automation", rule=None):
        _require_on(c)
        auth.domain(who)
        row = _row(c, aid)
        if not row:
            raise Problem("not_found", "No such automation", 404)
        if not (rule or may_change)(c, who, flow_of(row)):
            raise Problem("forbidden", f"Only its owner, the people above its owner or its group's lead may {what}", 403)
        return row

    @app.get("/api/v2/automations")
    def automations_list(request: Request, owner: str = "", limit: int = 50, cursor: int = 0):
        """The automations the caller may change (the same rule decides what they see), newest first."""
        who = request.state.identity
        with store.read() as c:
            _require_on(c)
            auth.domain(who)
            rows = c.execute("SELECT * FROM automations WHERE deleted_at IS NULL"
                             + (" AND owner=?" if owner else "") + " ORDER BY created DESC",
                             ((F.owner_ref(owner),) if owner else ())).fetchall()
            visible = [view(c, dict(r), who) for r in rows if may_see(c, who, flow_of(r))]
        shown, more = page(visible[max(cursor, 0):], max(1, min(limit, 200)), max(cursor, 0), LIST_BYTES)
        return {"automations": shown, "next": more}

    @app.get("/api/v2/automations/question-sets")
    def automations_question_sets(request: Request):
        """The saved question sets a Decide step may name, each with its questions."""
        from clients import judge as J
        with store.read() as c:
            _require_on(c)
            auth.domain(request.state.identity)
        sets = []
        for listed in J.list_sets():
            if listed.get("error"):
                continue
            data = J.load_set(listed["id"])
            sets.append({"id": f"{data['id']}@{data['version']}", "summary": data["summary"],
                         "questions": data["questions"]})
        return {"sets": sets}

    @app.post("/api/v2/automations")
    def automations_create(request: Request, body: AutomationIn):
        """Save a new automation as version 1. The caller must be allowed to change an automation of that owner."""
        who = request.state.identity

        def work(c):
            _require_on(c)
            auth.domain(who)
            flow = _checked(c, {k: v for k, v in body.model_dump().items() if v is not None})
            _require(c, who, flow, "make an automation for " + flow["owner"])
            if flow["builtin"]:
                raise Problem("forbidden", "Built-in automations come with Tico; the hub makes them", 403)
            return view(c, _save(c, who.actor, "auto_" + H.new_id(), flow, None, via=_via(who)), who, detail=True)
        return mutate(request, body, work)

    @app.get("/api/v2/automations/{aid}")
    def automations_get(request: Request, aid: str):
        who = request.state.identity
        with store.read() as c:
            return view(c, found(c, who, aid, rule=may_see), who, detail=True)

    @app.patch("/api/v2/automations/{aid}")
    def automations_update(request: Request, aid: str, body: AutomationPatch):
        """Change an automation. A change to its trigger, steps or batch times is a new version. A bot that may not
        change it (and the Automations Bot always) proposes instead: a pending version a person restores. Pausing a
        built-in one is the top of the org's alone."""
        who = request.state.identity

        def work(c):
            row = found(c, who, aid, "change this automation", rule=lambda c, who, flow: True)
            before = flow_of(row)
            changes = body.model_dump(exclude_unset=True)
            summary = changes.pop("summary", None)
            if "spend_cap" in changes and changes["spend_cap"] is None:
                changes.pop("spend_cap")
                before_cap = {k: v for k, v in before.items() if k != "spend_cap"}
            else:
                before_cap = before
            flow = _checked(c, {**before_cap, **changes})
            if who.role == "bot" and (who.actor == HELPER or not may_change(c, who, before)):
                if not changes or set(changes) - set(VERSIONED):
                    raise Problem("forbidden", "A bot may only propose a change to an automation's trigger, steps "
                                  "or batch times", 403)
                n = _propose(c, who.actor, aid, flow, before, summary)
                if may_see(c, who, before):
                    return {**view(c, row, who, detail=True), "pending": n}
                return {"id": aid, "pending": n, "can_edit": False}
            _require(c, who, before, "change this automation")
            _require(c, who, flow, "give this automation to " + flow["owner"])
            warning = None
            if before.get("builtin") and changes.get("enabled") is False:
                if who.role != "owner":
                    raise Problem("forbidden", "Only the top of the org pauses a built-in automation", 403)
                warning = "This is a built-in automation: the work it does stops until it is turned back on."
            if flow != before:
                row = _save(c, who.actor, aid, flow, before, summary=summary, via=_via(who))
            return {**view(c, row, who, detail=True), **({"warning": warning} if warning else {})}
        return mutate(request, body, work)

    def delete(request, aid, body):
        who = request.state.identity

        def work(c):
            row = found(c, who, aid, "delete this automation")
            if row["builtin"]:
                raise Problem("builtin", "A built-in automation cannot be deleted; the top of the org may pause it", 409)
            c.execute("UPDATE automations SET deleted_at=?, enabled=0 WHERE id=?", (H.now(), aid))
            c.execute("UPDATE automation_runs SET status='skipped',finished=? WHERE automation_id=? "
                      "AND status IN ('queued','waiting')", (H.now(), aid))
            audit_log.write(c, who.actor, "automation:" + aid, flow_of(row), None, _via(who))
            return {"id": aid, "deleted": True}
        return mutate(request, body, work)

    @app.delete("/api/v2/automations/{aid}")
    def automations_delete(request: Request, aid: str, body: Empty | None = None):
        return delete(request, aid, body or Empty())

    @app.post("/api/v2/automations/{aid}/delete")
    def automations_delete_post(request: Request, aid: str, body: Empty | None = None):
        """The same delete for clients that only POST (the hub CLI and MCP)."""
        return delete(request, aid, body or Empty())

    @app.post("/api/v2/automations/{aid}/run")
    def automations_run(request: Request, aid: str, body: RunNow | None = None):
        """Run it now, whatever its trigger and batch times say; `input` stands in for the trigger's output (the page's
        "Test with sample"). Answers with the run once it has gone as far as it can now."""
        who, body = request.state.identity, body or RunNow()

        def work(c):
            row = found(c, who, aid, "run this automation")
            rid = queue(c, row, {**body.input, "manual": {"by": who.actor}}, "manual", manual=True, chain=(aid,))
            return {"run": rid}
        rid = mutate(request, body, work)["run"]
        hub.drain()
        with store.read() as c:
            return {"run": run_view(c.execute("SELECT * FROM automation_runs WHERE id=?", (rid,)).fetchone())}

    @app.get("/api/v2/automations/{aid}/runs")
    def automations_runs(request: Request, aid: str, limit: int = 25, before: str = ""):
        """Its runs, newest first, each with its steps' status, outputs and cost (kept 30 days); `next` is the `before`
        for the page after. `daily` holds the counts, which include what the trigger's filters dropped."""
        limit = max(1, min(limit, 100))
        with store.read() as c:
            found(c, request.state.identity, aid, rule=may_see)
            at = c.execute("SELECT started, id FROM automation_runs WHERE id=? AND automation_id=?",
                           (before, aid)).fetchone() if before else None
            if before and not at:
                raise Problem("not_found", "No such run", 404)
            rows = c.execute("SELECT * FROM automation_runs WHERE automation_id=?"
                             + (" AND (started<? OR (started=? AND id<?))" if at else "")
                             + " ORDER BY started DESC, id DESC LIMIT ?",
                             (aid, *((at["started"], at["started"], at["id"]) if at else ()), limit + 1)).fetchall()
            days = [dict(r) for r in c.execute("SELECT day, runs, dropped FROM automation_daily WHERE automation_id=? "
                                               "ORDER BY day DESC LIMIT 30", (aid,))]
        runs, cut = page([run_view(r) for r in rows], limit, 0, RUN_BYTES)
        return {"runs": runs, "next": runs[-1]["id"] if cut is not None and runs else None, "daily": days}

    @app.get("/api/v2/automations/{aid}/versions")
    def automations_versions(request: Request, aid: str, status: str = "", limit: int = 50, cursor: int = 0):
        """Its versions, newest first; `status=pending` for the proposals waiting on a person."""
        with store.read() as c:
            found(c, request.state.identity, aid, rule=may_see)
            rows = [{"n": r["n"], "actor": r["actor"], "at": r["at"], "status": r["status"],
                     **({"summary": r["summary"]} if r["summary"] else {}), "flow": json.loads(r["flow_json"])}
                    for r in c.execute("SELECT * FROM automation_versions WHERE automation_id=?"
                                       + (" AND status=?" if status else "") + " ORDER BY n DESC",
                                       (aid, *((status,) if status else ())))]
        shown, more = page(rows[max(cursor, 0):], max(1, min(limit, 200)), max(cursor, 0), LIST_BYTES)
        return {"versions": shown, "next": more}

    @app.post("/api/v2/automations/{aid}/versions/{n}/restore")
    def automations_restore(request: Request, aid: str, n: int, body: Empty | None = None):
        """A pending version becomes the current one and keeps its number; an older one is saved as a new version.
        Either way its trigger, steps and batch times replace the current ones."""
        who, body = request.state.identity, body or Empty()

        def work(c):
            row = found(c, who, aid, "change this automation")
            old = c.execute("SELECT * FROM automation_versions WHERE automation_id=? AND n=?", (aid, n)).fetchone()
            if not old:
                raise Problem("not_found", f"No version {n}", 404)
            before = flow_of(row)
            flow = _checked(c, {**{k: v for k, v in before.items() if k not in VERSIONED}, **json.loads(old["flow_json"])})
            _require(c, who, flow, "restore this version")
            pending = old["status"] == "pending"
            saved = _save(c, who.actor, aid, flow, before, current=n if pending else None, new_version=not pending,
                          via=_via(who))
            return view(c, saved, who, detail=True)
        return mutate(request, body, work)

    @app.delete("/api/v2/automations/{aid}/versions/{n}")
    def automations_discard(request: Request, aid: str, n: int, body: Empty | None = None):
        """Discard a pending version (a proposal); any other version stays (409)."""
        who, body = request.state.identity, body or Empty()

        def work(c):
            row = found(c, who, aid, "discard a proposal")
            old = c.execute("SELECT status FROM automation_versions WHERE automation_id=? AND n=?", (aid, n)).fetchone()
            if not old:
                raise Problem("not_found", f"No version {n}", 404)
            if old["status"] != "pending":
                raise Problem("not_pending", "Only a pending version can be discarded", 409)
            c.execute("DELETE FROM automation_versions WHERE automation_id=? AND n=?", (aid, n))
            return view(c, row, who, detail=True)
        return mutate(request, body, work)

    # An inbox's send switch: on by default; off, send_reply saves a draft and logs send_off.
    def inbox_rights(c, who, inbox):
        _require_on(c)
        auth.domain(who)
        if who.role == "owner":
            return
        person = H.human(c, H.actor_id(who.actor)) if who.role == "human" else None
        if not (person and "@" in inbox and str(person.get("email") or "").lower() == inbox):
            raise Problem("forbidden", "Only the inbox's person or the top of the org sets its send switch", 403)

    @app.get("/api/v2/inboxes/{inbox}")
    def inbox_view(request: Request, inbox: str):
        inbox = inbox.strip().lower()
        with store.read() as c:
            inbox_rights(c, request.state.identity, inbox)
            return {"inbox": inbox, "send": A.send_on(c, inbox)}

    @app.patch("/api/v2/inboxes/{inbox}")
    def inbox_update(request: Request, inbox: str, body: InboxSend):
        who, inbox = request.state.identity, inbox.strip().lower()

        def work(c):
            inbox_rights(c, who, inbox)
            before = {"inbox": inbox, "send": A.send_on(c, inbox)}
            c.execute("INSERT INTO automation_inboxes(inbox,send,updated,updated_by) VALUES(?,?,?,?) "
                      "ON CONFLICT(inbox) DO UPDATE SET send=excluded.send,updated=excluded.updated,"
                      "updated_by=excluded.updated_by", (inbox, int(body.send), H.now(), who.actor))
            after = {"inbox": inbox, "send": body.send}
            if after != before:
                audit_log.write(c, who.actor, "inbox:" + inbox, before, after, _via(who))
            return after
        return mutate(request, body, work)

    @app.get("/api/v2/people/{person}/assistant")
    def person_assistant(request: Request, person: str):
        """The bot an `assistant:<person>` step runs on, once one has run (null before)."""
        from . import assistant
        with store.read() as c:
            _require_on(c)
            auth.domain(request.state.identity)
            if not H.human(c, person):
                raise Problem("not_found", "No such person", 404)
            return {"bot": hub.settings.assistant_bot if assistant.find_room(c, "human:" + person) else None}

    # The computer that reads a mailbox carries out the mail actions queued for it (runner/connectors.py).
    def mail_computer(c, who, mailbox):
        """Only the computer that reads this mailbox claims and reports its actions: by the check mail publishing uses
        (backend/connectors.py `publisher`), and, once the mailbox has been published, only the runner that did."""
        from .connectors import human_of
        runner = app.state.execution.runner(c, who)
        if not runner or runner["operator"] not in (store.settings.processing_operators or (auth.owner_id(c),)):
            raise Problem("forbidden", "This machine is not assigned the private app-connector capability", 403)
        box = c.execute("SELECT runner_id FROM mail_mailboxes WHERE address=?", (mailbox,)).fetchone()
        if not human_of(c, mailbox) or (box and box["runner_id"] and box["runner_id"] != runner["id"]):
            raise Problem("forbidden", "Another computer reads this mailbox", 403)
        return runner

    @app.post("/api/v2/automations/mail-actions/claim")
    def automation_mail_claim(request: Request, body: MailClaim):
        """A lease of up to 20 of the mailbox's queued actions for MAIL_LEASE_MINUTES. A send is read against the
        inbox's send switch now, not when it was queued: off, a send or forward is claimed as a draft and its step
        shows send_off."""
        who = request.state.identity

        def work(c):
            _require_on(c)
            mailbox = body.mailbox.strip().lower()
            runner = mail_computer(c, who, mailbox)
            now = H.now()
            for row in c.execute("SELECT * FROM automation_mail_actions WHERE mailbox=? AND state='claimed' "
                                 "AND claimed_at<?", (mailbox, H.shift(now, minutes=-MAIL_LEASE_MINUTES))).fetchall():
                if row["attempts"] >= MAIL_TRIES:
                    _mail_report(c, row, "failed", {**json.loads(row["result_json"] or "{}"), "ok": False,
                                                    "detail": f"no result after {MAIL_TRIES} tries"})
                else:
                    c.execute("UPDATE automation_mail_actions SET state='queued' WHERE id=?", (row["id"],))
            rows = [dict(r) for r in c.execute(
                "SELECT * FROM automation_mail_actions WHERE state='queued' AND mailbox=? ORDER BY created LIMIT 20",
                (mailbox,))]
            sending = A.send_on(c, mailbox)
            out = []
            for r in rows:
                action, result, args = r["action"], json.loads(r["result_json"] or "{}"), json.loads(r["args_json"])
                if action in ("send", "forward") and not sending:
                    # Both send mail out: a reply becomes a draft reply, a forward a draft to its target.
                    action, result = "draft" if action == "send" else action, {**result, "send_off": True}
                    args = {**args, "draft_only": True} if action == "forward" else args
                    owner = c.execute("SELECT owner FROM automations WHERE id=?", (r["automation_id"],)).fetchone()
                    H.event(c, A.actor_of(owner["owner"] if owner else ""), "automation.send_off", r["automation_id"],
                            {"run": r["run_id"], "mailbox": mailbox, "msg_id": r["msg_id"]})
                c.execute("UPDATE automation_mail_actions SET state='claimed',claimed_at=?,claimed_by=?,"
                          "attempts=attempts+1,action=?,result_json=? WHERE id=?",
                          (now, runner["id"], action, json.dumps(result) if result else None, r["id"]))
                out.append({"id": r["id"], "mailbox": r["mailbox"], "msg_id": r["msg_id"], "action": action,
                            "args": args, "attempt": r["attempts"] + 1})
            return {"actions": out, "lease_seconds": MAIL_LEASE_MINUTES * 60}
        return mutate(request, body, work)

    @app.post("/api/v2/automations/mail-actions/{mid}/result")
    def automation_mail_result(request: Request, mid: str, body: MailResult):
        """What the computer did. Idempotent by action id: once done or failed, a repeat (a lost answer, a late
        report after the lease ran out) changes nothing. A failure it may retry goes back to the queue until
        MAIL_TRIES claims; a late success counts, so the action is never carried out again."""
        who = request.state.identity

        def work(c):
            _require_on(c)
            row = c.execute("SELECT * FROM automation_mail_actions WHERE id=?", (mid,)).fetchone()
            if not row:
                raise Problem("not_found", "No such mail action", 404)
            mail_computer(c, who, row["mailbox"])
            if row["state"] in ("done", "failed"):
                return {"id": mid, "state": row["state"]}
            state = ("done" if body.ok else "queued" if body.retry and row["attempts"] < MAIL_TRIES else "failed")
            result = {**json.loads(row["result_json"] or "{}"), "ok": body.ok, "detail": body.detail,
                      **{k: v for k, v in (("message", body.message), ("draft", body.draft), ("thread", body.thread))
                         if v}}
            _mail_report(c, row, state, result)
            return {"id": mid, "state": state}
        return mutate(request, body, work)


class MailClaim(Contract):
    mailbox: str = Field(min_length=3, max_length=320)


class MailResult(Contract):
    ok: bool
    detail: str = Field(default="", max_length=1000)
    retry: bool = True                                      # a failure worth another claim (not: no such message)
    message: str = Field(default="", max_length=200)        # the Gmail message sent
    draft: str = Field(default="", max_length=200)          # the Gmail draft made
    thread: str = Field(default="", max_length=200)
