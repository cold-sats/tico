"""Task reviews retain the existing ask/answer protocol and legacy attachment path."""
import json

import pytest

from backend.tests.test_api import api, assign, claim, headers, post, ready, restrict, runner  # noqa: F401
from backend.store import H
from clients.task_review import ask_from_args
from clients.hubcli import parser
from runner.service import Runner


def task(api, title="Review the draft"):
    return post(api, "tasks", {"owner": "ops", "title": title, "body": "Read the report."})["id"]


def ask(who=None, other=True):
    return {"questions": [{"id": "verdict", "header": "Review", "question": "Is this ready?",
                           "options": [{"label": "Approve"}, {"label": "Request changes"}], "other": other}], "who": who}


def attach(api, tid, name="report.md", **fields):
    return post(api, f"tasks/{tid}/files", {"name": name, "text": "# Report", **fields})


def get(api, path, who="ana-test"):
    response = api.get("/api/v2/" + path, headers=headers(who))
    assert response.status_code == 200, response.text
    return response.json()


def test_version_names_scopes_archive_and_author_edits(api):
    tid = task(api)
    first = attach(api, tid, note="Draft")
    second = attach(api, tid, note="Revised")
    assert first["file_id"] == second["file_id"] and (first["version"], second["version"]) == (1, 2)
    separate = attach(api, task(api, "Review another draft"))
    assert separate["file_id"] != first["file_id"]
    fid = first["file_id"]
    versions = get(api, f"tasks/{tid}/files")["files"][0]["versions"]
    assert [v["n"] for v in versions] == [2, 1] and versions[0]["note"] == "Revised"
    assert all(k in versions[0] for k in ("width", "height", "duration_ms", "media_state", "poster_url", "thumb_url"))
    assert api.get(versions[1]["url"], headers=headers()).content == b"# Report"
    path = f"/api/v2/files/{fid}/versions/2"
    assert api.patch(path, json={"note": "Changed", "ask": ask()}, headers=headers()).status_code == 200
    assert api.patch(path, json={"note": "No"}, headers=headers("cara-test")).status_code == 403
    assert api.patch(path, json={"note": "x" * 501}, headers=headers()).status_code == 422
    assert api.patch(f"/api/v2/files/{fid}", json={"archived": True}, headers=headers()).status_code == 200
    assert attach(api, tid)["file_id"] != fid


def test_legacy_attachment_is_v1_and_adopted_without_rewriting(api):
    tid = task(api)
    from backend.auth import Identity
    from backend.blobs import register
    digest = api.app.state.blobs.put(b"old")
    with api.app.state.store.transaction() as c:
        old = register(c, Identity("human:ana", "owner"), digest, 3, "report.md", "text/markdown")
        c.execute("INSERT INTO task_assets VALUES(?,?)", (tid, old["id"]))
    listed = get(api, f"tasks/{tid}/files")["files"][0]
    assert listed["id"] == old["id"] and listed["versions"][0]["n"] == 1
    new = attach(api, tid)
    assert new["file_id"] == old["id"] and new["version"] == 2
    assert api.get(f"/api/v2/files/{old['id']}?v=1", headers=headers()).content == b"old"
    assert api.get(f"/api/v2/files/{old['id']}?v=2", headers=headers()).content == b"# Report"


@pytest.mark.parametrize("change", [
    {"extra": True}, {"questions": []}, {"questions": [{"id": "x", "header": "H", "question": "Q", "surprise": 1}]},
    {"questions": [{"id": "x" * 41, "header": "H", "question": "Q"}]},
    {"questions": [{"id": "x", "header": "H", "question": "Q", "multi": "yes"}]},
    {"questions": [{"id": "x", "header": "H", "question": "Q", "options": [{"label": "A", "oops": 1}]}]},
])
def test_ask_validation(api, change):
    tid = task(api)
    r = api.post(f"/api/v2/tasks/{tid}/comments", json={"text": "Review", "ask": {**ask(), **change}}, headers=headers())
    assert r.status_code == 422, r.text


def test_comments_answers_rights_validation_multiple_answers_and_needs_you(api):
    tid = task(api)
    question = post(api, f"tasks/{tid}/comments", {"text": "Which draft?", "ask": ask("ben")})["comment"]
    assert question["kind"] == "ask" and question["ask"]["who"] == "ben"
    assert get(api, f"tasks/{tid}")["task"]["open_asks"] == 1
    listing = get(api, "tasks")["tasks"]
    assert next(t for t in listing if t["id"] == tid)["open_asks"] == 1
    assert tid in [t["id"] for t in get(api, "needs-you", "ben-test")["items"]]
    body = {"target": {"comment": question["id"]}, "answers": {"verdict": ["Approve"]}}
    assert api.post(f"/api/v2/tasks/{tid}/answers", json=body, headers=headers()).status_code == 403
    with api.app.state.store.transaction() as c:
        restrict(c, "ops", read={"everyone": True}, write={"people": ["ana", "ben"]})
    assert api.post(f"/api/v2/tasks/{tid}/answers", json=body, headers=headers("cara-test")).status_code == 403
    with api.app.state.store.transaction() as c:
        restrict(c, "ops", everyone=True)
    for invalid in ({"verdict": ["Bogus"]}, {"missing": ["Approve"]}, {"verdict": ["Approve", "Request changes"]}):
        assert api.post(f"/api/v2/tasks/{tid}/answers", json={**body, "answers": invalid}, headers=headers("ben-test")).status_code == 422
    answer = post(api, f"tasks/{tid}/answers", body, "ben-test")
    assert answer["comment"]["kind"] == "answer" and 'answered "Is this ready?": Approve.' in answer["comment"]["body"]
    assert answer["comment"]["refs"]["answer"] == answer["answer"]
    post(api, f"tasks/{tid}/answers", {**body, "answers": {"verdict": ["Request changes"]}, "other": "Change the intro."}, "cara-test")
    comments = get(api, f"tasks/{tid}/comments")["comments"]
    assert len(next(m for m in comments if m["id"] == question["id"])["answers"]) == 2
    assert len(get(api, f"tasks/{tid}/answers")["answers"]) == 2
    assert get(api, f"tasks/{tid}")["task"]["open_asks"] == 0


def test_file_answer_wake_structured_and_plain_runner_path(api):
    tid = task(api)
    made = attach(api, tid, ask=ask(), note="Read this version")
    fid = made["file_id"]
    body = {"target": {"file": fid, "version": 1}, "answers": {"verdict": ["Approve"]}}
    # The author is Ana; another person with comment rights can answer.
    answer = post(api, f"tasks/{tid}/answers", body, "ben-test")
    assert 'approved "report.md" v1.' in answer["comment"]["body"]
    with api.app.state.store.read() as c:
        msg = H.message(c, answer["comment"]["id"])
        assert msg["to_actor"] == "bot:ops"
        assert c.execute("SELECT 1 FROM jobs WHERE message_id=?", (msg["id"],)).fetchone()
        question = c.execute("SELECT ask_message_id FROM task_file_reviews WHERE file_id=?", (fid,)).fetchone()[0]
        assert H.answers_to(c, [question])[question]["refs"]["answer"] == answer["answer"]
    prompt = Runner.__new__(Runner).prompt({"bot": "ops", "message": msg, "history": [], "conversation": {"id": "c"}})
    assert json.loads(next(line[8:] for line in prompt.splitlines() if line.startswith("answer: "))) == answer["answer"]
    assert msg["body"] in prompt  # old runners still receive the same readable body
    assert get(api, f"tasks/{tid}/files")["files"][0]["versions"][0]["answers"] == [answer["answer"]]
    assert api.patch(f"/api/v2/files/{fid}/versions/1", json={"ask": ask("ben")}, headers=headers()).status_code == 422


def test_multiple_open_asks_recipients_and_dismiss(api):
    tid = task(api)
    first = post(api, f"tasks/{tid}/comments", {"text": "First", "ask": ask("ben", False)})["comment"]
    second = post(api, f"tasks/{tid}/comments", {"text": "Second", "ask": ask("cara")})["comment"]
    assert tid in [t["id"] for t in get(api, "needs-you", "ben-test")["items"]]
    assert get(api, f"tasks/{tid}")["task"]["open_asks"] == 2
    body = {"target": {"comment": first["id"]}, "answers": {"verdict": ["Approve"]}, "other": "No"}
    assert api.post(f"/api/v2/tasks/{tid}/answers", json=body, headers=headers("ben-test")).status_code == 422
    post(api, f"tasks/{tid}/answers", {"target": {"comment": second["id"]}, "dismiss": True}, "ben-test")
    assert get(api, f"tasks/{tid}")["task"]["open_asks"] == 1
    assert next(t for t in get(api, "tasks")["tasks"] if t["id"] == tid)["open_asks"] == 1


def test_cli_choices_and_attach_options():
    args = parser().parse_args(["task", "comment", "t1", "Review", "--attach", "a.md", "--attach", "b.md", "--choices", "A,B"])
    assert args.attach == ["a.md", "b.md"]
    assert [o["label"] for o in ask_from_args(args)["questions"][0]["options"]] == ["A", "B"]
    args = parser().parse_args(["task", "attach", "t1", "a.md", "--note", "Draft", "--choices", "Approve,Request changes"])
    assert args.note == "Draft" and ask_from_args(args)["questions"][0]["id"] == "verdict"
    assert parser().parse_args(["task", "answers", "t1"]).fn == "task answers"


def test_comment_attachments_mcp_fields_and_version_edit(api):
    from backend.tests.test_mcp import call
    tid = task(api)
    error, made = call(api, "hub_task_attach", {"id": tid, "name": "report.md", "text": "Draft", "note": "First"})
    assert not error, made
    fid = made["file_id"]
    error, comment = call(api, "hub_task_comment", {"id": tid, "text": "Review this", "ask": ask("ben"),
                                                   "attachments": [fid + "@1"]})
    assert not error, comment
    assert comment["comment"]["refs"]["files"] == [fid + "@1"]
    assert comment["comment"]["refs"]["attachments"][0]["url"] == f"/api/v2/files/{fid}?v=1"
    assert get(api, f"tasks/{tid}/files")["files"][0]["versions"][0]["comment_id"] == comment["comment"]["id"]
    edited = api.patch(f"/api/v2/files/{fid}/versions/1", json={"ask": ask("ben")}, headers=headers())
    assert edited.status_code == 200, edited.text
    edited = api.patch(f"/api/v2/files/{fid}/versions/1", json={"ask": ask("cara")}, headers=headers())
    assert edited.status_code == 200 and edited.json()["ask"]["who"] == "cara"
    post(api, f"tasks/{tid}/answers", {"target": {"comment": comment["comment"]["id"]},
                                     "answers": {"verdict": ["Approve"]}}, "ben-test")
    error, answers = call(api, "hub_task_answers", {"id": tid})
    assert not error and len(answers["answers"]) == 1


def test_free_text_multi_validation_and_cross_task_targets(api):
    tid = task(api)
    free = {"questions": [{"id": "text", "header": "Draft", "question": "What should change?", "options": []}]}
    comment = post(api, f"tasks/{tid}/comments", {"text": "Review", "ask": free})["comment"]
    answer = post(api, f"tasks/{tid}/answers", {"target": {"comment": comment["id"]}, "answers": {"text": []},
                                             "other": "Tighten the intro."}, "ben-test")
    assert "Tighten the intro." in answer["comment"]["body"]
    multi = ask()
    multi["questions"][0]["multi"] = True
    comment = post(api, f"tasks/{tid}/comments", {"text": "Review", "ask": multi})["comment"]
    post(api, f"tasks/{tid}/answers", {"target": {"comment": comment["id"]},
                                     "answers": {"verdict": ["Approve", "Request changes"]}}, "ben-test")
    other_task = task(api, "Review another draft")
    assert api.post(f"/api/v2/tasks/{other_task}/answers", json={"target": {"comment": comment["id"]}, "dismiss": True},
                    headers=headers("ben-test")).status_code == 404
    assert api.post(f"/api/v2/tasks/{tid}/comments", json={"text": "Review", "ask": ask("unknown")},
                    headers=headers()).status_code == 422


def test_plain_ask_and_reply_still_close_through_existing_protocol(api):
    tid = task(api)
    with api.app.state.store.transaction() as c:
        question = H.task_ask(c, "bot:ops", tid, "Which format?")
    reply = post(api, f"tasks/{tid}/comments", {"text": "Markdown."})["comment"]
    with api.app.state.store.read() as c:
        assert H.answers_to(c, [question["id"]])[question["id"]]["id"] == reply["id"]
        assert H.unanswered_ask(c, H.task(c, tid)) is None
    assert get(api, f"tasks/{tid}")["task"]["open_asks"] == 0


def test_review_migration_keeps_existing_version_bytes(api):
    import sqlite3
    tid = task(api)
    fid = attach(api, tid)["file_id"]
    with api.app.state.store.read() as c:
        assert c.execute("PRAGMA user_version").fetchone()[0] == 21
        assert c.execute("SELECT 1 FROM cloud_migrations WHERE version=54").fetchone()
        with pytest.raises(sqlite3.IntegrityError, match="immutable"):
            c.execute("UPDATE bot_file_versions SET digest='changed' WHERE file_id=?", (fid,))


def test_cli_comment_uploads_use_distinct_retry_keys(tmp_path, monkeypatch):
    from clients import remotecli
    paths = [tmp_path / name for name in ("a.md", "b.md")]
    for path in paths:
        path.write_text("Draft")
    calls = []
    class Client:
        def __init__(self, *args, **kwargs):
            pass
        def get(self, path):
            return {"actor": "human:ana"}
        def post(self, path, body, key=None):
            calls.append((path, body, key))
            return {"file_id": "file-a", "version": len(calls)} if path.endswith("/files") else {"ok": True}
    monkeypatch.setattr(remotecli, "Client", Client)
    monkeypatch.setenv("HUB_API_URL", "https://example.com")
    monkeypatch.setenv("HUB_OPERATION_ID", "review-operation")
    args = parser().parse_args(["task", "comment", "t1", "Review", "--attach", str(paths[0]), "--attach", str(paths[1]),
                                "--choices", "A,B"])
    assert remotecli.run(args) == {"ok": True}
    assert len(set(c[2] for c in calls)) == 3
    assert calls[-1][1]["attachments"] == ["file-a@1", "file-a@2"]
    assert calls[-1][1]["ask"]["questions"][0]["options"] == [{"label": "A"}, {"label": "B"}]


def test_bot_version_answers_and_finished_tasks_stay_in_needs_you(api):
    tid = task(api)
    machine = runner(api)
    assign(api, machine, "ops")
    ready(api, machine, ["ops"])
    attempt = claim(api, machine, "ops")
    made = post(api, f"tasks/{tid}/files", {"name": "draft.md", "text": "Draft", "ask": ask()}, attempt["token"])
    assert get(api, f"tasks/{tid}")["task"]["open_asks"] == 1
    with api.app.state.store.transaction() as c:
        c.execute("UPDATE tasks SET status='done' WHERE id=?", (tid,))
    assert tid in [t["id"] for t in get(api, "needs-you")["items"]]
    body = {"target": {"file": made["file_id"], "version": 1}, "answers": {"verdict": ["Approve"]}}
    answer = post(api, f"tasks/{tid}/answers", body)
    assert answer["comment"]["body"] == 'Ana approved "draft.md" v1.'
    assert tid not in [t["id"] for t in get(api, "needs-you")["items"]]
