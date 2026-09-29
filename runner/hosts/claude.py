"""The Claude Code host: one `claude -p` process per turn, one Claude session per bot thread.

Verified against Claude Code 2.1.212. Claude Code has no server the runner could hold open, so
a turn is one `claude -p` run: the prompt goes in on stdin, newline-delimited stream-json comes
out on stdout, and the process exits when the turn is over. A thread is a Claude session id
chosen here (uuid4). The first turn passes `--session-id`, later turns `--resume`, and a fork
is `--resume <old> --fork-session --session-id <new>`; Claude reloads the conversation from its
own session files under ~/.claude/projects, so the process must keep the HOME that holds the
login and those files.

    claude -p --output-format stream-json --verbose --include-partial-messages
           --permission-mode bypassPermissions [--model m] [--effort e] --session-id <uuid>

Turn ids are the runner's own uuid4. One turn runs at a time per host, so the runner keeps one
host per Claude bot. A `-p` process reads nothing after its prompt: `steer` is refused
(`supports_steer` is False, so the runner does not poll for mid-turn inputs) and `interrupt`
terminates the process.
"""

import json
import os
import subprocess
import tempfile
import threading
import uuid

from .base import Host, HostError, hub_mcp_server, is_auth_retryable, is_limit
from .codex import iso

STREAM_ARGS = ["--output-format", "stream-json", "--verbose", "--include-partial-messages",
               "--permission-mode", "bypassPermissions"]
# `claude --effort` accepts exactly these. Anything else means Claude's own default, so a
# Codex-only value in a manifest cannot fail every turn.
EFFORTS = ("low", "medium", "high", "xhigh", "max")
WINDOW_MINUTES = {"five_hour": 300, "seven_day": 7 * 24 * 60}
STOP_TIMEOUT_S = 10
STDERR_TAIL = 2000


def effort_for(effort):
    e = str(effort or "").strip().lower()
    return e if e in EFFORTS else None


def model_for(model):
    """`--model` for a thread, or None for Claude's default.

    The registry's defaults name a Codex model, which an employee that only says
    `runtime: claude` inherits; Claude would refuse it.
    """
    m = str(model or "").strip()
    if not m or m == "default" or m.lower().startswith("gpt-"):
        return None
    return m


def usage_tokens(usage):
    """(input, output, total) from a Claude usage object.

    Cached prompt tokens are input the model read all the same, so they count as input;
    `input_tokens` alone is only the uncached remainder.
    """
    u = usage if isinstance(usage, dict) else {}

    def count(key):
        try:
            return int(u.get(key) or 0)
        except (TypeError, ValueError):
            return 0

    inp = count("input_tokens") + count("cache_creation_input_tokens") + count("cache_read_input_tokens")
    out = count("output_tokens")
    return inp, out, inp + out


class ClaudeHost(Host):
    name = "claude"
    supports_steer = False

    def __init__(self, bot=None, cmd=("claude",), log=None, stderr_path=None, spawn=None):
        super().__init__(log=log)
        self.bot = bot
        self.cmd = list(cmd)
        self.stderr_path = stderr_path
        self._spawn = spawn or subprocess.Popen
        self._up = False
        self.proc = None                   # the running turn's process
        self._reader = None
        self._threads = {}                 # thread id -> {"settings", "started", "fork_from"}
        self._turn = None                  # (thread id, turn id) while a turn runs
        self._reply = {}                   # turn id -> the last complete assistant text
        self._last_message = {}            # turn id -> (message id, text) already emitted
        self._limited = set()              # turn ids Claude reported as rate limited
        self._interrupted = set()
        self._done_turns = set()

    # ------------------------------------------------------------------ process
    def start(self):
        """Nothing runs between turns; `alive` means the host accepts turns."""
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
    def _record(self, thread_id, bot, settings, started, fork_from=None):
        self._threads[thread_id] = {"bot": bot, "settings": dict(settings), "started": started,
                                    "fork_from": fork_from}
        return thread_id

    def start_thread(self, bot, settings):
        return self._record(str(uuid.uuid4()), bot, settings, started=False)

    def resume_thread(self, bot, thread_id, settings):
        return self._record(thread_id, bot, settings, started=True)

    def fork_thread(self, bot, thread_id, settings):
        return self._record(str(uuid.uuid4()), bot, settings, started=False, fork_from=thread_id)

    def _argv(self, thread_id, t, effort):
        argv = self.cmd + ["-p"] + STREAM_ARGS
        # The hub's MCP server for this turn. Not `--strict-mcp-config`: a bot repo's own
        # `.mcp.json` (an integration's read-only server, say) stays in force.
        hub = hub_mcp_server(t["settings"].get("env"))
        if hub:
            argv += ["--mcp-config", json.dumps({"mcpServers": {"hub": hub}})]
        model = model_for(t["settings"].get("model"))
        if model:
            argv += ["--model", model]
        effort = effort_for(effort or t["settings"].get("effort"))
        if effort:
            argv += ["--effort", effort]
        if t["fork_from"]:
            argv += ["--resume", t["fork_from"], "--fork-session", "--session-id", thread_id]
        elif t["started"]:
            argv += ["--resume", thread_id]
        else:
            argv += ["--session-id", thread_id]
        return argv

    @staticmethod
    def _env(settings):
        env = settings.get("env")
        if not env:
            return None
        env = dict(env)
        # The login and the session files live under HOME; a trimmed environment must keep it.
        if not env.get("HOME") and os.environ.get("HOME"):
            env["HOME"] = os.environ["HOME"]
        return env

    # ------------------------------------------------------------------ turns
    def start_turn(self, thread_id, text, effort=None):
        with self._lock:
            if not self._up:
                raise HostError("claude host is not running")
            if self._turn:
                raise HostError("claude host already has a turn running")
            t = self._threads.get(thread_id)
            if t is None:
                raise HostError(f"unknown claude thread {thread_id}")
            turn = str(uuid.uuid4())
            stderr = tempfile.TemporaryFile("w+", encoding="utf-8", errors="replace")
            try:
                proc = self._spawn(self._argv(thread_id, t, effort), stdin=subprocess.PIPE,
                                   stdout=subprocess.PIPE, stderr=stderr, cwd=t["settings"]["cwd"],
                                   env=self._env(t["settings"]), text=True, bufsize=1)
            except OSError as e:
                stderr.close()
                raise HostError(f"could not start claude: {e}")
            self.proc = proc
            self._turn = (thread_id, turn)
            self._reply[turn] = ""
        self._log(f"claude[{self.bot}]: turn started pid {getattr(proc, 'pid', '?')}")
        self.emit("status", thread_id, None, state="active")
        threading.Thread(target=self._feed, args=(proc, text), daemon=True).start()
        self._reader = threading.Thread(target=self._read_loop, args=(proc, thread_id, turn, stderr),
                                        daemon=True)
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
        result = None
        try:
            for line in proc.stdout:
                line = line.strip()
                if not line:
                    continue
                try:
                    msg = json.loads(line)
                except ValueError:
                    continue
                try:
                    if self._on_message(msg, tid, turn):
                        result = msg
                except Exception as e:
                    self._log(f"claude[{self.bot}]: event error {e}")
        except (ValueError, OSError):
            pass
        try:
            rc = proc.wait()
        except Exception:
            rc = -1
        self._finish(tid, turn, result, rc, self._stderr_tail(stderr))

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

    def _on_message(self, msg, tid, turn):
        """Map one stream-json line to keeper events. True when it is the turn's result."""
        if not isinstance(msg, dict) or msg.get("parent_tool_use_id"):
            return False                         # subagent traffic is not the bot's reply
        kind = msg.get("type")
        if kind == "stream_event":
            ev = msg.get("event") or {}
            delta = ev.get("delta") or {}
            if ev.get("type") == "content_block_delta" and delta.get("type") == "text_delta" \
                    and delta.get("text"):
                self.emit("delta", tid, turn, text=delta["text"], delta_kind="text")
        elif kind == "assistant":
            m = msg.get("message") or {}
            text = "".join(c.get("text") or "" for c in (m.get("content") or [])
                           if isinstance(c, dict) and c.get("type") == "text")
            if text and self._last_message.get(turn) != (m.get("id"), text):
                self._last_message[turn] = (m.get("id"), text)
                self._reply[turn] = text
                self.emit("message", tid, turn, text=text, final=False, item_id=m.get("id"))
        elif kind == "system" and msg.get("subtype") == "init":
            t = self._threads.get(tid)
            if t:                                # Claude owns the id now: resume from here on
                t.update(started=True, fork_from=None)
        elif kind == "rate_limit_event":
            info = msg.get("rate_limit_info") or {}
            if info.get("status") == "rejected":
                self._limited.add(turn)
            self.emit("rate_limits", tid, turn, used_percent=None,
                      window_minutes=WINDOW_MINUTES.get(info.get("rateLimitType")),
                      resets_at=iso(info.get("resetsAt")), status=info.get("status"))
        elif kind == "result":
            return True
        return False

    def _finish(self, tid, turn, result, rc, stderr):
        with self._lock:
            if self._turn and self._turn[1] == turn:
                self._turn = None
                self.proc = None
            interrupted = turn in self._interrupted
        reply = self._reply.pop(turn, "")
        self._last_message.pop(turn, None)
        limited = turn in self._limited
        self._limited.discard(turn)
        if turn in self._done_turns:
            return
        self._done_turns.add(turn)
        result = result if isinstance(result, dict) else None
        if result:
            inp, out, total = usage_tokens(result.get("usage"))
            if total:
                self.emit("tokens", tid, turn, input=inp, output=out, total=total,
                          cost_usd=result.get("total_cost_usd"))
        if interrupted:
            self.emit("turn_completed", tid, turn, status="interrupted")
        elif result and not result.get("is_error") and rc == 0:
            text = result.get("result") or reply
            if text:
                self.emit("message", tid, turn, text=text, final=True)
            self.emit("turn_completed", tid, turn, status="completed",
                      stop_reason=result.get("stop_reason"))
        else:
            error = self._error_text(result, rc, stderr)
            self.emit("turn_failed", tid, turn, error=error, limit=limited or is_limit(error),
                      auth_retry=is_auth_retryable(error))
        self.emit("status", tid, None, state="idle")

    @staticmethod
    def _error_text(result, rc, stderr):
        if result:
            errors = result.get("errors")
            if isinstance(errors, list) and errors:
                return "; ".join(str(e) for e in errors)
            if isinstance(result.get("result"), str) and result["result"]:
                return result["result"]
            if result.get("subtype"):
                return str(result["subtype"])
        if stderr:
            return stderr
        return f"claude exited {rc}"

    def steer(self, thread_id, turn_id, text):
        raise HostError("Claude runtime cannot steer a running turn")

    def interrupt(self, thread_id, turn_id):
        with self._lock:
            proc, running = self.proc, self._turn
            if not proc or not running or running[1] != turn_id:
                return                           # already over; nothing to stop
            self._interrupted.add(turn_id)
        self._end(proc)

    # ------------------------------------------------------------------ helpers
    def active_turn(self, thread_id):
        running = self._turn
        return running[1] if running and running[0] == thread_id else None
