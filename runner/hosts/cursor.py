"""The Cursor agent host: one `cursor-agent -p --output-format stream-json` process per turn.

Verified against Cursor Agent 2026.09.28 (docs at cursor.com/docs/cli). A thread is a chat made
with `cursor-agent create-chat` (its id is the thread id, so a restart resumes it). The prompt goes
in on stdin (a long prompt would not fit an argument) and the workspace is the bot's repository:

    cursor-agent -p --output-format stream-json --force --trust --model auto
                 --resume <chat id> --workspace <repo>

Events are one JSON object per line: `system` (`init` carries the session id), `assistant` (a
complete message), `thinking`, `tool_call` (`started` / `completed`) and a final `result`
(`success`, or `is_error`). The CLI has no effort setting (it lives in the model name), no steering,
and no MCP here: the bot uses the hub CLI over bash. CURSOR_API_KEY, when set, signs it in without a
browser login; otherwise the login the person made with `cursor-agent login` is used.
"""

import json
import os
import re
import subprocess
import tempfile
import threading
import uuid

from .. import isolation
from .base import Host, HostError, is_limit

EXECUTABLE = "cursor-agent"
CHAT_ID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")
# Catalog id -> the CLI's own model id. Anything else the person names is passed through, so a
# model Cursor adds tomorrow works without a change here.
MODELS = {"cursor-auto": "auto"}
DEFAULT_MODEL = "auto"
STOP_TIMEOUT_S = 10
STDERR_TAIL = 2000


def model_for(model):
    value = str(model or "").strip()
    return DEFAULT_MODEL if not value or value == "default" else MODELS.get(value, value)


def usage_tokens(usage):
    """(input, output, total) from the `usage` object on a result event."""
    u = usage if isinstance(usage, dict) else {}

    def count(key):
        try:
            return int(u.get(key) or 0)
        except (TypeError, ValueError):
            return 0
    inp = count("inputTokens") + count("cacheReadTokens") + count("cacheWriteTokens")
    out = count("outputTokens")
    return inp, out, inp + out


def cached_tokens(usage):
    try:
        return int((usage if isinstance(usage, dict) else {}).get("cacheReadTokens") or 0)
    except (TypeError, ValueError):
        return 0


def message_text(message):
    content = (message or {}).get("content") if isinstance(message, dict) else None
    if isinstance(content, str):
        return content
    return "".join(block.get("text", "") for block in content or []
                   if isinstance(block, dict) and block.get("type") == "text")


class CursorHost(Host):
    name = "cursor"
    supports_steer = False

    def __init__(self, bot=None, cmd=(EXECUTABLE,), log=None, stderr_path=None, spawn=None, run=None):
        super().__init__(log=log)
        self._run = run or isolation.run
        self.bot = bot
        self.cmd = list(cmd)
        self.stderr_path = stderr_path
        self._spawn = spawn or isolation.popen
        self._up = False
        self.proc = None
        self._reader = None
        self._threads = {}            # thread id (the chat id) -> {"bot", "settings"}
        self._turn = None             # (thread id, turn id) while a process runs
        self._interrupted = set()
        self._done_turns = set()

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

    def _record(self, thread_id, bot, settings):
        self._threads[thread_id] = {"bot": bot, "settings": dict(settings)}
        return thread_id

    def _new_chat(self, settings):
        try:
            done = self._run(self.cmd + ["create-chat"], capture_output=True, text=True, timeout=30,
                             cwd=settings["cwd"], env=self._env(settings), stdin=subprocess.DEVNULL)
        except (OSError, subprocess.SubprocessError) as exc:
            raise HostError(f"could not start a cursor chat: {exc}")
        found = CHAT_ID.search(done.stdout or "")
        if done.returncode or not found:
            raise HostError("cursor-agent create-chat failed: " + ((done.stderr or done.stdout).strip()[-300:] or "no chat id"))
        return found.group(0)

    def start_thread(self, bot, settings):
        return self._record(self._new_chat(settings), bot, settings)

    def resume_thread(self, bot, thread_id, settings):
        return self._record(thread_id, bot, settings)

    def fork_thread(self, bot, thread_id, settings):
        # The CLI cannot copy a chat: a fork starts a fresh one.
        return self._record(self._new_chat(settings), bot, settings)

    def _argv(self, thread_id, t):
        settings = t["settings"]
        return self.cmd + ["-p", "--output-format", "stream-json", "--force", "--trust",
                           "--model", model_for(settings.get("model")), "--workspace", str(settings["cwd"]),
                           "--resume", thread_id]

    @staticmethod
    def _env(settings):
        env = dict(settings.get("env") or os.environ)
        if not env.get("HOME") and os.environ.get("HOME"):
            env["HOME"] = os.environ["HOME"]
        return env

    def start_turn(self, thread_id, text, effort=None):
        with self._lock:
            if not self._up:
                raise HostError("cursor host is not running")
            if self._turn:
                raise HostError("cursor host already has a turn running")
            t = self._threads.get(thread_id)
            if t is None:
                raise HostError(f"unknown cursor thread {thread_id}")
            turn = str(uuid.uuid4())
            stderr = tempfile.TemporaryFile("w+", encoding="utf-8", errors="replace")
            try:
                proc = self._spawn(self._argv(thread_id, t), stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=stderr,
                                   cwd=t["settings"]["cwd"], env=self._env(t["settings"]), text=True, bufsize=1)
            except OSError as exc:
                stderr.close()
                raise HostError(f"could not start cursor-agent: {exc}")
            self.proc = proc
            self._turn = (thread_id, turn)
        self._log(f"cursor[{self.bot}]: turn started pid {getattr(proc, 'pid', '?')}")
        self.emit("status", thread_id, None, state="active")
        threading.Thread(target=self._feed, args=(proc, text), daemon=True).start()
        self._reader = threading.Thread(target=self._read_loop, args=(proc, thread_id, turn, stderr), daemon=True)
        self._reader.start()
        return turn

    @staticmethod
    def _feed(proc, text):
        try:
            proc.stdin.write(text)
            proc.stdin.close()
        except (BrokenPipeError, ValueError, OSError):
            pass

    def _read_loop(self, proc, tid, turn, stderr):
        state = {"reply": "", "error": "", "done": False}
        try:
            for line in proc.stdout:
                try:
                    event = json.loads(line)
                except ValueError:
                    continue
                try:
                    self._on_event(event, tid, turn, state)
                except Exception as exc:
                    self._log(f"cursor[{self.bot}]: event error {exc}")
        except (ValueError, OSError):
            pass
        try:
            rc = proc.wait()
        except Exception:
            rc = -1
        self._finish(tid, turn, rc, self._stderr_tail(stderr), state)

    def _stderr_tail(self, stderr):
        try:
            stderr.seek(0)
            text = stderr.read()
        except (OSError, ValueError):
            text = ""
        finally:
            try:
                stderr.close()
            except OSError:
                pass
        if text and self.stderr_path:
            try:
                with open(self.stderr_path, "a", encoding="utf-8") as log:
                    log.write(text if text.endswith("\n") else text + "\n")
            except OSError:
                pass
        return text.strip()[-STDERR_TAIL:]

    def _on_event(self, event, tid, turn, state):
        if not isinstance(event, dict):
            return
        kind = event.get("type")
        if kind == "assistant":
            text = message_text(event.get("message"))
            if text:
                state["reply"] = text
                self.emit("message", tid, turn, text=text, final=False)
        elif kind == "tool_call" and event.get("subtype") == "started":
            call = event.get("tool_call") or {}
            name = next(iter(call), "") if isinstance(call, dict) else ""
            self.emit("tool", tid, turn, name=name, tool=name, phase="tool_execution_start")
        elif kind == "result":
            state["done"] = True
            if event.get("is_error") or event.get("subtype") not in (None, "success"):
                state["error"] = str(event.get("result") or event.get("error") or event.get("subtype") or "cursor error")
            elif event.get("result"):
                state["reply"] = str(event["result"])
            inp, out, total = usage_tokens(event.get("usage"))
            if total:
                self.emit("tokens", tid, turn, input=inp, output=out, total=total,
                          usage={"input": inp, "cached": cached_tokens(event.get("usage")), "output": out})

    def _finish(self, tid, turn, rc, stderr, state):
        with self._lock:
            if self._turn and self._turn[1] == turn:
                self._turn = None
                self.proc = None
            interrupted = turn in self._interrupted
        if turn in self._done_turns:
            return
        self._done_turns.add(turn)
        if interrupted:
            self.emit("turn_completed", tid, turn, status="interrupted")
        elif state["done"] and not state["error"] and rc == 0:
            if state["reply"]:
                self.emit("message", tid, turn, text=state["reply"], final=True)
            self.emit("turn_completed", tid, turn, status="completed")
        else:
            text = state["error"] or stderr or f"cursor-agent exited {rc}"
            self.emit("turn_failed", tid, turn, error=text, limit=is_limit(text))
        self.emit("status", tid, None, state="idle")

    def steer(self, thread_id, turn_id, text):
        raise HostError("Cursor runtime cannot steer a running turn")

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
