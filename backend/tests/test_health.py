"""Health: every check is computed from live state, and people who are not administrators see counts only."""

import pytest

from backend import onboarding, releases
from backend.store import H
from backend.tests.test_getting_started import SIGNED_IN, activate, add_bot, enrolled, heartbeat  # noqa: F401
from backend.tests.test_onboarding import as_person, environment, signed_in  # noqa: F401


@pytest.fixture(autouse=True)
def quiet(monkeypatch):
    monkeypatch.setattr(releases, "CHECKER", releases.Checker())
    monkeypatch.setenv("TICO_UPDATE_CHECK", "off")


def queue(c, bot, minutes_ago, ident):
    """A message to the bot, which the database turns into a queued job."""
    c.execute("INSERT INTO messages(id,from_actor,to_actor,kind,body,created) VALUES(?,?,?,?,?,?)",
              (ident, "human:ana", "bot:" + bot, "request", "hi", H.shift(H.now(), minutes=-minutes_ago)))


def health_of(api, headers=None):
    body = api.get("/api/v2/health", headers=headers or signed_in()).json()
    return body, {row["id"]: row for row in body["checks"]}


def with_backup(monkeypatch, backup):
    real = onboarding.config_view
    monkeypatch.setattr(onboarding, "config_view", lambda *a, **k: {**real(*a, **k), **({"backup": backup} if backup else {})})


def test_all_good(environment, monkeypatch):
    api = environment()
    runner = enrolled(api)
    heartbeat(api, runner, seconds_ago=5, runtimes=SIGNED_IN)
    with_backup(monkeypatch, {"mode": "remote", "last_replicated_at": H.now(), "target_kind": "s3"})
    monkeypatch.setenv("TICO_AUTH_PROXY", "oidc") if False else None
    body, checks = health_of(api)
    assert {k: v["status"] for k, v in checks.items() if k != "signin"} == {
        "version": "ok", "computers": "ok", "models": "ok", "waiting": "ok", "queue": "ok",
        "github": "info", "backups": "ok", "failed": "ok"}
    assert body["computers"][0]["online"] and body["computers"][0]["runtimes"][0]["ready"]


def test_requested_server_settings_report_effective_state(environment, monkeypatch):
    from backend.credentials import CredentialCipher
    from backend.tests.test_credentials import FakeKMS

    api = environment()
    settings = api.app.state.store.settings
    settings.credential_kms_key = "example-key"
    monkeypatch.setenv("TICO_BLOCK_EXTERNAL_INVITES", "1")
    _, checks = health_of(api)
    assert checks["external_invites"]["status"] == checks["credential_kms"]["status"] == "warn"
    settings.block_external_invites = True
    api.app.state.vault.cipher = CredentialCipher("example-key", FakeKMS())
    with api.app.state.store.transaction() as c:
        api.app.state.vault.cipher.key(c)
    _, checks = health_of(api)
    assert checks["external_invites"]["status"] == checks["credential_kms"]["status"] == "ok"
    settings.credential_kms_key = ""
    _, checks = health_of(api)
    assert checks["credential_kms"]["status"] == "warn"
    assert "Restore the original" in checks["credential_kms"]["summary"]
    monkeypatch.setenv("TICO_CREDENTIAL_KMS_KEY", "example-key")
    _, checks = health_of(api)
    assert checks["credential_kms"]["status"] == "warn"
    assert "requested but is not active" in checks["credential_kms"]["summary"]


@pytest.mark.parametrize("source", ["credentials", "computer", ""])
def test_rejected_model_key_points_to_its_source(environment, source):
    api = environment()
    runner = enrolled(api)
    runtime = {"installed": True, "authenticated": "rejected", "rejected_reason": "Unauthorized"}
    if source:
        runtime["credential_source"] = source
    heartbeat(api, runner, seconds_ago=5, runtimes={"codex": runtime})
    body, checks = health_of(api)
    summary = checks["models"]["summary"]
    assert "Sign-in rejected" in summary and "runner's secrets" not in summary
    assert "Tools > Credentials" in summary if source != "computer" else "computer-local" in summary
    assert body["computers"][0]["runtimes"][0]["credential_source"] == source
    assert any(fix["href"] == "#/credentials" for fix in checks["models"]["fixes"])


def test_an_offline_computer_holds_its_bots(environment):
    api = environment()
    runner = enrolled(api)
    add_bot(api, "helper")
    heartbeat(api, runner, seconds_ago=600, runtimes=SIGNED_IN)
    with api.app.state.store.transaction() as c:
        c.execute("INSERT INTO assignments(bot,runner_id,generation,updated,updated_by) VALUES('helper',?,1,?,'t')",
                  (runner, H.now()))
    body, checks = health_of(api)
    assert checks["computers"]["status"] == "bad" and checks["waiting"]["status"] == "bad"
    assert body["waiting"][0]["bot"] == "helper" and body["waiting"][0]["reason"] == "computer_offline"
    assert body["computers"][0]["last_seen"]
    # A second computer that is up makes it a warning, not an outage.
    heartbeat(api, runner, seconds_ago=5, runtimes=SIGNED_IN)
    with api.app.state.store.transaction() as c:
        c.execute("INSERT INTO runners(id,label,operator,token_hash,created,last_seen) "
                  "SELECT 'r2','Old laptop',operator,'h2',created,? FROM runners WHERE id=?",
                  (H.shift(H.now(), hours=-2), runner))
    body, checks = health_of(api)
    assert checks["computers"]["status"] == "warn" and "Old laptop" in checks["computers"]["summary"]


def test_backups_local_only_and_stale(environment, monkeypatch):
    api = environment()
    old = H.shift(H.now(), hours=-30)
    with_backup(monkeypatch, {"mode": "remote", "last_replicated_at": old, "target_kind": "s3"})
    assert health_of(api)[1]["backups"]["status"] == "warn"
    with_backup(monkeypatch, {"mode": "off"})
    assert health_of(api)[1]["backups"]["status"] == "bad"


def test_no_off_disk_backup_is_a_quiet_note_on_a_local_install_and_a_warning_on_a_server(environment, monkeypatch):
    from types import SimpleNamespace

    from backend import health
    backup = {"mode": "local-only", "last_replicated_at": None, "target_kind": "local"}
    # A local backup is a note, with the bucket setup link, and does not count as attention.
    with_backup(monkeypatch, backup)
    body, checks = health_of(environment())
    assert checks["backups"]["status"] == "info"
    assert checks["backups"]["fixes"][0]["href"].endswith("#backups-and-restore")
    assert "backup bucket" in checks["backups"]["summary"]
    assert not any(x["id"] == "backups" and x["status"] in ("warn", "bad") for x in body["checks"])
    # A real server keeps the warning, and a local install with backups switched off is still not fine.
    assert health._backups({"backup": backup}, SimpleNamespace(loopback=False))["status"] == "warn"
    assert health._backups({"backup": {"mode": "off"}}, SimpleNamespace(loopback=True))["status"] == "bad"


def test_others_see_counts_not_details(environment):
    api = environment()
    runner = enrolled(api)
    heartbeat(api, runner, seconds_ago=600)
    body, checks = health_of(api, as_person(api, "quinn"))
    assert body["audience"] == "human" and body["computers"] == [] and body["waiting"] == []
    assert set(checks) == {"computers", "waiting", "queue", "failed"}
    assert all(not row["fixes"] for row in checks.values())
    assert "helper" not in checks["waiting"]["summary"]


def test_a_local_credential_key_that_is_not_backed_up_is_a_warning_or_a_note():
    from types import SimpleNamespace

    from backend import health
    remote = {"mode": "remote", "last_replicated_at": H.now(), "target_kind": "s3"}
    server, local = SimpleNamespace(loopback=False), SimpleNamespace(loopback=True)
    check = lambda backup, where=server: health._backups({"backup": backup}, where)
    # No local key (a KMS install, or no credential saved yet): as before.
    assert check({**remote, "credential_key": {"present": False}})["status"] == "ok"
    assert check(remote)["status"] == "ok"
    # Backups are set up and the key is not in them: a warning that says why.
    missing = check({**remote, "credential_key": {"present": True, "copied_at": None, "current": False}})
    assert missing["status"] == "warn" and "credential key" in missing["summary"] and missing["fixes"]
    assert check({**remote, "credential_key": {"present": True, "copied_at": "2026-01-01T00:00:00Z", "current": True}})["status"] == "ok"
    # No off-disk backup: the key is named in the note, and a quick start stays a note once it is copied.
    only = {"mode": "local-only", "last_replicated_at": None, "target_kind": "local"}
    held = {"present": True, "copied_at": "2026-01-01T00:00:00Z", "current": True}
    assert "credential key" in check({**only, "credential_key": held})["summary"]
    quiet = check({**only, "credential_key": held}, local)
    assert quiet["status"] == "info" and "credential key" in quiet["summary"] and quiet["fixes"][0]["href"].endswith("#backups-and-restore")
    assert check({**only, "credential_key": {**held, "copied_at": None, "current": False}}, local)["status"] == "warn"
    assert "credential key" in check({"mode": "off", "credential_key": held})["summary"]
