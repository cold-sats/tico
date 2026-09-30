"""The latest public release, asked of GitHub at most every 15 minutes and served from memory in between."""
import threading
import time

import httpx

RELEASES_URL = "https://api.github.com/repos/ticoteam/tico/releases/latest"
TTL = 15 * 60


class Latest:
    def __init__(self, url=RELEASES_URL, token="", clock=time.monotonic, transport=None):
        self.url, self.clock, self.transport = url, clock, transport
        self.headers = {"Accept": "application/vnd.github+json", "User-Agent": "tico-hq"}
        if token:
            self.headers["Authorization"] = "Bearer " + token
        self.lock = threading.Lock()
        self.value, self.fetched = None, None

    def get(self):
        """The release as {tag_name, html_url, published_at, name}, the last good one when GitHub is down, else None."""
        with self.lock:
            now = self.clock()
            if self.value and self.fetched is not None and now - self.fetched < TTL:
                return self.value
            try:
                with httpx.Client(timeout=5, transport=self.transport) as http:
                    r = http.get(self.url, headers=self.headers)
                body = r.json() if r.status_code == 200 else {}
                if isinstance(body, dict) and body.get("tag_name"):
                    self.value = {k: str(body.get(k) or "") for k in ("tag_name", "html_url", "published_at", "name")}
                    self.fetched = now
                    return self.value
            except (httpx.HTTPError, ValueError):
                pass
            # Serve the stale answer, and try again in a minute rather than on every request.
            if self.value:
                self.fetched = now - TTL + 60
            return self.value
