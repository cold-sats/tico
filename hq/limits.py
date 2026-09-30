"""The request rate limit. The address is used only here, in memory, as a salted hash that is forgotten with the
process; it is never written to a log or to the database."""
import hashlib
import os
import time
from collections import deque


class Limiter:
    def __init__(self, limit=60, window=3600, clock=time.monotonic, max_keys=100_000):
        self.limit, self.window, self.clock, self.max_keys = limit, window, clock, max_keys
        self.salt = os.urandom(16)
        self.hits = {}
        self.swept = clock()

    def allow(self, address):
        now = self.clock()
        if now - self.swept > 300 or len(self.hits) > self.max_keys:
            self._sweep(now)
        key = hashlib.blake2b(str(address).encode(), key=self.salt, digest_size=16).digest()
        seen = self.hits.setdefault(key, deque())
        while seen and now - seen[0] >= self.window:
            seen.popleft()
        if len(seen) >= self.limit:
            return False
        seen.append(now)
        return True

    def _sweep(self, now):
        self.swept = now
        for key in [k for k, seen in self.hits.items() if not seen or now - seen[-1] >= self.window]:
            del self.hits[key]
        if len(self.hits) > self.max_keys:
            self.hits.clear()
