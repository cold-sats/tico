"""A scripted host for the runner's tests: no process, no network, no runtime.

    host = FakeHost(replies=["hello"])          # one canned reply per turn, in order
    host.replies.append("and another")
    host.die_next_turn()                        # the next turn starts and the host dies
    host.fail_next_turn("You've hit your usage limit. Try again at 9:11 PM.")

A turn is answered synchronously: `start_turn` emits the deltas, the final message and
`turn_completed` before it returns, so a test can tick the runner and see the whole turn.
"""

import uuid

from .base import Host, HostError, is_auth_retryable, is_limit

DEFAULT_REPLY = "ok"


class FakeHost(Host):
    name = "fake"
    supports_steer = True

    def __init__(self, replies=None, log=None):
        super().__init__(log=log)
        self.replies = list(replies or [])
        self.started = False
        self._alive = False
        self.threads = {}                  # thread id -> {"bot", "settings"}
        self.prompts = []                  # (thread_id, text) in order
        self.steers = []                   # (thread_id, turn_id, text)
        self.interrupts = []
        self.resumes = []                  # thread ids the runner asked us to resume
        self.forks = []
        self.starts = 0                    # how many times the process "started"
        self._die_next = False
        self._fail_next = None
        self._fail_after_reply = None
        self._hold_next = False
        self.resume_fails = 0              # make this many resume_thread calls fail
        self.fork_fails = 0
        self.turn_of = {}                  # thread id -> the running turn

    # ------------------------------------------------------------------ process
    def start(self):
        self.started = True
        self._alive = True
        self.starts += 1

    def stop(self):
        self._alive = False

    def alive(self):
        return self._alive

    def supervise(self):
        if self.alive():
            return False
        self.start()
        self.turn_of = {}
        self.emit("error", error="fake host restarted", host_restart=True)
        return True

    # ------------------------------------------------------------------ scripting
    def die_next_turn(self):
        self._die_next = True

    def fail_next_turn(self, error="the turn failed", after_reply=None):
        """Fail the next turn. `after_reply` makes the bot speak first, so a test can show the
        difference between a turn that never ran and one that had already acted."""
        self._fail_next = error
        self._fail_after_reply = after_reply

    def hold_next_turn(self):
        """The next turn starts and stays running until `complete()`."""
        self._hold_next = True

    def complete(self, thread_id, reply="ok"):
        """Finish a held turn."""
        turn = self.turn_of.pop(thread_id, None)
        if not turn:
            raise HostError(f"no turn running on {thread_id}")
        self.emit("message", thread_id, turn, text=reply, final=True)
        self.emit("status", thread_id, None, state="idle")
        self.emit("turn_completed", thread_id, turn, status="completed")
        return turn

    def kill(self):
        """The process is gone; the runner's next supervise() brings it back."""
        self._alive = False

    # ------------------------------------------------------------------ threads
    def _require_alive(self):
        if not self._alive:
            raise HostError("fake host is not running")

    def start_thread(self, bot, settings):
        self._require_alive()
        tid = str(uuid.uuid4())
        self.threads[tid] = {"bot": bot, "settings": settings}
        return tid

    def resume_thread(self, bot, thread_id, settings):
        self._require_alive()
        self.resumes.append(thread_id)
        if self.resume_fails > 0:
            self.resume_fails -= 1
            raise HostError("fake resume failed")
        self.threads[thread_id] = {"bot": bot, "settings": settings}
        return thread_id

    def fork_thread(self, bot, thread_id, settings):
        self._require_alive()
        self.forks.append(thread_id)
        if self.fork_fails > 0:
            self.fork_fails -= 1
            raise HostError("fake fork failed")
        return self.start_thread(bot, settings)

    # ------------------------------------------------------------------ turns
    def start_turn(self, thread_id, text, effort=None):
        self._require_alive()
        turn = str(uuid.uuid4())
        self.prompts.append((thread_id, text))
        self.turn_of[thread_id] = turn
        self.emit("status", thread_id, turn, state="active")
        if self._die_next:
            self._die_next = False
            self._alive = False                     # mid-turn death: nothing more is emitted
            return turn
        if self._hold_next:
            self._hold_next = False
            return turn                             # still running until complete() is called
        if self._fail_next is not None:
            err, self._fail_next = self._fail_next, None
            said, self._fail_after_reply = getattr(self, "_fail_after_reply", None), None
            self.turn_of.pop(thread_id, None)
            if said:
                self.emit("message", thread_id, turn, text=said, final=False)
            self.emit("turn_failed", thread_id, turn, error=err, limit=is_limit(err),
                      auth_retry=is_auth_retryable(err))
            self.emit("status", thread_id, None, state="idle")
            return turn
        reply = self.replies.pop(0) if self.replies else DEFAULT_REPLY
        for chunk in (reply[i:i + 20] for i in range(0, len(reply), 20)):
            self.emit("delta", thread_id, turn, text=chunk, delta_kind="text")
        self.emit("message", thread_id, turn, text=reply, final=True)
        self.emit("tokens", thread_id, turn, input=100, output=len(reply), total=100 + len(reply),
                  usage={"input": 100, "cached": 0, "output": len(reply)})
        self.turn_of.pop(thread_id, None)
        self.emit("status", thread_id, None, state="idle")
        self.emit("turn_completed", thread_id, turn, status="completed")
        return turn

    def start_goal(self, thread_id, action, objective, effort=None):
        self.emit("goal", thread_id, None,
                  status={"pause": "paused", "clear": "cleared"}.get(action, "active"),
                  objective=objective, note="")
        turn = self.start_turn(thread_id, "/goal clear" if action in ("pause", "clear") else "/goal " + objective,
                               effort=effort)
        return turn

    def goal_met(self, thread_id, note="The condition holds."):
        self.emit("goal", thread_id, None, status="met", note=note)

    def steer(self, thread_id, turn_id, text):
        self._require_alive()
        self.steers.append((thread_id, turn_id, text))

    def interrupt(self, thread_id, turn_id):
        self.interrupts.append((thread_id, turn_id))
        self.turn_of.pop(thread_id, None)
