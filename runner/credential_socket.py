"""A bot's GitHub token, from the supervisor, without the runner's registration.

git's credential helper runs inside a turn, as the turn's user, which must not be able to read
runner.json (runner/isolation.py). So the supervisor listens on a Unix socket and the helper
asks it: it sends the turn's attempt token, and gets a GitHub token for the bot that attempt
belongs to, minted with the runner's registration. The socket has no other question: it cannot
name a bot, so an attempt never gets another bot's token, an attempt that has ended gets nothing,
and the runner's own token never crosses it.

One JSON line each way: {"token": "<attempt token>"} then {"token": "<github token>"} or {"error": "..."}.
"""
import json
import os
import socket
import socketserver
import threading
from pathlib import Path

from .outage import log

SOCKET_ENV = "TICO_CRED_SOCKET"
DEFAULT_PATH = "/run/tico-runner/git-credential.sock"
MAX_LINE = 4096


class Server:
    """Serves `mint(bot)` to whoever presents the attempt token registered for that bot."""

    def __init__(self, path, mint):
        self.path, self.mint = str(path), mint
        self.attempts, self.lock = {}, threading.Lock()
        self.server = None

    def register(self, attempt_token, bot):
        with self.lock:
            self.attempts[attempt_token] = bot

    def unregister(self, attempt_token):
        with self.lock:
            self.attempts.pop(attempt_token, None)

    def answer(self, line):
        try:
            token = json.loads(line).get("token")
        except (ValueError, AttributeError):
            return {"error": "bad request"}
        with self.lock:
            bot = self.attempts.get(token) if isinstance(token, str) and token else None
        if not bot:
            return {"error": "unknown attempt"}
        try:
            granted = self.mint(bot)
        except Exception as exc:
            return {"error": type(exc).__name__}
        if not granted:
            return {"error": "no token"}
        return {"token": granted}

    def start(self):
        outer = self

        class Handler(socketserver.StreamRequestHandler):
            def handle(self):
                self.request.settimeout(20)
                try:
                    reply = outer.answer(self.rfile.readline(MAX_LINE))
                    self.wfile.write(json.dumps(reply).encode() + b"\n")
                except OSError:
                    pass

        class UnixServer(socketserver.ThreadingMixIn, socketserver.UnixStreamServer):
            daemon_threads = True

        path = Path(self.path)
        path.parent.mkdir(mode=0o755, parents=True, exist_ok=True)
        path.unlink(missing_ok=True)
        self.server = UnixServer(self.path, Handler)
        # Whoever holds an attempt token may ask; the file mode only keeps strangers' processes out.
        from . import isolation
        os.chmod(self.path, 0o600)
        isolation.chown(self.path)
        threading.Thread(target=self.server.serve_forever, name="credential-socket", daemon=True).start()
        return self

    def stop(self):
        if self.server:
            self.server.shutdown()
            self.server.server_close()
            Path(self.path).unlink(missing_ok=True)


def serve(client, path=None):
    """The supervisor's server when isolation is on (else None): `client` is the runner's own."""
    from . import isolation
    if not isolation.enabled():
        return None
    path = path or os.environ.get("TICO_RUNNER_CRED_SOCKET") or DEFAULT_PATH

    def mint(bot):
        granted = client.post("github/token", {"bot": bot})
        return granted.get("token") if granted.get("configured") else ""
    try:
        return Server(path, mint).start()
    except OSError as exc:
        log(f"Tico runner: no credential socket at {path} ({type(exc).__name__}); turns keep their start-of-turn token")
        return None


def request(path, attempt_token, timeout=20):
    """The GitHub token for the bot this attempt belongs to. Raises OSError/ValueError on failure."""
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as connection:
        connection.settimeout(timeout)
        connection.connect(str(path))
        connection.sendall(json.dumps({"token": attempt_token}).encode() + b"\n")
        line = connection.makefile("rb").readline(MAX_LINE)
    reply = json.loads(line)
    if not reply.get("token"):
        raise ValueError(reply.get("error") or "refused")
    return reply["token"]
