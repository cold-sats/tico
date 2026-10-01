"""Service keys: another system files, updates, closes and reopens its tasks with one, and reaches nothing else."""

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
    task = first["task"]
    assert first["created"] and (task["owner"], task["requester"]) == ("human:ben", "keeper")
    assert task["body"] == "The report is ready.\n\n_Filed by Billing backend (service key)._"
    again = inbound(api, secret, **work)
    assert (again["task"]["id"], again["created"], again["changed"]) == (task["id"], False, False)
    # Another piece of work may share the title and the owner: the pair is what makes it one task.
    other = inbound(api, secret, **{**work, "key": "report-42"})
    assert other["created"] and other["task"]["id"] != task["id"]
    changed = inbound(api, secret, key="report-41", body="The report is ready. Two charts moved.", labels=["reports"])
    assert changed["changed"] and changed["task"]["labels"] == ["reports"]
    assert changed["task"]["body"].startswith("The report is ready. Two charts moved.")
    closed = inbound(api, secret, key="report-41", close=True, note="Approved in billing.")
    assert closed["changed"] and closed["task"]["status"] == "closed"
    assert not inbound(api, secret, key="report-41", close=True)["changed"]
    reopened = inbound(api, secret, key="report-41", owner="human:cara")
    assert reopened["changed"] and (reopened["task"]["id"], reopened["task"]["status"]) == (task["id"], "open")
    assert reopened["task"]["owner"] == "human:cara"
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
