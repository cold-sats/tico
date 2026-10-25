"""Failed runs wait, then stop (quiet task flow, section 7).

A bot's run that fails within FAST seconds of starting is not the same as one that fails after real work: it
changed nothing and will fail the same way again. Each such failure makes the bot wait before its next run, per bot,
15 s doubling to 8 h and reset by a run that completes normally. A person's message sent after the last failure does not wait it out:
it is the retry someone is watching, and its failure counts like any other (re-queued, it then waits as the rest do). After HOLD_AFTER of them in a row the bot is held:
no claim starts its queued work (a person's chat message included) until a person releases it, and the bot's
operator gets one Needs-you item while Health names the error class. The held bot's queued work is kept.

A failure that is a provider's usage limit takes the usage-limit hold instead (backend/login_holds.py), however the
provider wrapped it: `classify` reads the text of any failed run, so a runner that did not flag it (an older one)
or an error that nests the limit inside another ("Prompt is too long - automatic compaction failed: You've hit
your weekly limit - resets Oct 26, 8pm (UTC)") still waits for the reset the text names. A failure that says the
session's prompt grew too large to send ("too many total text bytes", "Prompt is too long") starts the next run in a
fresh provider session, as a person's Clear does, rather than resuming the same session into the same error.

What does not count: a run a person stopped, a usage limit or a model at capacity (their own waits), a run that
yielded or was handed back, and a run that failed after FAST seconds of work. Only a completed run resets the count.
"""

import json
import re

from clients import gateway

from . import login_holds
from .store import H

FAST = 60                 # a run that fails sooner than this after starting is a fast failure
FIRST_WAIT = 15           # seconds the bot waits after its first fast failure; doubles for each one in a row
MAX_WAIT = 8 * 3600       # and never longer than this
HOLD_AFTER = 5            # fast failures in a row that hold the bot until a person releases it
ERROR_CHARS = 300

SCHEMA = (
    "CREATE TABLE IF NOT EXISTS run_backoff(bot TEXT PRIMARY KEY, fails INTEGER NOT NULL DEFAULT 0, wait_until TEXT, "
    "error_class TEXT, error TEXT, last_failed TEXT, held_at TEXT, task_id TEXT, released_at TEXT, released_by TEXT)",)

# A provider's limit named anywhere in an error: "You've hit your weekly limit", "usage limit reached", "rate limit".
LIMIT_RE = re.compile(r"hit your (?:[a-z-]+ ){0,2}limit|\b(?:weekly|usage|session|monthly|spend(?:ing)?|rate|\d+-hour) "
                      r"limit|limit reached|usage_limit_reached|rate_limit_error", re.I)
# The session's prompt is too large to send; the same session fails the same way next time.
TOO_LONG_RE = re.compile(r"too many total text bytes|prompt is too long", re.I)
SIGN_IN_RE = re.compile(r"sign.?in|log.?in|unauthorized|authentication|invalid (?:x-)?api.?key|\b401\b", re.I)

USAGE_LIMIT, PROMPT_TOO_LONG, SIGN_IN, GATEWAY, OTHER = "usage_limit", "prompt_too_long", "sign_in", "gateway", "other"
CLASS_WORDS = {
    USAGE_LIMIT: "a provider usage limit",
    PROMPT_TOO_LONG: "the session grew too large to send",
    SIGN_IN: "the AI sign-in was refused",
    GATEWAY: "the Tico AI Gateway refused the run",
    OTHER: "an error before any work",
}


def ensure(c):
    for statement in SCHEMA:
        c.execute(statement)


def is_limit(text, now=None):
    """Whether an error's text says the provider's usage limit was hit, however the rest of it is worded. A model at
    capacity or a Tico Gateway code is not (login_holds.capacity, clients/gateway.py): they have their own waits."""
    text = str(text or "")
    if not text or gateway.run_code(text) or login_holds.capacity(text):
        return False
    return bool(LIMIT_RE.search(text) or login_holds.reset_from_text(text, now or H.now()))


def error_class(text):
    """What kind of failure an error text shows: one of USAGE_LIMIT, PROMPT_TOO_LONG, SIGN_IN, GATEWAY, OTHER."""
    text = str(text or "")
    if is_limit(text):
        return USAGE_LIMIT
    if TOO_LONG_RE.search(text):
        return PROMPT_TOO_LONG
    if gateway.run_code(text):
        return GATEWAY
    return SIGN_IN if SIGN_IN_RE.search(text) else OTHER


SUMMARY_CHARS = 600       # a failed run's summary is read as an error only when it is this short, never a long reply


def texts(c, aid, body):
    """What a failed run said went wrong: the runtime's error events, newest first, then its summary when it is short
    enough to be the error itself (a bot's own long text that mentions a limit is not one)."""
    from .execution import limit_errors
    summary = body.text if len(body.text or "") <= SUMMARY_CHARS else ""
    return [t for t in (*limit_errors(c, aid), summary) if t]


def classify(c, aid, body, now=None):
    """Read a failed or interrupted run's text and fix what an older runner did not say. A provider limit anywhere in
    it sets `body.limited` and, when the text names one, `limit_resets_at`, so the run takes the usage-limit hold
    (login_holds.after_turn) until that reset; the error events that show it are marked as limit notices, as a
    current runner marks them. Answers the kind of failure: USAGE_LIMIT, PROMPT_TOO_LONG or None."""
    now = now or H.now()
    if body.limited or body.fallback or body.primary_limited:
        return USAGE_LIMIT if body.limited else None   # the runner already read its limits (and any fallback's) itself
    found = [t for t in texts(c, aid, body) if is_limit(t, now)]
    if found:
        body.limited = True
        if not body.limit_resets_at:
            for text in found:
                reset = login_holds.believable(login_holds.reset_from_text(text, now), now)
                if reset:
                    body.limit_resets_at = login_holds._iso(reset)
                    break
        for event in c.execute("SELECT id,payload_json FROM attempt_events WHERE attempt_id=? AND kind='error'",
                               (aid,)).fetchall():
            try:
                payload = json.loads(event["payload_json"])
            except ValueError:
                continue
            if isinstance(payload, dict) and not payload.get("limit") and is_limit(payload.get("error"), now):
                c.execute("UPDATE attempt_events SET payload_json=? WHERE id=?",
                          (json.dumps({**payload, "limit": True}), event["id"]))
        return USAGE_LIMIT
    if any(TOO_LONG_RE.search(t) for t in texts(c, aid, body)):
        return PROMPT_TOO_LONG
    return None


def fresh_session(c, settings, bot, conversation_id, aid):
    """The bot's next run in this conversation starts a new provider session (views.clear_chat_session, the same
    mechanism as a person's Clear): its history is reloaded from Tico instead of resuming the session that no longer
    fits."""
    from .views import clear_chat_session
    clear_chat_session(c, settings, H.KEEPER, bot, conversation_id, {"reason": PROMPT_TOO_LONG, "attempt": aid})


# ---------------------------------------------------------------------------------------------------- the state
def get(c, bot):
    row = c.execute("SELECT * FROM run_backoff WHERE bot=?", (bot,)).fetchone()
    return dict(row) if row else {}


def wait_for(fails):
    """Seconds the bot waits after `fails` fast failures in a row."""
    return min(FIRST_WAIT * 2 ** max(fails - 1, 0), MAX_WAIT)


def refusal(c, bot):
    """Why a claim passes over all of the bot's work for its failed runs: "run_hold" while it is held, "backoff" until
    its wait ends, else None. Read only, as every refusal (execution.claim_refusal)."""
    row = c.execute("SELECT held_at,wait_until FROM run_backoff WHERE bot=?", (bot,)).fetchone()
    if not row:
        return None
    if row["held_at"]:
        return "run_hold"
    return "backoff" if row["wait_until"] and row["wait_until"] > H.now() else None


def _since_failure(c, bot):
    row = c.execute("SELECT last_failed FROM run_backoff WHERE bot=?", (bot,)).fetchone()
    return (row and row["last_failed"]) or ""


def person_waiting(c, bot):
    """Whether a person wrote to the bot since its last failed run: the job a back-off wait lets through."""
    return bool(c.execute("SELECT 1 FROM jobs j JOIN messages m ON m.id=j.message_id WHERE j.bot=? AND j.state='queued' "
                          "AND m.from_actor LIKE 'human:%' AND m.created>? LIMIT 1", (bot, _since_failure(c, bot))).fetchone())


def job_refusal(c, bot, message):
    """"backoff" for a job the bot's wait holds: any but a person's message sent since the last failure. Read only
    (execution.job_refusal)."""
    if refusal(c, bot) != "backoff":
        return None
    fresh = str(message.get("from_actor") or "").startswith("human:") and str(message.get("created") or "") > _since_failure(c, bot)
    return None if fresh else "backoff"


def reset(c, bot):
    """A run completed normally: the count starts over. A hold is not lifted by it (only a release does)."""
    c.execute("UPDATE run_backoff SET fails=0,wait_until=NULL WHERE bot=? AND held_at IS NULL AND fails>0", (bot,))


def fast(row, now):
    """Whether the run failed within FAST seconds of starting (its claim, for a run that never reported a start)."""
    began = H.parse_ts(row["started"] or row["created"])
    return bool(began) and (H.parse_ts(now) - began).total_seconds() < FAST


def failed(c, settings, row, body, aid, now=None):
    """Count a run that ended in failure and wait or hold. The caller leaves out the runs that do not count (a Stop, a
    usage limit, a busy model, a yield). A slow failure changes nothing. Answers the bot's new state, or None."""
    now = now or H.now()
    if not fast(row, now):
        return None
    bot = row["bot"]
    text = (texts(c, aid, body) or [""])[0]
    kind = error_class(text)
    error = " ".join(text.split())[:ERROR_CHARS]
    state = get(c, bot)
    fails = int(state.get("fails") or 0) + 1
    held = bool(state.get("held_at"))
    hold_now = fails >= HOLD_AFTER and not held
    wait = None if fails >= HOLD_AFTER else H.shift(now, seconds=wait_for(fails))
    c.execute("INSERT INTO run_backoff(bot,fails,wait_until,error_class,error,last_failed) VALUES(?,?,?,?,?,?) "
              "ON CONFLICT(bot) DO UPDATE SET fails=excluded.fails,wait_until=excluded.wait_until,"
              "error_class=excluded.error_class,error=excluded.error,last_failed=excluded.last_failed",
              (bot, fails, wait, kind, error, now))
    if hold_now:
        hold(c, settings, bot, fails, kind, error, now)
    return get(c, bot)


def hold(c, settings, bot, fails, kind, error, now):
    """Hold the bot: one Needs-you item for its operator, and an event. Its queued work is kept."""
    from . import bot_stops
    name = bot_stops.name_of(c, bot)
    task_id = bot_stops.raise_item(
        c, settings, bot, f"{name} stopped after {fails} failed runs in a row",
        f"Tico stopped {name}: its last {fails} runs each failed within a minute, with {CLASS_WORDS[kind]}.\n\n"
        f"Last error: {error or 'none was reported'}\n\n"
        f"Check its last runs in Runs. When the cause is fixed, release {name} (Settings > Bots > {name}, or "
        f"`hub bot release {bot}`). Everything queued for it is kept and starts after the release.")
    c.execute("UPDATE run_backoff SET held_at=?,task_id=? WHERE bot=?", (now, task_id, bot))
    H.event(c, H.KEEPER, "bot.run_held", bot, {"fails": fails, "error_class": kind, "task": task_id})


def release(c, actor, bot):
    """Lift the hold and the wait, and start the count over. Answers whether the bot had either."""
    state = get(c, bot)
    if not (state.get("held_at") or state.get("wait_until") or state.get("fails")):
        return False
    from . import bot_stops
    c.execute("UPDATE run_backoff SET fails=0,wait_until=NULL,held_at=NULL,task_id=NULL,released_at=?,released_by=? "
              "WHERE bot=?", (H.now(), actor, bot))
    bot_stops.close_item(c, state.get("task_id"), "Released.")
    if state.get("held_at"):
        H.event(c, actor, "bot.run_released", bot, {"fails": state.get("fails"), "error_class": state.get("error_class")})
    return bool(state.get("held_at") or state.get("wait_until"))


def held(c):
    """Every bot held for failed runs: the rows Health lists."""
    return [dict(r) for r in c.execute("SELECT * FROM run_backoff WHERE held_at IS NOT NULL ORDER BY held_at")]


def words(c, bot):
    """What the pages say about the bot's failed runs: the hold, or the wait before its next try."""
    from . import bot_stops
    state = get(c, bot)
    name = bot_stops.name_of(c, bot)
    if state.get("held_at"):
        cause = CLASS_WORDS.get(state.get("error_class")) or CLASS_WORDS[OTHER]
        return (f"Tico stopped {name}: its last {state.get('fails')} runs failed within a minute ({cause}). "
                "Check its last runs, then release it.")
    left = max(1, int((H.parse_ts(state.get("wait_until")) - H.parse_ts(H.now())).total_seconds())) \
        if state.get("wait_until") and H.parse_ts(state["wait_until"]) else 0
    return f"{name} is pausing {left} s after a failed run before it tries again" if left else ""
