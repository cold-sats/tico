import json
import subprocess
import sys

from runner.service import CLAUDE_AUTH_TIMEOUT_SECONDS, Runner


def service(config):
    instance = Runner.__new__(Runner)
    instance.config = config
    return instance


def test_environment_uses_registered_projects_and_only_scoped_hub_token(tmp_path, monkeypatch):
    monkeypatch.setattr("runner.op.resolve_op_refs", lambda env: {})
    monkeypatch.setenv("TICO_RUNNER_TOKEN", "machine-secret-must-not-reach-bot")
    monkeypatch.setenv("HUB_DB", "/old/local/database.sqlite")
    monkeypatch.setenv("HUB_HUMAN_OVERRIDE", "ana")
    secrets = tmp_path / "secrets"
    secrets.mkdir()
    (secrets / "_shared.env").write_text("SETUP_TEST_VALUE=shared\n")
    (secrets / "cpo.env").write_text("SETUP_TEST_VALUE=product-only\n")
    local = service({"url": "https://hub.acme.example", "projects_dir": str(tmp_path), "token": "machine-token"})
    env = local.environment({"bot": "cpo", "token": "attempt-only-token"})
    assert env["SETUP_TEST_VALUE"] == "product-only"
    assert env["HUB_TOKEN"] == "attempt-only-token"
    assert env["HUB_EMPLOYEE"] == "cpo"
    assert "TICO_RUNNER_TOKEN" not in env and "HUB_DB" not in env and "HUB_HUMAN_OVERRIDE" not in env
    assert "machine-token" not in env.values()


def test_environment_loads_only_the_declared_key_from_a_safe_credential_profile(tmp_path, monkeypatch):
    monkeypatch.setattr("runner.op.resolve_op_refs", lambda env: {})
    secrets = tmp_path / "secrets"
    secrets.mkdir()
    (secrets / "docs-qa.env").write_text("GEMINI_API_KEY=usable\nUNRELATED_SECRET=hidden\n")
    local = service({"url": "https://hub.acme.example", "projects_dir": str(tmp_path), "token": "machine"})
    attempt = {"bot": "botops", "token": "attempt", "config": {"access": [{
        "service": "gemini", "credential_profile": "docs-qa", "env": "GEMINI_API_KEY"}]}}
    env = local.environment(attempt)
    assert env["GEMINI_API_KEY"] == "usable"
    assert "UNRELATED_SECRET" not in env

