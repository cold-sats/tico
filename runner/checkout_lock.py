"""A turn owns its checkout until its harness, uploads and publishing have stopped."""

import fcntl
import hashlib
import os
from contextlib import contextmanager
from pathlib import Path


@contextmanager
def hold(checkout):
    checkout = Path(checkout).resolve()
    directory = checkout.parent / ".tico-locks"
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    name = hashlib.sha256(str(checkout).encode()).hexdigest() + ".lock"
    # Keep the inode: unlinking it would let another process lock a different file.
    fd = os.open(directory / name, os.O_CREAT | os.O_RDWR, 0o600)
    acquired = False
    try:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            acquired = True
        except BlockingIOError:
            pass
        yield acquired
    finally:
        os.close(fd)
