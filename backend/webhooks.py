"""Outgoing webhooks: Tico tells an address a person chose when something happens.

An endpoint belongs to a person (`created_by`), who sees through it what they could see in Tico: `publish` builds one
message per distinct owner, and a task they cannot read produces nothing for them. A bot cannot make an endpoint. It
asks, a person approves, and the person owns what is made (`requested_by` names the bot). The CEO Bot sends nothing.

`publish` runs in the caller's write transaction and only inserts: one `webhook_events` row for the event and one
`webhook_sends` row for each endpoint that should hear of it, so a rolled-back change tells nobody. The workers in
backend/webhook_delivery.py post them after the commit. A producer calls it with one line and it never raises on that
path: a failure is rolled back to a savepoint, logged, and the producer's own write goes on.
"""
import base64
import hashlib
import json
import logging
import re
import secrets
import uuid
from urllib.parse import urlsplit

from fastapi import Request
from pydantic import Field

from . import egress
from . import hubdb as H
from . import models as M
from . import webhook_delivery as D
from .models import Contract
from .store import Problem
from .webhooks_schema import SCHEMA  # noqa: F401  (hubdb.MIGRATIONS applies it)

log = logging.getLogger(__name__)

MAX_PER_EVENT = 20              # endpoints one event reaches; the rest are skipped and Health says so
MAX_PER_PERSON = 50
MAX_DATA = 64 * 1024
LISTED = 100
MAX_LIST_BYTES = 256 * 1024
LOG_LISTED = 100
GRACE = D.GRACE_HOURS
CUSTOM = re.compile(r"custom\.[a-z0-9][a-z0-9_.-]{0,62}")
PATTERN = re.compile(r"\*|[a-z][a-z0-9_]*(\.[a-z0-9_]+)*\.\*|[a-z][a-z0-9_]*(\.[a-z0-9_]+)+")
FALLBACK_EXAMPLE = {"example": True, "message": "A test event from Tico for Acme"}
EXAMPLES_AT = "acme.example"

_state = {"auth": None, "base": ""}


class Refused(Exception):
    """An event that cannot be sent. `reason` is plain words for whoever asked."""

    def __init__(self, reason):
        super().__init__(reason)
        self.reason = reason


def use(auth, base=""):
    """The sign-in rules and the address app links start with, once the app is built."""
    _state["auth"], _state["base"] = auth, (base or "").rstrip("/")


# ------------------------------------------------------------------------------------------------- names and shapes
def _catalog():
    try:
        from . import event_catalog
        return event_catalog
    except ImportError:             # the catalog is built beside this module; any dotted lowercase name does until it lands
        return None


def canonical(name):
    """The catalog's name for `name`, or None when it is not an event."""
    name = str(name or "").strip()
    catalog = _catalog()
    if catalog:
        return catalog.canonical(name)
    return name if CUSTOM.fullmatch(name) or PATTERN.fullmatch(name) and "*" not in name else None


def matches(pattern, name):
    return pattern == "*" or pattern == name or (pattern.endswith("*") and name.startswith(pattern[:-1]))


def subscribed(events, name):
    return any(matches(p, name) for p in events)


def clean_events(events):
    """A subscription list: catalog names, `group.*` patterns or `*`, each once, aliases in their catalog spelling."""
    out = []
    catalog = _catalog()
    for item in events or []:
        item = str(item).strip()
        if not item or not PATTERN.fullmatch(item) and not CUSTOM.fullmatch(item):
            raise Problem("webhook", f"{item or 'An empty name'} is not an event name", 422)
        if "*" not in item:
            name = canonical(item)
            if not name:
                raise Problem("webhook", f"{item} is not an event Tico sends", 422)
            item = name
        elif item != "*" and catalog and not any(matches(item, n) for n in catalog.EVENTS) and not item.startswith("custom."):
            raise Problem("webhook", f"{item} matches no event Tico sends", 422)
        if item not in out:
            out.append(item)
    if not out:
        raise Problem("webhook", "Choose at least one event", 422)
    return out


def example_for(name):
    catalog = _catalog()
    event = catalog.EVENTS.get(canonical(name) or "") if catalog else None
    return dict(event.example) if event and event.example else dict(FALLBACK_EXAMPLE)


def version_of(name):
    catalog = _catalog()
    event = catalog.EVENTS.get(name) if catalog else None
    return event.version if event else 1


def links_for(type_, subject, data):
    """Where to look at the thing, in the app and over the API. Only what is known is given."""
    base, group = _state["base"], type_.split(".")[0]
    app = api = ""
    if group == "task":
        app, api = f"#/task/{subject}", f"/api/v2/tasks/{subject}"
    elif group == "approval" and data.get("task_id"):
        app, api = f"#/task/{data['task_id']}", f"/api/v2/tasks/{data['task_id']}"
    elif group == "bot":
        app, api = f"#/bot/{subject}", f"/api/v2/bots/{subject}"
    elif group in ("meeting", "strategy", "market", "health"):
        app = {"meeting": "#/meetings", "strategy": "#/strategy", "market": "#/market", "health": "#/health"}[group]
    out = {}
    if app:
        out["app"] = f"{base}/{app}" if base else app
    if api:
        out["api"] = f"{base}{api}"
    return out


def envelope(type_, subject, data, timestamp):
    return {"type": type_, "version": version_of(type_), "timestamp": timestamp, "data": data,
            "links": links_for(type_, subject, data)}


def body_of(env):
    return json.dumps(env, separators=(",", ":"), ensure_ascii=False)


# ----------------------------------------------------------------------------------------------------- who may read
def _identity(c, actor, cache):
    if actor not in cache:
        try:
            cache[actor] = _state["auth"].identity_for_actor(c, actor)
        except (Problem, AttributeError):
            cache[actor] = None
    return cache[actor]


def _admin(c, actor, cache):
    who = _identity(c, actor, cache)
    return bool(who and (who.role == "owner" or _state["auth"].bot_admin(who)))


def _task_readable(c, actor, task_id, cache):
    row = H.task(c, task_id) if task_id else None
    if not row:
        return False
    auth = _state["auth"]
    who = _identity(c, actor, cache) if auth else None
    if auth and who:
        try:
            auth.task_row(c, who, row)
            return True
        except Problem:
            return False
    return H.task_private_readable(c, actor, row)


def view_for(c, actor, type_, subject, data, cache):
    """`data` as this person may have it, or None when none of it is theirs. The event's own rules, one per group:
    a task by the task's privacy, an approval by who decides it, a Needs-you item by who it is for, a bot by who may
    read it; Health and inbound mail are for owners and admins; the rest is company-wide."""
    group = type_.split(".")[0]
    if group == "task":
        return data if _task_readable(c, actor, subject, cache) else None
    # Whatever the event is called, a subject that is a task is that task's to give: a rule or a person may send a
    # custom event about one.
    if H.task(c, subject) and not _task_readable(c, actor, subject, cache):
        return None
    if group == "approval":
        row = c.execute("SELECT decision_owner, task_id FROM approvals WHERE id=?", (subject,)).fetchone()
        if not row or not (actor == row["decision_owner"] or _admin(c, actor, cache)):
            return None
        return data if not row["task_id"] or _task_readable(c, actor, row["task_id"], cache) else None
    if group == "needs_you":
        return data if data.get("to") == actor else None
    if group == "bot":
        auth, who = _state["auth"], _identity(c, actor, cache)
        if auth and who:
            return data if auth.bot_access(c, who, subject)["read"] else None
        return data
    if group in ("health", "inbound", "webhook"):
        return data if _admin(c, actor, cache) or not _state["auth"] else None
    return data


# ------------------------------------------------------------------------------------------------------------ publish
def listening(c):
    """Whether any endpoint is on: the one cheap query a producer pays when nobody is."""
    return c.execute("SELECT 1 FROM webhooks WHERE enabled=1 AND deleted_at IS NULL LIMIT 1").fetchone() is not None


def _is_ceo(actor):
    from . import ceo_bot
    return actor == H.bot_actor(ceo_bot.SLUG)


def _refresh(c):
    if hasattr(c, "after_commit"):
        c.after_commit.append(D.ring)
    else:
        D.ring()


def _event_row(c, event_id, type_, subject, data, actor, skipped=0):
    payload = json.dumps(data, separators=(",", ":"), default=str)
    if len(payload) > MAX_DATA:
        payload = json.dumps({"truncated": True, "bytes": len(payload)})
    c.execute("INSERT OR IGNORE INTO webhook_events(id,type,subject,version,payload,actor,skipped,created) "
              "VALUES(?,?,?,?,?,?,?,?)", (event_id, type_, str(subject), version_of(type_), payload, actor, skipped, H.now()))


def _queue(c, hook, event_id, type_, subject, data):
    """One send for one endpoint; 0 when that endpoint already has this event."""
    stamp = H.now()
    if len(json.dumps(data, default=str)) > MAX_DATA:
        data = {"truncated": True}
    body = body_of(envelope(type_, str(subject), data, stamp))
    return c.execute("INSERT OR IGNORE INTO webhook_sends(id,event_id,webhook_id,type,subject,body,state,attempts,"
                     "next_attempt,created) VALUES(?,?,?,?,?,?,'ready',0,?,?)",
                     ("wh_" + uuid.uuid4().hex[:24], event_id, hook["id"], type_, str(subject), body, stamp, stamp)).rowcount


def _event_id(type_, subject, revision):
    return f"{type_}:{subject}:{revision}" if revision is not None else "we_" + uuid.uuid4().hex[:20]


def publish(c, type, subject, data, actor, *, only=None, revision=None):
    """Queue `type` about `subject` for the endpoints that should hear of it; the number of sends queued.

    Inside the caller's write transaction, inserts only. Without `only` it never raises: every enabled endpoint
    subscribed to `type` gets a message built through its owner's read view, at most MAX_PER_EVENT of them. With
    `only` (an endpoint id) it sends to that one and raises Refused when it cannot: the endpoint is missing, paused
    or deleted, the sender is the CEO Bot or a bot whose send switch is off, or the endpoint's owner may not read
    the subject. `revision` makes the event id repeatable, so a retried write queues nothing twice."""
    if only is not None:
        return _publish_only(c, str(type), str(subject), data or {}, actor, only, revision)
    try:
        name = canonical(type)
        # One indexed query when nobody listens, which is nearly always.
        hooks = [h for h in c.execute("SELECT * FROM webhooks WHERE enabled=1 AND deleted_at IS NULL ORDER BY created, id")]
        if not name or not hooks or _is_ceo(actor):
            return 0
        hooks = [h for h in hooks if subscribed(json.loads(h["events_json"]), name)]
        if not hooks:
            return 0
        c.execute("SAVEPOINT webhook_publish")
        try:
            queued = _fan_out(c, hooks, name, str(subject), data or {}, actor, revision)
            c.execute("RELEASE webhook_publish")
        except Exception:
            c.execute("ROLLBACK TO webhook_publish")
            c.execute("RELEASE webhook_publish")
            raise
        if queued:
            _refresh(c)
        return queued
    except Exception:
        log.warning("publish of %s failed; the change goes on without it", type, exc_info=True)
        return 0


def _fan_out(c, hooks, name, subject, data, actor, revision):
    event_id = _event_id(name, subject, revision)
    kept, skipped = hooks[:MAX_PER_EVENT], max(0, len(hooks) - MAX_PER_EVENT)
    _event_row(c, event_id, name, subject, data, actor, skipped)
    cache, views, queued = {}, {}, 0
    for hook in kept:
        owner = hook["created_by"]
        if owner not in views:
            views[owner] = view_for(c, owner, name, subject, data, cache)
        if views[owner] is not None:
            queued += _queue(c, hook, event_id, name, subject, views[owner])
    return queued


def _publish_only(c, type_, subject, data, actor, only, revision):
    hook = c.execute("SELECT * FROM webhooks WHERE id=?", (only,)).fetchone()
    if not hook or hook["deleted_at"]:
        raise Refused("That endpoint does not exist")
    if not hook["enabled"]:
        raise Refused("That endpoint is paused")
    if _is_ceo(actor):
        raise Refused("The CEO Bot does not send webhooks")
    if H.is_bot(actor):
        from . import mail_settings
        if not (mail_settings.stored(c, H.actor_id(actor)) or {}).get("outbound_send"):
            raise Refused("This bot may not send outside: its send switch is off")
    name = canonical(type_)
    if not name:
        raise Refused(f"{type_} is not an event Tico sends")
    _actor_may_use(c, actor, hook, name)
    if len(json.dumps(data, default=str)) > MAX_DATA:
        raise Refused("The data is over 64 KB")
    if view_for(c, hook["created_by"], name, subject, data, {}) is None:
        raise Refused("The person who owns that endpoint may not read this")
    event_id = _event_id(name, subject, revision)
    _event_row(c, event_id, name, subject, data, actor)
    queued = _queue(c, hook, event_id, name, subject, data)
    if queued:
        _refresh(c)
    return queued


def _actor_may_use(c, actor, hook, name):
    """The same test as may_send, keyed by actor string: a caller that reaches publish without the API (a rule, a
    producer) still cannot aim at someone else's endpoint. Bots were checked for their send switch by the caller."""
    if actor == H.KEEPER:
        return
    if H.is_bot(actor):
        if not subscribed(json.loads(hook["events_json"]), name):
            raise Refused("That endpoint does not listen for this event")
        return
    if not _state.get("auth"):
        return
    if hook["created_by"] != actor and not _admin(c, actor, {}):
        raise Refused("Only the person who made this endpoint, or an admin, may send to it")


# ------------------------------------------------------------------------------------------------------ endpoint rights
def is_person(who):
    return who.role in ("owner", "human")


def is_admin(who):
    auth = _state["auth"]
    return who.role == "owner" or bool(auth and is_person(who) and auth.bot_admin(who))


def may_manage(who, hook=None):
    """People make endpoints and manage their own; owners and admins manage all. A bot manages none."""
    if not is_person(who):
        raise Problem("forbidden", "A person manages webhook endpoints; a bot asks and a person approves", 403)
    if hook is not None and hook["created_by"] != who.actor and not is_admin(who):
        raise Problem("forbidden", "Only the person who made this endpoint, or an admin, may change it", 403)


def may_send(c, who, hook, name):
    """Who may send a custom event to an endpoint: a person who manages it; a bot only with its send switch on, and
    only to an endpoint that listens for that name; never the CEO Bot."""
    if is_person(who):
        may_manage(who, hook)
        return
    if who.role != "bot" or _is_ceo(who.actor):
        raise Problem("forbidden", "Only people and bots with sending switched on send webhooks", 403)
    from . import mail_settings
    if not (mail_settings.stored(c, H.actor_id(who.actor)) or {}).get("outbound_send"):
        raise Problem("forbidden", "Sending is off for this bot; a person turns it on in its mail settings", 403)
    if not subscribed(json.loads(hook["events_json"]), name):
        raise Problem("forbidden", "That endpoint does not listen for this event", 403)


def _row(c, hook_id):
    row = c.execute("SELECT * FROM webhooks WHERE id=? AND deleted_at IS NULL", (hook_id,)).fetchone()
    if not row:
        raise Problem("not_found", "Webhook endpoint not found", 404)
    return row


def _reach(c, who, hook_id):
    """The endpoint when this caller may see it: its owner, an admin, or a bot (which sees it without its address)."""
    row = _row(c, hook_id)
    if row["created_by"] != who.actor and not is_admin(who) and who.role != "bot":
        raise Problem("not_found", "Webhook endpoint not found", 404)
    return row


# --------------------------------------------------------------------------------------------------------- the shapes
def _origin(url):
    parts = urlsplit(url)
    return f"{parts.scheme}://{parts.netloc}/…"


def counts(c, ids):
    """Per endpoint over seven days: delivered, failed, and the sends still to go."""
    if not ids:
        return {}
    since = H.shift(H.now(), days=-7)
    marks = ",".join("?" * len(ids))
    out = {i: {"delivered": 0, "failed": 0, "pending": 0} for i in ids}
    for row in c.execute(f"SELECT webhook_id, state, count(*) n FROM webhook_sends WHERE webhook_id IN ({marks}) AND "
                         f"(state IN ('ready','sending') OR next_attempt>=?) GROUP BY webhook_id, state", (*ids, since)):
        key = {"delivered": "delivered", "failed": "failed", "ready": "pending", "sending": "pending"}.get(row["state"])
        if key:
            out[row["webhook_id"]][key] += row["n"]
    return out


def view(hook, who, tally=None):
    mine = is_person(who) and (hook["created_by"] == who.actor or is_admin(who))
    grace = hook["secret_prev_until"] if hook["secret_prev"] and (hook["secret_prev_until"] or "") > H.now() else None
    return {"id": hook["id"], "name": hook["name"], "url": hook["url"] if mine else _origin(hook["url"]),
            "host": hook["host"], "events": json.loads(hook["events_json"]), "enabled": bool(hook["enabled"]),
            "paused_reason": hook["paused_reason"], "rate_per_hour": hook["rate_per_hour"],
            "allow_http": bool(hook["allow_http"]), "created_by": hook["created_by"],
            "requested_by": hook["requested_by"] or None, "created": hook["created"], "updated": hook["updated"],
            "revision": hook["revision"], "old_secret_until": grace, "can_change": mine,
            "last_7_days": tally or {"delivered": 0, "failed": 0, "pending": 0}}


def send_view(row):
    return {"id": row["id"], "webhook_id": row["webhook_id"], "event_id": row["event_id"], "type": row["type"],
            "subject": row["subject"], "state": row["state"], "attempts": row["attempts"],
            "last_status": row["last_status"], "last_error": row["last_error"],
            "next_attempt": row["next_attempt"] if row["state"] == "ready" else None, "created": row["created"],
            "delivered_at": row["delivered_at"]}


def listing(c, who, limit=LISTED, offset=0):
    """Endpoints the caller may see, newest last, paged and byte-capped. `more` says another page waits."""
    limit = max(1, min(int(limit or LISTED), LISTED))
    sql, args = "SELECT * FROM webhooks WHERE deleted_at IS NULL", []
    if who.role != "bot" and not is_admin(who):
        sql, args = sql + " AND created_by=?", [who.actor]
    rows = c.execute(sql + " ORDER BY created, id LIMIT ? OFFSET ?", (*args, limit + 1, offset)).fetchall()
    more = len(rows) > limit
    rows = rows[:limit]
    tally = counts(c, [r["id"] for r in rows])
    items, spent = [], 0
    for n, row in enumerate(rows):
        item = view(row, who, tally.get(row["id"]))
        spent += len(json.dumps(item))
        if items and spent > MAX_LIST_BYTES:
            more, rows = True, rows[:n]
            break
        items.append(item)
    out = {"items": items, "more": more}
    if more:
        out["next_offset"] = offset + len(items)
    return out


# ------------------------------------------------------------------------------------------------------ the operations
class WebhookCreate(Contract):
    name: str = Field(min_length=1, max_length=100)
    url: str = Field(min_length=1, max_length=2000)
    events: list[str] = Field(default_factory=lambda: ["*"], max_length=60)
    rate_per_hour: int = Field(default=600, ge=1, le=100000)
    allow_http: bool = False


class WebhookUpdate(Contract):
    name: str | None = Field(default=None, min_length=1, max_length=100)
    url: str | None = Field(default=None, min_length=1, max_length=2000)
    events: list[str] | None = Field(default=None, max_length=60)
    rate_per_hour: int | None = Field(default=None, ge=1, le=100000)
    allow_http: bool | None = None
    expected_revision: int | None = None


class WebhookSend(Contract):
    type: str = Field(min_length=1, max_length=64)
    data: dict = Field(default_factory=dict)
    subject: str = Field(default="", max_length=200)


class WebhookExample(Contract):
    type: str = Field(default="", max_length=64)


class Pause(Contract):
    reason: str = Field(default="", max_length=200)


def new_secret():
    return D.PREFIX + base64.b64encode(secrets.token_bytes(32)).decode()


def check_address(url, allow_http):
    """The host of `url` when an endpoint may hold it. Plain http is for a receiver on this computer while it is
    built, and only with the endpoint's switch on."""
    try:
        parts = egress.check(url, allow_http=True)
    except egress.Blocked as exc:
        raise Problem("webhook", exc.reason, 422) from exc
    if parts.scheme == "http":
        if parts.hostname not in ("localhost", "127.0.0.1", "::1"):
            raise Problem("webhook", "Plain http is allowed only to this computer (localhost)", 422)
        if not allow_http:
            raise Problem("webhook", "Plain http needs the owner's \"Allow plain http to this computer\" switch", 422)
    return parts.hostname.lower()


def owner_only_http(who, allow_http):
    if allow_http and who.role != "owner":
        raise Problem("forbidden", "Only the owner turns on plain http to this computer", 403)


def _spec(body):
    return {"name": body.name, "url": body.url, "events": clean_events(body.events), "rate_per_hour": body.rate_per_hour,
            "allow_http": body.allow_http}


def _insert(c, vault, who, spec, owner, requested_by=""):
    host = check_address(spec["url"], spec["allow_http"])
    if c.execute("SELECT count(*) FROM webhooks WHERE created_by=? AND deleted_at IS NULL", (owner,)).fetchone()[0] >= MAX_PER_PERSON:
        raise Problem("webhook", f"One person has at most {MAX_PER_PERSON} webhook endpoints", 409)
    hook_id, secret, now = "ep_" + uuid.uuid4().hex[:12], new_secret(), H.now()
    c.execute("INSERT INTO webhooks(id,name,url,host,enabled,events_json,secret,rate_per_hour,allow_http,created_by,"
              "requested_by,created,updated) VALUES(?,?,?,?,1,?,?,?,?,?,?,?,?)",
              (hook_id, spec["name"], spec["url"], host, json.dumps(spec["events"]),
               vault.cipher.seal(c, D.sealed_as(hook_id), secret), spec["rate_per_hour"], int(spec["allow_http"]),
               owner, requested_by, now, now))
    H.event(c, who.actor, "webhook.created", hook_id, {"name": spec["name"], "host": host, "for": owner})
    return {**view(c.execute("SELECT * FROM webhooks WHERE id=?", (hook_id,)).fetchone(), who), "secret": secret}


def _approval_payload(spec):
    digest = hashlib.sha256(json.dumps(spec, sort_keys=True).encode()).hexdigest()
    return {"to": spec["url"], "cc": "", "subject": f"Create webhook endpoint {spec['name']}", "body_sha256": digest,
            "mailbox": "webhooks", "webhook": spec}


def create(c, vault, who, body):
    """A person's endpoint, with its secret in the answer (shown once). A bot's request files a `send` approval
    instead and the answer says so. Asking again with the same details after a person approved it makes the endpoint,
    owned by that person, and spends the approval."""
    spec = _spec(body)
    if is_person(who):
        owner_only_http(who, spec["allow_http"])
        return _insert(c, vault, who, spec, who.actor)
    if who.role != "bot" or _is_ceo(who.actor):
        raise Problem("forbidden", "Only people and bots ask for webhook endpoints", 403)
    payload = _approval_payload(spec)
    digest = H.payload_hash(payload)
    approved = c.execute("SELECT * FROM approvals WHERE payload_hash=? AND requested_by=? AND kind='send' AND "
                         "decision='approved' AND consumed_at IS NULL ORDER BY decided_at LIMIT 1",
                         (digest, who.actor)).fetchone()
    if approved:
        H.approval_consume(c, who.actor, approved["id"])
        return _insert(c, vault, who, spec, approved["decided_by"], requested_by=who.actor)
    open_ = c.execute("SELECT id FROM approvals WHERE payload_hash=? AND decision IS NULL", (digest,)).fetchone()
    owner_only_http(who, spec["allow_http"])
    check_address(spec["url"], False)
    try:
        aid = open_["id"] if open_ else H.approval_request(c, who.actor, "send", payload)["id"]
    except H.Refused as exc:
        raise Problem("approval", str(exc), 422) from exc
    return {"approval": {"id": aid, "status": "pending"}, "webhook": None}


def update(c, who, hook_id, body):
    hook = _row(c, hook_id)
    may_manage(who, hook)
    if body.expected_revision is not None and body.expected_revision != hook["revision"]:
        raise Problem("version_conflict", "This endpoint changed; refresh before saving", 409)
    name = body.name if body.name is not None else hook["name"]
    url = body.url if body.url is not None else hook["url"]
    allow = bool(hook["allow_http"] if body.allow_http is None else body.allow_http)
    if allow != bool(hook["allow_http"]):
        if who.role != "owner":
            raise Problem("forbidden", "Only the owner turns plain http to this computer on or off", 403)
    events = clean_events(body.events) if body.events is not None else json.loads(hook["events_json"])
    host = check_address(url, allow)
    c.execute("UPDATE webhooks SET name=?, url=?, host=?, events_json=?, rate_per_hour=?, allow_http=?, "
              "revision=revision+1, updated=? WHERE id=?",
              (name, url, host, json.dumps(events), body.rate_per_hour or hook["rate_per_hour"], int(allow),
               H.now(), hook_id))
    H.event(c, who.actor, "webhook.updated", hook_id, {"name": name})
    return view(_row(c, hook_id), who, counts(c, [hook_id]).get(hook_id))


def rotate(c, vault, who, hook_id):
    """A new secret; the old one keeps signing beside it for a day, so the receiver can switch without a gap."""
    hook = _row(c, hook_id)
    may_manage(who, hook)
    old = vault.cipher.unseal(c, D.sealed_as(hook_id), hook["secret"])
    secret = new_secret()
    c.execute("UPDATE webhooks SET secret=?, secret_prev=?, secret_prev_until=?, revision=revision+1, updated=? WHERE id=?",
              (vault.cipher.seal(c, D.sealed_as(hook_id), secret), vault.cipher.seal(c, D.sealed_as(hook_id, True), old),
               H.shift(H.now(), hours=GRACE), H.now(), hook_id))
    H.event(c, who.actor, "webhook.rotated", hook_id, {})
    return {**view(_row(c, hook_id), who, counts(c, [hook_id]).get(hook_id)), "secret": secret}


def pause(c, who, hook_id, reason=""):
    hook = _row(c, hook_id)
    may_manage(who, hook)
    c.execute("UPDATE webhooks SET enabled=0, paused_reason=?, revision=revision+1, updated=? WHERE id=?",
              (reason or f"Paused by {who.actor}", H.now(), hook_id))
    H.event(c, who.actor, "webhook.paused", hook_id, {})
    return view(_row(c, hook_id), who, counts(c, [hook_id]).get(hook_id))


def resume(c, who, hook_id):
    hook = _row(c, hook_id)
    may_manage(who, hook)
    c.execute("UPDATE webhooks SET enabled=1, paused_reason='', revision=revision+1, updated=? WHERE id=?", (H.now(), hook_id))
    H.event(c, who.actor, "webhook.resumed", hook_id, {})
    _refresh(c)
    return view(_row(c, hook_id), who, counts(c, [hook_id]).get(hook_id))


def delete(c, who, hook_id):
    """Gone for good: its pending sends are cancelled and its secrets cleared. Finished sends stay in the log until
    the cleanup removes them."""
    hook = _row(c, hook_id)
    may_manage(who, hook)
    cancelled = c.execute("UPDATE webhook_sends SET state='cancelled', last_error='The endpoint was deleted', "
                          "next_attempt=?, claimed_at=NULL WHERE webhook_id=? AND state IN ('ready','sending')",
                          (H.now(), hook_id)).rowcount
    c.execute("UPDATE webhooks SET deleted_at=?, enabled=0, secret='', secret_prev='', updated=? WHERE id=?",
              (H.now(), H.now(), hook_id))
    H.event(c, who.actor, "webhook.deleted", hook_id, {"cancelled": cancelled})
    return {"id": hook_id, "deleted": True, "cancelled": cancelled}


def send_custom(c, who, hook_id, body):
    """A custom event to one endpoint, by a person or by a bot with sending on."""
    hook = _row(c, hook_id)
    name = body.type.strip()
    if not CUSTOM.fullmatch(name):
        raise Problem("webhook", "A custom event is named custom.<something> in lowercase", 422)
    may_send(c, who, hook, name)
    try:
        queued = publish(c, name, body.subject or name, body.data, who.actor, only=hook_id)
    except Refused as exc:
        raise Problem("webhook", exc.reason, 409) from exc
    return {"queued": queued, "type": name}


def send_example(c, who, hook_id, body):
    """The catalog's example for an event, or a plain test message, sent now to one endpoint."""
    hook = _row(c, hook_id)
    may_manage(who, hook)
    name = canonical(body.type) if body.type else "custom.example"
    if not name:
        raise Problem("webhook", f"{body.type} is not an event Tico sends", 422)
    if not hook["enabled"]:
        raise Problem("webhook", "That endpoint is paused", 409)
    queued = _queue(c, hook, "we_" + uuid.uuid4().hex[:20], name, "example", example_for(name))
    _refresh(c)
    return {"queued": queued, "type": name}


def sends(c, who, hook_id, state=None, limit=LOG_LISTED, offset=0):
    _reach(c, who, hook_id)
    if who.role == "bot":
        raise Problem("forbidden", "A person reads an endpoint's send log", 403)
    limit = max(1, min(int(limit or LOG_LISTED), LOG_LISTED))
    sql, args = "SELECT * FROM webhook_sends WHERE webhook_id=?", [hook_id]
    if state:
        sql, args = sql + " AND state=?", [*args, state]
    rows = c.execute(sql + " ORDER BY created DESC, id LIMIT ? OFFSET ?", (*args, limit + 1, offset)).fetchall()
    more = len(rows) > limit
    out = {"items": [send_view(r) for r in rows[:limit]], "more": more}
    if more:
        out["next_offset"] = offset + limit
    return out


def one_send(c, who, hook_id, send_id):
    _reach(c, who, hook_id)
    if who.role == "bot":
        raise Problem("forbidden", "A person reads an endpoint's send log", 403)
    row = c.execute("SELECT * FROM webhook_sends WHERE id=? AND webhook_id=?", (send_id, hook_id)).fetchone()
    if not row:
        raise Problem("not_found", "Send not found", 404)
    attempts = c.execute("SELECT n,at,timestamp_sent,status,ms,response_head,error FROM webhook_attempts WHERE send_id=? "
                         "ORDER BY n DESC LIMIT 50", (send_id,)).fetchall()
    return {**send_view(row), "attempt_log": [dict(a) for a in attempts]}


def retry(c, who, hook_id, send_id):
    """Try a finished send again now. Its id and body stay, so a receiver that kept the first still drops the repeat."""
    hook = _row(c, hook_id)
    may_manage(who, hook)
    row = c.execute("SELECT * FROM webhook_sends WHERE id=? AND webhook_id=?", (send_id, hook_id)).fetchone()
    if not row:
        raise Problem("not_found", "Send not found", 404)
    if row["state"] in ("ready", "sending"):
        raise Problem("webhook", "That send is still being tried", 409)
    if row["state"] == "withheld":
        raise Problem("webhook", "A rehearsal copy sends nothing", 409)
    c.execute("UPDATE webhook_sends SET state='ready', attempts=0, next_attempt=?, claimed_at=NULL, last_error='' WHERE id=?",
              (H.now(), send_id))
    H.event(c, who.actor, "webhook.retried", send_id, {"webhook": hook_id})
    _refresh(c)
    return send_view(c.execute("SELECT * FROM webhook_sends WHERE id=?", (send_id,)).fetchone())


# ------------------------------------------------------------------------------------------------------------- Health
def health_summary(c):
    """What Health shows for outgoing webhooks, from the rows: sends that gave up in the last day, endpoints failing
    more than half their attempts, and events that skipped endpoints past the per-event cap."""
    day = H.shift(H.now(), hours=-24)
    names = {r["id"]: r["name"] for r in c.execute("SELECT id,name FROM webhooks WHERE deleted_at IS NULL")}
    if not names:
        return {"failed": [], "flaky": [], "skipped": 0}
    failed = [names[r["webhook_id"]] for r in c.execute(
        "SELECT DISTINCT webhook_id FROM webhook_sends WHERE state='failed' AND next_attempt>=?", (day,)) if r["webhook_id"] in names]
    flaky = []
    for r in c.execute("SELECT webhook_id, count(*) n, sum(CASE WHEN status BETWEEN 200 AND 299 THEN 0 ELSE 1 END) bad "
                       "FROM webhook_attempts WHERE at>=? GROUP BY webhook_id", (day,)):
        if r["webhook_id"] in names and r["n"] >= 5 and r["bad"] * 2 > r["n"] and names[r["webhook_id"]] not in failed:
            flaky.append(names[r["webhook_id"]])
    skipped = c.execute("SELECT count(*) FROM webhook_events WHERE skipped>0 AND created>=?", (day,)).fetchone()[0]
    return {"failed": failed, "flaky": flaky, "skipped": skipped}


# ---------------------------------------------------------------------------------------------------------- the routes
def install(app, settings, store, auth, mutate):
    use(auth, settings.public_url)

    def once(request, body, fn):
        """A write whose answer carries a secret goes through the vault's receipt (Vault.change): the idempotency row
        keeps a keyed fingerprint of the request and the answer without the secret. A replay answers with
        `replayed: true` and no secret, so the page asks for a new one instead of showing a stale one."""
        shown = {}

        def run(c):
            result = fn(c)
            if result.get("webhook") and "secret" in result["webhook"]:
                shown["secret"] = result["webhook"].pop("secret")
            return result
        out = request.app.state.vault.change(request.state.identity, request.url.path,
                                             request.headers.get("idempotency-key"), body, lambda c, who: None, run)
        if out.get("webhook") is not None:
            out = {**out, "webhook": {**out["webhook"], "replayed": not shown, **({"secret": shown["secret"]} if shown else {})}}
        return out

    def person_or_bot(who):
        if who.role not in ("owner", "human", "bot"):
            raise Problem("forbidden", "Only people and bots use webhook endpoints", 403)

    @app.get("/api/v2/webhooks")
    def webhook_list(request: Request, limit: int = LISTED, offset: int = 0):
        """The caller's endpoints (an admin sees everyone's), with 7-day delivered and failed counts. Paged."""
        who = request.state.identity
        person_or_bot(who)
        with store.read() as c:
            return listing(c, who, limit, offset)

    @app.post("/api/v2/webhooks")
    def webhook_create(request: Request, body: WebhookCreate):
        """A new endpoint. The answer's `secret` is shown only now. A bot's call files an approval instead and the
        answer says `approval`; asking again after a person approved it makes the endpoint."""
        who = request.state.identity
        person_or_bot(who)

        def make(c):
            made = create(c, request.app.state.vault, who, body)
            return made if "approval" in made else {"webhook": made}
        return once(request, body, make)

    @app.get("/api/v2/webhooks/{hook_id}")
    def webhook_show(request: Request, hook_id: str):
        """One endpoint and its last ten attempts."""
        who = request.state.identity
        person_or_bot(who)
        with store.read() as c:
            hook = _reach(c, who, hook_id)
            shown = view(hook, who, counts(c, [hook_id]).get(hook_id))
            recent = [] if who.role == "bot" else [dict(r) for r in c.execute(
                "SELECT send_id,n,at,status,ms,error FROM webhook_attempts WHERE webhook_id=? ORDER BY at DESC, n DESC LIMIT 10",
                (hook_id,))]
            return {"webhook": shown, "recent_attempts": recent}

    @app.post("/api/v2/webhooks/{hook_id}/update")
    def webhook_update(request: Request, hook_id: str, body: WebhookUpdate):
        """Change the name, address, events, rate or (for the owner) the plain-http switch."""
        return mutate(request, body, lambda c: {"webhook": update(c, request.state.identity, hook_id, body)})

    @app.post("/api/v2/webhooks/{hook_id}/rotate")
    def webhook_rotate(request: Request, hook_id: str, body: M.Empty):
        """A new secret, shown once; the old one keeps signing beside it for 24 hours."""
        return once(request, body, lambda c: {"webhook": rotate(c, request.app.state.vault, request.state.identity, hook_id)})

    @app.post("/api/v2/webhooks/{hook_id}/pause")
    def webhook_pause(request: Request, hook_id: str, body: Pause):
        """Stop sending; what is queued waits."""
        return mutate(request, body, lambda c: {"webhook": pause(c, request.state.identity, hook_id, body.reason)})

    @app.post("/api/v2/webhooks/{hook_id}/resume")
    def webhook_resume(request: Request, hook_id: str, body: M.Empty):
        return mutate(request, body, lambda c: {"webhook": resume(c, request.state.identity, hook_id)})

    @app.post("/api/v2/webhooks/{hook_id}/delete")
    def webhook_delete(request: Request, hook_id: str, body: M.Empty):
        """Delete the endpoint and cancel what is waiting to be sent."""
        return mutate(request, body, lambda c: delete(c, request.state.identity, hook_id))

    @app.post("/api/v2/webhooks/{hook_id}/send")
    def webhook_send(request: Request, hook_id: str, body: WebhookSend):
        """A custom event (custom.<name>) to one endpoint."""
        return mutate(request, body, lambda c: send_custom(c, request.state.identity, hook_id, body))

    @app.post("/api/v2/webhooks/{hook_id}/example")
    def webhook_example(request: Request, hook_id: str, body: WebhookExample):
        """Send an event type's example to one endpoint."""
        return mutate(request, body, lambda c: send_example(c, request.state.identity, hook_id, body))

    @app.get("/api/v2/webhooks/{hook_id}/sends")
    def webhook_sends(request: Request, hook_id: str, state: str = "", limit: int = LOG_LISTED, offset: int = 0):
        """The send log, newest first: type, subject, state, attempts, last status, next attempt."""
        who = request.state.identity
        person_or_bot(who)
        with store.read() as c:
            return sends(c, who, hook_id, state or None, limit, offset)

    @app.get("/api/v2/webhooks/{hook_id}/sends/{send_id}")
    def webhook_send_one(request: Request, hook_id: str, send_id: str):
        """One send with its attempts."""
        who = request.state.identity
        person_or_bot(who)
        with store.read() as c:
            return {"send": one_send(c, who, hook_id, send_id)}

    @app.post("/api/v2/webhooks/{hook_id}/sends/{send_id}/retry")
    def webhook_retry(request: Request, hook_id: str, send_id: str, body: M.Empty):
        """Try a failed or cancelled send again."""
        return mutate(request, body, lambda c: {"send": retry(c, request.state.identity, hook_id, send_id)})
