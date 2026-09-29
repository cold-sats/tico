"""Close transcripts enter as finished meetings through the runner door (backend/imports.py)."""

from backend.store import H
from backend.tests.test_api import api, headers, post, runner  # noqa: F401


def transcript(kind="call", activity="acti_one", **changes):
    body = {"source": "close", "resource_type": kind, "external_id": activity,
            "owner_email": "ben@acme.example", "title": "Pricing call",
            "started": "2026-09-19T10:00:00-07:00", "ended": "2026-09-19T10:05:00-07:00",
            "duration_ms": 300000, "source_updated_at": "2026-09-19T17:07:00Z",
            "context": {"lead_name": "Dana Reyes", "lead_url": "https://app.close.com/lead/lead_1/"},
            "summary_text": "Dana asked for pricing.",
            "turns": [{"text": "Can you send pricing?", "start_ms": 1000, "end_ms": 3000,
                       "speaker": "Dana Reyes", "side": "contact"}]}
    body.update(changes)
    return body


def test_close_transcript_import_is_idempotent_and_has_no_audio_or_job(api):
    machine = runner(api)
    post(api, "imports/transcripts", transcript(), expected=403)
    first = post(api, "imports/transcripts", transcript(), machine["token"])
    assert first["status"] == "done" and first["changed"] is True
    rid = first["id"]
    again = post(api, "imports/transcripts", transcript(), machine["token"])
    assert again["id"] == rid and again["changed"] is False
    record = api.get("/api/meetings/" + rid, headers=headers("cara-test")).json()
    assert record["source"] == "close" and record["source_type"] == "call"
    assert record["transcript_provider"] == "close"
    assert record["turns"][0]["speaker"] == "Dana Reyes"
    assert "Can you send pricing?" in record["transcript_readable"]
    assert record["notes"] == "Dana asked for pricing."
    assert record["can_edit"] is False
    assert len(record["transcript_sources"]) == 1 and record["transcript_sources"][0]["primary"]
    with api.app.state.store.read() as c:
        assert c.execute("SELECT count(*) FROM media_assets WHERE meeting_id=?", (rid,)).fetchone()[0] == 0
        assert c.execute("SELECT count(*) FROM service_jobs WHERE resource_id=?", (rid,)).fetchone()[0] == 0
        assert c.execute("SELECT count(*) FROM recording_transcripts WHERE meeting_id=?", (rid,)).fetchone()[0] == 1
