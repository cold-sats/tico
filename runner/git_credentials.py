"""GitHub credentials from the team's GitHub App (backend/github_app.py), scoped to the bot's repository.

The hub mints an installation token that lasts an hour, and a turn can run longer, so git does not
keep one: its credential helper is this module, which gets a fresh token on every credential
request: from the hub with the runner's own registration, or, where bot code cannot read that file
(runner/isolation.py), from the supervisor's socket with the turn's attempt token. The helper is configured through
environment variables (no file, no askpass script on disk) and the token is only ever printed to
git. `gh` selects a token for its repository through a turn-local command wrapper. With no app
connected, or on any failure, the turn keeps whatever git access the machine already has.
"""
import json
import os
import shlex
import shutil
import re
import subprocess
import sys
from pathlib import Path

from . import credential_socket, isolation
from .outage import log

ROOT = Path(__file__).resolve().parents[1]
# The leading empty value clears helpers inherited from the machine's git config for github.com,
# so a stale keychain entry cannot win over the scoped token.
KEY = "credential.https://github.com.helper"
TOKENS_KEY = "TICO_GITHUB_TOKENS"
# A fixed token, for when the runner's registration file is not known (tests, embedding).
# The bot's repository (`owner/name`) as the hub resolved it, for the turn's publish step.
REPOSITORY_KEY = "TICO_GITHUB_REPOSITORY"
STATIC_HELPER = "!f() { echo username=x-access-token; echo \"password=$GH_TOKEN\"; }; f"


def fresh_helper(config_path, bot, socket_path=None):
    """A git credential helper that fetches a token each time git asks to `get`: from the hub
    with the runner's registration, or from the supervisor's socket when there is one."""
    where = ("--socket", str(socket_path)) if socket_path else (("--config", str(config_path)) if config_path else ())
    run = " ".join(shlex.quote(part) for part in (
        sys.executable, "-m", "runner.git_credentials", *where, "--bot", bot))
    return f"!f() {{ [ \"$1\" = get ] || exit 0; cd {shlex.quote(str(ROOT))} && exec {run}; }}; f"


def environment(token, helper=STATIC_HELPER):
    return {
        "GH_TOKEN": token, "GITHUB_TOKEN": token, "GIT_TERMINAL_PROMPT": "0",
        "GIT_CONFIG_COUNT": "3",
        "GIT_CONFIG_KEY_0": KEY, "GIT_CONFIG_VALUE_0": "",
        "GIT_CONFIG_KEY_1": KEY, "GIT_CONFIG_VALUE_1": helper,
        "GIT_CONFIG_KEY_2": "credential.https://github.com.useHttpPath", "GIT_CONFIG_VALUE_2": "true",
    }


def apply(env, client, bot, config_path=None, socket_path=None):
    """Add the bot's repository-scoped GitHub credentials to `env`. True when applied.
    Never raises: a turn must not fail because GitHub access could not be arranged."""
    try:
        granted = client.post("github/token", {"bot": bot})
    except Exception as exc:
        log(f"Tico runner: {bot}: no GitHub App token ({type(exc).__name__}); using the machine's git access")
        return False
    if not granted.get("configured") or not granted.get("token"):
        return False
    helper = fresh_helper(config_path, bot, socket_path) if (config_path or socket_path or "tokens" in granted) else STATIC_HELPER
    env.update(environment(granted["token"], helper))
    if "tokens" in granted:
        env[TOKENS_KEY] = json.dumps(granted["tokens"])
        executable = shutil.which("gh", path=env.get("PATH", os.environ.get("PATH")))
        if executable:
            env["TICO_GITHUB_GH"] = executable
            env["TICO_GITHUB_PYTHON"] = sys.executable
            env["TICO_GITHUB_BOT"] = bot
            if config_path and not socket_path:
                env["TICO_GITHUB_CONFIG"] = str(config_path)
            env["PATH"] = str(ROOT / "runner" / "credential_bin") + os.pathsep + env.get("PATH", os.environ.get("PATH", os.defpath))
    if socket_path:
        env[credential_socket.SOCKET_ENV] = str(socket_path)
    if granted.get("repository"):
        env[REPOSITORY_KEY] = str(granted["repository"])
    return True


def _same_repository(url, repository):
    """Whether a remote URL names `owner/name` on github.com, however it is spelled."""
    text = str(url or "").strip().lower().removesuffix("/").removesuffix(".git")
    return text.endswith("github.com/" + repository.lower()) or text.endswith("github.com:" + repository.lower())


def publish_history(path, repository, env=None, url=None, timeout=60):
    """Publish a bot's local history to its GitHub repository when the checkout has none yet.

    `hub bot repo-create <slug> --empty` makes an empty repository for a bot built on a
    computer; nothing pushes into it, because a turn's token is scoped to the bot's own repository
    and BotOps cannot push another bot's. So the runner does it, with that bot's own token from
    `apply`: a checkout with commits and no upstream gets `origin` set to the resolved https URL and
    `git push -u origin <branch>`. Never forces. A remote that already has history this checkout
    does not contain is left alone and reported. Returns (state, detail), state one of `published`,
    `current` (nothing to do), `skipped` (not a checkout with commits) or `failed`; detail says why
    for `failed` and `skipped`."""
    path = Path(path)
    if not repository or not (path / ".git").exists():
        return "skipped", "no repository link" if not repository else "not a git checkout"
    env = {**(env if env is not None else os.environ), "GIT_TERMINAL_PROMPT": "0"}

    def git(*args, timeout=15):
        return isolation.run(["git", "-C", str(path), *args], capture_output=True, text=True,
                             stdin=subprocess.DEVNULL, env=env, timeout=timeout)

    def why(result):
        lines = (result.stderr or result.stdout or "").strip().splitlines()
        return (lines[-1] if lines else f"exit {result.returncode}")[:200]

    try:
        branch = git("symbolic-ref", "--short", "-q", "HEAD").stdout.strip()
        if not branch:
            return "skipped", "no branch is checked out"
        if git("rev-parse", "--verify", "-q", "HEAD").returncode != 0:
            return "skipped", "no commits yet"
        if git("rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}").returncode == 0:
            return "current", ""
        wanted = url or f"https://github.com/{repository}.git"
        origin = git("config", "--get", "remote.origin.url")      # as configured, before any insteadOf rewrite
        current = origin.stdout.strip() if origin.returncode == 0 else ""
        if current and current != wanted and not _same_repository(current, repository):
            return "failed", f"origin is {current}, not {repository}; left as it is"
        if origin.returncode != 0:
            added = git("remote", "add", "origin", wanted)
            if added.returncode != 0:
                return "failed", "could not add origin: " + why(added)
        elif not current:
            git("remote", "set-url", "origin", wanted)
        listed = git("ls-remote", "--heads", "origin", timeout=timeout)
        if listed.returncode != 0:
            text = why(listed)
            return "failed", ("GitHub refused the bot's token" if any(w in text for w in ("uthentication", "403", "Permission", "denied"))
                              else "could not reach " + repository + ": " + text)
        remote = {line.split("\t")[1].removeprefix("refs/heads/"): line.split("\t")[0]
                  for line in listed.stdout.splitlines() if "\t" in line}
        if remote:
            # Anything already there must be an ancestor of what is pushed, or this would rewrite it.
            if branch not in remote:
                return "failed", f"{repository} already has history on {', '.join(sorted(remote))}, not {branch}; nothing pushed"
            if git("fetch", "--quiet", "--no-tags", "origin", branch, timeout=timeout).returncode != 0 \
                    or git("merge-base", "--is-ancestor", "FETCH_HEAD", "HEAD").returncode != 0:
                return "failed", f"{repository} already has different history on {branch}; nothing pushed"
        pushed = git("push", "-q", "-u", "origin", branch, timeout=timeout)
        if pushed.returncode != 0:
            return "failed", "push failed: " + why(pushed)
        return "published", ""
    except subprocess.TimeoutExpired:
        return "failed", "timed out"
    except (OSError, subprocess.SubprocessError) as exc:
        return "failed", type(exc).__name__


def clone_repository(path, repository, env=None, url=None, timeout=180):
    """Bring a bot's GitHub repository onto this computer: the other half of `publish_history`.

    A bot placed on a computer that has never held it (added, or moved from another computer) has no
    checkout there, and nothing else puts one there. `env` carries the bot's scoped token from `apply`
    (or the machine's own git access). Only a missing or empty folder is cloned into; anything already
    there is left as it is. Returns (state, detail), state `cloned` or `failed`; detail says why."""
    path = Path(path)
    if path.exists() and (not path.is_dir() or any(path.iterdir())):
        return "failed", f"{path.name} already exists here and is not an empty folder; left as it is"
    env = {**(env if env is not None else os.environ), "GIT_TERMINAL_PROMPT": "0"}
    wanted = url or f"https://github.com/{repository}.git"
    try:
        done = isolation.run(["git", "clone", "--quiet", wanted, str(path)], capture_output=True, text=True,
                             stdin=subprocess.DEVNULL, env=env, timeout=timeout)
    except subprocess.TimeoutExpired:
        return "failed", "timed out"
    except (OSError, subprocess.SubprocessError) as exc:
        return "failed", type(exc).__name__
    if done.returncode == 0:
        return "cloned", ""
    lines = (done.stderr or done.stdout or "").strip().splitlines()
    text = (lines[-1] if lines else f"exit {done.returncode}")[:200]
    if any(word in text for word in ("uthentication", "403", "Permission", "denied")):
        return "failed", "GitHub refused the bot's token"
    if "not found" in text.lower():
        return "failed", f"GitHub has no repository {repository} that this token can see"
    return "failed", text


def repository_name(value):
    """Normalize a Git credential path, GitHub URL or owner/repo argument."""
    value = str(value or "").strip()
    value = re.sub(r"^(?:https?://github\.com/|git@github\.com:)", "", value, flags=re.I)
    parts = value.strip("/").split("/")
    if len(parts) < 2:
        return None
    name = parts[1].removesuffix(".git")
    return parts[0] + "/" + name if re.fullmatch(r"[\w.-]+", parts[0]) and re.fullmatch(r"[\w.-]+", name) else None


def select_token(granted, repository=None):
    """Old servers have one token; new ones have authoritative repository groups."""
    if not granted.get("configured"):
        return ""
    if repository and "tokens" in granted:
        for group in granted["tokens"]:
            if any(str(name).lower() == repository.lower() for name in group.get("repositories", [])):
                return group.get("token", "")
        return ""
    return granted.get("token", "")


def credential(config_path, bot, socket_path=None, repository=None):
    """Fresh repository credentials, falling back to the turn's matching token in memory."""
    from clients.tico import Client
    try:
        if socket_path:
            return credential_socket.request(socket_path, os.environ.get("HUB_TOKEN", ""), timeout=15,
                                             repository=repository)
        if config_path:
            config = json.loads(Path(config_path).read_text())
            granted = Client(config["url"], config["token"], timeout=10, retries=1).post("github/token", {"bot": bot})
            return select_token(granted, repository)
    except Exception as exc:
        print(f"Tico runner: no fresh GitHub App token ({type(exc).__name__})", file=sys.stderr)
    granted = {"configured": True, "token": os.environ.get("GH_TOKEN", "")}
    if TOKENS_KEY in os.environ:
        granted["tokens"] = json.loads(os.environ[TOKENS_KEY])
    return select_token(granted, repository)


def gh_repository(argv, env):
    for index, arg in enumerate(argv):
        if arg in ("-R", "--repo") and index + 1 < len(argv):
            return repository_name(argv[index + 1])
        if arg.startswith("--repo=") or (arg.startswith("-R") and len(arg) > 2):
            return repository_name(arg.split("=", 1)[1] if arg.startswith("--repo=") else arg[2:])
    for arg in argv:
        if arg.startswith("https://github.com/"):
            return repository_name(arg)
        if arg.lstrip("/").startswith("repos/"):
            return repository_name(arg.lstrip("/")[6:])
    if len(argv) > 2 and argv[0] == "repo" and argv[1] in ("view", "clone", "fork"):
        if not argv[2].startswith("-"):
            return repository_name(argv[2])
    if env.get("GH_REPO"):
        return repository_name(env["GH_REPO"])
    remote = subprocess.run(["git", "config", "--get", "remote.origin.url"], capture_output=True,
                            text=True, timeout=10, env=env)
    return repository_name(remote.stdout) if remote.returncode == 0 else None


def gh_main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    env = dict(os.environ)
    repository = None
    try:
        repository = gh_repository(argv, env)
        token = credential(env.get("TICO_GITHUB_CONFIG"), env.get("TICO_GITHUB_BOT"),
                           env.get(credential_socket.SOCKET_ENV), repository)
    except (OSError, subprocess.SubprocessError):
        token = ""
    if token:
        env.update(GH_TOKEN=token, GITHUB_TOKEN=token)
    elif repository:
        print("Tico runner: no GitHub token for that repository", file=sys.stderr)
        return 1
    os.execve(env["TICO_GITHUB_GH"], [env["TICO_GITHUB_GH"], *argv], env)


def main(argv=None):
    import argparse
    parser = argparse.ArgumentParser(description="git credential helper backed by the Tico hub")
    parser.add_argument("--config")
    parser.add_argument("--socket")
    parser.add_argument("--bot", required=True)
    args = parser.parse_args(argv)
    wanted = dict(line.split("=", 1) for line in sys.stdin.read().splitlines() if "=" in line)
    if wanted.get("host") != (os.environ.get("TICO_GITHUB_HOST") or "github.com"):   # the override is for tests
        return
    token = credential(args.config, args.bot, args.socket, repository_name(wanted.get("path")))
    if token:
        sys.stdout.write(f"username=x-access-token\npassword={token}\n")


if __name__ == "__main__":
    main()
