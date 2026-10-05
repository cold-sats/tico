"""Deleting tasks offline removes them and their conversations, and refuses a task carrying work."""

from backend.task_delete import delete_tasks
from backend.tests.test_tasks_board import api, bot_token, get, headers, post  # noqa: F401  (the fixture)


def test_delete_removes_imported_tickets_and_refuses_one_with_work_outside_the_list(api):
    store = api.app.state.store
    ticket = post(api, "tasks", {"owner": "ben", "title": "Fix the account page", "body": "Imported."})
    post(api, f"tasks/{ticket['id']}/links", {"url": "https://example.com/c/18945"})
    post(api, f"tasks/{ticket['id']}/comments", {"text": "Copied from the old board."})
    parent = post(api, "tasks", {"owner": "ben", "title": "Plan the launch", "body": "x"})
    post(api, "tasks", {"owner": "priya", "title": "Write the post", "body": "x", "parent_id": parent["id"]})

    with store.transaction() as c:
        conversation = c.execute("SELECT conversation_id FROM tasks WHERE id=?", (ticket["id"],)).fetchone()[0]
        dry = delete_tasks(c, [ticket["id"]])
        assert dry["applied"] is False and dry["tasks"] == 1 and dry["messages"] >= 1 and not dry["refused"]
        refused = delete_tasks(c, [parent["id"]], apply=True)
        assert refused["refused"] == {"subtasks outside the list": 1} and refused["applied"] is False
        assert delete_tasks(c, ["no-such-task"], apply=True)["missing"] == ["no-such-task"]
        assert delete_tasks(c, [ticket["id"]], apply=True)["applied"] is True

    with store.read() as c:
        for table, column, value in (("tasks", "id", ticket["id"]), ("task_links", "task_id", ticket["id"]),
                                     ("task_events", "task_id", ticket["id"]),
                                     ("conversations", "id", conversation),
                                     ("messages", "conversation_id", conversation)):
            assert c.execute(f"SELECT count(*) FROM {table} WHERE {column}=?", (value,)).fetchone()[0] == 0, table
        assert c.execute("SELECT count(*) FROM events WHERE action='task.deleted' AND target=?",
                         (ticket["id"],)).fetchone()[0] == 1
        assert c.execute("SELECT count(*) FROM tasks WHERE id=?", (parent["id"],)).fetchone()[0] == 1
    get(api, "tasks/" + ticket["id"], expected=404)


def test_a_person_deletes_a_task_they_asked_for_and_nobody_else_can(api):
    mine = post(api, "tasks", {"owner": "ben", "title": "Fix the duplicate page", "body": "x"}, token="priya-test")
    theirs = post(api, "tasks", {"owner": "ben", "title": "Fix the pricing page", "body": "x"}, token="ben-test")
    parent = post(api, "tasks", {"owner": "ben", "title": "Plan the launch", "body": "x"}, token="priya-test")
    post(api, "tasks", {"owner": "ben", "title": "Write the post", "body": "x", "parent_id": parent["id"]}, token="priya-test")

    refused = post(api, f"tasks/{theirs['id']}/delete", {}, token="priya-test", expected=403)
    assert refused["error"]["code"] == "forbidden"
    assert post(api, f"tasks/{parent['id']}/delete", {}, token="priya-test", expected=409)["error"]["code"] == "has_work"
    assert post(api, f"tasks/{mine['id']}/delete", {}, token="priya-test") == {"deleted": mine["id"]}
    get(api, "tasks/" + mine["id"], expected=404)
    # A mover may delete anyone's task; a bot never deletes, even its own.
    assert post(api, f"tasks/{theirs['id']}/delete", {})["deleted"] == theirs["id"]
    bots = post(api, "tasks", {"owner": "ops", "title": "Draft the newsletter", "body": "x"})
    r = api.post(f"/api/v2/tasks/{bots['id']}/delete", json={}, headers=headers(bot_token(api)))
    assert r.status_code == 403
