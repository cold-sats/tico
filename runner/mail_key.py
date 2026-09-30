"""The company's Google Workspace key, where bots cannot read it (Linux Docker runner).

The service-account key acts as any mailbox in the company. Every bot on a computer runs as the
same user, so a key in workspace/secrets is one prompt injection away from all of them. When the
two-user layout is on (runner/isolation.py) the supervisor keeps the key in its own state directory
(owned by ticorun, 0600, closed to the bot user), the connectors job reads it there, and an inbox
bot's turn asks the supervisor, over the credential socket, for a short-lived token for one mailbox
(runner/credential_socket.py). Without the layout (a Mac, or Docker started the old way) the key
stays where it was and bots can read it: `exposed` says so, and Settings > Health shows a warning.
"""
import json
import os
import subprocess
from pathlib import Path

from . import isolation
from .outage import log

FILE = "google-sa.json"
ROOT = Path(__file__).resolve().parents[1]


def protected_path(config):
    """Where the key lives when isolation is on: the supervisor's state directory."""
    home = Path(os.environ.get("HOME") or "/home/runner")
    return Path(config.get("state_dir") or home / ("state-" + str(config.get("runner_id") or ""))) / FILE


def workspace_path(config):
    return Path(config.get("projects_dir") or "") / "secrets" / FILE


def protect(config):
    """Move a key found in the workspace (put there by an older install, or by an operator following
    an older doc) to the protected place. One time in practice; cheap, so it runs on every check.
    Returns True when it moved one. A no-op wherever isolation is off."""
    if not isolation.enabled() or os.environ.get("GOOGLE_SA_KEY"):
        return False
    old, new = workspace_path(config), protected_path(config)
    try:
        if old.is_symlink() or not old.is_file():
            return False
        data = old.read_bytes()
        new.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        temporary = new.with_name(new.name + ".new")
        temporary.unlink(missing_ok=True)
        descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(data)
        os.replace(temporary, new)
        old.unlink()
    except OSError as exc:
        log(f"Tico runner: could not move the mail key out of the bots' reach ({type(exc).__name__})")
        return False
    log(f"Tico runner: moved the Google mail key out of workspace/secrets to {new}; bots ask the runner for mail access")
    return True


def status(config):
    """`protected`, `exposed` (a key bots can read) or None (no key on this computer)."""
    if isolation.enabled():
        return "exposed" if workspace_path(config).is_file() else "protected" if protected_path(config).is_file() else None
    from .connectors import mail_secret_path
    return "exposed" if mail_secret_path(config).is_file() else None


def held_by_computer(config):
    """True when this computer holds the Google key for its bots: the two-user layout is on, the key is in
    the supervisor's state directory and the connectors job runs here (the runner supervises it when
    TICO_SIDE_JOBS is 1, the container default). A bot's turn never has GOOGLE_SA_KEY in its environment
    then; it asks for a short-lived token over the credential socket, so the key is there, not missing."""
    if not isolation.enabled() or os.environ.get("TICO_SIDE_JOBS") != "1":
        return False
    from .connectors import mail_secret_path
    return mail_secret_path(config).is_file()


def minter(config, script=None):
    """(service, mailbox) -> {"token", "expiry"}: the mail CLI, run here with the key, prints one token."""
    from .connectors import mail_umask
    script = script or ROOT / "scripts" / "mail.sh"
    key = protected_path(config)

    def mint(service, mailbox):
        env = {k: v for k, v in os.environ.items() if k != "HUB_TOKEN"}
        env["GOOGLE_SA_KEY"] = str(key)
        result = subprocess.run([str(script), "mint-token", "--mailbox", mailbox, "--service", service],
                                cwd=ROOT, stdin=subprocess.DEVNULL, capture_output=True, text=True,
                                timeout=60, env=env, **mail_umask())
        if result.returncode:
            raise RuntimeError("mint-token failed")
        return json.loads(result.stdout)
    return mint
