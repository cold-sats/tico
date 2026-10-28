"""An automation's flow (CONTRACT §2): the shape a save must have, and how a condition reads a run's values.

Pure: no database, no clock. `check` refuses a flow on save with one sentence naming the first thing wrong;
`holds` and `all_hold` decide a condition against the values a run has gathered (the trigger's payload, the outputs
of earlier steps and, after a `find`, the item).
"""
import re

from clients import judge as J
from backend import templating

TRIGGERS = {"message": ("inbox",), "task_received": ("to",), "schedule": ("cron",), "webhook": ("id",),
            "listening": ("destination",), "event": ("name",)}
STEP_TYPES = ("filter", "decide", "llm", "find", "bot_turn", "paths", "action")
ACTIONS = ("archive", "leave_for_you", "draft_reply", "send_reply", "create_task", "label", "forward", "wake_bot",
           "note", "post_update", "call_webhook", "assign")
OPS = ("is", "is_not", ">=", "<=", "contains", "matches")
SOURCES = ("mail", "tasks", "prs", "listening", "docs")
LEVELS = J.DECIDE_LEVELS
MAX_PATHS = 10          # paths in one fork
MAX_DEPTH = 3           # forks inside forks
MAX_STEPS = 100         # every step in the flow, nested ones included
MAX_RULES = 50
MAX_CONDS = 20
MAX_TEXT = 8000
MAX_FIND = 100
NAME = re.compile(r"[A-Za-z][A-Za-z0-9_-]{0,39}")
OWNER = re.compile(r"(person|bot|group):[a-z0-9][a-z0-9._-]{0,63}")
CLOCK = re.compile(r"([01][0-9]|2[0-3]):[0-5][0-9]")
FIELD = re.compile(r"[A-Za-z0-9_][A-Za-z0-9_.-]{0,199}")


class Invalid(ValueError):
    """A flow refused on save; the message says where and why."""


def owner_ref(value):
    """`human:<id>` (how the hub names a person elsewhere) is `person:<id>` here."""
    value = str(value or "").strip()
    return "person:" + value[6:] if value.startswith("human:") else value


# ---------------------------------------------------------------------------------------------------- shape on save
def _need(ok, where, what):
    if not ok:
        raise Invalid(f"{where}: {what}")


def _text(value, where, what, *, required=True, cap=MAX_TEXT):
    if value is None and not required:
        return
    _need(isinstance(value, str) and (value.strip() or not required) and len(value) <= cap, where,
          f"{what} is text of at most {cap} characters")


def check_cond(cond, where):
    _need(isinstance(cond, dict), where, "a condition is a map")
    _need(set(cond) <= {"field", "op", "value", "min"}, where, "a condition has field, op, value and min only")
    _need(isinstance(cond.get("field"), str) and FIELD.fullmatch(cond["field"]), where,
          "a condition names a field such as message.from or d1.bucket")
    _need(cond.get("op") in OPS, where, f"op is one of {', '.join(OPS)}")
    if "min" in cond and cond["min"] is not None:
        _need(isinstance(cond["min"], (int, float)) and not isinstance(cond["min"], bool) and 0 <= cond["min"] <= 1,
              where, "min is a number from 0 to 1")
    if cond["op"] in (">=", "<="):
        _need(_number(cond.get("value")) is not None, where, f"{cond['op']} compares with a number")
    if cond["op"] == "matches":
        _need(isinstance(cond.get("value"), str) and len(cond["value"]) <= 200, where,
              "matches takes a pattern of at most 200 characters")
        try:
            re.compile(cond["value"])
        except re.error as exc:
            raise Invalid(f"{where}: the pattern does not read ({exc})") from None


def check_conds(conds, where):
    _need(isinstance(conds, list) and len(conds) <= MAX_CONDS, where, f"conditions are a list of at most {MAX_CONDS}")
    for n, cond in enumerate(conds):
        check_cond(cond, f"{where} condition {n + 1}")


def check_action(action, where):
    _need(isinstance(action, dict), where, "an action is a map with do and args")
    _need(set(action) <= {"do", "args"}, where, "an action has do and args only")
    _need(action.get("do") in ACTIONS, where, f"do is one of {', '.join(ACTIONS)}")
    _need(isinstance(action.get("args", {}), dict), where, "args is a map")


def _check_trigger(trigger):
    _need(isinstance(trigger, dict), "trigger", "is a map with a type")
    kind = trigger.get("type")
    _need(kind in TRIGGERS, "trigger", f"type is one of {', '.join(TRIGGERS)}")
    for key in TRIGGERS[kind]:
        _text(trigger.get(key), "trigger", key, cap=300)
    if kind == "schedule":
        from croniter import croniter
        _need(len(trigger["cron"].split()) == 5 and croniter.is_valid(trigger["cron"]), "trigger",
              "cron is a five-field schedule such as 0 9 * * 1-5")
        _check_zone(trigger.get("tz") or "UTC", "trigger")
    if "send" in trigger:
        _need(isinstance(trigger["send"], bool), "trigger", "send is true or false")
    check_conds(trigger.get("filters") or [], "trigger filters")


def _check_zone(zone, where):
    from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
    try:
        ZoneInfo(str(zone))
    except (ZoneInfoNotFoundError, ValueError):
        raise Invalid(f"{where}: {zone} is not a time zone such as Europe/Paris") from None


def _check_step(step, where, seen, depth, counts):
    _need(isinstance(step, dict), where, "a step is a map")
    _need(isinstance(step.get("id"), str) and NAME.fullmatch(step["id"]), where,
          "every step has an id: a letter, then letters, digits, _ or - (40 at most)")
    where = f"step {step['id']}"
    _need(step["id"] not in seen, where, "step ids are unique in the flow")
    seen.add(step["id"])
    counts[0] += 1
    _need(counts[0] <= MAX_STEPS, where, f"a flow has at most {MAX_STEPS} steps")
    kind = step.get("type")
    _need(kind in STEP_TYPES, where, f"type is one of {', '.join(STEP_TYPES)}")
    _need(isinstance(step.get("enabled", True), bool), where, "enabled is true or false")
    if kind == "filter":
        rules = step.get("rules", [])
        _need(isinstance(rules, list) and len(rules) <= MAX_RULES, where, f"rules are a list of at most {MAX_RULES}")
        for n, rule in enumerate(rules):
            at = f"{where} rule {n + 1}"
            _need(isinstance(rule, dict) and set(rule) <= {"when", "match", "then", "stop"}, at,
                  "a rule has when, match, then and stop")
            check_conds(rule.get("when", []), at)
            _need(rule.get("match", "all") in ("all", "any"), at, "match is all or any")
            _need(isinstance(rule.get("then", []), list), at, "then is a list of actions")
            for m, action in enumerate(rule.get("then", [])):
                check_action(action, f"{at} action {m + 1}")
            _need(isinstance(rule.get("stop", False), bool), at, "stop is true or false")
    elif kind == "decide":
        _need(("set" in step) != ("questions" in step), where, "decide takes a question set or questions, not both")
        if "set" in step:
            question_set(step["set"])
        else:
            try:
                J.validate({}, step["questions"])
            except J.JudgeError as exc:
                raise Invalid(f"{where}: {exc.detail}") from None
        _need(step.get("level", "low") in LEVELS, where, f"level is one of {', '.join(LEVELS)}")
        _need(isinstance(step.get("out"), str) and NAME.fullmatch(step["out"]), where, "out names the answers, such as d1")
    elif kind == "llm":
        _need(isinstance(step.get("as"), str) and re.fullmatch(r"(assistant:|bot:)[a-z0-9][a-z0-9._-]{0,63}", step["as"]),
              where, "as is assistant:<person> or bot:<slug>")
        _text(step.get("prompt"), where, "prompt")
        _need(isinstance(step.get("out"), str) and NAME.fullmatch(step["out"]), where, "out names the result, such as draft")
    elif kind == "find":
        _need(depth == 0, where, "find is a top-level step")
        _need(not counts[1], where, "a flow has one find")
        counts[1] = True
        _need(step.get("source") in SOURCES, where, f"source is one of {', '.join(SOURCES)}")
        _text(step.get("query", ""), where, "query", required=False, cap=500)
        _need(step.get("since", "last_run") == "last_run", where, "since is last_run")
        limit = step.get("limit", 20)
        _need(isinstance(limit, int) and not isinstance(limit, bool) and 1 <= limit <= MAX_FIND, where,
              f"limit is 1 to {MAX_FIND}")
    elif kind == "bot_turn":
        _need(isinstance(step.get("bot"), str) and re.fullmatch(r"(bot:)?[a-z0-9][a-z0-9._-]{0,63}", step["bot"]), where,
              "bot names a bot")
        _text(step.get("prompt"), where, "prompt")
    elif kind == "action":
        check_action({"do": step.get("do"), "args": step.get("args", {})}, where)
    elif kind == "paths":
        _need(depth < MAX_DEPTH, where, f"paths nest at most {MAX_DEPTH} levels")
        paths = step.get("paths")
        _need(isinstance(paths, list) and 1 <= len(paths) <= MAX_PATHS, where, f"a fork has 1 to {MAX_PATHS} paths")
        names = set()
        for n, path in enumerate(paths):
            at = f"{where} path {n + 1}"
            _need(isinstance(path, dict) and set(path) <= {"name", "when", "steps"}, at, "a path has name, when and steps")
            _text(path.get("name"), at, "name", cap=80)
            _need(path["name"] not in names, at, "path names are unique in the fork")
            names.add(path["name"])
            check_conds(path.get("when", []), at)
            _check_steps(path.get("steps", []), at, seen, depth + 1, counts)
        otherwise = step.get("otherwise")
        if otherwise is not None:
            _need(isinstance(otherwise, dict) and set(otherwise) <= {"steps"}, where, "otherwise is a map with steps")
            _check_steps(otherwise.get("steps", []), f"{where} otherwise", seen, depth + 1, counts)


def _check_steps(steps, where, seen, depth, counts):
    _need(isinstance(steps, list), where, "steps are a list")
    for n, step in enumerate(steps):
        _check_step(step, f"{where} step {n + 1}", seen, depth, counts)
        # Paths never rejoin: what comes after a fork would run on no path in particular.
        _need(step.get("type") != "paths" or n == len(steps) - 1, f"step {step['id']}",
              "paths end their list; put what follows inside each path")


def question_set(ref):
    """`mail-triage@1` (or a bare name): the set's questions. The version, when given, must be the one installed."""
    _need(isinstance(ref, str) and ref, "decide", "set names a question set such as mail-triage@1")
    name, _, version = ref.partition("@")
    try:
        data = J.load_set(name)
    except J.JudgeError as exc:
        raise Invalid(f"decide: {exc.detail}") from None
    _need(not version or version == str(data["version"]), "decide",
          f"{name} is at version {data['version']}, not {version}")
    return data["questions"]


def check(flow):
    """Refuse a flow that cannot run (Invalid). Returns the flow with defaults filled."""
    _need(isinstance(flow, dict), "automation", "is a map")
    _text(flow.get("name"), "name", "the name", cap=120)
    owner = owner_ref(flow.get("owner"))
    _need(OWNER.fullmatch(owner), "owner", "is person:<id>, bot:<slug> or group:<id>")
    if flow.get("group"):
        _need(isinstance(flow["group"], str) and re.fullmatch(r"group:[a-z0-9][a-z0-9._-]{0,63}", flow["group"]),
              "group", "is group:<id>")
    cap = flow.get("spend_cap")
    if cap is not None:
        _need(isinstance(cap, dict) and set(cap) == {"per_30m"} and _number(cap["per_30m"]) is not None
              and 0 <= float(cap["per_30m"]) <= 10_000, "spend_cap", "is {per_30m: dollars}")
    batch = flow.get("batch")
    if batch is not None:
        _need(isinstance(batch, dict) and set(batch) <= {"times", "tz"} and isinstance(batch.get("times"), list)
              and 1 <= len(batch["times"]) <= 24 and all(isinstance(t, str) and CLOCK.fullmatch(t) for t in batch["times"]),
              "batch", "times are 1 to 24 clock times such as 08:00")
        _check_zone(batch.get("tz") or "UTC", "batch")
    _check_trigger(flow.get("trigger"))
    counts = [0, False]
    _check_steps(flow.get("steps", []), "steps", set(), 0, counts)
    return {**flow, "owner": owner, "enabled": flow.get("enabled", True) is not False,
            "builtin": flow.get("builtin") is True, "steps": flow.get("steps", [])}


# ---------------------------------------------------------------------------------------------------- conditions
def _number(value):
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    try:
        return float(str(value).strip())
    except (TypeError, ValueError):
        return None


def _same(a, b):
    if isinstance(a, str) and isinstance(b, str):
        return a.strip().casefold() == b.strip().casefold()
    if isinstance(a, bool) or isinstance(b, bool):
        return a is b or str(a).lower() == str(b).lower()
    na, nb = _number(a), _number(b)
    if na is not None and nb is not None and not isinstance(a, str) and not isinstance(b, str):
        return na == nb
    return a == b


def lookup(values, field):
    """The value at a dotted field, or None."""
    found = templating.lookup(values, field)
    return None if found is templating.MISSING else found


def _is_answer(value):
    return isinstance(value, dict) and ("choice" in value or "noul" in value or "score" in value)


def _answer_is(answer, want, least):
    """A judge answer against `is <want>`: a choice is `want` with at least `least` probability; a yes/no (noul) is yes
    or no with at least that much (half when no `min` is set); a score equals the number."""
    if "choice" in answer:
        if not _same(answer["choice"], want):
            return False
        odds = answer.get("probabilities") or {}
        p = _number(odds.get(answer["choice"])) if answer["choice"] in odds else _number(answer.get("confidence"))
        return least is None or (p or 0) >= least
    if "noul" in answer:
        p = _number(answer.get("noul")) or 0.0
        yes = str(want).strip().lower() in ("yes", "true", "1")
        no = str(want).strip().lower() in ("no", "false", "0")
        floor = 0.5 if least is None else least
        return (yes and p >= floor) or (no and 1 - p >= floor)
    return _same(answer["score"], want)


def _plain(answer):
    """What a judge answer compares as with >=, <=, contains and matches: the choice, the score or the yes probability."""
    if "choice" in answer:
        return answer["choice"]
    if "score" in answer:
        return answer["score"]
    return answer["noul"]


def holds(cond, values):
    """Whether one condition holds for these values. A missing field holds only for `is_not`."""
    value, op, want, least = lookup(values, cond["field"]), cond["op"], cond.get("value"), cond.get("min")
    if op in ("is", "is_not"):
        if _is_answer(value):
            hit = _answer_is(value, want, least)
        elif isinstance(value, list):
            hit = any(_same(v, want) for v in value)
        else:
            hit = value is not None and _same(value, want) if want is not None else value is None
        return hit if op == "is" else not hit
    if value is None:
        return False
    if _is_answer(value):
        value = _plain(value)
    if op in (">=", "<="):
        a, b = _number(value), _number(want)
        if a is None or b is None:
            return False
        return a >= b if op == ">=" else a <= b
    if op == "contains":
        if isinstance(value, (list, tuple)):
            return any(_same(v, want) for v in value)
        return str(want or "").casefold() in str(value).casefold()
    try:
        return re.search(str(want), templating.text_of(value), re.IGNORECASE) is not None
    except re.error:
        return False


def all_hold(conds, values, match="all"):
    """Every condition holds (`all`) or one does (`any`). No conditions hold."""
    if not conds:
        return True
    results = (holds(cond, values) for cond in conds)
    return any(results) if match == "any" else all(results)


def render(text, values, cap=MAX_TEXT):
    """`{{field}}` in a prompt or an action's text, from the run's values."""
    return templating.render(str(text or ""), values, cap=cap)


def render_args(args, values):
    return templating.render_json(args or {}, values)
