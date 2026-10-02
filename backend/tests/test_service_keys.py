"""Service keys: another system files, updates, closes and reopens its tasks with one, and reaches nothing else."""

import pytest

from backend.auth import Identity
from backend.store import H, Problem, digest
from backend.tests.test_api import api, get, headers, post  # noqa: F401  (the api fixture)


def inbound(api, secret, expected=200, **body):
    r = api.post("/api/v2/inbound/tasks", json=body, headers={"Authorization": "Bearer " + secret})
    assert r.status_code == expected, r.text
    return r.json()


def test_one_task_per_piece_of_work_whatever_order_the_calls_come_in(api):
    secret = post(api, "service-keys", {"label": "Billing backend"})["key"]
    # Done over there before any task existed: nothing is filed.
    assert inbound(api, secret, key="report-40", close=True) == {"task": None, "created": False, "changed": False}
    work = {"key": "report-41", "owner": "ben@acme.example", "title": "Review the weekly report for Acme",
            "body": "The report is ready."}
    first = inbound(api, secret, **work)
    assert set(first["task"]) == {"id"}
    task = get(api, "tasks/" + first["task"]["id"])["task"]
    assert first["created"] and (task["owner"], task["requester"]) == ("human:ben", "keeper")
    assert task["body"] == "The report is ready.\n\n_Filed by Billing backend (service key)._"
    again = inbound(api, secret, **work)
    assert (again["task"]["id"], again["created"], again["changed"]) == (task["id"], False, False)
    # Another piece of work may share the title and the owner: the pair is what makes it one task.
    other = inbound(api, secret, **{**work, "key": "report-42"})
    assert other["created"] and other["task"]["id"] != task["id"]
    changed = inbound(api, secret, key="report-41", body="The report is ready. Two charts moved.", labels=["reports"])
    assert changed["changed"] and changed["task"] == {"id": task["id"]}
    updated = get(api, "tasks/" + task["id"])["task"]
    assert updated["labels"] == ["reports"]
    assert updated["body"].startswith("The report is ready. Two charts moved.")
    closed = inbound(api, secret, key="report-41", close=True, note="Approved in billing.")
    assert closed["changed"] and get(api, "tasks/" + task["id"])["task"]["status"] == "closed"
    assert not inbound(api, secret, key="report-41", close=True)["changed"]
    reopened = inbound(api, secret, key="report-41", owner="human:cara")
    assert reopened["changed"] and reopened["task"] == {"id": task["id"]}
    updated = get(api, "tasks/" + task["id"])["task"]
    assert (updated["status"], updated["owner"]) == ("open", "human:cara")
    inbound(api, secret, 422, key="report-43", owner="nobody@acme.example", title="Review the report", body="x")
    with api.app.state.store.read() as c:
        used = c.execute("SELECT COUNT(*) FROM events WHERE action='service_key.use'").fetchone()[0]
    assert used == 8                # every call that was answered, including the ones that changed nothing


def test_a_service_key_reaches_nothing_else_and_a_revoked_one_nothing_at_all(api):
    post(api, "service-keys", {"label": "Mine"}, token="cara-test", expected=403)       # a member
    made = post(api, "service-keys", {"label": "Billing backend"}, token="ben-test")     # an admin
    listed = get(api, "service-keys")["keys"]
    assert [k["id"] for k in listed] == [made["id"]] and made["key"] not in str(listed)
    sk = {"Authorization": "Bearer " + made["key"]}
    for method, path in (("get", "/api/v2/tasks"), ("get", "/api/v2/me"), ("get", "/api/v2/service-keys"),
                         ("post", "/api/v2/tasks"), ("post", "/api/v2/sql"), ("post", "/api/v2/mcp")):
        r = api.request(method.upper(), path, headers=sk, json={} if method == "post" else None)
        assert r.status_code == 403, path
    # A person's session or personal token is not a service key, and SQL never shows a key's hash.
    token = post(api, "me/tokens", {"label": "script"})["token"]
    for person in (headers(), headers(token)):
        assert api.post("/api/v2/inbound/tasks", json={"key": "x", "close": True}, headers=person).status_code == 403
    assert api.post("/api/v2/sql", json={"sql": "SELECT key_hash FROM service_keys"}, headers=headers()).status_code == 422
    post(api, "service-keys/" + made["id"] + "/revoke", {})
    assert api.post("/api/v2/inbound/tasks", json={"key": "x", "close": True}, headers=sk).status_code == 401


def test_keys_cannot_read_teammate_changes_or_mutate_other_keys_work(api):
    first = post(api, "service-keys", {"label": "Reports"})
    second = post(api, "service-keys", {"label": "Billing"})
    task = inbound(api, first["key"], key="same-key", owner="human:ben",
                   title="Review the report", body="Please review.")["task"]
    with api.app.state.store.transaction() as c:
        c.execute("UPDATE tasks SET body='Confidential teammate revision',note='Internal note' WHERE id=?", (task["id"],))
        H.task_comment(c, "human:ana", task["id"], "Confidential comment", wake=False)
    assert inbound(api, first["key"], key="same-key") == {"task": task, "created": False, "changed": False}
    assert inbound(api, second["key"], key="same-key", close=True)["task"] is None
    other = inbound(api, second["key"], key="same-key", owner="human:ben",
                    title="Review the report", body="Please review.")["task"]
    assert other != task
    assert get(api, "tasks/" + task["id"])["task"]["body"] == "Confidential teammate revision"
    with api.app.state.store.read() as c:
        assert c.execute("SELECT key_hash FROM service_keys WHERE id=?", (first["id"],)).fetchone()[0] == digest(first["key"])
    # Revalidate a credential obtained before revocation under the write lock, before running any callback.
    who = Identity("service:" + first["id"], "service")
    post(api, "service-keys/" + first["id"] + "/revoke", {})
    with pytest.raises(Problem) as exc:
        api.app.state.store.write(who, lambda c: pytest.fail("revoked key reached a write"))
    assert exc.value.status == 401


def test_private_work_is_neither_returned_nor_changed_by_its_service_key(api):
    secret = post(api, "service-keys", {"label": "Reports"})["key"]
    task = inbound(api, secret, key="report", owner="human:ben", title="Review the report", body="Please review.")["task"]
    with api.app.state.store.transaction() as c:
        # Privacy belongs to the separate task gate; the service boundary tolerates older schemas.
        if "private" not in {r[1] for r in c.execute("PRAGMA table_info(tasks)")}:
            c.execute("ALTER TABLE tasks ADD COLUMN private INTEGER NOT NULL DEFAULT 0")
        c.execute("UPDATE tasks SET private=1 WHERE id=?", (task["id"],))
        before = dict(c.execute("SELECT * FROM tasks WHERE id=?", (task["id"],)).fetchone())
    for body in ({}, {"body": "Overwrite", "owner": "human:cara"}, {"close": True}, {"step": "open"}):
        refused = inbound(api, secret, 403, key="report", **body)
        assert "Please review" not in str(refused)
    with api.app.state.store.read() as c:
        assert dict(c.execute("SELECT * FROM tasks WHERE id=?", (task["id"],)).fetchone()) == before


def test_mint_shows_the_secret_once_without_persisting_it_in_the_retry_cache(api):
    same_headers = headers()
    made = api.post("/api/v2/service-keys", json={"label": "Reports"}, headers=same_headers).json()
    retry = api.post("/api/v2/service-keys", json={"label": "Reports"}, headers=same_headers)
    assert retry.status_code == 200, retry.text
    assert retry.json()["id"] == made["id"] and "key" not in retry.json()
    with api.app.state.store.read() as c:
        for table in ("service_keys", "idempotency", "events"):
            assert made["key"] not in str([tuple(r) for r in c.execute("SELECT * FROM " + table)])
