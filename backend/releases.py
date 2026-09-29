"""Which version is running, whether a newer public release exists, and the owner's "Update now".

The version is `TICO_VERSION` (the Docker image sets it), else a `VERSION` file at the
repository root, else "dev". The newest release comes from
GitHub's public API, at most once per `TTL`, and never on a request's path: a read returns what is
cached and, when that is stale, starts one background refresh. Any failure keeps the last answer.

Applying an update is the job of a separate updater service (`TICO_UPDATER_URL`); this process
never restarts itself. Without one the owner is told the command to run by hand.
"""
import logging
import os
import re
import threading
import time
from pathlib import Path

import httpx

from .store import Problem

log = logging.getLogger("tico.releases")
ROOT = Path(__file__).resolve().parents[1]
LATEST_URL = "https://api.github.com/repos/ticoteam/tico/releases/latest"
TTL = 6 * 3600
FORCE_GAP = 60           # the owner's "Check for updates" may reach GitHub at most this often
RETRY = 15 * 60          # after a failed check; a rate-limited or offline box should not hammer GitHub
MANUAL_COMMAND = "docker compose pull && docker compose up -d"
SEMVER = re.compile(r"^v?(\d+)\.(\d+)\.(\d+)(?:-([0-9A-Za-z.-]+))?(?:\+[0-9A-Za-z.-]+)?$")
# Replaced in tests with an httpx.MockTransport so nothing reaches the network.
TRANSPORT = None


def version():
    value = os.environ.get("TICO_VERSION", "").strip()
    if not value:
        try:
            value = (ROOT / "VERSION").read_text().strip()
        except OSError:
            value = ""
    return re.sub(r"^v(?=\d)", "", value) or "dev"  # the image is built from a v1.2.3 tag


def parse(value):
    """(major, minor, patch, prerelease-key) or None when `value` is not a semantic version."""
    match = SEMVER.match(str(value or "").strip())
    if not match:
        return None
    major, minor, patch, pre = match.groups()
    # A release outranks its own prereleases; prerelease identifiers compare part by part.
    key = (1,) if not pre else (0, *((0, int(p)) if p.isdigit() else (1, p) for p in pre.split(".")))
    return int(major), int(minor), int(patch), key


def newer(latest, current):
    a, b = parse(latest), parse(current)
    return bool(a and b and a > b)


def _client(timeout=5):
    return httpx.Client(timeout=timeout, transport=TRANSPORT, follow_redirects=False)


class Checker:
    def __init__(self, clock=time.time):
        self.clock = clock
        self.lock = threading.Lock()
        self.etag = ""
        self.release = None
        self.checked = 0.0
        self.retry_at = 0.0
        self.running = False
        self.forced = 0.0

    @staticmethod
    def enabled():
        return os.environ.get("TICO_UPDATE_CHECK", "").strip().lower() not in ("off", "0", "false", "no")

    def refresh(self):
        """One conditional request. Runs in the background thread; tests call it directly."""
        url = os.environ.get("TICO_RELEASES_URL", "").strip() or LATEST_URL
        headers = {"Accept": "application/vnd.github+json", "User-Agent": "tico-update-check"}
        if self.etag and self.release:
            headers["If-None-Match"] = self.etag
        try:
            with _client() as http:
                r = http.get(url, headers=headers)
            if r.status_code == 304:
                pass
            elif r.status_code == 200:
                body = r.json()
                self.release = {"tag": str(body.get("tag_name") or ""), "url": str(body.get("html_url") or ""),
                                "published_at": str(body.get("published_at") or ""),
                                "name": str(body.get("name") or body.get("tag_name") or "")}
                self.etag = r.headers.get("etag", "")
            else:
                raise httpx.HTTPError("status %s" % r.status_code)
            self.checked, self.retry_at = self.clock(), 0.0
        except Exception as exc:
            log.debug("Release check failed: %s", type(exc).__name__)
            self.retry_at = self.clock() + RETRY
        finally:
            self.running = False

    def check_now(self):
        """The owner's "Check for updates": one request now, however fresh the cache is."""
        if not self.enabled():
            raise Problem("check_disabled", "Update checks are turned off on this server (TICO_UPDATE_CHECK).", 409)
        with self.lock:
            wait = FORCE_GAP - (self.clock() - self.forced)
            if wait > 0:
                raise Problem("rate_limited", "Checked a moment ago. Try again in %d seconds." % (int(wait) + 1), 429,
                              retryable=True, extra={"retry_after": int(wait) + 1})
            self.forced = self.clock()
        self.refresh()
        # refresh() swallows failures and schedules a retry; that is how a failed check shows here.
        if self.retry_at > self.clock():
            raise Problem("check_failed", "Could not reach GitHub to look for a new release. Try again later.", 502,
                          retryable=True)

    def _refresh_if_stale(self):
        now = self.clock()
        if self.running or now < self.retry_at or (self.checked and now - self.checked < TTL):
            return
        with self.lock:
            if self.running:
                return
            self.running = True
        threading.Thread(target=self.refresh, daemon=True, name="release-check").start()

    def view(self, current):
        """The notice payload. Returns at once with whatever is cached."""
        out = {"current": current, "latest": "", "available": False, "url": "", "published_at": "", "name": ""}
        if not self.enabled() or parse(current) is None:
            return out
        self._refresh_if_stale()
        release = self.release
        if release:
            latest = release["tag"].lstrip("v")
            out.update(latest=latest, url=release["url"], published_at=release["published_at"], name=release["name"],
                       available=newer(latest, current))
        return out


CHECKER = Checker()


def notice():
    return CHECKER.view(version())


def check_now():
    CHECKER.check_now()
    return notice()


def _updater():
    url = os.environ.get("TICO_UPDATER_URL", "").strip().rstrip("/")
    return url, os.environ.get("TICO_UPDATER_TOKEN", "").strip()


def _call(method, path, body=None):
    url, token = _updater()
    try:
        with _client(10) as http:
            r = http.request(method, url + path, json=body, headers={"Authorization": "Bearer " + token})
        if r.status_code >= 400:
            raise httpx.HTTPError("status %s" % r.status_code)
        return r.json()
    except (httpx.HTTPError, ValueError) as exc:
        log.warning("Updater call %s %s failed: %s", method, path, type(exc).__name__)
        raise Problem("updater_unreachable", "The updater did not answer. Try again, or update by hand.", 502,
                      retryable=True, extra={"command": MANUAL_COMMAND}) from None


def status():
    if not _updater()[0]:
        return {"configured": False, "state": "unavailable", "command": MANUAL_COMMAND}
    data = _call("GET", "/status")
    return {"configured": True, "state": str(data.get("state") or ""), "from": str(data.get("from") or ""),
            "to": str(data.get("to") or ""), "message": str(data.get("message") or "")}


def start(target):
    if parse(target) is None:
        raise Problem("invalid_version", "That is not a release version", 422)
    if not _updater()[0]:
        raise Problem("manual_update", "This installation has no updater. Run this on the server: " + MANUAL_COMMAND,
                      409, extra={"command": MANUAL_COMMAND})
    _call("POST", "/update", {"version": str(target).lstrip("v")})
    log.info("Update to %s requested", target)
    return status()
