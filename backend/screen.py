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
ANSWER_SECONDS = 30         # the runner connects within this once the browser has (its backup poll is 10 s)
BACKLOG_BYTES = 1 << 20     # what a computer may send before the browser comes
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
        self.backlog = []                       # what the computer sent before the browser came
        # runner_in: the computer's socket is there and nothing else reads it, so the relay may.
        self.browser_in, self.runner_in, self.ended = asyncio.Event(), asyncio.Event(), asyncio.Event()


def _allows(mode, control):
    return mode == "control" or mode == "view" and not control


class Registry:
    """Admission, mode changes and revocation all hold `lock`, so no session outlives the mode that let it in."""

    def __init__(self, store):
        self.store = store
        self.lock = threading.Lock()
        self.sessions = {}
        self.modes = {}                         # runner id -> the mode last set in this process ("off" once revoked)

    def _stale(self):
        """Sessions whose browser never came within the ticket's minute. Called under the lock."""
        now = time.monotonic()
        return [s for s in self.sessions.values() if not s.redeemed and now - s.created > TICKET_SECONDS]

    def _mark(self, session, code, reason):
        """Close `session` in the registry; under the lock. True when this call closed it."""
        if session.closed:
            return False
        session.closed, session.code, session.reason = True, code, reason
        self.sessions.pop(session.id, None)
        return True

    def _after(self, sessions):
        """Outside the lock: wake the closed sessions' sockets, and record each close."""
        try:
            running = asyncio.get_running_loop()
        except RuntimeError:
            running = None
        for session in sessions:
            if session.loop is not None:
                session.loop.call_soon_threadsafe(session.ended.set)
            if running is not None:
                running.run_in_executor(None, self.audit_close, session)
            else:
                self.audit_close(session)

    def _sweep(self):
        """Close the stale sessions; under the lock. Returns them for `_after`."""
        stale = self._stale()
        for session in stale:
            self._mark(session, 4404, "nobody opened the screen")
        return stale

    def admit(self, runner_id, actor, control, width, height, mode):
        """A new session, visible to the computer at once. `mode` was read inside the same write transaction a mode
        change or revocation takes, and the registry's own record of the mode is checked under the lock too."""
        ticket = secrets.token_urlsafe(32)
        with self.lock:
            stale = self._sweep()
            if not (_allows(mode, control) and _allows(self.modes.get(runner_id, mode), control)):
                session = None
            elif sum(s.runner_id == runner_id for s in self.sessions.values()) >= MAX_SESSIONS:
                session = False
            else:
                session = Session(runner_id, actor, control, _digest(ticket), width, height)
                self.sessions[session.id] = session
        self._after(stale)
        if session is None:
            raise Problem("screen_off", "This computer's screen is off or view only now", 403)
        if session is False:
            raise Problem("screen_busy", "This computer's screen is open %d times already. Close one first."
                          % MAX_SESSIONS, 429)
        return session, ticket

    def set_mode(self, runner_id, mode, reason):
        """Record a computer's new mode and close, under the same lock, every session it no longer allows."""
        with self.lock:
            self.modes[runner_id] = mode
            found = [s for s in list(self.sessions.values())
                     if s.runner_id == runner_id and not _allows(mode, s.control) and self._mark(s, 4403, reason)]
        self._after(found)
        return len(found)

    def redeem(self, runner_id, ticket, loop):
        """The session a browser's ticket opens, once."""
        with self.lock:
            stale = self._sweep()
            wanted = _digest(ticket) if ticket else None
            session = next((s for s in self.sessions.values() if s.ticket_hash == wanted), None)
            if (session is None or session.redeemed or session.closed or session.runner_id != runner_id
                    or not _allows(self.modes.get(runner_id, "control"), session.control)):
                session = None
            else:
                session.redeemed, session.started = True, time.monotonic()
                session.loop = session.loop or loop
        self._after(stale)
        return session

    def attach(self, runner_id, session_id, loop):
        """The session a computer's websocket answers, once."""
        with self.lock:
            session = self.sessions.get(session_id)
            if (session is None or session.closed or session.runner is not None or session.runner_id != runner_id
                    or not _allows(self.modes.get(runner_id, "control"), session.control)):
                return None
            session.runner = True                # claimed; the socket replaces it once accepted
            session.loop = session.loop or loop
            return session

    def pending(self, runner_id):
        with self.lock:
            stale = self._sweep()
            found = [{"session_id": s.id, "control": s.control} for s in self.sessions.values()
                     if s.runner_id == runner_id and s.runner is None]
        self._after(stale)
        return found

    def end(self, session, code, reason):
        """Close a session once, from the server's loop or a request thread; its sockets close with `code`."""
        with self.lock:
            closed = self._mark(session, code, reason)
        if closed:
            self._after([session])
        return closed

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


async def _send(target, message):
    if message.get("bytes") is not None:
        await target.send_bytes(message["bytes"])
    elif message.get("text") is not None:
        await target.send_text(message["text"])


async def _pump(source, target):
    """Frames from `source` to `target` until either side goes."""
    while True:
        message = await source.receive()
        if message["type"] == "websocket.disconnect":
            return
        await _send(target, message)


async def _first(*events, timeout):
    """Wait for any of `events`; True unless the wait timed out."""
    waits = [asyncio.ensure_future(e.wait()) for e in events]
    try:
        done, _ = await asyncio.wait(waits, timeout=max(0.0, timeout), return_when=asyncio.FIRST_COMPLETED)
        return bool(done)
    finally:
        for wait in waits:
            wait.cancel()


async def _hold(sessions, session, socket):
    """Until the browser comes: keep what the computer sends (its VNC greeting) and notice it going."""
    held = 0
    while not session.browser_in.is_set() and not session.closed:
        receive = asyncio.ensure_future(socket.receive())
        others = [asyncio.ensure_future(session.browser_in.wait()), asyncio.ensure_future(session.ended.wait())]
        left = TICKET_SECONDS - (time.monotonic() - session.created)
        await asyncio.wait([receive, *others], timeout=max(0.0, left), return_when=asyncio.FIRST_COMPLETED)
        for wait in others:
            wait.cancel()
        if not receive.done():
            receive.cancel()
            await asyncio.gather(receive, return_exceptions=True)   # finished before the relay reads the socket
            if not session.browser_in.is_set() and not session.ended.is_set():
                sessions.end(session, 4404, "nobody opened the screen")
            continue
        message = receive.result()
        if message["type"] == "websocket.disconnect":
            sessions.end(session, 1000, "computer closed")
            return
        held += len(message.get("bytes") or b"") + len(message.get("text") or "")
        if held > BACKLOG_BYTES:
            sessions.end(session, 1011, "computer sent too much before the browser came")
            return
        session.backlog.append(message)


async def _relay(sessions, session):
    for message in session.backlog:
        await _send(session.browser, message)
    session.backlog = []
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
        # The mode now stored, not this request's (a replayed older request must not reopen anything).
        with store.read() as c:
            row = c.execute("SELECT screen,revoked_at FROM runners WHERE id=?", (rid,)).fetchone()
        mode = row["screen"] if row and not row["revoked_at"] and row["screen"] in MODES else "off"
        sessions.set_mode(rid, mode, "screen turned off" if mode == "off" else "view only now")
        return result

    @app.post("/api/v2/runners/{rid}/screen/sessions")
    def open_screen(request: Request, rid: str, body: M.ScreenSessionStart):
        """Open the computer's screen: a single-use ticket for the browser's websocket at `ws_path`, good for a
        minute. The computer's operator or an admin, in person: not the Assistant, BotOps or a personal token."""
        who = request.state.identity
        human_only(who)
        if who.via or who.via_token:
            raise Problem("forbidden", "Open the screen yourself in the app", 403)
        admitted = []

        def work(c):
            # Inside the write lock a mode change and a revocation take, so neither can pass this check unseen.
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
            session, ticket = sessions.admit(rid, who.actor, body.control, width, height, mode)
            admitted.append(session)
            H.event(c, who.actor, "runner.screen_open", rid, {"session_id": session.id, "control": body.control})
            # A `runner` change row is the runner's `screen_open` event (backend/events.py runner_read).
            c.execute("INSERT INTO changes(topic,kind,subject_id,ref,at) VALUES('runner','screen_open',?,?,?)",
                      (rid, session.id, H.now()))
            return {"session_id": session.id, "ticket": ticket, "control": body.control,
                    "ws_path": f"/api/v2/runners/{rid}/screen/ws?ticket={ticket}",
                    "width": width, "height": height}
        try:
            return store.write(who, work)       # never `mutate`: its replay record would keep the ticket
        except Exception:
            for session in admitted:            # the write failed after admission: close it, waking any socket
                sessions.end(session, 1011, "could not open the screen")
            raise

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
        try:
            await _hold(sessions, session, websocket)
            if not session.closed:
                session.runner_in.set()         # the relay reads this socket from here on
            await session.ended.wait()
        finally:
            sessions.end(session, 1000, "")
            await _close(websocket, session.code, session.reason)

    return sessions
