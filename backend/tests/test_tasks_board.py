"""The tasks board: queues in rank order, two lanes,
labels, blocked-by, links, comments that wake or wait, movers, and plain-English titles."""

import uuid

import pytest
from fastapi.testclient import TestClient

from backend import hubdb as H
from backend.app import create_app
from backend.auth import Identity
from backend.config import Settings
from backend.store import encode


@pytest.fixture
def api(tmp_path, monkeypatch):
    monkeypatch.setattr(H, "TITLE_LINT", "warn")
    app = create_app(Settings(db_path=tmp_path / "hub.db", test_identities={
        "ana-test": Identity("human:ana", "owner", "ana@acme.example"),
        "ben-test": Identity("human:ben", "human", "ben@acme.example"),
        "priya-test": Identity("human:priya", "human", "priya@acme.example"),
    }))
    with TestClient(app) as client:
        with app.state.store.transaction() as c:
            bots = {slug: {"name": slug, "runtime": "fake", "status": "active"}
                    for slug in ("ops", "cpo", "cmo")}
            H.sync_registry(c, bots, {"people": [
                {"id": "ana", "email": "ana@acme.example", "team": "leadership"},
                {"id": "ben", "email": "ben@acme.example", "team": "product"},
                {"id": "priya", "email": "priya@acme.example", "team": "sales"}]})
            c.execute("INSERT INTO registry_metadata VALUES('people',?)", (encode({"people": [
                {"id": "ana", "email": "ana@acme.example", "team": "leadership", "primary_for": ["*"]},
                {"id": "ben", "email": "ben@acme.example", "team": "product"},
                {"id": "priya", "email": "priya@acme.example", "team": "sales"}]}),))
            for slug, config in bots.items():
                c.execute("INSERT INTO bot_config(bot,config_json,team,operator) VALUES(?,?,?,?)",
                          (slug, encode(config), "product" if slug == "cpo" else "marketing" if slug == "cmo" else None, "ana"))
            c.execute("INSERT INTO registry_metadata VALUES('onboarding',?)",
                      (encode({"completed": "2026-01-01T00:00:00Z"}),))
        yield client


def headers(token="ana-test"):
    return {"Authorization": "Bearer " + token, "Idempotency-Key": str(uuid.uuid4())}


def post(api, path, body, token="ana-test", expected=200):
    r = api.post("/api/v2/" + path, json=body, headers=headers(token))
    assert r.status_code == expected, r.text
    data = r.json()
    return data["task"] if isinstance(data, dict) and set(data) == {"task"} else data


def get(api, path, token="ana-test", expected=200):
    r = api.get("/api/v2/" + path, headers=headers(token))
    assert r.status_code == expected, r.text
    return r.json()


def bot_token(api, slug="ops"):
    """A leased bot identity: enroll a runner, assign the bot, send it a message, claim the turn."""
    code = post(api, "enrollments", {"operator": "ana"})["code"]
    r = post(api, "runners/enroll", {"code": code, "label": "Mac", "platform": "test"})
    post(api, "bots/" + slug + "/assignment", {"runner_id": r["runner_id"], "expected_generation": 0})
    post(api, "runners/heartbeat", {"version": "test", "platform": "test", "readiness": {slug: True}}, token=r["token"])
    post(api, "chat/" + slug, {"text": "Please look at your queue."})
    return post(api, "jobs/claim", {"bot": slug}, token=r["token"])["attempt"]["token"]


# ----------------------------------------------------------------------------- rank


def test_completing_a_bot_requested_human_task_needs_a_result(api):
    token = bot_token(api, "ops")
    task = post(api, "tasks", {"owner": "ana", "title": "Decide the content hold",
        "body": "Keep or change the hold?"}, token=token)
    post(api, "tasks/" + task["id"], {"version": task["version"], "status": "done"}, expected=422)
    post(api, "tasks/" + task["id"], {"version": task["version"], "close": True}, expected=422)
    done = post(api, "tasks/" + task["id"], {"version": task["version"], "status": "done",
        "note": "Keep the hold; no publication is approved."})
    assert done["status"] == "done" and done["note"] == "Keep the hold; no publication is approved."


# ----------------------------------------------------------------------------- lanes


# ----------------------------------------------------------------------------- labels
# ----------------------------------------------------------------------------- blocked by
def test_finishing_the_blocker_clears_blocked_by_and_wakes_the_bot_owner(api):
    blocker = post(api, "tasks", {"owner": "cmo", "title": "Write the copy", "body": "x"})
    blocked = post(api, "tasks", {"owner": "ops", "title": "Publish the page", "body": "x"})
    blocked = post(api, "tasks/" + blocked["id"], {"version": blocked["version"], "blocked_by": blocker["id"]})
    assert blocked["blocked_by"] == blocker["id"] and blocked["blocker"]["title"] == "Write the copy"
    post(api, "tasks/" + blocked["id"], {"version": blocked["version"], "blocked_by": blocked["id"]}, expected=422)
    post(api, "tasks/" + blocker["id"], {"version": blocker["version"], "status": "done", "note": "Done."})
    after = get(api, "tasks/" + blocked["id"])
    assert after["task"]["blocked_by"] is None
    assert any(e["field"] == "blocked_by" and e["new"] is None for e in after["events"])
    assert any("Unblocked" in m["body"] for m in after["messages"])


# ----------------------------------------------------------------------------- links
# ----------------------------------------------------------------------------- comments


# ----------------------------------------------------------------------------- movers
def test_only_a_mover_changes_lane_labels_or_blocked_by_on_someone_elses_task(api):
    task = post(api, "tasks", {"owner": "cmo", "title": "Draft the newsletter", "body": "x"})
    post(api, "tasks/" + task["id"], {"version": task["version"], "labels": ["newsletter"]}, token="priya-test", expected=403)
    post(api, "tasks/" + task["id"], {"version": task["version"], "status": "done"}, token="priya-test", expected=403)
    ok = post(api, "tasks/" + task["id"], {"version": task["version"], "labels": ["newsletter"]}, token="ben-test")
    assert ok["labels"] == ["newsletter"]
    assert get(api, "tasks/" + task["id"], token="priya-test")["mover"] is False
    assert get(api, "tasks/" + task["id"], token="ben-test")["mover"] is True
    # the owner of a task still marks their own done, mover or not
    mine = post(api, "tasks", {"owner": "priya", "title": "Call the lead", "body": "Ask whether they want the demo."})
    done = post(api, "tasks/" + mine["id"], {"version": mine["version"], "status": "done"}, token="priya-test")
    assert done["status"] == "done"
    assert api.get("/api/me", headers=headers("priya-test")).json()["mover"] is False
    assert api.get("/api/me", headers=headers("ben-test")).json()["mover"] is True


# ----------------------------------------------------------------------------- titles
# ----------------------------------------------------------------------------- preferences


def test_task_labels_and_links_with_an_attachment(api):
    import json
    response = api.post("/api/v2/uploads/tasks", headers=headers(), data={
        "owner": "ana", "title": "Review the release", "body": "Check the attached notes.",
        "labels": json.dumps(["release"]), "links": json.dumps(["https://example.com/release"]),
        "acceptance_criteria": json.dumps(["Read the notes"])},
        files={"files": ("notes.md", b"Release notes", "text/markdown")})
    assert response.status_code == 200, response.text
    task = response.json()["task"]
    assert task["labels"] == ["release"]
    assert task["links"][0]["url"] == "https://example.com/release"
    assert task["attachments"][0]["name"] == "notes.md"


# ----------------------------------------------------------------------------- tags
@pytest.mark.parametrize("cloud", [False, True])
def test_tag_migration_backfills_once_and_preserves_legacy_column(api, cloud):
    task = post(api, "tasks", {"owner": "cmo", "title": "Review the migration", "body": "x"})
    store = api.app.state.store
    with store.transaction() as c:
        c.execute("UPDATE tasks SET labels_json=? WHERE id=?", ('["release","bug","bug"]', task["id"]))
        c.execute("DROP TABLE task_tags")
        c.execute("DROP TABLE tags")
        c.execute("PRAGMA user_version=13")
        c.execute("DELETE FROM cloud_migrations WHERE version=47")
    if cloud:
        store.initialize(seed_market=False)
    else:
        c = H.connect(store.settings.db_path)
        c.close()
    with store.read() as c:
        assert c.execute("PRAGMA user_version").fetchone()[0] == 14
        assert {tag["key"] for tag in H.tags(c)} == {"release", "bug"}
        assert set(H.task_labels(H.task(c, task["id"]))) == {"release", "bug"}
        assert c.execute("SELECT COUNT(*) FROM task_tags").fetchone()[0] == 2
        if cloud:
            assert c.execute("SELECT 1 FROM cloud_migrations WHERE version=47").fetchone()
    changed = post(api, "tasks/" + task["id"], {"version": task["version"], "labels": ["bug"]})
    assert changed["labels"] == ["bug"]
    store.initialize(seed_market=False)
    with store.read() as c:
        assert H.task_labels(H.task(c, task["id"])) == ["bug"]
        assert c.execute("SELECT labels_json FROM tasks WHERE id=?", (task["id"],)).fetchone()[0] == '["release","bug","bug"]'


def test_legacy_label_keys_write_tags_and_filter_by_join(api):
    task = post(api, "tasks", {"owner": "cmo", "title": "Fix the settings", "body": "x", "labels": ["Bug", "settings"]})
    assert task["labels"] == ["bug", "settings"]
    assert [(tag["key"], tag["label"], tag["metadata"]) for tag in task["tags"]] == [
        ("bug", "bug", {}), ("settings", "settings", {})]
    with api.app.state.store.transaction() as c:
        assert c.execute("SELECT labels_json FROM tasks WHERE id=?", (task["id"],)).fetchone()[0] == "[]"
        c.execute("UPDATE tasks SET labels_json='[\"obsolete\"]' WHERE id=?", (task["id"],))
    assert get(api, "tasks?label=bug")["tasks"][0]["id"] == task["id"]
    assert get(api, "tasks?label=obsolete")["tasks"] == []
    assert get(api, "tasks/labels")["labels"] == ["bug", "settings"]
    updated = post(api, "tasks/" + task["id"], {"version": task["version"], "labels": ["settings", "new-key"]})
    assert updated["labels"] == ["settings", "new-key"]
    data = get(api, "tasks/" + task["id"])
    assert data["task"]["labels"] == updated["labels"]
    assert any(event["field"] == "labels" and event["new"] == '["settings", "new-key"]' for event in data["events"])
    with api.app.state.store.read() as c:
        assert {row[0] for row in c.execute("SELECT action FROM events WHERE action LIKE 'tag.%'")} >= {
            "tag.create", "tag.attach", "tag.detach"}


def test_template_instances_copy_defaults_and_cannot_attach_templates(api):
    template = post(api, "tags", {"key": "release-checklist", "label": "release", "is_template": True,
        "metadata": {"date": "2026-10-02", "channel": "stable"}, "markdown": "- [ ] Smoke checks"})["tag"]
    instance = post(api, "tags/" + template["id"] + "/instances", {"key": "release-2026-10-02", "metadata": {"date": "2026-10-03"}})["tag"]
    assert instance["template_id"] == template["id"] and not instance["is_template"]
    assert instance["label"] == "release" and instance["markdown"] == template["markdown"]
    assert instance["metadata"] == {"date": "2026-10-03", "channel": "stable"}
    post(api, "tags/" + template["id"], {"version": 1, "markdown": "Changed", "metadata": {} })
    assert get(api, "tags/" + instance["key"])["tag"]["markdown"] == "- [ ] Smoke checks"
    assert get(api, "tags?is_template=true")["tags"][0]["id"] == template["id"]
    task = post(api, "tasks", {"owner": "cmo", "title": "Ship the release", "body": "x", "labels": [instance["key"]]})
    assert task["tags"][0]["metadata"] == instance["metadata"]
    assert get(api, "tags/" + instance["key"])["tasks"][0]["id"] == task["id"]
    post(api, "tasks/" + task["id"], {"version": task["version"], "labels": ["would-be-new", template["key"]]}, expected=422)
    assert get(api, "tags/" + instance["key"])["tasks"][0]["id"] == task["id"]
    assert not any(tag["key"] == "would-be-new" for tag in get(api, "tags")["tags"])
    post(api, "tasks", {"owner": "cmo", "title": "Invalid template task", "body": "x", "labels": [template["key"]]}, expected=422)


def test_tag_owner_movers_and_stale_versions(api):
    tag = post(api, "tags", {"key": "release-day", "owner": "priya", "markdown": "- [ ] Smoke checks"})["tag"]
    assert get(api, "tags/" + tag["id"], token="priya-test")["editable"] is True
    changed = post(api, "tags/" + tag["id"], {"version": 1, "markdown": "- [x] Smoke checks"}, token="priya-test")["tag"]
    assert changed["version"] == 2
    post(api, "tags/" + tag["id"], {"version": 1, "metadata": {"date": "2026-10-02"}}, token="priya-test", expected=409)
    assert get(api, "tags/" + tag["id"])["tag"]["metadata"] == {}
    post(api, "tags/" + tag["id"], {"version": 2, "owner": "ana"}, token="ben-test")
    post(api, "tags/" + tag["id"], {"version": 3, "markdown": "Clobber"}, token="priya-test", expected=403)
    post(api, "tags", {"key": "not-mine", "owner": "ana"}, token="priya-test", expected=403)
    mine = post(api, "tags", {"key": "my-checklist"}, token="priya-test")["tag"]
    assert mine["owner"] == "human:priya"
    task = post(api, "tasks", {"owner": "priya", "title": "Review the checklist", "body": "Read it."})
    post(api, "tasks/" + task["id"], {"version": task["version"], "labels": [mine["key"]]}, token="priya-test", expected=403)


def test_bot_tag_owner_edits_and_tag_tasks_respect_visibility(api):
    token = bot_token(api, "ops")
    tag = post(api, "tags", {"key": "release-bot", "markdown": "- [ ] Smoke checks"}, token=token)["tag"]
    post(api, "tags/" + tag["id"], {"version": 1, "markdown": "- [x] Smoke checks"}, token=token)
    mine = post(api, "tasks", {"owner": "ops", "title": "Run smoke checks", "body": "x", "labels": [tag["key"]]})
    other = post(api, "tasks", {"owner": "cmo", "title": "Write release notes", "body": "x", "labels": [tag["key"]]})
    assert [task["id"] for task in get(api, "tags/" + tag["id"], token=token)["tasks"]] == [mine["id"]]
    assert {task["id"] for task in get(api, "tags/" + tag["id"])["tasks"]} == {mine["id"], other["id"]}
    sql = post(api, "sql", {"sql": "SELECT task_id FROM task_tags JOIN tags ON tags.id=task_tags.tag_id WHERE tags.key='release-bot'"}, token=token)
    assert sql["rows"] == [[mine["id"]]]
    assert get(api, "tasks/labels", token=token)["tags"][0]["key"] == tag["key"]


def test_task_label_strings_resolve_only_by_key_even_if_one_is_a_tag_id(api):
    tag = post(api, "tags", {"key": "release-checklist"})["tag"]
    task = post(api, "tasks", {"owner": "cmo", "title": "Review a key collision", "body": "x", "labels": [tag["id"]]})
    assert task["labels"] == [tag["id"]]
    assert task["tags"][0]["key"] == tag["id"]
    assert task["tags"][0]["id"] != tag["id"]
    assert get(api, "tasks/labels")["tags"][0]["key"] == tag["id"]


def test_needs_you_includes_tag_keys_and_metadata(api):
    tag = post(api, "tags", {"key": "release-2026-10-02", "label": "release", "metadata": {"date": "2026-10-02"}})["tag"]
    task = post(api, "tasks", {"owner": "ana", "title": "Review the release", "body": "Read the notes.", "labels": [tag["key"]]})
    items = get(api, "needs-you")["items"]
    mine = next(item for item in items if item["id"] == task["id"])
    assert mine["labels"] == [tag["key"]]
    assert mine["tags"][0]["metadata"] == {"date": "2026-10-02"}
