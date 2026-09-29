"""Stable v2 answers carry display names beside actor ids, and archived bots stay out of the bot list."""
from backend.store import H
from backend.tests.test_api import api, headers, post  # noqa: F401  (fixture)


def test_task_and_notice_carry_names(api):
    with api.app.state.store.transaction() as c:
        c.execute("UPDATE humans SET name='Ana Alvarez' WHERE id='ana'")
        c.execute("UPDATE bots SET display_name='Ops Bot' WHERE slug='ops'")
    made = api.post("/api/v2/tasks", json={"owner": "bot:ops", "title": "Rotate keys", "body": "Do it"},
                    headers=headers("ana-test"))
    assert made.status_code == 200, made.text
    task = made.json()["task"]
    assert task["owner"] == "bot:ops" and task["owner_name"] == "Ops Bot"
    assert task["requester_name"] == "Ana Alvarez"
    listed = api.get("/api/v2/tasks", headers=headers("ana-test")).json()
    assert listed["actors"]["bot:ops"] == "Ops Bot" and listed["actors"]["human:ana"] == "Ana Alvarez"


def test_notices_are_rendered_for_people_with_ids_kept(api):
    with api.app.state.store.transaction() as c:
        c.execute("UPDATE humans SET name='Ben Brooks' WHERE id='ben'")
        c.execute("UPDATE bots SET display_name='Ops Bot' WHERE slug='ops'")
    made = api.post("/api/v2/tasks", json={"owner": "human:ben", "title": "Review", "body": "x"},
                    headers=headers("ana-test"))
    assert made.status_code == 200, made.text
    seen = api.get("/api/v2/needs-you", headers=headers("ben-test")).json()
    assert seen["actors"].get("human:ben") == "Ben Brooks"
    tid = made.json()["task"]["id"]
    detail = api.get("/api/v2/tasks/" + tid, headers=headers("ben-test")).json()
    notices = [m for m in detail["messages"] if m["kind"] == "notice"]
    assert notices, detail
    for m in notices:
        assert "human:" not in m["body"] and "bot:" not in m["body"], m["body"]
        assert m["from_actor"]
    assert any(m["body"].startswith("New task from ") for m in notices)
    raw = [m for m in notices if "body_raw" in m]
    assert raw and "human:ana" in raw[0]["body_raw"]


def test_archived_bots_are_left_out_unless_asked(api):
    with api.app.state.store.transaction() as c:
        c.execute("UPDATE bots SET state='archived' WHERE slug='finance'")
    slugs = {b["slug"] for b in api.get("/api/v2/bots", headers=headers("ana-test")).json()}
    assert "finance" not in slugs and "ops" in slugs
    every = {b["slug"] for b in api.get("/api/v2/bots?include_archived=1", headers=headers("ana-test")).json()}
    assert "finance" in every
