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
    python3 hermes_agent.py heartbeat --profile scout    # what the timer runs
    python3 hermes_agent.py status --profile scout       # the last reply, and what is waiting
    python3 hermes_agent.py uninstall --profile scout    # timer, config entry and env line

The heartbeat is a plain HTTP call, never an agent turn: it proves the box and the profile are
there, not that the model works. What the agent does with the hub is visible on its bot page
like any bot's. See docs/hermes-agents.md.
"""

import argparse
import json
import os
import platform
import plistlib
import re
import shutil
import stat
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path

VERSION = "0.1.0"
CONFIG_DIR = Path(os.environ.get("TICO_AGENT_CONFIG_DIR") or Path.home() / ".config" / "tico" / "agents")
EVERY_SECONDS = 60
MCP_SERVER_NAME = "tico"
ENV_TOKEN = "TICO_AGENT_TOKEN"
ENV_URL = "TICO_URL"


class Failure(Exception):
    pass


# ----------------------------------------------------------------------------- the hub
def request(url, token, method, path, body=None, timeout=15):
    data = json.dumps(body).encode() if body is not None else None
    headers = {"Authorization": "Bearer " + token, "Accept": "application/json",
               "User-Agent": "tico-hermes-agent/" + VERSION}
    if data is not None:
        headers["Content-Type"] = "application/json"
        headers["Idempotency-Key"] = os.urandom(16).hex()
    req = urllib.request.Request(url.rstrip("/") + path, data=data, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            return json.loads(response.read().decode() or "{}")
    except urllib.error.HTTPError as exc:
        try:
            detail = json.loads(exc.read().decode()).get("error", {}).get("detail", "")
        except (ValueError, AttributeError):
            detail = ""
        raise Failure(f"{method} {path}: HTTP {exc.code}" + (f": {detail}" if detail else ""))
    except urllib.error.URLError as exc:
        raise Failure(f"{method} {path}: {exc.reason}")


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


def upsert_env(directory, values):
    path = directory / ".env"
    lines = path.read_text().splitlines() if path.exists() else []
    keys = set(values)
    kept = [line for line in lines if not any(line.startswith(k + "=") for k in keys)]
    kept += [f"{k}={v}" for k, v in values.items()]
    path.write_text("\n".join(kept) + "\n")
    os.chmod(path, 0o600)


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
        raise Failure(f"No agent configuration for profile {profile!r}; run install first")


def save_config(profile, value):
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    path = config_path(profile)
    path.write_text(json.dumps(value, indent=2))
    os.chmod(path, 0o600)
    return path


def installed_copy():
    """The timer runs a copy under our config dir, so a downloaded file in Downloads can go."""
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    target = CONFIG_DIR / "hermes_agent.py"
    source = Path(__file__).resolve()
    if source != target.resolve():
        shutil.copy2(source, target)
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


# ----------------------------------------------------------------------------- commands
def heartbeat_body(profile, directory):
    model, provider = read_model(directory)
    return {"version": hermes_version(), "platform": sys.platform + " " + platform.machine(),
            "model": model, "provider": provider, "profile": profile,
            "detail": ("gateway running" if gateway_running(directory) else "gateway not running")
                      + "; heartbeat " + VERSION}


def cmd_heartbeat(args):
    config = load_config(args.profile)
    directory = Path(config.get("profile_dir") or profile_dir(args.profile))
    reply = request(config["url"], config["token"], "POST", "/api/v2/agents/heartbeat",
                    heartbeat_body(args.profile, directory))
    config["last_reply"] = reply
    save_config(args.profile, config)
    waiting = reply.get("waiting", {})
    print(f"{reply.get('server_time', '')} {reply.get('bot', '')}: {waiting.get('messages', 0)} message(s), "
          f"{waiting.get('tasks', 0)} task(s) waiting")
    return 0


def cmd_status(args):
    config = load_config(args.profile)
    print(json.dumps({k: config.get(k) for k in ("url", "bot", "profile", "profile_dir", "python", "timer", "last_reply")},
                     indent=2))
    return 0


def cmd_install(args):
    directory = Path(args.profile_dir) if args.profile_dir else profile_dir(args.profile)
    if not directory.is_dir():
        raise Failure(f"No Hermes profile directory at {directory}; create the profile first "
                      f"(`hermes profile create {args.profile}`) or pass --profile-dir")
    me = request(args.url, args.token, "GET", "/api/v2/me")
    if me.get("role") != "bot" or me.get("actor") != "bot:" + args.bot or not me.get("agent"):
        raise Failure(f"This token is not the agent credential for bot {args.bot!r}: the hub says "
                      f"{me.get('actor')!r} ({me.get('role')!r})")
    upsert_env(directory, {ENV_TOKEN: args.token, ENV_URL: args.url.rstrip("/")})
    mcp = upsert_mcp(directory, args.url)
    python = sys.executable
    config = {"url": args.url.rstrip("/"), "bot": args.bot, "token": args.token, "profile": args.profile,
              "profile_dir": str(directory), "python": python, "harness": me.get("agent")}
    path = save_config(args.profile, config)
    reply = request(args.url, args.token, "POST", "/api/v2/agents/heartbeat", heartbeat_body(args.profile, directory))
    config["last_reply"] = reply
    timer = ""
    if not args.no_timer:
        timer = install_timer(args.profile, python)
        config["timer"] = timer
    save_config(args.profile, config)
    print(f"Registered Hermes profile {args.profile!r} as bot {args.bot!r} at {args.url}")
    print(f"  MCP server `{MCP_SERVER_NAME}` in {directory / 'config.yaml'}: {mcp}; token in {directory / '.env'}")
    print(f"  credential saved in {path}")
    print(f"  heartbeat: {timer or 'none (run `heartbeat` yourself every minute)'}")
    waiting = reply.get("waiting", {})
    print(f"  the hub sees it: {waiting.get('messages', 0)} message(s) and {waiting.get('tasks', 0)} task(s) waiting")
    if mcp == "written":
        print("  restart the profile's gateway or chat so it loads the new MCP server (`/reload-mcp` in a chat)")
    return 0


def cmd_uninstall(args):
    try:
        config = load_config(args.profile)
    except Failure:
        config = {}
    directory = Path(config.get("profile_dir") or profile_dir(args.profile))
    remove_timer(args.profile)
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
    for name, fn, help_text in (("heartbeat", cmd_heartbeat, "post one heartbeat (what the timer runs)"),
                                ("status", cmd_status, "the saved configuration and the last reply"),
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
