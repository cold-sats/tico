"""A person's Grok Bots synced in: placed under them, transcripts copied once, never dispatched to."""

from backend.store import H
from backend.tests.test_api import api, get, headers, post  # noqa: F401

GROK_ID = "4a7e880c-eb8e-49df-9789-3abfff190aa7"


def designer(**overrides):
    return {"grok_id": GROK_ID, "name": "Tico Designer", "description": "Designs Tico's pages.",
            "instructions": "You design Tico. Keep it plain.",
            "messages": [{"role": "user", "text": "Make the org chart calmer.", "at": "2026-09-27T10:00:00Z"},
                         {"role": "bot", "text": "Softer lines, fewer badges.", "at": "2026-09-27T10:01:00Z"}],
            **overrides}


def sync(api, *bots, token="ana-test", expected=200, source="Groky"):
    return post(api, "grokbot/sync", {"bots": list(bots), "source": source}, token=token, expected=expected)


def room_messages(api, slug):
    with api.app.state.store.read() as c:
        return [dict(r) for r in c.execute(
            "SELECT m.* FROM messages m JOIN conversations v ON v.id=m.conversation_id "
            "WHERE v.scope='personal' AND v.owner_actor='human:ana' AND v.room_key=? ORDER BY m.created", (slug,))]


def test_a_new_grok_bot_lands_under_the_person_with_its_history_and_instructions(api):
    out = sync(api, designer())
    [bot] = out["bots"]
    assert bot["created"] and bot["bot"] == "grok-designer" and bot["messages_added"] == 2
    assert bot["synced_through"].startswith("2026-09-27T10:01:00")
    row = next(b for b in get(api, "bots") if b["slug"] == "grok-designer")
    assert row["reports_to"] == "human:ana" and row["operator"] == "ana"
    assert row["display_name"] == "Grok Designer"          # "Tico Designer" in Grok
    with api.app.state.store.read() as c:
        config = H._json(c.execute("SELECT config_json FROM bot_config WHERE bot='grok-designer'").fetchone()[0], {})
        assert config["harness"] == "grokbot"
        assert config["grok"]["instructions"] == "You design Tico. Keep it plain."
        assert config["grok"]["source"] == "Groky"
        assert config["grok"]["name"] == "Tico Designer"      # its name in Grok, for rebuilding it
        # Copied history is read and quiet: no job for a runner, nothing unread.
        assert c.execute("SELECT count(*) FROM jobs WHERE bot='grok-designer'").fetchone()[0] == 0
    messages = room_messages(api, "grok-designer")
    assert [(m["from_actor"], m["body"]) for m in messages] == [
        ("human:ana", "Make the org chart calmer."), ("bot:grok-designer", "Softer lines, fewer badges.")]
    assert all(m["read_at"] for m in messages)


def test_the_same_name_from_two_grok_bots_gets_two_slugs_and_a_bot_cannot_sync(api):
    sync(api, designer(), designer(grok_id="other-grok-id", messages=[]))
    slugs = {b["slug"] for b in get(api, "bots")}
    assert {"grok-designer", "grok-designer-2"} <= slugs
    r = api.post("/api/v2/grokbot/sync", json={"bots": [designer()]}, headers=headers("cara-test"))
    assert r.status_code == 403


PNG = bytes.fromhex("89504e470d0a1a0a0000000d4948445200000001000000010806000000"
                    "1f15c4890000000d49444154789c6360000002000154a24f5d0000000049454e44ae426082")


def test_tico_fetches_only_public_https_images():
    from backend import grokbot as G
    assert G.fetch_image("http://imagine.example/a.png") is None
    assert G.fetch_image("file:///etc/passwd") is None
    assert not G.public_host("localhost") and not G.public_host("127.0.0.1") and not G.public_host("169.254.169.254")
    assert G.fetch_image("https://127.0.0.1/a.png") is None



def test_full_messages_images_and_humans_have_distinct_import_identities(api):
    from backend.grokbot import GrokMessage, message_id
    from backend.tests.test_api import Identity
    first = {"role": "bot", "at": "2026-09-27T10:00:00Z", "text": "a" * 501 + "first"}
    second = {**first, "text": "a" * 501 + "second"}
    assert sync(api, designer(messages=[first, second]))["bots"][0]["messages_added"] == 2
    assert sync(api, designer(messages=[first, second]))["bots"][0]["messages_known"] == 2
    api.app.state.store.settings.test_identities["sam-test"] = Identity("human:ben", "owner", "ben@acme.example")
    assert sync(api, designer(messages=[first]), token="sam-test")["bots"][0]["messages_added"] == 1
    plain = GrokMessage(**first)
    image = GrokMessage(**first, images=[{"url": "https://example.com/image.png"}])
    assert message_id(GROK_ID, plain, "ana") != message_id(GROK_ID, image, "ana")
    import base64
    attached = [{**first, "text": "Look at this", "images": [{"name": name, "content_base64": base64.b64encode(PNG).decode()}]}
                for name in ("first.png", "second.png")]
    assert sync(api, designer(messages=attached))["bots"][0]["messages_added"] == 2
    assert sync(api, designer(messages=attached))["bots"][0]["messages_known"] == 2
    messages = room_messages(api, "grok-designer")
    images = [H._json(message["refs_json"], {}).get("attachments") for message in messages if message["body"] == "Look at this"]
    assert len(images) == 2 and all(images)
    # A pre-release import uses the old ID; identical attachments still replay without duplicating history.
    import uuid
    from backend.grokbot import NAMESPACE
    old_key = f"{attached[0]['role']}|{attached[0]['at']}|{attached[0]['text'][:500]}"
    old_id = "grok-" + str(uuid.uuid5(NAMESPACE, GROK_ID + "|" + old_key))
    imported = next(message for message in messages if message["body"] == "Look at this")
    with api.app.state.store.transaction() as c:
        assets = [row[0] for row in c.execute("SELECT blob_id FROM message_assets WHERE message_id=?", (imported["id"],))]
        c.execute("DELETE FROM message_assets WHERE message_id=?", (imported["id"],))
        c.execute("UPDATE messages SET id=? WHERE id=?", (old_id, imported["id"]))
        for asset in assets:
            c.execute("INSERT INTO message_assets VALUES(?,?)", (old_id, asset))
    assert sync(api, designer(messages=attached))["bots"][0]["messages_known"] == 2


def test_explicit_empty_metadata_clears_and_omitted_metadata_preserves(api):
    sync(api, designer(messages=[]))
    sync(api, {"grok_id": GROK_ID, "name": "Tico Designer", "messages": []})
    with api.app.state.store.read() as c:
        before = dict(c.execute("SELECT config_json,description FROM bot_config WHERE bot='grok-designer'").fetchone())
    assert before["description"]
    out = sync(api, designer(description="", instructions="", messages=[]))
    assert out["bots"][0]["instructions_changed"]
    with api.app.state.store.read() as c:
        row = c.execute("SELECT config_json,description FROM bot_config WHERE bot='grok-designer'").fetchone()
        grok = H._json(row["config_json"], {})["grok"]
    assert row["description"] == "" and grok["instructions"] == "" and grok["instructions_hash"]
