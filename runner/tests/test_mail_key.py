"""The company's Google key stays with the supervisor; an inbox bot's turn gets a token for its own mailboxes only."""
import os
import shutil
import stat
import tempfile
from unittest import mock

import pytest

from runner import credential_socket as C, isolation, mail_key
from runner.connectors import mail_secret_path


@pytest.fixture
def channel():
    directory = tempfile.mkdtemp(dir="/tmp")
    minted = []

    def mail(service, mailbox):
        minted.append((service, mailbox))
        return {"token": f"ya29.{mailbox}", "expiry": "2026-01-01T00:00:00"}
    server = C.Server(os.path.join(directory, "cred.sock"), lambda bot: "ghs", mail).start()
    server.minted = minted
    yield server
    server.stop()
    shutil.rmtree(directory, ignore_errors=True)


def test_only_the_inbox_bots_turn_gets_mail_and_only_for_its_mailboxes(channel):
    channel.register("attempt-inbox", "ana-inbox", ["ana@acme.example", "ben@acme.example"])
    channel.register("attempt-other", "helper")                    # a bot the hub named no mailbox for
    assert C.request_mail(channel.path, "attempt-inbox", "gmail", "Ana@Acme.example")["token"] == "ya29.ana@acme.example"
    for attempt, mailbox in (("attempt-other", "ana@acme.example"), ("attempt-inbox", "cara@acme.example"),
                             ("guess", "ana@acme.example")):
        with pytest.raises(ValueError):
            C.request_mail(channel.path, attempt, "gmail", mailbox)
    with pytest.raises(ValueError):
        C.request_mail(channel.path, "attempt-inbox", "drive", "ana@acme.example")     # no other service
    assert channel.minted == [("gmail", "ana@acme.example")]
    channel.unregister("attempt-inbox")
    with pytest.raises(ValueError):
        C.request_mail(channel.path, "attempt-inbox", "gmail", "ana@acme.example")


def test_the_key_moves_out_of_the_bots_reach_when_isolated(tmp_path, monkeypatch):
    monkeypatch.delenv("GOOGLE_SA_KEY", raising=False)
    home = tmp_path / "home"
    secrets = home / "workspace" / "secrets"
    secrets.mkdir(parents=True)
    (secrets / "google-sa.json").write_text('{"type": "service_account"}')
    os.chmod(secrets / "google-sa.json", 0o600)
    config = {"projects_dir": str(home / "workspace"), "state_dir": str(home / "state-r1")}
    monkeypatch.setattr(isolation, "identity", lambda: (10003, 10002))
    assert mail_key.status(config) == "exposed"
    assert mail_key.protect(config) is True
    moved = home / "state-r1" / "google-sa.json"
    assert moved.read_text() == '{"type": "service_account"}' and not (secrets / "google-sa.json").exists()
    # Closed to the bot user: no group or other bits on the file or its directory, and the mail
    # job now reads it there.
    assert stat.S_IMODE(moved.stat().st_mode) == 0o600 and stat.S_IMODE(moved.parent.stat().st_mode) == 0o700
    assert moved.stat().st_uid != 10003
    assert mail_secret_path(config) == moved and mail_key.status(config) == "protected"
    assert mail_key.protect(config) is False


def test_without_isolation_the_key_stays_and_is_reported_readable(tmp_path, monkeypatch):
    monkeypatch.delenv("GOOGLE_SA_KEY", raising=False)
    monkeypatch.delenv(isolation.UID_ENV, raising=False)
    (tmp_path / "secrets").mkdir()
    (tmp_path / "secrets" / "google-sa.json").write_text("{}")
    config = {"projects_dir": str(tmp_path)}
    assert mail_key.protect(config) is False and mail_key.status(config) == "exposed"
    assert mail_secret_path(config) == tmp_path / "secrets" / "google-sa.json"


def test_the_mail_cli_asks_the_supervisor_only_inside_an_isolated_turn(channel, monkeypatch):
    from connectors.mail import auth
    channel.register("attempt-inbox", "ana-inbox", ["ana@acme.example"])
    monkeypatch.delenv(auth.SOCKET_ENV, raising=False)
    assert auth.supervisor_token("ana@acme.example", [auth.GMAIL_SCOPE]) is None        # Mac: the key file is used
    monkeypatch.setenv(auth.SOCKET_ENV, channel.path)
    monkeypatch.setenv("HUB_TOKEN", "attempt-inbox")
    assert auth.supervisor_token("ana@acme.example", [auth.GMAIL_SCOPE])["token"] == "ya29.ana@acme.example"
    with pytest.raises(auth.Failure):
        auth.supervisor_token("cara@acme.example", [auth.GMAIL_SCOPE])
