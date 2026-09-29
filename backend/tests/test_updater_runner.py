"""docker/updater.py in runner mode: the runner box's sidecar pulls the matching tico-runner tag, recreates the
runner, and puts the old image back when the new one does not turn healthy."""
import importlib.util
import stat
from pathlib import Path

import pytest

SOURCE = Path(__file__).resolve().parents[2] / "docker/updater.py"


def load(monkeypatch, mode, tmp_path):
    for key, value in {"TICO_UPDATER_MODE": mode, "TICO_PROJECT_DIR": str(tmp_path),
                       "TICO_COMPOSE_FILE": "runner.compose.yaml" if mode == "runner" else "",
                       "TICO_UPDATER_TOKEN_FILE": str(tmp_path / "token"), "TICO_UPDATER_BUNDLE": "never"}.items():
        monkeypatch.setenv(key, value)
    spec = importlib.util.spec_from_file_location("tico_updater_" + (mode or "server"), SOURCE)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class Docker:
    """Stands in for `docker`: records every command, and answers the two questions the updater asks."""

    def __init__(self, module, monkeypatch, healthy):
        self.calls, self.answers = [], list(healthy)
        monkeypatch.setattr(module.subprocess, "run", self.run)
        monkeypatch.setattr(module, "healthy", lambda seconds: self.answers.pop(0))
        monkeypatch.setattr(module, "running_image", lambda: ("sha256:old", "v0.1.0"))

    def run(self, argv, env=None, **kw):
        self.calls.append((argv, (env or {}).get("TICO_TAG")))
        return type("R", (), {"returncode": 0, "stdout": "", "stderr": ""})()

    def compose(self):
        return [(a[a.index("--project-directory") + 2:], tag) for a, tag in self.calls if a[:2] == ["docker", "compose"]]


def test_runner_mode_manages_the_runner_service_and_image(monkeypatch, tmp_path):
    updater = load(monkeypatch, "runner", tmp_path)
    assert (updater.SERVICE, updater.IMAGE) == ("runner", "ghcr.io/ticoteam/tico-runner")
    (tmp_path / ".env").write_text("TICO_URL=https://tico.example.com\n")
    docker = Docker(updater, monkeypatch, [True])
    updater.update("v0.2.0")
    assert updater.status["state"] == "healthy" and updater.status["to"] == "v0.2.0" and updater.status["from"] == "v0.1.0"
    assert docker.compose() == [(["pull", "runner"], "v0.2.0"),
                                (["up", "-d", "--no-deps", "--pull", "never", "runner"], "v0.2.0")]
    assert all(a[3] == str(tmp_path / "runner.compose.yaml") for a, _ in docker.calls if a[:2] == ["docker", "compose"])
    assert "TICO_TAG=v0.2.0" in (tmp_path / ".env").read_text()      # a later `docker compose up` stays on it


def test_a_runner_that_does_not_turn_healthy_is_rolled_back(monkeypatch, tmp_path):
    updater = load(monkeypatch, "runner", tmp_path)
    (tmp_path / ".env").write_text("TICO_URL=https://tico.example.com\n")
    docker = Docker(updater, monkeypatch, [False, True])
    updater.update("v0.2.0")
    assert updater.status["state"] == "rolled_back" and "Went back to v0.1.0" in updater.status["message"]
    assert "the runner did not come up healthy" in updater.status["message"]
    assert (["docker", "tag", "sha256:old", "ghcr.io/ticoteam/tico-runner:v0.1.0"], None) in docker.calls
    assert docker.compose()[-1] == (["up", "-d", "--no-deps", "--pull", "never", "runner"], "v0.1.0")
    assert "TICO_TAG" not in (tmp_path / ".env").read_text()           # the failed version is not remembered


def test_a_rollback_that_fails_too_is_reported_failed(monkeypatch, tmp_path):
    updater = load(monkeypatch, "runner", tmp_path)
    Docker(updater, monkeypatch, [False, False])
    updater.update("v0.2.0")
    assert updater.status["state"] == "failed" and "old version did not start either" in updater.status["message"]


def test_the_runner_reads_a_token_the_updater_wrote(monkeypatch, tmp_path):
    updater = load(monkeypatch, "runner", tmp_path)
    updater.ensure_token()
    token = (tmp_path / "token").read_text().strip()
    assert len(token) == 64 and stat.S_IMODE((tmp_path / "token").stat().st_mode) == 0o644
    updater.ensure_token()
    assert (tmp_path / "token").read_text().strip() == token           # written once


def test_server_mode_is_unchanged(monkeypatch, tmp_path):
    updater = load(monkeypatch, "", tmp_path)
    assert (updater.SERVICE, updater.IMAGE, updater.COMPOSE_FILE) == ("server", "ghcr.io/ticoteam/tico", "")
    updater.ensure_token()
    assert not (tmp_path / "token").exists()                           # the server writes that one
    docker = Docker(updater, monkeypatch, [True])
    updater.update("v0.2.0")
    assert docker.compose()[0] == (["pull", "server"], "v0.2.0") and "-f" not in docker.calls[0][0]


def test_the_runner_compose_keeps_the_socket_in_the_sidecar():
    import yaml
    compose = yaml.safe_load((SOURCE.parent / "runner.compose.yaml").read_text())
    sockets = [name for name, svc in compose["services"].items()
               if any("docker.sock" in str(v) for v in svc.get("volumes", []))]
    assert sockets == ["updater"]
    assert compose["services"]["runner"]["environment"]["TICO_UPDATER_URL"] == "http://updater:8080"
    assert "runner-control:/control:ro" in compose["services"]["runner"]["volumes"]
