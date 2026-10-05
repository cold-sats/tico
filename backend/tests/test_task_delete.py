"""Deleting tasks offline removes them and their conversations, and refuses a task carrying work."""

from backend.task_delete import delete_tasks
from backend.tests.test_tasks_board import api, get, post  # noqa: F401  (the fixture)


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
