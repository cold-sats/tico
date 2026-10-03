"""Retired importers disappear from setup while old data and authorized clients remain compatible."""
import json

import pytest

from backend.store import H
from backend.tests.test_api import api, get, headers, post, runner, setup_attempt  # noqa: F401


def historical_meeting(api, machine):
    return post(api, "meetings/import", {"source": "fireflies", "external_id": "historical-1",
                "title": "Historical meeting", "transcript": "Sam: Preserve the recording.",
                "notes": "Original shared notes", "owner_email": "ben@acme.example",
                "media_url": "https://example.com/recording/historical-1"}, machine["token"])


def persisted_setting(api, machine):
    with api.app.state.store.transaction() as c:
        c.execute("INSERT INTO meeting_importers VALUES(?,?,?,?,?)",
                  ("fireflies", 1, machine["runner_id"], "human:ana", H.now()))
        c.execute("INSERT INTO service_health(service,last_success,last_error,detail_json) VALUES(?,?,NULL,?)",
                  ("recording:fireflies", H.now(), json.dumps({"imported_total": 7})))


def test_historical_source_still_deduplicates_and_preserves_versions_and_files(api):
    machine = runner(api)
    first = historical_meeting(api, machine)
    again = historical_meeting(api, machine)
    assert first["id"] == again["id"] and not again["changed"]
    rid = first["id"]
    attached = api.post("/api/meetings/" + rid + "/attachments", headers=headers("ben-test"),
                        files={"files": ("history.txt", b"Historical attachment", "text/plain")})
    assert attached.status_code == 200, attached.text
    before = api.get("/api/meetings/" + rid, headers=headers("ben-test")).json()
    persisted_setting(api, machine)
    assert post(api, "meeting-importers/fireflies", {"enabled": False, "runner_id": ""}) == {"ok": True}
    after = api.get("/api/meetings/" + rid, headers=headers("ben-test")).json()
    for field in ("notes", "turns", "media_url", "source", "attachments", "review_state"):
        assert after[field] == before[field]
    blob = after["attachments"][0]["id"]
    downloaded = api.get("/api/v2/files/" + blob, headers=headers("ben-test"))
    assert downloaded.status_code == 200 and downloaded.content == b"Historical attachment"
    versions = api.get("/api/meetings/" + rid + "/versions", headers=headers("ben-test")).json()["versions"]
    assert any(v["notes"] == "Original shared notes" for v in versions)
    with api.app.state.store.read() as c:
        assert c.execute("SELECT count(*) FROM meetings").fetchone()[0] == 1


def test_retired_persisted_settings_are_hidden_unassigned_and_can_be_disabled(api):
    machine = runner(api)
    persisted_setting(api, machine)
    assert "fireflies" not in {r["source"] for r in get(api, "meeting-importers")["importers"]}
    assert get(api, "runners/importers", machine["token"])["importers"] == []
    assert "fireflies" not in {r["id"] for r in api.get("/api/meetings/sources", headers=headers()).json()["sources"]}
    assert post(api, "meeting-importers/fireflies", {"enabled": True, "runner_id": machine["runner_id"]}, expected=410)
    with api.app.state.store.read() as c:
        assert c.execute("SELECT enabled FROM meeting_importers WHERE source='fireflies'").fetchone()[0] == 1
    assert post(api, "meeting-importers/fireflies", {"enabled": False, "runner_id": ""}) == {"ok": True}
    with api.app.state.store.read() as c:
        assert c.execute("SELECT enabled FROM meeting_importers WHERE source='fireflies'").fetchone()[0] == 0
        detail = c.execute("SELECT detail_json FROM service_health WHERE service='recording:fireflies'").fetchone()[0]
        assert json.loads(detail)["imported_total"] == 7


def test_authorized_old_runner_retired_heartbeat_is_acknowledged_without_rewriting_history(api):
    machine = runner(api)
    persisted_setting(api, machine)
    with api.app.state.store.read() as c:
        before = tuple(c.execute("SELECT * FROM service_health WHERE service='recording:fireflies'").fetchone())
    assert post(api, "imports/sources/fireflies/status", {"state": "ok", "imported": 100}, machine["token"]) == {"ok": True}
    with api.app.state.store.read() as c:
        assert tuple(c.execute("SELECT * FROM service_health WHERE service='recording:fireflies'").fetchone()) == before


@pytest.mark.parametrize("actor", ["owner", "member", "bot", "revoked_runner"])
def test_retired_heartbeat_still_requires_authorized_importer(api, actor):
    machine = runner(api)
    token, expected = "ana-test", 403
    if actor == "member":
        token = "ben-test"
    elif actor == "bot":
        token = setup_attempt(api)[2]["token"]
    elif actor == "revoked_runner":
        with api.app.state.store.transaction() as c:
            c.execute("UPDATE runners SET revoked_at=? WHERE id=?", (H.now(), machine["runner_id"]))
        token, expected = machine["token"], 401
    assert post(api, "imports/sources/fireflies/status", {"state": "ok"}, token, expected=expected)


def test_available_importer_configuration_and_status_are_unchanged(api):
    machine = runner(api)
    assert post(api, "meeting-importers/zoom", {"enabled": True, "runner_id": machine["runner_id"]}) == {"ok": True}
    assert get(api, "runners/importers", machine["token"])["importers"] == [{"source": "zoom"}]
    assert post(api, "imports/sources/zoom/status", {"state": "ok", "imported": 2}, machine["token"]) == {"ok": True}
    listed = next(r for r in get(api, "meeting-importers")["importers"] if r["source"] == "zoom")
    assert listed["status"] == "syncing" and listed["imported_total"] == 2


def test_retained_retired_health_does_not_ask_to_reconnect(api):
    machine = runner(api)
    persisted_setting(api, machine)
    with api.app.state.store.transaction() as c:
        c.execute("UPDATE service_health SET last_error=?,detail_json=? WHERE service='recording:fireflies'",
                  (H.now(), json.dumps({"error_code": "auth_failed", "message": "Reconnect Fireflies"})))
    response = api.get("/api/v2/health", headers=headers())
    assert response.status_code == 200, response.text
    assert "fireflies" not in json.dumps(response.json()["checks"]).lower()
