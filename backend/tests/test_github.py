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
    tag = post(api, 'tags', {'key': 'release-checklist', 'label': 'release',
        'metadata': {'date': '2026-10-02'}, 'markdown': '- [ ] Smoke checks'})['tag']
    typ = post(api, 'task-types', {'name': 'Engineering', 'steps': [
        {'name': 'Draft', 'status': 'open'}, {'name': 'Code review', 'status': 'review'},
        {'name': 'Merged', 'status': 'ready'}]})['type']
    task = post(api, 'tasks', {'owner': 'cpo', 'title': 'Build the release screen', 'body': 'Please.',
        'links': [PR], 'type': typ['id'], 'labels': [tag['key']]})
    general = post(api, 'tasks', {'owner': 'cpo', 'title': 'Review an ordinary request', 'body': 'Please.', 'links': [PR]})
    assert task['lane'] == general['lane'] == 'company'
    hook(api, 'pull_request', pr_event('opened'))
    assert get(api, 'tasks/' + task['id'])['task']['step']['name'] == 'Code review'
    hook(api, 'pull_request', pr_event('closed', merged=True, merge_commit_sha='abc123'))
    assert get(api, 'tasks/' + task['id'])['task']['step']['name'] == 'Merged'
    api.app.state.store.settings.release_commit = 'abc123'
    with api.app.state.store.transaction() as c:
        assert G.ship_deployed(c, api.app.state.store.settings) == [task['id']]
    after = get(api, 'tasks/' + task['id'])['task']
    assert after['status'] == 'done' and after['step'] is None and after['type_id'] == typ['id']
    assert after['labels'] == [tag['key']] and after['tags'][0]['metadata'] == tag['metadata']
    assert get(api, 'tags/' + tag['id'])['tasks'][0]['status'] == 'done'
    assert get(api, 'tasks/' + general['id'])['task']['status'] == 'open'


def test_grouped_wakes_retry_bad_rows_and_send_blocked_tasks(api, monkeypatch):
    from backend.repositories import save_metadata
    tasks = [post(api, "tasks", {"owner": "cpo", "title": title, "body": "Review work"})
             for title in ("Broken notice", "Blocked task", "Finished task")]
    store = api.app.state.store
    with store.transaction() as c:
        for task in tasks:
            save_metadata(c, "github-task-wake:" + task["id"], {"due": H.shift(H.now(), seconds=-1), "items": ["Checks failed"]})
        c.execute("UPDATE tasks SET status='blocked' WHERE id=?", (tasks[1]["id"],))
        c.execute("UPDATE tasks SET status='closed' WHERE id=?", (tasks[2]["id"],))
    wake = H._wake
    def broken(c, task, *args):
        if task["id"] == tasks[0]["id"]:
            H.event(c, H.KEEPER, "wake.partial", task["id"])
            raise RuntimeError("bad conversation")
        return wake(c, task, *args)
    monkeypatch.setattr(H, "_wake", broken)
    with store.transaction() as c:
        assert G.flush_wakes(c) == [tasks[1]["id"]]
    with store.read() as c:
        assert [r[0] for r in c.execute("SELECT key FROM registry_metadata WHERE key LIKE 'github-task-wake:%'")] == ["github-task-wake:" + tasks[0]["id"]]
        assert not c.execute("SELECT 1 FROM events WHERE action='wake.partial'").fetchone()
    monkeypatch.setattr(H, "_wake", wake)
    with store.transaction() as c:
        assert G.flush_wakes(c) == [tasks[0]["id"]]


def test_deploy_query_uses_repository_index_and_ignores_other_repos(api):
    own = post(api, "tasks", {"owner": "cpo", "title": "Release work", "body": "Review", "links": [PR]})
    other = post(api, "tasks", {"owner": "cpo", "title": "Other work", "body": "Review",
                                "links": ["https://github.com/example/other/pull/412"]})
    store = api.app.state.store
    store.settings.release_commit = "release-sha"
    store.settings.release_repo = "TicoTeam/Tico"
    with store.transaction() as c:
        c.execute("UPDATE tasks SET status='ready' WHERE id IN (?,?)", (own["id"], other["id"]))
        c.execute("UPDATE task_links SET state='merged',pr_sha='release-sha'")
        plan = c.execute("EXPLAIN QUERY PLAN SELECT l.id FROM task_links l JOIN tasks t ON t.id=l.task_id "
                         "WHERE l.kind='pr' AND l.state='merged' AND l.url LIKE ? AND t.status='ready'",
                         ("https://github.com/ticoteam/tico/pull/%",)).fetchall()
        assert any("task_links_repo_url" in r[3] and "url>?" in r[3] for r in plan)
        assert G.ship_deployed(c, store.settings) == [own["id"]]
        assert H.task(c, other["id"])["status"] == "ready"
