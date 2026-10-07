"""Whether a bot's engineering tools work on this computer, for readiness (backend/health.py warns).

Two checks, run rarely in the background like runner/container_probe.py (and through its ContainerProbe, so a
failure is checked again at once and only two in a row are reported):

- GitHub sign-in: a token minted for a bot on this computer the way a turn gets one (`github/token`), asked for
  `GET /installation/repositories`. GitHub answering 401 is the "Bad credentials" a bot's `gh` would hit.
  No App, no bot with GitHub access, or no answer from GitHub is nothing to report.
- Browser launch: the Chromium that Playwright installed for this computer's bots, started headless on a blank
  page. Missing system libraries fail here the way they fail a bot's browser check. No browser installed is
  nothing to report.

The token is never logged or returned; a result carries only whether it worked and GitHub's or the browser's
own short reason.
"""
import datetime
import glob
import json
import os
import platform
import subprocess
import time
import urllib.error
import urllib.request
from pathlib import Path

from . import isolation, safe_git

API = "https://api.github.com"
GITHUB_LIMIT_S = 15
BROWSER_LIMIT_S = 30
# Where Playwright keeps its browsers (PLAYWRIGHT_BROWSERS_PATH overrides), newest version last when sorted.
CACHE = {"Darwin": "Library/Caches/ms-playwright", "Windows": "AppData/Local/ms-playwright"}
EXECUTABLES = ("chromium_headless_shell-*/*/chrome-headless-shell", "chromium_headless_shell-*/*/headless_shell",
               "chromium-*/*/chrome", "chromium-*/*/Chromium.app/Contents/MacOS/Chromium",
               "chromium-*/*/Google Chrome for Testing.app/Contents/MacOS/Google Chrome for Testing")


def _result(ok, started, error=""):
    return {"ok": ok, "seconds": round(time.monotonic() - started, 1), "error": error[:300],
            "checked_at": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")}


def github(client, bots, opener=urllib.request.urlopen):
    """{ok, seconds, error, checked_at} for the first of `bots` the GitHub App gives a token, or None."""
    started = time.monotonic()
    for bot in bots:
        try:
            granted = client.post("github/token", {"bot": bot})
        except Exception:
            continue          # a refused or failed mint already shows in Health (token_failure, repositories)
        if not granted.get("configured"):
            return None       # no App: bots use the computer's own git access
        token = granted.get("token")
        if not token:
            continue
        request = urllib.request.Request(API + "/installation/repositories?per_page=1", headers={
            "Authorization": "token " + token, "Accept": "application/vnd.github+json", "User-Agent": "tico-runner"})
        try:
            with opener(request, timeout=GITHUB_LIMIT_S) as response:
                response.read(1)
            return _result(True, started)
        except urllib.error.HTTPError as exc:
            if exc.code != 401:
                return None   # rate limits and outages are not a sign-in problem
            try:
                said = json.loads(exc.read() or b"{}").get("message") or ""
            except (ValueError, OSError, AttributeError):
                said = ""
            return _result(False, started, f"{bot}: GitHub answered 401 {said or 'Bad credentials'}")
        except (OSError, ValueError):
            return None       # no network: not a sign-in problem
    return None


def browsers(home=None):
    """Playwright's Chromium executables on this computer, newest first."""
    root = os.environ.get("PLAYWRIGHT_BROWSERS_PATH") or ""
    if root in ("", "0"):
        root = str(Path(home or Path.home()) / CACHE.get(platform.system(), ".cache/ms-playwright"))
    found = [path for pattern in EXECUTABLES for path in glob.glob(os.path.join(glob.escape(root), pattern))]
    return sorted((path for path in found if os.access(path, os.X_OK)), reverse=True)


def browser(run=isolation.run, home=None):
    """{ok, seconds, error, checked_at} for starting the newest installed Chromium headless, or None.

    The executable sits in the bots' shared cache, where bot code can replace it, so it runs as the bot user
    (runner/isolation.py) with only process settings in its environment, never as the supervisor."""
    found = browsers(home)
    if not found:
        return None
    started = time.monotonic()
    try:
        done = run([found[0], "--headless", "--no-sandbox", "--disable-gpu", "--dump-dom", "about:blank"],
                   capture_output=True, text=True, timeout=BROWSER_LIMIT_S, stdin=subprocess.DEVNULL,
                   env=safe_git.process_environment())
    except subprocess.TimeoutExpired:
        return _result(False, started, f"the browser did not start within {BROWSER_LIMIT_S} s")
    except OSError as exc:
        return _result(False, started, str(exc))
    if done.returncode == 0:
        return _result(True, started)
    lines = [line for line in (done.stderr or done.stdout or "").strip().splitlines() if line.strip()]
    # The loader names the missing library on its own line ("error while loading shared libraries: libglib-2.0.so.0").
    reason = next((line for line in lines if "shared librar" in line), lines[-1] if lines else f"exit {done.returncode}")
    return _result(False, started, reason.strip())
