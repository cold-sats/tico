"""Current task participants fence derived reads, independently of room or bot grants.

Structured provenance is checked again on each request. This cannot retract a download
or identify private information copied into unrelated, untagged prose.
"""
import re

from .store import H, Problem


def references(c, value):
    """Task ids anywhere in a structured reference or payload, including nested lists."""
    found = set()
    if isinstance(value, str):
        if value.startswith("task:"):
            value = value[5:]
        if c.execute("SELECT 1 FROM tasks WHERE id=?", (value,)).fetchone():
            found.add(value)
        for ident in re.findall(r"(?:#/task/|/tasks/)([a-zA-Z0-9_-]+)", value):
            if c.execute("SELECT 1 FROM tasks WHERE id=?", (ident,)).fetchone():
                found.add(ident)
    elif isinstance(value, dict):
        for item in value.values():
            found.update(references(c, item))
    elif isinstance(value, (list, tuple)):
        for item in value:
            found.update(references(c, item))
    return found


def message_tasks(c, message, seen=None, include_run=True):
    if not message:
        return set()
    message = dict(message)
    seen = set() if seen is None else seen
    mid = message.get("id")
    if mid in seen:
        return set()
    if len(seen) >= 100:
        # An unbounded reply chain is an unsupported provenance path.
        raise Problem("privacy", "Message provenance is too deep to authorize", 403)
    seen.add(mid)
    if mid:
        message = H.message(c, mid) or message
    conv = H.conversation(c, message["conversation_id"]) if message.get("conversation_id") else None
    refs = message.get("refs") or H._json(message.get("refs_json"), {}) or {}
    ids = references(c, refs)
    for key in ("answers", "inputs"):
        for mid in refs.get(key, []) if isinstance(refs.get(key), list) else []:
            if isinstance(mid, str):
                ids.update(message_tasks(c, H.message(c, mid), seen, include_run=False))
    tid = H.message_task_id(message, conv)
    if tid and H.task(c, tid):
        ids.add(tid)
    if message.get("in_reply_to"):
        ids.update(message_tasks(c, H.message(c, message["in_reply_to"]), seen, include_run=False))
    if include_run and refs.get("turn_id"):
        ids.update(attempt_tasks(c, refs["turn_id"]))
    return ids


def attempt_tasks(c, aid):
    ids = set()
    for row in c.execute("SELECT m.* FROM attempts a JOIN jobs j ON j.id=a.job_id "
                         "JOIN messages m ON m.id=j.message_id WHERE a.id=? UNION "
                         "SELECT m.* FROM attempt_inputs i JOIN messages m ON m.id=i.message_id "
                         "WHERE i.attempt_id=?", (aid, aid)):
        ids.update(message_tasks(c, row, include_run=False))
    ids.update(r[0] for r in c.execute("SELECT id FROM tasks WHERE carried_by=?", (aid,)))
    return ids


def readable(c, actor, ids):
    return all(H.task_private_readable(c, actor, H.task(c, tid)) for tid in ids)


def message_readable(c, actor, message):
    if not message:
        return False
    message = dict(message)
    message = H.message(c, message.get("id")) or message
    if message.get("deleted_at") or message.get("deleted"):
        return False
    try:
        return readable(c, actor, message_tasks(c, message))
    except Problem:
        return False


def require_message(c, who, message):
    if not message_readable(c, who.actor, message):
        raise Problem("not_found", "Message not found", 404)
    return message


def page(c, who, cid, *, before=None, since=None, limit=200, task_id=None):
    """Paginate visible rows, so hidden rows cannot leak cursors or counts."""
    clauses, args = ["conversation_id=?"], [cid]
    if before:
        anchor = c.execute("SELECT rowid,* FROM messages WHERE id=? AND conversation_id=?", (before, cid)).fetchone()
        if not anchor or not message_readable(c, who.actor, anchor):
            raise Problem("cursor", "Message cursor is unavailable", 422)
        clauses.append("rowid<?")
        args.append(anchor["rowid"])
    if since:
        clauses.append("created>?")
        args.append(since)
    visible = []
    for row in c.execute("SELECT * FROM messages WHERE " + " AND ".join(clauses) + " ORDER BY rowid DESC", args):
        if not message_readable(c, who.actor, row):
            continue
        if task_id and task_id not in message_tasks(c, row):
            continue
        visible.append({**dict(row), "refs": H._json(row["refs_json"], {}) or {}})
        if len(visible) > limit:
            break
    more = len(visible) > limit
    messages = list(reversed(visible[:limit]))
    return {"messages": messages, "has_more": more,
            "next_before": messages[0]["id"] if more and messages else None}


def require_payload(c, who, payload, actor=None):
    """Cached writes are reads too; a stored response cannot restore revoked access."""
    actor = actor or who.actor
    if who.role == "runner" and isinstance(payload, dict) and actor == who.actor:
        attempt = payload.get("attempt")
        if isinstance(attempt, dict) and attempt.get("bot"):
            actor = "bot:" + attempt["bot"]
    if not readable(c, actor, references(c, payload)):
        raise Problem("privacy", "This response contains a task you can no longer read", 403)
    if isinstance(payload, dict):
        key = payload.get("key")
        if isinstance(key, str) and key.startswith("report:") and not message_readable(c, actor, H.message(c, key[7:])):
            raise Problem("privacy", "This report is no longer available", 403)
        for key in ("items_json", "responses_json", "refs_json"):
            if isinstance(payload.get(key), str):
                require_payload(c, who, H._json(payload[key], {}) or {}, actor)
        if payload.get("attempt_id") and not attempt_readable(c, actor, payload["attempt_id"]):
            raise Problem("privacy", "This execution is no longer available", 403)
        if payload.get("conversation_id") and payload.get("id") and not message_readable(c, actor, payload):
            raise Problem("privacy", "This message is no longer available", 403)
        for value in payload.values():
            if isinstance(value, (dict, list)):
                require_payload(c, who, value, actor)
    elif isinstance(payload, list):
        for value in payload:
            if isinstance(value, (dict, list)):
                require_payload(c, who, value, actor)
    return payload


def attempt_readable(c, actor, aid):
    try:
        return readable(c, actor, attempt_tasks(c, aid))
    except Problem:
        return False


def require_attempt(c, who, aid):
    if not attempt_readable(c, who.actor, aid):
        raise Problem("not_found", "Turn not found", 404)


def private_execution(c, who):
    return bool(who.attempt_id and any(H.task_private(c, H.task(c, tid))
                                     for tid in attempt_tasks(c, who.attempt_id)))


def public_message(c, message):
    """External channel audiences have no task participant authority."""
    if not message or dict(message).get("deleted_at") or dict(message).get("deleted"):
        return False
    try:
        return not any(H.task_private(c, H.task(c, tid)) for tid in message_tasks(c, message))
    except Problem:
        return False


def require_batch(c, who, row):
    if row:
        require_payload(c, who, H._json(row["items_json"], []) or [])
        if row.get("message_id"):
            require_message(c, who, H.message(c, row["message_id"]))


def content_readable(c, actor, payload):
    return readable(c, actor, references(c, payload))


def guard_write(c, who, path):
    """A private execution has no automatic company-publication capability."""
    if who.role != "bot" or not private_execution(c, who):
        return
    if path in ("/api/v2/sql", "/api/v2/mcp", "/api/v2/tasks/dry-run"):
        return
    if path.startswith(("/api/v2/attempts/", "/api/v2/jobs/", "/api/v2/files/", "/api/v2/messages",
                        "/api/v2/conversations/", "/api/v2/chat/", "/api/v2/tasks")):
        task_path = re.fullmatch(r"/api/v2/tasks/([^/]+)(?:/.*)?", path)
        if task_path and task_path[1] not in ("dry-run", "labels", "stuck"):
            row = H.task(c, task_path[1])
            if row and not H.task_private(c, row):
                raise Problem("privacy", "Private task work cannot write company-visible tasks", 403)
            if row:
                require_destination(c, who, row["owner"], row["conversation_id"], {"task": row["id"]})
        return
    if path.endswith(("/status", "/usage")) or path == "/api/v2/status":
        return
    raise Problem("privacy", "Private task work cannot publish into company-wide resources", 403)


def require_destination(c, who, to, conversation_id, refs, reply=None):
    ids = references(c, refs)
    ids.update(message_tasks(c, reply) if reply else ())
    if who.attempt_id:
        ids.update(attempt_tasks(c, who.attempt_id))
    private = [H.task(c, tid) for tid in ids if H.task_private(c, H.task(c, tid))]
    if not private:
        return
    conv = H.conversation(c, conversation_id) if conversation_id else None
    audience = set((conv or {}).get("participants") or []) | {who.actor, to}
    for row in private:
        if not all(H.task_private_readable(c, actor, row) for actor in audience):
            raise Problem("privacy", "Private task content stays with its requester and current owner", 403)
    if (conv or {}).get("scope") == "shared":
        raise Problem("privacy", "Discuss private tasks in their task conversation", 403)


def status(c, who, row):
    """Free-form focus/results can contain task content; hide it when provenance is lost."""
    if not row:
        return row
    row = dict(row)
    tid = row.get("task_id")
    task = H.task(c, tid) if tid else None
    private = [task] if task and H.task_private(c, task) else []
    if not tid:
        private = [dict(r) for r in c.execute("SELECT * FROM tasks WHERE owner=? OR requester=?",
                                             ("bot:" + row["bot"], "bot:" + row["bot"]))
                   if H.task_private(c, dict(r))]
    if any(not H.task_private_readable(c, who.actor, t) for t in private):
        row.update(task_id=None, focus="", last_result="", reason="")
    tasks = [dict(t) for t in c.execute("SELECT * FROM tasks WHERE owner=? OR requester=?",
                                        ("bot:" + row["bot"], "bot:" + row["bot"]))
             if H.task_private_readable(c, who.actor, dict(t))]
    if "open_tasks" in row:
        row["open_tasks"] = sum(t["owner"] == "bot:" + row["bot"] and t["status"] in H.ACTIVE_STATUSES for t in tasks)
    if "needs_human" in row:
        row["needs_human"] = sum(t["requester"] == "bot:" + row["bot"] and H.is_human(t["owner"])
                                 and t["status"] in H.ACTIVE_STATUSES for t in tasks)
    return row


def job_count(c, who, bot, states=("queued",)):
    marks = ",".join("?" * len(states))
    return sum(message_readable(c, who.actor, row) and
               (not row["attempt_id"] or attempt_readable(c, who.actor, row["attempt_id"]))
               for row in c.execute("SELECT m.*,j.attempt_id FROM jobs j JOIN messages m ON m.id=j.message_id "
                                    f"WHERE j.bot=? AND j.state IN ({marks})", (bot, *states)))


def blob_readable(c, actor, bid):
    """A task attachment cannot regain access through uploader ownership or another link."""
    ids = {r[0] for r in c.execute("SELECT task_id FROM task_assets WHERE blob_id=?", (bid,))}
    for row in c.execute("SELECT f.task_id,f.scope,v.attempt_id FROM bot_files f "
                         "JOIN bot_file_versions v ON v.file_id=f.id WHERE v.blob_id=? "
                         "OR v.poster_blob_id=? OR v.thumb_blob_id=?", (bid, bid, bid)):
        if row["task_id"]:
            ids.add(row["task_id"])
        if row["scope"].startswith("task:"):
            ids.add(row["scope"][5:])
        if row["attempt_id"]:
            ids.update(attempt_tasks(c, row["attempt_id"]))
    for row in c.execute("SELECT m.* FROM message_assets a JOIN messages m ON m.id=a.message_id "
                         "WHERE a.blob_id=?", (bid,)):
        if not message_readable(c, actor, row):
            return False
    return readable(c, actor, ids)


def event_readable(c, actor, event):
    event = dict(event)
    ids = references(c, H._json(event.get("detail_json"), {}) or {})
    target = event.get("target")
    if H.task(c, target):
        ids.add(target)
    msg = H.message(c, target)
    if msg and not message_readable(c, actor, msg):
        return False
    if c.execute("SELECT 1 FROM attempts WHERE id=?", (target,)).fetchone():
        ids.update(attempt_tasks(c, target))
    # Tool/audit events from a private execution often have no explicit task ref.
    if H.is_bot(event.get("actor")):
        for row in c.execute("SELECT id FROM attempts WHERE bot=? AND created<=? "
                             "AND coalesce(finished,?)>=?", (H.actor_id(event["actor"]),
                                                            event["ts"], H.now(), event["ts"])):
            ids.update(attempt_tasks(c, row[0]))
    return readable(c, actor, ids)
