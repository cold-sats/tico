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
def test_needs_you_is_asks_first_then_my_tasks_in_rank_order(api):
    later = post(api, "tasks", {"owner": "ana", "title": "Review the plan", "body": "Say yes or change it."})
    first = post(api, "tasks", {"owner": "ana", "title": "Approve the budget", "body": "Say yes or no.", "top": True})
    items = get(api, "needs-you")["items"]
    ids = [i.get("id") for i in items if i.get("kind") == "task"]
    assert ids.index(first["id"]) < ids.index(later["id"])


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
def test_the_product_lane_is_retired_so_every_new_or_moved_task_is_company_work(api):
    """Ana, 2026-09-25: a product-team bot's task, or one asking for the product lane, is company."""
    default = post(api, "tasks", {"owner": "cpo", "title": "Ship the pricing page", "body": "x"})
    asked = post(api, "tasks", {"owner": "cpo", "title": "Fix the checkout bug", "body": "x", "lane": "product"})
    assert default["lane"] == asked["lane"] == "company"
    moved = post(api, "tasks/" + asked["id"], {"version": asked["version"], "lane": "product"}, token="ben-test")
    assert moved["lane"] == "company"
    post(api, "tasks", {"owner": "cpo", "title": "Plan the launch", "body": "x", "lane": "nowhere"}, expected=422)


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
def test_a_movers_comment_wakes_the_bot_and_a_bystanders_comment_waits(api):
    task = post(api, "tasks", {"owner": "cmo", "title": "Draft the newsletter", "body": "x"})
    with api.app.state.store.read() as c:
        before = c.execute("SELECT COUNT(*) FROM jobs WHERE bot='cmo'").fetchone()[0]
    woke = post(api, "tasks/" + task["id"] + "/comments", {"text": "Use the September numbers."}, token="ben-test")
    assert woke["woke"] is True
    quiet = post(api, "tasks/" + task["id"] + "/comments", {"text": "Sales would like a mention of the promo."}, token="priya-test")
    assert quiet["woke"] is False
    with api.app.state.store.read() as c:
        after = c.execute("SELECT COUNT(*) FROM jobs WHERE bot='cmo'").fetchone()[0]
    assert after == before + 1
    comments = get(api, "tasks/" + task["id"])["comments"]
    assert [m["from_actor"] for m in comments] == ["human:ben", "human:priya"]
    assert comments[1]["refs"].get("quiet") is True


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
