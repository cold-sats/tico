"""Helper services restart on new code.

The Mac runs two helpers beside the runner: connectors and Close calls.
The runner fast-forwards the shared checkout and restarts itself, but nothing restarted the
helpers: both could run for days, so calendar sync stayed broken for hours
after its fix merged. Each helper now looks every few minutes; when the checkout has moved
and code it loads changed, it exits between jobs and the supervisor starts it on the new code.
"""
import subprocess
import time

HELPER_CODE = ("runner/", "clients/", "connectors/")


def code_changed(old, new, root, paths=HELPER_CODE, run=subprocess.run):
    """Whether files under `paths` differ between two commits. Unknown counts as changed."""
    try:
        done = run(["git", "-C", str(root), "diff", "--name-only", old, new], capture_output=True,
                   text=True, timeout=30, stdin=subprocess.DEVNULL)
    except (OSError, subprocess.SubprocessError):
        return True
    if done.returncode:
        return True
    return any(path.startswith(paths) for path in done.stdout.split())


class CodeWatch:
    def __init__(self, every=300, clock=time.monotonic, head=None, changed=None, supervised=None, root=None):
        from .service import ROOT, checkout_head
        from .service import supervised as process_supervised
        self.root = root or ROOT
        self.head = head or (lambda: checkout_head(self.root))
        self.changed = changed or (lambda old, new: code_changed(old, new, self.root))
        self.supervised = process_supervised if supervised is None else supervised
        self.every, self.clock = every, clock
        self.started = self.head()
        self.checked = clock()

    def stale(self):
        """True once, when this process should exit so the supervisor starts it on the new code."""
        if not self.started or not self.supervised() or self.clock() - self.checked < self.every:
            return False
        self.checked = self.clock()
        head = self.head()
        return bool(head and head != self.started and self.changed(self.started, head))
