"""Settings for the meeting importers, their heartbeats, and one real import through the hub."""
from datetime import datetime, timedelta, timezone

from clients.tico import APIError
from runner.importers import fireflies
from runner.state import State

from backend.tests.test_api import api, get, headers, post, runner  # noqa: F401


def test_only_the_owner_configures_and_the_machine_learns_what_to_run(api):
    machine = runner(api)
    other = runner(api, "ben", "Ben Mac")
    listing = get(api, "meeting-importers")
    assert [i["source"] for i in listing["importers"]] == ["fireflies", "zoom", "google-meet", "granola"]
    assert all(i["status"] == "off" and i["setup"]["file"].startswith("secrets/") for i in listing["importers"])
    assert {c["id"] for c in listing["computers"]} == {machine["runner_id"]}        # Ben's Mac may not run importers
    assert api.get("/api/v2/meeting-importers", headers=headers("ben-test")).status_code == 403
    post(api, "meeting-importers/fireflies", {"enabled": True, "runner_id": machine["runner_id"]}, "ben-test", expected=403)
    post(api, "meeting-importers/fireflies", {"enabled": True, "runner_id": other["runner_id"]}, expected=422)
    post(api, "meeting-importers/nope", {"enabled": True, "runner_id": machine["runner_id"]}, expected=404)
    post(api, "meeting-importers/fireflies", {"enabled": True, "runner_id": machine["runner_id"]})
    assert get(api, "runners/importers", machine["token"]) == {"importers": [{"source": "fireflies"}]}
    get(api, "runners/importers", other["token"], expected=403)             # not a machine that may run importers
    row = [i for i in get(api, "meeting-importers")["importers"] if i["source"] == "fireflies"][0]
    assert row["enabled"] and row["status"] == "waiting" and row["runner_label"] == "Test Mac"
    post(api, "meeting-importers/fireflies", {"enabled": False, "runner_id": machine["runner_id"]})
    assert get(api, "runners/importers", machine["token"]) == {"importers": []}


def test_heartbeats_show_counts_the_last_error_and_the_sources_strip(api):
    machine = runner(api)
    post(api, "meeting-importers/zoom", {"enabled": True, "runner_id": machine["runner_id"]})
    post(api, "imports/sources/zoom/status", {"state": "ok", "imported": 2}, machine["token"])
    post(api, "imports/sources/zoom/status", {"state": "ok", "imported": 1}, machine["token"])
    zoom = [i for i in get(api, "meeting-importers")["importers"] if i["source"] == "zoom"][0]
    assert zoom["status"] == "syncing" and zoom["imported_total"] == 3 and zoom["last_import"] and zoom["error"] == ""
    strip = {s["id"]: s for s in api.get("/api/meetings/sources", headers=headers("ben-test")).json()["sources"]}
    assert strip["zoom"]["status"] == "syncing" and strip["zoom"]["imported"] == 3 and "granola" not in strip
    post(api, "imports/sources/zoom/status", {"state": "error", "error_code": "auth_failed", "message": "Zoom refused the credential"},
         machine["token"])
    zoom = [i for i in get(api, "meeting-importers")["importers"] if i["source"] == "zoom"][0]
    assert zoom["status"] == "error" and zoom["error_code"] == "auth_failed" and zoom["error"] == "Zoom refused the credential"
    post(api, "imports/sources/zoom/status", {"state": "ok"}, "ben-test", expected=403)
    post(api, "imports/sources/close-ish/status", {"state": "ok"}, machine["token"], expected=404)
    post(api, "imports/sources/zoom/status", {"state": "error", "error_code": "Bad Code!"}, machine["token"], expected=422)
    # Moving an importer to another computer starts from a clean status.
    second = runner(api, "ana", "Second Mac")
    post(api, "meeting-importers/zoom", {"enabled": True, "runner_id": second["runner_id"]})
    zoom = [i for i in get(api, "meeting-importers")["importers"] if i["source"] == "zoom"][0]
    assert zoom["status"] == "waiting" and zoom["error"] == "" and zoom["imported_total"] == 0


class HubClient:
    """The runner's client, pointed at the test hub."""

    def __init__(self, api, token):
        self.api, self.token = api, token

    def get(self, path, **query):
        r = self.api.get("/api/v2/" + path, headers=headers(self.token))
        assert r.status_code == 200, r.text
        return r.json()

    def post(self, path, body=None, key=None):
        r = self.api.post("/api/v2/" + path, json=body or {}, headers=headers(self.token))
        if r.status_code != 200:
            error = r.json().get("error", {})
            raise APIError(error.get("code", "http_error"), error.get("detail", ""), r.status_code)
        return r.json()


def test_an_importer_files_real_meetings_once_and_updates_them_in_place(api, tmp_path):
    machine = runner(api)
    when = datetime(2026, 9, 28, 18, 0, tzinfo=timezone.utc)
    detail = {"id": "ff1", "title": "Pricing call", "date": int((when).timestamp() * 1000), "duration": 1,
              "organizer_email": "dana@example.com", "participants": ["dana@example.com", "ben@acme.example"],
              "transcript_url": "https://app.fireflies.ai/view/ff1", "meeting_link": "https://zoom.us/j/1",
              "summary": {"overview": "Pricing."}, "meeting_attendees": [],
              "sentences": [{"speaker_name": "Dana", "text": "Can you send pricing?", "start_time": 1, "end_time": 3}]}

    def transport(method, url, headers=None, body=None, form=None, raw=False):
        query = body["query"]
        if "user {" in query:
            return {"data": {"user": {"email": "ben@acme.example"}}}
        if "transcripts(" in query:
            return {"data": {"transcripts": [{"id": "ff1", "title": detail["title"], "date": detail["date"], "duration": 1}]}}
        return {"data": {"transcript": detail}}

    def importer():
        return fireflies.Fireflies({"projects_dir": str(tmp_path), "url": "x", "token": "x"}, State(tmp_path / "state"),
                                   HubClient(api, machine["token"]), env={"FIREFLIES_API_KEY": "k"}, transport=transport,
                                   now=lambda: when + timedelta(hours=1))

    assert importer().tick() == 1
    with api.app.state.store.read() as c:
        assert c.execute("SELECT count(*) FROM meetings").fetchone()[0] == 1
    assert importer().tick() == 0                                       # remembered: nothing new to file
    detail["summary"] = {"overview": "Pricing, revised."}
    detail["title"] = "Pricing call (revised)"
    lost = importer()
    lost.state = State(tmp_path / "another-computer")                    # a computer with no memory of the first
    assert lost.tick() == 1
    with api.app.state.store.read() as c:
        assert c.execute("SELECT count(*) FROM meetings").fetchone()[0] == 1          # same meeting, updated in place
        row = c.execute("SELECT title,notes,owner FROM meetings").fetchone()
        assert row["title"] == "Pricing call (revised)" and row["notes"].startswith("Pricing, revised")
