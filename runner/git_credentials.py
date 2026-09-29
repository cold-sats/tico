"""GitHub credentials from the company's GitHub App (backend/github_app.py), scoped to the bot's repository.

The hub mints an installation token that lasts an hour, and a turn can run longer, so git does not
keep one: its credential helper is this module, which gets a fresh token on every credential
request: from the hub with the runner's own registration, or, where bot code cannot read that file
(runner/isolation.py), from the supervisor's socket with the turn's attempt token. The helper is configured through
environment variables (no file, no askpass script on disk) and the token is only ever printed to
git. `gh` cannot ask, so it reads GH_TOKEN, the token from the start of the turn. With no app
connected, or on any failure, the turn keeps whatever git access the machine already has.
"""
import json
import os
import shlex
import subprocess
import sys
from pathlib import Path

from . import credential_socket, isolation
from .outage import log

ROOT = Path(__file__).resolve().parents[1]
# The leading empty value clears helpers inherited from the machine's git config for github.com,
# so a stale keychain entry cannot win over the scoped token.
KEY = "credential.https://github.com.helper"
# A fixed token, for when the runner's registration file is not known (tests, embedding).
# The bot's repository (`owner/name`) as the hub resolved it, for the turn's publish step.
REPOSITORY_KEY = "TICO_GITHUB_REPOSITORY"
STATIC_HELPER = "!f() { echo username=x-access-token; echo \"password=$GH_TOKEN\"; }; f"


def fresh_helper(config_path, bot, socket_path=None):
    """A git credential helper that fetches a token each time git asks to `get`: from the hub
    with the runner's registration, or from the supervisor's socket when there is one."""
    where = ("--socket", str(socket_path)) if socket_path else ("--config", str(config_path))
    run = " ".join(shlex.quote(part) for part in (
        sys.executable, "-m", "runner.git_credentials", *where, "--bot", bot))
    return f"!f() {{ [ \"$1\" = get ] || exit 0; cd {shlex.quote(str(ROOT))} && exec {run}; }}; f"


def environment(token, helper=STATIC_HELPER):
    return {
        "GH_TOKEN": token, "GITHUB_TOKEN": token, "GIT_TERMINAL_PROMPT": "0",
        "GIT_CONFIG_COUNT": "2",
        "GIT_CONFIG_KEY_0": KEY, "GIT_CONFIG_VALUE_0": "",
        "GIT_CONFIG_KEY_1": KEY, "GIT_CONFIG_VALUE_1": helper,
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
    helper = fresh_helper(config_path, bot, socket_path) if (config_path or socket_path) else STATIC_HELPER
    env.update(environment(granted["token"], helper))
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

    `hub github create-bot-repo <slug> --empty` makes an empty repository for a bot built on a
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


def credential(config_path, bot, socket_path=None):
    """The token to give git now: fresh from the hub (or, with a socket, from the supervisor, which
    is told only this turn's HUB_TOKEN), else the one this turn started with."""
    from clients.tico import Client
    try:
        if socket_path:
            return credential_socket.request(socket_path, os.environ.get("HUB_TOKEN", ""), timeout=15)
        config = json.loads(Path(config_path).read_text())
        granted = Client(config["url"], config["token"], timeout=10, retries=1).post("github/token", {"bot": bot})
        if granted.get("configured") and granted.get("token"):
            return granted["token"]
    except Exception as exc:
        print(f"Tico runner: no fresh GitHub App token ({type(exc).__name__})", file=sys.stderr)
    return os.environ.get("GH_TOKEN", "")


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
    token = credential(args.config, args.bot, args.socket)
    if token:
        sys.stdout.write(f"username=x-access-token\npassword={token}\n")


if __name__ == "__main__":
    main()
