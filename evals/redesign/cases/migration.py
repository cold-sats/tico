"""Migration (PLAN §7, scenarios 39-44; CONTRACT §4; mapping PLAN §8). Each scenario installs the fixture through
today's routes with the redesign off (migration_fixture.py), turns the setting on, and drives the converter:
POST /api/v2/redesign/migration/dry-run, then convert, then restore.

Read shapes the CONTRACT does not name, and what this script reads instead (each is a CONTRACT gap):
- a dry-run object's `becomes`: for an object that turns into an automation, that automation as CONTRACT §2 shapes it
  (name, owner, trigger, steps, enabled, builtin), possibly wrapped; for one that stays, "unchanged"; a spend limit
  or turn budget, the new amounts (`per_30m_usd`, `turns_per_hour`, `turns_per_day`). An object is found by its `id`
  (the fixture's id, or one ending in ":<that id>"), never by `kind`, whose words are not named.
- resolving a flag: no route is named. POST .../resolve {"accept": [{kind, id, flags}]} is a placeholder.
- convert's snapshot: `snapshot` (an id, or {id, expires|expires_at}) or `expires`/`expires_at` beside it.
- an automation's link to its source: any of LINK_KEYS, as an id, an object with an id, or a list of those."""
import datetime as dt
import json
from decimal import ROUND_CEILING, Decimal
from zoneinfo import ZoneInfo

from ..harness import CLAUDE_ID, OPENAI_ID, RELEASE_ID, W5, Check, Scenario, Unmet, body, find, got, \
    hook_post, replied, rows, setup
from .migration_fixture import (BOT_BUDGET, BUILTIN_JOBS, CEO, CRON, DESTINATIONS, FIXTURE_BOTS, GUARD, HEALTH,
                                HOOK_ID, HOURLY, INBOXES, ROUTINES, SYSTEM_JOBS, WAKE_RULES, install_fixture,
                                installed)

BASE = "/api/v2/redesign/migration"
UTC, LONDON = dt.timezone.utc, ZoneInfo("Europe/London")
LINK_KEYS = ("source", "sources", "source_id", "source_ids", "migrated_from")
WAKES = "What wakes"


# ---------------------------------------------------------------------------------------------- reading
def text(value):
    return json.dumps(value, sort_keys=True, default=str)


def fx(f):
    return f["fixture"]


def half_up(hourly):
    """PLAN decision 16: $X an hour is $X/2 per 30 minutes, rounded up to $0.10."""
    tenths = (Decimal(str(hourly)) / 2 / Decimal("0.1")).to_integral_value(rounding=ROUND_CEILING)
    return float(tenths * Decimal("0.1"))


def same(value, ident):
    value = str(value or "")
    return bool(ident) and (value == ident or value.endswith(":" + ident) or value.endswith("/" + ident))


def when(value):
    """An ISO time as an aware datetime; a naive one is read as UTC."""
    at = dt.datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    return at if at.tzinfo else at.replace(tzinfo=UTC)


def objects(f, key="dry"):
    data = body(f, key)
    found = data.get("objects") if isinstance(data, dict) else None
    if not isinstance(found, list):
        raise Unmet(W5, f"{key}: the report has no objects list: {got(f, key).excerpt()}")
    return [o for o in found if isinstance(o, dict)]


def for_ids(f, *idents, key="dry"):
    return [o for o in objects(f, key) if any(same(o.get("id"), ident) for ident in idents)]


def automation_in(obj):
    """The automation a dry-run object becomes (CONTRACT §2 shape), or None."""
    return find(obj.get("becomes"), lambda d: "trigger" in d or "steps" in d or "builtin" in d)


def unchanged(obj):
    value = obj.get("becomes")
    return (isinstance(value, str) and value.strip().lower().startswith("unchanged")) or \
        (isinstance(value, dict) and value.get("unchanged") is True)


def step_of(auto, kind):
    return find(auto.get("steps"), lambda d: d.get("type") == kind)


def is_bot(value, slug):
    return value in (slug, "bot:" + slug)


def automations(f, key="autos"):
    return [a for a in rows(body(f, key)) if isinstance(a, dict)]


def unwrap(data):
    return data.get("automation", data) if isinstance(data, dict) else {}


def links(auto):
    out = set()

    def walk(value):
        if isinstance(value, str):
            out.add(value)
        elif isinstance(value, dict):
            out.update(v for k, v in value.items() if k in ("id", "ref") and isinstance(v, str))
        elif isinstance(value, list):
            for item in value:
                walk(item)
    for key in LINK_KEYS:
        walk(auto.get(key))
    return out


def linked_to(f, *idents, key="autos"):
    return [a for a in automations(f, key) if any(same(link, i) for link in links(a) for i in idents)]


def converted_id(f, ident, key="autos"):
    hits = linked_to(f, ident, key=key)
    if len(hits) != 1:
        raise Unmet(W5, f"{len(hits)} automation(s) link to {ident} after converting, want 1")
    return hits[0]["id"]


def snapshot_of(data):
    data = data if isinstance(data, dict) else {}
    snap = data.get("snapshot")
    ident = snap.get("id") if isinstance(snap, dict) else snap if isinstance(snap, str) else data.get("snapshot_id")
    holder = snap if isinstance(snap, dict) else data
    return ident, holder.get("expires") or holder.get("expires_at")


def started(run):
    return when(run.get("started"))


def ready(f, *names):
    """The named fixture objects installed, then the dry run answered."""
    installed(f, *names)
    objects(f)


# ---------------------------------------------------------------------------------------------- steps
def guarded(f, need, fn, *args):
    """Run `fn` only once the `need` step was accepted: a later step never acts on a migration that did not happen."""
    setup(f, need)
    return fn(*args)


def dry_run(org):
    return post(org, f"{BASE}/dry-run")


def resolve(org, f, key="dry"):
    """The owner accepts every flagged mapping as the dry run shows it. Nothing flagged: nothing to send."""
    flagged = [{"kind": o.get("kind"), "id": o.get("id"), "flags": o["flags"]} for o in objects(f, key) if o.get("flags")]
    if not flagged:
        return None
    return post(org, f"{BASE}/resolve", {"accept": flagged})


def convert(org, f, after="resolve"):
    resolved = got(f, after)
    if resolved is not None and not 200 <= resolved.status < 300:
        raise Unmet(W5, f"{after}: {resolved.status} {resolved.excerpt()}")
    return post(org, f"{BASE}/convert")


def migrate(org, f, suffix="", need=None):
    """Dry run, resolve its flags, convert: a chain, so each step names the reason the one before it stopped."""
    if need:
        org.step(f, "dry" + suffix, guarded, f, need, dry_run, org)
    else:
        org.step(f, "dry" + suffix, dry_run, org)
    org.step(f, "resolve" + suffix, resolve, org, f, "dry" + suffix)
    org.step(f, "convert" + suffix, convert, org, f, "resolve" + suffix)


def prologue(org, f):
    """The fixture with the redesign off, then the setting on (it converts nothing by itself)."""
    install_fixture(org, f)
    org.step(f, "setting", org.redesign_on)


def get(org, path):
    return org.api("get", path, wave=W5)


def post(org, path, payload=None):
    return org.api("post", path, payload or {}, wave=W5)


def jump(org, at):
    """Move the fake clock to `at` in one jump, report the runner in, and run the scheduler pass. World.advance
    heartbeats every 50 seconds (1,800 calls for 25 hours), which would take several seconds a scenario."""
    org.clock.shift((at - org.now()).total_seconds())
    org.heartbeat(org.bot_slugs)
    org.scheduler_pass()
    return at


def runs_for(org, f, ident, key="autos"):
    return get(org, f"/api/v2/automations/{converted_id(f, ident, key)}/runs")


def occurrences(org, f):
    """The old hourly sweep's occurrences (a route main has). After converting, its row is gone: 404 reads as none."""
    installed(f, "routine:pr_sweep")
    return get(org, f"/api/v2/routines/{fx(f)['routines']['pr_sweep']}/occurrences")


def deliver(org, f):
    """A delivery to the old incoming address, with the secret the trigger was created with."""
    setup(f, "convert")
    installed(f, "trigger")
    hook = fx(f)["hook"]
    return hook_post(org, hook["id"], hook["secret"], {"service": "api", "status": "failed"})


def read_wakes(org, f):
    """Every "What wakes" automation read in full (a listing row may omit its steps), by id."""
    found = {}
    for auto in automations(f):
        if str(auto.get("name") or "").startswith(WAKES):
            reply = get(org, f"/api/v2/automations/{auto['id']}")
            if not 200 <= reply.status < 300:
                raise Unmet(W5, f"read {auto['id']}: {reply.status} {reply.excerpt()}")
            found[auto["id"]] = {**auto, **unwrap(reply.body)}
    return found


# ---------------------------------------------------------------------------------------------- 39 dry run
def s39_steps(org, f):
    prologue(org, f)
    org.step(f, "dry", dry_run, org)
    org.step(f, "routines_after", guarded, f, "dry", get, org, "/api/v2/routines")


def mapped(f, label, idents, want):
    """Some dry-run object for one of `idents` becomes an automation `want` accepts; `want` answers (ok, detail)."""
    found = for_ids(f, *idents)
    if not found:
        return False, f"no object for {label} ({', '.join(i for i in idents if i)})"
    seen = []
    for obj in found:
        auto = automation_in(obj)
        if auto is None:
            seen.append(f"{obj.get('kind')} becomes {text(obj.get('becomes'))[:80]}")
            continue
        ok, detail = want(auto)
        if ok:
            return True, detail
        seen.append(detail)
    return False, "; ".join(seen)


def valued(f, label, idents, pred):
    found = for_ids(f, *idents)
    hit = next((o for o in found if pred(o)), None)
    shown = "; ".join(f"{o.get('kind')} {o.get('id')} -> {text(o.get('becomes'))[:90]} flags {o.get('flags')}"
                      for o in found) or "no object"
    return hit is not None, f"{label}: {shown}"


def scheduled(bot, routine):
    def want(auto):
        trig, turn = auto.get("trigger") or {}, step_of(auto, "bot_turn") or {}
        ok = (auto.get("owner") == "bot:" + bot and trig.get("type") == "schedule"
              and trig.get("cron") == routine["cron"] and trig.get("tz") == routine["timezone"]
              and is_bot(turn.get("bot"), bot) and turn.get("prompt") == routine["text"])
        return ok, f"owner {auto.get('owner')}, trigger {text(trig)}, bot turn {text(turn)[:100]}"
    return want


def triggered(bot, routine, trigger):
    def want(auto):
        trig, turn = auto.get("trigger") or {}, step_of(auto, "bot_turn") or {}
        ok = (auto.get("owner") == "bot:" + bot and all(trig.get(k) == v for k, v in trigger.items())
              and is_bot(turn.get("bot"), bot) and turn.get("prompt") == routine["text"])
        return ok, f"owner {auto.get('owner')}, trigger {text(trig)}, bot turn {text(turn)[:100]}"
    return want


def routine_row(name, trigger=None):
    bot, routine = ROUTINES[name]

    def check(f):
        ready(f, "routine:" + name, *(["trigger"] if name == "deploy_triage" else []))
        want = scheduled(bot, routine) if trigger is None else triggered(bot, routine, trigger)
        return mapped(f, name, [fx(f)["routines"][name]], want)
    return check


def builtin_row(label, idents_of, extra=None, needs=()):
    def check(f):
        ready(f, *needs)

        def want(auto):
            ok = auto.get("builtin") is True and (extra is None or extra(auto))
            return ok, f"builtin {auto.get('builtin')}, {text(auto)[:120]}"
        return mapped(f, label, idents_of(f), want)
    return check


def still_wanted_kept(auto):
    """Still wanted? was set daily at 10:00: the built-in keeps that time."""
    trig = auto.get("trigger") or {}
    return "10:00" in text(auto) or str(trig.get("cron") or "").startswith("0 10 ")


def stale_row(f):
    ready(f, "job:stale_review")

    def want(auto):
        trig = auto.get("trigger") or {}
        fields = str(trig.get("cron") or "").split()
        hourly = trig.get("type") == "schedule" and len(fields) == 5 and fields[0].isdigit() and fields[1:] == ["*"] * 4
        ok = auto.get("builtin") is not True and auto.get("enabled") is False and hourly
        return ok, f"builtin {auto.get('builtin')}, enabled {auto.get('enabled')}, trigger {text(trig)}"
    return mapped(f, "stale ticket review", ["stale_review"], want)


def wake_rows(f):
    ready(f, *("rule:" + name for name in WAKE_RULES))
    names, bad = {}, []
    for name, (bot, _event, _outcome) in WAKE_RULES.items():
        hit = None
        for obj in for_ids(f, fx(f)["rules"][name]):
            auto = automation_in(obj)
            if auto and str(auto.get("name") or "").startswith(WAKES) and auto.get("owner") == "bot:" + bot \
                    and auto.get("builtin") is not True and step_of(auto, "filter"):
                hit = auto
        if hit is None:
            bad.append(name)
        else:
            names.setdefault(bot, set()).add(hit.get("name"))
    one_each = len(names) == 2 and all(len(v) == 1 for v in names.values())
    return not bad and one_each, f"unmapped {bad}, automations {({b: sorted(v) for b, v in names.items()})}"


def inbox_rows(f):
    ready(f, *("inbox:" + person for person in INBOXES))
    results = []
    for person, (bot, mailbox) in INBOXES.items():
        def want(auto, person=person, mailbox=mailbox):
            trig, llm = auto.get("trigger") or {}, step_of(auto, "llm") or {}
            ok = (auto.get("owner") == "person:" + person and trig.get("type") == "message"
                  and trig.get("inbox") == mailbox and llm.get("as") == "assistant:" + person)
            return ok, f"owner {auto.get('owner')}, trigger {text(trig)}, llm as {llm.get('as')}"
        results.append(mapped(f, mailbox, [mailbox, bot], want))
    return all(ok for ok, _ in results), " | ".join(detail for _, detail in results)


def librarian_row(f):
    return routine_row("briefing")(f)


def destinations_row(f):
    ready(f, *("destination:" + key for key in DESTINATIONS))
    results = [valued(f, key, [key], unchanged) for key in DESTINATIONS]
    return all(ok for ok, _ in results), " | ".join(detail for _, detail in results)


def ceo_row(f):
    def renamed(obj):
        named = "strategy bot" in text(obj.get("becomes")).lower()
        slug = find(obj.get("becomes"), lambda d: "slug" in d)
        return named and (slug is None or slug.get("slug") == CEO)
    ready(f)
    return valued(f, "CEO Bot", [CEO], renamed)


def limit_row(bot, flagged=False):
    want = half_up(HOURLY[bot])

    def check(f):
        ready(f, "limit:" + bot)

        def pred(obj):
            hit = find(obj.get("becomes"), lambda d: isinstance(d.get("per_30m_usd"), (int, float))
                       and abs(d["per_30m_usd"] - want) < 1e-6)
            return hit is not None and (not flagged or bool(obj.get("flags")))
        return valued(f, f"{bot} hourly {HOURLY[bot]:.2f} -> {want:.2f}" + (" flagged" if flagged else ""), [bot], pred)
    return check


def budget_rows(f):
    ready(f, "team_budget", "bot_budget")
    team = next((o for o in objects(f) if find(o.get("becomes"), lambda d: d.get("turns_per_hour") == GUARD[
        "turns_per_hour"] and d.get("turns_per_day") == GUARD["turns_per_day"])), None)
    bot, own = BOT_BUDGET
    kept = valued(f, bot, [bot], lambda o: find(o.get("becomes"), lambda d: d.get("turns_per_hour") == own[
        "turns_per_hour"]) is not None or (unchanged(o) and "budget" in str(o.get("kind") or "")))
    return team is not None and kept[0], \
        f"team raised to {GUARD}: {'yes' if team else 'no'}; {bot} kept at {own['turns_per_hour']}: {kept[1]}"


def goal_row(f):
    ready(f, "goal")
    return valued(f, "goal", [fx(f)["goal"]], unchanged)


def listed(f):
    """Every fixture object has a row in the report."""
    ready(f)
    ids = fx(f)
    want = {**{"routine " + n: [i] for n, i in ids["routines"].items()},
            **{"wake rule " + n: [i] for n, i in ids["rules"].items()},
            "task rule": [ids["task_rule"]],
            **{"system job " + job: [job] for job in (*BUILTIN_JOBS, *SYSTEM_JOBS)},
            **{"inbox " + p: [i["mailbox"], i["bot"]] for p, i in ids["inboxes"].items()},
            **{"destination " + key: [key] for key in DESTINATIONS},
            **{"hourly limit " + bot: [bot] for bot in HOURLY},
            "Health Monitor": [HEALTH], "CEO Bot": [CEO], "goal": [ids["goal"]]}
    missing = [label for label, idents in want.items() if not for_ids(f, *idents)]
    return not missing, f"{len(objects(f))} object(s); missing {missing}"


def counted(f):
    data, found = body(f, "dry"), objects(f)
    counts = data.get("counts")
    if not isinstance(counts, dict):
        return False, f"counts {text(counts)[:80]}"
    total = counts["total"] if isinstance(counts.get("total"), int) else \
        sum(v for v in counts.values() if isinstance(v, int) and not isinstance(v, bool))
    return total == len(found), f"counts add to {total}, {len(found)} object(s)"


def dry_changes_nothing(f):
    ready(f, *("routine:" + name for name in ROUTINES))   # a real report, not just a 2xx
    setup(f, "routines_after")
    have = {r.get("id") for r in rows(body(f, "routines_after"))}
    gone = [name for name, sid in fx(f)["routines"].items() if sid not in have]
    return not gone, f"routines no longer listed after the dry run: {gone}"


# ---------------------------------------------------------------------------------------------- 40 wake rules
def s40_steps(org, f):
    prologue(org, f)
    migrate(org, f)
    org.step(f, "autos", guarded, f, "convert", get, org, "/api/v2/automations")
    org.step(f, "wakes", guarded, f, "autos", read_wakes, org, f)
    org.step(f, "rules_after", guarded, f, "convert", get, org, "/api/v2/rules")


def filter_rules(auto):
    found = []

    def walk(value):
        if isinstance(value, dict):
            if value.get("type") == "filter":
                found.extend(r for r in value.get("rules") or [] if isinstance(r, dict))
            for child in value.values():
                walk(child)
        elif isinstance(value, list):
            for child in value:
                walk(child)
    walk(auto.get("steps"))
    return found


def wakes_of(f, bot):
    return [a for a in got(f, "wakes").values() if a.get("owner") == "bot:" + bot and a.get("builtin") is not True]


def wake_automation(bot):
    want = [(event, outcome) for _n, (b, event, outcome) in WAKE_RULES.items() if b == bot]

    def check(f):
        installed(f, *("rule:" + n for n, r in WAKE_RULES.items() if r[0] == bot))
        setup(f, "convert", "autos")
        mine = wakes_of(f, bot)
        if len(mine) != 1:
            return False, f"{len(mine)} {WAKES} automation(s) owned by bot:{bot}, want 1"
        rules = filter_rules(mine[0])
        hits = [w for w in want if any(w[0] in text(r) and w[1] in text(r) for r in rules)]
        return len(rules) == len(want) and hits == want, \
            f"{mine[0].get('name')}: {len(rules)} Filter rule(s), matched {hits} of {want}"
    return check


def only_custom(f):
    installed(f, *("rule:" + n for n in WAKE_RULES))
    setup(f, "convert", "autos")
    owners = sorted({a.get("owner") for a in got(f, "wakes").values() if a.get("builtin") is not True})
    want = sorted({"bot:" + b for b, _e, _o in WAKE_RULES.values()})
    return owners == want, f"{WAKES} automations for {owners}, want {want}"


def builtin_wakes(f):
    setup(f, "convert", "autos")
    hits = [a for a in automations(f) if a.get("name") == "What wakes bots"]
    ok = len(hits) == 1 and hits[0].get("builtin") is True and hits[0].get("can_edit") is False
    return ok, f"{len(hits)} 'What wakes bots'" + (f": builtin {hits[0].get('builtin')}, can_edit "
                                                   f"{hits[0].get('can_edit')}" if hits else "")


def custom_rows_gone(f):
    installed(f, *("rule:" + n for n in WAKE_RULES))
    setup(f, "convert", "rules_after")
    listed_rules = (body(f, "rules_after") or {}).get("rules") or []
    ids = {r.get("id") for r in listed_rules if isinstance(r, dict)}
    left = [n for n, rid in fx(f)["rules"].items() if rid in ids]
    builtins = sum(1 for r in listed_rules if isinstance(r, dict) and r.get("built_in"))
    return not left and builtins > 0, f"custom rows still listed {left}; {builtins} built-in rule(s) listed"


# ---------------------------------------------------------------------------------------------- 41 convert
def s41_steps(org, f):
    prologue(org, f)                                                   # 09:00 UTC
    org.step(f, "before_cut", org.pass_time, dt.timedelta(minutes=31))   # the old sweep fires its 09:30 occurrence
    org.step(f, "occ_before", occurrences, org, f)
    org.step(f, "dry", dry_run, org)
    org.step(f, "early", guarded, f, "dry", post, org, f"{BASE}/convert")   # flags unresolved
    org.step(f, "resolve", resolve, org, f)
    org.step(f, "convert", convert, org, f)
    f["cutover"] = org.now()
    org.step(f, "autos", guarded, f, "convert", get, org, "/api/v2/automations")
    org.step(f, "routines_after", guarded, f, "convert", get, org, "/api/v2/routines")
    org.step(f, "destinations_after", guarded, f, "convert", get, org, "/api/v2/listening/destinations")
    org.step(f, "hook", deliver, org, f)
    org.step(f, "hook_runs", guarded, f, "hook", runs_for, org, f, fx(f)["routines"]["deploy_triage"])
    for n in range(4):   # to 10:31, a scheduler pass every 15 minutes: the 10:30 sweep is due once
        org.step(f, f"tick{n}", guarded, f, "convert", org.pass_time, dt.timedelta(minutes=15))
    org.step(f, "sweep_runs", guarded, f, "convert", runs_for, org, f, fx(f)["routines"]["pr_sweep"])
    org.step(f, "occ_after", guarded, f, "convert", occurrences, org, f)


def refused_early(f):
    ready(f, "limit:" + RELEASE_ID)
    flagged = [o for o in objects(f) if o.get("flags")]
    if not flagged:
        return False, "the dry run raised no flag (the 0.25 hourly limit should raise one)"
    ok, detail = replied(f, "early", 409, 422)
    return ok, f"{len(flagged)} flagged; convert answered {detail}"


def snapshot_taken(f):
    setup(f, "convert")
    ident, expires = snapshot_of(body(f, "convert"))
    if not ident or not expires:
        return False, f"snapshot {ident}, expires {expires}: {got(f, 'convert').excerpt()}"
    off = abs((when(expires) - f["cutover"]) - dt.timedelta(hours=24))
    return off <= dt.timedelta(minutes=5), f"snapshot {ident} expires {expires}"


def sources_linked(f):
    installed(f, *("routine:" + n for n in ROUTINES), "task_rule", *("inbox:" + p for p in INBOXES))
    setup(f, "convert", "autos")
    want = {**{"routine " + n: [sid] for n, sid in fx(f)["routines"].items()}, "task rule": [fx(f)["task_rule"]],
            **{"inbox " + p: [i["mailbox"], i["bot"]] for p, i in fx(f)["inboxes"].items()}}
    missing = [label for label, idents in want.items() if not linked_to(f, *idents)]
    return not missing, f"no automation links to {missing}"


def routine_rows_gone(f):
    installed(f, *("routine:" + n for n in ROUTINES))
    setup(f, "convert", "routines_after")
    have = {r.get("id") for r in rows(body(f, "routines_after"))}
    left = [n for n, sid in fx(f)["routines"].items() if sid in have]
    return not left, f"old routines still listed: {left}"


def hook_kept(f):
    ok, detail = replied(f, "hook", 200, 202, needs=("convert",))
    if not ok:
        return ok, f"old address answered {detail}"
    count = len(rows(body(f, "hook_runs")))
    return count == 1, f"old address answered {detail}; the Webhook automation has {count} run(s), want 1"


def fired_once(f):
    """The hourly sweep fired at 09:30 before the cutover; across the cutover only its 10:30 occurrence fires, once,
    from either system: the automation's runs since the cutover plus any old occurrence after it."""
    setup(f, "occ_before", "convert", "sweep_runs")
    cut = f["cutover"]
    before = [o for o in rows(body(f, "occ_before")) if when(o.get("occurrence")) <= cut]
    if len(before) != 1:
        return False, f"the old routine fired {len(before)} time(s) before the cutover, want 1 (09:30)"
    after = got(f, "occ_after")
    old = [] if after.status == 404 else [o for o in rows(body(f, "occ_after")) if when(o.get("occurrence")) > cut]
    new = [r for r in rows(body(f, "sweep_runs")) if started(r) > cut]
    times = [started(r).strftime("%H:%M") for r in new] + ["old " + str(o.get("occurrence")) for o in old]
    on_time = all(started(r) >= cut.replace(hour=10, minute=30, second=0, microsecond=0) for r in new)
    return len(new) + len(old) == 1 and on_time, f"fires after the cutover: {times}, want one at 10:30"


def destinations_kept(f):
    installed(f, *("destination:" + key for key in DESTINATIONS))
    setup(f, "convert", "destinations_after")
    have = {d.get("key"): d.get("receiver") for d in rows(body(f, "destinations_after"))}
    want = {key: "bot:" + d["receiver"] for key, d in DESTINATIONS.items()}
    return all(have.get(k) == v for k, v in want.items()), f"receivers {have}, want {want}"


# ---------------------------------------------------------------------------------------------- 42 times
STANDUP_DAYS = (21, 22, 23, 24, 25, 26)   # Europe/London leaves summer time at 02:00 on Sunday Oct 25, 2026


def nine_london(day):
    return dt.datetime(2026, 10, day, 9, tzinfo=LONDON)


def close_standup(org):
    """The standup is finished each morning, so its open task closes before the next occurrence. While a converted
    routine's last task is open, an occurrence starts no run (CONTRACT section 4, as the legacy scheduler's one-open-run
    rule does); the scenario checks the clock, not that rule, so it closes the task the way the team would."""
    with org.store.read() as c:
        open_ids = [r["id"] for r in c.execute(
            "SELECT id FROM tasks WHERE owner IN (?, ?) AND status NOT IN ('closed','done')",
            (CLAUDE_ID, "bot:" + CLAUDE_ID))]
    closed = 0
    for tid in open_ids:
        task = org.api("get", f"/api/v2/tasks/{tid}", wave=W5)
        version = (task.body.get("task") or task.body).get("version") if isinstance(task.body, dict) else None
        closed += org.api("post", f"/api/v2/tasks/{tid}", {"version": version, "status": "closed"}, wave=W5).status < 300
    return closed


def s42_steps(org, f):
    prologue(org, f)   # Tue Oct 20, 09:00 UTC (10:00 London)
    org.step(f, "old", get, org, f"/api/v2/bots/{CLAUDE_ID}/routines")
    migrate(org, f)
    org.step(f, "autos", guarded, f, "convert", get, org, "/api/v2/automations")
    org.step(f, "read", lambda: get(org, f"/api/v2/automations/{converted_id(f, fx(f)['routines']['standup'])}"))
    org.step(f, "runs20", runs_for, org, f, fx(f)["routines"]["standup"])
    for day in STANDUP_DAYS:   # one day at a time, to 09:00 London exactly, so the scheduler fires each in turn
        org.step(f, f"to{day}", guarded, f, "convert", jump, org, nine_london(day))
        org.step(f, f"runs{day}", runs_for, org, f, fx(f)["routines"]["standup"])
        org.step(f, f"closed{day}", close_standup, org)


def standup_trigger(f):
    installed(f, "routine:standup")
    trig = unwrap(body(f, "read")).get("trigger") or {}
    routine = ROUTINES["standup"][1]
    ok = trig.get("type") == "schedule" and trig.get("cron") == routine["cron"] and trig.get("tz") == routine["timezone"]
    return ok, f"trigger {text(trig)}"


def next_run_kept(f):
    installed(f, "routine:standup")
    setup(f, "old", "read")
    row = next((r for r in rows(body(f, "old")) if r.get("id") == fx(f)["routines"]["standup"]), {})
    want = nine_london(21).astimezone(UTC)
    old, new = row.get("next_due"), unwrap(body(f, "read")).get("next_run")
    if not old or not new:
        return False, f"routine next_due {old}, automation next_run {new}"
    return when(old) == when(new) == want, f"routine next_due {old}, automation next_run {new}, want {want.isoformat()}"


def fired_at_nine(day, utc_hour):
    def check(f):
        installed(f, "routine:standup")
        setup(f, f"runs{day - 1}", f"runs{day}")
        seen = {r.get("id") for r in rows(body(f, f"runs{day - 1}"))}
        new = [r for r in rows(body(f, f"runs{day}")) if r.get("id") not in seen]
        times = [started(r) for r in new]
        hits = [t for t in times if t.astimezone(LONDON).date().day == day and t.astimezone(LONDON).hour == 9
                and t.astimezone(LONDON).minute < 10 and t.astimezone(UTC).hour == utc_hour]
        return len(new) == 1 and len(hits) == 1, \
            f"started {[t.isoformat() for t in times]}, want one at 09:00 London on Oct {day} ({utc_hour}:00 UTC)"
    return check


# ---------------------------------------------------------------------------------------------- 43 limit
def s43_steps(org, f):
    prologue(org, f)
    migrate(org, f)
    org.step(f, "limits", guarded, f, "convert", get, org, "/api/v2/usage/limits")


def limit_now(bot):
    want = half_up(HOURLY[bot])

    def check(f):
        installed(f, "limit:" + bot)
        setup(f, "convert", "limits")
        row = ((body(f, "limits") or {}).get("bots") or {}).get(bot) or {}
        per_30m = row.get("own_per_30m_usd", row.get("per_30m_usd"))
        hours = {k: row.get(k) for k in ("hourly_usd", "own_hourly_usd") if row.get(k) is not None}
        ok = isinstance(per_30m, (int, float)) and abs(per_30m - want) < 1e-6 and not hours
        return ok, f"per_30m_usd {per_30m} (want {want:.2f}), hour fields left {hours}"
    return check


# ---------------------------------------------------------------------------------------------- 44 restore
def s44_steps(org, f):
    prologue(org, f)
    migrate(org, f)
    org.step(f, "autos", guarded, f, "convert", get, org, "/api/v2/automations")
    org.step(f, "hour", guarded, f, "convert", lambda: jump(org, org.now() + dt.timedelta(hours=1)))
    org.step(f, "restore", guarded, f, "convert", post, org, f"{BASE}/restore")
    org.step(f, "routines_back", guarded, f, "restore", get, org, "/api/v2/routines")
    org.step(f, "rules_back", guarded, f, "restore", get, org, "/api/v2/rules")
    org.step(f, "autos_back", guarded, f, "restore", get, org, "/api/v2/automations")
    migrate(org, f, suffix="2", need="restore")   # convert again: a fresh snapshot to let expire
    org.step(f, "day", guarded, f, "convert2", lambda: jump(org, org.now() + dt.timedelta(hours=25)))
    org.step(f, "restore2", guarded, f, "convert2", post, org, f"{BASE}/restore")


def routines_back(f):
    installed(f, *("routine:" + n for n in ROUTINES))
    setup(f, "restore", "routines_back")
    have = {r.get("id") for r in rows(body(f, "routines_back"))}
    missing = [n for n, sid in fx(f)["routines"].items() if sid not in have]
    return not missing, f"routines not back: {missing}"


def rules_back(f):
    installed(f, *("rule:" + n for n in WAKE_RULES))
    setup(f, "restore", "rules_back")
    have = {r.get("id") for r in (body(f, "rules_back") or {}).get("rules") or [] if isinstance(r, dict)}
    missing = [n for n, rid in fx(f)["rules"].items() if rid not in have]
    return not missing, f"wake rules not back: {missing}"


def automations_gone(f):
    installed(f, *("routine:" + n for n in ROUTINES))
    setup(f, "restore", "autos_back")
    left = [a.get("name") for a in linked_to(f, *fx(f)["routines"].values(), key="autos_back")
            if a.get("builtin") is not True]
    return not left, f"converted automations still listed: {left}"


# ---------------------------------------------------------------------------------------------- the scenarios
def routine_label(name, becomes):
    bot, routine = ROUTINES[name]
    return f"{routine['title']} ({bot}) becomes {becomes}"


SCENARIOS = [
    Scenario(39, "migration-dry-run", "Dry run lists every fixture object with its PLAN §8 mapping and flags", s39_steps, [
        Check("every fixture object has a row in the report", W5, listed),
        Check("counts add up to the rows listed", W5, counted),
        Check("the dry run changes nothing: every routine is still listed", W5, dry_changes_nothing),
        *[Check(routine_label(name, "a Schedule automation: same owner, cron, time zone; text as its Bot turn"), W5,
                routine_row(name)) for name in CRON if name != "briefing"],
        Check(routine_label("release_notes", "an Event automation on release_published"), W5,
              routine_row("release_notes", {"type": "event", "name": "release_published"})),
        Check(routine_label("deploy_triage", f"a Webhook automation on the same trigger ({HOOK_ID})"), W5,
              routine_row("deploy_triage", {"type": "webhook", "id": HOOK_ID})),
        Check("custom wake rules become one What wakes automation per bot, each rule a Filter step", W5, wake_rows),
        Check("the task rule becomes a built-in automation", W5,
              builtin_row("task rule", lambda f: [fx(f)["task_rule"]], needs=("task_rule",))),
        Check("system jobs (Start assigned tasks, Recover unstarted) become built-in automations", W5,
              lambda f: _all(f, [builtin_row(job, lambda f, job=job: [job]) for job in BUILTIN_JOBS])),
        Check("Still wanted? becomes a built-in that keeps its control (daily at 10:00)", W5,
              builtin_row("still wanted", lambda f: ["still_wanted"], still_wanted_kept, needs=("job:still_wanted",))),
        Check("Stale ticket review becomes a regular automation, Off, hourly", W5, stale_row),
        Check("Dana's and Priya's inboxes become message automations on their owner, LLM as the owner's Assistant", W5,
              inbox_rows),
        Check("Health Monitor becomes a built-in automation", W5,
              builtin_row("Health Monitor", lambda f: [HEALTH])),
        Check("listening destinations (market, leads) stay unchanged", W5, destinations_row),
        Check("the Librarian's market briefing becomes Schedule + Bot turn owned by the Librarian", W5, librarian_row),
        Check("CEO Bot becomes Strategy Bot in the same row (slug goal-manager)", W5, ceo_row),
        Check("hourly 3.00 becomes 1.50 per 30 minutes", W5, limit_row(OPENAI_ID)),
        Check("hourly 5.00 becomes 2.50 per 30 minutes", W5, limit_row(CLAUDE_ID)),
        Check("hourly 0.25 becomes 0.20 per 30 minutes (rounded up to $0.10), with a flag", W5,
              limit_row(RELEASE_ID, flagged=True)),
        Check("turn budgets rise to the guard defaults (300/h, 2,500/day); a bot's 600/h is kept", W5, budget_rows),
        Check("the goal stays unchanged", W5, goal_row),
    ], setting=False, bots=FIXTURE_BOTS),
    Scenario(40, "migration-wake-rules", "Custom wake rules become one What wakes automation per bot", s40_steps, [
        Check("Builder (Claude): one What wakes automation, its two rules as Filter rules (wake, note)", W5,
              wake_automation(CLAUDE_ID)),
        Check("Builder (OpenAI): one What wakes automation, its rule as a Filter rule (batch)", W5,
              wake_automation(OPENAI_ID)),
        Check("only bots with custom rules get a What wakes automation", W5, only_custom),
        Check("the built-in wake rules show as one read-only built-in, What wakes bots", W5, builtin_wakes),
        Check("the custom rule rows are gone; the built-in rules are still listed", W5, custom_rows_gone),
    ], setting=False, bots=FIXTURE_BOTS),
    Scenario(41, "migration-convert", "Convert: snapshot, links to sources, old rows gone, no double fire", s41_steps, [
        Check("convert is refused (409 or 422) while a flag is unresolved", W5, refused_early),
        Check("convert after resolving takes a snapshot with an id and a 24-hour expiry", W5, snapshot_taken),
        Check("each converted routine, the task rule and each inbox links to its source", W5, sources_linked),
        Check("the old routine rows are gone", W5, routine_rows_gone),
        Check("the webhook keeps its URL and secret: the old address runs the Webhook automation", W5, hook_kept),
        Check("the hourly sweep fires exactly once across the cutover (10:30)", W5, fired_once),
        Check("listening destinations keep their receivers (market: the Librarian)", W5, destinations_kept),
    ], setting=False, bots=FIXTURE_BOTS),
    Scenario(42, "migration-times", "A converted routine fires at the same local time, across the DST change",
             s42_steps, [
        Check("the converted standup keeps 0 9 * * * in Europe/London", W5, standup_trigger),
        Check("its next_run is the routine's next fire: 09:00 London on Oct 21 (08:00 UTC)", W5, next_run_kept),
        Check("Oct 24, summer time: fires at 09:00 London (08:00 UTC)", W5, fired_at_nine(24, 8)),
        Check("Oct 25, the change: fires at 09:00 London (09:00 UTC)", W5, fired_at_nine(25, 9)),
        Check("Oct 26, winter time: fires at 09:00 London (09:00 UTC)", W5, fired_at_nine(26, 9)),
    ], setting=False, bots=FIXTURE_BOTS),
    Scenario(43, "migration-limit", "Hourly $X becomes 30-min $X/2, rounded up to $0.10; the hour is cleared", s43_steps, [
        Check("hourly 3.00 is now 1.50 per 30 minutes, hour cleared", W5, limit_now(OPENAI_ID)),
        Check("hourly 5.00 is now 2.50 per 30 minutes, hour cleared", W5, limit_now(CLAUDE_ID)),
        Check("hourly 0.25 is now 0.20 per 30 minutes, hour cleared", W5, limit_now(RELEASE_ID)),
    ], setting=False, bots=FIXTURE_BOTS),
    Scenario(44, "migration-restore", "Restore within a day brings the old objects back; the snapshot expires",
             s44_steps, [
        Check("restore within 24 hours is accepted", W5, lambda f: replied(f, "restore", 200, 201, needs=("convert",))),
        Check("the old routines are back, same ids", W5, routines_back),
        Check("the custom wake rules are back, same ids", W5, rules_back),
        Check("the converted automations are gone, so nothing fires twice", W5, automations_gone),
        Check("25 hours after the next convert the snapshot is gone: restore refused (404 or 410)", W5,
              lambda f: replied(f, "restore2", 404, 410, needs=("convert2",))),
    ], setting=False, bots=FIXTURE_BOTS),
]


def _all(f, checks):
    results = [check(f) for check in checks]
    return all(ok for ok, _ in results), " | ".join(detail for _, detail in results)
