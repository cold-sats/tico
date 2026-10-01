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


class Flaky:
    """A mail CLI whose one mailbox answers unauthorized_client while `refuse` is set."""
    def __init__(self, refuse=True):
        self.refuse, self.calls = refuse, 0

    def __call__(self, args):
        self.calls += 1
        if self.refuse:
            raise RuntimeError("Local mail lookup failed: unauthorized_client: Client is unauthorized")
        return {"messages": []}


def one_domain(tmp_path):
    mail, hub, now = Flaky(), Hub(["ana@acme-signin.example"]), [1000.0]
    work = publisher(tmp_path, hub, mail)
    work.clock = lambda: now[0]
    return work, mail, hub, now


def delegation_reported(hub):
    return {"account": "ana@acme-signin.example", "reason": "delegation"} in hub.reports[-1]["failing"]


def test_one_unauthorized_client_does_not_block_the_domain(tmp_path, capsys):
    work, mail, hub, now = one_domain(tmp_path)
    work.mail_tick()                                # the transient reply
    mail.refuse = False
    work.mail_tick()                                # straight after: the delegation was fine
    assert not work.blocked("ana@acme-signin.example")
    assert all(not r["failing"] for r in hub.reports)
    assert "cannot act for the domain" not in capsys.readouterr().out
    assert work.domains == {}


def test_three_errors_in_one_cycle_or_a_minute_are_not_enough(tmp_path):
    work, mail, hub, now = one_domain(tmp_path)
    for _ in range(3):                              # three errors, one cycle
        work.note_delegation("ana@acme-signin.example")
    assert not work.blocked("ana@acme-signin.example")
    work.cycle += 1
    work.note_delegation("ana@acme-signin.example")       # a second cycle completes the threshold
    assert work.blocked("ana@acme-signin.example")
    other = publisher(tmp_path, hub, mail)
    other.clock = lambda: now[0]
    for _ in range(3):                              # three errors in one cycle, five minutes on, count too
        other.note_delegation("ana@acme.example")
        now[0] += 150
    assert other.domains["acme.example"]["down"]


def test_three_consecutive_errors_block_report_and_log_once(tmp_path, capsys):
    work, mail, hub, now = one_domain(tmp_path)
    work.mail_tick()
    work.mail_tick()
    assert not work.blocked("ana@acme-signin.example") and not delegation_reported(hub)
    work.mail_tick()                                # the third in a row, three cycles
    assert work.blocked("ana@acme-signin.example") and delegation_reported(hub)
    work.mail_tick()
    work.mail_tick()                                # blocked: not tried, still reported
    assert mail.calls == 3 and delegation_reported(hub)
    assert capsys.readouterr().out.count("cannot act for the domain acme-signin.example") == 1


def test_the_backoff_grows_2_5_15_30_60_minutes_and_stays_at_an_hour(tmp_path):
    work, mail, hub, now = one_domain(tmp_path)
    for _ in range(3):
        work.mail_tick()
    waits = []
    for _ in range(7):
        start = now[0]
        waits.append(work.domains["acme-signin.example"]["until"] - start)
        now[0] = work.domains["acme-signin.example"]["until"] - 1
        assert work.blocked("ana@acme-signin.example")
        now[0] += 1                                 # the wait is over: it is tried again and fails again
        assert not work.blocked("ana@acme-signin.example")
        work.mail_tick()
        assert delegation_reported(hub)             # still reported while it is retried
    assert waits == [120, 300, 900, 1800, 3600, 3600, 3600]


def test_one_success_resets_the_domain_and_clears_the_health_issue(tmp_path, capsys):
    work, mail, hub, now = one_domain(tmp_path)
    for _ in range(3):
        work.mail_tick()
    assert delegation_reported(hub)
    now[0] += 121
    mail.refuse = False                             # the delegation was granted after all
    work.mail_tick()
    assert work.domains == {} and not work.blocked("ana@acme-signin.example")
    assert hub.reports[-1]["failing"] == []
    assert "can act for the domain acme-signin.example again" in capsys.readouterr().out
    mail.refuse = True                              # a later error starts counting from zero
    work.mail_tick()
    assert not work.blocked("ana@acme-signin.example") and hub.reports[-1]["failing"] == []


def test_a_success_on_another_mailbox_of_the_domain_resets_it(tmp_path):
    work, mail, hub, now = one_domain(tmp_path)
    for _ in range(3):
        work.mail_tick()
    now[0] += 121
    work.delegated("bob@acme-signin.example")
    assert not work.blocked("ana@acme-signin.example") and work.domains == {}


def test_a_delegated_domain_keeps_syncing_beside_an_undelegated_one(tmp_path):
    calls = []

    def mail(args):
        box = args[args.index("--mailbox") + 1]
        calls.append(box)
        if box.endswith("@acme-signin.example"):
            raise RuntimeError("Local mail lookup failed: unauthorized_client: Client is unauthorized")
        return {"messages": []}
    hub = Hub(["ana@acme-signin.example", "ana@acme.example"])
    work = publisher(tmp_path, hub, mail)
    for _ in range(10):
        work.mail_tick()
    assert calls.count("ana@acme-signin.example") == 3               # tried three times, then left alone
    assert calls.count("ana@acme.example") >= 6                      # the delegated mailbox keeps syncing
    assert {"account": "ana@acme-signin.example", "reason": "delegation"} in hub.reports[-1]["failing"]


def test_the_health_issue_names_the_mailbox_and_the_domain(api):
    machine = runner(api)
    post(api, "connectors/health", {"service": "mail", "failing": [
        {"account": "ana@acme-signin.example", "reason": "delegation"}]}, machine["token"])
    with api.app.state.store.read() as c:
        error = c.execute("SELECT last_error FROM service_health WHERE service='connector:mail'").fetchone()[0]
    assert "ana@acme-signin.example" in error and "domain acme-signin.example" in error and "delegation" in error
    mail = [s for s in get(api, "computers")["services"] if s["service"] == "connector:mail"][0]
    assert mail["name"] == "Mail Tool" and mail["text"].startswith("Mail Tool: ") and mail["fix"] == "Open Health for Mail Tool"
    ops = get(api, "operations")
    assert ops["computers"] == ops["machines"] and ops["computers"]
    assert {"connector:mail": "Mail Tool"}.items() <= {s["service"]: s["name"] for s in ops["services"]}.items()


def named(api, person, body, token="ana-test", expected=200):
    return post(api, f"access/people/{person}", body, token=token, expected=expected)


def test_an_owner_names_a_message_bot_and_the_address_it_reads(api):
    seed_org(api)
    named(api, "ben", {"inbox_bot": "coo", "mailbox": "Ben@Acme.team"})
    with api.app.state.store.read() as c:
        assert routines.token_mailboxes(c, "coo") == ["ben@acme.team"]     # Ben has no reports; the address is the owner's word
        assert routines.declared_mailbox(json_config(c, "coo")) == "ben@acme.team"
    assert "ben@acme.team" in [b["address"] for b in mail_targets(api)]     # the sync follows it too
    named(api, "ben", {"inbox_bot": ""})
    with api.app.state.store.read() as c:
        assert routines.token_mailboxes(c, "coo") == []


def json_config(c, bot):
    import json
    return json.loads(c.execute("SELECT config_json FROM bot_config WHERE bot=?", (bot,)).fetchone()[0])


def test_only_an_owner_or_admin_names_a_message_bot_and_one_bot_serves_one_person(api):
    seed_org(api)
    named(api, "ben", {"inbox_bot": "coo", "mailbox": "ben@acme.team"}, token="cara-test", expected=403)   # a member cannot
    named(api, "ben", {"inbox_bot": "inbox"}, expected=409)                # Ana's message bot
    named(api, "ben", {"mailbox": "ben@acme.team"}, expected=422)          # an address needs the bot that reads it
    named(api, "ben", {"inbox_bot": "no-such-bot"}, expected=404)
    named(api, "ben", {"inbox_bot": "coo", "mailbox": "not an address"}, expected=422)
    with api.app.state.store.read() as c:
        assert routines.token_mailboxes(c, "coo") == []


def test_naming_the_mailbox_keeps_the_bots_other_tools(api):
    seed_org(api)
    with api.app.state.store.transaction() as c:
        c.execute("UPDATE bot_config SET config_json=? WHERE bot='coo'", (encode({
            "name": "coo", "tools": [{"service": "slack", "identity": "Acme"}, {"service": "gmail", "identity": "old@acme.team", "can": ["read"]}]}),))
    named(api, "ben", {"inbox_bot": "coo", "mailbox": "ben@acme.team"})
    with api.app.state.store.read() as c:
        assert json_config(c, "coo")["tools"] == [{"service": "slack", "identity": "Acme"},
                                                  {"service": "gmail", "identity": "ben@acme.team", "can": ["read"]}]
