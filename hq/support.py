"""Support tickets: what a person writes to the Tico team from their app, and what the team writes back.

    POST /v1/support                       a person files a ticket; the answer is {ticket_id, secret}
    GET  /v1/support/{ticket_id}           that person's app asks for its status and replies (the ticket's secret)
    GET  /v1/staff/tickets                 the team lists tickets              (HQ_STAFF_KEY)
    GET  /v1/staff/tickets/{id}            one ticket with its replies         (HQ_STAFF_KEY)
    POST /v1/staff/tickets/{id}/reply      a reply the person's app will fetch (HQ_STAFF_KEY)
    POST /v1/staff/tickets/{id}/status     open, answered or closed            (HQ_STAFF_KEY)

A ticket is untrusted text from anyone on the internet. It is validated strictly, stored as plain text and never
interpreted, and it is never logged. The address of a request is used for rate limiting in memory (limits.py) and
nowhere else. The ticket's secret is shown once, in the answer to POST; HQ keeps only its SHA-256, so the database
cannot be used to read another person's replies. Closed tickets are deleted after 90 days and any ticket after 13
months (`Tickets.purge`). PRIVACY.md is the statement of it; docs/support.md is how the team works the queue.
"""
import hashlib
import hmac
import json
import re
import secrets
import time
from datetime import datetime, timedelta, timezone

from fastapi import Request
from fastapi.responses import JSONResponse

from .limits import Limiter

CLOSED_DAYS = 90
TICKET_DAYS = 395                 # 13 months, as the install rows
MAX_MESSAGE = 4000
MAX_REPLY = 8000
MAX_REQUEST = 16 * 1024           # bytes of a ticket request; a full message is well under this
MAX_STAFF_REQUEST = 48 * 1024
STATUSES = ("open", "answered", "closed")
ALPHABET = "ABCDEFGHIJKLMNOPQRSTUVWXYZ234567"

TICKET_ID = re.compile(r"TK-[A-Z2-7]{8}")
SECRET = re.compile(r"[A-Za-z0-9_-]{20,64}")
# The same shapes hq/app.py accepts for a ping.
INSTALL_ID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}")
VERSION = re.compile(r"[0-9]{1,4}\.[0-9]{1,4}\.[0-9]{1,4}(?:-[0-9A-Za-z][0-9A-Za-z.-]{0,31})?")
EMAIL = re.compile(r"[^@\s<>\",;()\[\]\\]{1,64}@[A-Za-z0-9](?:[A-Za-z0-9.-]{0,251}[A-Za-z0-9])?\.[A-Za-z]{2,24}")
MOMENT = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z")
CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f  ‪-‮⁦-⁩]")
FIELDS = ("message", "email", "install_id", "version")

SCHEMA = """
CREATE TABLE IF NOT EXISTS tickets(
 ticket_id TEXT PRIMARY KEY, key_hash TEXT NOT NULL, created TEXT NOT NULL, updated TEXT NOT NULL,
 closed TEXT, status TEXT NOT NULL DEFAULT 'open', body TEXT NOT NULL, email TEXT, install_id TEXT, version TEXT,
 email_pending INTEGER NOT NULL DEFAULT 0);
CREATE INDEX IF NOT EXISTS tickets_created ON tickets(created);
CREATE TABLE IF NOT EXISTS ticket_replies(
 id INTEGER PRIMARY KEY AUTOINCREMENT, ticket_id TEXT NOT NULL, created TEXT NOT NULL, body TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS ticket_replies_ticket ON ticket_replies(ticket_id, id);
"""


def utcnow():
    return datetime.now(timezone.utc)


def stamp(moment):
    return moment.strftime("%Y-%m-%dT%H:%M:%SZ")


def digest(value):
    return hashlib.sha256(str(value).encode()).hexdigest()


class Invalid(Exception):
    """A request refused; `field` names the one thing wrong, never its value."""

    def __init__(self, field):
        super().__init__(field)
        self.field = field


def text(value, field, limit):
    """Plain text of 1..limit characters: a string, no control characters, no blank message."""
    if not isinstance(value, str) or CONTROL.search(value):
        raise Invalid(field)
    value = value.replace("\r\n", "\n").replace("\r", "\n")
    if not value.strip() or len(value) > limit:
        raise Invalid(field)
    return value.strip()


def parse_ticket(data):
    """(message, email, install_id, version) from a decoded request, or Invalid. Fields beyond these four are refused."""
    if not isinstance(data, dict) or set(data) - set(FIELDS):
        raise Invalid("fields")
    message = text(data.get("message"), "message", MAX_MESSAGE)
    values = {}
    for name, pattern in (("email", EMAIL), ("install_id", INSTALL_ID), ("version", VERSION)):
        value = data.get(name)
        if value in (None, ""):
            values[name] = None
        elif not isinstance(value, str) or (name == "email" and len(value) > 254) or not pattern.fullmatch(value):
            raise Invalid(name)
        else:
            values[name] = value
    return message, values["email"], values["install_id"], values["version"]


class Tickets:
    """The tickets table and the limits in front of it. Shares the installs database's connection and lock."""

    def __init__(self, db, now=utcnow, clock=time.monotonic):
        self.db, self.now = db, now
        with db.lock:
            db.conn.execute("PRAGMA secure_delete=ON")       # a deleted ticket's text is overwritten, not just unlinked
            db.conn.executescript(SCHEMA)
        # In memory, as the request limit is: a salted hash of the address, or of the install id, forgotten on restart.
        self.per_address = Limiter(limit=5, window=3600, clock=clock)         # tickets an hour from one address
        self.per_install = Limiter(limit=10, window=86400, clock=clock)       # tickets a day from one install id
        self.overall = Limiter(limit=1000, window=86400, clock=clock)         # tickets a day in all: a flood cap
        self.reads = Limiter(limit=600, window=3600, clock=clock)             # a person's app asking for replies
        self.staff = Limiter(limit=1200, window=3600, clock=clock)
        self.refused = Limiter(limit=20, window=3600, clock=clock)            # wrong staff keys, per address

    # ------------------------------------------------------------------ people
    def create(self, message, email, install_id, version):
        """Store a ticket. Returns (ticket_id, secret); the secret is not kept, only its hash."""
        secret = secrets.token_urlsafe(24)
        moment = stamp(self.now())
        with self.db.lock:
            while True:
                ticket_id = "TK-" + "".join(secrets.choice(ALPHABET) for _ in range(8))
                if not self.db.conn.execute("SELECT 1 FROM tickets WHERE ticket_id=?", (ticket_id,)).fetchone():
                    break
            self.db.conn.execute(
                "INSERT INTO tickets(ticket_id,key_hash,created,updated,status,body,email,install_id,version) "
                "VALUES(?,?,?,?,'open',?,?,?,?)",
                (ticket_id, digest(secret), moment, moment, message, email, install_id, version))
        return ticket_id, secret

    def for_person(self, ticket_id, secret):
        """What the person's app may see: the status and the replies. None for an unknown ticket or a wrong secret,
        the same answer for both."""
        with self.db.lock:
            row = self.db.conn.execute("SELECT * FROM tickets WHERE ticket_id=?", (ticket_id,)).fetchone()
            expected = row["key_hash"] if row else digest("no such ticket")
            if not hmac.compare_digest(digest(secret), expected) or not row:
                return None
            replies = self._replies(ticket_id)
        return {"ticket_id": ticket_id, "status": row["status"], "created": row["created"],
                "updated": row["updated"], "replies": replies}

    # ------------------------------------------------------------------ staff
    def _replies(self, ticket_id):
        return [{"id": r["id"], "created": r["created"], "body": r["body"]} for r in self.db.conn.execute(
            "SELECT id,created,body FROM ticket_replies WHERE ticket_id=? ORDER BY id", (ticket_id,))]

    def _staff_view(self, row):
        return {"ticket_id": row["ticket_id"], "status": row["status"], "created": row["created"],
                "updated": row["updated"], "body": row["body"], "email": row["email"], "version": row["version"],
                "install_id": row["install_id"], "email_pending": bool(row["email_pending"]),
                "replies": self._replies(row["ticket_id"])}

    def listing(self, status="", since="", limit=50):
        """Oldest first, so a caller that remembers the last `updated` it saw misses nothing."""
        where, args = [], []
        if status and status != "all":
            where.append("status=?")
            args.append(status)
        if since:
            where.append("updated>?")
            args.append(since)
        sql = "SELECT * FROM tickets" + (" WHERE " + " AND ".join(where) if where else "")
        with self.db.lock:
            rows = self.db.conn.execute(sql + " ORDER BY updated, ticket_id LIMIT ?", (*args, limit)).fetchall()
            return [self._staff_view(r) for r in rows]

    def show(self, ticket_id):
        with self.db.lock:
            row = self.db.conn.execute("SELECT * FROM tickets WHERE ticket_id=?", (ticket_id,)).fetchone()
            return self._staff_view(row) if row else None

    def reply(self, ticket_id, body):
        """Record a reply for the install to fetch. A ticket with an email address is marked "email pending": HQ sends
        no mail, the Support bot drafts it. Returns the ticket's new state, None for an unknown ticket, and False for
        a closed one."""
        moment = stamp(self.now())
        with self.db.lock:
            row = self.db.conn.execute("SELECT * FROM tickets WHERE ticket_id=?", (ticket_id,)).fetchone()
            if not row:
                return None
            if row["status"] == "closed":
                return False
            reply = self.db.conn.execute("INSERT INTO ticket_replies(ticket_id,created,body) VALUES(?,?,?)",
                                         (ticket_id, moment, body)).lastrowid
            pending = 1 if row["email"] else 0
            self.db.conn.execute("UPDATE tickets SET status='answered', updated=?, email_pending=? WHERE ticket_id=?",
                                 (moment, pending or row["email_pending"], ticket_id))
        return {"ticket_id": ticket_id, "status": "answered", "reply_id": reply, "email_pending": bool(pending)}

    def set_status(self, ticket_id, status=None, email_sent=False):
        moment = stamp(self.now())
        with self.db.lock:
            row = self.db.conn.execute("SELECT * FROM tickets WHERE ticket_id=?", (ticket_id,)).fetchone()
            if not row:
                return None
            status = status or row["status"]
            closed = (row["closed"] or moment) if status == "closed" else None
            pending = 0 if email_sent else row["email_pending"]
            self.db.conn.execute("UPDATE tickets SET status=?, closed=?, email_pending=?, updated=? WHERE ticket_id=?",
                                 (status, closed, pending, moment, ticket_id))
        return {"ticket_id": ticket_id, "status": status, "email_pending": bool(pending)}

    # ------------------------------------------------------------------ retention
    def purge(self):
        """Closed tickets after 90 days, any ticket after 13 months, with their replies. Returns how many tickets."""
        now = self.now()
        closed_cutoff = stamp(now - timedelta(days=CLOSED_DAYS))
        old_cutoff = stamp(now - timedelta(days=TICKET_DAYS))
        with self.db.lock:
            ids = [r[0] for r in self.db.conn.execute(
                "SELECT ticket_id FROM tickets WHERE created<? OR (status='closed' AND closed<?)",
                (old_cutoff, closed_cutoff))]
            for ticket_id in ids:
                self.db.conn.execute("DELETE FROM ticket_replies WHERE ticket_id=?", (ticket_id,))
                self.db.conn.execute("DELETE FROM tickets WHERE ticket_id=?", (ticket_id,))
            # Free the deleted text from the file, not only from the table.
            if ids:
                self.db.conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        return len(ids)


# ---------------------------------------------------------------------- the routes
def no_store(body, status=200):
    return JSONResponse(body, status_code=status, headers={"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"})


def refuse(error, status, **extra):
    return no_store({"error": error, **extra}, status)


async def read_json(request, limit):
    """The request's JSON, or a (status, error) pair. The body is read only up to `limit` bytes."""
    declared = request.headers.get("content-length", "")
    if declared.isdigit() and int(declared) > limit:
        return 413, "too_large"
    raw = b""
    async for chunk in request.stream():
        raw += chunk
        if len(raw) > limit:
            return 413, "too_large"
    try:
        return 200, json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError, RecursionError):
        return 422, "invalid"


def install(app, tickets, address, staff_key=""):
    """Add the six routes. `address(request)` is who is asking, for the rate limits only."""
    key_digest = digest(staff_key) if staff_key else ""

    @app.post("/v1/support")
    async def file_ticket(request: Request):
        who = address(request)
        if not tickets.per_address.allow(who) or not tickets.overall.allow("all"):
            return JSONResponse({"error": "rate_limited"}, status_code=429, headers={"Retry-After": "3600"})
        status, data = await read_json(request, MAX_REQUEST)
        if status != 200:
            return refuse(data, status)
        try:
            message, email, install_id, version = parse_ticket(data)
        except Invalid as bad:
            return refuse("invalid", 422, field=bad.field)
        if install_id and not tickets.per_install.allow(install_id):
            return JSONResponse({"error": "rate_limited"}, status_code=429, headers={"Retry-After": "86400"})
        ticket_id, secret = tickets.create(message, email, install_id, version)
        return no_store({"ticket_id": ticket_id, "secret": secret, "status": "open"}, 201)

    @app.get("/v1/support/{ticket_id}")
    def ticket_for_person(request: Request, ticket_id: str):
        if not tickets.reads.allow(address(request)):
            return JSONResponse({"error": "rate_limited"}, status_code=429, headers={"Retry-After": "3600"})
        secret = request.headers.get("x-ticket-secret") or request.query_params.get("secret") or ""
        found = None
        if TICKET_ID.fullmatch(ticket_id) and SECRET.fullmatch(secret):
            found = tickets.for_person(ticket_id, secret)
        return no_store(found) if found else refuse("not_found", 404)

    def staff_only(request):
        """None when the caller holds the staff key, else the refusal. With no key configured the routes do not exist."""
        if not key_digest:
            return refuse("not_found", 404)
        who = address(request)
        if not tickets.staff.allow(who):
            return JSONResponse({"error": "rate_limited"}, status_code=429, headers={"Retry-After": "3600"})
        header = request.headers.get("authorization", "")
        given = header[7:].strip() if header[:7].lower() == "bearer " else ""
        if given and hmac.compare_digest(digest(given), key_digest):
            return None
        if not tickets.refused.allow(who):
            return JSONResponse({"error": "rate_limited"}, status_code=429, headers={"Retry-After": "3600"})
        return refuse("unauthorized", 401)

    def known(ticket_id):
        return TICKET_ID.fullmatch(ticket_id)

    @app.get("/v1/staff/tickets")
    def staff_list(request: Request):
        denied = staff_only(request)
        if denied:
            return denied
        params = request.query_params
        status, since = params.get("status", ""), params.get("since", "")
        limit = params.get("limit", "50")
        if (status and status not in STATUSES + ("all",)) or (since and not MOMENT.fullmatch(since)) \
                or not limit.isdigit() or not 1 <= int(limit) <= 200:
            return refuse("invalid", 422)
        return no_store({"tickets": tickets.listing(status, since, int(limit))})

    @app.get("/v1/staff/tickets/{ticket_id}")
    def staff_show(request: Request, ticket_id: str):
        denied = staff_only(request)
        if denied:
            return denied
        found = tickets.show(ticket_id) if known(ticket_id) else None
        return no_store(found) if found else refuse("not_found", 404)

    @app.post("/v1/staff/tickets/{ticket_id}/reply")
    async def staff_reply(request: Request, ticket_id: str):
        denied = staff_only(request)
        if denied:
            return denied
        status, data = await read_json(request, MAX_STAFF_REQUEST)
        if status != 200:
            return refuse(data, status)
        try:
            if not isinstance(data, dict) or set(data) != {"body"}:
                raise Invalid("fields")
            body = text(data["body"], "body", MAX_REPLY)
        except Invalid as bad:
            return refuse("invalid", 422, field=bad.field)
        done = tickets.reply(ticket_id, body) if known(ticket_id) else None
        if done is None:
            return refuse("not_found", 404)
        return no_store(done) if done else refuse("closed", 409)

    @app.post("/v1/staff/tickets/{ticket_id}/status")
    async def staff_status(request: Request, ticket_id: str):
        denied = staff_only(request)
        if denied:
            return denied
        status, data = await read_json(request, MAX_STAFF_REQUEST)
        if status != 200:
            return refuse(data, status)
        if not isinstance(data, dict) or not data or set(data) - {"status", "email_sent"} \
                or data.get("status", "open") not in STATUSES or not isinstance(data.get("email_sent", False), bool):
            return refuse("invalid", 422)
        done = tickets.set_status(ticket_id, data.get("status"), data.get("email_sent") is True) \
            if known(ticket_id) else None
        return no_store(done) if done else refuse("not_found", 404)
