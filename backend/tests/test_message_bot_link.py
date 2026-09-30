"""A message bot made for a person is linked to them: `inbox_bot` on their roster entry and the mailbox on the bot.

That link is what lets the bot's runs ask a computer for a mail token (routines.token_mailboxes). It is written where
the bot is made, and once at start for bots made before that when there is no doubt whose they are.
"""
import json

from backend import message_bots, routines
from backend.store import H, encode
from backend.tests.test_api import api, get, post  # noqa: F401  (fixture)
from backend.tests.test_member_bots import botops, register, turn  # noqa: F401  (fixtures)
from backend.tests.test_onboarding import (ASSISTANT_AGENT, ASSISTANT_CARD, BOTOPS_CARD, draft,  # noqa: F401
                                           environment, signed_in)

MODEL = {"model": "gpt-6-astra", "effort": "high", "harness": None, "runner_id": None}


def inbox_bot_of(api, person):
    with api.app.state.store.read() as c:
        return next(p for p in message_bots._roster(c)["people"] if p["id"] == person).get("inbox_bot")


def mailbox_of(api, bot):
    with api.app.state.store.read() as c:
        return routines.declared_mailbox(message_bots._config(c, bot))


def add_from_template(api, slug, instructions, token="ana-test"):
    return post(api, "bots", {"slug": slug, "display_name": "Inbox Manager", "description": "Mail", "status": "planned",
                              "template": "inbox", "instructions": instructions, **MODEL}, token=token)


def test_adding_the_template_in_settings_links_the_person_the_mailbox_line_names(api):
    add_from_template(api, "ben-inbox", "# Inbox\n\nMailbox: ben@acme.example\n")
    assert inbox_bot_of(api, "ben") == "ben-inbox" and inbox_bot_of(api, "ana") is None
    assert mailbox_of(api, "ben-inbox") == "ben@acme.example"
    with api.app.state.store.read() as c:
        assert routines.token_mailboxes(c, "ben-inbox")[0] == "ben@acme.example"


def test_a_mailbox_on_another_domain_is_kept_and_no_line_falls_back_to_the_requester(api):
    add_from_template(api, "ben-inbox", "Mailbox: ben@acme.example\n")
    add_from_template(api, "cara-inbox", "Nothing about a mailbox here.\n", token="cara-test")
    assert inbox_bot_of(api, "cara") == "cara-inbox" and mailbox_of(api, "cara-inbox") == "cara@acme.example"
    # A line that names nobody on the roster (the Workspace address is not the one a person signs in with) is still the
    # requester's: they made it.
    add_from_template(api, "stray-inbox", "Mailbox: someone@elsewhere.example\n")
    assert inbox_bot_of(api, "ana") == "stray-inbox" and mailbox_of(api, "stray-inbox") == "someone@elsewhere.example"
    # A person with a message bot already keeps it.
    add_from_template(api, "ben-inbox-2", "Mailbox: ben@acme.example\n")
    assert inbox_bot_of(api, "ben") == "ben-inbox"


def test_botops_registering_a_message_bot_in_chat_links_the_requester(api, botops):
    attempt = turn(api, botops)
    assert register(api, attempt, "cara-mail", template="inbox").status_code == 200
    assert inbox_bot_of(api, "cara") == "cara-mail" and mailbox_of(api, "cara-mail") == "cara@acme.example"
    assert register(api, attempt, "cara-notes", template="support").status_code == 200      # not a message bot: untouched
    assert inbox_bot_of(api, "cara") == "cara-mail"


def test_the_team_builder_links_a_message_bot_it_creates(environment):
    card = {"template": "inbox", "slug": "inbox", "name": "Inbox Manager", "required": False, "bootstrap": False,
            "kind": "helper", "summary": "Runs a mailbox.", "owns": ["the brief"], "never": ["send"],
            "reasoning_effort": "medium", "recommend_when": ["uses_email"]}
    api = environment(cards=[(ASSISTANT_CARD, ASSISTANT_AGENT), (BOTOPS_CARD, ""), (card, "# Inbox\n")])
    selected = {"riley-inbox": {"template": "inbox", "display_name": "Riley's mail",
                                "instructions": "# Inbox\n\nMailbox: riley@acme.example\n"}}
    assert draft(api, selected=selected).status_code == 200
    assert api.post("/api/v2/onboarding/complete", json={}, headers=signed_in()).status_code == 200
    with api.app.state.store.read() as c:
        people = {p["id"]: p for p in message_bots._roster(c)["people"]}
        assert people["riley"]["inbox_bot"] == "riley-inbox" and not people["morgan"].get("inbox_bot")
        assert routines.declared_mailbox(message_bots._config(c, "riley-inbox")) == "riley@acme.example"


# ------------------------------------------------------------------ start-up backfill

def old_message_bot(api, slug, instructions="", tools=None, template="inbox"):
    """A message bot as an earlier release left it: a template and its text, and nobody's `inbox_bot`."""
    config = {"name": slug, "runtime": "fake", "status": "active", "template": template, "instructions": instructions}
    if tools:
        config["tools"] = tools
    with api.app.state.store.transaction() as c:
        c.execute("INSERT INTO bots(slug,display_name,state) VALUES(?,?,'active')", (slug, slug))
        c.execute("INSERT INTO bot_config(bot,config_json,operator) VALUES(?,?,'ana')", (slug, encode(config)))


def backfill(api):
    with api.app.state.store.transaction() as c:
        return message_bots.backfill(c)


def test_backfill_links_the_bot_whose_mailbox_is_a_person_s_email(api):
    old_message_bot(api, "inbox-manager", "Role.\n\nMailbox: ben@acme.example\n")
    old_message_bot(api, "cara-mail", tools=[{"service": "gmail", "identity": "cara@acme.example", "can": ["read"]}])
    assert backfill(api) == ["cara-mail", "inbox-manager"]
    assert inbox_bot_of(api, "ben") == "inbox-manager" and inbox_bot_of(api, "cara") == "cara-mail"
    assert mailbox_of(api, "inbox-manager") == "ben@acme.example"
    assert backfill(api) == []                                                            # nothing left to do


def test_backfill_links_a_mailbox_on_another_domain_to_the_bot_s_owner(api):
    old_message_bot(api, "inbox-manager", "Mailbox: ana@tico.example\n")                # three people, operator ana
    assert backfill(api) == ["inbox-manager"]
    assert inbox_bot_of(api, "ana") == "inbox-manager" and mailbox_of(api, "inbox-manager") == "ana@tico.example"


def test_backfill_uses_the_creator_before_the_operator_and_the_only_person_when_nothing_else_says(api):
    old_message_bot(api, "inbox-manager", "Mailbox: chris@workspace.example\n")
    with api.app.state.store.transaction() as c:
        c.execute("UPDATE bot_config SET created_by='human:cara' WHERE bot='inbox-manager'")
    assert backfill(api) == ["inbox-manager"] and inbox_bot_of(api, "cara") == "inbox-manager"
    old_message_bot(api, "lone", "Mailbox: x@workspace.example\n")
    with api.app.state.store.transaction() as c:
        c.execute("UPDATE bot_config SET operator='nobody' WHERE bot='lone'")
        c.execute("INSERT OR REPLACE INTO registry_metadata VALUES('people',?)", (encode({"people": [
            {"id": "ben", "email": "ben@acme.example", "primary_for": ["*"]}]}),))
    assert backfill(api) == ["lone"] and inbox_bot_of(api, "ben") == "lone"


def test_the_mailbox_is_found_in_the_gmail_tool_the_computer_reports_or_in_the_instructions_words(api):
    # BotOps wrote the address into bot.yaml only: the server knows it from the computer's report.
    old_message_bot(api, "reported", "Reads mail for the owner.")
    with api.app.state.store.transaction() as c:
        c.execute("INSERT INTO runners(id,label,operator,token_hash,created,last_seen,readiness_json) VALUES('r1','Mac','ana','h',?,?,?)",
                  (H.now(), H.now(), encode({"schema_version": 1, "bots": {"reported": {"tools": [
                      {"service": "gmail", "identity": "Chris@Workspace.example", "can": ["read", "draft"]}]}}})))
        c.execute("INSERT INTO assignments(bot,runner_id,generation,updated,updated_by) VALUES('reported','r1',1,?,'keeper')", (H.now(),))
    assert backfill(api) == ["reported"]
    assert inbox_bot_of(api, "ana") == "reported"
    with api.app.state.store.read() as c:
        assert message_bots.mailbox_of(c, "reported", message_bots._config(c, "reported")) == "chris@workspace.example"
    words = message_bots.mailbox_in_words
    assert words("You run the inbox for my mailbox Ben@Acme.example. Be brief.") == "ben@acme.example"
    assert words("Mailbox: <ben@acme.example>.") == "ben@acme.example" and words("no address here") == ""
    old_message_bot(api, "spoken", "You are the inbox manager for my mailbox cara@acme.example.")
    assert backfill(api) == ["spoken"] and inbox_bot_of(api, "cara") == "spoken"


def test_backfill_leaves_what_is_a_choice_for_an_owner(api):
    old_message_bot(api, "first", "Mailbox: ben@acme.example\n")
    old_message_bot(api, "second", "Mailbox: ben@acme.example\n")           # two bots for one person
    old_message_bot(api, "no-mailbox", "Runs mail, says nothing of whose.\n")
    old_message_bot(api, "a-role", "Mailbox: cara@acme.example\n", template="support")
    assert backfill(api) == []
    with api.app.state.store.transaction() as c:
        c.execute("UPDATE bots SET state='archived' WHERE slug='second'")
    assert backfill(api) == ["first"]
    # An owner who takes the link away is not overruled at the next start.
    post(api, "access/people/ben", {"inbox_bot": ""})
    assert inbox_bot_of(api, "ben") is None and backfill(api) == []
