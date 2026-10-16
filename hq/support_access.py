"""Support access: the Tico team, or its Support Agent, uses a person's app in a session that person opened from a
ticket (docs/support.md, "Letting Tico support in"). The install dials out; HQ only carries requests to it.

    POST /v1/support/{ticket_id}/access                 the install opens a session {tier, expires_at} -> {session} (the ticket's secret)
    POST /v1/support/{ticket_id}/access/{sid}/pull      the install long-polls for requests: {ended, requests} (the secret)
    POST /v1/support/{ticket_id}/access/{sid}/reply     the install's answers {replies: [{rid, status, content_type, body_b64}]} (the secret)
    POST /v1/support/{ticket_id}/access/{sid}/end       the person stopped it, or it expired there (the secret)
    GET  /v1/staff/access                               live sessions; ?ticket=TK-... for a ticket's, ended ones too (HQ_STAFF_KEY)
    GET  /v1/staff/access/{sid}/log                     every request carried in a session (HQ_STAFF_KEY)
    GET|POST|PUT|PATCH|DELETE /v1/staff/access/{sid}/api/{path}   one request to the install's /api/{path}, answered
        with the install's own status and body, or 504 when it does not answer in time (HQ_STAFF_KEY;
        X-Tico-Support-By: staff or support-agent)

HQ never opens a session: only the install does, with the ticket's secret, and it says when it ends. A session HQ has
not seen, one that ended, or one past its time carries nothing. Each carried request (who, method, path, status, never
a body) is kept in `access_log` with its ticket and deleted with it. What an install answers is untrusted data: the
Support Agent reads it as such.

The requests waiting for an install and the answers waiting for staff are kept in this process's memory: HQ runs as one
process (__main__.py), so the request a staff call queued and the pull that takes it meet here.
"""
import asyncio
import base64
import re
import secrets
from datetime import datetime, timedelta, timezone

from fastapi import Request
from fastapi.responses import JSONResponse, Response

from .support import MOMENT, TICKET_ID, SECRET, no_store, read_json, refuse, stamp

SCHEMA = """
CREATE TABLE IF NOT EXISTS access_sessions(
 session_id TEXT PRIMARY KEY, ticket_id TEXT NOT NULL, tier TEXT NOT NULL, opened TEXT NOT NULL, expires_at TEXT NOT NULL,
 ended_at TEXT, end_reason TEXT);
CREATE INDEX IF NOT EXISTS access_sessions_ticket ON access_sessions(ticket_id);
CREATE TABLE IF NOT EXISTS access_log(
 id INTEGER PRIMARY KEY AUTOINCREMENT, session_id TEXT NOT NULL, ticket_id TEXT NOT NULL, at TEXT NOT NULL,
 by TEXT NOT NULL, method TEXT NOT NULL, path TEXT NOT NULL, status INTEGER);
CREATE INDEX IF NOT EXISTS access_log_session ON access_log(session_id, id);
"""
SESSION = re.compile(r"sa_[0-9a-f]{24}")
TIERS = ("app", "full")
MAX_HOURS = 721                   # the install allows 720; an hour's slack for clocks
PULL_WAIT = 25                    # seconds a pull is held open with nothing to hand over
PROXY_WAIT = 30                   # seconds a staff call waits for the install's answer
MAX_PROXY_REQUEST = 1024 * 1024   # a staff call's body
MAX_REPLIES = 3 * 1024 * 1024     # one reply batch: the install caps each answer at 2 MB
MAX_QUERY = 4000
METHODS = ("GET", "POST", "PUT", "PATCH", "DELETE")
BY = ("staff", "support-agent")


class Relay:
    """Requests queued for an install, and the staff calls waiting for their answers. In memory: HQ is one process."""

    def __init__(self):
        self.queued, self.wakes, self.waiting = {}, {}, {}

    def _wake(self, sid):
        return self.wakes.setdefault(sid, asyncio.Event())

    async def ask(self, sid, request, wait):
        """Queue one request and wait for its answer: the reply dict, or None after `wait` seconds."""
        future = asyncio.get_running_loop().create_future()
        self.waiting[request["rid"]] = (sid, future)
        self.queued.setdefault(sid, []).append(request)
        self._wake(sid).set()
        try:
            return await asyncio.wait_for(future, wait)
        except asyncio.TimeoutError:
            return None
        finally:
            self.waiting.pop(request["rid"], None)
            if request in self.queued.get(sid, []):
                self.queued[sid].remove(request)

    async def take(self, sid, wait, still_live):
        """What is queued for this session, waiting up to `wait` seconds for something."""
        if not self.queued.get(sid):
            event = self._wake(sid)
            event.clear()
            try:
                await asyncio.wait_for(event.wait(), wait)
            except asyncio.TimeoutError:
                pass
        if not still_live():
            return None
        taken, self.queued[sid] = self.queued.get(sid, []), []
        return taken

    def answer(self, sid, reply):
        held = self.waiting.get(reply["rid"])
        if held and held[0] == sid and not held[1].done():
            held[1].set_result(reply)

    def end(self, sid):
        """Wake a held pull, and answer every waiting staff call with the end."""
        self._wake(sid).set()
        for rid, (owner, future) in list(self.waiting.items()):
            if owner == sid and not future.done():
                future.set_result({"rid": rid, "ended": True})
        self.queued.pop(sid, None)


class Sessions:
    """The access_sessions and access_log tables. Shares the tickets' database connection and lock."""

    def __init__(self, tickets):
        self.tickets, self.db = tickets, tickets.db
        with self.db.lock:
            self.db.conn.executescript(SCHEMA)
        self.relay = Relay()

    def moment(self):
        return stamp(self.tickets.now())

    def open(self, ticket_id, tier, expires_at):
        """A new session on this ticket; any live one on it ends first. Returns the session id."""
        sid = "sa_" + secrets.token_hex(12)
        moment = self.moment()
        with self.db.lock:
            for row in self.db.conn.execute("SELECT session_id FROM access_sessions WHERE ticket_id=? AND ended_at IS NULL",
                                            (ticket_id,)).fetchall():
                self.db.conn.execute("UPDATE access_sessions SET ended_at=?, end_reason='replaced' WHERE session_id=?",
                                     (moment, row["session_id"]))
                self.relay.end(row["session_id"])
            self.db.conn.execute("INSERT INTO access_sessions(session_id,ticket_id,tier,opened,expires_at) VALUES(?,?,?,?,?)",
                                 (sid, ticket_id, tier, moment, expires_at))
        return sid

    def get(self, sid, ticket_id=None):
        with self.db.lock:
            row = self.db.conn.execute("SELECT * FROM access_sessions WHERE session_id=?", (sid,)).fetchone()
        return row if row and (ticket_id is None or row["ticket_id"] == ticket_id) else None

    def live(self, row):
        return bool(row) and not row["ended_at"] and row["expires_at"] > self.moment()

    def end(self, sid, reason):
        with self.db.lock:
            self.db.conn.execute("UPDATE access_sessions SET ended_at=?, end_reason=? WHERE session_id=? AND ended_at IS NULL",
                                 (self.moment(), reason, sid))
        self.relay.end(sid)

    def record(self, row, by, method, path, status):
        with self.db.lock:
            self.db.conn.execute("INSERT INTO access_log(session_id,ticket_id,at,by,method,path,status) VALUES(?,?,?,?,?,?,?)",
                                 (row["session_id"], row["ticket_id"], self.moment(), by, method, path[:500], status))

    def listing(self, ticket_id=""):
        with self.db.lock:
            if ticket_id:
                rows = self.db.conn.execute("SELECT * FROM access_sessions WHERE ticket_id=? ORDER BY opened DESC LIMIT 50",
                                            (ticket_id,)).fetchall()
            else:
                rows = self.db.conn.execute("SELECT * FROM access_sessions WHERE ended_at IS NULL AND expires_at>? "
                                            "ORDER BY opened", (self.moment(),)).fetchall()
        return [dict(r) for r in rows]

    def log(self, sid):
        with self.db.lock:
            return [dict(r) for r in self.db.conn.execute(
                "SELECT at,by,method,path,status FROM access_log WHERE session_id=? ORDER BY id DESC LIMIT 500", (sid,))]


def _later(moment, value):
    """Whether `value` is an HQ time after `moment` and within MAX_HOURS of it."""
    if not isinstance(value, str) or not MOMENT.fullmatch(value):
        return False
    limit = datetime.strptime(moment, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc) + timedelta(hours=MAX_HOURS)
    return moment < value <= stamp(limit)


def install(app, tickets, address, staff_only, sessions=None):
    """Add the routes. `staff_only(request)` is the staff check of support.py: None, or the refusal."""
    sessions = sessions or Sessions(tickets)
    app.state.access_sessions = sessions

    def install_session(request, ticket_id, sid=None):
        """(ticket row, session row) when the caller holds the ticket's secret and, with `sid`, the session is on it."""
        if not tickets.access.allow(address(request)):
            return None, JSONResponse({"error": "rate_limited"}, status_code=429, headers={"Retry-After": "3600"})
        secret = request.headers.get("x-ticket-secret") or ""
        found = None
        if TICKET_ID.fullmatch(ticket_id) and SECRET.fullmatch(secret):
            with tickets.db.lock:
                found = tickets._owned(ticket_id, secret)
        if not found:
            return None, refuse("not_found", 404)
        if sid is None:
            return (found, None), None
        row = sessions.get(sid, ticket_id) if SESSION.fullmatch(sid) else None
        return ((found, row), None) if row else (None, refuse("not_found", 404))

    @app.post("/v1/support/{ticket_id}/access")
    async def open_access(request: Request, ticket_id: str):
        found, denied = install_session(request, ticket_id)
        if denied:
            return denied
        status, data = await read_json(request, 1024)
        if status != 200:
            return refuse(data, status)
        if not isinstance(data, dict) or set(data) != {"tier", "expires_at"} or data["tier"] not in TIERS \
                or not _later(sessions.moment(), data["expires_at"]):
            return refuse("invalid", 422)
        if found[0]["status"] == "closed":
            return refuse("closed", 409)
        return no_store({"session": sessions.open(ticket_id, data["tier"], data["expires_at"])}, 201)

    @app.post("/v1/support/{ticket_id}/access/{sid}/pull")
    async def pull(request: Request, ticket_id: str, sid: str):
        found, denied = install_session(request, ticket_id, sid)
        if denied:
            return denied
        row = found[1]
        if not sessions.live(row):
            return no_store({"ended": True, "requests": []})
        taken = await sessions.relay.take(sid, PULL_WAIT, lambda: sessions.live(sessions.get(sid)))
        if taken is None:
            return no_store({"ended": True, "requests": []})
        return no_store({"ended": False, "requests": taken})

    @app.post("/v1/support/{ticket_id}/access/{sid}/reply")
    async def reply(request: Request, ticket_id: str, sid: str):
        found, denied = install_session(request, ticket_id, sid)
        if denied:
            return denied
        status, data = await read_json(request, MAX_REPLIES)
        if status != 200:
            return refuse(data, status)
        replies = data.get("replies") if isinstance(data, dict) else None
        if not isinstance(replies, list) or len(replies) > 50:
            return refuse("invalid", 422)
        for item in replies:
            if (isinstance(item, dict) and isinstance(item.get("rid"), str) and isinstance(item.get("status"), int)
                    and isinstance(item.get("body_b64", ""), str) and isinstance(item.get("content_type", ""), str)):
                sessions.relay.answer(sid, item)
        return no_store({"ok": True})

    @app.post("/v1/support/{ticket_id}/access/{sid}/end")
    async def end_access(request: Request, ticket_id: str, sid: str):
        found, denied = install_session(request, ticket_id, sid)
        if denied:
            return denied
        sessions.end(sid, "ended_by_install")
        return no_store({"ended": True})

    @app.get("/v1/staff/access")
    def staff_sessions(request: Request):
        denied = staff_only(request)
        if denied:
            return denied
        ticket_id = request.query_params.get("ticket", "")
        if ticket_id and not TICKET_ID.fullmatch(ticket_id):
            return refuse("invalid", 422)
        return no_store({"sessions": [{"session": r["session_id"], "ticket_id": r["ticket_id"], "tier": r["tier"],
                                       "opened": r["opened"], "expires_at": r["expires_at"], "ended_at": r["ended_at"],
                                       "end_reason": r["end_reason"]} for r in sessions.listing(ticket_id)]})

    @app.get("/v1/staff/access/{sid}/log")
    def staff_log(request: Request, sid: str):
        denied = staff_only(request)
        if denied:
            return denied
        if not SESSION.fullmatch(sid) or not sessions.get(sid):
            return refuse("not_found", 404)
        return no_store({"log": sessions.log(sid)})

    @app.api_route("/v1/staff/access/{sid}/api/{path:path}", methods=list(METHODS))
    async def staff_call(request: Request, sid: str, path: str):
        denied = staff_only(request)
        if denied:
            return denied
        row = sessions.get(sid) if SESSION.fullmatch(sid) else None
        if not row:
            return refuse("not_found", 404)
        if not sessions.live(row):
            return refuse("session_ended", 409)
        by = request.headers.get("x-tico-support-by", "staff")
        query = request.url.query
        if by not in BY or len(query) > MAX_QUERY:
            return refuse("invalid", 422)
        raw = b""
        async for chunk in request.stream():
            raw += chunk
            if len(raw) > MAX_PROXY_REQUEST:
                return refuse("too_large", 413)
        target = "/api/" + path
        answer = await sessions.relay.ask(sid, {
            "rid": secrets.token_hex(8), "by": by, "method": request.method, "path": target, "query": query,
            "content_type": request.headers.get("content-type", "")[:200],
            "body_b64": base64.b64encode(raw).decode()}, PROXY_WAIT)
        if answer is None:
            sessions.record(row, by, request.method, target, 504)
            return refuse("install_timeout", 504)
        if answer.get("ended"):
            sessions.record(row, by, request.method, target, 409)
            return refuse("session_ended", 409)
        try:
            body = base64.b64decode(answer.get("body_b64") or "", validate=True)
        except ValueError:
            body, answer = b"", {**answer, "status": 502}
        status = answer["status"] if 100 <= answer["status"] <= 599 else 502
        sessions.record(row, by, request.method, target, status)
        content_type = answer.get("content_type") or "application/octet-stream"
        return Response(body, status_code=status, media_type=content_type.split(";")[0][:100] or None,
                        headers={"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"})

    return sessions
