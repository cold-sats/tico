"""The repository webhook moves a product-lane task with its pull request, and a release ships it."""

import hashlib
import hmac
import json
import uuid

import pytest
from fastapi.testclient import TestClient

from backend import github as G
from backend import hubdb as H
from backend.app import create_app
from backend.auth import Identity
from backend.config import Settings
from backend.store import encode

SECRET = "hook-secret"
PR = "https://github.com/ticoteam/tico/pull/412"


@pytest.fixture
def api(tmp_path):
    app = create_app(Settings(db_path=tmp_path / "hub.db", github_webhook_secret=SECRET,
                              release_commit="", release_repo="ticoteam/tico", test_identities={
        "ana-test": Identity("human:ana", "owner", "ana@acme.example")}))
    with TestClient(app) as client:
        with app.state.store.transaction() as c:
            bots = {slug: {"name": slug, "runtime": "fake", "status": "active"} for slug in ("cpo", "cmo")}
            H.sync_registry(c, bots, {"people": [{"id": "ana", "email": "ana@acme.example", "team": "leadership"}]})
            c.execute("INSERT INTO registry_metadata VALUES('people',?)", (encode({"people": [
                {"id": "ana", "email": "ana@acme.example", "team": "leadership", "primary_for": ["*"]}]}),))
            for slug, config in bots.items():
                c.execute("INSERT INTO bot_config(bot,config_json,team,operator) VALUES(?,?,?,?)",
                          (slug, encode(config), "product" if slug == "cpo" else "marketing", "ana"))
            c.execute("INSERT INTO registry_metadata VALUES('onboarding',?)", (encode({"completed": "2026-01-01T00:00:00Z"}),))
        yield client


def headers():
    return {"Authorization": "Bearer ana-test", "Idempotency-Key": str(uuid.uuid4())}


def post(api, path, body, expected=200):
    r = api.post("/api/v2/" + path, json=body, headers=headers())
    assert r.status_code == expected, r.text
    data = r.json()
    return data["task"] if isinstance(data, dict) and set(data) == {"task"} else data


def get(api, path):
    r = api.get("/api/v2/" + path, headers=headers())
    assert r.status_code == 200, r.text
    return r.json()


def hook(api, event, payload, secret=SECRET, expected=200):
    body = json.dumps(payload).encode()
    sig = "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    r = api.post(G.PATH, content=body, headers={"X-Hub-Signature-256": sig, "X-GitHub-Event": event,
                                               "Content-Type": "application/json"})
    assert r.status_code == expected, r.text
    return r.json() if r.content else {}


def pr_event(action, **over):
    pr = {"html_url": PR, "draft": False, "merged": False, "merge_commit_sha": None, "merged_at": None, **over}
    return {"action": action, "pull_request": pr, "repository": {"full_name": "ticoteam/tico"}}


def test_a_bad_signature_is_refused_and_an_unset_secret_hides_the_path(api, tmp_path):
    hook(api, "ping", {"zen": "x"}, secret="wrong", expected=403)
    assert hook(api, "ping", {"zen": "x"}) == {"ok": True}
    bare = create_app(Settings(db_path=tmp_path / "other.db"))
    with TestClient(bare) as client:
        r = client.post(G.PATH, content=b"{}", headers={"X-Hub-Signature-256": "sha256=00", "X-GitHub-Event": "ping"})
        assert r.status_code == 404


def test_the_pull_request_moves_the_task_through_review_ready_and_shipped(api):
    task = post(api, "tasks", {"owner": "cpo", "title": "Ship the pricing page", "body": "x", "links": [PR]})
    assert task["lane"] == "company" and task["status"] == "open"
    # The product lane is retired (new tasks are company work); a product row from before still moves.
    with api.app.state.store.transaction() as c:
        c.execute("UPDATE tasks SET lane='product' WHERE id=?", (task["id"],))

    opened = hook(api, "pull_request", pr_event("opened"))
    assert opened["moved"] == [[task["id"], "review"]]
    assert get(api, "tasks/" + task["id"])["task"]["status"] == "review"

    merged = hook(api, "pull_request", pr_event("closed", merged=True, merge_commit_sha="abc123", merged_at="2026-09-18T20:00:00Z"))
    assert merged["moved"] == [[task["id"], "ready"]]
    detail = get(api, "tasks/" + task["id"])
    assert detail["task"]["status"] == "ready"
    assert detail["task"]["links"][0]["state"] == "merged" and detail["task"]["links"][0]["pr_sha"] == "abc123"

    # main moves on: the merge commit, then a later commit that the next release is built from
    pushed = hook(api, "push", {"ref": "refs/heads/main", "repository": {"full_name": "ticoteam/tico", "default_branch": "main"},
                                "commits": [{"id": "abc123"}, {"id": "def456"}], "head_commit": {"id": "def456"}})
    assert pushed["commits"] == 2 and pushed["shipped"] == []
    api.app.state.store.settings.release_commit = "def456"
    with api.app.state.store.transaction() as c:
        assert G.ship_deployed(c, api.app.state.store.settings) == [task["id"]]
    after = get(api, "tasks/" + task["id"])
    assert after["task"]["status"] == "done" and "Shipped in release def456" in after["task"]["note"]
    assert after["task"]["links"][0]["state"] == "shipped"


def test_webhook_and_deploy_map_custom_steps_and_preserve_status_without_a_step(api):
    typ = post(api, 'task-types', {'name': 'Engineering', 'steps': [
        {'name': 'Draft', 'status': 'open'}, {'name': 'Code review', 'status': 'review'},
        {'name': 'Merged', 'status': 'ready'}]})['type']
    task = post(api, 'tasks', {'owner': 'cpo', 'title': 'Build the release screen', 'body': 'Please.',
        'links': [PR], 'type': typ['id']})
    with api.app.state.store.transaction() as c:
        c.execute("UPDATE tasks SET lane='product' WHERE id=?", (task['id'],))
    hook(api, 'pull_request', pr_event('opened'))
    assert get(api, 'tasks/' + task['id'])['task']['step']['name'] == 'Code review'
    hook(api, 'pull_request', pr_event('closed', merged=True, merge_commit_sha='abc123'))
    assert get(api, 'tasks/' + task['id'])['task']['step']['name'] == 'Merged'
    api.app.state.store.settings.release_commit = 'abc123'
    with api.app.state.store.transaction() as c:
        assert G.ship_deployed(c, api.app.state.store.settings) == [task['id']]
    after = get(api, 'tasks/' + task['id'])['task']
    assert after['status'] == 'done' and after['step'] is None and after['type_id'] == typ['id']
