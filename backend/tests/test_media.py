from backend.tests.test_api import api, assign, claim, get, headers, post, ready, runner  # noqa: F401


def media_post(api, path, body=None, token="ana-test", key=None, expected=200, **kwargs):
    response = api.post("/api/" + path, json=body, headers=headers(token, key), **kwargs)
    assert response.status_code == expected, response.text
    return response.json()


def import_meeting(api, token="ana-test", expected=200, **fields):
    """A finished meeting of the caller's, filed through the import API."""
    body = {"title": "Pricing call", "transcript": "Ana: We agreed to ship on Friday.", **fields}
    response = api.post("/api/v2/meetings/import", json=body, headers=headers(token))
    assert response.status_code == expected, response.text
    return response.json()


def test_a_meeting_sent_to_a_bot_becomes_its_task_and_delete_is_recoverable(api):
    rid = import_meeting(api)["id"]
    sent = media_post(api, "meetings/" + rid + "/send", {"slug": "coo"})
    assert sent["slug"] == "coo" and not sent["pending"]
    tasks = get(api, "tasks")["tasks"]
    assert len(tasks) == 1 and tasks[0]["owner"] == "bot:coo" and "ship on Friday" in tasks[0]["body"]
    deleted = media_post(api, "meetings/" + rid + "/delete", {})
    assert deleted["recoverable"]
    assert api.get("/api/meetings/" + rid, headers=headers()).status_code == 404
    with api.app.state.store.read() as c:
        assert c.execute("SELECT count(*) FROM meetings WHERE id=?", (rid,)).fetchone()[0] == 1


def test_auto_delivery_still_reaches_the_assistant_nobody_chats_with(api):
    """With no bot of their own, a person's note goes to the assistant as a task, though its
    chat was retired (2026-09-24)."""
    note = media_post(api, "notes", {"text": "Call the plumber back"}, "ben-test")
    sent = media_post(api, "meetings/" + note["id"] + "/send", {"slug": "auto"}, "ben-test")
    assert sent["slug"] == "coo" and sent["task"]
    task = get(api, "tasks/" + sent["task"], "ben-test")["task"]
    assert task["owner"] == "bot:coo" and task["requester"] == "human:ben"
    post(api, "chat/coo", {"text": "Did you get it?"}, "ben-test", expected=403)


def test_a_private_meeting_reaches_its_participants_and_nobody_else(api):
    invited = import_meeting(api, "ben-test", title="Comp review", private=True,
                             participants=["Cara@Acme.example"])["id"]
    elsewhere = import_meeting(api, "cara-test", title="Board prep", private=True,
                               participants=["ana@acme.example"])["id"]
    # The spelling in the participant list is not the spelling in the roster; the match ignores case.
    assert api.get("/api/meetings/" + invited, headers=headers("cara-test")).json()["can_edit"] is False
    assert api.get("/api/meetings/" + elsewhere, headers=headers("ben-test")).status_code == 403
    assert [r["id"] for r in api.get("/api/meetings", headers=headers("ben-test")).json()] == [invited]
    assert sorted(r["id"] for r in api.get("/api/meetings", headers=headers()).json()) == sorted([invited, elsewhere])
