"""Which Slack channels bots may read and post in is a list in the database (backend/slack_channels.py): who may change it,
what an entry holds, the old registry file until it is imported, BotOps and the MCP tools as the requester, and the Slack
gateway following the list.

Ana owns the company, Ben is an admin, Cara is a member (the base fixture).
"""
import json

import pytest

from backend import slack_channels as SC
from backend.auth import Identity
from backend.tests.test_api import api, get, post, setup_attempt  # noqa: F401  (fixture)
from backend.tests.test_botops_parity import act
from backend.tests.test_mcp import call as mcp
from backend.tests.test_member_bots import botops, finish, turn  # noqa: F401  (fixture)
from backend.tests.test_slack_gateway import CHANNELS, MARKETING, QUIET, channel_message, digests, readers  # noqa: F401  (fixture)

OLD_FILE = """channels:
  - id: C0000000010
    name: customer_success
    purpose: Customer success
    post: false
    readers: [ops]
  - name: agents
    readers: doc-updater
"""


def listed(api, token="ana-test"):
    return {row["channel"]: row for row in get(api, "slack/channels", token)["channels"]}


def old_file(api, text=OLD_FILE):
    settings = api.app.state.store.settings
    (settings.registry_dir / "slack-channels.yaml").write_text(text)


# ------------------------------------------------------------------ who may change the list, and what an entry holds
def test_an_owner_or_admin_lists_a_channel_and_a_member_may_read_the_list_but_not_change_it(api):
    made = post(api, "slack/channels", {"channel": "#Customer_Success", "readers": ["ops", "BOT:cpo"], "note": "Customer success"}, "ben-test")
    assert made["created"] and made["channel"] == "#customer_success" and made["id"] == ""
    assert made["readers"] == ["ops", "cpo"] and made["post"] is True, "bots may post unless someone turns it off"
    # Adding again adds readers and changes only what is sent.
    again = post(api, "slack/channels", {"channel": "customer_success", "readers": ["ops", "finance"], "post": False}, "ana-test")
    assert not again["created"] and again["readers"] == ["ops", "cpo", "finance"] and again["post"] is False
    assert again["note"] == "Customer success", "a note that was not sent is kept"
    by_id = post(api, "slack/channels", {"channel": "C0000000010", "name": "#ideas"}, "ana-test")
    assert (by_id["id"], by_id["name"], by_id["channel"]) == ("C0000000010", "ideas", "#ideas")

    seen = get(api, "slack/channels", "cara-test")
    assert seen["can_manage"] is False and seen["bots"] == [] and {r["channel"] for r in seen["channels"]} == {"#customer_success", "#ideas"}
    assert get(api, "slack/channels", "ben-test")["can_manage"] is True
    for path, body in (("slack/channels", {"channel": "#customer_success", "readers": ["ops"]}),
                       ("slack/channels/remove", {"channel": "#customer_success"}), ("slack/channels/import", {})):
        post(api, path, body, "cara-test", expected=403)
    post(api, "slack/channels", {"channel": "#customer_success", "readers": ["not-a-bot"]}, "ana-test", expected=422)
    post(api, "slack/channels", {"channel": "two words"}, "ana-test", expected=422)
    with api.app.state.store.read() as c:
        assert {r["action"] for r in c.execute("SELECT action FROM events WHERE action LIKE 'slack.channel%'")} >= {
            "slack.channel_added", "slack.channel_changed"}


def test_a_reader_or_the_whole_channel_comes_off_the_list(api):
    post(api, "slack/channels", {"channel": "#customer_success", "readers": ["ops", "cpo"]})
    left = post(api, "slack/channels/remove", {"channel": "#customer_success", "reader": "ops"}, "ben-test")
    assert left["readers"] == ["cpo"] and left["removed"] is True
    assert post(api, "slack/channels/remove", {"channel": "#customer_success", "reader": "ops"})["removed"] is False
    gone = post(api, "slack/channels/remove", {"channel": "#customer_success"}, "ben-test")
    assert gone["deleted"] and listed(api) == {}
    post(api, "slack/channels/remove", {"channel": "#customer_success"}, expected=404)


def test_a_bot_reads_the_list_for_its_own_checks_but_cannot_change_it(api):
    post(api, "slack/channels", {"channel": "#customer_success", "readers": ["ops"]})
    _, _, attempt = setup_attempt(api, "ops")
    assert [r["channel"] for r in get(api, "slack/channels", attempt["token"])["channels"]] == ["#customer_success"]
    post(api, "slack/channels", {"channel": "#sales", "readers": ["ops"]}, attempt["token"], expected=403)
    post(api, "slack/channels/remove", {"channel": "#customer_success"}, attempt["token"], expected=403)
    assert list(listed(api)) == ["#customer_success"]


# ------------------------------------------------------------------ the old registry file, until it is imported
def test_the_old_registry_file_still_counts_until_it_is_imported_once(api):
    old_file(api)
    state = get(api, "slack/channels")
    assert state["registry_file"] == {"present": True, "channels": 2, "imported": False}
    rows = listed(api)
    assert {k: v["source"] for k, v in rows.items()} == {"#customer_success": "file", "#agents": "file"}
    assert rows["#customer_success"]["readers"] == ["ops"] and rows["#customer_success"]["post"] is False
    assert rows["#customer_success"]["note"] == "Customer success" and rows["#agents"]["readers"] == ["doc-updater"]
    # A file-only channel cannot be removed from here, but adding to it stores it, keeping what the file said.
    post(api, "slack/channels/remove", {"channel": "#agents"}, expected=409)
    kept = post(api, "slack/channels", {"channel": "#customer_success", "readers": ["cpo"]})
    assert kept["source"] == "app" and kept["readers"] == ["ops", "cpo"] and kept["post"] is False
    post(api, "slack/channels/import", {}, "cara-test", expected=403)
    done = post(api, "slack/channels/import", {}, "ben-test")
    assert done == {"imported": 1, "skipped": 1}
    assert {k: v["source"] for k, v in listed(api).items()} == {"#customer_success": "app", "#agents": "app"}
    # After the import the file is ignored: what was removed here stays removed.
    post(api, "slack/channels/remove", {"channel": "#agents"})
    assert list(listed(api)) == ["#customer_success"] and get(api, "slack/channels")["registry_file"]["imported"] is True
    post(api, "slack/channels/import", {}, expected=409)


def test_with_no_file_there_is_nothing_to_import(api):
    assert get(api, "slack/channels")["registry_file"] == {"present": False, "channels": 0, "imported": False}
    post(api, "slack/channels/import", {}, expected=404)


# ------------------------------------------------------------------ BotOps and the MCP tools, as the requester
def test_botops_and_the_mcp_tools_change_the_list_as_the_person_who_asked(api, botops):
    err, added = mcp(api, "hub_slack_channel_add", {"channel": "#customer_success", "readers": ["ops"], "note": "Onboarding"}, token="ben-test")
    assert not err and added["created"] and added["readers"] == ["ops"], added
    err, refused = mcp(api, "hub_slack_channel_add", {"channel": "#sales", "readers": ["ops"]}, token="cara-test")
    assert err and "owner or an admin" in json.dumps(refused)
    # BotOps is an admin's hands when an admin asks, and a member's when a member does.
    ben = turn(api, botops, person="ben-test", text="Let the CPO read #customer_success")
    err, done = mcp(api, "hub_slack_channel_add", {"channel": "#customer_success", "readers": ["cpo"], "post": False}, token=ben["token"])
    assert not err and done["readers"] == ["ops", "cpo"] and done["post"] is False and "needs_confirm" not in done, done
    with api.app.state.store.read() as c:
        event = c.execute("SELECT actor,detail_json FROM events WHERE action='slack.channel_changed' ORDER BY ts DESC").fetchone()
    assert event["actor"] == "human:ben" and '"via": "botops"' in event["detail_json"]
    err, removed = mcp(api, "hub_slack_channel_remove", {"channel": "#customer_success", "reader": "cpo"}, token=ben["token"])
    assert not err and removed["readers"] == ["ops"]
    err, listing = mcp(api, "hub_slack_channel_list", {}, token=ben["token"])
    assert not err and [r["channel"] for r in listing["channels"]] == ["#customer_success"]
    finish(api, botops, ben)
    cara = turn(api, botops, person="cara-test", text="Let ops read #sales")
    assert act(api, cara, "POST", "slack/channels", {"channel": "#sales", "readers": ["ops"]}).status_code == 403


def test_the_hub_command_maps_onto_the_tools():
    from clients import hubcli, hubtools, remotecli
    parser = hubcli.parser()
    add = parser.parse_args(["slack", "channel", "add", "#customer_success", "--reader", "ops", "--reader", "cpo", "--no-post", "--note", "x"])
    assert (add.fn, add.channel, add.readers, add.post, add.note) == ("slack channel add", "#customer_success", ["ops", "cpo"], False, "x")
    assert parser.parse_args(["slack", "channel", "add", "#a"]).post is None, "leaving the flag out keeps what the entry has"
    remove = parser.parse_args(["slack", "channel", "remove", "#customer_success", "--reader", "ops"])
    for parsed in (add, remove, parser.parse_args(["slack", "channel", "list"]), parser.parse_args(["slack", "channel", "import"])):
        tool = remotecli.tool_name(parsed.fn)
        assert tool in hubtools.BY_NAME
        fields = {k for k, v in vars(parsed).items() if k not in ("cmd", "sub", "subsub", "fn") and v is not None}
        assert fields <= set(hubtools.BY_NAME[tool]["inputSchema"]["properties"]), tool


# ------------------------------------------------------------------ the gateway and the connector read the list
def test_the_gateway_follows_the_list_in_the_database_and_not_the_file(readers, monkeypatch):
    gw, hub = readers, readers.store
    ana = Identity("human:ana", "owner", "ana@acme.example")
    monkeypatch.setitem(CHANNELS, "C0NEW", {"id": "C0NEW", "name": "newchan"})
    gw.slack.conversations_list = lambda: list(CHANNELS.values())
    with hub.transaction() as c:
        SC.import_file(c, hub.settings, ana)
        SC.remove(c, hub.settings, ana, "#marketing", reader="cmo")
        SC.add(c, hub.settings, ana, "#newchan", readers=["cto"])        # the name only: Slack gives the id
    (hub.settings.registry_dir / "slack-channels.yaml").unlink()
    gw.clock.advance(3600)
    gw.tick()                                                           # a new reader starts at now
    with hub.read() as c:
        assert c.execute("SELECT channel_id FROM slack_channels WHERE name='newchan'").fetchone()[0] == "C0NEW"
    assert gw.receive(channel_message("Launch copy is ready")) == "stored"
    assert gw.receive(channel_message("Something new", channel="C0NEW")) == "stored"
    assert gw.receive(channel_message("Nobody reads this", channel=QUIET)) == "stored"
    gw.clock.advance(3600)
    out = gw.tick()["digests"]
    assert [(d["reader"], d["state"]) for d in out] == [("cto", "sent"), ("seo", "sent")], "cmo was taken off #marketing"
    sent = {d["reader"]: d["body"] for d in digests(hub)}
    assert "Something new" in sent["cto"] and "Launch copy" in sent["seo"] and "Launch copy" not in sent["cto"]


def test_the_channel_map_keeps_the_shape_the_gateway_and_messaging_read(api):
    old_file(api)
    post(api, "slack/channels", {"channel": "C0000000020", "name": "sales", "readers": ["ops"], "note": "Deals", "digest_hours": 24})
    post(api, "slack/channels", {"channel": "#nameonly", "readers": ["ops"]})
    with api.app.state.store.read() as c:
        mapped = SC.channel_map(c, api.app.state.store.settings)
    assert mapped == {"C0000000010": {"name": "customer_success", "purpose": "Customer success", "post": False, "digest_hours": 0.0,
                                      "readers": ["ops"]},
                      "C0000000020": {"name": "sales", "purpose": "Deals", "post": True, "digest_hours": 24.0, "readers": ["ops"]}}, \
        "a channel with no id yet is left to the gateway to resolve"
