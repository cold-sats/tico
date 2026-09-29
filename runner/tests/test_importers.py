"""Meeting importers, offline: recorded provider responses in, hub import bodies out.

The fixtures follow the providers' published schemas (Fireflies GraphQL, Granola v1 OpenAPI,
Zoom Meetings API, Google Meet REST v2). Nothing here touches a network, and no credential is real.
"""

import base64
import json
import threading
import urllib.error
import urllib.parse
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa

from backend.imports import MeetingImport
from clients.tico import APIError
from runner.importers import base, fireflies, google_meet, granola, zoom
from runner.importers.base import ProviderError
from runner.importers.service import ImporterService, doctor
from runner.state import State

NOW = datetime(2026, 9, 28, 20, 0, tzinfo=timezone.utc)
OWNER = "ana@acme.example"
KEY = "sk-live-SECRET-KEY-123"


class Hub:
    """Just enough of the hub: the import door keyed like the real one, and the status door."""

    def __init__(self, roster=(OWNER, "ben@acme.example")):
        self.roster, self.meetings, self.posts, self.statuses = set(roster), {}, [], []

    def get(self, path, **query):
        if path == "config":
            return {"owner_email": OWNER}
        if path == "runners/importers":
            return {"importers": [{"source": s} for s in getattr(self, "enabled", [])]}
        raise AssertionError(path)

    def post(self, path, body=None, key=None):
        if path.startswith("imports/sources/"):
            self.statuses.append((path.split("/")[2], body))
            return {"ok": True}
        assert path == "meetings/import"
        self.posts.append(body)
        MeetingImport.model_validate(body)              # the real contract accepts every body
        if body["owner_email"] not in self.roster:
            raise APIError("not_found", "owner_email must name a person on the Tico roster", 404)
        key = (body["source"], body["owner_email"], body["external_id"])
        existing = key in self.meetings
        changed = self.meetings.get(key) != body
        self.meetings[key] = body
        return {"id": "m" + str(len(self.meetings)), "existing": existing, "changed": changed, "status": "done"}


def make(cls, tmp_path, transport, env, **extra):
    hub = extra.pop("hub", None) or Hub()
    state = State(tmp_path / "state")
    config = {"projects_dir": str(tmp_path / "projects"), "url": "https://hub.test", "token": "t"}
    return cls(config, state, hub, env=env, transport=transport, now=lambda: NOW, **extra), hub, state


class Recorder:
    """A transport that answers from a routing function and remembers every call."""

    def __init__(self, route):
        self.route, self.calls = route, []

    def __call__(self, method, url, headers=None, body=None, form=None, raw=False):
        parsed = urllib.parse.urlsplit(url)
        call = SimpleNamespace(method=method, url=url, path=parsed.path, host=parsed.netloc, headers=headers or {},
                               query=dict(urllib.parse.parse_qsl(parsed.query)), body=body, form=form)
        self.calls.append(call)
        return self.route(call)


# ---------------------------------------------------------------- Fireflies

def ff_route(pages, details, user=OWNER, errors=None):
    def route(call):
        query = call.body["query"]
        if errors:
            return {"errors": errors}
        if "user {" in query:
            return {"data": {"user": {"email": user, "name": "Ana"}}}
        if "transcripts(" in query:
            skip = call.body["variables"]["skip"]
            return {"data": {"transcripts": pages[skip // fireflies.PAGE] if skip // fireflies.PAGE < len(pages) else []}}
        return {"data": {"transcript": details[call.body["variables"]["id"]]}}
    return route


def ff_detail(ident="ff1", sentences=None, **changes):
    row = {"id": ident, "title": "Pricing call", "date": 1790000000000, "duration": 30,
           "organizer_email": "dana@example.com", "participants": ["dana@example.com", OWNER],
           "transcript_url": "https://app.fireflies.ai/view/ff1", "audio_url": "https://cdn.fireflies.ai/a.mp3?sig=1",
           "meeting_link": "https://zoom.us/j/883",
           "meeting_attendees": [{"displayName": "Dana Reyes", "email": "dana@example.com", "name": None}],
           "summary": {"overview": "Pricing was discussed.", "short_summary": "", "action_items": "Ana sends a quote",
                       "shorthand_bullet": ["Ten percent"]},
           "sentences": sentences if sentences is not None else [
               {"speaker_name": "Dana Reyes", "text": "Can you send pricing?", "start_time": 5.0, "end_time": 8.5},
               {"speaker_name": "Dana Reyes", "text": "By Friday.", "start_time": 9.0, "end_time": 10.0},
               {"speaker_name": "Ana", "text": "Ten percent, then.", "start_time": 70.0, "end_time": 72.0}]}
    row.update(changes)
    return row


def ff_env():
    return {"FIREFLIES_API_KEY": KEY}


def test_fireflies_maps_a_transcript_and_files_it_for_the_key_holder(tmp_path):
    started = int((NOW - timedelta(hours=2)).timestamp() * 1000)
    detail = ff_detail(date=started, duration=2)
    transport = Recorder(ff_route([[{"id": "ff1", "title": "Pricing call", "date": started, "duration": 2}]], {"ff1": detail}))
    importer, hub, _ = make(fireflies.Fireflies, tmp_path, transport, ff_env())
    assert importer.tick() == 1
    body = hub.posts[0]
    assert (body["source"], body["external_id"], body["owner_email"]) == ("fireflies", "ff1", OWNER)
    assert body["title"] == "Pricing call" and body["duration_seconds"] == 120
    assert body["transcript"] == [
        {"speaker": "Dana Reyes", "start_ms": 5000, "end_ms": 10000, "text": "Can you send pricing? By Friday."},
        {"speaker": "Ana", "start_ms": 70000, "end_ms": 72000, "text": "Ten percent, then."}]
    assert {"name": "Dana Reyes", "email": "dana@example.com"} in body["participants"] and OWNER in body["participants"]
    assert body["media_url"] == "https://app.fireflies.ai/view/ff1"
    assert body["context"]["meeting_url"] == "https://zoom.us/j/883" and body["context"]["audio_url"].startswith("https://")
    assert body["notes"].startswith("Pricing was discussed.") and "## Action items" in body["notes"] and "- Ten percent" in body["notes"]
    assert all(c.headers["Authorization"] == "Bearer " + KEY for c in transport.calls)
    assert {c.host for c in transport.calls} == {"api.fireflies.ai"}


def test_fireflies_paginates_and_never_imports_the_same_transcript_twice(tmp_path, monkeypatch):
    monkeypatch.setattr(fireflies, "PAGE", 2)
    when = int((NOW - timedelta(hours=1)).timestamp() * 1000)
    rows = [{"id": "ff" + str(i), "title": "t", "date": when + i, "duration": 1} for i in range(3)]
    details = {r["id"]: ff_detail(r["id"], date=r["date"], duration=1) for r in rows}
    transport = Recorder(ff_route([rows[:2], rows[2:]], details))
    importer, hub, _ = make(fireflies.Fireflies, tmp_path, transport, ff_env())
    assert importer.tick() == 3
    assert len(hub.meetings) == 3
    lists = [c for c in transport.calls if "transcripts(" in c.body["query"]]
    assert [c.body["variables"]["skip"] for c in lists[:2]] == [0, 2]
    before = len(hub.posts)
    assert importer.tick() == 0                              # unchanged: remembered, not even refetched
    assert len(hub.posts) == before
    # And the hub key: the same external id again is the same meeting, not a second one.
    hub.post("meetings/import", {**hub.posts[0]})
    assert len(hub.meetings) == 3


def test_fireflies_window_is_bounded_and_backfill_is_explicit(tmp_path):
    transport = Recorder(ff_route([[]], {}))
    importer, hub, state = make(fireflies.Fireflies, tmp_path, transport, ff_env())
    importer.tick()
    lists = [c.body["variables"] for c in transport.calls if "transcripts(" in c.body["query"]]
    assert lists[0]["from"] == "2026-08-29T20:00:00Z" and lists[-1]["to"] == "2026-09-28T20:00:00Z"
    assert len(lists) == 30                                   # one bounded day per call
    assert state.import_cursor(importer.scope_state(importer.scopes()[0])).startswith("2026-09-28T20:00")
    transport.calls.clear()
    importer.tick()                                           # next pass: only the rolling overlap
    assert transport.calls and datetime.fromisoformat(
        [c.body["variables"]["from"] for c in transport.calls if "transcripts(" in c.body["query"]][0].replace("Z", "+00:00")) \
        == NOW - timedelta(hours=base.RECENT_HOURS)
    wide, _, _ = make(fireflies.Fireflies, tmp_path / "b", Recorder(ff_route([[]], {})), ff_env(), backfill_days=400)
    wide.transport.calls.clear()
    wide.tick()
    first = [c.body["variables"]["from"] for c in wide.transport.calls if "transcripts(" in c.body["query"]][0]
    assert first == "2025-09-28T20:00:00Z"                    # capped at a year


def test_fireflies_transcript_not_ready_holds_the_cursor(tmp_path):
    when = int((NOW - timedelta(hours=1)).timestamp() * 1000)
    row = {"id": "ff1", "title": "t", "date": when, "duration": 1}
    transport = Recorder(ff_route([[row]], {"ff1": ff_detail(sentences=[], date=when)}))
    importer, hub, state = make(fireflies.Fireflies, tmp_path, transport, ff_env())
    assert importer.tick() == 0 and hub.posts == []
    cursor = state.import_cursor(importer.scope_state(importer.scopes()[0]))
    assert datetime.fromisoformat(cursor) <= datetime.fromtimestamp(when / 1000, timezone.utc)


def test_fireflies_errors_are_sanitized(tmp_path):
    for code, wanted in (("auth_failed", "auth_failed"), ("too_many_requests", "rate_limited"),
                         ("something_new", "provider_error")):
        importer, _, _ = make(fireflies.Fireflies, tmp_path, Recorder(ff_route([], {}, errors=[
            {"message": "bad key " + KEY, "extensions": {"code": code}}])), ff_env())
        with pytest.raises(ProviderError) as caught:
            importer.tick()
        assert caught.value.code == wanted and KEY not in str(caught.value)


def test_missing_credentials_say_which_file_and_never_call_out(tmp_path):
    for cls, env in ((fireflies.Fireflies, {}), (granola.Granola, {}), (zoom.Zoom, {"ZOOM_ACCOUNT_ID": "a"}),
                     (google_meet.GoogleMeet, {})):
        calls = Recorder(lambda call: {})
        importer, _, _ = make(cls, tmp_path, calls, env)
        with pytest.raises(ProviderError) as caught:
            importer.tick()
        assert caught.value.code == "missing_credentials" and "secrets/" in str(caught.value) and calls.calls == []


def test_credentials_are_read_from_the_secret_file_on_this_computer(tmp_path):
    projects = tmp_path / "projects" / "secrets"
    projects.mkdir(parents=True)
    (projects / "granola.env").write_text("# key\nGRANOLA_API_KEY='grn_file'\n")
    state = State(tmp_path / "state")
    config = {"projects_dir": str(tmp_path / "projects"), "url": "https://hub.test", "token": "t"}
    assert granola.Granola(config, state, Hub()).ready()["GRANOLA_API_KEY"] == "grn_file"
    assert doctor(config)["granola"].startswith("present") and doctor(config)["zoom"].startswith("not set up")


def test_a_provider_failure_never_carries_the_url_or_the_body():
    class Opener:
        def open(self, request, timeout=None):
            raise urllib.error.HTTPError(request.full_url, 401, "no", {}, None)
    with pytest.raises(ProviderError) as caught:
        base.request_json("GET", "https://api.example/x?token=" + KEY, headers={"Authorization": "Bearer " + KEY},
                          tool="Fireflies", opener=Opener())
    assert caught.value.code == "auth_failed" and KEY not in str(caught.value) and "api.example" not in str(caught.value)
    class Down:
        def open(self, request, timeout=None):
            raise urllib.error.URLError("dns for " + KEY)
    with pytest.raises(ProviderError) as caught:
        base.request_json("GET", "https://api.example/", tool="Zoom", opener=Down())
    assert caught.value.code == "unreachable" and KEY not in str(caught.value)


# ---------------------------------------------------------------- Granola

def gr_note(ident="not_1d3tmYTlCICgjy", **changes):
    row = {"id": ident, "object": "note", "title": "Quarterly review", "owner": {"name": "Ana Cruz", "email": OWNER},
           "created_at": (NOW - timedelta(hours=3)).isoformat().replace("+00:00", "Z"),
           "updated_at": (NOW - timedelta(hours=2)).isoformat().replace("+00:00", "Z")}
    row.update(changes)
    return row


def gr_detail(row, transcript, **changes):
    detail = {**row, "web_url": "https://notes.granola.ai/d/abc", "calendar_event": {
        "event_title": "Quarterly review", "invitees": [{"email": "dana@example.com"}], "organiser": OWNER,
        "calendar_event_id": "evt1", "scheduled_start_time": "2026-09-28T17:00:00Z", "scheduled_end_time": "2026-09-28T18:00:00Z"},
        "attendees": [{"name": "Ana Cruz", "email": OWNER}, {"name": "Dana Reyes", "email": "dana@example.com"}],
        "folder_membership": [], "summary_text": "Plain", "summary_markdown": "## Decisions\nHold price.",
        "private_notes_text": "SECRET SCRATCH", "private_notes_markdown": "SECRET SCRATCH", "transcript": transcript}
    detail.update(changes)
    return detail


T0 = "2026-09-28T17:00:05Z"
TRANSCRIPT = [
    {"speaker": {"source": "speaker", "attribution": "them", "name": "Dana Reyes"}, "text": "Can you send pricing?",
     "start_time": T0, "end_time": "2026-09-28T17:00:08Z"},
    {"speaker": {"source": "microphone", "attribution": "me"}, "text": "Ten percent.",
     "start_time": "2026-09-28T17:01:15Z", "end_time": "2026-09-28T17:01:17Z"},
    {"speaker": {"source": "speaker", "attribution": "them"}, "text": "Great.", "start_time": "2026-09-28T17:02:00Z",
     "end_time": "2026-09-28T17:02:01Z"}]


def gr_route(pages, details, transcripts=None, too_large=()):
    def route(call):
        parts = call.path.split("/")
        if call.path == "/v1/notes":
            return pages[int(call.query.get("cursor") or 0)]
        note = parts[3]
        if len(parts) == 5:
            data = transcripts[note]
            start = int(call.query.get("cursor") or 0)
            size = int(call.query["page_size"])
            chunk = data[start:start + size]
            more = start + size < len(data)
            return {"transcript": chunk, "hasMore": more, "cursor": str(start + size) if more else None}
        if note in too_large and call.query.get("include"):
            raise ProviderError("provider_error", "Granola returned HTTP 413", 413)
        return details[note]
    return route


def test_granola_uses_the_official_api_and_keeps_private_notes_out(tmp_path):
    row = gr_note()
    detail = gr_detail(row, TRANSCRIPT)
    transport = Recorder(gr_route([{"notes": [row], "hasMore": False, "cursor": None}], {row["id"]: detail}))
    importer, hub, _ = make(granola.Granola, tmp_path, transport, {"GRANOLA_API_KEY": "grn_x"})
    assert importer.tick() == 1
    body = hub.posts[0]
    assert (body["source"], body["external_id"], body["owner_email"]) == ("granola", row["id"], OWNER)
    assert body["private"] is True                                 # personal notes stay personal by default
    assert body["transcript"] == [
        {"speaker": "Dana Reyes", "start_ms": 0, "end_ms": 3000, "text": "Can you send pricing?"},
        {"speaker": "Ana Cruz", "start_ms": 70000, "end_ms": 72000, "text": "Ten percent."},
        {"speaker": "Others", "start_ms": 115000, "end_ms": 116000, "text": "Great."}]
    assert body["notes"] == "## Decisions\nHold price." and "SECRET SCRATCH" not in json.dumps(body)
    assert body["media_url"] == "https://notes.granola.ai/d/abc" and body["started_at"] == "2026-09-28T17:00:00+00:00"
    assert {"name": "Dana Reyes", "email": "dana@example.com"} in body["participants"]
    assert all(c.headers["Authorization"] == "Bearer grn_x" and c.host == "public-api.granola.ai" for c in transport.calls)
    listing = transport.calls[0]
    assert listing.query["created_after"] == "2026-08-29T20:00:00Z" and int(listing.query["page_size"]) <= 30


def test_granola_company_visibility_is_opt_in(tmp_path):
    row = gr_note()
    route = gr_route([{"notes": [row], "hasMore": False, "cursor": None}], {row["id"]: gr_detail(row, TRANSCRIPT)})
    importer, hub, _ = make(granola.Granola, tmp_path, Recorder(route), {"GRANOLA_API_KEY": "k", "GRANOLA_PRIVATE": "0"})
    importer.tick()
    assert "private" not in hub.posts[0]


def test_granola_paginates_notes_and_large_transcripts_and_dedupes(tmp_path, monkeypatch):
    monkeypatch.setattr(granola, "TRANSCRIPT_PAGE", 2)
    rows = [gr_note("not_" + str(i) * 14) for i in range(3)]
    pages = {0: {"notes": rows[:2], "hasMore": True, "cursor": "1"}, 1: {"notes": rows[2:], "hasMore": False, "cursor": None}}
    details = {r["id"]: gr_detail(r, None) for r in rows}
    long = {r["id"]: TRANSCRIPT for r in rows}
    transport = Recorder(gr_route(pages, details, long, too_large={r["id"] for r in rows}))
    importer, hub, _ = make(granola.Granola, tmp_path, transport, {"GRANOLA_API_KEY": "k"})
    assert importer.tick() == 3 and len(hub.meetings) == 3
    assert all(len(p["transcript"]) == 3 for p in hub.posts)
    pages_read = [c for c in transport.calls if c.path.endswith("/transcript")]
    assert len(pages_read) == 6                                # two pages per note
    before = len(hub.posts)
    assert importer.tick() == 0 and len(hub.posts) == before   # updated_at unchanged
    changed = {**pages[1], "notes": [gr_note(rows[2]["id"], updated_at="2026-09-28T19:59:00Z")]}
    pages[1] = changed
    importer.tick()
    assert len(hub.posts) == before + 1 and len(hub.meetings) == 3


def test_granola_skips_a_note_owned_by_someone_outside_the_roster(tmp_path):
    row = gr_note(owner={"name": "Guest", "email": "guest@elsewhere.example"})
    route = gr_route([{"notes": [row], "hasMore": False, "cursor": None}],
                     {row["id"]: gr_detail(row, TRANSCRIPT, owner=row["owner"])})
    importer, hub, _ = make(granola.Granola, tmp_path, Recorder(route), {"GRANOLA_API_KEY": "k"})
    assert importer.tick() == 0 and hub.meetings == {}


def test_granola_auth_error_is_sanitized_through_the_service(tmp_path):
    def route(call):
        raise ProviderError(*base.status_code(401, "Granola"), status=401)
    hub = Hub()
    service = ImporterService({"projects_dir": str(tmp_path), "url": "https://hub.test", "token": "t"}, tmp_path / "s",
                              client=hub, now=lambda: NOW, transport=Recorder(route), only="granola",
                              classes=lambda s: lambda *a, **k: granola.Granola(*a, env={"GRANOLA_API_KEY": KEY}, **k))
    assert service.sync("granola") is None
    source, status = hub.statuses[-1]
    assert source == "granola" and status["state"] == "error" and status["error_code"] == "auth_failed"
    assert KEY not in json.dumps(status) and "granola.ai" not in json.dumps(status)


# ---------------------------------------------------------------- Zoom

ZOOM_ENV = {"ZOOM_ACCOUNT_ID": "acct", "ZOOM_CLIENT_ID": "cid", "ZOOM_CLIENT_SECRET": "csecret"}
VTT = "WEBVTT\n\n1\n00:00:05.000 --> 00:00:08.000\nDana Reyes: Can you send pricing?\n\n2\n00:01:10.000 --> 00:01:12.000\nAna: Ten percent.\n"


def zm_meeting(uuid="abc+/def==", start="2026-09-28T17:00:00Z", **changes):
    row = {"uuid": uuid, "id": 88320100042, "topic": "Pricing call", "start_time": start, "duration": 45,
           "host_id": "u1", "share_url": "https://acme.zoom.us/rec/share/xyz",
           "recording_files": [{"id": "f1", "file_type": "MP4", "status": "completed", "download_url": "https://acme.zoom.us/rec/download/v"},
                               {"id": "f2", "file_type": "TRANSCRIPT", "file_extension": "VTT", "status": "completed",
                                "recording_type": "audio_transcript", "download_url": "https://acme.zoom.us/rec/download/t"}]}
    row.update(changes)
    return row


def zm_route(recordings, participants=None, users=None, vtt=VTT):
    users = users if users is not None else [{"id": "u1", "email": "Ana@Acme.example"}]

    def route(call):
        if call.host == "zoom.us":
            assert call.form == {"grant_type": "account_credentials", "account_id": "acct"}
            assert call.headers["Authorization"] == "Basic " + base64.b64encode(b"cid:csecret").decode()
            return {"access_token": "tok", "expires_in": 3600}
        assert call.headers["Authorization"] == "Bearer tok"
        if call.path == "/v2/users":
            return {"users": users, "next_page_token": ""}
        if call.path.endswith("/recordings"):
            token = call.query.get("next_page_token") or ""
            page = recordings(call, token)
            return page
        if "/participants" in call.path:
            if participants is None:
                raise ProviderError("forbidden", "denied", 403)
            return {"participants": participants, "next_page_token": ""}
        if "/rec/download/" in call.path:
            return vtt.encode()
        raise AssertionError(call.url)
    return route


def test_zoom_downloads_the_vtt_transcript_and_files_it_for_the_host(tmp_path):
    seen = {}
    def recordings(call, token):
        seen.update(call.query)
        return {"meetings": [zm_meeting()], "next_page_token": ""}
    parts = [{"name": "Dana Reyes", "user_email": "dana@example.com"}, {"name": "Ana", "user_email": ""}]
    transport = Recorder(zm_route(recordings, parts))
    importer, hub, _ = make(zoom.Zoom, tmp_path, transport, ZOOM_ENV)
    assert importer.tick() == 1
    body = hub.posts[0]
    assert (body["source"], body["owner_email"], body["format"]) == ("zoom", "ana@acme.example", "vtt")
    assert body["external_id"] == "abc-/def" and body["transcript"] == VTT and body["duration_seconds"] == 2700
    assert body["media_url"] == "https://acme.zoom.us/rec/share/xyz" and body["context"] == {"zoom_meeting_id": "88320100042"}
    assert {"name": "Dana Reyes", "email": "dana@example.com"} in body["participants"]
    assert "Ana" in body["participants"] and "ana@acme.example" in body["participants"]
    assert set(seen) >= {"from", "to", "page_size"} and int(seen["page_size"]) <= 300
    assert any("/past_meetings/abc%2B%2Fdef%3D%3D/participants" in c.url for c in transport.calls)
    downloads = [c for c in transport.calls if "/rec/download/" in c.path]
    assert len(downloads) == 1 and downloads[0].url.endswith("/rec/download/t")      # audio and video are never fetched


def test_zoom_double_encodes_a_uuid_that_starts_with_a_slash(tmp_path):
    def recordings(call, token):
        return {"meetings": [zm_meeting("/abc//d==")], "next_page_token": ""}
    transport = Recorder(zm_route(recordings, []))
    importer, hub, _ = make(zoom.Zoom, tmp_path, transport, ZOOM_ENV)
    importer.tick()
    assert any("/past_meetings/%252Fabc%252F%252Fd%253D%253D/participants" in c.url for c in transport.calls)


def test_zoom_paginates_windows_and_stays_within_a_month(tmp_path):
    windows = []
    def recordings(call, token):
        if not token:
            windows.append((call.query["from"], call.query["to"]))
            return {"meetings": [zm_meeting("u-" + call.query["from"], start=call.query["from"] + "T23:00:00Z")], "next_page_token": "p2"}
        return {"meetings": [zm_meeting("v-" + call.query["from"], start=call.query["from"] + "T23:30:00Z")], "next_page_token": ""}
    importer, hub, _ = make(zoom.Zoom, tmp_path, Recorder(zm_route(recordings, [])), ZOOM_ENV)
    assert importer.tick() > 0
    assert windows[0][0] == "2026-08-29" and windows[-1][1] == "2026-09-28"
    assert all((datetime.fromisoformat(b) - datetime.fromisoformat(a)).days <= 7 for a, b in windows)
    assert len({k[2] for k in hub.meetings}) == len(hub.meetings)          # every id once per owner


def test_zoom_recording_without_a_transcript_is_skipped_and_a_fresh_one_is_revisited(tmp_path):
    old = zm_meeting("old", start="2026-09-20T10:00:00Z", recording_files=[
        {"id": "f1", "file_type": "MP4", "status": "completed", "download_url": "https://acme.zoom.us/rec/download/v"}])
    fresh = zm_meeting("fresh", start="2026-09-28T19:00:00Z", recording_files=[
        {"id": "f1", "file_type": "MP4", "status": "completed", "download_url": "https://acme.zoom.us/rec/download/v"}])
    importer, hub, state = make(zoom.Zoom, tmp_path, Recorder(zm_route(lambda c, t: {"meetings": [old, fresh], "next_page_token": ""}, [])), ZOOM_ENV)
    assert importer.tick() == 0 and hub.posts == []
    cursor = datetime.fromisoformat(state.import_cursor(importer.scope_state(importer.scopes()[0])))
    assert cursor <= datetime(2026, 9, 28, 19, tzinfo=timezone.utc)


def test_zoom_refuses_a_download_outside_zoom_and_never_follows_redirects_elsewhere(tmp_path):
    bad = zm_meeting(recording_files=[{"id": "f2", "file_type": "TRANSCRIPT", "file_extension": "VTT", "status": "completed",
                                       "download_url": "https://evil.example/rec/download/t"}])
    importer, hub, _ = make(zoom.Zoom, tmp_path, Recorder(zm_route(lambda c, t: {"meetings": [bad], "next_page_token": ""}, [])), ZOOM_ENV)
    with pytest.raises(ProviderError) as caught:
        importer.tick()
    assert caught.value.code == "bad_response"
    assert zoom.zoom_host("https://us02web.zoom.us/x") and not zoom.zoom_host("https://zoom.us.evil.example/x")
    assert not zoom.zoom_host("http://zoom.us/x")


def test_zoom_users_can_be_limited_and_bad_credentials_are_sanitized(tmp_path):
    users = [{"id": "u1", "email": "ana@acme.example"}, {"id": "u2", "email": "ben@acme.example"}]
    asked = []
    def recordings(call, token):
        asked.append(call.path)
        return {"meetings": [], "next_page_token": ""}
    importer, _, _ = make(zoom.Zoom, tmp_path, Recorder(zm_route(recordings, [], users)), {**ZOOM_ENV, "ZOOM_USERS": "Ben@acme.example"})
    importer.tick()
    assert {p.split("/")[3] for p in asked} == {"u2"}

    def refuse(call):
        raise ProviderError(*base.status_code(401, "Zoom"), status=401)
    broken, _, _ = make(zoom.Zoom, tmp_path / "x", Recorder(refuse), ZOOM_ENV)
    with pytest.raises(ProviderError) as caught:
        broken.tick()
    assert caught.value.code == "auth_failed" and "csecret" not in str(caught.value)


# ---------------------------------------------------------------- Google Meet

def service_account(tmp_path):
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pem = key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()).decode()
    path = tmp_path / "projects" / "secrets" / "sa.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"type": "service_account", "client_email": "tico@proj.iam.gserviceaccount.com",
                                "private_key": pem, "token_uri": "https://evil.example/token"}))
    return key.public_key(), str(path)


def gm_env(path, users="Ana@acme.example"):
    return {"GOOGLE_MEET_USERS": users, "GOOGLE_SERVICE_ACCOUNT_FILE": path}


REC = "conferenceRecords/conf1"
TR = REC + "/transcripts/tr1"


def gm_route(public=None, records=None, transcripts=None, entries=None, seen=None):
    seen = seen if seen is not None else {}
    def route(call):
        if call.host == "oauth2.googleapis.com":
            assertion = call.form["assertion"]
            head, claims, sig = assertion.split(".")
            pad = lambda s: s + "=" * (-len(s) % 4)
            data = json.loads(base64.urlsafe_b64decode(pad(claims)))
            seen["claims"] = data
            if public:
                public.verify(base64.urlsafe_b64decode(pad(sig)), (head + "." + claims).encode(), padding.PKCS1v15(), hashes.SHA256())
            assert call.form["grant_type"] == "urn:ietf:params:oauth:grant-type:jwt-bearer"
            return {"access_token": "tok-" + data["sub"], "expires_in": 3600}
        assert call.headers["Authorization"].startswith("Bearer tok-")
        seen.setdefault("users", set()).add(call.headers["Authorization"])
        path = call.path[len("/v2/"):]
        if path == "conferenceRecords":
            seen["filter"] = call.query.get("filter")
            return records(call)
        if path == REC + "/transcripts":
            return transcripts
        if path == REC + "/participants":
            return {"participants": [{"name": REC + "/participants/p1", "signedinUser": {"user": "users/1", "displayName": "Ana Cruz"}},
                                     {"name": REC + "/participants/p2", "anonymousUser": {"displayName": "Dana Reyes"}}]}
        if path == TR + "/entries":
            return entries(call)
        if path == "spaces/sp1":
            return {"name": "spaces/sp1", "meetingCode": "abc-mnop-xyz", "meetingUri": "https://meet.google.com/abc-mnop-xyz"}
        raise AssertionError(path)
    return route


def gm_record(**changes):
    row = {"name": REC, "startTime": "2026-09-28T17:00:00Z", "endTime": "2026-09-28T18:00:00Z", "space": "spaces/sp1"}
    row.update(changes)
    return row


def entry(i, who, words, at):
    end = (datetime.fromisoformat(at.replace("Z", "+00:00")) + timedelta(seconds=3)).isoformat().replace("+00:00", "Z")
    return {"name": TR + "/entries/e" + str(i), "participant": REC + "/participants/" + who, "text": words,
            "languageCode": "en-US", "startTime": at, "endTime": end}


def test_google_meet_signs_a_delegated_assertion_and_maps_entries(tmp_path):
    public, path = service_account(tmp_path)
    seen = {}
    pages = {"": {"transcriptEntries": [entry(1, "p2", "Can you send pricing?", "2026-09-28T17:00:05Z"),
                                        entry(2, "p1", "Ten percent.", "2026-09-28T17:01:10Z")], "nextPageToken": "n2"},
             "n2": {"transcriptEntries": [entry(3, "p1", "Sending it.", "2026-09-28T17:01:20Z")]}}
    transcripts = {"transcripts": [{"name": TR, "state": "FILE_GENERATED", "startTime": "2026-09-28T17:00:00Z",
                                    "endTime": "2026-09-28T18:00:00Z",
                                    "docsDestination": {"document": "d1", "exportUri": "https://docs.google.com/document/d/d1/view"}}]}
    transport = Recorder(gm_route(public, lambda c: {"conferenceRecords": [gm_record()]}, transcripts,
                                  lambda c: pages[c.query.get("pageToken", "")], seen))
    importer, hub, _ = make(google_meet.GoogleMeet, tmp_path, transport, gm_env(path))
    assert importer.tick() == 1
    assert seen["claims"]["sub"] == "ana@acme.example" and seen["claims"]["iss"] == "tico@proj.iam.gserviceaccount.com"
    assert seen["claims"]["scope"] == "https://www.googleapis.com/auth/meetings.space.readonly"
    assert seen["claims"]["aud"] == "https://oauth2.googleapis.com/token"          # never the key file's own token_uri
    assert all(c.host in ("oauth2.googleapis.com", "meet.googleapis.com") for c in transport.calls)
    body = hub.posts[0]
    assert (body["source"], body["external_id"], body["owner_email"]) == ("google-meet", "conf1", "ana@acme.example")
    assert body["title"] == "Google Meet abc-mnop-xyz" and body["duration_seconds"] == 3600
    assert body["transcript"] == [
        {"speaker": "Dana Reyes", "start_ms": 5000, "end_ms": 8000, "text": "Can you send pricing?"},
        {"speaker": "Ana Cruz", "start_ms": 70000, "end_ms": 83000, "text": "Ten percent. Sending it."}]
    assert body["media_url"] == "https://docs.google.com/document/d/d1/view"
    assert body["context"]["meeting_url"] == "https://meet.google.com/abc-mnop-xyz"
    assert "ana@acme.example" in body["participants"] and "Dana Reyes" in body["participants"]


def test_google_meet_window_is_capped_at_the_thirty_day_record_lifetime_and_each_user_is_separate(tmp_path):
    public, path = service_account(tmp_path)
    seen = {}
    transport = Recorder(gm_route(public, lambda c: {}, {}, lambda c: {}, seen))
    importer, hub, _ = make(google_meet.GoogleMeet, tmp_path, transport, gm_env(path, "ana@acme.example, ben@acme.example"),
                            backfill_days=200)
    importer.tick()
    filters = [c.query["filter"] for c in transport.calls if c.path == "/v2/conferenceRecords"]
    assert 'start_time>="2026-08-29T20:00:00.000Z"' in filters[0]
    assert len(seen["users"]) == 2 and len(filters) == 2 * 5                         # two people, 7-day windows


def test_google_meet_running_meetings_and_pending_transcripts_hold_the_cursor(tmp_path):
    public, path = service_account(tmp_path)
    running = gm_record(endTime=None)
    running.pop("endTime")
    transport = Recorder(gm_route(public, lambda c: {"conferenceRecords": [running]}, {}, lambda c: {}))
    importer, hub, state = make(google_meet.GoogleMeet, tmp_path, transport, gm_env(path))
    assert importer.tick() == 0 and hub.posts == []
    assert datetime.fromisoformat(state.import_cursor(importer.scope_state(importer.scopes()[0]))) <= datetime(2026, 9, 28, 17, tzinfo=timezone.utc)
    pending = {"transcripts": [{"name": TR, "state": "ENDED"}]}
    other, hub2, _ = make(google_meet.GoogleMeet, tmp_path / "o", Recorder(gm_route(public, lambda c: {"conferenceRecords": [gm_record()]}, pending, lambda c: {})), gm_env(path))
    assert other.tick() == 0 and hub2.posts == []


def test_google_meet_delegation_errors_are_sanitized(tmp_path):
    public, path = service_account(tmp_path)
    def refuse(call):
        raise ProviderError(*base.status_code(400, "Google"), status=400)
    importer, _, _ = make(google_meet.GoogleMeet, tmp_path, Recorder(refuse), gm_env(path))
    with pytest.raises(ProviderError) as caught:
        importer.tick()
    assert caught.value.code == "auth_failed" and "domain-wide delegation" in str(caught.value)
    assert "PRIVATE KEY" not in str(caught.value)
    broken = tmp_path / "bad.json"
    broken.write_text(json.dumps({"client_email": "x@y", "private_key": "not a key"}))
    importer, _, _ = make(google_meet.GoogleMeet, tmp_path / "b", Recorder(lambda c: {}), gm_env(str(broken)))
    with pytest.raises(ProviderError) as caught:
        importer.tick()
    assert caught.value.code == "missing_credentials"


# ---------------------------------------------------------------- the service

def test_service_runs_only_what_the_hub_assigned_and_reports_status(tmp_path):
    hub = Hub()
    hub.enabled = ["fireflies"]
    row = int((NOW - timedelta(hours=1)).timestamp() * 1000)
    transport = Recorder(ff_route([[{"id": "ff1", "title": "t", "date": row, "duration": 1}]], {"ff1": ff_detail(date=row, duration=1)}))
    service = ImporterService({"projects_dir": str(tmp_path), "url": "https://hub.test", "token": "t"}, tmp_path / "s",
                              client=hub, now=lambda: NOW, transport=transport,
                              classes=lambda s: lambda *a, **k: fireflies.Fireflies(*a, env=ff_env(), **k))
    assert service.tick() == {"fireflies": 1}
    assert hub.statuses == [("fireflies", {"state": "ok", "imported": 1})]
    assert service.tick() == {}                                  # not due again yet
    hub.enabled = []
    service.due.clear()
    assert service.tick() == {}


def test_service_backfill_is_one_bounded_pass_over_the_named_importer(tmp_path):
    hub = Hub()
    transport = Recorder(ff_route([[]], {}))
    service = ImporterService({"projects_dir": str(tmp_path), "url": "https://hub.test", "token": "t"}, tmp_path / "s",
                              client=hub, now=lambda: NOW, transport=transport, backfill_days=3, only="fireflies",
                              classes=lambda s: lambda *a, **k: fireflies.Fireflies(*a, env=ff_env(), **k))
    assert service.tick() == {"fireflies": 0}
    first = [c.body["variables"]["from"] for c in transport.calls if "transcripts(" in c.body["query"]][0]
    assert first == "2026-09-25T20:00:00Z"


def test_a_bug_reports_the_type_and_never_the_text(tmp_path):
    hub = Hub()
    def boom(call):
        raise ValueError("secret " + KEY)
    service = ImporterService({"projects_dir": str(tmp_path), "url": "https://hub.test", "token": "t"}, tmp_path / "s",
                              client=hub, now=lambda: NOW, transport=Recorder(boom), only="fireflies",
                              classes=lambda s: lambda *a, **k: fireflies.Fireflies(*a, env=ff_env(), **k))
    assert service.sync("fireflies") is None
    assert KEY not in json.dumps(hub.statuses) and hub.statuses[-1][1]["error_code"] == "sync_error"
