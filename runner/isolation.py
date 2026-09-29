"""Keep the runner's own credential away from the code a bot runs (Linux, Docker runner).

The runner's registration (runner.json) can claim any bot's work, so it must not sit where a turn
can read it. In the Docker image the supervisor starts as root with a handful of capabilities (see
docker/runner.compose.yaml), owns the registration file (mode 0600) and drops every process that
runs bot-controlled code to an unprivileged user (`bot`, TICO_RUNNER_BOT_UID): the model CLI of a
turn, the login relay, `git` in a bot's checkout and any model CLI the runner probes. That user's
HOME holds the workspace, the secrets the turns need and the model logins; the supervisor's
files are root-only or read-only to it. A turn gets its attempt token and the environment the
runner already passes, and asks for its GitHub token over a socket (runner/credential_socket.py).

It stays off wherever the supervisor is not root or TICO_RUNNER_BOT_UID is unset: a Mac runner is a
trust group of one user (SECURITY.md), and so is an image started the way it was before this.
Bots still share the one `bot` user with each other.
"""
import os
import subprocess
from pathlib import Path

UID_ENV, GID_ENV = "TICO_RUNNER_BOT_UID", "TICO_RUNNER_BOT_GID"


def identity():
    """(uid, gid) that bot code runs as, or None when this process is not separating them."""
    if not hasattr(os, "geteuid") or os.geteuid() != 0:
        return None
    try:
        uid = int(os.environ[UID_ENV])
        gid = int(os.environ.get(GID_ENV) or uid)
    except (KeyError, ValueError):
        return None
    return (uid, gid) if uid > 0 else None


def enabled():
    return identity() is not None


def demote(kwargs):
    """`subprocess` keyword arguments with the bot user added when isolation is on."""
    who = identity()
    if not who:
        return kwargs
    return {**kwargs, "user": who[0], "group": who[1], "extra_groups": []}


def run(*args, **kwargs):
    return subprocess.run(*args, **demote(kwargs))


def popen(*args, **kwargs):
    return subprocess.Popen(*args, **demote(kwargs))


def chown(path, *, recursive=False):
    """Hand a file the supervisor made to the bot user. A no-op when isolation is off."""
    who = identity()
    if not who:
        return
    path = Path(path)
    try:
        os.chown(path, *who, follow_symlinks=False)
        if recursive and path.is_dir() and not path.is_symlink():
            for root, dirs, files in os.walk(path):
                for name in (*dirs, *files):
                    os.chown(os.path.join(root, name), *who, follow_symlinks=False)
    except OSError:
        pass


def mkdir(path, mode=0o700):
    """`mkdir -p` where every directory it creates belongs to the bot user when isolation is on."""
    path = Path(path)
    missing = []
    for part in (path, *path.parents):
        if part.exists():
            break
        missing.append(part)
    path.mkdir(mode=mode, parents=True, exist_ok=True)
    for part in missing:
        chown(part)
    return path


def bot_state(default):
    """Where per-turn host state lives: `default` (inside the runner's own state) unless isolated,
    where the supervisor's state directory is closed to bot code, so it is a bot-owned directory."""
    if not enabled():
        return Path(default)
    return mkdir(Path(os.environ.get("HOME") or "/home/runner") / ".tico-host")


def turn_dir():
    """A directory a turn can read files the supervisor prepared for it (vault files)."""
    base = Path(os.environ.get("TICO_RUNNER_TURN_DIR") or "/run/tico-runner/turn")
    base.mkdir(mode=0o755, parents=True, exist_ok=True)
    return base


def adopt(*paths):
    """Give the bot user anything under `paths` that root made: a secret file someone wrote with
    `docker exec` (root by default) or a login run as root. Cheap; never follows symlinks."""
    who = identity()
    if not who:
        return
    for path in paths:
        try:
            stats = os.lstat(path)
            if stats.st_uid != who[0]:
                os.chown(path, *who, follow_symlinks=False)
            if not os.path.isdir(path) or os.path.islink(path):
                continue
            for root, dirs, files in os.walk(path):
                for name in (*dirs, *files):
                    child = os.path.join(root, name)
                    if os.lstat(child).st_uid != who[0]:
                        os.chown(child, *who, follow_symlinks=False)
        except OSError:
            pass
