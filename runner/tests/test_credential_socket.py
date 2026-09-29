"""A turn that cannot read the runner's registration still gets its own bot's GitHub token, and only that."""
import io
import os
import shutil
import tempfile
from unittest import mock

import pytest

from runner import credential_socket as C, git_credentials as G, isolation


@pytest.fixture
def channel():
    directory = tempfile.mkdtemp(dir="/tmp")     # short: a Unix socket path has a length limit
    minted = []

    def mint(bot):
        minted.append(bot)
        return f"ghs_{bot}"
    server = C.Server(os.path.join(directory, "cred.sock"), mint).start()
    server.minted = minted
    yield server
    server.stop()
    shutil.rmtree(directory, ignore_errors=True)


def test_an_attempt_gets_a_token_for_its_own_bot_only(channel):
    channel.register("attempt-a", "alpha")
    channel.register("attempt-b", "beta")
    assert C.request(channel.path, "attempt-a") == "ghs_alpha"
    assert C.request(channel.path, "attempt-b") == "ghs_beta"
    assert channel.minted == ["alpha", "beta"]      # the request cannot name a bot: there is no field for it


def test_unknown_or_finished_attempts_get_nothing(channel):
    channel.register("attempt-a", "alpha")
    for token in ("", "guess", "attempt-a "):
        with pytest.raises(ValueError):
            C.request(channel.path, token)
    channel.unregister("attempt-a")
    with pytest.raises(ValueError):
        C.request(channel.path, "attempt-a")
    assert channel.minted == []


def test_the_helper_uses_the_socket_and_never_the_registration(channel, monkeypatch, capsys):
    channel.register("attempt-a", "alpha")
    monkeypatch.setenv("HUB_TOKEN", "attempt-a")
    monkeypatch.setattr("sys.stdin", io.StringIO("protocol=https\nhost=github.com\n\n"))
    G.main(["--socket", channel.path, "--bot", "alpha"])           # no --config: the file is not readable to a turn
    assert capsys.readouterr().out == "username=x-access-token\npassword=ghs_alpha\n"


def test_apply_points_the_turn_at_the_socket_without_the_config_path():
    class Hub:
        def post(self, path, body):
            return {"configured": True, "token": "ghs_start", "repository": "acme/alpha"}
    env = {}
    assert G.apply(env, Hub(), "alpha", "/home/runner/runner.json", "/run/tico-runner/git-credential.sock")
    helper = env["GIT_CONFIG_VALUE_1"]
    assert "--socket /run/tico-runner/git-credential.sock" in helper and "runner.json" not in helper
    assert env[C.SOCKET_ENV] == "/run/tico-runner/git-credential.sock"


def test_it_falls_back_to_the_turn_token_when_the_supervisor_is_gone(monkeypatch):
    monkeypatch.setenv("GH_TOKEN", "ghs_start")
    assert G.credential(None, "alpha", "/tmp/no-such.sock") == "ghs_start"


def test_bot_code_is_demoted_only_when_the_supervisor_is_root_and_told_to(monkeypatch):
    monkeypatch.delenv(isolation.UID_ENV, raising=False)
    assert isolation.demote({"cwd": "x"}) == {"cwd": "x"}
    monkeypatch.setenv(isolation.UID_ENV, "10003")
    with mock.patch("os.geteuid", return_value=1000):
        assert isolation.identity() is None
    with mock.patch("os.geteuid", return_value=0):
        assert isolation.demote({}) == {"user": 10003, "group": 10003, "extra_groups": []}
