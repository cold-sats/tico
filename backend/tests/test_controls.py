from backend.tests.test_api import api, claim, expire, get, headers, post, setup_attempt


def test_drain_finishes_current_run_but_does_not_claim_more_work(api):
    r, _, a = setup_attempt(api)
    post(api, f"attempts/{a['id']}/started", {"thread_id": "current"}, r["token"])
    post(api, "bots/ops/control", {"action": "drain", "expected_revision": 1})
    post(api, "chat/ops", {"text": "Saved while draining"})
    post(api, f"attempts/{a['id']}/complete", {"outcome": "completed", "last_seq": 0}, r["token"])
    assert claim(api, r) is None
    post(api, "bots/ops/control", {"action": "resume", "expected_revision": 2})
    assert claim(api, r)


def test_pause_fences_current_credential_even_after_resume(api):
    r, _, a = setup_attempt(api)
    post(api, f"attempts/{a['id']}/started", {"thread_id": "current"}, r["token"])
    post(api, "bots/ops/control", {"action": "pause", "expected_revision": 1})
    get(api, "me", a["token"], expected=409)
    post(api, "bots/ops/control", {"action": "resume", "expected_revision": 2})
    get(api, "me", a["token"], expected=409)
    assert claim(api, r) is None  # Interrupted external effects still require reconciliation.


def test_clear_only_resets_requesting_person_and_preserves_history(api):
    r, msg, a = setup_attempt(api)
    path = "/api/employees/ops/session/clear"
    assert api.post(path, json={}, headers=headers()).status_code == 409
    post(api, f"attempts/{a['id']}/started", {"thread_id": "old-thread"}, r["token"])
    post(api, f"attempts/{a['id']}/complete", {"outcome": "completed", "last_seq": 0, "text": "Old context"}, r["token"])
    assert api.post(path, json={}, headers=headers()).status_code == 200
    new = post(api, "chat/ops", {"text": "A fresh request"})
    replacement = claim(api, r)
    assert [m["body"] for m in replacement["history"]] == ["A fresh request"]
    history = get(api, f"conversations/{msg['conversation_id']}/messages")
    assert len(history) == 3 and new["conversation_id"] == msg["conversation_id"]


def test_a_message_held_by_an_update_says_so_plainly_and_status_shows_the_update(api):
    # Ana, 2026-09-27: "what does Saved — bot is draining for maintenance mean?"
    from backend.store import H
    with api.app.state.store.transaction() as c:
        c.execute("INSERT INTO bot_control VALUES('ops',1) ON CONFLICT(bot) DO UPDATE SET draining=1")
        H.event(c, "system:deploy", "bot.drain", "ops", {"release": "r1"})
    msg = post(api, "chat/ops", {"text": "Held by the update"})
    snap = get(api, f"conversations/{msg['conversation_id']}/snapshot")
    assert snap["execution"]["label"] == "Saved — Tico is updating; this starts when the update finishes"
    updating = get(api, "status")["updating"]
    assert updating and updating["bots"] == 1
    # A person's drain is a pause, not an update.
    with api.app.state.store.transaction() as c:
        H.event(c, "human:ana", "bot.drain", "ops", {})
    snap = get(api, f"conversations/{msg['conversation_id']}/snapshot")
    assert snap["execution"]["label"] == "Saved — this bot is paused; this starts when it's resumed"
    assert get(api, "status")["updating"] is None
