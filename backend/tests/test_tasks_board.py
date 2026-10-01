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


# ----------------------------------------------------------------------------- task pipelines

def pipeline(api, token='ana-test'):
    return post(api, 'task-types', {'name': 'Marketing', 'steps': [
        {'name': 'Draft', 'status': 'open'},
        {'name': 'Legal review', 'status': 'review'},
        {'name': 'Copy review', 'status': 'review'},
        {'name': 'Complete', 'status': 'done'},
        {'name': 'Archive', 'status': 'closed'},
    ]}, token=token)['type']


def edit_pipeline_task(api, task, **fields):
    return post(api, 'tasks/' + task['id'], {'version': task['version'], **fields})


def test_steps_keep_status_contract_stay_first_match_and_clear(api):
    typ = pipeline(api)
    task = post(api, 'tasks', {'owner': 'cmo', 'title': 'Draft the campaign', 'body': 'Please.', 'type': typ['id']})
    assert task['type'] == {'id': typ['id'], 'name': 'Marketing'}
    assert task['step']['name'] == 'Draft' and task['status'] == 'open'
    task = edit_pipeline_task(api, task, step='Copy review')
    copy_id = task['step_id']
    assert task['status'] == 'review'
    # A status-only call from an old client stays on the second review step.
    task = edit_pipeline_task(api, task, status='review')
    assert task['step_id'] == copy_id
    task = edit_pipeline_task(api, task, status='doing')
    assert task['step'] is None and task['step_id'] is None and task['status'] == 'doing'
    task = edit_pipeline_task(api, task, status='review')
    assert task['step']['name'] == 'Legal review'
    # No step order: move straight to any step, then back to the first.
    task = edit_pipeline_task(api, task, step='Complete')
    assert task['status'] == 'done' and task['done_at']
    task = edit_pipeline_task(api, task, step='Draft')
    assert task['status'] == 'open' and task['done_at'] is None
    task = edit_pipeline_task(api, task, step='Archive')
    assert task['status'] == 'closed' and task['closed_at'] and task['step']['name'] == 'Archive'
    task = edit_pipeline_task(api, task, status='open')
    assert task['closed_at'] is None and task['step']['name'] == 'Draft'
    task = edit_pipeline_task(api, task, close=True)
    assert task['status'] == 'closed' and task['step']['name'] == 'Archive'
    history = get(api, 'tasks/' + task['id'])['events']
    assert any(e['field'] == 'step' and e['new'] == copy_id for e in history)
    listed = next(t for t in get(api, 'tasks?status=closed')['tasks'] if t['id'] == task['id'])
    assert listed['type'] == task['type'] and listed['step'] == task['step']


def test_type_and_step_management_permissions_and_references(api):
    post(api, 'task-types', {'name': 'Sales'}, token='priya-test', expected=403)
    typ = pipeline(api, token='ben-test')
    task = post(api, 'tasks', {'owner': 'cmo', 'title': 'Write the ad', 'body': 'Please.',
        'type': 'Marketing', 'step': 'Copy review'})
    assert task['status'] == 'review'
    clean = lambda steps: [{k: s[k] for k in ('id', 'name', 'position', 'status')} for s in steps]
    post(api, 'task-types/' + typ['id'], {'steps': clean(typ['steps'][:2])}, expected=422)
    post(api, 'task-types/' + typ['id'] + '/delete', {}, expected=422)
    renamed = clean(typ['steps'])
    renamed[1]['name'], renamed[2]['name'] = renamed[2]['name'], renamed[1]['name']
    post(api, 'task-types/' + typ['id'], {'steps': renamed})
    assert get(api, 'tasks/' + task['id'])['task']['step_id'] == task['step_id']
    task = edit_pipeline_task(api, task, type='General')
    assert task['type_id'] == 'general' and task['step_id'] == 'general-review'
    # Empty removes a step assignment without changing its status.
    task = edit_pipeline_task(api, task, step='')
    assert task['status'] == 'review' and task['step'] is None
    other = post(api, 'task-types', {'name': 'Design', 'steps': [{'name': 'Draft', 'status': 'open'}]})['type']
    post(api, 'tasks/' + task['id'], {'version': task['version'], 'step': other['steps'][0]['id']}, expected=422)
    post(api, 'task-types/' + typ['id'], {'steps': []})
    post(api, 'task-types/' + typ['id'] + '/delete', {})
    post(api, 'task-types/general/delete', {}, expected=422)
    with api.app.state.store.read() as c:
        assert c.execute('SELECT 1 FROM cloud_migrations WHERE version=48').fetchone()
        assert c.execute('PRAGMA foreign_key_check').fetchall() == []


def test_step_moves_enforce_existing_bot_status_permissions(api):
    typ = post(api, 'task-types', {'name': 'Engineering', 'steps': [
        {'name': 'Merged', 'status': 'ready'}, {'name': 'Archive', 'status': 'closed'}]})['type']
    task = post(api, 'tasks', {'owner': 'ops', 'title': 'Build the screen', 'body': 'Please.', 'type': typ['id']})
    token = bot_token(api)
    for step in typ['steps']:
        post(api, 'tasks/' + task['id'], {'version': task['version'], 'step': step['id']}, token=token, expected=403)
    post(api, 'tasks', {'owner': 'cmo', 'title': 'Build another screen', 'body': 'Please.',
         'type': typ['id'], 'step': typ['steps'][0]['id']}, token=token, expected=403)
    assert get(api, 'tasks/' + task['id'])['task']['status'] == 'open'


def test_editing_a_step_status_moves_tasks_with_history_and_completion_dates(api):
    typ = pipeline(api)
    task = post(api, 'tasks', {'owner': 'cmo', 'title': 'Review the launch', 'body': 'Please.', 'type': typ['id']})
    steps = [{k: s[k] for k in ('id', 'name', 'position', 'status')} for s in typ['steps']]
    steps[0]['status'] = 'done'
    post(api, 'task-types/' + typ['id'], {'steps': steps})
    after = get(api, 'tasks/' + task['id'])
    assert after['task']['status'] == 'done' and after['task']['done_at']
    assert after['task']['step_id'] == task['step_id'] and after['task']['version'] > task['version']
    assert any(e['field'] == 'status' and e['new'] == 'done' for e in after['events'])


def test_same_status_step_move_does_not_repeat_a_result_or_completion(api):
    typ = post(api, 'task-types', {'name': 'Decisions', 'steps': [
        {'name': 'Recorded', 'status': 'done'}, {'name': 'Verified', 'status': 'done'},
        {'name': 'Archived', 'status': 'closed'}, {'name': 'Filed', 'status': 'closed'}]})['type']
    token = bot_token(api)
    task = post(api, 'tasks', {'owner': 'ana', 'title': 'Decide the campaign', 'body': 'Review it.',
        'type': typ['id']}, token=token)
    task = edit_pipeline_task(api, task, step='Recorded', note='Proceed with the draft.')
    done_at = task['done_at']
    task = edit_pipeline_task(api, task, step='Verified')
    assert task['status'] == 'done' and task['done_at'] == done_at
    task = edit_pipeline_task(api, task, step='Archived')
    closed_at = task['closed_at']
    task = edit_pipeline_task(api, task, step='Filed')
    assert task['status'] == 'closed' and task['closed_at'] == closed_at
    task = edit_pipeline_task(api, task, close=True)
    assert task['closed_at'] == closed_at


def test_stranded_auto_reopen_maps_to_the_types_open_step(api):
    typ = post(api, 'task-types', {'name': 'Follow-up', 'steps': [
        {'name': 'Next', 'status': 'open'}, {'name': 'Waiting for input', 'status': 'waiting'}]})['type']
    task = post(api, 'tasks', {'owner': 'cmo', 'title': 'Review the draft', 'body': 'Please.', 'type': typ['id']})
    task = edit_pipeline_task(api, task, step='Waiting for input')
    with api.app.state.store.transaction() as c:
        future = H.shift(H.now(), days=2)
        assert (task['id'], 'open') in H.sweep_stranded(c, at=future)
        after = H.task(c, task['id'])
        assert after['status'] == 'open' and after['step_id'] == typ['steps'][0]['id']
