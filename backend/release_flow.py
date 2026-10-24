"""The release rhythm of a team that ships Dev tickets: one release a day, on request, and what follows a release.

Three things, all in plain code, none asked of a model:

- **The schedule** (`release-schedule`, a team setting): once a day at a set hour in company time (`updates.ZONE`),
  a second hour if the team wants one, or off. At each hour the Release Manager gets ONE task, "Release: <n> tickets
  at Pending Release", listing them; with nothing at Pending Release nobody is woken. Pending Release arrivals are
  notes, so the Release Manager hears about the tickets only here (or from `release now`).
- **Release now** (`hub release now`): a person or bot who moves Dev tickets asks for the same task at once, for a
  hotfix or a midday release. An unfinished Release task is woken instead of a second one being filed.
- **`release_published`**: when a release is published, each Dev ticket it carries wakes its QA owner (post-release
  tests, only for a ticket tagged `qa`) and the Technical Writer (docs and release notes, after the release), once
  each, and every routine that runs `on: release_published` gets one task for the release. The Technical Writer's
  work starts here and nowhere earlier.

The Release Manager, the Technical Writer and a ticket's QA owner are found, never configured per ticket: the bot
the team named in the schedule setting, else the one active bot built from the `release-notes` template (writer:
`docs-writer`; QA: the owner of the ticket's `QA:` subtask, else its `qa` role, else the one `issue-triage` bot).
With none found the feature is idle for that role and says so (`GET /api/v2/release-schedule`).

A release carries the Dev tickets at the Pending Release step when it is published that have a pull request merged in
its repository; the rest of the factory's steps stay a person's or bot's to move (docs/software-factory.md).
"""
import json
import re
from datetime import datetime, timedelta

from .store import H, Problem

KEY = "release-schedule"
FIRED = "release-schedule-fired"
DEFAULT_TIMES = ["10:00"]
MAX_TIMES = 2
GRACE = timedelta(hours=3)          # a missed hour (server down) still releases within this long; later it is skipped
KEEP_FIRED = 10
MAX_LISTED = 60                     # tickets named in a task body; the count in the title is the whole number
AT = re.compile(r"^([01]\d|2[0-3]):([0-5]\d)$")
TITLE = "Release: "
MANAGER, WRITER, QA = "release-notes", "docs-writer", "issue-triage"     # starter templates (templates/catalog)
PENDING = "pending release"
QA_CHILD = re.compile(r"^QA\b", re.I)
EVENT = "release_published"


def zone():
    from .updates import ZONE
    return ZONE


# ----------------------------------------------------------------------------- the setting
def load(c):
    row = c.execute("SELECT value_json FROM registry_metadata WHERE key=?", (KEY,)).fetchone()
    try:
        stored = json.loads(row[0]) if row else {}
    except ValueError:
        stored = {}
    stored = stored if isinstance(stored, dict) else {}
    times = [t for t in stored.get("times") or [] if isinstance(t, str) and AT.match(t)][:MAX_TIMES]
    return {"on": stored["on"] if isinstance(stored.get("on"), bool) else True,
            "times": sorted(dict.fromkeys(times)) or list(DEFAULT_TIMES),
            "bot": str(stored.get("bot") or ""), "writer": str(stored.get("writer") or "")}


def save(c, actor, changes):
    """Set what `changes` names: `on`, `times` (one or two HH:MM in company time), `bot` (the Release Manager) and
    `writer` (the Technical Writer), the last two a bot slug or "" to go back to finding it by template."""
    before = load(c)
    after = dict(before)
    if changes.get("on") is not None:
        after["on"] = bool(changes["on"])
    if changes.get("times") is not None:
        times = [str(t).strip() for t in changes["times"]]
        if not 1 <= len(times) <= MAX_TIMES or any(not AT.match(t) for t in times):
            raise Problem("invalid", "Give one or two release times as HH:MM, from 00:00 to 23:59", 422)
        after["times"] = sorted(dict.fromkeys(times))
    for field in ("bot", "writer"):
        if changes.get(field) is not None:
            slug = H.actor_id(str(changes[field]).strip()) if str(changes[field]).strip() else ""
            if slug and not (H.bot(c, slug) or {}).get("state") == "active":
                raise Problem("invalid", f"No active bot {slug}", 422)
            after[field] = slug
    c.execute("INSERT INTO registry_metadata VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value_json=excluded.value_json",
              (KEY, json.dumps(after, sort_keys=True)))
    if after != before:
        H.event(c, actor, "release.schedule", "team", {"before": before, "after": after})
    return after


def _with_template(c, template):
    return [r[0] for r in c.execute(
        "SELECT b.slug FROM bots b JOIN bot_config bc ON bc.bot=b.slug WHERE b.state='active' "
        "AND json_extract(bc.config_json,'$.template')=? ORDER BY b.slug", (template,))]


def _named(c, slug, template):
    if slug:
        return slug if (H.bot(c, slug) or {}).get("state") == "active" else None
    found = _with_template(c, template)
    return found[0] if found else None


def release_manager(c, cfg=None):
    """The bot that cuts releases: the one the setting names, else the first active `release-notes` bot; None when neither."""
    return _named(c, (cfg or load(c))["bot"], MANAGER)


def technical_writer(c, cfg=None):
    return _named(c, (cfg or load(c))["writer"], WRITER)


def qa_owner(c, ticket):
    """Who runs a ticket's tests: the owner of its newest `QA:` subtask, else a bot on it in the `qa` role, else the
    team's one `issue-triage` bot. A bot slug or None."""
    from . import task_relations as TR
    kids = [H.task(c, i) for i in TR.child_ids(c, ticket["id"])]
    for kid in sorted((k for k in kids if k and QA_CHILD.match(k["title"] or "")), key=lambda k: k["created"], reverse=True):
        slug = H.actor_id(kid["owner"]) if H.is_bot(kid["owner"]) else None
        if slug and (H.bot(c, slug) or {}).get("state") == "active":
            return slug
    for (actor,) in c.execute("SELECT actor FROM task_roles WHERE task_id=? AND lower(role)='qa' ORDER BY created",
                              (ticket["id"],)):
        if H.is_bot(actor) and (H.bot(c, H.actor_id(actor)) or {}).get("state") == "active":
            return H.actor_id(actor)
    found = _with_template(c, QA)
    return found[0] if len(found) == 1 else None


# ----------------------------------------------------------------------------- what is waiting for a release
def pending(c, reader=None):
    """The Dev tickets at the Pending Release step, oldest first: dicts of the task row plus `prs` (its pull request
    links). A private ticket `reader` (an actor) may not read is left out."""
    from .roadmap_flow import ENGINEERING
    rows = [H.task(c, r[0]) for r in c.execute(
        "SELECT t.id FROM tasks t JOIN task_steps s ON s.id=t.step_id JOIN task_types y ON y.id=t.type_id "
        f"WHERE lower(s.name)=? AND (y.role=? OR y.name='Dev tickets') AND t.status IN "
        f"({','.join('?' * len(H.ACTIVE_STATUSES))}) ORDER BY t.created, t.id",
        (PENDING, ENGINEERING, *H.ACTIVE_STATUSES))]
    return [{**r, "prs": [l for l in H.task_links(c, r["id"]) if l["kind"] == "pr"]} for r in rows
            if r and (reader is None or H.task_private_readable(c, reader, r))]


def _name(t):
    return (f"#{t['number']} " if t.get("number") is not None else "") + str(t["title"]).strip()


def _line(t):
    pr = next((p["url"] for p in t["prs"]), "")
    return f"- {_name(t)} (owner {t['owner']}){' ' + pr if pr else ''}"


def _task_body(tickets, why):
    shown = tickets[:MAX_LISTED]
    more = f"\n...and {len(tickets) - len(shown)} more: `hub task list --step \"Pending Release\"`." if len(tickets) > len(shown) else ""
    return (f"{why}\n\nAt Pending Release now:\n" + "\n".join(_line(t) for t in shown) + more +
            "\n\nCut one release for them with your release playbook and docs/releasing.md. When it is published, "
            "Tico wakes each ticket's QA owner and the Technical Writer by itself.")


def _unfinished(c, owner):
    """The Release task `owner` has not finished, if any: a second is never filed beside it."""
    row = c.execute("SELECT id FROM tasks WHERE owner=? AND title LIKE ? ESCAPE '\\' AND status IN (" +
                    ",".join("?" * len(H.ACTIVE_STATUSES)) + ") ORDER BY created DESC LIMIT 1",
                    (owner, TITLE.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%",
                     *H.ACTIVE_STATUSES)).fetchone()
    return H.task(c, row[0]) if row else None


def request(c, actor, *, source, note=""):
    """Ask the Release Manager for a release of what is at Pending Release: ONE task, or a wake on its unfinished
    Release task. Returns `{sent, reason, task, tickets}`; `reason` says why nothing was sent (`no_release_manager`,
    `nothing_pending`) or that a wake went to the open task (`already_open`)."""
    manager = release_manager(c)
    if not manager:
        return {"sent": False, "reason": "no_release_manager", "task": None, "tickets": 0}
    owner = H.bot_actor(manager)
    tickets = pending(c, owner)
    if not tickets:
        return {"sent": False, "reason": "nothing_pending", "task": None, "tickets": 0}
    if actor == H.KEEPER:
        who = "The daily release time came."
    else:
        who = f"Asked by {H.actor_id(actor)}" + (f": {note}" if note else ".")
    title = f"{TITLE}{len(tickets)} ticket{'s' if len(tickets) != 1 else ''} at Pending Release"
    body = _task_body(tickets, who)
    open_task = _unfinished(c, owner)
    if open_task:
        if source == "release_schedule":
            return {"sent": False, "reason": "already_open", "task": open_task["id"], "tickets": len(tickets)}
        H._wake(c, open_task, owner, f"{title}\n{body}", refs={"wake": "release_now"}, trigger="schedule", source=source)
        H.event(c, actor, "release.requested", open_task["id"], {"source": source, "tickets": len(tickets), "woke": True})
        return {"sent": True, "reason": "already_open", "task": open_task["id"], "tickets": len(tickets)}
    task = H.task_create(c, actor, title, body, owner, deduplicate=False, trigger="schedule", trigger_source=source)
    H.event(c, actor, "release.requested", task["id"], {"source": source, "tickets": len(tickets)})
    return {"sent": True, "reason": None, "task": task["id"], "tickets": len(tickets)}


# ----------------------------------------------------------------------------- the daily hour
def _fired(c):
    row = c.execute("SELECT value_json FROM registry_metadata WHERE key=?", (FIRED,)).fetchone()
    try:
        found = json.loads(row[0]) if row else {}
    except ValueError:
        found = {}
    return found if isinstance(found, dict) else {}


def occurrences(cfg, at):
    """{key: local time} of each configured hour that came within GRACE before `at`."""
    local = at.astimezone(zone())
    out = {}
    for text in cfg["times"]:
        hour, minute = (int(x) for x in text.split(":"))
        point = local.replace(hour=hour, minute=minute, second=0, microsecond=0)
        if point > local:
            point = (datetime.combine(local.date() - timedelta(days=1), point.timetz().replace(tzinfo=None))
                     .replace(tzinfo=zone()))
        if local - point <= GRACE:
            out[point.strftime("%Y-%m-%dT%H:%M")] = point
    return out


def due(c, at):
    """The first hour that has come and not yet been handled, as its key, or None. Reads only."""
    cfg = load(c)
    if not cfg["on"]:
        return None
    fired = _fired(c)
    return next((k for k in sorted(occurrences(cfg, at)) if k not in fired), None)


def tick(c, at):
    """Handle a due hour once: mark it, then send the Release Manager its one task (or nothing). Caller owns the
    transaction. Returns the request's answer, or None when no hour was due."""
    key = due(c, at)
    if key is None:
        return None
    result = request(c, H.KEEPER, source="release_schedule")
    fired = _fired(c)
    fired[key] = {"at": H.now(), "sent": result["sent"], "reason": result["reason"], "task": result["task"],
                  "tickets": result["tickets"]}
    for old in sorted(fired)[:-KEEP_FIRED]:
        fired.pop(old)
    c.execute("INSERT INTO registry_metadata VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value_json=excluded.value_json",
              (FIRED, json.dumps(fired, sort_keys=True)))
    return result


def next_at(cfg, at):
    """The next release hour after `at` (a datetime in company time), or None while the schedule is off."""
    if not cfg["on"]:
        return None
    local = at.astimezone(zone())
    best = None
    for text in cfg["times"]:
        hour, minute = (int(x) for x in text.split(":"))
        point = local.replace(hour=hour, minute=minute, second=0, microsecond=0)
        if point <= local:
            point = datetime.combine(local.date() + timedelta(days=1), point.timetz().replace(tzinfo=None)).replace(tzinfo=zone())
        best = point if best is None or point < best else best
    return best


# ----------------------------------------------------------------------------- after a release
def carried(c, repo):
    """The Dev tickets a release in `repo` carries: at Pending Release with a pull request merged (or shipped) there."""
    repo = str(repo or "").lower()
    return [t for t in pending(c) if any(p.get("state") in ("merged", "shipped") and str(p.get("repo") or "").lower() == repo
                                         for p in t["prs"])]


def published(c, target, url="", release_repo=""):
    """A release was published (`target` is `owner/repo@vX.Y.Z`): each ticket it carries wakes its QA owner and the
    Technical Writer once, and every routine on `release_published` gets its task. Called once per release, from
    the first time the milestone is recorded. A prerelease (a tag with a suffix) and a repository other than
    the server's release repository do nothing. Returns the carried ticket ids."""
    repo, _, tag = target.partition("@")
    if "-" in tag or release_repo and repo.lower() != str(release_repo).lower():
        return []
    cfg = load(c)
    writer, tickets = technical_writer(c, cfg), carried(c, repo)
    sent = {}
    for ticket in tickets:
        facts = f"{_name(ticket)} is in {tag}" + (f" ({url})" if url else "")
        qa = qa_owner(c, ticket) if "qa" in H.task_labels(ticket) else None
        for who, body, role in (
                (qa, f"Released: {facts}. Run its check live tests now and watch the watch live items; "
                     "report to the ticket.", "qa"),
                (writer, f"Released: {facts}. Update the docs for this change and write its release notes now "
                         "that it is out.", "docs")):
            if who and H._wake(c, ticket, H.bot_actor(who), body, trigger=EVENT,
                               refs={"wake": EVENT, "release": tag, "role": role}, source=target):
                sent.setdefault(ticket["id"], []).append(who)
    from . import routines
    listing = "\n".join(_line(t) for t in tickets[:MAX_LISTED])
    routines.emit(c, EVENT, target, {"release": tag, "url": url, "tickets": len(tickets)},
                  title=tag, content=listing)
    H.event(c, H.KEEPER, "release.published", target, {"tickets": [t["id"] for t in tickets], "woke": sent})
    return [t["id"] for t in tickets]


# ----------------------------------------------------------------------------- the API
def may_release(c, who):
    """Whoever moves Dev tickets: the owner, a person on a mover team, or a bot of a type whose bots may `work` it."""
    if who.role == "owner" or who.role == "human" and H.can_move(c, who.actor):
        return True
    return who.role == "bot" and bool(c.execute(
        "SELECT 1 FROM task_types WHERE bots='work' AND (role='engineering' OR name='Dev tickets') LIMIT 1").fetchone())


def view(c, who, auth, now=None):
    now = now or datetime.now(zone())
    cfg = load(c)
    fired = _fired(c)
    last = fired[max(fired)] if fired else None
    nxt = next_at(cfg, now)
    return {**cfg, "zone": str(zone()), "release_manager": release_manager(c, cfg), "technical_writer": technical_writer(c, cfg),
            "next": nxt.isoformat() if nxt else None, "last": last, "pending": len(pending(c)),
            "can_change": bool(auth.bot_admin(who)), "can_release": may_release(c, who)}


def install(app, store, auth, mutate):
    from fastapi import Request

    from . import models as M

    @app.get("/api/v2/release-schedule")
    def release_schedule(request: Request):
        """The team's release schedule: `on`, `times` (company time, `zone`), the Release Manager and Technical Writer
        found (`release_manager`, `technical_writer`; `bot` and `writer` are the team's choice, "" to find them by
        template), `next` hour, the `last` hour's result, how many tickets are `pending` now, and what this viewer
        may do (`can_change`, `can_release`). Everyone who can open Settings reads it."""
        who = request.state.identity
        auth.domain(who)
        with store.read() as c:
            return view(c, who, auth)

    @app.patch("/api/v2/release-schedule")
    def release_schedule_save(request: Request, body: M.ReleaseScheduleUpdate):
        """Turn the daily release on or off, set its one or two times, or name the Release Manager and Technical Writer.
        An owner or an admin; only what is sent changes."""
        who = request.state.identity
        auth.domain(who)
        if not auth.bot_admin(who):
            raise Problem("forbidden", "Only an owner or an admin changes the release schedule", 403)
        mutate(request, body, lambda c: save(c, who.actor, body.model_dump(exclude_none=True)))
        with store.read() as c:
            return view(c, who, auth)

    @app.post("/api/v2/release/now")
    def release_now(request: Request, body: M.ReleaseNow):
        """Ask the Release Manager to cut a release of what is at Pending Release now, without waiting for the daily
        hour (a hotfix, a midday release). ONE task, or a wake on its unfinished Release task. A person who moves Dev
        tickets, or a bot that may work them. `sent` is false, with a `reason`, when nobody was asked."""
        who = request.state.identity
        auth.domain(who)
        with store.read() as c:
            if not may_release(c, who):
                raise Problem("forbidden", "Only someone who moves Dev tickets asks for a release", 403)
        return mutate(request, body, lambda c: request_now(c, who.actor, body.note or ""))


def request_now(c, actor, note):
    result = request(c, actor, source="release_now", note=note)
    if not result["sent"] and result["reason"] == "no_release_manager":
        raise Problem("not_found", "No Release Manager: name one in the release schedule, or add the Release Manager "
                                   "starter bot", 404)
    return result
