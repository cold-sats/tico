"""Settings for the meeting importers, their heartbeats, and one real import through the hub."""
from datetime import datetime, timedelta, timezone

from clients.tico import APIError
from runner.importers import fireflies
from runner.state import State

from backend.tests.test_api import api, get, headers, post, runner  # noqa: F401


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
