import json
import subprocess
import sys

from runner.service import CLAUDE_AUTH_TIMEOUT_SECONDS, Runner


def service(config):
    instance = Runner.__new__(Runner)
    instance.config = config
    instance.vault_values, instance.vault_names, instance.vault_files = {}, {}, {}
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
    assert "SETUP_TEST_VALUE" not in env
    assert env["HUB_TOKEN"] == "attempt-only-token"
    assert env["HUB_EMPLOYEE"] == "cpo"
    assert "TICO_RUNNER_TOKEN" not in env and "HUB_DB" not in env and "HUB_HUMAN_OVERRIDE" not in env
    assert "machine-token" not in env.values()


def test_environment_loads_only_live_grants_and_ignores_legacy_profiles(tmp_path, monkeypatch):
    monkeypatch.setattr("runner.op.resolve_op_refs", lambda env: {})
    secrets = tmp_path / "secrets"
    secrets.mkdir()
    (secrets / "docs-qa.env").write_text("GEMINI_API_KEY=usable\nUNRELATED_SECRET=hidden\n")
    local = service({"url": "https://hub.acme.example", "projects_dir": str(tmp_path), "token": "machine"})
    attempt = {"bot": "botops", "token": "attempt", "config": {"access": [{
        "service": "gemini", "credential_profile": "docs-qa", "env": "GEMINI_API_KEY"}]}}
    assert "GEMINI_API_KEY" not in local.environment(attempt)
    granted = {"credentials": [{"id": "gemini", "env": "GEMINI_API_KEY", "kind": "api_key", "value": "granted"}]}
    from unittest.mock import Mock
    client = Mock()
    client.get.return_value = granted
    monkeypatch.setattr("runner.service.Client", lambda *a, **k: client)
    env = local.environment({**attempt, "id": "a1", "credential_vault": True})
    assert env["GEMINI_API_KEY"] == "granted"
    client.get.assert_called_once_with("credential-runtime")
    assert "UNRELATED_SECRET" not in env

