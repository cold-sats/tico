"""The 2026-09-25 performance pass: the page is revalidated, not re-sent; the chat stream's cheap
mark moves with what its snapshot shows; the goal tree is two queries, not two per goal."""

from backend.store import H
from backend.tests.test_api import api, get, headers, post  # noqa: F401
from backend.views import snapshot_mark


def test_the_page_and_its_files_are_revalidated_and_the_api_is_never_stored(api):
    auth = {"Authorization": "Bearer ana-test"}
    page = api.get("/", headers=auth)
    assert page.status_code == 200 and page.headers["cache-control"] == "private, no-cache"
    assert page.headers["cdn-cache-control"] == "no-store"
    # Unchanged, it comes back as a 304 with no body; Cloudflare's weak form of the tag matches.
    again = api.get("/", headers={**auth, "If-None-Match": "W/" + page.headers["etag"]})
    assert again.status_code == 304 and again.content == b""
    icon = api.get("/assets/bot-symbols.svg", headers=auth)
    assert icon.status_code == 200 and icon.headers["cache-control"] == "private, max-age=3600"
    data = api.get("/api/v2/status", headers=auth)
    assert data.headers["cache-control"] == "no-store, no-cache, must-revalidate"


def test_the_chat_mark_moves_with_a_message_and_a_run(api):
    post(api, "chat/ops", {"text": "Where are we on the pricing page?"})
    store = api.app.state.store
    with store.read() as c:
        cid = c.execute("SELECT id FROM conversations WHERE kind='chat'").fetchone()[0]
        first = snapshot_mark(c, cid)
        assert snapshot_mark(c, cid) == first, "nothing changed, same mark"
    post(api, "chat/ops", {"text": "And the checklist?"})
    with store.read() as c:
        second = snapshot_mark(c, cid)
    assert second != first
    with store.transaction() as c:
        c.execute("UPDATE jobs SET state='cancelled' WHERE message_id=(SELECT id FROM messages "
                  "WHERE conversation_id=? ORDER BY rowid DESC LIMIT 1)", (cid,))
    with store.read() as c:
        assert snapshot_mark(c, cid) != second, "the run's state is in the mark"


def test_the_goal_tree_counts_open_tasks_and_measures_in_one_pass(api):
    top = post(api, "goals", {"title": "Grow revenue 30% this year", "owner": "ana"})["goal"]
    plain = post(api, "goals", {"title": "Keep churn under 2%", "owner": "ana"})["goal"]
    post(api, f"goals/{top['id']}/kpis", {"name": "booked demos per two weeks", "unit": "demos"})
    post(api, "tasks", {"title": "Draft the pricing page", "body": "Details.", "owner": "coo", "goal_id": top["id"]})
    tree = {g["id"]: g for g in get(api, "goals/tree")["goals"]}
    assert tree[top["id"]]["open_tasks"] == 1 and [k["name"] for k in tree[top["id"]]["kpis"]] == ["booked demos per two weeks"]
    assert tree[plain["id"]]["open_tasks"] == 0 and tree[plain["id"]]["kpis"] == []


def test_the_new_indexes_exist(api):
    with api.app.state.store.read() as c:
        names = {r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='index'")}
    assert {"tasks_goal", "attempts_bot_created", "attempts_job", "attempts_runner_state",
            "events_action_target"} <= names


def test_the_watch_stream_sends_a_snapshot_then_keeps_alive_while_nothing_moves(api, monkeypatch):
    import asyncio
    real_sleep = asyncio.sleep
    monkeypatch.setattr("backend.views.asyncio.sleep", lambda seconds: real_sleep(0))
    post(api, "chat/ops", {"text": "Where are we on the pricing page?"})
    with api.app.state.store.read() as c:
        cid = c.execute("SELECT id FROM conversations WHERE kind='chat'").fetchone()[0]
    lines = []
    with api.stream("GET", f"/api/v2/conversations/{cid}/watch", headers={"Authorization": "Bearer ana-test"}) as r:
        assert r.status_code == 200
        for line in r.iter_lines():
            lines.append(line)
            if line.startswith(": keepalive"):
                break
    assert lines[0] == "event: snapshot" and "Where are we on the pricing page?" in lines[1]


def test_a_person_without_a_workspace_photo_is_asked_about_once_a_day(tmp_path, monkeypatch):
    from types import SimpleNamespace
    from backend import people_photos
    calls = []
    monkeypatch.setattr(people_photos, "google_photo", lambda email, subject=None: calls.append(email))
    settings = SimpleNamespace(blob_dir=tmp_path / "blobs", db_path=tmp_path / "hub.db")
    assert people_photos.load(settings, "ben@acme.example") is None
    assert people_photos.load(settings, "ben@acme.example") is None
    assert calls == ["ben@acme.example"], "the miss is remembered"
    monkeypatch.setattr(people_photos, "MISS_TTL", -1)
    people_photos.load(settings, "ben@acme.example")
    assert len(calls) == 2, "and asked again once it is stale"


def test_a_workspace_photo_keeps_for_a_week_in_the_browser(api, monkeypatch):
    from backend import people_photos
    monkeypatch.setattr(people_photos, "load", lambda *a, **k: (b"\x89PNG fake", "image/png"))
    r = api.get("/api/people/ben/photo", headers={"Authorization": "Bearer ana-test"})
    assert r.status_code == 200 and r.headers["cache-control"] == "private, max-age=604800"
    assert r.headers["cdn-cache-control"] == "no-store"


def test_needs_you_can_answer_with_the_count_alone(api):
    post(api, "tasks", {"title": "Approve the budget", "body": "Details.", "owner": "ana"}, token="ben-test")
    full = api.get("/api/v2/needs-you", headers={"Authorization": "Bearer ana-test"}).json()
    brief = api.get("/api/v2/needs-you?count=1", headers={"Authorization": "Bearer ana-test"}).json()
    assert brief == {"actor": "human:ana", "count": len(full["items"])} and brief["count"] >= 1


def test_a_tick_with_nothing_due_writes_no_schedule_and_says_how_long_it_took(api):
    import json
    from datetime import datetime, timezone
    from backend.scheduler import Scheduler
    store = api.app.state.store
    with store.transaction() as c:
        c.execute("INSERT INTO schedules(id,bot,cron,title,playbook,last_fired,next_due) "
                  "VALUES('morning','ops','0 9 * * *','Review daily work','Review work',NULL,NULL)")
        c.execute("CREATE TABLE schedule_writes(n INTEGER)")
        c.execute("CREATE TRIGGER count_schedule_writes AFTER UPDATE ON schedules BEGIN INSERT INTO schedule_writes VALUES(1); END")
    scheduler = Scheduler(store, api.app.state.execution)
    scheduler.tick(datetime(2026, 9, 10, 17, 0, tzinfo=timezone.utc))      # sets next_due once
    with store.read() as c:
        first = c.execute("SELECT count(*) FROM schedule_writes").fetchone()[0]
    scheduler.tick(datetime(2026, 9, 10, 17, 0, 10, tzinfo=timezone.utc))
    with store.read() as c:
        assert c.execute("SELECT count(*) FROM schedule_writes").fetchone()[0] == first == 1
        detail = json.loads(c.execute("SELECT detail_json FROM service_health WHERE service='scheduler'").fetchone()[0])
    assert isinstance(detail["tick_ms"], int) and detail["failures"] == []


def test_a_slack_photo_is_fetched_once_and_served_by_the_hub(tmp_path):
    from types import SimpleNamespace
    from backend import people_photos
    settings = SimpleNamespace(blob_dir=tmp_path / "blobs", db_path=tmp_path / "hub.db")
    calls = []
    def fetch(url):
        calls.append(url)
        return b"\\x89PNG face", "image/png"
    url = "https://avatars.slack-edge.com/2024-01-01/1_abc_192.png"
    assert people_photos.remote_photo(settings, url, fetch=fetch) == (b"\\x89PNG face", "image/png")
    assert people_photos.remote_photo(settings, url, fetch=fetch)[0] == b"\\x89PNG face"
    assert calls == [url], "kept after the first fetch"
    # Never an arbitrary host, plain http, or something that is not an image.
    for other in ("https://evil.example.com/a.png", "http://avatars.slack-edge.com/a.png",
                  "https://avatars.slack-edge.com.evil.example/a.png"):
        assert people_photos.remote_photo(settings, other, fetch=fetch) is None
    assert calls == [url]
    assert people_photos.remote_photo(settings, "https://avatars.slack-edge.com/x.png",
                                      fetch=lambda u: (b"<html>", "text/html")) is None


def test_the_photo_route_serves_a_kept_slack_photo_for_a_week(api, monkeypatch):
    from backend import people_photos
    monkeypatch.setattr(people_photos, "load", lambda *a, **k: None)
    monkeypatch.setattr(people_photos, "remote_photo", lambda settings, url: (b"\\x89PNG face", "image/png"))
    with api.app.state.store.transaction() as c:
        import json
        row = c.execute("SELECT value_json FROM registry_metadata WHERE key='people'").fetchone()
        people = json.loads(row[0])
        people["people"][1]["photo"] = "https://avatars.slack-edge.com/ben.png"
        c.execute("UPDATE registry_metadata SET value_json=? WHERE key='people'", (json.dumps(people),))
    r = api.get("/api/people/ben/photo", headers={"Authorization": "Bearer ana-test"}, follow_redirects=False)
    assert r.status_code == 200 and r.content == b"\\x89PNG face"
    assert r.headers["cache-control"] == "private, max-age=604800"
