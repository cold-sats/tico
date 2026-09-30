#!/usr/bin/env python3
"""Register a Hermes profile with the hub as an external agent, and keep its heartbeat going.

One file, standard library only, for the box that runs the profile; the hub serves it at
`GET /api/v2/agents/setup-script` so the box needs no checkout. What it does:

    python3 hermes_agent.py install --profile scout --url https://hub.example --bot scout --token tico-agent-...
        1. checks the token is that bot's agent credential (`GET /api/v2/me`);
        2. puts the hub in the profile's config.yaml as an MCP server (`mcp_servers.tico`),
           with the token in the profile's `.env` as TICO_AGENT_TOKEN, so the profile's
           agent has every `hub_*` tool (inbox, say, tasks, approvals, status, sql, ...);
        3. saves the credential in ~/.config/tico/agents/<profile>.json (mode 600);
        4. posts one heartbeat and installs a timer (launchd on macOS, a systemd user timer on
           Linux) that posts one every minute. The bot shows offline after three misses.
    python3 hermes_agent.py pair --profile scout --url https://hub.example
        the same four steps with no token to copy: it prints a code and what to tell BotOps,
        waits for a person (or BotOps) to approve it for a bot, and receives the credential itself.
    python3 hermes_agent.py update --profile scout       # newest connector from the hub, then install again
    python3 hermes_agent.py doctor --profile scout       # what works, what does not, old tool names
    python3 hermes_agent.py heartbeat --profile scout    # what the timer runs
    python3 hermes_agent.py status --profile scout       # the last reply, and what is waiting
    python3 hermes_agent.py uninstall --profile scout    # timer, config entry and env line

The heartbeat is a plain HTTP call, never an agent turn: it proves the box and the profile are
there, not that the model works. What the agent does with the hub is visible on its bot page
like any bot's. See docs/hermes-agents.md.
"""

import argparse
import ast
import json
import os
import platform
import plistlib
import re
import shutil
import socket
import stat
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

VERSION = "0.2.0"
CONFIG_DIR = Path(os.environ.get("TICO_AGENT_CONFIG_DIR") or Path.home() / ".config" / "tico" / "agents")
EVERY_SECONDS = 60
MCP_SERVER_NAME = "tico"
ENV_TOKEN = "TICO_AGENT_TOKEN"
ENV_URL = "TICO_URL"
BACKOFF_SECONDS = 3600      # one heartbeat an hour for a bot that is archived or whose credential is revoked
LABEL = "tico-agent"


class Failure(Exception):
    """Something to tell the person in one line. A failed call also carries what the hub answered."""

    def __init__(self, message, status=None, code="", detail=""):
        super().__init__(message)
        self.status, self.code, self.detail = status, code, detail


# ----------------------------------------------------------------------------- the hub
def _open(url, token, method, path, body=None, timeout=15, headers=None):
    """One call to the hub, returning the response bytes. Always sends this connector's own
    User-Agent: Cloudflare in front of a hub blocks Python's default one (error 1010)."""
    data = json.dumps(body).encode() if body is not None else None
    head = {"Accept": "application/json", "User-Agent": "tico-hermes-agent/" + VERSION}
    if token:
        head["Authorization"] = "Bearer " + token
    if data is not None:
        head["Content-Type"] = "application/json"
        head["Idempotency-Key"] = os.urandom(16).hex()
    head.update(headers or {})
    req = urllib.request.Request(url.rstrip("/") + path, data=data, method=method, headers=head)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            return response.read()
    except urllib.error.HTTPError as exc:
        code = detail = ""
        try:
            error = json.loads(exc.read().decode()).get("error", {})
            code, detail = str(error.get("code", "")), str(error.get("detail", ""))
        except (ValueError, AttributeError):
            pass
        raise Failure(f"{method} {path}: HTTP {exc.code}" + (f": {detail}" if detail else ""),
                      status=exc.code, code=code, detail=detail)
    except urllib.error.URLError as exc:
        raise Failure(f"{method} {path}: {exc.reason}")
    except OSError as exc:
        raise Failure(f"{method} {path}: {exc}")


def request(url, token, method, path, body=None, timeout=15, headers=None):
    return json.loads(_open(url, token, method, path, body, timeout, headers).decode() or "{}")


# ----------------------------------------------------------------------------- the profile
def hermes_home():
    return Path(os.environ.get("HERMES_HOME") or Path.home() / ".hermes").expanduser()


def profile_dir(profile):
    """A profile is a separate Hermes home; `default` is the home itself."""
    if profile in ("", "default"):
        return hermes_home()
    return hermes_home() / "profiles" / profile


def hermes_version():
    exe = shutil.which("hermes")
    if not exe:
        return ""
    try:
        out = subprocess.run([exe, "--version"], capture_output=True, text=True, timeout=20)
    except (OSError, subprocess.SubprocessError):
        return ""
    match = re.search(r"v?(\d+\.\d+\.\d+\S*)", (out.stdout or out.stderr).splitlines()[0] if (out.stdout or out.stderr) else "")
    return match.group(1)[:100] if match else ""


def read_model(directory):
    """`model.default` and `model.provider` from the profile's config.yaml, without PyYAML."""
    path = directory / "config.yaml"
    try:
        lines = path.read_text().splitlines()
    except OSError:
        return "", ""
    model = provider = ""
    inside = False
    for line in lines:
        if re.match(r"^model:\s*$", line):
            inside = True
            continue
        if inside and line and not line.startswith(" "):
            inside = False
        if inside:
            m = re.match(r"^\s+(default|provider):\s*(.+?)\s*$", line)
            if m:
                value = m.group(2).strip().strip("'\"")
                if m.group(1) == "default":
                    model = value
                else:
                    provider = value
    return model[:200], provider[:100]


def gateway_running(directory):
    try:
        pid = int((directory / "gateway.pid").read_text().strip())
        os.kill(pid, 0)
        return True
    except (OSError, ValueError):
        return False


def write_private(path, text):
    """Write a file that only its owner can read, all at once: nobody ever sees a half file or a wide mode."""
    path = Path(path)
    tmp = path.with_name(path.name + ".tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as handle:
        handle.write(text)
    os.chmod(tmp, 0o600)
    os.replace(tmp, path)


def upsert_env(directory, values):
    path = directory / ".env"
    lines = path.read_text().splitlines() if path.exists() else []
    keys = set(values)
    kept = [line for line in lines if not any(line.startswith(k + "=") for k in keys)]
    kept += [f"{k}={v}" for k, v in values.items()]
    write_private(path, "\n".join(kept) + "\n")


def remove_env(directory, keys):
    path = directory / ".env"
    if not path.exists():
        return
    lines = [line for line in path.read_text().splitlines() if not any(line.startswith(k + "=") for k in keys)]
    path.write_text("\n".join(lines) + ("\n" if lines else ""))


def upsert_mcp(directory, url):
    """Put the hub in `mcp_servers.<tico>` of the profile's config.yaml, keeping the rest.
    With PyYAML the document is rewritten; without it a block is appended when no
    `mcp_servers:` exists yet, and otherwise the person is told what to paste."""
    path = directory / "config.yaml"
    entry = {"url": url.rstrip("/") + "/api/v2/mcp",
             "headers": {"Authorization": "Bearer ${" + ENV_TOKEN + "}"}}
    try:
        import yaml  # noqa: F401
    except ImportError:
        yaml = None
    if yaml:
        config = yaml.safe_load(path.read_text()) if path.exists() else {}
        config = config if isinstance(config, dict) else {}
        servers = config.get("mcp_servers")
        if not isinstance(servers, dict):
            servers = {}
        servers[MCP_SERVER_NAME] = entry
        config["mcp_servers"] = servers
        backup = path.with_suffix(".yaml.tico-bak")
        if path.exists():
            shutil.copy2(path, backup)
        path.write_text(yaml.safe_dump(config, sort_keys=False, allow_unicode=True))
        return "written"
    text = path.read_text() if path.exists() else ""
    block = ("\nmcp_servers:\n  " + MCP_SERVER_NAME + ":\n    url: \"" + entry["url"] + "\"\n"
             "    headers:\n      Authorization: \"Bearer ${" + ENV_TOKEN + "}\"\n")
    if re.search(r"^mcp_servers:", text, re.M):
        print("config.yaml already has mcp_servers and PyYAML is not installed here; add this under it:\n"
              + block.replace("\nmcp_servers:\n", ""), file=sys.stderr)
        return "manual"
    path.write_text(text.rstrip("\n") + "\n" + block)
    return "appended"


def remove_mcp(directory):
    path = directory / "config.yaml"
    try:
        import yaml
    except ImportError:
        print("PyYAML is not installed here; remove mcp_servers." + MCP_SERVER_NAME + " from "
              + str(path) + " by hand", file=sys.stderr)
        return
    if not path.exists():
        return
    config = yaml.safe_load(path.read_text()) or {}
    servers = config.get("mcp_servers") if isinstance(config, dict) else None
    if isinstance(servers, dict) and MCP_SERVER_NAME in servers:
        del servers[MCP_SERVER_NAME]
        if not servers:
            del config["mcp_servers"]
        path.write_text(yaml.safe_dump(config, sort_keys=False, allow_unicode=True))


# ----------------------------------------------------------------------------- our config
def config_path(profile):
    return CONFIG_DIR / (profile + ".json")


def load_config(profile):
    path = config_path(profile)
    try:
        mode = stat.S_IMODE(path.stat().st_mode)
        if mode & 0o077:
            raise Failure(f"{path} must be readable only by its owner (chmod 600)")
        return json.loads(path.read_text())
    except OSError:
        raise Failure(f"No agent configuration for profile {profile!r}; run pair (or install) first")


def save_config(profile, value):
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    path = config_path(profile)
    write_private(path, json.dumps(value, indent=2))
    return path


def installed_copy():
    """The timer runs a copy under our config dir, so a downloaded file in Downloads can go."""
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    target = CONFIG_DIR / "hermes_agent.py"
    source = Path(__file__).resolve()
    if source != target.resolve():
        write_private(target, source.read_text())
    return target


# ----------------------------------------------------------------------------- the timer
def timer_label(profile):
    return "team.tico-agent." + profile


def install_timer(profile, python):
    script = installed_copy()
    log_dir = CONFIG_DIR / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    log = log_dir / (profile + ".log")
    if sys.platform == "darwin":
        agents = Path.home() / "Library" / "LaunchAgents"
        agents.mkdir(parents=True, exist_ok=True)
        plist = agents / (timer_label(profile) + ".plist")
        plistlib.dump({"Label": timer_label(profile),
                       "ProgramArguments": [python, str(script), "heartbeat", "--profile", profile],
                       "StartInterval": EVERY_SECONDS, "RunAtLoad": True,
                       "StandardOutPath": str(log), "StandardErrorPath": str(log),
                       "EnvironmentVariables": {"PATH": os.environ.get("PATH", "/usr/bin:/bin"),
                                                "HOME": str(Path.home())}},
                      plist.open("wb"))
        os.chmod(plist, 0o600)
        subprocess.run(["launchctl", "bootout", f"gui/{os.getuid()}", str(plist)], capture_output=True)
        done = subprocess.run(["launchctl", "bootstrap", f"gui/{os.getuid()}", str(plist)], capture_output=True, text=True)
        if done.returncode != 0:
            raise Failure("launchctl bootstrap failed: " + (done.stderr or done.stdout).strip())
        return f"launchd job {timer_label(profile)} every {EVERY_SECONDS} s, log {log}"
    if sys.platform.startswith("linux") and shutil.which("systemctl"):
        units = Path.home() / ".config" / "systemd" / "user"
        units.mkdir(parents=True, exist_ok=True)
        name = "tico-agent-" + profile
        (units / (name + ".service")).write_text(
            "[Unit]\nDescription=Tico heartbeat for Hermes profile " + profile + "\n\n"
            "[Service]\nType=oneshot\nExecStart=" + python + " " + str(script) + " heartbeat --profile " + profile + "\n")
        (units / (name + ".timer")).write_text(
            "[Unit]\nDescription=Tico heartbeat timer for Hermes profile " + profile + "\n\n"
            "[Timer]\nOnBootSec=30\nOnUnitActiveSec=" + str(EVERY_SECONDS) + "s\nAccuracySec=5s\n\n"
            "[Install]\nWantedBy=timers.target\n")
        for command in (["systemctl", "--user", "daemon-reload"],
                        ["systemctl", "--user", "enable", "--now", name + ".timer"]):
            done = subprocess.run(command, capture_output=True, text=True)
            if done.returncode != 0:
                raise Failure(" ".join(command) + " failed: " + (done.stderr or done.stdout).strip())
        return f"systemd user timer {name}.timer every {EVERY_SECONDS} s"
    raise Failure("No timer installed: this is neither macOS nor a Linux with systemd. Run "
                  f"`{python} {script} heartbeat --profile {profile}` from cron every minute instead")


def remove_timer(profile):
    if sys.platform == "darwin":
        plist = Path.home() / "Library" / "LaunchAgents" / (timer_label(profile) + ".plist")
        if plist.exists():
            subprocess.run(["launchctl", "bootout", f"gui/{os.getuid()}", str(plist)], capture_output=True)
            plist.unlink()
        return
    if sys.platform.startswith("linux") and shutil.which("systemctl"):
        name = "tico-agent-" + profile
        subprocess.run(["systemctl", "--user", "disable", "--now", name + ".timer"], capture_output=True)
        units = Path.home() / ".config" / "systemd" / "user"
        for suffix in (".service", ".timer"):
            (units / (name + suffix)).unlink(missing_ok=True)
        subprocess.run(["systemctl", "--user", "daemon-reload"], capture_output=True)


def _suffixed(name, profile):
    """True for `team.tico-agent.scout`, `com.tidy.tico-agent.scout`, `tico-agent-scout`: any name
    that ends in `tico-agent.<profile>` or `tico-agent-<profile>` on a word boundary."""
    for sep in (".", "-"):
        tail = LABEL + sep + profile
        if name.endswith(tail) and (name == tail or name[-len(tail) - 1] in ".-_"):
            return True
    return False


def remove_old_timers(profile):
    """Earlier versions labelled the launchd job `com.tidy.tico-agent.<profile>` (an environment's name
    on a public connector); a reinstall under the current label would leave two heartbeats. Remove any
    other job or unit for this profile that runs a hermes_agent.py. Returns what was removed."""
    removed = []
    current = timer_label(profile)
    if sys.platform == "darwin":
        agents = Path.home() / "Library" / "LaunchAgents"
        for plist in sorted(agents.glob("*.plist")) if agents.is_dir() else []:
            try:
                job = plistlib.loads(plist.read_bytes())
            except (OSError, ValueError, plistlib.InvalidFileException):
                continue
            label = str(job.get("Label") or plist.stem)
            arguments = [str(a) for a in job.get("ProgramArguments") or []]
            if label == current or plist.stem == current or not _suffixed(label, profile):
                continue
            if not any(a.endswith("hermes_agent.py") for a in arguments):
                continue
            subprocess.run(["launchctl", "bootout", f"gui/{os.getuid()}", str(plist)], capture_output=True)
            plist.unlink(missing_ok=True)
            removed.append("launchd job " + label)
    elif sys.platform.startswith("linux") and shutil.which("systemctl"):
        units = Path.home() / ".config" / "systemd" / "user"
        current_name = "tico-agent-" + profile
        stems = sorted({u.stem for u in units.glob("*.service")} | {u.stem for u in units.glob("*.timer")}) if units.is_dir() else []
        changed = False
        for stem in stems:
            if stem == current_name or not _suffixed(stem, profile):
                continue
            try:
                text = (units / (stem + ".service")).read_text()
            except OSError:
                continue
            if "hermes_agent.py" not in text:
                continue
            subprocess.run(["systemctl", "--user", "disable", "--now", stem + ".timer"], capture_output=True)
            for suffix in (".service", ".timer"):
                (units / (stem + suffix)).unlink(missing_ok=True)
            removed.append("systemd unit " + stem)
            changed = True
        if changed:
            subprocess.run(["systemctl", "--user", "daemon-reload"], capture_output=True)
    return removed


def timer_loaded(profile):
    """(loaded, note): is the heartbeat timer known to launchd or systemd right now."""
    if sys.platform == "darwin":
        done = subprocess.run(["launchctl", "print", f"gui/{os.getuid()}/{timer_label(profile)}"],
                              capture_output=True, text=True)
        return done.returncode == 0, "launchd job " + timer_label(profile)
    if sys.platform.startswith("linux") and shutil.which("systemctl"):
        name = "tico-agent-" + profile + ".timer"
        done = subprocess.run(["systemctl", "--user", "is-active", name], capture_output=True, text=True)
        return done.returncode == 0 and done.stdout.strip() == "active", "systemd user timer " + name
    return False, "no launchd or systemd here"


# ----------------------------------------------------------------------------- install, shared
def perform_install(profile, directory, url, bot, token, no_timer=False):
    """The steps `install`, `pair` and `update` all end in. Never prints the token."""
    url = url.rstrip("/")
    me = request(url, token, "GET", "/api/v2/me")
    if me.get("role") != "bot" or me.get("actor") != "bot:" + bot or not me.get("agent"):
        raise Failure(f"This token is not the agent credential for bot {bot!r}: the hub says "
                      f"{me.get('actor')!r} ({me.get('role')!r})")
    upsert_env(directory, {ENV_TOKEN: token, ENV_URL: url})
    mcp = upsert_mcp(directory, url)
    python = sys.executable
    config = {"url": url, "bot": bot, "token": token, "profile": profile,
              "profile_dir": str(directory), "python": python, "harness": me.get("agent")}
    path = save_config(profile, config)
    reply = request(url, token, "POST", "/api/v2/agents/heartbeat", heartbeat_body(profile, directory))
    config["last_reply"] = reply
    config["last_ok"] = time.time()
    timer = ""
    if not no_timer:
        timer = install_timer(profile, python)
        config["timer"] = timer
    save_config(profile, config)
    removed = remove_old_timers(profile)
    print(f"Registered Hermes profile {profile!r} as bot {bot!r} at {url}")
    print(f"  MCP server `{MCP_SERVER_NAME}` in {directory / 'config.yaml'}: {mcp}; token in {directory / '.env'}")
    print(f"  credential saved in {path}")
    print(f"  heartbeat: {timer or 'none (run `heartbeat` yourself every minute)'}")
    for name in removed:
        print(f"  removed the older {name} for this profile, so there is one heartbeat")
    waiting = reply.get("waiting", {})
    print(f"  the hub sees it: {waiting.get('messages', 0)} message(s) and {waiting.get('tasks', 0)} task(s) waiting")
    if mcp == "written":
        print("  restart the profile's gateway or chat so it loads the new MCP server (`/reload-mcp` in a chat)")
    return 0


def profile_directory(profile, given=None):
    directory = Path(given).expanduser() if given else profile_dir(profile)
    if not directory.is_dir():
        raise Failure(f"No Hermes profile directory at {directory}; create the profile first "
                      f"(`hermes profile create {profile}`) or pass --profile-dir")
    return directory


# ----------------------------------------------------------------------------- commands
def heartbeat_body(profile, directory):
    model, provider = read_model(directory)
    return {"version": hermes_version(), "platform": sys.platform + " " + platform.machine(),
            "model": model, "provider": provider, "profile": profile,
            "detail": ("gateway running" if gateway_running(directory) else "gateway not running")
                      + "; heartbeat " + VERSION}


def blocked_message(failure, bot):
    """The one line for a heartbeat the hub refuses for good reasons, or ''. The timer keeps
    trying, but once an hour, so a forgotten profile does not hammer the hub every minute."""
    if failure.status == 409 and (failure.code == "bot_archived" or "archived" in failure.detail.lower()):
        return f"Bot {bot} is archived in Tico: restore it (ask BotOps) or run uninstall"
    if failure.status == 401:
        return f"Bot {bot}: credential revoked: run pair again"
    return ""


def cmd_heartbeat(args):
    config = load_config(args.profile)
    hold = config.get("backoff") or {}
    if hold.get("until", 0) > time.time():
        return 0
    directory = Path(config.get("profile_dir") or profile_dir(args.profile))
    try:
        reply = request(config["url"], config["token"], "POST", "/api/v2/agents/heartbeat",
                        heartbeat_body(args.profile, directory))
    except Failure as exc:
        message = blocked_message(exc, config.get("bot", args.profile))
        if not message:
            raise
        config["backoff"] = {"until": time.time() + BACKOFF_SECONDS, "since": hold.get("since") or time.time(),
                             "reason": exc.code or str(exc.status), "message": message}
        save_config(args.profile, config)
        print(message, file=sys.stderr)
        return 1
    config["last_reply"] = reply
    config["last_ok"] = time.time()
    if config.pop("backoff", None):
        print(f"Bot {config.get('bot', '')} answers again: heartbeat back to every {EVERY_SECONDS} s")
    save_config(args.profile, config)
    waiting = reply.get("waiting", {})
    print(f"{reply.get('server_time', '')} {reply.get('bot', '')}: {waiting.get('messages', 0)} message(s), "
          f"{waiting.get('tasks', 0)} task(s) waiting")
    return 0


def cmd_status(args):
    config = load_config(args.profile)
    print(json.dumps({k: config.get(k) for k in ("url", "bot", "profile", "profile_dir", "python", "timer",
                                                 "last_reply", "backoff")}, indent=2))
    return 0


def cmd_install(args):
    directory = profile_directory(args.profile, args.profile_dir)
    return perform_install(args.profile, directory, args.url, args.bot, args.token, args.no_timer)


def pair_code_sentence(profile, code):
    return f"connect my Hermes profile {profile}, code {code}"


def cmd_pair(args):
    directory = profile_directory(args.profile, args.profile_dir)
    url = args.url.rstrip("/")
    created = request(url, None, "POST", "/api/v2/agents/pairings",
                      {"profile": args.profile, "harness": "hermes",
                       "host": socket.gethostname().split(".")[0], "version": VERSION})
    pairing, code, secret = created.get("pairing_id"), created.get("code"), created.get("secret")
    if not (pairing and code and secret):
        raise Failure("The hub did not start a pairing; is this the hub's runner address?")
    wait = max(1, int(created.get("expires_in") or 600))
    every = min(30, max(1, int(created.get("poll_every") or 3)))
    print(f"Tell BotOps (or press Pair on the bot in Settings → Bots): {pair_code_sentence(args.profile, code)}")
    print(f"Waiting for approval (the code works for {wait // 60 or 1} minute(s); Ctrl-C to stop)...", flush=True)
    deadline = time.monotonic() + wait
    trouble = 0
    try:
        while True:
            try:
                answer = request(url, None, "GET", "/api/v2/agents/pairings/" + str(pairing),
                                 headers={"X-Pairing-Secret": secret})
                trouble = 0
            except Failure as exc:
                if exc.status is not None and exc.status < 500 and exc.status != 429:
                    raise Failure("The hub no longer knows this pairing; run pair again") from exc
                trouble += 1
                if trouble >= 10:
                    raise
                answer = {"state": "pending"}
            state = answer.get("state")
            if state == "approved":
                break
            if state == "expired":
                raise Failure(f"The code {code} expired before anyone approved it; run pair again")
            if state == "declined":
                raise Failure(f"The code {code} was declined in Tico; nothing was changed on this computer")
            if state not in ("pending", None):
                raise Failure(f"The pairing is {state}; run pair again")
            if time.monotonic() >= deadline:
                raise Failure(f"The code {code} expired before anyone approved it; run pair again")
            time.sleep(every)
    except KeyboardInterrupt:
        print("\nStopped. The code stays valid until it expires but nothing was changed here.", file=sys.stderr)
        return 130
    bot, token = answer.get("bot"), answer.get("token")
    if not bot or not token:
        raise Failure("The hub approved the pairing without a bot or credential; run pair again")
    print(f"Approved for bot {bot!r}.")
    return perform_install(args.profile, directory, answer.get("url") or url, bot, token, args.no_timer)


def fetch_script(url, token):
    text = _open(url, token, "GET", "/api/v2/agents/setup-script", timeout=30, headers={"Accept": "text/plain"}).decode()
    try:
        ast.parse(text)
    except SyntaxError:
        raise Failure("The hub did not send a Python file (a sign-in page, perhaps); nothing was replaced")
    if "def cmd_heartbeat" not in text or "tico-hermes-agent" not in text:
        raise Failure("The download is not the Hermes connector; nothing was replaced")
    return text


def script_version(text):
    match = re.search(r'^VERSION = "([^"]+)"', text, re.M)
    return match.group(1) if match else "?"


def cmd_update(args):
    config = load_config(args.profile)
    text = fetch_script(config["url"], config["token"])
    target = CONFIG_DIR / "hermes_agent.py"
    before = script_version(target.read_text()) if target.exists() else VERSION
    write_private(target, text)
    after = script_version(text)
    print(f"Connector {before} -> {after} in {target}" if before != after else f"Connector is current ({after}); reinstalled it in {target}")
    # The new file does the install, so a newer connector's steps apply now, not on the next update.
    done = subprocess.run([config.get("python") or sys.executable, str(target), "reinstall", "--profile", args.profile])
    if done.returncode != 0:
        raise Failure("The new connector could not finish installing; see above")
    return 0


def cmd_reinstall(args):
    """Run the install steps again with what `install` or `pair` saved."""
    config = load_config(args.profile)
    directory = profile_directory(args.profile, config.get("profile_dir"))
    return perform_install(args.profile, directory, config["url"], config["bot"], config["token"],
                           no_timer=not config.get("timer"))


# Tools renamed in Tico 0.2.21 (CHANGELOG, Breaking changes), old -> new. Names ending in `_` are prefixes.
RENAMED_TOOLS = {
    "hub_say": "hub_message_send", "hub_notice": "hub_message_send (fyi)", "hub_inbox": "hub_message_list",
    "hub_ack": "hub_message_mark_read", "hub_history": "hub_conversation_show",
    "hub_ask": "hub_question_ask", "hub_answer": "hub_question_answer",
    "hub_board": "hub_task_list (all)", "hub_task_stuck": "hub_task_list (stuck)",
    "hub_goals": "hub_goal_list", "hub_goal_auto": "hub_goal_status (auto)", "hub_kpi_add": "hub_kpi_create",
    "hub_context_search": "hub_doc_search", "hub_context_show": "hub_doc_read",
    "hub_meetings_transcript": "hub_meeting_read", "hub_bot_register": "hub_bot_create",
    "hub_bot_set": "hub_bot_update", "hub_bot_onboarded": "hub_bot_setup_done", "hub_turns": "hub_run_list",
    "hub_fleet": "hub_health_check", "hub_fleet-check": "hub_health_check", "hub_fleet_check": "hub_health_check",
    "hub_computers": "hub_computer_list", "hub_catalog": "hub_template_list",
    "hub_routine_on": "hub_routine_update (enabled)", "hub_routine_off": "hub_routine_update (enabled)",
    "hub_org": "hub_team_show", "hub_updates": "hub_update_list",
    "hub_integrations": "hub_tool_*", "hub_integration": "hub_tool_*", "hub_queries": "hub_tool_*",
    "hub_learn": "hub_tool_*", "hub_decisions": "hub_decision_ask",
    "hub_judge": "hub_decision_ask", "hub_listen_judge": "hub_listening_*",
    "hub_docs_": "hub_doc_", "hub_files_": "hub_file_", "hub_status_": "hub_bot_status_",
    "hub_people_": "hub_human_", "hub_person_": "hub_human_", "hub_tools_": "hub_tool_",
    "hub_batch_": "hub_needs_you_", "hub_listen_": "hub_listening_", "hub_intake_": "hub_listening_",
}
TOOL_WORD = re.compile(r"\bhub_[A-Za-z0-9_]+(?:-check)?")
SCAN_LIMIT = 2_000_000
MAX_SHOWN = 100


def new_tool_name(word):
    if word in RENAMED_TOOLS:
        return RENAMED_TOOLS[word]
    for old, new in RENAMED_TOOLS.items():
        if old.endswith("_") and word.startswith(old):
            return new + (word[len(old):] or "*")
    return ""


def scan_old_tool_names(directory):
    """(file, line number, old name, new name) for each renamed tool a profile's own text still uses:
    SOUL.md, skills/, cron definitions and memories/. Reads only; never edits."""
    roots = [directory / "SOUL.md", directory / "skills", directory / "cron", directory / "memories"]
    roots += sorted(directory.glob("cron*.json")) + sorted(directory.glob("cron*.yaml")) + sorted(directory.glob("cron*.yml"))
    found = []
    for root in roots:
        files = [root] if root.is_file() else sorted(f for f in root.rglob("*") if f.is_file()) if root.is_dir() else []
        for path in files:
            if any(part.startswith(".") for part in path.relative_to(directory).parts):
                continue
            try:
                if path.stat().st_size > SCAN_LIMIT:
                    continue
                lines = path.read_text(encoding="utf-8").splitlines()
            except (OSError, UnicodeDecodeError):
                continue
            for number, line in enumerate(lines, 1):
                for word in TOOL_WORD.findall(line):
                    new = new_tool_name(word)
                    if new:
                        found.append((path, number, word, new))
    return found


def env_value(directory, key):
    try:
        for line in (directory / ".env").read_text().splitlines():
            if line.startswith(key + "="):
                return line[len(key) + 1:].strip().strip("'\"")
    except OSError:
        pass
    return ""


def mcp_url(directory):
    """The url of `mcp_servers.tico` in config.yaml, '' when there is none."""
    try:
        text = (directory / "config.yaml").read_text()
    except OSError:
        return ""
    try:
        import yaml
        config = yaml.safe_load(text)
        entry = ((config or {}).get("mcp_servers") or {}).get(MCP_SERVER_NAME) if isinstance(config, dict) else None
        return str(entry.get("url") or "(no url)") if isinstance(entry, dict) else ""
    except ImportError:
        pass
    except Exception:
        return ""
    inside = seen = False
    for line in text.splitlines():
        if re.match(r"^mcp_servers:\s*$", line):
            inside = True
        elif inside and line and not line.startswith((" ", "\t", "#")):
            inside = False
        elif inside and re.match(r"^\s+" + MCP_SERVER_NAME + r":\s*$", line):
            seen = True
        elif inside and seen:
            m = re.match(r"^\s+url:\s*(.+?)\s*$", line)
            if m:
                return m.group(1).strip("'\"")
    return "(no url)" if seen else ""


def cmd_doctor(args):
    problems = []

    def say(level, text):
        if level == "problem":
            problems.append(text)
        print(f"  {level.upper() if level != 'ok' else 'ok':<7} {text}")

    print(f"Hermes profile {args.profile!r}, connector {VERSION}")
    path = config_path(args.profile)
    config = {}
    try:
        mode = stat.S_IMODE(path.stat().st_mode)
        config = json.loads(path.read_text())
        if mode & 0o077:
            say("problem", f"credential file {path} is mode {mode:03o}; run chmod 600 on it")
        else:
            say("ok", f"credential file {path} exists, mode 600")
    except (OSError, ValueError) as exc:
        say("problem", f"no usable credential file at {path} ({exc.__class__.__name__}); run pair")
    directory = Path(config.get("profile_dir") or profile_dir(args.profile))
    if not directory.is_dir():
        say("problem", f"profile directory {directory} does not exist")
        return 1

    found = mcp_url(directory)
    expected = config.get("url", "").rstrip("/") + "/api/v2/mcp" if config.get("url") else ""
    if not found:
        say("problem", f"config.yaml has no mcp_servers.{MCP_SERVER_NAME} entry; run update")
    elif expected and found != expected:
        say("problem", f"mcp_servers.{MCP_SERVER_NAME} points at {found}, the credential file says {expected}; run update")
    else:
        say("ok", f"mcp_servers.{MCP_SERVER_NAME} is in config.yaml ({found})")

    token = env_value(directory, ENV_TOKEN)
    if not token:
        say("problem", f"{ENV_TOKEN} is missing from {directory / '.env'}; run update")
    elif config.get("token") and token != config["token"]:
        say("problem", f"{ENV_TOKEN} in .env is not the credential file's token; run update")
    else:
        say("ok", f"{ENV_TOKEN} is present in .env")

    loaded, note = timer_loaded(args.profile)
    say("ok" if loaded else "problem", f"heartbeat timer ({note}) is " + ("loaded" if loaded else "not loaded; run update"))

    reply = config.get("last_reply")
    last_ok = config.get("last_ok")
    if not reply:
        say("problem", "no heartbeat has been answered yet")
    else:
        when = reply.get("server_time", "?")
        age = f", {int(time.time() - last_ok)} s ago" if last_ok else ""
        waiting = reply.get("waiting", {})
        say("ok", f"last heartbeat reply {when}{age}: {waiting.get('messages', 0)} message(s), "
                  f"{waiting.get('tasks', 0)} task(s) waiting")
        if last_ok and time.time() - last_ok > 180:
            say("warn", "the last good heartbeat is more than three minutes old; the bot shows offline")
    hold = config.get("backoff")
    if hold:
        say("problem", hold.get("message", "heartbeats are paused") + " (retrying once an hour)")

    if config.get("url") and config.get("token"):
        try:
            me = request(config["url"], config["token"], "GET", "/api/v2/me")
            if me.get("actor") == "bot:" + str(config.get("bot")):
                say("ok", f"GET /api/v2/me works: {me.get('actor')} ({me.get('agent') or me.get('role')})")
            else:
                say("problem", f"GET /api/v2/me answers {me.get('actor')!r}, not bot:{config.get('bot')}")
        except Failure as exc:
            message = blocked_message(exc, config.get("bot", args.profile)) or str(exc)
            say("problem", "GET /api/v2/me failed: " + message)

    old = scan_old_tool_names(directory)
    if old:
        say("warn", f"{len(old)} use(s) of tool names renamed in Tico 0.2.21 (not edited; change them by hand):")
        for file, number, word, new in old[:MAX_SHOWN]:
            print(f"            {file}:{number}: {word} -> {new}")
        if len(old) > MAX_SHOWN:
            print(f"            ... and {len(old) - MAX_SHOWN} more")
    else:
        say("ok", "SOUL.md, skills, cron and memories use no old tool names")
    print("Everything needed is working." if not problems else f"{len(problems)} problem(s) found.")
    return 1 if problems else 0


def cmd_uninstall(args):
    try:
        config = load_config(args.profile)
    except Failure:
        config = {}
    directory = Path(config.get("profile_dir") or profile_dir(args.profile))
    remove_timer(args.profile)
    remove_old_timers(args.profile)
    if directory.is_dir():
        remove_env(directory, [ENV_TOKEN, ENV_URL])
        remove_mcp(directory)
    config_path(args.profile).unlink(missing_ok=True)
    print(f"Removed the hub from Hermes profile {args.profile!r}. Revoke its credential in Settings → Bots too.")
    return 0


def parser():
    p = argparse.ArgumentParser(description="Register a Hermes profile with the hub and keep its heartbeat.")
    sub = p.add_subparsers(dest="command", required=True)
    s = sub.add_parser("install", help="wire the profile to the hub and start the heartbeat timer")
    s.add_argument("--profile", required=True, help="the Hermes profile name (`default` for ~/.hermes itself)")
    s.add_argument("--url", required=True, help="the hub's origin, for example https://tico.example.com")
    s.add_argument("--bot", required=True, help="the bot slug this profile is")
    s.add_argument("--token", required=True, help="the agent credential from Settings → Bots")
    s.add_argument("--profile-dir", help="the profile directory when it is not under ~/.hermes")
    s.add_argument("--no-timer", action="store_true", help="do not install a launchd/systemd timer")
    s.set_defaults(fn=cmd_install)
    s = sub.add_parser("pair", help="connect the profile to a bot with a code, no token to copy")
    s.add_argument("--profile", required=True, help="the Hermes profile name (`default` for ~/.hermes itself)")
    s.add_argument("--url", required=True, help="the hub's runner address, for example https://runner.example.com")
    s.add_argument("--profile-dir", help="the profile directory when it is not under ~/.hermes")
    s.add_argument("--no-timer", action="store_true", help="do not install a launchd/systemd timer")
    s.set_defaults(fn=cmd_pair)
    for name, fn, help_text in (("heartbeat", cmd_heartbeat, "post one heartbeat (what the timer runs)"),
                                ("status", cmd_status, "the saved configuration and the last reply"),
                                ("update", cmd_update, "download the newest connector from the hub and install again"),
                                ("reinstall", cmd_reinstall, "run the install steps again with the saved credential"),
                                ("doctor", cmd_doctor, "check the wiring and list old tool names (changes nothing)"),
                                ("uninstall", cmd_uninstall, "remove the timer, the env line and the MCP entry")):
        s = sub.add_parser(name, help=help_text)
        s.add_argument("--profile", required=True)
        s.set_defaults(fn=fn)
    return p


def main(argv=None):
    args = parser().parse_args(argv)
    try:
        return args.fn(args)
    except Failure as exc:
        print("error: " + str(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
