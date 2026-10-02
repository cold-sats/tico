"""Structured reviews use the existing task ask/answer messages and wake path."""
from .store import H, Problem, encode


def comment_rights(c, auth, who, task_id):
    row = auth.task(c, who, task_id)
    others = [a for a in dict.fromkeys([row["owner"], row["requester"], H.task_origin(c, row)])
              if a and a not in (who.actor, H.KEEPER)]
    target = next((a for a in others if H.is_bot(a)), None)
    if target and who.actor != row["owner"]:
        auth.require_write(c, who, H.actor_id(target))
    if target:
        auth.require_bot_contact(c, who, target, task_id=task_id, kind="comment")
    return row


def file_version(c, task_id, fid, number):
    row = c.execute("SELECT v.* FROM bot_file_versions v JOIN bot_files f ON f.id=v.file_id "
                    "WHERE f.task_id=? AND v.file_id=? AND v.version=?", (task_id, fid, number)).fetchone()
    if row:
        return dict(row)
    # Legacy attachments are v1 without rewriting old data.
    if number == 1:
        row = c.execute("SELECT b.* FROM blobs b JOIN task_assets a ON a.blob_id=b.id "
                        "WHERE a.task_id=? AND b.id=?", (task_id, fid)).fetchone()
        if row:
            return {**dict(row), "actor": row["owner"], "mime": row["content_type"], "version": 1}
    raise Problem("not_found", "File version not found on this task", 404)


def check_ask(c, task_id, ask, auth, who):
    if not ask:
        return None
    value = ask.model_dump(exclude_none=True)
    value["who"] = ask.who
    if ask.who:
        target = H.resolve_actor(c, ask.who)
        if not H.bot(c, H.actor_id(target)) and not H.human(c, H.actor_id(target)):
            raise Problem("validation", "Question recipient not found", 422)
        if H.is_bot(target):
            row = H.task(c, task_id)
            if target not in (row["owner"], row["requester"], H.task_origin(c, row)):
                auth.require_write(c, who, H.actor_id(target))
            auth.require_bot_contact(c, who, target, task_id=task_id, kind="comment")
    for question in ask.questions:
        for option in question.options:
            if option.file:
                fid, number = option.file.rsplit("@", 1)
                file_version(c, task_id, fid, int(number))
    return value


def version_review(c, fid, number):
    row = c.execute("SELECT * FROM task_file_reviews WHERE file_id=? AND version=?", (fid, number)).fetchone()
    asked = H.message(c, row["ask_message_id"]) if row and row["ask_message_id"] else None
    return {"note": row["note"] if row else None, "comment_id": row["comment_id"] if row else None,
            "ask": {k: asked["refs"].get(k) for k in ("questions", "who")} if asked else None,
            "answers": H.review_answers(c, asked["id"]) if asked else []}


def edit_version(c, auth, who, task_id, fid, number, body):
    auth.task(c, who, task_id)
    if body.ask is not None:
        comment_rights(c, auth, who, task_id)
    version = file_version(c, task_id, fid, number)
    if version["actor"] != who.actor:
        raise Problem("forbidden", "Only whoever added this version may edit its note or question", 403)
    value = check_ask(c, task_id, body.ask, auth, who)
    current = version_review(c, fid, number)
    c.execute("INSERT OR IGNORE INTO task_file_reviews(file_id,version) VALUES(?,?)", (fid, number))
    if "note" in body.model_fields_set:
        c.execute("UPDATE task_file_reviews SET note=? WHERE file_id=? AND version=?", (body.note, fid, number))
    if "ask" in body.model_fields_set:
        existing = c.execute("SELECT ask_message_id FROM task_file_reviews WHERE file_id=? AND version=?",
                             (fid, number)).fetchone()[0]
        if existing:
            if value is None or value == current["ask"]:
                return version_review(c, fid, number)
            if H.answers_to(c, [existing]):
                raise Problem("validation", "This version's question was answered; attach a new version for another review", 422)
            asked = H.message(c, existing)
            row = H.task(c, task_id)
            recipient = H.resolve_actor(c, value.get("who") or row["requester"])
            c.execute("UPDATE messages SET refs_json=?,to_actor=? WHERE id=?",
                      (encode({**asked["refs"], **value}), recipient, existing))
            return version_review(c, fid, number)
        if value:
            msg = H.task_comment(c, who.actor, task_id, body.note or f'Review "{version["name"]}" v{number}.',
                                 ask=value, extra_refs={"target": {"file": fid, "version": number}})
            c.execute("UPDATE task_file_reviews SET ask_message_id=? WHERE file_id=? AND version=?",
                      (msg["id"], fid, number))
    return version_review(c, fid, number)


def answer_task(c, auth, who, task_id, body, wake):
    comment_rights(c, auth, who, task_id)
    target = body.target.model_dump(exclude_none=True)
    version = None
    if body.target.comment:
        asked = H.message(c, body.target.comment)
        if not asked or H.message_task_id(asked, H.conversation(c, asked["conversation_id"])) != task_id:
            raise Problem("not_found", "Question not found on this task", 404)
        if (asked.get("refs") or {}).get("target"):
            raise Problem("validation", "Use the file and version target for a file question", 422)
    else:
        version = file_version(c, task_id, body.target.file, body.target.version)
        review = c.execute("SELECT ask_message_id FROM task_file_reviews WHERE file_id=? AND version=?",
                           (body.target.file, body.target.version)).fetchone()
        asked = H.message(c, review[0]) if review and review[0] else None
    if not asked or asked["kind"] != "ask" or not asked["refs"].get("questions"):
        raise Problem("validation", "The target has no structured question", 422)
    if asked["from_actor"] == who.actor:
        raise Problem("forbidden", "The asker cannot answer their own question", 403)
    questions = {q["id"]: q for q in asked["refs"]["questions"]}
    if body.dismiss:
        if body.answers or body.other:
            raise Problem("validation", "Dismiss does not include answers or other text", 422)
    else:
        if set(body.answers) - set(questions):
            raise Problem("validation", "Unknown question id", 422)
        if set(body.answers) != set(questions):
            raise Problem("validation", "Answer every question", 422)
        for qid, question in questions.items():
            labels = body.answers[qid]
            allowed = {o["label"] for o in question["options"]}
            if len(set(labels)) != len(labels) or set(labels) - allowed or (not question["multi"] and len(labels) > 1):
                raise Problem("validation", "Choose valid labels for each question", 422)
            if not labels and not (body.other and question["other"]):
                raise Problem("validation", "Choose an option or supply an allowed other answer", 422)
        # Other text is allowed when at least one question offers a free-text answer.
        if body.other and not any(q["other"] for q in questions.values()):
            raise Problem("validation", "Other text is not allowed for this question", 422)
    by = H.human(c, H.actor_id(who.actor)) if H.is_human(who.actor) else H.bot(c, H.actor_id(who.actor))
    name = (by or {}).get("name") or H.actor_id(who.actor)
    subject = f'"{version["name"]}" v{body.target.version}' if version else "the question"
    if body.dismiss:
        text = f"{name} dismissed the question on {subject}." if version else f"{name} dismissed the question."
    elif version and len(questions) == 1 and list(body.answers.values()) == [["Approve"]]:
        text = f"{name} approved {subject}."
    else:
        text = " ".join(f'{name} answered "{q["question"]}": {", ".join(body.answers[qid]) or "Other"}.'
                         for qid, q in questions.items())
        if version:
            text += f" File: {subject}."
    if body.other:
        text += " " + body.other
    value = {"target": target, "answers": body.answers, "other": body.other, "dismiss": body.dismiss,
             "by": who.actor, "at": H.now()}
    msg = H.task_comment(c, who.actor, task_id, text, wake=wake,
                         extra_refs={"answer": value}, answer_to=asked["id"])
    return {"comment": {**msg, "answer": value}, "answer": value,
            "comments": H.task_comments(c, task_id), "woke": bool(wake)}
