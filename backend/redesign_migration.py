"""The redesign's converter (PLAN §8, CONTRACT §4): today's routines, wake rules, system jobs, inboxes, limits and
budgets become automations and the new amounts, once per install, by the owner.

- **Dry run** reads every object and says what it becomes, with flags where the mapping needs a person's eye. It
  writes nothing.
- **Resolve** records the owner's yes to flags. Convert is refused while a flag has no yes.
- **Convert** snapshots the affected rows first, then converts one object per transaction: the automation is saved
  with its `source`, and in the same write the old row stops (a routine's row is soft-deleted, a wake rule's row
  removed). A schedule automation takes the routine's own `next_due`, so an occurrence due across the cutover fires
  once, from one system.
- **Restore** within a day of the convert puts the snapshot back and soft-deletes the converted automations. After
  the day the snapshot is dropped (the scheduler's hourly sweep, `prune`) and restore answers 410.

What stays where it is (the engine of record does not move in this pass): task rules, system jobs and the Health
Monitor show as read-only built-in automations (`readonly`, with the job's `controls`) and keep running from their
own tables. A converted wake rule keeps deciding wakes from rules.py, which reads it from its "What wakes"
automation (`wake_rows`), so an edit there (a rule's step turned off, deleted, its event or outcome changed) is what
wakes the bot.

Dormant: every route answers 404 while the `redesign` setting is off.
"""
import json
import logging
import math
from datetime import datetime, timedelta, timezone

from . import automation_flow as F, redesign
from .models import Contract
from .store import H, Problem

log = logging.getLogger("tico.redesign_migration")
KEEP_HOURS = 24
# A migration in one of these may still be restored (or is still running): no second convert starts beside it.
OPEN_STATES = ("converting", "interrupted", "converted")
WAKES_PREFIX = "auto_wakes_"                  # custom "What wakes" automations: rules.py reads its rows from these
GUARD = {"turns_per_hour": 300, "turns_per_day": 2500}   # CONTRACT §1 run guard defaults
STRATEGY_NAME = "Strategy Bot"
DEFAULT_PROMPT = ("Read this message for {name}. Archive what needs nothing, label what belongs somewhere, draft a "
                  "reply where one is wanted, and leave the rest for {name}.")
OUTCOME_DO = {"wake": "wake_bot", "batch": "wake_bot", "action": "wake_bot", "note": "note", "ignore": "archive",
              "ask": "leave_for_you"}
# The message the inbox automation runs on, handed to the Assistant the way message automations do: each `{{field}}`
# becomes a quoted data block after the instructions (automation_flow.render_prompt), never read as instructions.
MESSAGE_PART = ("\n\nThe message to handle: id {{message.id}} in thread {{message.thread}}, from {{message.from}} "
                "({{message.from_name}}), subject {{message.subject}}. Its body:\n{{message.body}}")
JOB_MIRRORS_SKIP = ("stale_review",)          # a regular automation instead (PLAN §8)
SCHEMA = (
    "CREATE TABLE IF NOT EXISTS redesign_migrations(id TEXT PRIMARY KEY, state TEXT NOT NULL, actor TEXT NOT NULL, "
    "created TEXT NOT NULL, expires TEXT NOT NULL, finished TEXT, restored_at TEXT, snapshot_json TEXT, "
    "result_json TEXT)",
    "CREATE TABLE IF NOT EXISTS redesign_migration_accepts(flag TEXT PRIMARY KEY, accepted_by TEXT NOT NULL, "
    "at TEXT NOT NULL)",
    "CREATE TABLE IF NOT EXISTS redesign_migrated(kind TEXT NOT NULL, id TEXT NOT NULL, migration TEXT NOT NULL, "
    "automation TEXT, PRIMARY KEY(kind, id))",
)


def ensure(c):
    for statement in SCHEMA:
        c.execute(statement)
    # CONTRACT §1 30-minute limits (wave 2 adds the same columns; both are idempotent).
    from .hubdb import add_column
    from . import usage_limits
    usage_limits.ensure(c)
    add_column(c, "usage_limits", "per_30m_usd", "REAL")
    add_column(c, "usage_pools", "per_30m_usd", "REAL")


class Accept(Contract):
    """Flags the owner says yes to: flag ids, object ids (every flag on it), or {id, flags} as the dry run lists them."""
    accept: list[str | dict] | None = None


# ---------------------------------------------------------------------------------------------------- reading
def _now():
    return H.now()


def _at(stamp):
    return datetime.fromisoformat(str(stamp).replace("Z", "+00:00")).astimezone(timezone.utc)


def _stamp(at):
    return at.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _json(raw, default):
    try:
        value = json.loads(raw) if raw else default
    except (TypeError, ValueError):
        return default
    return value if isinstance(value, type(default)) else default


def _meta(c, key):
    row = c.execute("SELECT value_json FROM registry_metadata WHERE key=?", (key,)).fetchone()
    return row[0] if row else None


def _set_meta(c, key, raw):
    if raw is None:
        c.execute("DELETE FROM registry_metadata WHERE key=?", (key,))
    else:
        c.execute("INSERT INTO registry_metadata VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value_json=excluded.value_json",
                  (key, raw))


def _table(c, name):
    return bool(H._has_table(c, name))


def _columns(c, table):
    return {r[1] for r in c.execute(f"PRAGMA table_info({table})")}


def half(value):
    """$X an hour is $X/2 per 30 minutes, rounded up to $0.10 (PLAN decision 16)."""
    return round(math.ceil(round(float(value) / 2 * 10, 6)) / 10, 6)


def _flag(obj_id, kind, text, keeps=False):
    return {"id": f"{obj_id}#{kind}", "kind": kind, "text": text, **({"keeps": True} if keeps else {})}


def _owner_person(who):
    return "person:" + H.actor_id(who.actor) if who.role in ("owner", "human") and H.actor_id(who.actor) else None


def _bot_name(c, slug):
    row = H.bot(c, slug) or {}
    return (row.get("display_name") or "").strip() or slug


def _cron(preset, at):
    """A system job's preset as a five-field cron, in company time."""
    hour, minute = (int(p) for p in (at or "09:00").split(":"))
    return {"15m": "*/15 * * * *", "hourly": "0 * * * *", "4h": "0 */4 * * *", "daily": f"{minute} {hour} * * *",
            "business": "0 8-17 * * 1-5", "weekly": f"{minute} {hour} * * 1"}.get(preset or "hourly", "0 * * * *")


def _zone():
    """Company time (system jobs run in it) as a zone name."""
    from . import system_routines as SR
    zone = SR.zone()
    return str(getattr(zone, "key", zone))


def _mirror(name, owner, key, controls, source, words=""):
    """A read-only built-in automation that shows something Tico still runs from its own table."""
    return {"name": name[:120], "owner": owner, "builtin": True, "readonly": True, "enabled": bool(controls.get("on", True)),
            "trigger": {"type": "event", "name": "tico.builtin." + key},
            "steps": [], "controls": controls, "source": source, **({"description": words[:500]} if words else {})}


# ---------------------------------------------------------------------------------------------------- the plan
def plan(c, who):
    """Every object the converter knows, in report order: {kind, id, title, becomes, flags, _do}. `_do` is what convert
    does with it and never leaves the module."""
    ensure_read = _table(c, "redesign_migrated")
    done = {(r["kind"], r["id"]) for r in c.execute("SELECT kind, id FROM redesign_migrated")} if ensure_read else set()
    me = _owner_person(who)
    out = []
    out += _routines(c, done)
    out += _wake_rules(c, done, me)
    out += _builtins(c, done, me)
    out += _inboxes(c, done)
    out += _bots(c, done)
    out += _unchanged(c)
    out += _limits(c, done)
    out += _budgets(c, done)
    accepted = {r["flag"] for r in c.execute("SELECT flag FROM redesign_migration_accepts")} if ensure_read else set()
    for obj in out:
        for flag in obj["flags"]:
            flag["accepted"] = flag["id"] in accepted
    return out


def _routines(c, done):
    from . import automations, event_catalog as CAT, routines, triggers
    rows = c.execute("SELECT s.*, coalesce(sc.timezone, ?) AS timezone, coalesce(sc.enabled, 1) AS enabled "
                     "FROM schedules s LEFT JOIN schedule_config sc ON sc.schedule_id=s.id "
                     "WHERE s.deleted_at IS NULL ORDER BY s.bot, s.id", (routines.DEFAULT_ZONE,)).fetchall()
    inbox_bots = {b["bot"] for b in routines.message_bot_mailboxes(c)}
    out = []
    for row in rows:
        row = dict(row)
        sid, bot = row["id"], row["bot"]
        if ("routine", sid) in done:
            continue
        flags, text = [], row["playbook"] or routines.DEFAULT_TEXT
        found = H.bot(c, bot)
        event = row["event_name"] or ""
        if event.startswith(triggers.EVENT):
            trigger = {"type": "webhook", "id": event[len(triggers.EVENT):]}
            if not triggers.exists(c, event):
                flags.append(_flag(sid, "no_trigger", "Its incoming webhook is gone; it stays a routine", keeps=True))
        elif event:
            trigger = {"type": "event", "name": event}
            if not CAT.canonical(event):
                flags.append(_flag(sid, "unknown_event", f"Tico does not list the event {event}; the automation "
                                                         "runs only if something sends it"))
        else:
            trigger = {"type": "schedule", "cron": row["cron"], "tz": row["timezone"] or routines.DEFAULT_ZONE}
        enabled = bool(row["enabled"])
        if not found or found.get("state") == "archived":
            flags.append(_flag(sid, "no_bot", f"Its bot {bot} is gone; it stays a routine", keeps=True))
        elif found.get("state") != "active":
            enabled = False
            flags.append(_flag(sid, "bot_not_active", f"{_bot_name(c, bot)} is {found.get('state')}: the automation "
                                                      "starts off; turn it on when the bot is back"))
        if bot in inbox_bots and enabled:
            enabled = False
            flags.append(_flag(sid, "inbox_bot", f"{_bot_name(c, bot)} reads an inbox and retires with it: this "
                                                 "routine starts off"))
        if len(text) > F.MAX_PROMPT:
            flags.append(_flag(sid, "too_long", f"Its text is longer than {F.MAX_PROMPT:,} characters; it stays a "
                                                "routine until it is shorter", keeps=True))
        if "{{" in text:
            flags.append(_flag(sid, "placeholders", "Its text has {{placeholders}}: a Bot turn fills them from the "
                                                    "automation's values, which may differ from the routine's"))
        flow = {"name": (row["title"] or "Routine")[:120], "owner": "bot:" + bot, "enabled": enabled,
                "trigger": trigger, "steps": [{"id": "turn", "type": "bot_turn", "bot": "bot:" + bot, "prompt": text}],
                "source": {"kind": "routine", "id": sid}}
        do = "routine"
        if automations.is_briefing_routine(row) and trigger["type"] == "schedule":
            # The hub's Market briefing does this now: the routine becomes that built-in, on the routine's own time
            # and words, so the two never both run.
            flow = {**automations.briefing_flow(trigger["cron"], trigger["tz"], text), "builtin": True,
                    "enabled": enabled, "source": flow["source"]}
            do = "adopt_briefing"
        out.append({"kind": "routine", "id": sid, "title": row["title"], "becomes": flow, "flags": flags,
                    "_do": (do, {"next_due": row["next_due"]})})
    return out


def _rule_step(n, row):
    """One wake rule as its own Filter step: the event (and the rule's simple conditions) as `when`, its outcome as the
    action, and the whole row in the action's args, which is what rules.py reads back."""
    when = _json(row["when_json"], {})
    params = _json(row["params_json"], {})
    conds = [] if row["event"] == "*" else [{"field": "event", "op": "is", "value": row["event"]}]
    for key, value in sorted(when.items()):
        if isinstance(value, (str, int, float, bool)) and F.FIELD.fullmatch(str(key)) and len(conds) < F.MAX_CONDS:
            conds.append({"field": "task." + str(key), "op": "is", "value": value})
    rule = {k: row[k] for k in ("id", "scope_kind", "scope_id", "event", "position", "note", "created_by", "created",
                                 "updated", "revision") if k in row.keys()}
    rule["action_by"] = dict(row).get("action_by")
    rule["when"] = when
    do = OUTCOME_DO.get(row["then_outcome"], "wake_bot")
    if row["then_outcome"] == "action" and params.get("action") in F.ACTIONS:
        do = params["action"]
    return {"id": f"r{n}", "type": "filter", "enabled": bool(row["enabled"]),
            "rules": [{"when": conds, "match": "all", "stop": True,
                       "then": [{"do": do, "args": {"outcome": row["then_outcome"], "params": params, "rule": rule}}]}]}


def _wake_rules(c, done, me):
    from . import tico_notices
    rows = [r for r in c.execute("SELECT * FROM rules ORDER BY scope_kind, scope_id, position, created, id").fetchall()
            if not tico_notices.is_builtin_rule(r["id"]) and ("wake_rule", r["id"]) not in done]
    groups = {}
    for row in rows:
        groups.setdefault((row["scope_kind"], row["scope_id"] or ""), []).append(row)
    out = []
    for (scope, ident), members in groups.items():
        if scope == "bot" and H.bot(c, ident):
            name, owner = f"What wakes {_bot_name(c, ident)}", "bot:" + ident
        else:
            words = {"team": "every bot", "department": f"the {ident} bots", "type": f"bots on {ident} tasks",
                     "task": f"bots on task {ident}"}.get(scope, f"{scope} {ident}".strip())
            name, owner = f"What wakes {words}", me
        flow = {"name": name[:120], "owner": owner, "enabled": True, "wakes": {"scope_kind": scope, "scope_id": ident},
                "trigger": {"type": "event", "name": "tico.wake"},
                "steps": [_rule_step(n + 1, row) for n, row in enumerate(members)],
                "source": [{"kind": "wake_rule", "id": row["id"]} for row in members]}
        group = {"scope_kind": scope, "scope_id": ident, "rules": [row["id"] for row in members]}
        for row in members:
            flags = []
            if owner != "bot:" + ident:
                flags.append(_flag(row["id"], "scope", f"A {scope} rule, not one bot's: it goes in \"{name}\", owned "
                                                       "by you"))
            if not owner:
                flags.append(_flag(row["id"], "no_owner", "No person to own it; it stays a rule", keeps=True))
            out.append({"kind": "wake_rule", "id": row["id"], "title": f"{row['event']} → {row['then_outcome']}",
                        "becomes": flow, "flags": flags, "_do": ("wakes", group)})
    return out


WAKES_BUILTIN = "auto_builtin_wakes"   # the hub's own "What wakes bots" (automations.ensure_builtins)


def wakes_builtin(owner):
    """`What wakes bots`: the built-in wake rules (rules.py, which keeps deciding by them) shown read-only, a Filter
    step per ten rules. Its `event` trigger is never emitted and `readonly` keeps the engine off it."""
    from . import rules
    listed = rules._builtins()
    steps = []
    for start in range(0, len(listed), F.MAX_RULES):
        chunk = listed[start:start + F.MAX_RULES]
        steps.append({"id": f"b{start // F.MAX_RULES + 1}", "type": "filter", "rules": [
            {"when": [] if r["event"] == "*" else [{"field": "event", "op": "is", "value": r["event"]}],
             "then": [{"do": OUTCOME_DO.get(r["then"], "wake_bot"), "args": {"outcome": r["then"], "rule": r["id"],
                                                                           "words": r.get("words", "")[:300]}}],
             "stop": True} for r in chunk]})
    return {**_mirror("What wakes bots", owner, "wakes", {"on": True}, {"kind": "builtin", "id": "wake-builtins"}),
            "steps": steps}


def _builtins(c, done, me):
    """The built-in wake rules, task rules, system jobs and the Health Monitor: read-only built-ins. The hub makes
    `What wakes bots` itself once the redesign is on; the converter then only records it (`adopt`)."""
    from . import system_routines as SR
    out = []
    if ("builtin", "wake-builtins") not in done and me:
        made = c.execute("SELECT 1 FROM automations WHERE id=? AND deleted_at IS NULL", (WAKES_BUILTIN,)).fetchone()
        out.append({"kind": "builtin", "id": "wake-builtins", "title": "Built-in wake rules", "becomes": wakes_builtin(me),
                    "flags": [], "_do": ("adopt", {}) if made else ("mirror", {})})
    if _table(c, "task_rules"):
        for row in c.execute("SELECT * FROM task_rules ORDER BY created, id").fetchall():
            if ("task_rule", row["id"]) in done or not me:
                continue
            controls = {"on": bool(row["enabled"]), "preset": row["preset"], "at": row["at"],
                        "department": row["department"], "triggers": _json(row["triggers_json"], []),
                        "actions": _json(row["actions_json"], [])}
            flow = _mirror(row["name"], me, "task_rule", controls, {"kind": "task_rule", "id": row["id"]})
            out.append({"kind": "task_rule", "id": row["id"], "title": row["name"], "becomes": flow, "flags": [],
                        "_do": ("mirror", {})})
    cfg = SR.config(c)
    for job in SR.JOBS:
        oid = "job:" + job.key
        if ("system_job", oid) in done or not me:
            continue
        controls = {"on": True, "schedule": job.schedule, **(cfg.get(job.key) or {})}
        if job.key == "stale_review":
            control = cfg[job.key]
            flow = {"name": job.name, "owner": me, "enabled": bool(control["on"]),
                    "trigger": {"type": "schedule", "cron": _cron(control["preset"], control["at"]), "tz": _zone()},
                    "steps": [{"id": "tasks", "type": "find", "source": "tasks", "query": "open tasks that look finished "
                               "or forgotten", "limit": 20},
                              {"id": "verdict", "type": "decide", "set": "stale-review@1", "out": "d1", "level": "low"},
                              {"id": "route", "type": "paths", "paths": [
                                  {"name": "Suggest to the owner", "when": [{"field": "d1.verdict", "op": "is_not",
                                                                             "value": "leave"}],
                                   "steps": [{"id": "suggest", "type": "action", "do": "leave_for_you", "args": {}}]}]}],
                    "source": {"kind": "system_job", "id": oid}}
            out.append({"kind": "system_job", "id": oid, "title": job.name, "becomes": flow, "flags": [],
                        "_do": ("stale_review", {"on": bool(control["on"])})})
            continue
        flow = _mirror(job.name, me, "job." + job.key, controls, {"kind": "system_job", "id": oid}, job.what)
        out.append({"kind": "system_job", "id": oid, "title": job.name, "becomes": flow, "flags": [],
                    "_do": ("mirror", {})})
    health = H.bot(c, "health-monitor")
    if health and ("health_monitor", "bot:health-monitor") not in done and me:
        flow = _mirror("Health Monitor", me, "health", {"on": health.get("state") == "active", "bot": "health-monitor"},
                       {"kind": "bot", "id": "health-monitor"}, "Finds install problems and files them for BotOps.")
        out.append({"kind": "health_monitor", "id": "bot:health-monitor", "title": "Health Monitor", "becomes": flow,
                    "flags": [], "_do": ("mirror", {})})
    return out


def _inboxes(c, done):
    from . import people as P, routines, views
    roster = views.roster(c)
    out = []
    for box in routines.message_bot_mailboxes(c):
        oid = "inbox:" + box["address"]
        if ("inbox", oid) in done:
            continue
        person = P.person(box["person_id"], roster) or {}
        name = person.get("name") or box["person_id"]
        found = c.execute("SELECT content FROM mail_agent_instructions WHERE bot=?", (box["bot"],)).fetchone() \
            if _table(c, "mail_agent_instructions") else None
        prompt = (found["content"] if found and (found["content"] or "").strip() else DEFAULT_PROMPT.format(name=name))
        prompt = prompt.rstrip() + MESSAGE_PART
        flags = []
        if len(prompt) > F.MAX_PROMPT:
            flags.append(_flag(oid, "too_long", f"The Inbox Manager's instructions are longer than {F.MAX_PROMPT:,} "
                                                "characters; the inbox stays with its bot until they are shorter",
                               keeps=True))
        bot = H.bot(c, box["bot"]) or {}
        flow = {"name": f"{name}'s inbox"[:120], "owner": "person:" + box["person_id"], "enabled": True,
                "trigger": {"type": "message", "inbox": box["address"]},
                "steps": [{"id": "read", "type": "llm", "as": "assistant:" + box["person_id"], "prompt": prompt[:F.MAX_PROMPT],
                           "out": "triage"}],
                "source": [{"kind": "inbox", "id": box["address"]}, {"kind": "bot", "id": box["bot"]}]}
        out.append({"kind": "inbox", "id": oid, "title": f"{name}'s inbox ({_bot_name(c, box['bot'])})",
                    "becomes": flow, "flags": flags,
                    "_do": ("inbox", {"bot": box["bot"], "state": bot.get("state") or "active"})})
    return out


def _bots(c, done):
    from . import ceo_bot
    out = []
    ceo = H.bot(c, ceo_bot.SLUG)
    if ceo and ("bot", "bot:" + ceo_bot.SLUG) not in done:
        current = (ceo.get("display_name") or "").strip()
        default = current in ("", ceo_bot.NAME, ceo_bot.OLD_NAME, STRATEGY_NAME)
        flags = [] if default else [_flag("bot:" + ceo_bot.SLUG, "custom_name",
                                          f"Someone named it {current}; it keeps that name and becomes the Strategy "
                                          "bot")]
        out.append({"kind": "bot", "id": "bot:" + ceo_bot.SLUG, "title": current or ceo_bot.NAME,
                    "becomes": {"slug": ceo_bot.SLUG, "display_name": STRATEGY_NAME if default else current,
                                "role": "the strategy bot"},
                    "flags": flags, "_do": ("rename", {"before": ceo.get("display_name"), "rename": default})})
    return out


def _unchanged(c):
    out = []
    if _table(c, "listening_destinations"):
        for row in c.execute("SELECT key, receiver FROM listening_destinations ORDER BY key").fetchall():
            out.append({"kind": "destination", "id": "destination:" + row["key"], "title": row["key"],
                        "becomes": "unchanged", "flags": [], "_do": None})
    if _table(c, "goals"):
        for row in c.execute("SELECT id, title FROM goals ORDER BY created, id").fetchall():
            out.append({"kind": "goal", "id": "goal:" + row["id"], "title": row["title"], "becomes": "unchanged",
                        "flags": [], "_do": None})
    return out


def _limit(oid, title, hourly, where):
    amount = half(hourly)
    flags = []
    if amount * 2 > float(hourly) + 1e-9:
        flags.append(_flag(oid, "rounding", f"${float(hourly):.2f} an hour is ${amount:.2f} per 30 minutes after "
                                            f"rounding up: up to ${amount * 2:.2f} an hour"))
    return {"kind": "spend_limit", "id": oid, "title": title, "becomes": {"per_30m_usd": amount, "hourly_usd": None},
            "flags": flags, "_do": ("limit", {**where, "per_30m_usd": amount})}


def _limits(c, done):
    from . import usage_limits
    out = []
    if _table(c, "usage_limits") and "hourly_usd" in _columns(c, "usage_limits"):
        for row in c.execute("SELECT bot, hourly_usd FROM usage_limits WHERE hourly_usd IS NOT NULL ORDER BY bot"):
            if ("spend_limit", "limit:" + row["bot"]) not in done and row["hourly_usd"] > 0:
                out.append(_limit("limit:" + row["bot"], f"{row['bot']} hourly limit", row["hourly_usd"],
                                  {"table": "usage_limits", "key": row["bot"]}))
    if _table(c, "usage_pools"):
        for row in c.execute("SELECT scope, hourly_usd FROM usage_pools WHERE hourly_usd IS NOT NULL ORDER BY scope"):
            oid = "limit:pool:" + row["scope"]
            if ("spend_limit", oid) not in done and row["hourly_usd"] > 0:
                out.append(_limit(oid, f"{row['scope']} hourly limit", row["hourly_usd"],
                                  {"table": "usage_pools", "key": row["scope"]}))
    stored = _json(_meta(c, usage_limits.KEY), {})
    hourly = usage_limits._amount(stored.get("hourly_usd"))
    if hourly and ("spend_limit", "limit:company-default") not in done:
        out.append(_limit("limit:company-default", "Company default hourly limit", hourly, {"table": "registry"}))
    return out


def _raised(values):
    """A budget raised to the guard, unless set higher or to 0 (no limit)."""
    return {k: (GUARD[k] if isinstance(v, int) and 0 < v < GUARD[k] else v) for k, v in values.items()}


def _budgets(c, done):
    from . import turn_budgets as TB
    out = []
    stored = _json(_meta(c, TB.TEAM_KEY), {})
    team = TB.team(c)
    after = _raised(team)
    if ("turn_budget", "budget:team") not in done:
        out.append({"kind": "turn_budget", "id": "budget:team", "title": "Team turn budgets", "becomes": after,
                    "flags": [], "_do": ("budget_team", {"raise": after != team and bool(stored)})})
    for row in c.execute("SELECT bot, config_json FROM bot_config ORDER BY bot").fetchall():
        mine = {k: v for k, v in TB.own(_json(row["config_json"], {})).items() if v is not None}
        if not mine or ("turn_budget", "budget:" + row["bot"]) in done:
            continue
        raised = _raised(mine)
        out.append({"kind": "turn_budget", "id": "budget:" + row["bot"], "title": f"{row['bot']} turn budget",
                    "becomes": raised if raised != mine else "unchanged", "flags": [],
                    "_do": ("budget_bot", {"bot": row["bot"], "values": raised}) if raised != mine else None})
    return out


# ---------------------------------------------------------------------------------------------------- the report
def public(obj):
    return {k: v for k, v in obj.items() if not k.startswith("_")}


def report(c, who):
    objects = plan(c, who)
    counts = {}
    for obj in objects:
        counts[obj["kind"]] = counts.get(obj["kind"], 0) + 1
    flags = [f for obj in objects for f in obj["flags"]]
    open_ = [f["id"] for f in flags if not f["accepted"]]
    return {"objects": [public(o) for o in objects], "counts": {**counts, "total": len(objects)},
            "flags": {"total": len(flags), "open": len(open_)}, "ready": not open_, "migration": current(c)}


def current(c):
    """The latest migration: {id, state, created, expires, restorable}, or None."""
    if not _table(c, "redesign_migrations"):
        return None
    row = c.execute("SELECT id, state, created, expires, finished, restored_at FROM redesign_migrations "
                    "ORDER BY created DESC, id DESC LIMIT 1").fetchone()
    if not row:
        return None
    out = dict(row)
    out["restorable"] = row["state"] in ("converted", "interrupted") and row["expires"] > _now()
    return out


def _accept_ids(objects, accept):
    """The flag ids `accept` names. Unknown names are refused, so a typo never reads as a yes."""
    flags = {f["id"]: f for o in objects for f in o["flags"]}
    by_obj = {o["id"]: [f["id"] for f in o["flags"]] for o in objects}
    out = set()
    for item in accept or []:
        if isinstance(item, dict):
            named = item.get("flags")
            if named is None:
                ident = item.get("id")
                if ident in flags:
                    out.add(ident)
                elif ident in by_obj:
                    out.update(by_obj[ident])
                else:
                    raise Problem("invalid", f"No flag or object {ident} in the dry run", 422)
                continue
            for flag in named if isinstance(named, list) else [named]:
                fid = flag.get("id") if isinstance(flag, dict) else flag
                if fid not in flags:
                    raise Problem("invalid", f"No flag {fid} in the dry run", 422)
                out.add(fid)
        elif item in flags:
            out.add(item)
        elif item in by_obj:
            out.update(by_obj[item])
        else:
            raise Problem("invalid", f"No flag or object {item} in the dry run", 422)
    return out


def resolve(c, who, accept):
    objects = plan(c, who)
    ids = _accept_ids(objects, accept)
    for fid in sorted(ids):
        c.execute("INSERT OR IGNORE INTO redesign_migration_accepts(flag, accepted_by, at) VALUES(?,?,?)",
                  (fid, who.actor, _now()))
    if ids:
        H.event(c, who.actor, "redesign.migration.resolved", "", {"flags": len(ids)})
    return report(c, who)


# ---------------------------------------------------------------------------------------------------- convert
def _limit_now(c, where):
    """A spend limit's two amounts as stored now: a bot's or a pool's row, or the company default's JSON."""
    from . import usage_limits
    if where["table"] == "registry":
        stored = _json(_meta(c, usage_limits.KEY), {})
        return {"hourly_usd": stored.get("hourly_usd"), "per_30m_usd": stored.get("per_30m_usd")}
    column = "bot" if where["table"] == "usage_limits" else "scope"
    row = c.execute(f"SELECT * FROM {where['table']} WHERE {column}=?", (where["key"],)).fetchone()
    row = dict(row) if row else {}
    return {"hourly_usd": row.get("hourly_usd"), "per_30m_usd": row.get("per_30m_usd")}


def _budget_now(c, bot):
    """The declared turn budgets: the team's (bot None) or one bot's."""
    from . import turn_budgets as TB
    if bot is None:
        return _json(_meta(c, TB.TEAM_KEY), {})
    row = c.execute("SELECT config_json FROM bot_config WHERE bot=?", (bot,)).fetchone()
    return _json(row["config_json"] if row else None, {})


def _same(a, b):
    """Two stored values alike (amounts compared to the cent's fraction, so 0.2 == 0.20000000001)."""
    if isinstance(a, (int, float)) and isinstance(b, (int, float)) and not isinstance(a, bool) and not isinstance(b, bool):
        return abs(float(a) - float(b)) < 1e-6
    return a == b


def _snapshot(c, objects):
    """What the convert will change, as it is now, and what the convert changes it to: restore puts back only those
    fields, and only where they still hold what the convert wrote. Nothing the convert does not touch is kept."""
    from . import ceo_bot
    routine_ids = [o["id"] for o in objects if o["kind"] == "routine"]
    rule_ids = [o["id"] for o in objects if o["kind"] == "wake_rule"]

    def rows(sql, ids):
        found = []
        for start in range(0, len(ids), 500):
            chunk = ids[start:start + 500]
            found += [dict(r) for r in c.execute(sql.format(",".join("?" * len(chunk))), chunk)]
        return found
    snap = {"schedules": rows("SELECT * FROM schedules WHERE id IN ({})", routine_ids),
            "schedule_config": rows("SELECT * FROM schedule_config WHERE schedule_id IN ({})", routine_ids),
            "rules": rows("SELECT * FROM rules WHERE id IN ({})", rule_ids),
            "changes": {}, "bots": {}}
    for obj in objects:
        do = obj.get("_do")
        if not do:
            continue
        kind, args = do
        if kind == "limit":
            snap["changes"][obj["id"]] = {"kind": "limit", "where": {k: args.get(k) for k in ("table", "key")},
                                          "before": _limit_now(c, args),
                                          "after": {"hourly_usd": None, "per_30m_usd": args["per_30m_usd"]}}
        if kind == "budget_team" and args["raise"]:
            now = _budget_now(c, None)
            keys = [k for k, v in obj["becomes"].items() if not _same(now.get(k), v)]
            snap["changes"][obj["id"]] = {"kind": "budget", "bot": None, "before": {k: now.get(k) for k in keys},
                                          "after": {k: obj["becomes"][k] for k in keys}}
        if kind == "budget_bot":
            now = _budget_now(c, args["bot"])
            keys = [k for k, v in args["values"].items() if not _same(now.get(k), v)]
            snap["changes"][obj["id"]] = {"kind": "budget", "bot": args["bot"], "before": {k: now.get(k) for k in keys},
                                          "after": {k: args["values"][k] for k in keys}}
        if kind == "inbox":
            snap["bots"][args["bot"]] = {"state": args["state"], "object": obj["id"]}
        if kind == "rename":
            snap["bots"][ceo_bot.SLUG] = {"display_name": args["before"], "renamed": bool(args["rename"]),
                                          "object": obj["id"]}
        if kind == "stale_review":
            snap["stale_review"] = args["on"]
    return snap


def _save(c, who, flow):
    from . import automations
    aid = (WAKES_PREFIX if flow.get("wakes") else "auto_mig_") + H.new_id()
    checked = automations._checked(c, flow)
    via = "migration" if not who.via else f"{who.via}, migration"
    automations._save(c, who.actor, aid, checked, None, via=via)
    return aid


def _adopt(c, who, flow):
    """The Librarian's briefing routine as the hub's Market briefing built-in: made if the hub has not made it yet
    (or a restore took it away), then given the routine's time, words and on/off."""
    from . import automations
    aid = "auto_builtin_" + automations.BRIEFING_KEY
    row = c.execute("SELECT * FROM automations WHERE id=?", (aid,)).fetchone()
    if row and row["deleted_at"]:
        c.execute("UPDATE automations SET deleted_at=NULL WHERE id=?", (aid,))
    via = "migration" if not who.via else f"{who.via}, migration"
    automations._save(c, who.actor, aid, automations._checked(c, flow), automations.flow_of(row) if row else None,
                      via=via)
    return aid


def _mark(c, kind, ident, mid, aid):
    c.execute("INSERT OR REPLACE INTO redesign_migrated(kind, id, migration, automation) VALUES(?,?,?,?)",
              (kind, ident, mid, aid))


def _convert_one(c, who, mid, obj, group_done):
    """One object, in the caller's transaction. Returns the automation id (or None) it made."""
    from . import ceo_bot, team_rules, turn_budgets as TB, usage_limits
    kind, args = obj["_do"]
    now = _now()
    if kind in ("routine", "adopt_briefing"):
        live = c.execute("SELECT next_due FROM schedules WHERE id=? AND deleted_at IS NULL", (obj["id"],)).fetchone()
        if not live:
            return None
        aid = _save(c, who, obj["becomes"]) if kind == "routine" else _adopt(c, who, obj["becomes"])
        if obj["becomes"]["trigger"]["type"] == "schedule" and live["next_due"]:
            # The routine's own next fire: the occurrence it would have run is the automation's, once.
            c.execute("UPDATE automations SET next_due=? WHERE id=?", (live["next_due"], aid))
        c.execute("UPDATE schedules SET deleted_at=?, next_due=NULL, updated_at=? WHERE id=?", (now, now, obj["id"]))
        H.event(c, who.actor, "routine.converted", obj["id"], {"automation": aid})
        _mark(c, "routine", obj["id"], mid, aid)
        return aid
    if kind == "wakes":
        key = (args["scope_kind"], args["scope_id"])
        if key in group_done:
            return group_done[key]
        aid = _save(c, who, obj["becomes"])
        for rid in args["rules"]:
            c.execute("DELETE FROM rules WHERE id=?", (rid,))
            _mark(c, "wake_rule", rid, mid, aid)
        group_done[key] = aid
        return aid
    if kind == "adopt":   # the hub's own built-in: recorded, never removed by a restore
        _mark(c, "builtin", obj["id"], mid, None)
        return None
    if kind == "mirror":
        aid = _save(c, who, obj["becomes"])
        _mark(c, {"builtin": "builtin", "task_rule": "task_rule", "system_job": "system_job",
                  "health_monitor": "health_monitor"}[obj["kind"]], obj["id"], mid, aid)
        return aid
    if kind == "stale_review":
        aid = _save(c, who, obj["becomes"])
        if args["on"]:
            team_rules.save(c, who.actor, {"stale_review": False})   # the automation runs it now, not the job
        _mark(c, "system_job", obj["id"], mid, aid)
        return aid
    if kind == "inbox":
        aid = _save(c, who, obj["becomes"])
        if args["state"] == "active":
            H.status_set(c, who.actor, args["bot"], state="paused",
                         reason="Retired by the redesign: its inbox is an automation now")
        _mark(c, "inbox", obj["id"], mid, aid)
        return aid
    if kind == "rename":
        if args["rename"]:
            ceo_bot._rename(c, who.actor, STRATEGY_NAME)
        _mark(c, "bot", obj["id"], mid, None)
        return None
    if kind == "limit":
        if args["table"] == "registry":
            stored = _json(_meta(c, usage_limits.KEY), {})
            stored.update(per_30m_usd=args["per_30m_usd"], hourly_usd=None)
            _set_meta(c, usage_limits.KEY, json.dumps(stored, sort_keys=True))
        else:
            column = "bot" if args["table"] == "usage_limits" else "scope"
            c.execute(f"UPDATE {args['table']} SET per_30m_usd=?, hourly_usd=NULL WHERE {column}=?",
                      (args["per_30m_usd"], args["key"]))
        _mark(c, "spend_limit", obj["id"], mid, None)
        return None
    if kind == "budget_team":
        if args["raise"]:
            stored = _json(_meta(c, TB.TEAM_KEY), {})
            stored.update(obj["becomes"])
            _set_meta(c, TB.TEAM_KEY, json.dumps(stored, sort_keys=True))
        _mark(c, "turn_budget", obj["id"], mid, None)
        return None
    if kind == "budget_bot":
        row = c.execute("SELECT config_json FROM bot_config WHERE bot=?", (args["bot"],)).fetchone()
        declared = _json(row["config_json"] if row else None, {})
        declared.update(args["values"])
        c.execute("UPDATE bot_config SET config_json=?, revision=revision+1 WHERE bot=?",
                  (json.dumps(declared, sort_keys=True), args["bot"]))
        _mark(c, "turn_budget", obj["id"], mid, None)
        return None
    raise AssertionError(kind)


def convert(store, who, accept=None):
    """Snapshot, then one transaction per object. Refused while a flag has no yes (409) or a converted migration can
    still be restored (409: restore it or let it expire first)."""
    with store.transaction() as c:
        _require_on(c)
        ensure(c)
        _expire(c, _now())
        # In the same write that starts a convert, so two converts can never both start (each would make its own
        # "What wakes" automations from the same rules).
        busy = c.execute("SELECT id, state, expires FROM redesign_migrations WHERE state IN "
                         f"({','.join('?' * len(OPEN_STATES))}) ORDER BY created DESC LIMIT 1", OPEN_STATES).fetchone()
        if busy and busy["state"] == "converting":
            raise Problem("conflict", "A convert is running; wait for it to finish", 409)
        if busy:
            raise Problem("conflict", f"The last convert ({busy['state']}) can still be restored; restore it or wait "
                                      f"until {busy['expires']}", 409)
        objects = plan(c, who)
        if accept:
            for fid in sorted(_accept_ids(objects, accept)):
                c.execute("INSERT OR IGNORE INTO redesign_migration_accepts(flag, accepted_by, at) VALUES(?,?,?)",
                          (fid, who.actor, _now()))
            objects = plan(c, who)
        open_ = [f["id"] for o in objects for f in o["flags"] if not f["accepted"]]
        if open_:
            raise Problem("flags_open", f"{len(open_)} flag(s) need your yes first (resolve, or convert with accept)",
                          409, extra={"flags": open_[:200]})
        work = [o for o in objects if o["_do"] and not any(f.get("keeps") for f in o["flags"])]
        mid, now = "mig_" + H.new_id(), _now()
        expires = _stamp(_at(now) + timedelta(hours=KEEP_HOURS))
        c.execute("INSERT INTO redesign_migrations(id, state, actor, created, expires, snapshot_json) "
                  "VALUES(?,?,?,?,?,?)", (mid, "converting", who.actor, now, expires,
                                          json.dumps(_snapshot(c, work), sort_keys=True, default=str)))
        H.event(c, who.actor, "redesign.migration.snapshot", mid, {"objects": len(work)})
    converted, failed, groups = [], [], {}
    for obj in work:
        try:
            with store.transaction() as c:
                aid = _convert_one(c, who, mid, obj, groups)
            converted.append({"kind": obj["kind"], "id": obj["id"], **({"automation": aid} if aid else {})})
        except Problem as exc:
            failed.append({"kind": obj["kind"], "id": obj["id"], "detail": exc.detail})
        except Exception as exc:   # one object's surprise must not leave the rest half-converted
            log.exception("redesign migration: %s %s did not convert", obj["kind"], obj["id"])
            failed.append({"kind": obj["kind"], "id": obj["id"], "detail": type(exc).__name__})
    kept = [{"kind": o["kind"], "id": o["id"]} for o in objects if o["_do"] and o not in work]
    result = {"converted": len(converted), "failed": failed, "kept": kept}
    with store.transaction() as c:
        c.execute("UPDATE redesign_migrations SET state='converted', finished=?, result_json=? WHERE id=? "
                  "AND state IN ('converting','interrupted')",
                  (_now(), json.dumps(result, sort_keys=True), mid))
        from . import audit_log
        audit_log.write(c, who.actor, "redesign_migration:" + mid, None, {"converted": len(converted),
                                                                          "failed": len(failed)}, who.via or None)
        H.event(c, who.actor, "redesign.migration.converted", mid, {"converted": len(converted), "failed": len(failed)})
    return {"migration": mid, "snapshot": {"id": mid, "expires": expires}, "expires": expires,
            "converted": converted, "failed": failed, "kept": kept,
            "counts": {"converted": len(converted), "failed": len(failed), "kept": len(kept)}}


# ---------------------------------------------------------------------------------------------------- restore
def _expire(c, now):
    """A snapshot past its day is dropped, a convert cut off by a restart included. What it converted stays converted
    (and its routines stay held)."""
    if not _table(c, "redesign_migrations"):
        return 0
    return c.execute("UPDATE redesign_migrations SET state='expired', snapshot_json=NULL "
                     "WHERE state IN ('converted','interrupted','converting') AND expires<=?", (now,)).rowcount


def prune(c, now):
    """The scheduler's hourly sweep: snapshots older than a day go."""
    return _expire(c, now)


def interrupted(c):
    """At startup: a convert still `converting` was cut off by the restart. It is marked `interrupted`, which restore
    undoes from its snapshot like a finished one (only what it converted) and the sweep expires after its day."""
    if not _table(c, "redesign_migrations"):
        return 0
    return c.execute("UPDATE redesign_migrations SET state='interrupted', finished=? WHERE state='converting'",
                     (_now(),)).rowcount


def _put(c, table, row):
    columns = [k for k in row if k in _columns(c, table)]
    c.execute(f"INSERT OR REPLACE INTO {table}({','.join(columns)}) VALUES({','.join('?' * len(columns))})",
              [row[k] for k in columns])


def _set_limit(c, where, values):
    from . import usage_limits
    if where["table"] == "registry":
        stored = _json(_meta(c, usage_limits.KEY), {})
        stored.update(values)
        _set_meta(c, usage_limits.KEY, json.dumps(stored, sort_keys=True))
        return
    column = "bot" if where["table"] == "usage_limits" else "scope"
    c.execute(f"UPDATE {where['table']} SET hourly_usd=?, per_30m_usd=? WHERE {column}=?",
              (values.get("hourly_usd"), values.get("per_30m_usd"), where["key"]))


def _set_budget(c, bot, values):
    from . import turn_budgets as TB
    declared = _budget_now(c, bot)
    for k, v in values.items():
        if v is None:
            declared.pop(k, None)
        else:
            declared[k] = v
    if bot is None:
        _set_meta(c, TB.TEAM_KEY, json.dumps(declared, sort_keys=True))
    else:
        c.execute("UPDATE bot_config SET config_json=?, revision=revision+1 WHERE bot=?",
                  (json.dumps(declared, sort_keys=True), bot))


def _held_runs(c, aid, ref_prefix):
    """What restore does with a converted automation's unfinished runs. A run that did something (a turn started, an
    action done) is left to finish, and so is one the old object cannot take back (an event's): firing it again
    would do it twice. A run that has done nothing yet on what the old object takes back itself (a schedule's
    occurrence, a mail the Inbox Manager reads) is skipped, so the old object does it once. Returns the earliest
    schedule occurrence skipped, for the routine to fire."""
    now, back = _now(), None
    for run in c.execute("SELECT id, trigger_ref, state_json FROM automation_runs WHERE automation_id=? "
                         "AND status='queued'", (aid,)).fetchall():
        ref = str(run["trigger_ref"] or "")
        if not ref.startswith(ref_prefix) or _json(run["state_json"], {}).get("steps"):
            continue
        c.execute("UPDATE automation_runs SET status='skipped', finished=? WHERE id=? AND status='queued'",
                  (now, run["id"]))
        if ref.startswith("schedule:"):
            due = ref[len("schedule:"):]
            back = due if back is None or due < back else back
    return back


def restore(c, who):
    """Put back what the convert changed and delete what it made. A finished convert and one cut off by a restart
    (`interrupted`) are restored alike: only the objects it converted. A field changed since the convert is left as it
    is and listed in `skipped`. 404 with no migration, 410 once it expired."""
    from . import ceo_bot, team_rules
    from .scheduler import next_due
    _require_on(c)
    ensure(c)
    now = _now()
    _expire(c, now)
    live = current(c)
    if not live or live["state"] in ("restored",):
        raise Problem("not_found", "There is no converted migration to restore", 404)
    if live["state"] not in ("converted", "interrupted"):
        raise Problem("gone", "The snapshot is kept one day after converting; this one has expired", 410)
    mid = live["id"]
    snap = json.loads(c.execute("SELECT snapshot_json FROM redesign_migrations WHERE id=?", (mid,)).fetchone()[0])
    marked = {(r["kind"], r["id"]): r["automation"]
              for r in c.execute("SELECT kind, id, automation FROM redesign_migrated WHERE migration=?", (mid,))}
    done = {ident for _, ident in marked}
    made = {aid for aid in marked.values() if aid}
    skipped = []
    # The routines: the row as it was, firing next when its automation would have (no double fire, no gap). A run
    # its automation queued and has not started gives its occurrence back to the routine.
    routines_back = 0
    for row in snap["schedules"]:
        aid = marked.get(("routine", row["id"]))
        if not aid:
            continue
        auto = c.execute("SELECT next_due FROM automations WHERE id=?", (aid,)).fetchone()
        due = (auto["next_due"] if auto else None) or row.get("next_due")
        owed = _held_runs(c, aid, "schedule:")
        if row.get("cron") and not row.get("event_name"):
            if owed:
                due = owed
            elif not due or due <= now:
                tz = next((sc.get("timezone") for sc in snap["schedule_config"] if sc["schedule_id"] == row["id"]),
                          None)
                due = _stamp(next_due(row["cron"], _at(now), tz or "America/Los_Angeles"))
        _put(c, "schedules", {**row, "deleted_at": None, "next_due": due if row.get("cron") else None,
                              "updated_at": now})
        routines_back += 1
    restored_routines = {r["id"] for r in snap["schedules"] if ("routine", r["id"]) in marked}
    for row in snap["schedule_config"]:
        if row["schedule_id"] in restored_routines:
            _put(c, "schedule_config", row)
    rules_back = 0
    for row in snap["rules"]:
        if ("wake_rule", row["id"]) in marked:
            _put(c, "rules", row)
            rules_back += 1
    for oid, change in (snap.get("changes") or {}).items():
        if oid not in done:
            continue
        now_values = _limit_now(c, change["where"]) if change["kind"] == "limit" else _budget_now(c, change["bot"])
        if not all(_same(now_values.get(k), v) for k, v in change["after"].items()):
            skipped.append({"id": oid, "why": "changed after the convert; left as it is"})
            continue
        if change["kind"] == "limit":
            _set_limit(c, change["where"], change["before"])
        else:
            _set_budget(c, change["bot"], change["before"])
    for bot, was in snap["bots"].items():
        if was.get("object") and was["object"] not in done:
            continue
        if "display_name" in was and was.get("renamed", True):
            if ((H.bot(c, bot) or {}).get("display_name") or "") == STRATEGY_NAME:
                ceo_bot._rename(c, who.actor, was["display_name"] or "")
            else:
                skipped.append({"id": was.get("object") or "bot:" + bot, "why": "renamed after the convert"})
        if was.get("state") == "active":
            if (H.bot(c, bot) or {}).get("state") == "paused":
                H.status_set(c, who.actor, bot, state="active", reason="The redesign's convert was restored")
            else:
                skipped.append({"id": was.get("object") or "bot:" + bot, "why": "its bot changed after the convert"})
    for (kind, _), aid in marked.items():
        if kind == "inbox" and aid:
            _held_runs(c, aid, "mail:")
    if snap.get("stale_review") and any(k == "system_job" and i == "job:stale_review" for k, i in marked):
        team_rules.save(c, who.actor, {"stale_review": True})
    for aid in sorted(made):
        # Its runs already under way finish (above).
        if aid.startswith("auto_builtin_"):
            # An adopted built-in is the hub's: it stays, paused, while the routine it took over runs again.
            from . import automations
            row = c.execute("SELECT * FROM automations WHERE id=? AND deleted_at IS NULL", (aid,)).fetchone()
            if row and row["enabled"]:
                before = automations.flow_of(row)
                automations._save(c, who.actor, aid, {**before, "enabled": False}, before, via="migration restore")
        else:
            c.execute("UPDATE automations SET deleted_at=?, enabled=0 WHERE id=? AND deleted_at IS NULL", (now, aid))
    c.execute("DELETE FROM redesign_migrated WHERE migration=?", (mid,))
    c.execute("UPDATE redesign_migrations SET state='restored', restored_at=?, snapshot_json=NULL WHERE id=?", (now, mid))
    from . import audit_log
    audit_log.write(c, who.actor, "redesign_migration:" + mid, {"state": live["state"]}, {"state": "restored"},
                    who.via or None)
    H.event(c, who.actor, "redesign.migration.restored", mid, {"automations": len(made), "skipped": len(skipped)})
    return {"migration": mid, "restored": True, "automations_removed": len(made), "routines": routines_back,
            "rules": rules_back, "skipped": skipped}


# ---------------------------------------------------------------------------------------------------- hooks
def holds(c, kind, ident):
    """Whether a converted object is held: a routine the convert soft-deleted is never brought back by a `create` with
    its key (a built-in routine re-seeded at startup), so it cannot fire beside its automation."""
    try:
        return c.execute("SELECT 1 FROM redesign_migrated WHERE kind=? AND id=?", (kind, ident)).fetchone() is not None
    except Exception:   # sqlite3.OperationalError: a database from before the converter
        return False


def converted(c):
    """Whether a convert happened that was not restored (its snapshot kept or already expired)."""
    try:
        return c.execute("SELECT 1 FROM redesign_migrations WHERE state IN ('converting','interrupted','converted',"
                         "'expired') "
                         "LIMIT 1").fetchone() is not None
    except Exception:   # sqlite3.OperationalError: a database from before the converter
        return False


DO_OUTCOME = {"wake_bot": "wake", "note": "note", "archive": "ignore", "leave_for_you": "ask"}


def _scalar(key, value):
    return isinstance(value, (str, int, float, bool)) and bool(F.FIELD.fullmatch(str(key)))


def wake_rules_of(aid, flow):
    """A "What wakes" automation's rules, read from what it shows: each Filter rule's `event is` condition is the
    event, its `task.<field> is <value>` conditions the rule's conditions, its action the outcome. What a rule
    carries out of sight is only its id, scope and history, and the conditions a filter cannot show (a list, a
    range). Raises ValueError (why) for a flow a wake rule cannot express, which `check_wakes` refuses on save."""
    scope = flow.get("wakes") or {}
    trigger = flow.get("trigger") or {}
    if trigger.get("type") != "event" or trigger.get("name") != "tico.wake":
        raise ValueError("its trigger stays the wake rules' own (event tico.wake)")
    out = []
    for n, step in enumerate(flow.get("steps") or []):
        if step.get("type") != "filter":
            raise ValueError(f"step {step.get('id')} is a {step.get('type')}: it holds wake rules, one Filter step each")
        for i, rule in enumerate(step.get("rules") or []):
            where = f"step {step.get('id')} rule {i + 1}"
            then = rule.get("then") or []
            if len(then) != 1:
                raise ValueError(f"{where}: a wake rule does one thing (wake, note, archive or leave for you)")
            if rule.get("stop") is False:
                raise ValueError(f"{where}: a wake rule stops at the first match; keep 'stop' on")
            action = then[0]
            args = action.get("args") or {}
            source = args.get("rule") if isinstance(args.get("rule"), dict) else {}
            event, when = None, {}
            conds = rule.get("when") or []
            if len(conds) > 1 and rule.get("match", "all") != "all":
                raise ValueError(f"{where}: a wake rule matches all of its conditions")
            for cond in conds:
                field, op = str(cond.get("field") or ""), cond.get("op")
                if field == "event" and op == "is" and event is None and isinstance(cond.get("value"), str):
                    event = cond["value"]
                elif field.startswith("task.") and op == "is" and _scalar(field[5:], cond.get("value")):
                    when[field[5:]] = cond["value"]
                else:
                    raise ValueError(f"{where}: a wake rule's conditions are 'event is' and 'task.<field> is'")
            # The conditions it never showed (not a simple value) stay; every one it showed is as the filter says.
            when = {**{k: v for k, v in (source.get("when") or {}).items() if not _scalar(k, v)}, **when}
            do, outcome = action.get("do"), args.get("outcome")
            params = args.get("params") if isinstance(args.get("params"), dict) else {}
            # What the converter showed for the rule's own outcome (_rule_step): kept, with its params, while shown.
            was = params["action"] if outcome == "action" and params.get("action") in F.ACTIONS \
                else OUTCOME_DO.get(outcome, "wake_bot")
            if not (outcome and source and do == was):
                if do not in DO_OUTCOME:
                    raise ValueError(f"{where}: a wake rule wakes, notes, archives or leaves for you, not {do}")
                outcome, params = DO_OUTCOME[do], {}
            out.append({"id": source.get("id") or f"{aid}.{step.get('id')}.{i + 1}",
                        "scope_kind": scope.get("scope_kind") or source.get("scope_kind") or "bot",
                        "scope_id": scope.get("scope_id") or source.get("scope_id") or "", "event": event or "*",
                        "when_json": json.dumps(when, sort_keys=True), "then_outcome": outcome,
                        "params_json": json.dumps(params, sort_keys=True),
                        "enabled": 0 if step.get("enabled") is False else 1,
                        "position": source.get("position") if source.get("position") is not None else n + 1,
                        "note": source.get("note") or "", "created_by": source.get("created_by") or "",
                        "created": source.get("created") or "", "updated": source.get("updated") or "",
                        "revision": source.get("revision") or 1, "action_by": source.get("action_by")})
    return out


def check_wakes(flow):
    """On save (automations._checked): a "What wakes" automation is refused (422) when an edit is one its wake rules
    cannot carry out, rather than saved to show one thing and do another."""
    if not flow.get("wakes") or flow.get("readonly"):
        return
    try:
        wake_rules_of("check", flow)
    except ValueError as exc:
        raise Problem("invalid", f"A What wakes automation holds wake rules: {exc}", 422)


def wake_rows(c, event=None):
    """The converted wake rules, read back from the enabled "What wakes" automations as rules-table rows (rules.py adds
    them to its own). `event` keeps rows on that event or `*`; None keeps every row."""
    try:
        found = c.execute("SELECT id, flow_json FROM automations WHERE id>=? AND id<? AND deleted_at IS NULL "
                          "AND enabled=1", (WAKES_PREFIX, WAKES_PREFIX[:-1] + "`")).fetchall()
    except Exception:   # sqlite3.OperationalError: no automations table yet
        return []
    out = []
    for row in found:
        try:
            rows = wake_rules_of(row["id"], _json(row["flow_json"], {}))
        except ValueError:   # saved before the check (or by hand): nothing it shows can run
            log.warning("redesign migration: %s cannot be read as wake rules", row["id"])
            continue
        out += [r for r in rows if r["enabled"] and (event is None or r["event"] in (event, "*"))]
    return out


# ---------------------------------------------------------------------------------------------------- routes
def _require_on(c):
    if not redesign.on(c):
        raise Problem("not_found", "Not Found", 404)


def install(app, store, auth, mutate):
    from fastapi import Request
    from .models import Empty

    dormant = redesign.dormant()

    def owner(c, who):
        _require_on(c)
        auth.domain(who)
        if who.role != "owner":
            raise Problem("forbidden", "Only the owner (or BotOps for the owner) runs the redesign's migration", 403)

    @app.post("/api/v2/redesign/migration/dry-run", **dormant)
    def migration_dry_run(request: Request, body: Empty | None = None):
        """Every object today's install has, what it becomes and its flags. Writes nothing."""
        who = request.state.identity
        with store.read() as c:
            owner(c, who)
            return report(c, who)

    @app.post("/api/v2/redesign/migration/resolve", **dormant)
    def migration_resolve(request: Request, body: Accept):
        """Say yes to flagged mappings, as the dry run lists them; returns the dry run again."""
        who = request.state.identity

        def work(c):
            owner(c, who)
            ensure(c)
            return resolve(c, who, body.accept)
        return mutate(request, body, work)

    @app.post("/api/v2/redesign/migration/convert", **dormant)
    def migration_convert(request: Request, body: Accept | None = None):
        """Snapshot, then convert one object per transaction. 409 while a flag has no yes; `accept` says yes here."""
        who = request.state.identity
        with store.read() as c:
            owner(c, who)
        return convert(store, who, (body.accept if body else None))

    @app.post("/api/v2/redesign/migration/restore", **dormant)
    def migration_restore(request: Request, body: Empty | None = None):
        """Within a day of converting: the old objects back, the converted automations gone. 410 after the day."""
        who = request.state.identity

        def work(c):
            owner(c, who)
            return restore(c, who)
        return mutate(request, body or Empty(), work)
