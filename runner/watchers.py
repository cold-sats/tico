"""Watchers: programs in a bot's repository that this runner runs on a schedule, with no model (docs/watchers.md).

`employee.yaml` declares them (`watchers:`, clients/watchers.py). For each active bot hosted here, the runner runs each
declared program:

- no more often than its `every` (at least a minute), and never while the last run of it is still going;
- as the bot's user (runner/isolation.py), in the bot's repository, with the bot's secrets in its environment and
  no hub token, so a program fed hostile text can do nothing on the hub except say the three things in the protocol;
- with a timeout (60 seconds unless it says otherwise, 5 minutes at most), after which its process group is killed.

Its output is read up to a cap. Lines that start with `tico-event ` are events; the rest is a log. Both are cleaned of
every value that came from the secrets files, then posted to the hub (`POST /api/v2/runners/watchers`), which opens a
task or wakes the bot and records the run for Health. The hub being down is not a lost event: the program's state
directory (`<repository>/.state/<name>/`, its `TICO_WATCHER_STATE`) goes back to what it was before the run, so the
next run sees the same things again.
"""
import concurrent.futures
import os
import shutil
import signal
import subprocess
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

import yaml

from clients import watchers as declared
from clients.manifest import manifest_path
from . import isolation
from .outage import describe, log
from .profiles import SubscriptionUnavailable

SCAN_EVERY = 30              # seconds between reading the bots' bot.yaml files
OUTPUT_CAP = 256 * 1024      # bytes of output kept; the program is still drained past it
REPORT_CAP = 2000            # characters of log sent to the hub
STATE_CAP = 1024 * 1024      # bytes of state saved for the rollback
SECRET_NAMES = ("KEY", "TOKEN", "SECRET", "PASSWORD", "CREDENTIAL")
SHEBANG_PYTHON = "python"
# A parked starter bot's status: `needs_setup`, or `needs_onboarding` from a hub that has not moved to the new word.
PARKED_STATES = ("needs_setup", "needs_onboarding")


def now():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# Names that say a value is an address or a setting, not a secret: masking them would mangle ordinary text
# (a repository name, a URL, the bot's own name in a ticket title). A name that also says KEY/TOKEN/... wins.
PLAIN_NAMES = ("URL", "URI", "HOST", "REPO", "REPOS", "DIR", "PATH", "HOME", "EMAIL", "NAME", "LABEL", "TIMEZONE", "TZ")


def secret_values(env):
    """The values that must not appear in anything sent or logged: whatever the secrets files added to the
    environment, and any variable whose name says it is one. Call it before adding the runner's own variables."""
    found = set()
    for key, value in env.items():
        value, name = str(value or ""), key.upper()
        secret_name = any(w in name for w in SECRET_NAMES)
        plain_name = (any(name == w or name.endswith("_" + w) for w in PLAIN_NAMES)
                      or name.startswith(("HUB_", "TICO_")))     # the runner's own settings, never a credential
        if len(value) >= 6 and (secret_name or (value != os.environ.get(key) and not plain_name)):
            found.add(value)
    return sorted(found, key=len, reverse=True)


def redact(text, values):
    for value in values:
        text = text.replace(value, "[redacted]")
    return text


def command(path, argv):
    """The argv to run: a Python file with this runner's interpreter, whatever its mode; anything else as itself."""
    target = (Path(path) / argv[0]).resolve()
    root = Path(path).resolve()
    if root not in target.parents or not target.is_file():
        return None
    try:
        with target.open("rb") as handle:
            first = handle.readline(200)
    except OSError:
        return None
    if target.suffix == ".py" or (first.startswith(b"#!") and SHEBANG_PYTHON.encode() in first):
        return [sys.executable, str(target), *argv[1:]]
    return [str(target), *argv[1:]] if os.access(target, os.X_OK) else None


def snapshot(directory):
    saved, size = {}, 0
    for item in Path(directory).iterdir() if Path(directory).is_dir() else ():
        if item.is_file() and not item.is_symlink():
            size += item.stat().st_size
            if size > STATE_CAP:
                return None
            saved[item.name] = item.read_bytes()
    return saved


def restore(directory, saved):
    if saved is None:
        return
    directory = Path(directory)
    for item in list(directory.iterdir()) if directory.is_dir() else ():
        if item.is_file() and item.name not in saved:
            item.unlink()
    for name, data in saved.items():
        (directory / name).write_bytes(data)


class Watchers:
    def __init__(self, runner, clock=time.monotonic, popen=None):
        self.runner, self.clock = runner, clock
        self.popen = popen or isolation.popen
        self.pool = concurrent.futures.ThreadPoolExecutor(max_workers=3, thread_name_prefix="watcher")
        self.specs, self.next_scan = {}, 0.0
        self.next_at, self.running = {}, set()
        self.lock = threading.Lock()
        self.noted = {}          # (bot, name) -> the last problem logged, so a failing watcher is logged once
        self.stopping = False

    # ------------------------------------------------------------------ what is declared
    def scan(self):
        """{(bot, name): (entry, path, spec)} for the active bots hosted here that have finished setup. A bad declaration
        is logged once."""
        found = {}
        for entry in getattr(self.runner, "assignments_seen", None) or []:
            bot = entry.get("bot")
            if entry.get("state") != "active" or not self.runner.assigned_here(entry):
                continue
            if entry.get("onboarding_state") in PARKED_STATES:
                continue        # a bot still in setup takes no work, so what its watchers file would only pile up
            path = self.runner.local_path(bot)
            manifest = manifest_path(path)
            if not (path / "AGENT.md").is_file() or not manifest.is_file():
                continue
            try:
                specs = declared.parse((yaml.safe_load(manifest.read_text()) or {}).get("watchers"))
                self.noted.pop((bot, ""), None)
            except (OSError, yaml.YAMLError, AttributeError):
                continue
            except ValueError as exc:
                if self.noted.get((bot, "")) != str(exc):
                    self.noted[(bot, "")] = str(exc)
                    log(f"Tico runner: {bot} watchers ignored: {exc}")
                continue
            for spec in specs:
                found[(bot, spec["name"])] = (entry, path, spec)
        return found

    def tick(self):
        """Called by the runner's loop; starts what is due and returns at once."""
        if self.stopping or getattr(self.runner, "restart_due", None) is not None:
            return
        moment = self.clock()
        if moment >= self.next_scan:
            self.specs, self.next_scan = self.scan(), moment + SCAN_EVERY
        for key, (entry, path, spec) in self.specs.items():
            with self.lock:
                if key in self.running or self.next_at.get(key, 0.0) > moment:
                    continue
                self.running.add(key)
                self.next_at[key] = moment + spec["every"]
            self.pool.submit(self.guarded, key, entry, path, spec)

    def stop(self):
        self.stopping = True
        self.pool.shutdown(wait=False, cancel_futures=True)

    # ------------------------------------------------------------------ one run
    def guarded(self, key, entry, path, spec):
        try:
            self.run_once(key[0], entry, path, spec)
        except SubscriptionUnavailable as exc:
            self.problem(key, str(exc))
        except Exception as exc:                       # a watcher never stops the runner
            self.problem(key, f"failed to run ({describe(exc)})")
        finally:
            aid = "watcher:" + ":".join(key)
            self.runner.vault_values.pop(aid, None)
            self.runner.vault_names.pop(aid, None)
            for filename in self.runner.vault_files.pop(aid, []):
                Path(filename).unlink(missing_ok=True)
            with self.lock:
                self.running.discard(key)

    def problem(self, key, text):
        if self.noted.get(key) != text:
            self.noted[key] = text
            log(f"Tico runner: watcher {key[0]}/{key[1]} {text}")

    def environment(self, bot, entry, aid):
        granted = self.runner.client.get("runner-watcher-credentials", bot=bot)
        env = self.runner.environment({"id": aid, "bot": bot, "config": entry.get("config"), "token": "",
                                       "profile": entry.get("profile"),
                                       "computer_label": entry.get("computer_label")}, granted=granted)
        env.pop("HUB_TOKEN", None)
        return env

    def run_once(self, bot, entry, path, spec):
        key = (bot, spec["name"])
        argv = command(path, spec["argv"])
        if argv is None:
            return self.problem(key, "does not run: its file is not in the repository or cannot be executed")
        state = Path(path) / ".state" / spec["name"]
        isolation.mkdir(state)
        saved = snapshot(state)
        aid = "watcher:" + ":".join(key)
        env = self.environment(bot, entry, aid)
        secrets = sorted(set(secret_values(env)) | set(self.runner.vault_values.get(aid, [])), key=len, reverse=True)
        env.update({"TICO_WATCHER": spec["name"], "TICO_WATCHER_STATE": str(state), "HUB_BOT": bot, "HUB_EMPLOYEE": bot,
                    "HUB_API_URL": self.runner.config["url"], "HUB_WORKSPACE": str(self.runner.config["projects_dir"]),
                    "PATH": os.pathsep.join([str(Path(sys.executable).parent), env.get("PATH", os.defpath)])})
        started = now()
        proc = self.popen(argv, cwd=str(path), env=env, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                          stderr=subprocess.STDOUT, start_new_session=True)
        chunks, size = [], [0]

        def drain():
            for block in iter(lambda: proc.stdout.read(65536), b""):
                if size[0] < OUTPUT_CAP:
                    chunks.append(block[:OUTPUT_CAP - size[0]])
                    size[0] += len(chunks[-1])
        reader = threading.Thread(target=drain, daemon=True)
        reader.start()
        timed_out = False
        try:
            code = proc.wait(timeout=spec["timeout"])
        except subprocess.TimeoutExpired:
            timed_out, code = True, -9
            self.kill(proc)
        reader.join(5)
        text = redact(b"".join(chunks).decode("utf-8", "replace"), secrets)
        events, output = declared.events(text)
        body = {"bot": bot, "name": spec["name"], "started": started, "finished": now(), "exit": max(-255, min(255, code)),
                "timed_out": timed_out, "every": spec["every"], "output": output.strip()[-REPORT_CAP:], "events": events}
        try:
            self.runner.client.post("runners/watchers", body)
        except Exception as exc:
            restore(state, saved)                      # the events did not arrive, so the program must see them again
            return self.problem(key, f"ran but the hub did not take its report ({describe(exc)}); it will run again")
        if timed_out or code:
            self.problem(key, "timed out" if timed_out else f"exited {code}: {output.strip()[-300:]}")
        else:
            self.noted.pop(key, None)

    @staticmethod
    def kill(proc):
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except (OSError, AttributeError):
            try:
                proc.kill()
            except OSError:
                pass
        try:
            proc.wait(5)
        except subprocess.TimeoutExpired:
            pass
