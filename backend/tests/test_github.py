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


def test_many_prs_wait_for_every_link_and_roll_up_worst_state(api):
    second = PR.replace('/412', '/413')
    task = post(api, 'tasks', {'owner': 'cpo', 'title': 'Ship both pieces', 'body': 'x', 'links': [PR, second]})
    with api.app.state.store.transaction() as c:
        c.execute("UPDATE tasks SET lane='product' WHERE id=?", (task['id'],))
    hook(api, 'pull_request', pr_event('opened', head={'sha': 'head1'}))
    hook(api, 'pull_request', pr_event('closed', merged=True, merge_commit_sha='abc123'))
    detail = get(api, 'tasks/' + task['id'])['task']
    assert detail['status'] == 'review' and detail['pr_state'] == 'open'
    assert detail['links'][0]['repo'] == 'ticoteam/tico' and detail['links'][0]['number'] == 412
    hook(api, 'pull_request', pr_event('synchronize', html_url=second, mergeable=False, number=413))
    assert get(api, 'tasks/' + task['id'])['task']['pr_state'] == 'conflict'
    hook(api, 'check_run', {'repository': {'full_name': 'ticoteam/tico'}, 'check_run': {
        'name': 'Unit tests', 'conclusion': 'failure', 'pull_requests': [{'number': 413}]}})
    assert get(api, 'tasks/' + task['id'])['task']['pr_state'] == 'failing'
    hook(api, 'pull_request_review', {'action': 'submitted', 'pull_request': {'html_url': second},
        'review': {'state': 'changes_requested'}})
    hook(api, 'pull_request_review_comment', {'action': 'created', 'pull_request': {'html_url': second}})
    links = get(api, 'tasks/' + task['id'] + '/links')['links']
    assert links[1]['review_state'] == 'changes_requested' and links[1]['pending_comments'] == 1
    hook(api, 'pull_request', pr_event('closed', html_url=second))
    assert get(api, 'tasks/' + task['id'])['task']['status'] == 'ready'
    response = api.delete('/api/v2/tasks/' + task['id'] + '/links/' + links[1]['id'], headers=headers())
    assert response.status_code == 200 and len(response.json()['links']) == 1


def test_webhook_burst_is_durable_and_sends_one_specific_wake(api):
    from backend import repositories as R
    task = post(api, 'tasks', {'owner': 'cpo', 'title': 'Repair checks', 'body': 'x', 'links': [PR]})
    with api.app.state.store.transaction() as c:
        before = c.execute('SELECT count(*) FROM messages').fetchone()[0]
    for name in ('Unit tests', 'Lint'):
        hook(api, 'check_run', {'repository': {'full_name': 'ticoteam/tico'}, 'check_run': {
            'name': name, 'conclusion': 'failure', 'pull_requests': [{'number': 412}]}})
    with api.app.state.store.transaction() as c:
        assert G.flush_wakes(c) == []
        assert c.execute('SELECT count(*) FROM messages').fetchone()[0] == before
        key = 'github-task-wake:' + task['id']
        burst = R.metadata(c, key)
        assert len(burst['items']) == 2
        burst['due'] = H.shift(H.now(), seconds=-1)
        R.save_metadata(c, key, burst)
        assert G.flush_wakes(c) == [task['id']]
        assert G.flush_wakes(c) == []
        assert c.execute('SELECT count(*) FROM messages').fetchone()[0] == before + 1
        message = c.execute('SELECT body FROM messages ORDER BY created DESC LIMIT 1').fetchone()[0]
        assert 'Unit tests' in message and 'Lint' in message and 'tico#412' in message


def test_shipping_waits_for_all_merged_prs_in_the_release(api):
    second = PR.replace('/412', '/413')
    task = post(api, 'tasks', {'owner': 'cpo', 'title': 'Ship several changes', 'body': 'x', 'links': [PR, second]})
    with api.app.state.store.transaction() as c:
        c.execute("UPDATE tasks SET lane='product' WHERE id=?", (task['id'],))
    hook(api, 'pull_request', pr_event('closed', merged=True, merge_commit_sha='first'))
    hook(api, 'pull_request', pr_event('closed', html_url=second, merged=True, merge_commit_sha='second'))
    api.app.state.store.settings.release_commit = 'first'
    with api.app.state.store.transaction() as c:
        assert G.ship_deployed(c, api.app.state.store.settings) == []
        G.push(c, {'ref': 'refs/heads/main', 'repository': {'full_name': 'ticoteam/tico'},
                   'commits': [{'id': 'first'}, {'id': 'second'}]})
        api.app.state.store.settings.release_commit = 'second'
        assert G.ship_deployed(c, api.app.state.store.settings) == [task['id']]
        assert all(l['state'] == 'shipped' for l in H.task_links(c, task['id']))


def test_commit_status_and_old_head_checks_preserve_current_pr_state(api):
    task = post(api, 'tasks', {'owner': 'cpo', 'title': 'Check the current commit', 'body': 'x', 'links': [PR]})
    hook(api, 'pull_request', pr_event('synchronize', head={'sha': 'current'}))
    hook(api, 'check_run', {'repository': {'full_name': 'ticoteam/tico'}, 'check_run': {
        'name': 'Tests', 'head_sha': 'old', 'conclusion': 'failure', 'pull_requests': [{'number': 412}]}})
    assert get(api, 'tasks/' + task['id'])['task']['links'][0]['checks'] == 'pending'
    hook(api, 'status', {'repository': {'full_name': 'ticoteam/tico'}, 'sha': 'current',
                        'context': 'Tests', 'state': 'success'})
    assert get(api, 'tasks/' + task['id'])['task']['links'][0]['checks'] == 'passing'


def test_task_link_upgrade_preserves_legacy_pr_rows(api):
    from backend.store import Store
    task = post(api, 'tasks', {'owner': 'cpo', 'title': 'Keep the existing PR', 'body': 'x', 'links': [PR]})
    store = api.app.state.store
    with store.transaction() as c:
        c.execute('CREATE TABLE legacy_task_links(id TEXT PRIMARY KEY, task_id TEXT NOT NULL REFERENCES tasks(id), '
                  'kind TEXT NOT NULL, url TEXT NOT NULL, title TEXT, state TEXT, added_by TEXT, created TEXT NOT NULL, '
                  'pr_sha TEXT, pr_merged_at TEXT)')
        c.execute('INSERT INTO legacy_task_links SELECT id,task_id,kind,url,title,state,added_by,created,pr_sha,pr_merged_at FROM task_links')
        c.execute('DROP TABLE task_links')
        c.execute('ALTER TABLE legacy_task_links RENAME TO task_links')
        c.execute('PRAGMA user_version=17')
        c.execute('DELETE FROM cloud_migrations WHERE version=51')
    Store(store.settings).initialize(seed_market=False)
    with store.read() as c:
        link = H.task_links(c, task['id'])[0]
        assert link['url'] == PR and link['state'] == 'open' and link['title'] == 'tico#412'
        assert link['repo'] == 'ticoteam/tico' and link['number'] == 412
        assert link['path'] is None and link['computer_id'] is None and link['checks'] is None
        assert c.execute('PRAGMA user_version').fetchone()[0] == len(H.MIGRATIONS)
        assert c.execute('SELECT 1 FROM cloud_migrations WHERE version=51').fetchone()
