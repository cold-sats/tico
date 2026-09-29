"""Updates: every bot reports in once a day, and on Friday with the week.

"All bots report in daily, with Fridays being a more comprehensive week review ... a way to both
wake all bots make sure they are unstuck and make sure they make progress at least once per day."
"We should create a queue and get updates from the bots one at a time. These aren't really time
sensitive so it can take a while."

- `update_queue`: one request per enabled bot per day, sent one at a time (the next only once the
  last has posted or its run ended), so updates never crowd out real work on a Mac. Quietest bots
  first; a bot busy with a run is passed over and asked again later that day. A request is a
  keeper notice to the bot, which queues its run like any message; the facts it needs ride along.
- `updates`: what a bot posted (one per bot, day and kind; a second post replaces the first).
- `update_reads`: per person, so reading one is never someone else's read.
- A reply is an ordinary chat message to the bot carrying `refs.update`; the bot's session gets it
  like any message, and the update's thread is those replies plus the bot's answers to them.
- `update_settings`: a bot's daily and weekly switches (both on unless turned off).
"""
import json
import re
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from .store import H, Problem

ZONE = ZoneInfo("America/Los_Angeles")
START_HOUR = 5              # the day's queue is built from 05:00 Pacific
RUN_LIMIT_S = 75 * 60       # a request whose run has not ended in this long is given up on
PICKUP_LIMIT_S = 20 * 60    # ...and one no computer picked up in this long: move on (it may still post later)
KINDS = ("daily", "weekly")
# A linter rejects any update that runs long and sends the bot feedback. The feed is skimmed; a wall of text is refused with how to
# write it, and the bot posts again. A writing correction, so it never counts toward quarantine.
# Updates have no title and no sections, just 1-5 bullets, never task ids, only plain English;
# the word limits are 10% under the old 100 words.
BULLETS_MAX = 5
LIMITS = {"daily": {"words": 90, "bullet": 25}, "weekly": {"words": 180, "bullet": 40}}
SHAPE = ("An update is one to five bullets in plain English and nothing else: no title, no headings or "
         "sections (no Done / Next), no task ids or internal codes. Each bullet is one line: what you did, "
         "what you do next, or what waits on a person. Link a doc or PR in the words if it helps.")
BULLET = re.compile(r"^\s*[-*•]\s+\S")
HEADING = re.compile(r"^\s*(#{1,6}\s|\*\*[^*]+\*\*:?\s*$|__[^_]+__:?\s*$|[A-Z][A-Za-z /]{0,30}:\s*$)")
LABEL = re.compile(r"^\s*[-*•]\s+(\*\*[^*]+\*\*|(done|next|blocked|needs you|blocked / needs you|this week|next week)\s*[:—-])", re.I)
MD_LINK = re.compile(r"\[([^\]]*)\]\([^)]*\)")
TASK_ID = re.compile(r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b"
                     r"|\b(?=[0-9a-f]*\d)(?=[0-9a-f]*[a-f])[0-9a-f]{7,}\b"
                     r"|\b(?:task|job|attempt|msg|message)[:#\s]+[0-9a-f]{4,}\b", re.I)

SCHEMA = """
CREATE TABLE IF NOT EXISTS updates(
 id TEXT PRIMARY KEY, bot TEXT NOT NULL, kind TEXT NOT NULL, day TEXT NOT NULL,
 headline TEXT NOT NULL, body TEXT NOT NULL DEFAULT '', created TEXT NOT NULL, updated TEXT NOT NULL,
 UNIQUE(bot, kind, day));
CREATE INDEX IF NOT EXISTS updates_created ON updates(created);
CREATE TABLE IF NOT EXISTS update_reads(
 update_id TEXT NOT NULL, actor TEXT NOT NULL, read_at TEXT NOT NULL, PRIMARY KEY(update_id, actor));
CREATE TABLE IF NOT EXISTS update_queue(
 id TEXT PRIMARY KEY, bot TEXT NOT NULL, kind TEXT NOT NULL, day TEXT NOT NULL, rank INTEGER NOT NULL,
 state TEXT NOT NULL, message_id TEXT, sent_at TEXT, done_at TEXT, reason TEXT,
 UNIQUE(bot, kind, day));
CREATE INDEX IF NOT EXISTS update_queue_day ON update_queue(day, state, rank);
CREATE TABLE IF NOT EXISTS update_settings(
 bot TEXT PRIMARY KEY, daily INTEGER NOT NULL DEFAULT 1, weekly INTEGER NOT NULL DEFAULT 1);
"""


def local_now(at=None):
    at = at or H.parse_ts(H.now())
    return at.astimezone(ZONE)


def today(at=None):
    return local_now(at).date().isoformat()


def kind_for(day):
    """Friday's update is the week in review; every other day's is the daily one."""
    return "weekly" if datetime.fromisoformat(day).weekday() == 4 else "daily"


def settings(c, bot):
    row = c.execute("SELECT daily, weekly FROM update_settings WHERE bot=?", (bot,)).fetchone()
    return {"daily": bool(row["daily"]) if row else True, "weekly": bool(row["weekly"]) if row else True}


def set_settings(c, bot, daily=None, weekly=None):
    now = settings(c, bot)
    daily = now["daily"] if daily is None else bool(daily)
    weekly = now["weekly"] if weekly is None else bool(weekly)
    c.execute("INSERT INTO update_settings(bot,daily,weekly) VALUES(?,?,?) ON CONFLICT(bot) DO UPDATE SET "
              "daily=excluded.daily, weekly=excluded.weekly", (bot, int(daily), int(weekly)))
    return {"daily": daily, "weekly": weekly}


# ----------------------------------------------------------------------------- the queue
def build_queue(c, day, kind):
    """Today's requests, once: every active bot whose switch for `kind` is on, quietest first."""
    if c.execute("SELECT 1 FROM update_queue WHERE day=? LIMIT 1", (day,)).fetchone():
        return 0
    rows = c.execute(
        "SELECT b.slug, (SELECT max(u.created) FROM updates u WHERE u.bot=b.slug) last_update, "
        "(SELECT last_turn_at FROM bot_status s WHERE s.bot=b.slug) last_turn "
        "FROM bots b LEFT JOIN update_settings us ON us.bot=b.slug "
        "WHERE b.state='active' AND coalesce(us." + ("daily" if kind == "daily" else "weekly") + ",1)=1").fetchall()
    order = sorted(rows, key=lambda r: (r["last_update"] or "", r["last_turn"] or "", r["slug"]))
    for rank, row in enumerate(order):
        c.execute("INSERT INTO update_queue(id,bot,kind,day,rank,state) VALUES(?,?,?,?,?,'queued')",
                  (H.new_id(), row["slug"], kind, day, rank))
    return len(order)


def _busy(c, bot):
    return c.execute("SELECT 1 FROM jobs WHERE bot=? AND state IN ('queued','leased','running','input') LIMIT 1",
                     (bot,)).fetchone() is not None


def ensure_schema(c):
    """Columns added after the tables first shipped."""
    H.add_column(c, "update_queue", "tries", "INTEGER NOT NULL DEFAULT 0")


def _retry_or_miss(c, row, reason):
    """A run that ended without a post is asked once more, at the end of the day's queue: its
    computer may not have had the posting command yet (the first request can go out a
    minute after a deploy, before the computer's checkout catches up), or the run went sideways."""
    if (row["tries"] if "tries" in row.keys() else 0) < 1:
        last = c.execute("SELECT coalesce(max(rank), 0) FROM update_queue WHERE day=?", (row["day"],)).fetchone()[0]
        c.execute("UPDATE update_queue SET state='queued', rank=?, tries=tries+1, message_id=NULL, sent_at=NULL, "
                  "reason=? WHERE id=?", (last + 1, reason, row["id"]))
        return
    _finish(c, row, "missed", reason)


def _finish(c, row, state, reason=None):
    c.execute("UPDATE update_queue SET state=?, done_at=?, reason=? WHERE id=?", (state, H.now(), reason, row["id"]))


def settle_sent(c, row):
    """The request out now: posted, ended without a post, or still going. True while it is going."""
    if c.execute("SELECT 1 FROM updates WHERE bot=? AND kind=? AND day=?", (row["bot"], row["kind"], row["day"])).fetchone():
        _finish(c, row, "posted")
        return False
    job = c.execute("SELECT j.state, a.state attempt_state FROM jobs j LEFT JOIN attempts a ON a.id=j.attempt_id "
                    "WHERE j.message_id=?", (row["message_id"],)).fetchone()
    age = (H.parse_ts(H.now()) - H.parse_ts(row["sent_at"])).total_seconds()
    if job and job["state"] in ("completed", "cancelled", "uncertain", "held"):
        _retry_or_miss(c, row, {"completed": "its run ended without posting an update",
                                   "cancelled": "the request was cancelled",
                                   "uncertain": "its run stopped part-way",
                                   "held": "it could not run"}.get(job["state"], job["state"]))
        return False
    if (not job or job["state"] == "queued") and age > PICKUP_LIMIT_S:
        # Its computer is off, or it runs elsewhere (an external agent has no job here). The
        # request stays with the bot, and a late post still lands; the queue moves on.
        _finish(c, row, "missed", "it had not started after 20 minutes" if job else "it did not pick the request up")
        return False
    if age > RUN_LIMIT_S + PICKUP_LIMIT_S:
        _finish(c, row, "missed", "its run did not end")
        return False
    return True


def request_text(c, bot, kind, day):
    """What the bot is asked, with its facts: done since its last update, open work, what waits on
    a person, its goals. It writes from these, so the turn is short and says only what happened."""
    actor = H.bot_actor(bot)
    last = c.execute("SELECT max(created) FROM updates WHERE bot=?", (bot,)).fetchone()[0]
    since = last or H.shift(H.now(), days=-7 if kind == "weekly" else -1)
    done = c.execute("SELECT title FROM tasks WHERE owner=? AND status IN ('done','closed') AND updated>=? "
                     "ORDER BY updated DESC LIMIT 12", (actor, since)).fetchall()
    open_ = c.execute("SELECT title, status FROM tasks WHERE owner=? AND status IN ('open','doing','waiting','review','ready') "
                      "ORDER BY updated DESC LIMIT 12", (actor,)).fetchall()
    asked = c.execute("SELECT title, owner FROM tasks WHERE requester=? AND owner LIKE 'human:%' AND status IN "
                      "('open','doing','waiting') ORDER BY updated DESC LIMIT 8", (actor,)).fetchall()
    goals = c.execute("SELECT title FROM goals WHERE owner=? AND (status IS NULL OR status NOT IN ('done','dropped')) "
                      "ORDER BY rank LIMIT 5", (actor,)).fetchall()
    line = lambda rows, f: "\n".join("- " + f(r) for r in rows) or "- (none)"
    week = kind == "weekly"
    return "\n".join([
        f"Time for your {'week in review' if week else 'daily update'} ({day}). Post it with hub_update_post "
        "(or `hub update post`), in plain words, then carry on.",
        "",
        "Write one to five bullets in plain English and nothing else: no title, no headings or sections, "
        "no task ids or internal codes. Each bullet is one line: what you did, what you do next, or what "
        f"waits on a person (say who). At most {LIMITS[kind]['bullet']} words a bullet and {LIMITS[kind]['words']} in all."
        + (" For the week: what got done, how your goals went, and your one or two commitments for next week." if week else ""),
        "If nothing got done, say why in one bullet, then pick your most useful open task and start it in "
        "this turn. Every bot moves at least once a day. An update that breaks these rules is refused.",
        "",
        f"Finished {'this week' if week else 'since your last update'}:", line(done, lambda r: r["title"]),
        "Open:", line(open_, lambda r: f"{r['title']} ({r['status']})"),
        "Waiting on a person:", line(asked, lambda r: f"{r['title']} ({H.actor_id(r['owner'])})"),
        "Your goals:", line(goals, lambda r: r["title"]),
    ])


def send_request(c, row):
    message = H.say(c, H.KEEPER, H.bot_actor(row["bot"]), request_text(c, row["bot"], row["kind"], row["day"]),
                    kind="notice", refs={"update_request": row["id"], "wake": "update"})
    c.execute("UPDATE update_queue SET state='sent', message_id=?, sent_at=? WHERE id=?",
              (message["id"], H.now(), row["id"]))
    return message


def dispatch(c, at=None):
    """One step, from the scheduler's tick: build today's queue after 05:00, settle the request
    that is out, and send the next one. At most one request is out at a time."""
    local = local_now(at)
    day = local.date().isoformat()
    if local.hour >= START_HOUR:
        build_queue(c, day, kind_for(day))
    out = c.execute("SELECT * FROM update_queue WHERE state='sent' ORDER BY sent_at LIMIT 1").fetchone()
    if out and settle_sent(c, out):
        return None
    for row in c.execute("SELECT q.* FROM update_queue q JOIN bots b ON b.slug=q.bot WHERE q.state='queued' "
                         "AND q.day=? ORDER BY q.rank", (day,)).fetchall():
        bot = H.bot(c, row["bot"]) or {}
        if bot.get("state") != "active":
            _finish(c, row, "skipped", "the bot is " + (bot.get("state") or "gone"))
            continue
        if not settings(c, row["bot"])[row["kind"]]:
            _finish(c, row, "skipped", "its " + row["kind"] + " update is switched off")
            continue
        if _busy(c, row["bot"]):
            continue                      # asked later today, once its run is over
        send_request(c, row)
        return row["bot"]
    # A day that ends with bots never free leaves their requests behind; they are missed.
    for row in c.execute("SELECT * FROM update_queue WHERE state='queued' AND day<?", (day,)).fetchall():
        _finish(c, row, "missed", "it was busy all day")
    return None


# ----------------------------------------------------------------------------- posting and reading
def lint(body, kind):
    """What is wrong with an update, or None: 1-5 one-line bullets, plain English, short."""
    limit = LIMITS[kind]
    lines = [line for line in str(body or "").splitlines() if line.strip()]
    problems = []
    if not lines:
        problems.append("it is empty")
    headings = [line.strip() for line in lines if HEADING.match(line)]
    if headings:
        problems.append("it has a title or section heading (" + ", ".join(repr(h[:30]) for h in headings[:3]) + ")")
    loose = [line.strip() for line in lines if not BULLET.match(line) and not HEADING.match(line)]
    if loose:
        problems.append(f"{len(loose)} line{'s are' if len(loose) != 1 else ' is'} not a bullet (" + repr(loose[0][:40]) + ")")
    bullets = [line for line in lines if BULLET.match(line)]
    labelled = [b.strip() for b in bullets if LABEL.match(b)]
    if labelled:
        problems.append("a bullet starts with a section label (" + repr(labelled[0][:30]) + ")")
    if len(bullets) > BULLETS_MAX:
        problems.append(f"it has {len(bullets)} bullets (at most {BULLETS_MAX})")
    long = [len(b.split()) - 1 for b in bullets if len(b.split()) - 1 > limit["bullet"]]
    if long:
        problems.append(f"{len(long)} bullet{'s are' if len(long) != 1 else ' is'} over {limit['bullet']} words (longest {max(long)})")
    words = sum(len(b.split()) - 1 for b in bullets)
    if words > limit["words"]:
        problems.append(f"it is {words} words (a {kind} update is at most {limit['words']})")
    visible = MD_LINK.sub(r"\1", str(body or ""))
    ids = TASK_ID.findall(visible)
    if ids:
        problems.append("it has a task id or internal code (" + ", ".join(sorted(set(ids))[:3]) + "); say it in plain English")
    if not problems:
        return None
    return ("Not an update yet: " + "; ".join(problems) + ". " + SHAPE
            + " Rewrite it and post again with hub_update_post.")


def post(c, bot, body, kind=None, day=None):
    """Store a bot's bullets. `headline` keeps its first bullet, for places that show one line
    (MCP summaries); the feed shows only the bullets."""
    day = day or today()
    kind = kind or kind_for(day)
    if kind not in KINDS:
        raise Problem("kind", "An update is daily or weekly", 422)
    body = "\n".join(line.rstrip() for line in str(body or "").strip().splitlines() if line.strip())
    problem = lint(body, kind)
    if problem:
        raise H.Refused("lint", problem, "normal")
    first = body.splitlines()[0]
    headline = MD_LINK.sub(r"\1", re.sub(r"^\s*[-*•]\s+", "", first))[:200]
    now = H.now()
    existing = c.execute("SELECT id FROM updates WHERE bot=? AND kind=? AND day=?", (bot, kind, day)).fetchone()
    if existing:
        c.execute("UPDATE updates SET headline=?, body=?, updated=? WHERE id=?", (headline, body, now, existing["id"]))
        c.execute("DELETE FROM update_reads WHERE update_id=?", (existing["id"],))   # changed: unread again
        uid = existing["id"]
    else:
        uid = H.new_id()
        c.execute("INSERT INTO updates(id,bot,kind,day,headline,body,created,updated) VALUES(?,?,?,?,?,?,?,?)",
                  (uid, bot, kind, day, headline, body, now, now))
    H.event(c, H.bot_actor(bot), "update.post", uid, {"kind": kind, "day": day})
    return one(c, uid)


def purge_rejected(c):
    """Delete stored updates the linter would refuse now and ask their bots again (rejected updates are
    deleted and redone). Runs when the hub
    starts; the linter refuses new ones at the door. Each bot goes to the back of its day's queue."""
    removed = []
    for row in c.execute("SELECT * FROM updates").fetchall():
        if not lint(row["body"], row["kind"]):
            continue
        c.execute("DELETE FROM update_reads WHERE update_id=?", (row["id"],))
        c.execute("DELETE FROM updates WHERE id=?", (row["id"],))
        last = c.execute("SELECT coalesce(max(rank), 0) FROM update_queue WHERE day=?", (row["day"],)).fetchone()[0]
        c.execute("INSERT INTO update_queue(id,bot,kind,day,rank,state,tries) VALUES(?,?,?,?,?,'queued',0) "
                  "ON CONFLICT(bot,kind,day) DO UPDATE SET state='queued', rank=excluded.rank, tries=0, "
                  "message_id=NULL, sent_at=NULL, done_at=NULL, reason='asked again: the last one broke the update rules'",
                  (H.new_id(), row["bot"], row["kind"], row["day"], last + 1))
        H.event(c, H.KEEPER, "update.rejected", row["id"], {"bot": row["bot"]})
        removed.append(row["bot"])
    # The ones #635 deleted as "not given" (too long) are asked again the same way.
    for row in c.execute("SELECT * FROM update_queue WHERE state='missed' AND reason LIKE 'its update was too long%'").fetchall():
        last = c.execute("SELECT coalesce(max(rank), 0) FROM update_queue WHERE day=?", (row["day"],)).fetchone()[0]
        c.execute("UPDATE update_queue SET state='queued', rank=?, tries=0, message_id=NULL, sent_at=NULL, done_at=NULL, "
                  "reason='asked again: the last one broke the update rules' WHERE id=?", (last + 1, row["id"]))
        removed.append(row["bot"])
    return removed


def one(c, uid):
    row = c.execute("SELECT * FROM updates WHERE id=?", (uid,)).fetchone()
    return dict(row) if row else None


def thread(c, uid):
    """Replies to an update (messages carrying refs.update) and the bot's answers to them."""
    replies = [dict(r) for r in c.execute(
        "SELECT id, from_actor, to_actor, body, created, conversation_id FROM messages "
        "WHERE json_extract(refs_json,'$.update')=? ORDER BY created", (uid,))]
    ids = [r["id"] for r in replies]
    answers = [dict(r) for r in c.execute(
        "SELECT id, from_actor, to_actor, body, created, conversation_id, in_reply_to FROM messages WHERE in_reply_to IN ("
        + ",".join("?" * len(ids)) + ") ORDER BY created", ids)] if ids else []
    return sorted(replies + answers, key=lambda m: m["created"])


def _only(bots, column="u.bot"):
    """The SQL for "updates of these bots" (`bots` is the slugs the caller may read), so pages and
    counts are cut in the query and a hidden bot's updates leave no gap or number behind."""
    return f"{column} IN ({','.join('?' * len(bots))})", list(bots)


def listing(c, actor, readable, kind=None, bot=None, unread=False, before=None, limit=40):
    """The feed, newest first, with this person's read state, reply counts, and the requests that
    ended without an update (so a silent bot shows). `readable` is the set of bots to show."""
    where, args = ["1=1"], []
    if not readable:
        where.append("0")
    else:
        clause, values = _only(sorted(readable))
        where.append(clause)
        args += values
    if kind:
        where.append("u.kind=?"); args.append(kind)
    if bot:
        where.append("u.bot=?"); args.append(bot)
    if before:
        where.append("u.created<?"); args.append(before)
    if unread:
        where.append("r.read_at IS NULL")
    rows = c.execute(
        "SELECT u.*, r.read_at FROM updates u LEFT JOIN update_reads r ON r.update_id=u.id AND r.actor=? "
        "WHERE " + " AND ".join(where) + " ORDER BY u.created DESC LIMIT ?", (actor, *args, limit)).fetchall()
    items = []
    for row in rows:
        item = dict(row)
        item["read"] = bool(item.pop("read_at"))
        item["replies"] = c.execute("SELECT count(*) FROM messages WHERE json_extract(refs_json,'$.update')=?",
                                    (row["id"],)).fetchone()[0]
        items.append(item)
    missed = []
    if not unread and not before:
        for row in c.execute("SELECT bot, kind, day, reason, done_at FROM update_queue WHERE state='missed' "
                             "AND day>=? ORDER BY done_at DESC", (H.shift(H.now(), days=-2)[:10],)).fetchall():
            late = c.execute("SELECT 1 FROM updates WHERE bot=? AND kind=? AND day=?",
                             (row["bot"], row["kind"], row["day"])).fetchone()
            if not late and row["bot"] in readable and (not kind or row["kind"] == kind) and (not bot or row["bot"] == bot):
                missed.append(dict(row))
    unread_count = count_unread(c, actor, readable, kind)
    queue = c.execute("SELECT state, count(*) n FROM update_queue WHERE day=? GROUP BY state", (today(),)).fetchall()
    return {"updates": items, "missed": missed, "unread": unread_count,
            "next_before": items[-1]["created"] if len(items) >= limit else None,
            "today": {r["state"]: r["n"] for r in queue}}


def count_unread(c, actor, readable, kind=None):
    """How many updates of the last two weeks this person has not read (the badge)."""
    if not readable:
        return 0
    clause, values = _only(sorted(readable))
    return c.execute("SELECT count(*) FROM updates u LEFT JOIN update_reads r ON r.update_id=u.id AND r.actor=? "
                     f"WHERE r.read_at IS NULL AND u.created>=? AND {clause}" + (" AND u.kind=?" if kind else ""),
                     (actor, H.shift(H.now(), days=-14), *values, *([kind] if kind else []))).fetchone()[0]


def mark(c, actor, ids, read=True):
    now = H.now()
    for uid in ids:
        if read:
            c.execute("INSERT OR IGNORE INTO update_reads VALUES(?,?,?)", (uid, actor, now))
        else:
            c.execute("DELETE FROM update_reads WHERE update_id=? AND actor=?", (uid, actor))
    return len(ids)
