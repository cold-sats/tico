"""One import API for every source (`POST /api/v2/meetings/import`, docs/meetings.md)."""
import json

from backend.tests.test_api import api, get, headers, post, runner, setup_attempt  # noqa: F401
from backend.tests.test_media import import_meeting, media_post
from backend.tests.test_routines import DEBRIEF, create, setup

TEXT = "[00:05] Ana: Let's raise the annual plan.\n[01:10] Ben: Ten percent, then."
VTT = "WEBVTT\n\n00:00:05.000 --> 00:00:08.000\n<v Ana>Let's raise the annual plan.</v>\n\n00:01:10.000 --> 00:01:12.000\n<v Ben>Ten percent, then.</v>\n"
SRT = "1\n00:00:05,000 --> 00:00:08,000\nAna: Let's raise the annual plan.\n\n2\n00:01:10,000 --> 00:01:12,000\nBen: Ten percent, then.\n"
SEGMENTS = [{"speaker": "Ana", "start": 5, "end": 8, "text": "Let's raise the annual plan."},
            {"speaker": "Ben", "start": 70, "end": 72, "text": "Ten percent, then."}]


def meeting(api, rid, token="ana-test"):
    r = api.get("/api/meetings/" + rid, headers=headers(token))
    assert r.status_code == 200, r.text
    return r.json()


def test_every_format_lands_as_the_same_segments(api):
    seen = []
    for name, transcript in (("text", TEXT), ("vtt", VTT), ("srt", SRT), ("json", SEGMENTS), ("json-string", json.dumps(SEGMENTS))):
        made = import_meeting(api, title=name, transcript=transcript, source="zoom", external_id=name)
        assert made["turns"] == 2 and made["existing"] is False
        record = meeting(api, made["id"])
        seen.append([(t["speaker"], t["start_ms"], t["text"]) for t in record["turns"]])
        assert record["kind"] == "meeting" and record["status"] == "done" and record["source"] == "zoom"
        assert "Ten percent, then." in record["transcript_readable"]
    assert all(one == seen[0] for one in seen) and seen[0][0] == ("Ana", 5000, "Let's raise the annual plan.")


def test_the_same_source_and_id_updates_the_meeting_and_never_duplicates_it(api):
    first = import_meeting(api, transcript=TEXT, source="granola", external_id="g-1", title="Pricing")
    again = import_meeting(api, transcript=TEXT, source="granola", external_id="g-1", title="Pricing")
    assert again["id"] == first["id"] and again["existing"] is True and again["changed"] is False
    changed = import_meeting(api, transcript="Ana: Changed our mind.", source="granola", external_id="g-1", title="Pricing", notes="## Decision\nHold.")
    assert changed["id"] == first["id"] and changed["changed"] is True and changed["turns"] == 1
    record = meeting(api, first["id"])
    assert record["title"] == "Pricing" and [t["text"] for t in record["turns"]] == ["Changed our mind."]
    assert record["notes"].startswith("## Decision")
    with api.app.state.store.read() as c:
        assert c.execute("SELECT count(*) FROM meetings").fetchone()[0] == 1
        assert c.execute("SELECT count(*) FROM meeting_versions WHERE meeting_id=?", (first["id"],)).fetchone()[0] >= 2
    # The key is per source and per person: another source, or another person, is another meeting.
    assert import_meeting(api, transcript=TEXT, source="otter", external_id="g-1")["id"] != first["id"]
    assert import_meeting(api, "ben-test", transcript=TEXT, source="granola", external_id="g-1")["id"] != first["id"]
    # A meeting somebody deleted is not brought back.
    media_post(api, f"meetings/{first['id']}/delete", {})
    gone = import_meeting(api, transcript=TEXT, source="granola", external_id="g-1")
    assert gone == {"id": first["id"], "status": "deleted", "existing": True, "changed": False}


def test_participants_are_linked_to_the_roster_and_a_private_meeting_stays_theirs(api):
    made = import_meeting(api, "ben-test", participants=["Cara@Acme.example", "Ana", {"name": "Dana Reyes", "email": "dana@example.com"}],
                          private=True)
    record = meeting(api, made["id"], "ben-test")
    people = {p["email"] or p["name"]: p for p in record["participants"]}
    assert people["cara@acme.example"]["person_id"] == "cara" and people["cara@acme.example"]["name"]
    assert people["dana@example.com"]["person_id"] is None and people["dana@example.com"]["name"] == "Dana Reyes"
    assert [p["person_id"] for p in record["participants"]].count("ana") == 1
    assert "cara@acme.example" in record["confirmed_attendees"] and "Participants" in record["meeting_context"]
    # Private: its participants read it, and only its owner (or the company owner) edits it.
    assert meeting(api, made["id"], "cara-test")["can_edit"] is False


def test_a_bot_cannot_import_and_a_machine_files_only_for_a_person_on_the_roster(api):
    body = {"title": "From a machine", "transcript": TEXT, "source": "granola", "external_id": "g-7"}
    _, _, attempt = setup_attempt(api)
    assert api.post("/api/v2/meetings/import", json=body, headers=headers(attempt["token"])).status_code == 403
    machine, elsewhere = runner(api), runner(api, "ben", "Ben test Mac")
    for token, extra, status in ((machine["token"], {}, 404), (machine["token"], {"owner_email": "nobody@example.com"}, 404),
                                 (elsewhere["token"], {"owner_email": "ben@acme.example"}, 403)):
        assert api.post("/api/v2/meetings/import", json={**body, **extra}, headers=headers(token)).status_code == status
    made = api.post("/api/v2/meetings/import", json={**body, "owner_email": "Ben@Acme.example"}, headers=headers(machine["token"])).json()
    record = meeting(api, made["id"], "ben-test")
    assert record["owner"] == "ben@acme.example" and record["can_edit"] is True and record["uploaded_by"] == machine["runner_id"]
    # It is the same meeting whichever door files it: the key is the person's, not the machine's.
    again = import_meeting(api, "ben-test", title="From a machine", transcript=TEXT, source="granola", external_id="g-7")
    assert again["id"] == made["id"] and again["existing"] is True
    # A person files only their own, and Close is filed by its own worker.
    assert import_meeting(api, "ben-test", owner_email="ana@acme.example", expected=403)
    assert "own importer" in import_meeting(api, source="close", expected=422)["error"]["detail"]


def test_send_to_hands_the_meeting_to_a_bot_the_person_may_use_and_a_routine_hears_it(api):
    runner_ = setup(api)
    create(api, "ops", DEBRIEF)
    made = import_meeting(api, send_to="coo", source="zoom", external_id="z-1")
    assert made["sent"]["slug"] == "coo"
    owners = {t["owner"]: t for t in get(api, "tasks")["tasks"]}
    assert "ship on Friday" in owners["bot:coo"]["body"]
    debrief = [t for t in owners.values() if t["owner"] == "bot:ops"]
    assert len(debrief) == 1 and "Meeting debrief" in debrief[0]["title"] and "ship on Friday" in debrief[0]["body"]
    # An update never fires the routine again, and a private meeting never fires it at all.
    import_meeting(api, send_to="coo", source="zoom", external_id="z-1", notes="More.")
    import_meeting(api, private=True, source="zoom", external_id="z-2")
    assert len([t for t in get(api, "tasks")["tasks"] if t["owner"] == "bot:ops"]) == 1
    assert runner_
    # A bot the caller may not hand work to refuses the whole import, leaving nothing behind.
    with api.app.state.store.read() as c:
        before = c.execute("SELECT count(*) FROM meetings").fetchone()[0]
    import_meeting(api, "cara-test", send_to="no-such-bot", source="zoom", external_id="z-3", expected=404)
    with api.app.state.store.read() as c:
        assert c.execute("SELECT count(*) FROM meetings").fetchone()[0] == before


def test_the_mcp_tool_and_the_cli_file_a_meeting_the_same_way(api, tmp_path):
    from backend.tests.test_mcp import call
    from clients import hubtools
    err, made = call(api, "hub_meeting_import", {"title": "From a tool", "transcript": TEXT, "source": "zoom", "external_id": "m-1"})
    assert not err and made["turns"] == 2 and made["link"].startswith("#/meetings?meeting=")
    err, again = call(api, "hub_meeting_import", {"title": "From a tool", "transcript": TEXT, "source": "zoom", "external_id": "m-1"})
    assert again["id"] == made["id"] and again["changed"] is False
    err, found = call(api, "hub_meeting_search", {"q": "annual plan"})
    assert [r["id"] for r in found["results"]] == [made["id"]]
    # `hub meeting import <file>` reads the file itself: the name is the title, --date takes this
    # Mac's zone, and a format is only sent when it was chosen.
    sent = []
    class Api:
        def post(self, path, body, key=None):
            sent.append((path, body))
            return {"id": "m"}
    (tmp_path / "Pricing call.vtt").write_text(VTT)
    (tmp_path / "notes.md").write_text("Summary.")
    hubtools.meetings_import_file(Api(), {"file": str(tmp_path / "Pricing call.vtt"), "date": "2026-09-28T16:00",
                                          "participants": ["a@b.com"], "source": "granola", "external_id": "g-2",
                                          "format": "auto", "notes_file": str(tmp_path / "notes.md")})
    path, body = sent[0]
    assert path == "meetings/import" and body["title"] == "Pricing call" and body["transcript"] == VTT
    assert body["participants"] == ["a@b.com"] and body["notes"] == "Summary." and body["source"] == "granola"
    assert body["started_at"].startswith("2026-09-28T16:00:00") and body["started_at"][-6] in "+-"
    try:
        hubtools.meetings_import_file(Api(), {"file": str(tmp_path / "notes.md"), "date": "last tuesday"})
    except ValueError as exc:
        assert "not a date" in str(exc)
    else:
        raise AssertionError("a bad --date must be refused")

