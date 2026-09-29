from backend.tests.test_api import api, assign, claim, get, post, ready, runner, setup_attempt, expire


def test_interrupted_steered_question_is_not_silently_completed(api):
    r, _, a = setup_attempt(api)
    post(api, f"attempts/{a['id']}/started", {"thread_id": "thread"}, r["token"])
    # A second bot asks while COO is active.
    assign(api, r, "finance")
    ready(api, r, ["ops", "finance"])
    post(api, "chat/finance", {"text": "Ask COO"})
    finance = claim(api, r)
    q = post(api, "messages", {"to": "ops", "kind": "ask", "text": "Any update?", "wait_s": 60}, finance["token"])
    post(api, f"attempts/{a['id']}/inputs", {}, r["token"])
    expire(api, a["id"])
    with api.app.state.store.transaction() as c:
        api.app.state.execution.expire(c)
        state = c.execute("SELECT state FROM jobs WHERE message_id=?", (q["id"],)).fetchone()[0]
    assert state == "uncertain"


def test_plain_message_from_another_conversation_does_not_interrupt_running_turn(api):
    r, _, active = setup_attempt(api)
    post(api, f"attempts/{active['id']}/started", {"thread_id": "thread"}, r["token"])
    assign(api, r, "finance")
    ready(api, r, ["ops", "finance"])
    post(api, "chat/finance", {"text": "Send COO a separate update"})
    finance = claim(api, r)
    update = post(api, "messages", {"to": "ops", "kind": "say", "text": "Separate FYI"}, finance["token"])

    assert post(api, f"attempts/{active['id']}/inputs", {}, r["token"])["messages"] == []
    with api.app.state.store.read() as c:
        assert c.execute("SELECT state FROM jobs WHERE message_id=?", (update["id"],)).fetchone()[0] == "queued"
