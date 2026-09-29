"""A person's Grok Bots synced in: placed under them, transcripts copied once, never dispatched to."""

from backend.store import H
from backend.tests.test_api import api, get, headers, post  # noqa: F401
from backend.tests.test_mcp import call

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


def test_syncing_again_adds_only_what_is_new_and_keeps_where_the_person_moved_it(api):
    sync(api, designer())
    revision = next(b for b in get(api, "bots") if b["slug"] == "grok-designer")["revision"]
    post(api, "bots/grok-designer/definition", {"reports_to": "ops", "expected_revision": revision})
    more = designer(name="Tico Designer", instructions="You design Tico. Keep it calm.",
                    messages=designer()["messages"] + [{"role": "user", "text": "Ship it.", "at": "2026-09-28T09:00:00Z"}])
    [bot] = sync(api, more)["bots"]
    assert not bot["created"] and bot["bot"] == "grok-designer"
    assert (bot["messages_added"], bot["messages_known"]) == (1, 2)
    assert bot["instructions_changed"]
    row = next(b for b in get(api, "bots") if b["slug"] == "grok-designer")
    assert row["reports_to"] == "ops", "a sync never moves a bot the person placed"
    assert len(room_messages(api, "grok-designer")) == 3


def test_a_synced_bot_reports_in_by_its_last_sync_and_a_message_waits_in_its_inbox(api):
    sync(api, designer(messages=[]))
    row = next(b for b in get(api, "bots") if b["slug"] == "grok-designer")
    assert row["agent"]["harness"] == "grokbot" and row["agent"]["credential"] and row["online"]
    assert not [i for i in api.get("/api/status", headers=headers()).json()["health_issues"]
                if i["bot"] == "grok-designer"]
    post(api, "chat/grok-designer", {"text": "Hello from Tico."})
    with api.app.state.store.read() as c:
        assert c.execute("SELECT count(*) FROM jobs WHERE bot='grok-designer'").fetchone()[0] == 0
        c.execute("SELECT 1")
    with api.app.state.store.transaction() as c:
        c.execute("UPDATE bot_config SET config_json=json_set(config_json,'$.grok.last_sync',?) WHERE bot='grok-designer'",
                  (H.shift(H.now(), hours=-30),))
    assert not next(b for b in get(api, "bots") if b["slug"] == "grok-designer")["online"]


def test_the_same_name_from_two_grok_bots_gets_two_slugs_and_a_bot_cannot_sync(api):
    sync(api, designer(), designer(grok_id="other-grok-id", messages=[]))
    slugs = {b["slug"] for b in get(api, "bots")}
    assert {"grok-designer", "grok-designer-2"} <= slugs
    r = api.post("/api/v2/grokbot/sync", json={"bots": [designer()]}, headers=headers("cara-test"))
    assert r.status_code == 403


def test_the_mcp_tool_syncs_as_the_person(api):
    failed, out = call(api, "hub_grokbot_sync", {"bots": [designer()], "source": "Groky"}, token="ana-test")
    assert not failed and out["bots"][0]["bot"] == "grok-designer" and out["person"] == "ana"


def test_tico_in_a_grok_name_reads_grok_here():
    # Ana, 2026-09-28: "Tico Designer" in Grok is "Grok Designer" in Tico.
    from backend import grokbot as G
    assert G.local_name("Tico Designer") == "Grok Designer"
    assert G.local_name("Tico Sync") == "Grok Sync"
    assert G.local_name("tico  support bot") == "Grok support bot"
    assert G.local_name("Grok Tico Helper") == "Grok Helper"
    assert G.local_name("Ticonderoga") == "Ticonderoga"
    assert G.local_name("Designer") == "Designer"


PNG = bytes.fromhex("89504e470d0a1a0a0000000d4948445200000001000000010806000000"
                    "1f15c4890000000d49444154789c6360000002000154a24f5d0000000049454e44ae426082")


def test_images_a_grok_bot_showed_are_stored_and_shown_inline_and_a_lost_one_stays_a_link(api, monkeypatch):
    # Ana, 2026-09-28: "the images do not seem to be coming into me from GrokBot."
    import base64
    import json
    from backend import grokbot as G
    fetched = []

    def fake(url, transport=None):
        fetched.append(url)
        return (PNG, "image/png") if url.endswith("poster.png") else None
    monkeypatch.setattr(G, "fetch_image", fake)
    reply = {"role": "bot", "text": "Here are two options.", "at": "2026-09-27T10:02:00Z",
             "images": [{"url": "https://imagine.example/poster.png"}, {"url": "https://imagine.example/gone.png"},
                        {"name": "sketch.png", "content_base64": base64.b64encode(PNG).decode()}]}
    sync(api, designer(messages=[reply]))
    [msg] = room_messages(api, "grok-designer")
    refs = json.loads(msg["refs_json"])
    assert [a["name"] for a in refs["attachments"]] == ["poster.png", "sketch.png"]
    assert all(a["content_type"] == "image/png" for a in refs["attachments"])
    assert "[Image in Grok](https://imagine.example/gone.png)" in msg["body"]
    r = api.get(refs["attachments"][0]["url"], headers=headers("ana-test"))
    assert r.status_code == 200 and r.content == PNG
    # Sending the same message again fetches nothing and stores nothing twice.
    fetched.clear()
    sync(api, designer(messages=[reply]))
    assert fetched == [] and len(room_messages(api, "grok-designer")) == 1


def test_tico_fetches_only_public_https_images():
    from backend import grokbot as G
    assert G.fetch_image("http://imagine.example/a.png") is None
    assert G.fetch_image("file:///etc/passwd") is None
    assert not G.public_host("localhost") and not G.public_host("127.0.0.1") and not G.public_host("169.254.169.254")
    assert G.fetch_image("https://127.0.0.1/a.png") is None


def test_an_image_link_is_followed_but_only_to_an_image():
    import httpx
    from backend import grokbot as G

    def handler(request):
        if request.url.path == "/start":
            return httpx.Response(302, headers={"location": "https://cdn.example/poster.png"})
        if request.url.path == "/page":
            return httpx.Response(200, headers={"content-type": "text/html"}, content=b"<html>")
        if request.url.path == "/plain":
            return httpx.Response(302, headers={"location": "http://cdn.example/poster.png"})
        return httpx.Response(200, headers={"content-type": "image/png"}, content=PNG)
    t = httpx.MockTransport(handler)
    assert G.fetch_image("https://imagine.example/start", t) == (PNG, "image/png")
    assert G.fetch_image("https://imagine.example/page", t) is None           # not an image
    assert G.fetch_image("https://imagine.example/plain", t) is None          # a redirect off https
