"""Persistent Antigravity NDJSON driver, isolated to one Hub conversation.

The real provider conversation ID is saved separately from the stable host thread
ID. A failed/ interrupted turn is never replayed automatically.
"""
import json
import os
import signal
import subprocess
import threading
import uuid
from pathlib import Path

from .base import Host, HostError, is_limit


class AntigravityHost(Host):
    name = "antigravity"
    supports_steer = False

    def __init__(self, home, cmd=("agy",), spawn=None, log=None):
        super().__init__(log)
        self.home = Path(home)
        self.cmd = list(cmd)
        self._spawn = spawn or subprocess.Popen
        self._up = False
        self.proc = None
        self._reader = None
        self._thread = None
        self._turn = None
        self._settings = None
        self._provider_id = None
        self._usage = {}

    def start(self):
        self.home.mkdir(parents=True, exist_ok=True, mode=0o700)
        os.chmod(self.home, 0o700)
        self._up = True

    def alive(self):
        return self._up and (self.proc is None or self.proc.poll() is None)

    def _path(self, tid):
        return self.home / (str(uuid.UUID(tid)) + ".json")

    def start_thread(self, bot, settings):
        self._thread, self._settings = str(uuid.uuid4()), dict(settings)
        self._provider_id = None
        return self._thread

    def resume_thread(self, bot, thread_id, settings):
        if self._thread == thread_id and self.alive():
            return thread_id
        try:
            record = json.loads(self._path(thread_id).read_text())
            self._provider_id = str(uuid.UUID(record["conversation_id"]))
        except (OSError, ValueError, KeyError, TypeError) as exc:
            raise HostError("Antigravity conversation is unavailable") from exc
        self._thread, self._settings = thread_id, dict(settings)
        return thread_id

    def fork_thread(self, bot, thread_id, settings):
        return self.start_thread(bot, settings)

    def _remember(self, cid):
        cid = str(uuid.UUID(cid))
        if self._provider_id == cid:
            return
        if self._provider_id:
            raise HostError("Antigravity resumed the wrong conversation")
        self._provider_id = cid
        path = self._path(self._thread)
        temporary = path.with_suffix(".tmp")
        fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w") as output:
            json.dump({"conversation_id": cid}, output)
        os.replace(temporary, path)

    def start_turn(self, thread_id, text, effort=None):
        with self._lock:
            if not self.alive() or thread_id != self._thread or self._turn:
                raise HostError("Antigravity is unavailable or already running a turn")
            turn = self._turn = str(uuid.uuid4())
            try:
                if self.proc is None:
                    settings = self._settings
                    model = str(settings.get("model") or "gemini-3.8-flash")
                    effort = effort or settings.get("effort") or "low"
                    if effort not in ("low", "medium", "high"):
                        raise HostError("Unsupported Antigravity effort")
                    argv = self.cmd + ["--input-format", "stream-json", "--output-format", "stream-json",
                                       "--model", model + "-" + effort, "--effort", effort,
                                       "--dangerously-skip-permissions"]
                    if self._provider_id:
                        argv += ["--conversation", self._provider_id]
                    self.proc = self._spawn(argv, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                            stderr=subprocess.DEVNULL, text=True, bufsize=1,
                                            cwd=settings["cwd"], env=settings["env"], start_new_session=True)
                    self._reader = threading.Thread(target=self._read, daemon=True)
                    self._reader.start()
                self.proc.stdin.write(json.dumps({"event": "user", "message": {"content": text}}) + "\n")
                self.proc.stdin.flush()
            except Exception:
                self._turn = None
                raise
            self.emit("status", thread_id, turn, state="active")
            return turn

    def _read(self):
        try:
            for line in self.proc.stdout:
                event = json.loads(line)
                with self._lock:
                    tid, turn = self._thread, self._turn
                    if not self._up:
                        return
                    if event.get("event") == "init":
                        cid = event.get("conversation_id") or event.get("init", {}).get("conversation_id")
                        if cid:
                            self._remember(cid)
                    step = event.get("step_update") or {}
                    if step.get("conversation_id"):
                        self._remember(step["conversation_id"])
                    if not turn:
                        continue
                    if step.get("step_type") == "agent_response" and step.get("text_delta"):
                        self.emit("delta", tid, turn, text=step["text_delta"], delta_kind="text")
                    if step.get("step_type") == "tool":
                        self.emit("tool", tid, turn, tool=step.get("tool_name", "tool"), state=step.get("state"))
                    if event.get("event") != "result":
                        continue
                    result = event["result"]
                    if result.get("conversation_id"):
                        self._remember(result["conversation_id"])
                    usage = result.get("usage") or {}
                    delta = {k: max(0, int(usage.get(k) or 0) - int(self._usage.get(k) or 0))
                             for k in ("input_tokens", "output_tokens", "cache_read_tokens")}
                    self._usage = usage
                    self.emit("tokens", tid, turn, input=delta["input_tokens"], output=delta["output_tokens"],
                              cached=delta["cache_read_tokens"], total=delta["input_tokens"] + delta["output_tokens"])
                    self._turn = None
                    if result.get("status") == "SUCCESS":
                        self.emit("message", tid, turn, text=result.get("response", "").strip(), final=True)
                        self.emit("turn_completed", tid, turn, status="completed")
                    else:
                        error = str(result.get("error") or result.get("status") or "Antigravity failed")
                        self.emit("turn_failed", tid, turn, error=error, limit=is_limit(error))
                    self.emit("status", tid, turn, state="idle")
        except Exception as exc:
            self._log("Antigravity stream failed: " + type(exc).__name__)
        finally:
            with self._lock:
                if self._up and self._turn:
                    self.emit("turn_failed", self._thread, self._turn, error="Antigravity stream ended before a result", limit=False)
                self._turn = None
                self._up = False

    def steer(self, thread_id, turn_id, text):
        raise HostError("Antigravity steering is not enabled")

    def interrupt(self, thread_id, turn_id):
        self.stop()

    def stop(self):
        with self._lock:
            self._up = False
            proc = self.proc
        if proc and proc.poll() is None:
            try:
                os.killpg(proc.pid, signal.SIGTERM)
                proc.wait(timeout=5)
            except (OSError, subprocess.TimeoutExpired):
                try:
                    os.killpg(proc.pid, signal.SIGKILL)
                    proc.wait(timeout=5)
                except (OSError, subprocess.TimeoutExpired):
                    pass
        if self._reader and self._reader is not threading.current_thread():
            self._reader.join(timeout=2)
