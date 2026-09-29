import json

from backend.auth import Auth
from backend.backup import restore_snapshot, snapshot
from backend.config import Settings
from backend.store import H, Problem, Store, encode
from backend.tests.test_api import api, post, setup_attempt

import pytest


def test_store_replaces_legacy_queue_trigger_and_drains_queued_self_messages(tmp_path):
    settings = Settings(db_path=tmp_path / "old-queue.sqlite")
    store = Store(settings)
    store.initialize()
    with store.transaction() as c:
        H.sync_registry(c, {"coo": {"name": "coo", "status": "active"}},
                        {"people": []})
        c.execute("DELETE FROM cloud_migrations WHERE version=8")
        c.execute("DROP TRIGGER queue_bot_message")
        c.execute("CREATE TRIGGER queue_bot_message AFTER INSERT ON messages "
                  "WHEN NEW.to_actor LIKE 'bot:%' BEGIN "
                  "INSERT INTO jobs(id,message_id,bot,created) "
                  "VALUES(NEW.id,NEW.id,substr(NEW.to_actor,5),NEW.created); END")
        conversation = H.open_conversation(c, "bot:coo", ["bot:coo"], kind="chat")
        self_message = H._write_message(c, "bot:coo", "bot:coo", "legacy loop",
                                        conversation, "say", {}, None, None)
        assert c.execute("SELECT state FROM jobs WHERE message_id=?",
                         (self_message["id"],)).fetchone()[0] == "queued"
    store.initialize()
    with store.transaction() as c:
        assert c.execute("SELECT state FROM jobs WHERE message_id=?",
                         (self_message["id"],)).fetchone()[0] == "completed"
        H._write_message(c, "bot:coo", "bot:coo", "ignored by trigger",
                         conversation, "say", {}, None, None)
        assert c.execute("SELECT count(*) FROM jobs").fetchone()[0] == 1
        assert c.execute("SELECT 1 FROM cloud_migrations WHERE version=8").fetchone()


def test_restore_fences_credentials_and_preserves_uncertain_effects(api, tmp_path):
    r, _, a = setup_attempt(api)
    post(api, f"attempts/{a['id']}/started", {"thread_id": "pre-disaster"}, r["token"])
    backup = tmp_path / "backup.sqlite"
    restored = tmp_path / "restored.sqlite"
    snapshot(api.app.state.store.settings.db_path, backup)
    report = restore_snapshot(backup, restored)
    assert report["reenrollment_required"] and report["fenced_attempts"] == 1
    assert report["restored"]["integrity"] == ["ok"]
    store = Store(Settings(db_path=restored))
    auth = Auth(store)
    with pytest.raises(Problem):
        auth.authenticate({"authorization": "Bearer " + r["token"]})
    with pytest.raises(Problem):
        auth.authenticate({"authorization": "Bearer " + a["token"]})
    with store.read() as c:
        assert c.execute("SELECT state FROM jobs WHERE id=?", (a["job_id"],)).fetchone()[0] == "uncertain"
        assert c.execute("SELECT generation FROM assignments WHERE bot='ops'").fetchone()[0] == 2


def test_new_tasks_require_timezone_to_keep_scheduler_reliable(api):
    post(api, "tasks", {"title": "Review due date", "owner": "coo", "body": "Review it", "due": "2026-09-10"}, expected=422)
    task = post(api, "tasks", {"title": "Review due date", "owner": "coo", "body": "Review it", "due": "2026-09-11T10:00:00-07:00"})
    assert task["due"]


def test_restart_gives_lapsed_leases_one_more_period_instead_of_expiring_them(api):
    from fastapi.testclient import TestClient
    from backend.app import create_app
    from backend.tests.test_api import claim, expire
    r, _, a = setup_attempt(api)
    post(api, f"attempts/{a['id']}/started", {"thread_id": "through-deploy"}, r["token"])
    expire(api, a["id"])
    # A deploy restarts the API against the same database while the runner keeps working.
    with TestClient(create_app(api.app.state.store.settings)) as restarted:
        assert claim(restarted, r) is None
        with restarted.app.state.store.read() as c:
            attempt = c.execute("SELECT state,lease_until FROM attempts WHERE id=?", (a["id"],)).fetchone()
            assert attempt["state"] == "running" and attempt["lease_until"] > H.now()
            assert c.execute("SELECT state FROM jobs WHERE id=?", (a["job_id"],)).fetchone()[0] == "running"
            assert c.execute("SELECT count(*) FROM events WHERE action='attempt.lease-grace' AND target=?",
                             (a["id"],)).fetchone()[0] == 1
        result = post(restarted, f"attempts/{a['id']}/complete", {"outcome": "completed", "last_seq": 0,
                      "text": "Finished while the API was away."}, r["token"])
        assert result["outcome"] == "completed"
        # A lease that lapses again with nobody renewing it expires exactly as before.
        r2, _, b = setup_attempt(restarted, bot="cpo", operator="ben")
        post(restarted, f"attempts/{b['id']}/started", {"thread_id": "gone"}, r2["token"])
        expire(restarted, b["id"])
        assert claim(restarted, r2) is None
        with restarted.app.state.store.read() as c:
            assert c.execute("SELECT state FROM attempts WHERE id=?", (b["id"],)).fetchone()[0] == "expired"


def test_every_cloud_migration_number_is_used_once_and_in_order():
    """Two branches picked the same migration number twice on 2026-09-24 (#493): the second block
    then never runs on a database that already recorded the number. With no CI, this is the check
    that fails before such a merge ships."""
    import re
    from pathlib import Path
    source = (Path(__file__).resolve().parents[1] / "store.py").read_text()
    blocks = re.split(r'(?=if not c\.execute\("SELECT 1 FROM cloud_migrations WHERE version=)', source)[1:]
    pairs = [(int(re.match(r'if not c\.execute\("SELECT 1 FROM cloud_migrations WHERE version=(\d+)', b).group(1)),
              [int(v) for v in re.findall(r"INSERT INTO cloud_migrations VALUES\((\d+)", b)]) for b in blocks]
    checked = [v for v, _ in pairs]
    assert len(checked) == len(set(checked)), f"a migration number is used twice: {sorted(checked)}"
    assert all(inserted == [v] for v, inserted in pairs), "each block records exactly its own number"
    # Numbers may skip: some company-specific migrations were removed.
    assert checked == sorted(checked), "migration blocks run in number order"
