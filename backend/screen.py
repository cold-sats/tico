"""A computer's screen in the web app: watch its bots work, or take control.

Two locks, both needed. The computer's owner turns the screen on on the computer itself (the runner then reports
`screen_v1` and its size in `readiness.screen`), and the computer's operator or an admin sets `runners.screen` here
to `off`, `view` or `control`. Opening the screen makes a session: a single-use ticket the browser's websocket
carries, and a `screen_open` event on the runner's stream, which answers with its own websocket. The hub pipes the
bytes (VNC) between the two and reads none of them; view against control is the runner's to enforce, by the port it
connects the session to.

The session registry lives in memory in this one server process: a restart ends every open screen, and the runner
and the browser each open a fresh one. More than one process would need a shared registry first.
"""
import asyncio
import hashlib
import logging
import secrets
import threading
import time

from fastapi import Request, WebSocket

from .store import H, Problem

MODES = ("off", "view", "control")
CAPABILITY = "screen_v1"
MAX_SESSIONS = 3            # open per computer
TICKET_SECONDS = 60         # the browser connects within this
ANSWER_SECONDS = 20         # the runner connects within this once the browser has
MAX_SECONDS = 60 * 60       # one session's hard cap
WIDTH, HEIGHT = 1440, 900   # the runner's default display, when its report names none

UNAVAILABLE = "This computer has no screen. Turn it on on the computer first."

log = logging.getLogger(__name__)


def available(row):
    """Whether the computer's last heartbeat offered a screen."""
    return CAPABILITY in set(H._json(row["capabilities_json"], []) or []) if row else False


def size(row):
    screen = (H._json(row["readiness_json"], {}) or {}).get("screen") or {}
    return int(screen.get("width") or WIDTH), int(screen.get("height") or HEIGHT)


def listing(row):
    """The fields a computer's row carries in the Operations and Computers listings."""
    return {"screen": row["screen"] if row["screen"] in MODES else "off", "screen_available": available(row)}


def may_change(auth, who, runner):
    """The same rule as restart and inbox sharing: an admin, or the person whose computer it is."""
    return bool(runner) and (auth.bot_admin(who) or who.role == "human" and who.actor == "human:" + runner["operator"])


def _digest(ticket):
    return hashlib.sha256(ticket.encode()).hexdigest()


class Session:
    def __init__(self, runner_id, actor, control, ticket_hash, width, height):
        self.id = H.new_id()
        self.runner_id, self.actor, self.control = runner_id, actor, control
        self.ticket_hash, self.width, self.height = ticket_hash, width, height
        self.created = time.monotonic()
        self.started = None                     # when the browser connected
        self.redeemed = self.closed = False
        self.browser = self.runner = None
        self.loop = None
        self.code, self.reason = 1000, ""
        self.browser_in, self.runner_in, self.ended = asyncio.Event(), asyncio.Event(), asyncio.Event()


class Registry:
    def __init__(self, store):
        self.store = store
        self.lock = threading.Lock()
        self.sessions = {}

    def _sweep(self):
        """Sessions whose browser never came within the ticket's minute. Called under the lock."""
        now = time.monotonic()
        return [s for s in self.sessions.values() if not s.redeemed and now - s.created > TICKET_SECONDS]

    def _end_stale(self, stale):
        for session in stale:
            self.end(session, 4404, "nobody opened the screen")

    def open(self, runner_id, actor, control, width, height):
        ticket = secrets.token_urlsafe(32)
        with self.lock:
            stale = self._sweep()
            live = [s for s in self.sessions.values() if s.runner_id == runner_id and not s.closed and s not in stale]
            if len(live) >= MAX_SESSIONS:
                raise Problem("screen_busy", "This computer's screen is open %d times already. Close one first."
                              % MAX_SESSIONS, 429)
            session = Session(runner_id, actor, control, _digest(ticket), width, height)
            self.sessions[session.id] = session
        self._end_stale(stale)
        return session, ticket

    def redeem(self, runner_id, ticket, loop):
        """The session a browser's ticket opens, once."""
        with self.lock:
            stale = self._sweep()
            wanted = _digest(ticket) if ticket else None
            session = next((s for s in self.sessions.values() if s.ticket_hash == wanted), None)
            if (session is None or session in stale or session.redeemed or session.closed
                    or session.runner_id != runner_id):
                session = None
            else:
                session.redeemed, session.started = True, time.monotonic()
                session.loop = session.loop or loop
        self._end_stale(stale)
        return session

    def attach(self, runner_id, session_id, loop):
        """The session a computer's websocket answers, once."""
        with self.lock:
            session = self.sessions.get(session_id)
            if session is None or session.closed or session.runner is not None or session.runner_id != runner_id:
                return None
            session.runner = True                # claimed; the socket replaces it once accepted
            session.loop = session.loop or loop
            return session

    def pending(self, runner_id):
        with self.lock:
            stale = self._sweep()
            found = [{"session_id": s.id, "control": s.control} for s in self.sessions.values()
                     if s.runner_id == runner_id and not s.closed and s.runner is None and s not in stale]
        self._end_stale(stale)
        return found

    def end(self, session, code, reason):
        """Close a session once, from the server's loop or a request thread; its sockets close with `code`."""
        with self.lock:
            if session.closed:
                return False
            session.closed, session.code, session.reason = True, code, reason
            self.sessions.pop(session.id, None)
            loop = session.loop
        if loop is not None:
            loop.call_soon_threadsafe(session.ended.set)
        try:
            running = asyncio.get_running_loop()
        except RuntimeError:
            running = None
        if running is not None:
            running.run_in_executor(None, self.audit_close, session)
        else:
            self.audit_close(session)
        return True

    def close_where(self, runner_id, code, reason, control_only=False):
        with self.lock:
            found = [s for s in self.sessions.values()
                     if s.runner_id == runner_id and not s.closed and (s.control or not control_only)]
        for session in found:
            self.end(session, code, reason)
        return len(found)

    def audit_close(self, session):
        seconds = int(time.monotonic() - session.started) if session.started else 0
        try:
            with self.store.transaction() as c:
                H.event(c, session.actor, "runner.screen_close", session.runner_id,
                        {"session_id": session.id, "control": session.control, "seconds": seconds,
                         "code": session.code})
        except Exception:                       # an audit write never keeps a socket open
            log.exception("screen session close audit failed")


def registry(store):
    existing = getattr(store, "screen_sessions", None)
    if existing is None:
        existing = store.screen_sessions = Registry(store)
    return existing


async def _close(socket, code, reason):
    if socket is None or socket is True:
        return
    try:
        await socket.close(code=code, reason=reason)
    except Exception:                           # the other side already went
        pass


async def _pump(source, target):
    """Frames from `source` to `target` until either side goes."""
    while True:
        message = await source.receive()
        if message["type"] == "websocket.disconnect":
            return
        if message.get("bytes") is not None:
            await target.send_bytes(message["bytes"])
        elif message.get("text") is not None:
            await target.send_text(message["text"])


async def _first(*events, timeout):
    """Wait for any of `events`; True unless the wait timed out."""
    waits = [asyncio.ensure_future(e.wait()) for e in events]
    try:
        done, _ = await asyncio.wait(waits, timeout=max(0.0, timeout), return_when=asyncio.FIRST_COMPLETED)
        return bool(done)
    finally:
        for wait in waits:
            wait.cancel()


async def _relay(sessions, session):
    tasks = [asyncio.ensure_future(_pump(session.browser, session.runner)),
             asyncio.ensure_future(_pump(session.runner, session.browser)),
             asyncio.ensure_future(session.ended.wait())]
    try:
        done, _ = await asyncio.wait(tasks, timeout=max(0.0, MAX_SECONDS - (time.monotonic() - session.started)),
                                     return_when=asyncio.FIRST_COMPLETED)
    finally:
        for task in tasks:
            task.cancel()
    if not done:
        sessions.end(session, 4408, "time limit")
    else:
        sessions.end(session, 1000, "")         # either side closing closes the other


def install(app, store, auth, mutate, execution, settings):
    from . import models as M
    from .views import human_only
    sessions = registry(store)

    def computer(c, rid):
        return c.execute("SELECT * FROM runners WHERE id=? AND revoked_at IS NULL", (rid,)).fetchone()

    @app.post("/api/v2/runners/{rid}/screen")
    def screen_mode(request: Request, rid: str, body: M.ScreenMode):
        """Who may open this computer's screen from the app: off, view, or control. The computer's operator or an
        admin; a mode other than off needs the screen turned on on the computer. Off closes open sessions, view
        closes the ones in control."""
        who = request.state.identity

        def work(c):
            runner = computer(c, rid)
            if not may_change(auth, who, runner):
                raise Problem("forbidden", "You cannot change this computer", 403)
            if body.mode != "off" and not available(runner):
                raise Problem("screen_unavailable", UNAVAILABLE, 409)
            c.execute("UPDATE runners SET screen=? WHERE id=?", (body.mode, rid))
            H.event(c, who.actor, "runner.screen", rid, {"mode": body.mode})
            return {"screen": body.mode, "screen_available": available(runner)}
        result = mutate(request, body, work)
        if result["screen"] != "control":
            sessions.close_where(rid, 4403, "screen turned off" if result["screen"] == "off" else "view only now",
                                 control_only=result["screen"] == "view")
        return result

    @app.post("/api/v2/runners/{rid}/screen/sessions")
    def open_screen(request: Request, rid: str, body: M.ScreenSessionStart):
        """Open the computer's screen: a single-use ticket for the browser's websocket at `ws_path`, good for a
        minute. The computer's operator or an admin, in person."""
        who = request.state.identity
        human_only(who)
        if who.via:
            raise Problem("forbidden", "Open the screen yourself in the app", 403)
        with store.read() as c:
            runner = computer(c, rid)
            if not may_change(auth, who, runner):
                raise Problem("forbidden", "You cannot open this computer's screen", 403)
            mode = runner["screen"] if runner["screen"] in MODES else "off"
            if mode == "off":
                raise Problem("screen_off", "This computer's screen is off. Turn it on in Settings > Computers.", 403)
            if not available(runner):
                raise Problem("screen_unavailable", UNAVAILABLE, 409)
            if body.control and mode != "control":
                raise Problem("screen_view_only", "This computer's screen is view only", 403)
            width, height = size(runner)
        session, ticket = sessions.open(rid, who.actor, body.control, width, height)

        def work(c):
            H.event(c, who.actor, "runner.screen_open", rid, {"session_id": session.id, "control": body.control})
            # A `runner` change row is the runner's `screen_open` event (backend/events.py runner_read).
            c.execute("INSERT INTO changes(topic,kind,subject_id,ref,at) VALUES('runner','screen_open',?,?,?)",
                      (rid, session.id, H.now()))
            return session.id
        try:
            store.write(who, work)              # never `mutate`: its replay record would keep the ticket
        except Exception:
            with sessions.lock:
                session.closed = True
                sessions.sessions.pop(session.id, None)
            raise
        return {"session_id": session.id, "ticket": ticket, "control": body.control,
                "ws_path": f"/api/v2/runners/{rid}/screen/ws?ticket={ticket}",
                "width": width, "height": height}

    @app.get("/api/v2/runners/me/screen/sessions")
    def pending_screens(request: Request):
        """The screen sessions waiting for this computer to answer: the backup for a missed `screen_open` event."""
        who = request.state.identity
        with store.read() as c:
            runner = execution.runner(c, who)
            if not runner:
                raise Problem("forbidden", "This computer is no longer registered", 403)
        return {"sessions": sessions.pending(who.runner_id)}

    @app.websocket("/api/v2/runners/{rid}/screen/ws")
    async def browser_socket(websocket: WebSocket, rid: str, ticket: str = ""):
        # The ticket is the only credential; a page on another site never holds one, and its origin is refused too.
        origin = websocket.headers.get("origin")
        if origin and not settings.allows_origin(origin):
            await websocket.close(code=4403)
            return
        session = sessions.redeem(rid, ticket, asyncio.get_running_loop())
        if session is None:
            await websocket.close(code=4401)
            return
        offered = websocket.scope.get("subprotocols") or []
        await websocket.accept(subprotocol="binary" if "binary" in offered else None)
        session.browser = websocket
        session.browser_in.set()
        try:
            if not session.runner_in.is_set():
                if not await _first(session.runner_in, session.ended, timeout=ANSWER_SECONDS):
                    sessions.end(session, 4404, "computer did not answer")
            if not session.closed:
                await _relay(sessions, session)
        finally:
            sessions.end(session, 1000, "")
            await _close(websocket, session.code, session.reason)

    @app.websocket("/api/v2/runners/me/screen/{session_id}/ws")
    async def runner_socket(websocket: WebSocket, session_id: str):
        path = websocket.url.path

        def identify():
            who = auth.authenticate(websocket.headers, path, "GET")
            with store.read() as c:
                if who.role != "runner" or not execution.runner(c, who):
                    raise Problem("forbidden", "A registered computer is required", 403)
            return who
        try:
            who = await asyncio.get_running_loop().run_in_executor(None, identify)
        except Problem:
            await websocket.close(code=4401)
            return
        session = sessions.attach(who.runner_id, session_id, asyncio.get_running_loop())
        if session is None:
            await websocket.close(code=4404)
            return
        await websocket.accept()
        session.runner = websocket
        session.runner_in.set()
        try:
            if not session.browser_in.is_set():
                left = TICKET_SECONDS - (time.monotonic() - session.created)
                if not await _first(session.browser_in, session.ended, timeout=left):
                    sessions.end(session, 4404, "nobody opened the screen")
            await session.ended.wait()
        finally:
            sessions.end(session, 1000, "")
            await _close(websocket, session.code, session.reason)

    return sessions
