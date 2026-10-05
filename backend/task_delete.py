"""Deleting tasks outright, offline: for tasks made by mistake, such as a bulk import run twice.

Tasks are history, so the API only closes them. This removes a list of tasks, their own rows
(events, links, labels, delegations, reminders, a service key's mapping) and their conversations
with every message, in one transaction. A task that carries work is refused whole, so nothing
anyone or any bot did is lost: a turn, a job, an approval, a file, a routine occurrence, a
meeting delivery, a subtask or a blocked task outside the list. The audit log keeps one
`task.deleted` event per task.
"""

from .store import H


# Rows that only describe the task: deleted with it.
TASK_ROWS = ("task_events", "task_links", "task_tags", "task_delegations", "task_reminders",
             "service_key_tasks")
# Rows that are work done on the task: any one of them refuses the run.
TASK_WORK = ("turns", "approvals", "task_assets", "bot_files", "bot_file_activity",
             "bot_tool_requests", "meeting_deliveries", "schedule_occurrences", "watcher_items")
MESSAGE_WORK = ("turns", "jobs", "attempt_inputs", "approvals", "credential_requests",
                "bot_transition_checkpoints", "batches", "message_assets")
CONVERSATION_WORK = ("attempt_conversations", "session_epochs", "assistant_actions", "chat_goals",
                     "credential_requests", "bot_transition_checkpoints")
# Delivery bookkeeping for the messages: deleted with them.
MESSAGE_ROWS = ("slack_posts", "slack_digests", "update_queue")
CONVERSATION_ROWS = ("slack_digests", "slack_threads")


def _has(c, table, column):
    """An older database may lack a table or a column; there is nothing in it to remove."""
    return any(r[1] == column for r in c.execute(f"PRAGMA table_info('{table}')"))


def _marks(values):
    return ",".join("?" * len(values))


def _count(c, table, column, values):
    if not values or not _has(c, table, column):
        return 0
    total = 0
    for i in range(0, len(values), 500):
        part = values[i:i + 500]
        total += c.execute(f"SELECT count(*) FROM {table} WHERE {column} IN ({_marks(part)})", part).fetchone()[0]
    return total


def _delete(c, table, column, values):
    if not values or not _has(c, table, column):
        return 0
    total = 0
    for i in range(0, len(values), 500):
        part = values[i:i + 500]
        total += c.execute(f"DELETE FROM {table} WHERE {column} IN ({_marks(part)})", part).rowcount
    return total


def _column(c, sql, values):
    out = []
    for i in range(0, len(values), 500):
        part = values[i:i + 500]
        out += [r[0] for r in c.execute(sql.format(_marks(part)), part)]
    return out


def delete_tasks(c, ids, apply=False):
    """What deleting `ids` removes, and with apply=True removes it. Refuses the whole list if any
    task is unknown or carries work; the report says which and why."""
    ids = list(dict.fromkeys(i.strip() for i in ids if i and i.strip()))
    found = set(_column(c, "SELECT id FROM tasks WHERE id IN ({})", ids))
    missing = [i for i in ids if i not in found]
    conversations = list(dict.fromkeys(
        _column(c, "SELECT conversation_id FROM tasks WHERE id IN ({}) AND conversation_id IS NOT NULL", ids)
        + _column(c, "SELECT id FROM conversations WHERE task_id IN ({})", ids)))
    messages = _column(c, "SELECT id FROM messages WHERE conversation_id IN ({})", conversations)
    chosen = set(ids)
    refusals = {}
    for table in TASK_WORK:
        if n := _count(c, table, "task_id", ids):
            refusals[f"{table}.task_id"] = n
    for table in MESSAGE_WORK:
        if n := _count(c, table, "message_id", messages):
            refusals[f"{table}.message_id"] = n
    for table in CONVERSATION_WORK:
        if n := _count(c, table, "conversation_id", conversations):
            refusals[f"{table}.conversation_id"] = n
    outside = [r for r in _column(c, "SELECT id FROM tasks WHERE parent_id IN ({})", ids) if r not in chosen]
    if outside:
        refusals["subtasks outside the list"] = len(outside)
    blocked = [r for r in _column(c, "SELECT id FROM tasks WHERE blocked_by IN ({})", ids) if r not in chosen]
    if blocked:
        refusals["tasks blocked by one outside the list"] = len(blocked)
    report = {"tasks": len(found), "missing": missing, "refused": refusals,
              "conversations": len(conversations), "messages": len(messages),
              "rows": {t: _count(c, t, "task_id", ids) for t in TASK_ROWS},
              "applied": False}
    if missing or refusals or not apply:
        return report
    for table in MESSAGE_ROWS:
        _delete(c, table, "message_id", messages)
    for table in CONVERSATION_ROWS:
        _delete(c, table, "conversation_id", conversations)
    if _has(c, "task_file_reviews", "comment_id"):
        _delete(c, "task_file_reviews", "comment_id", messages)
        _delete(c, "task_file_reviews", "ask_message_id", messages)
    for table in TASK_ROWS:
        _delete(c, table, "task_id", ids)
    # Status lines and filed insights keep their own history; they only stop pointing at the task.
    for table, column in (("bot_status", "task_id"), ("market_insights", "filed_task")):
        if _has(c, table, column):
            for i in range(0, len(ids), 500):
                part = ids[i:i + 500]
                c.execute(f"UPDATE {table} SET {column}=NULL WHERE {column} IN ({_marks(part)})", part)
    _delete(c, "messages", "id", messages)
    # Detach the tasks from their conversations before the conversations go.
    for i in range(0, len(ids), 500):
        part = ids[i:i + 500]
        c.execute(f"UPDATE tasks SET conversation_id=NULL WHERE id IN ({_marks(part)})", part)
    _delete(c, "conversations", "id", conversations)
    rows = {}
    for i in range(0, len(ids), 500):
        part = ids[i:i + 500]
        rows.update({r[0]: r for r in c.execute(
            f"SELECT id,title,requester,owner,status FROM tasks WHERE id IN ({_marks(part)})", part)})
        # Links between tasks inside the list go first, so no row points at a deleted one.
        c.execute(f"UPDATE tasks SET parent_id=NULL, blocked_by=NULL WHERE id IN ({_marks(part)})", part)
    _delete(c, "tasks", "id", ids)
    for tid in ids:
        _, title, requester, owner, status = rows[tid]
        H.event(c, H.KEEPER, "task.deleted", tid, {"title": title, "requester": requester,
                                                   "owner": owner, "status": status})
    report["applied"] = True
    return report
