"""Gemini CLI stream-json host.

Gemini CLI has no daemon protocol, so each turn is one headless ``gemini -p`` process. The
host chooses a session id for the first turn and resumes it on later turns. A dedicated
``GEMINI_CLI_HOME`` keeps BotOps sessions and its API-key auth separate from the operator's
interactive Gemini login.
"""

import json
import os
import subprocess
import tempfile
import threading
import uuid
from pathlib import Path

from .. import isolation
from .base import Host, HostError, is_limit


STREAM_ARGS = ["--output-format", "stream-json", "--approval-mode", "yolo", "--skip-trust"]
EFFORTS = {"low": "LOW", "medium": "MEDIUM", "high": "HIGH"}
DEFAULT_MODEL = "gemini-3.8-flash"
STOP_TIMEOUT_S = 10
STDERR_TAIL = 2000


def effort_for(effort):
    return EFFORTS.get(str(effort or "").strip().lower(), "HIGH")


def usage_tokens(stats):
    value = stats if isinstance(stats, dict) else {}

    def count(key):
        try:
            return int(value.get(key) or 0)
        except (TypeError, ValueError):
            return 0

    inp, out = count("input_tokens"), count("output_tokens")
    return inp, out, count("total_tokens") or inp + out


class GeminiHost(Host):
    name = "gemini"
    supports_steer = False

    def __init__(self, bot=None, home=None, cmd=("gemini",), log=None, stderr_path=None,
                 spawn=None):
        super().__init__(log=log)
        self.bot = bot
        self.home = Path(home) if home else Path.home() / ".config" / "tico" / "gemini" / str(bot or "bot")
        self.cmd = list(cmd)
        self.stderr_path = stderr_path
        self._spawn = spawn or isolation.popen
        self._up = False
        self.proc = None
        self._reader = None
        self._threads = {}
        self._turn = None
        self._reply = {}
        self._interrupted = set()
        self._done_turns = set()

    # ------------------------------------------------------------------ process
    def start(self):
        self._up = True

    def stop(self):
        with self._lock:
            self._up = False
            proc, self.proc = self.proc, None
            running = self._turn
        if proc:
            if running:
                self._interrupted.add(running[1])
            self._end(proc)
        reader = self._reader
        if reader and reader is not threading.current_thread():
            reader.join(timeout=STOP_TIMEOUT_S)

    def alive(self):
        return self._up

    @staticmethod
    def _end(proc):
        try:
            proc.terminate()
            proc.wait(timeout=STOP_TIMEOUT_S)
        except Exception:
            try:
                proc.kill()
            except Exception:
                pass

    # ------------------------------------------------------------------ threads
    def _record(self, thread_id, bot, settings, started):
        self._threads[thread_id] = {"bot": bot, "settings": dict(settings), "started": started}
        return thread_id

    def start_thread(self, bot, settings):
        return self._record(str(uuid.uuid4()), bot, settings, started=False)

    def resume_thread(self, bot, thread_id, settings):
        return self._record(thread_id, bot, settings, started=True)

    def fork_thread(self, bot, thread_id, settings):
        # Gemini CLI does not expose session forking. Recovery therefore starts a clean session.
        return self.start_thread(bot, settings)

    def _argv(self, thread_id, thread):
        model = str(thread["settings"].get("model") or DEFAULT_MODEL)
        argv = self.cmd + ["--model", model] + STREAM_ARGS
        if thread["started"]:
            argv += ["--resume", thread_id]
        else:
            argv += ["--session-id", thread_id]
        # Keep the prompt out of the process list. In headless mode -p appends stdin.
        return argv + ["-p", ""]

    def _settings(self, model, effort):
        return {
            "experimental": {"dynamicModelConfiguration": True},
            "security": {"auth": {"selectedType": "gemini-api-key",
                                    "enforcedType": "gemini-api-key"}},
            "modelConfigs": {"customOverrides": [{
                "match": {"model": model},
                "modelConfig": {"generateContentConfig": {
                    "thinkingConfig": {"thinkingLevel": effort_for(effort)}}},
            }]},
        }

    def _prepare_home(self, model, effort):
        isolation.mkdir(self.home)
        os.chmod(self.home, 0o700)
        fd, temporary = tempfile.mkstemp(prefix="settings-", suffix=".json", dir=self.home)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as stream:
                json.dump(self._settings(model, effort), stream, indent=2)
                stream.write("\n")
            os.chmod(temporary, 0o600)
            os.replace(temporary, self.home / "settings.json")
            isolation.chown(self.home / "settings.json")
        finally:
            try:
                os.unlink(temporary)
            except FileNotFoundError:
                pass

    def _env(self, settings):
        env = dict(settings["env"]) if "env" in settings else dict(os.environ)
        if not env.get("HOME") and os.environ.get("HOME"):
            env["HOME"] = os.environ["HOME"]
        env["GEMINI_CLI_HOME"] = str(self.home)
        env["GEMINI_CLI_SYSTEM_SETTINGS_PATH"] = str(self.home / "settings.json")
        env["GEMINI_CLI_TRUST_WORKSPACE"] = "true"
        return env

    # ------------------------------------------------------------------ turns
    def start_turn(self, thread_id, text, effort=None):
        with self._lock:
            if not self._up:
                raise HostError("gemini host is not running")
            if self._turn:
                raise HostError("gemini host already has a turn running")
            thread = self._threads.get(thread_id)
            if thread is None:
                raise HostError(f"unknown gemini thread {thread_id}")
            settings = thread["settings"]
            model = str(settings.get("model") or DEFAULT_MODEL)
            if not self._env(settings).get("GEMINI_API_KEY"):
                raise HostError("Gemini API key is not configured for this bot")
            self._prepare_home(model, effort or settings.get("effort"))
            turn = str(uuid.uuid4())
            stderr = tempfile.TemporaryFile("w+", encoding="utf-8", errors="replace")
            try:
                proc = self._spawn(self._argv(thread_id, thread), stdin=subprocess.PIPE,
                                   stdout=subprocess.PIPE, stderr=stderr, cwd=settings["cwd"],
                                   env=self._env(settings), text=True, bufsize=1)
            except OSError as exc:
                stderr.close()
                raise HostError(f"could not start gemini: {exc}")
            self.proc = proc
            self._turn = (thread_id, turn)
            self._reply[turn] = ""
        self._log(f"gemini[{self.bot}]: turn started pid {getattr(proc, 'pid', '?')}")
        self.emit("status", thread_id, None, state="active")
        threading.Thread(target=self._feed, args=(proc, text), daemon=True).start()
        self._reader = threading.Thread(target=self._read_loop,
                                        args=(proc, thread_id, turn, stderr, text), daemon=True)
        self._reader.start()
        return turn

    @staticmethod
    def _feed(proc, text):
        try:
            proc.stdin.write(text)
            proc.stdin.close()
        except (BrokenPipeError, ValueError, OSError):
            pass

    def _read_loop(self, proc, thread_id, turn, stderr, text, recovered=False):
        result = None
        saw_event = False
        try:
            for line in proc.stdout:
                try:
                    message = json.loads(line.strip())
                except (TypeError, ValueError):
                    continue
                saw_event = True
                try:
                    if self._on_message(message, thread_id, turn):
                        result = message
                except Exception as exc:
                    self._log(f"gemini[{self.bot}]: event error {exc}")
        except (ValueError, OSError):
            pass
        try:
            returncode = proc.wait()
        except Exception:
            returncode = -1
        error = self._stderr_tail(stderr)
        # The CLI validates --resume before invoking the model. A missing session
        # can therefore restart once using the same conversation's supplied history,
        # without replaying any tool effects. Never retry a failure after an event.
        missing = f'Error resuming session: Invalid session identifier "{thread_id}".'
        with self._lock:
            thread = self._threads.get(thread_id)
            if (not recovered and not saw_event and returncode and error.startswith(missing)
                    and thread and thread["started"] and self._up
                    and turn not in self._interrupted):
                thread["started"] = False
                retry_stderr = tempfile.TemporaryFile("w+", encoding="utf-8", errors="replace")
                try:
                    settings = thread["settings"]
                    retry = self._spawn(self._argv(thread_id, thread), stdin=subprocess.PIPE,
                                        stdout=subprocess.PIPE, stderr=retry_stderr,
                                        cwd=settings["cwd"], env=self._env(settings), text=True, bufsize=1)
                except OSError:
                    retry_stderr.close()
                else:
                    self.proc = retry
                    self.emit("diagnostic", thread_id, turn,
                              text="Saved provider session is unavailable; restoring this conversation's context.")
                    threading.Thread(target=self._feed, args=(retry, text), daemon=True).start()
                    self._reader = threading.Thread(target=self._read_loop,
                        args=(retry, thread_id, turn, retry_stderr, text, True), daemon=True)
                    self._reader.start()
                    return
        self._finish(thread_id, turn, result, returncode, error)

    def _stderr_tail(self, stderr):
        try:
            stderr.seek(0)
            value = stderr.read()
        except (OSError, ValueError):
            value = ""
        finally:
            try:
                stderr.close()
            except OSError:
                pass
        if value and self.stderr_path:
            try:
                with open(self.stderr_path, "a", encoding="utf-8") as stream:
                    stream.write(value if value.endswith("\n") else value + "\n")
            except OSError:
                pass
        return value.strip()[-STDERR_TAIL:]

    def _on_message(self, message, thread_id, turn):
        if not isinstance(message, dict):
            return False
        kind = message.get("type")
        if kind == "init":
            thread = self._threads.get(thread_id)
            if thread:
                thread["started"] = True
        elif kind == "message" and message.get("role") == "assistant":
            text = str(message.get("content") or "")
            if text:
                if message.get("delta", True):
                    self._reply[turn] += text
                    self.emit("delta", thread_id, turn, text=text, delta_kind="text")
                else:
                    self._reply[turn] = text
                    self.emit("message", thread_id, turn, text=text, final=False)
        elif kind == "tool_use":
            self.emit("tool", thread_id, turn, server="", tool=message.get("tool_name") or
                      message.get("name") or "tool", status="started",
                      item_id=message.get("tool_id") or message.get("id"))
        elif kind == "tool_result":
            self.emit("tool", thread_id, turn, server="", tool=message.get("tool_name") or
                      message.get("name") or "tool",
                      status="failed" if message.get("status") == "error" else "completed",
                      item_id=message.get("tool_id") or message.get("id"))
        elif kind == "result":
            return True
        return False

    def _finish(self, thread_id, turn, result, returncode, stderr):
        with self._lock:
            if self._turn and self._turn[1] == turn:
                self._turn = None
                self.proc = None
            interrupted = turn in self._interrupted
        reply = self._reply.pop(turn, "")
        if turn in self._done_turns:
            return
        self._done_turns.add(turn)
        result = result if isinstance(result, dict) else None
        requested = str((self._threads.get(thread_id) or {}).get("settings", {}).get("model") or
                        DEFAULT_MODEL)
        actual_models = set((result or {}).get("stats", {}).get("models") or {})
        model_mismatch = bool(actual_models and requested not in actual_models)
        if result:
            inp, out, total = usage_tokens(result.get("stats"))
            if total:
                stats = result.get("stats") if isinstance(result.get("stats"), dict) else {}
                try:
                    cached = int(stats.get("cached") or 0)
                except (TypeError, ValueError):
                    cached = 0
                self.emit("tokens", thread_id, turn, input=inp, output=out, total=total,
                          usage={"input": inp, "cached": cached, "output": out})
        if interrupted:
            self.emit("turn_completed", thread_id, turn, status="interrupted")
        elif result and result.get("status") == "success" and returncode == 0 and not model_mismatch:
            if reply:
                self.emit("message", thread_id, turn, text=reply, final=True)
            self.emit("turn_completed", thread_id, turn, status="completed")
        else:
            error = (f"Gemini CLI used {', '.join(sorted(actual_models))} instead of {requested}"
                     if model_mismatch else self._error_text(result, returncode, stderr))
            self.emit("turn_failed", thread_id, turn, error=error, limit=is_limit(error))
        self.emit("status", thread_id, None, state="idle")

    @staticmethod
    def _error_text(result, returncode, stderr):
        if result:
            error = result.get("error")
            if isinstance(error, dict):
                error = error.get("message") or error.get("type")
            if error:
                return str(error)
            if result.get("status") and result.get("status") != "success":
                return str(result["status"])
        return stderr or f"gemini exited {returncode}"

    def steer(self, thread_id, turn_id, text):
        raise HostError("Gemini runtime cannot steer a running turn")

    def interrupt(self, thread_id, turn_id):
        with self._lock:
            proc, running = self.proc, self._turn
            if not proc or not running or running[1] != turn_id:
                return
            self._interrupted.add(turn_id)
        self._end(proc)

    def active_turn(self, thread_id):
        running = self._turn
        return running[1] if running and running[0] == thread_id else None
