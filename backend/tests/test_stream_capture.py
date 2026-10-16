from backend.tests.test_api import api, assign, claim, get, post, ready, setup_attempt


def turn_on(api, bot, token="ana-test", expected=200):
    revision = next(b for b in get(api, "bots") if b["slug"] == bot)["revision"]
    return post(api, f"bots/{bot}/definition", {"capture_stream": "on", "expected_revision": revision}, token,
                expected=expected)


def test_a_captured_stream_is_kept_masked_and_read_only_by_owners_and_engineering_bots(api):
    r, _, a = setup_attempt(api)
    post(api, f"attempts/{a['id']}/started", {"thread_id": "thread"}, r["token"])
    stream = {"provider": "claude", "frames": '{"dir":"start","provider":"claude","ms":0}\n'
              '{"dir":"in","ms":5,"frame":{"type":"assistant","text":"key sk-ant-api03-abcdefghijklmnop"}}\n'
              '{"dir":"out","ms":9,"frame":{"type":"user","text":"my pin is odd-shaped-pin-77"}}'}
    # Off by default: a runner cannot hand one in for a bot that does not capture.
    post(api, f"attempts/{a['id']}/capture", stream, r["token"], expected=409)
    # Only an owner turns it on.
    turn_on(api, "ops", "ben-test", expected=403)
    turn_on(api, "ops")
    post(api, f"attempts/{a['id']}/capture", stream, r["token"])
    # A bot outside engineering is refused; an engineering bot reads it (here, from its own live run).
    with api.app.state.store.transaction() as c:
        c.execute("UPDATE bot_config SET team='marketing' WHERE bot='ops'")
    get(api, f"attempts/{a['id']}/capture", a["token"], expected=403)
    with api.app.state.store.transaction() as c:
        c.execute("UPDATE bot_config SET team='engineering' WHERE bot='ops'")
    assert get(api, f"attempts/{a['id']}/capture", a["token"])["attempt"]["id"] == a["id"]
    post(api, f"attempts/{a['id']}/complete", {"outcome": "completed", "text": "done", "last_seq": 0}, r["token"])

    # A secret taken out after the run leaves its raw stream too.
    from backend.auth import Identity
    from backend.credential_cards import redact_value
    with api.app.state.store.transaction() as c:
        redact_value(c, Identity("human:ana", "owner", "ana@acme.example"), "odd-shaped-pin-77", "PIN",
                     attempt_id=a["id"])
    found = get(api, f"attempts/{a['id']}/capture")
    assert found["provider"] == "claude" and found["input"]["message"]["body"] == "Please summarize the current work."
    assert "sk-ant-api03" not in found["transcript"] and "••••" in found["transcript"]
    assert "odd-shaped-pin-77" not in found["transcript"] and "saved as PIN" in found["transcript"]
    assert found["output"]["final_text"] == "done"
    # A person who is not an owner is refused.
    get(api, f"attempts/{a['id']}/capture", "ben-test", expected=403)
    # Kept a week, then gone.
    with api.app.state.store.transaction() as c:
        c.execute("UPDATE attempt_captures SET created='2000-01-01T00:00:00Z'")
    get(api, f"attempts/{a['id']}/capture", expected=404)


def test_a_hidden_run_is_refused_and_a_secret_removed_mid_run_or_capture_off_leaves_nothing(api):
    r, msg, a = setup_attempt(api)
    post(api, f"attempts/{a['id']}/started", {"thread_id": "thread"}, r["token"])
    turn_on(api, "ops")
    stream = {"provider": "claude", "frames": '{"dir":"out","ms":1,"frame":{"text":"Please summarize the current work."}}'}
    post(api, f"attempts/{a['id']}/capture", stream, r["token"])
    # An engineering bot whose run list hides this run (another person's chat with ops) cannot read its stream.
    assign(api, r, "finance")
    ready(api, r, ["ops", "finance"])
    post(api, "chat/finance", {"text": "Check the numbers"})
    finance = claim(api, r, "finance")
    with api.app.state.store.transaction() as c:
        c.execute("UPDATE bot_config SET team='engineering' WHERE bot='finance'")
    assert get(api, "bots/ops/turns", finance["token"]) == []
    assert api.get(f"/api/v2/attempts/{a['id']}/capture",
                   headers={"Authorization": "Bearer " + finance["token"]}).status_code in (403, 404)
    # Turning capture off deletes what was kept.
    revision = next(b for b in get(api, "bots") if b["slug"] == "ops")["revision"]
    post(api, "bots/ops/definition", {"capture_stream": "off", "expected_revision": revision})
    get(api, f"attempts/{a['id']}/capture", expected=404)
    # A span the person takes out while the run is going: the stream handed in afterwards is not kept.
    turn_on(api, "ops")
    post(api, f"messages/{msg['id']}/redact", {"span": "summarize the current", "label": "removed"})
    assert post(api, f"attempts/{a['id']}/capture", stream, r["token"])["kept"] is False
    get(api, f"attempts/{a['id']}/capture", expected=404)


def test_a_fixture_is_written_in_three_parts(tmp_path):
    from clients.hubtools import write_fixture
    found = {"attempt": {"id": "../a1"}, "provider": "Claude", "truncated": False, "dropped_bytes": 0,
             "captured": "2026-10-16T00:00:00Z", "input": {"message": {"body": "hi"}, "config": {}},
             "transcript": '{"dir":"out"}\n{"dir":"in"}', "output": {"events": [], "result": {}, "final_text": ""}}
    written = write_fixture(found, tmp_path)
    assert sorted(p.split("/")[-1] for p in written) == ["claude_transcript.ndjson", "input.json", "output.json"]
    assert all(p.startswith(str(tmp_path / "replay-a1")) for p in written)
    assert (tmp_path / "replay-a1" / "claude_transcript.ndjson").read_text().count("\n") == 2
