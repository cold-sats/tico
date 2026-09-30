"""Which mailboxes the mail and calendar sync targets, and which one a message bot's token is for.

A message bot's mailbox is the address its `gmail` tool declares in bot.yaml (BotOps fills it from the
`Mailbox:` line). Only when it declares none does its person's own email stand in.
"""

import os

from backend import routines
from backend.store import H, encode
from backend.tests.test_api import api, get, post, runner, setup_attempt  # noqa: F401
from backend.tests.test_mail_api import ORG, seed_org
from runner.connectors import ConnectorPublisher

DECLARED = "ana@acme.team"


def declare(api, identity):
    """Give the `inbox` bot (Ana's message bot) a gmail tool with this identity, in bot.yaml's shape."""
    tools = [{"service": "gmail", "identity": identity, "can": ["read", "draft"]}]
    with api.app.state.store.transaction() as c:
        c.execute("UPDATE bot_config SET config_json=? WHERE bot='inbox'",
                  (encode({"name": "inbox", "runtime": "fake", "status": "active", "tools": tools}),))


def mail_targets(api, token=None):
    return get(api, "connectors/mail/targets", token or runner(api)["token"])["mailboxes"]


def test_targets_are_the_message_bots_declared_mailboxes_not_every_person(api):
    seed_org(api)
    declare(api, DECLARED)
    boxes = mail_targets(api)
    assert [b["address"] for b in boxes] == [DECLARED]          # Ben, Lena, Mira, Carla and Cara have no message bot
    assert boxes[0]["person_id"] == "ana"


def test_a_message_bot_without_a_declared_mailbox_falls_back_to_its_persons_email(api):
    seed_org(api)
    assert [b["address"] for b in mail_targets(api)] == ["ana@acme.example"]
    declare(api, "{{mailbox}}")                                 # never filled in: not a declaration
    assert [b["address"] for b in mail_targets(api)] == ["ana@acme.example"]


def test_an_archived_bot_or_a_person_who_left_is_not_a_target(api):
    seed_org(api)
    declare(api, DECLARED)
    token = runner(api)["token"]
    with api.app.state.store.transaction() as c:
        c.execute("UPDATE bots SET state='archived' WHERE slug='inbox'")
    assert mail_targets(api, token) == []
    with api.app.state.store.transaction() as c:
        c.execute("UPDATE bots SET state='active' WHERE slug='inbox'")
        people = [{**p, "hidden": True} if p["id"] == "ana" else p for p in ORG]
        c.execute("INSERT OR REPLACE INTO registry_metadata VALUES('people',?)", (encode({"people": people}),))
    assert mail_targets(api, token) == []


def test_calendar_targets_are_the_same_mailboxes_and_a_snapshot_for_one_is_accepted(api):
    seed_org(api)
    declare(api, DECLARED)
    token = runner(api)["token"]
    people = get(api, "connectors/calendar/targets", token)["people"]
    assert people == [{"id": "ana", "email": DECLARED}]
    post(api, "connectors/calendar/snapshots", {"snapshots": [{"email": DECLARED, "events": []}]}, token)
    with api.app.state.store.read() as c:
        assert c.execute("SELECT owner FROM connector_snapshots WHERE kind='calendar'").fetchone()[0] == "ana"


def test_the_token_is_issued_for_the_declared_mailbox_and_the_people_below(api):
    seed_org(api)
    declare(api, DECLARED)
    with api.app.state.store.read() as c:
        assert routines.token_mailboxes(c, "inbox") == [
            DECLARED, "ben@acme.example", "lena@acme.example", "mira@acme.example", "carla@acme.example"]
        assert routines.token_mailboxes(c, "coo") == []          # a bot that is nobody's message bot gets nothing


def test_without_a_declaration_the_token_is_for_the_persons_own_address(api):
    seed_org(api)
    with api.app.state.store.read() as c:
        assert routines.token_mailboxes(c, "inbox")[0] == "ana@acme.example"
        assert "ana@acme.example" in routines.token_mailboxes(c, "inbox")


def test_a_message_bot_turn_is_handed_the_declared_mailbox(api):
    seed_org(api)
    declare(api, DECLARED)
    _, _, attempt = setup_attempt(api, bot="inbox")
    assert attempt["mailboxes"][0] == DECLARED and "ana@acme.example" not in attempt["mailboxes"]
    assert "ben@acme.example" in attempt["mailboxes"]


# The runner: a domain the key can't act for is reported once, not failed on every cycle.

class Hub:
    def __init__(self, boxes):
        self.boxes, self.reports = boxes, []

    def get(self, path):
        assert path == "connectors/mail/targets"
        return {"mailboxes": [{"address": a, "message_count": 1} for a in self.boxes], "batch": 100}

    def post(self, path, body):
        assert path == "connectors/health"
        self.reports.append(body)
        return {"ok": True}


def publisher(tmp_path, hub, mail):
    script = tmp_path / "hub/scripts/mail.sh"
    script.parent.mkdir(parents=True, exist_ok=True)
    script.write_text("#!/bin/sh\nexit 1\n")
    script.chmod(os.stat(script).st_mode | 0o100)
    made = ConnectorPublisher({"url": "http://localhost:8765", "token": "t", "projects_dir": str(tmp_path),
                               "mail_sync_seconds": 0, "owner_handle": "ana"}, client=hub, mail=mail)
    made.script = script
    return made


def test_an_undelegated_domain_is_reported_once_and_skipped_afterwards(tmp_path, capsys):
    calls = []

    def mail(args):
        box = args[args.index("--mailbox") + 1]
        calls.append(box)
        if box.endswith("@tidy.com"):
            raise RuntimeError("Local mail lookup failed: unauthorized_client: Client is unauthorized")
        return {"messages": []}
    hub = Hub(["chris@tidy.com", "chris@tico.team"])
    work = publisher(tmp_path, hub, mail)
    for _ in range(4):
        work.mail_tick()
    assert calls.count("chris@tidy.com") == 1                    # tried once, then left alone
    assert calls.count("chris@tico.team") >= 3                   # the delegated mailbox keeps syncing
    assert all({"account": "chris@tidy.com", "reason": "delegation"} in r["failing"] for r in hub.reports[1:])
    assert capsys.readouterr().out.count("cannot act for the domain tidy.com") == 1


def test_the_health_issue_names_the_mailbox_and_the_domain(api):
    machine = runner(api)
    post(api, "connectors/health", {"service": "mail", "failing": [
        {"account": "chris@tidy.com", "reason": "delegation"}]}, machine["token"])
    with api.app.state.store.read() as c:
        error = c.execute("SELECT last_error FROM service_health WHERE service='connector:mail'").fetchone()[0]
    assert "chris@tidy.com" in error and "domain tidy.com" in error and "delegation" in error
