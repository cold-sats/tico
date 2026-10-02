"""A turn owns its checkout until its harness, uploads and publishing have stopped."""

try:
    import fcntl
except ImportError:
    fcntl = None
import hashlib
import logging
import os
import threading
from contextlib import contextmanager
from pathlib import Path


_local = threading.local()
_warned = False


def inherited_fds():
    return (getattr(_local, "fd", None),) if getattr(_local, "fd", None) is not None else ()


@contextmanager
def hold(checkout, state_dir):
    global _warned
    fd, acquired = None, True
    try:
        directory = Path(state_dir) / "checkout-locks"
        directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        name = hashlib.sha256(str(Path(checkout).resolve()).encode()).hexdigest() + ".lock"
        # Keep the inode: unlinking it would let another process lock a different file.
        fd = os.open(directory / name, os.O_CREAT | os.O_RDWR, 0o600)
        if fcntl is None:
            raise OSError("File locking is unavailable")
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            acquired = False
    except OSError as exc:
        if fd is not None:
            os.close(fd)
            fd = None
        if not _warned:
            logging.getLogger("tico.runner").warning("Checkout lock unavailable; running unlocked: %s", exc)
            _warned = True
    previous = getattr(_local, "fd", None)
    _local.fd = fd if acquired else None
    try:
        yield acquired
    finally:
        _local.fd = previous
        if fd is not None:
            os.close(fd)
