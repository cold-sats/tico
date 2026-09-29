"""Calendar data stays provider-local and reaches only its signed-in person."""

import json
import os

import pytest

from backend.store import H
from backend.tests.test_api import api, get, headers, post, runner  # noqa: F401
from runner.connectors import ConnectorPublisher
from runner.outage import Outage


def event(title="Product sync"):
    return {"occurrence_id": "event_123", "event_id": "provider-event",
            "title": title, "start": "2026-09-11T09:00:00-07:00",
            "end": "2026-09-11T09:30:00-07:00",
            "attendees": ["ana@acme.example", "ben@acme.example"],
            "meeting_url": "https://meet.google.com/abc-defg-hij"}


class FakeClient:
    def __init__(self):
        self.published = []
        self.results = []

    def get(self, path):
        assert path == "connectors/calendar/targets"
        return {"hours": 24, "people": [
            {"id": "ana", "email": "ana@acme.example"},
            {"id": "ben", "email": "ben@acme.example"},
        ]}

    def post(self, path, body):
        if path == "connectors/calendar/actions/claim":
            return {"action": None}
        if path.startswith("connectors/calendar/actions/"):
            self.results.append((path, body))
            return {"ok": True}
        assert path == "connectors/calendar/snapshots"
        self.published.append(body)
        return {"ok": True}


def test_connector_worker_publishes_successes_without_cloud_provider_credentials(tmp_path):
    script = tmp_path / "hub/scripts/mail.sh"
    script.parent.mkdir(parents=True)
    script.write_text("#!/bin/sh\nexit 1\n")
    script.chmod(os.stat(script).st_mode | 0o100)
    client = FakeClient()
    publisher = ConnectorPublisher({"url": "http://localhost:8765", "token": "test",
                                    "projects_dir": str(tmp_path)}, client=client,
                                   fetch=lambda email, hours: [event(email)] if email.startswith("ana") else [])
    assert publisher.tick() == 2
    assert len(client.published) == 1
    snapshots = client.published[0]["snapshots"]
    assert snapshots[0]["email"] == "ana@acme.example" and snapshots[0]["events"][0]["title"] == "ana@acme.example"
    assert snapshots[1] == {"email": "ben@acme.example", "events": []}

    def partial(email, hours):
        if email.startswith("ben"):
            raise RuntimeError("provider detail must remain local")
        return [event()]
    publisher.fetch = partial
    # A failed account is logged on this Mac (account and error class only) and keeps its prior
    # cloud snapshot; the tick still publishes the others and never raises the provider detail.
    lines = []
    publisher.accounts["ben@acme.example"] = Outage("Tico connectors", "calendar refresh failed for ben@acme.example",
                                                  "still failing", "working again", out=lines.append)
    assert publisher.tick() == 1
    assert len(client.published) == 2 and len(client.published[-1]["snapshots"]) == 1
    assert lines == ["Tico connectors: calendar refresh failed for ben@acme.example (RuntimeError); retrying"]
    assert not any("provider detail" in str(call) for call in client.published)


def test_connector_worker_executes_each_calendar_action_once_and_reports_result(tmp_path):
    class ActionClient:
        def __init__(self):
            self.actions = [{"id": "a1", "calendar": "ana@acme.example", "title": "Call",
                             "start": "2030-09-22T09:00:00-07:00",
                             "end": "2030-09-22T09:30:00-07:00", "attendees": []}]
            self.results = []

        def post(self, path, body):
            if path == "connectors/calendar/actions/claim":
                return {"action": self.actions.pop(0) if self.actions else None}
            self.results.append((path, body))
            return {"ok": True}

    client, calls = ActionClient(), []
    publisher = ConnectorPublisher(
        {"url": "http://localhost:8765", "token": "test", "projects_dir": str(tmp_path)},
        client=client, event=lambda action: calls.append(action["id"]) or
        {"event_id": "event-1", "meeting_url": "https://meet.google.com/abc-defg-hij"})
    assert publisher.calendar_action_tick() == 1
    assert calls == ["a1"]
    assert client.results == [("connectors/calendar/actions/a1/result", {
        "status": "succeeded", "event_id": "event-1",
        "meeting_url": "https://meet.google.com/abc-defg-hij", "error": ""})]


def mail_message(**overrides):
    row = {"msg_id": "m-plain", "thread_id": "t-plain", "epoch": 1_783_368_400,
           "date": "2026-09-02T09:30:00-07:00", "from_addr": "person@customer.example",
           "from_header": "Real Person <person@customer.example>", "to": ["ana@acme.example"],
           "cc": [], "subject": "Pricing question", "snippet": "How does",
           "labels": ["INBOX", "UNREAD"], "body": "How does pricing work?",
           "body_truncated": False, "attachments": [], "list_id": "",
           "is_internal": False, "has_unsubscribe": False}
    row.update(overrides)
    return row


def mail_publish(mailbox="ana@acme.example", messages=None, deleted=None, **extra):
    body = {"mailbox": mailbox, "messages": messages if messages is not None else [mail_message()],
            "deleted": deleted or [], "synced_at": "2026-09-16T20:00:00+00:00"}
    body.update(extra)
    return body


def test_mail_tables_are_owner_only_in_sql(api):
    from backend.tests.test_sql import column, query

    machine = runner(api)
    post(api, "connectors/mail/messages", mail_publish(), machine["token"])
    assert column(api, "SELECT msg_id FROM mail_messages") == ["m-plain"]
    assert column(api, "SELECT address FROM mail_mailboxes") == ["ana@acme.example"]
    assert column(api, "SELECT msg_id FROM mail_fts") == ["m-plain"]
    assert query(api, "SELECT msg_id FROM mail_messages", "ben-test")["rows"] == []
    assert query(api, "SELECT address FROM mail_mailboxes", "ben-test")["rows"] == []
    assert query(api, "SELECT msg_id FROM mail_fts", "ben-test")["rows"] == []


def test_a_disconnected_connector_shows_in_settings_and_clears_itself(api):
    # See programmatically when something disconnected. The Mac reports each
    # refresh: a refused Google sign-in needs a person, a network drop only says the Mac is retrying.
    machine = runner(api)
    issues = lambda: [i for i in api.get("/api/status", headers=headers()).json()["health_issues"]
                      if i["kind"] == "service" and i["title"].startswith("connector:")]
    post(api, "connectors/health", {"service": "calendar", "failing": [
        {"account": "ben@acme.example", "reason": "signin"}, {"account": "ana@acme.example", "reason": "network"}]},
        machine["token"])
    [issue] = issues()
    assert issue["needs_person"] is True and issue["action"] == "Reconnect the Google account for ben@acme.example"
    assert "sign-in was refused" in issue["detail"] and "keeps retrying" in issue["detail"]
    post(api, "connectors/health", {"service": "mail", "failing": [{"account": "ana@acme.example", "reason": "network"}]},
         machine["token"])
    mail = next(i for i in issues() if i["title"].startswith("connector:mail"))
    assert mail["needs_person"] is False
    # Only the kind of failure is accepted: no provider message rides along.
    post(api, "connectors/health", {"service": "mail", "failing": [
        {"account": "ana@acme.example", "reason": "network", "detail": "provider text"}]}, machine["token"], expected=422)
    post(api, "connectors/health", {"service": "calendar", "failing": []}, machine["token"])
    post(api, "connectors/health", {"service": "mail", "failing": []}, machine["token"])
    assert issues() == []
    # A refresh that just stops writes no error; its age says so while a Mac is online.
    post(api, "runners/heartbeat", {"version": "test", "platform": "test", "readiness": {}}, machine["token"])
    with api.app.state.store.transaction() as c:
        c.execute("UPDATE service_health SET last_success=? WHERE service='connector:calendar'",
                  (H.shift(H.now(), minutes=-40),))
    [stale] = issues()
    assert "Calendar last refreshed 40 minutes ago" in stale["detail"] and stale["needs_person"] is False
    # A person who is not a connector Mac can't write health.
    post(api, "connectors/health", {"service": "mail", "failing": []}, "ben-test", expected=403)


def test_the_mac_reports_each_refresh_with_the_kind_of_failure_only(tmp_path):
    from runner.connectors import failure_reason
    import subprocess
    script = tmp_path / "hub/scripts/mail.sh"
    script.parent.mkdir(parents=True)
    script.write_text("#!/bin/sh\nexit 1\n")
    script.chmod(os.stat(script).st_mode | 0o100)
    client, health = FakeClient(), []
    real = client.post
    client.post = lambda path, body: health.append(body) or {"ok": True} if path == "connectors/health" else real(path, body)

    def fetch(email, hours):
        if email.startswith("ben"):
            raise RuntimeError("invalid_grant: provider detail must remain local")
        return []
    publisher = ConnectorPublisher({"url": "http://localhost:8765", "token": "test", "projects_dir": str(tmp_path)},
                                   client=client, fetch=fetch)
    publisher.accounts["ben@acme.example"] = Outage("t", "d", "s", "u", out=lambda line: None)
    assert publisher.tick() == 1
    assert health == [{"service": "calendar", "failing": [{"account": "ben@acme.example", "reason": "signin"}]}]
    assert "provider detail" not in json.dumps(health)
    assert failure_reason(subprocess.TimeoutExpired("mail.sh", 30)) == "network"
    assert failure_reason(ConnectionResetError()) == "network"
    assert failure_reason(ValueError("bad json")) == "error"


def test_the_mac_publishes_only_the_calendar_fields_the_hub_takes(tmp_path):
    # 2026-09-27: the CLI's extra Google fields (id, iCalUID, summary, htmlLink, status) made the
    # hub refuse the whole snapshot publish with a 422.
    from backend.connectors import CalendarPublish
    script = tmp_path / "hub/scripts/mail.sh"
    script.parent.mkdir(parents=True)
    rich = {**event(), "id": "provider-event", "iCalUID": "x@google.com", "summary": "Product sync",
            "htmlLink": "https://www.google.com/calendar/event?eid=x", "status": "confirmed"}
    script.write_text("#!/bin/sh\necho '" + json.dumps({"events": [rich]}) + "'\n")
    script.chmod(os.stat(script).st_mode | 0o100)
    publisher = ConnectorPublisher({"url": "http://localhost:8765", "token": "test", "projects_dir": str(tmp_path)},
                                   client=FakeClient())
    publisher.script = script                   # the publisher runs this checkout's script otherwise
    events = publisher.calendar("ana@acme.example", 24)
    assert set(events[0]) == {"occurrence_id", "event_id", "title", "start", "end", "attendees", "meeting_url"}
    CalendarPublish(snapshots=[{"email": "ana@acme.example", "events": events}])


def test_people_who_left_are_not_calendar_targets_and_a_missing_mailbox_is_not_a_sign_in(api):
    # 2026-09-27: marcus and nora (hidden on the roster) failed invalid_grant for 49 hours.
    from runner.connectors import failure_reason
    from backend.store import encode
    machine = runner(api)
    with api.app.state.store.transaction() as c:
        c.execute("INSERT OR IGNORE INTO humans(id,email) VALUES('gone','gone@acme.example')")
        row = c.execute("SELECT value_json FROM registry_metadata WHERE key='people'").fetchone()
        people = json.loads(row[0])["people"] + [{"id": "gone", "email": "gone@acme.example", "hidden": True}]
        c.execute("UPDATE registry_metadata SET value_json=? WHERE key='people'", (encode({"people": people}),))
    targets = get(api, "connectors/calendar/targets", machine["token"])["people"]
    assert "gone@acme.example" not in [p["email"] for p in targets] and targets
    assert failure_reason(RuntimeError("invalid_grant: Invalid email or User ID")) == "error"
    assert failure_reason(RuntimeError("invalid_grant: Token has been expired or revoked")) == "signin"


def test_the_hub_says_which_connectors_a_computer_runs(api):
    machine = runner(api)
    assert get(api, "runners/connectors", machine["token"]) == {"connectors": []}     # the Google key decides
    api.app.state.store.settings.processing_operators = ("ana",)
    assert get(api, "runners/connectors", machine["token"]) == {"connectors": ["mail", "calendar"]}
    other = runner(api, operator="ben", label="Other")
    assert get(api, "runners/connectors", other["token"]) == {"connectors": []}
