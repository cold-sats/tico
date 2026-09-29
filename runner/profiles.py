"""Subscription profiles: one directory on this machine per provider login.

Every bot used to run on whichever accounts the operator happened to be signed in to, because
the hosts inherit this process's `HOME` and `CODEX_HOME`. A profile is a named directory that
holds those homes instead, so two companies (or two bots of one company) on one Mac can use
different subscriptions. `share_operator` keeps the old behaviour: the operator's own `~/.codex`
and `$HOME`, which is what every registration made before profiles existed still gets.

The runner registration names them:

    "profiles": {"acme": {"dir": "~/.config/tico/environments/acme/profiles/acme",
                          "share_operator": false}},
    "default_profile": "acme",
    "bot_profiles": {"sales": "acme"}

Profiles are runner-side only. The server records nothing about them but their name.
"""

import json
import os
import re
import shutil
from pathlib import Path

RUNTIMES = ("codex", "claude", "gemini", "grok")
NAME_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
# The only relocation knob each CLI offers today. Codex reads CODEX_HOME; Claude Code and Grok
# Build key their login to HOME (grok 1.0.30 also honours GROK_HOME, but one
# rule for both keeps a profile a single directory). Gemini is not here: its host takes a home
# argument instead, so nothing in the turn's environment has to move.
HOME_VAR = {"codex": "CODEX_HOME", "claude": "HOME", "grok": "HOME"}
# Worst first: a runner row reports the profile that needs attention, not the healthy one.
SIGN_IN_ORDER = ("failed", "missing", "unknown", "ready")
LOGIN_COMMAND = {"codex": ["codex", "login"], "claude": ["claude", "auth", "login"],
                 "grok": ["grok", "login"]}


class Profile:
    """One subscription: the provider homes a bot's turns and readiness checks run against."""

    def __init__(self, name, directory, share_operator=False):
        self.name = name
        self.directory = Path(directory).expanduser()
        self.share_operator = bool(share_operator)

    def home(self, runtime):
        """Where this runtime keeps its login, or None when it uses the operator's own."""
        return None if self.share_operator else self.directory / runtime

    def environment(self, runtime, env=None):
        """`env` (this process's by default) with `runtime`'s home pointed at this profile."""
        env = dict(os.environ if env is None else env)
        home = self.home(runtime)
        if home and runtime in HOME_VAR:
            env[HOME_VAR[runtime]] = str(home)
        return env


def select(config, bot=None):
    """The profile a bot runs under: its own assignment, else the registration's default.

    None means this registration names no profiles at all, so the operator's own logins run
    every bot exactly as they did before.
    """
    profiles = config.get("profiles") or {}
    name = (config.get("bot_profiles") or {}).get(bot) if bot else None
    entry = profiles.get(name or config.get("default_profile") or "")
    if not isinstance(entry, dict) or not entry.get("dir"):
        return None
    return Profile(name or config["default_profile"], entry["dir"], entry.get("share_operator"))


def create(root, name, share_operator=False):
    """Make `<root>/<name>` with a home per runtime; returns its runner registration entry."""
    if not NAME_RE.fullmatch(name or ""):
        raise ValueError("A profile name is lowercase letters, digits, and single hyphens")
    directory = Path(root).expanduser() / name
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    (directory / "profile.json").write_text(
        json.dumps({"name": name, "share_operator": bool(share_operator)}, indent=2))
    if not share_operator:
        for runtime in RUNTIMES:
            (directory / runtime).mkdir(mode=0o700, exist_ok=True)
        # A relocated HOME is an empty home: without this, every commit a bot makes under it is
        # authored by nobody. The copy is deliberate, so a client's profile can differ later.
        source = Path.home() / ".gitconfig"
        for runtime in ("claude", "grok"):
            target = directory / runtime / ".gitconfig"
            if source.is_file() and not target.exists():
                shutil.copyfile(source, target)
    return {"dir": str(directory), "share_operator": bool(share_operator)}
