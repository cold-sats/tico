"""Helper services restart on new code.

A Mac runs three helpers beside the runner (connectors, close-calls, importers), each a long-lived loop under its own launchd
job. A release moves the shared checkout and restarts the runner's job only, so a helper would go on with the old release in
memory while it lazily imports new modules and runs new scripts from the switched checkout: two versions in one process.
Each helper therefore records the checkout's revision at start and looks again at least once a minute; when it has changed,
the loop exits with status 0 between jobs and the supervisor (launchd KeepAlive) starts it on the new code. Any new revision
counts, not only changes under runner/: a helper loads more than that.
"""
import time

from .outage import log

CHECK_EVERY_S = 60


class CodeWatch:
    def __init__(self, name, every=CHECK_EVERY_S, clock=time.monotonic, head=None, supervised=None, root=None, say=log):
        from .service import ROOT, checkout_head
        from .service import supervised as process_supervised
        self.name, self.every, self.clock, self.say = name, every, clock, say
        self.root = root or ROOT
        self.head = head or (lambda: checkout_head(self.root))
        self.supervised = process_supervised if supervised is None else supervised
        self.started = self.head()
        self.checked = clock()

    def stale(self, force=False):
        """True when this process should exit so the supervisor starts it on the new code. Looks at most once
        per `every` seconds; an unknown revision (no git, mid-checkout) never counts. Logs the reason."""
        if not self.started or not self.supervised():
            return False
        if not force and self.clock() - self.checked < self.every:
            return False
        self.checked = self.clock()
        head = self.head()
        if not head or head == self.started:
            return False
        self.say(f"{self.name}: the checkout moved from {self.started[:7]} to {head[:7]}; "
                 "exiting so the supervisor restarts it on the new code")
        return True

    def wait(self, stop, seconds):
        """Sleep up to `seconds` on the `stop` event, looking at the revision every `every` seconds. True when the
        revision changed (exit now); False when the time is up or `stop` was set."""
        deadline = self.clock() + seconds
        while not stop.is_set():
            left = deadline - self.clock()
            if left <= 0:
                return False
            stop.wait(min(left, self.every))
            if not stop.is_set() and self.stale(force=True):
                return True
        return False
