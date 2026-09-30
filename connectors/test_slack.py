#!/usr/bin/env python3
"""Unit tests for connectors/slack.py. No network, no token.

    python3 -m unittest discover -s connectors
"""

import contextlib, io, json, os, sys, tempfile, unittest
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import slack                                            # noqa: E402

TZ = "America/Los_Angeles"
NOW = datetime(2026, 9, 2, 10, 30, tzinfo=slack.zone(TZ))   # a Wednesday morning in LA


class PostPolicy(unittest.TestCase):
    channels = [
        {"id": "C0000000001", "name": "marketing", "post": True},
        {"id": "C0000000002", "name": "release_notes", "post": False},
        {"id": None, "name": "agents", "post": True},
        {"id": "C0000000003", "name": "random"},
    ]

    def test_employee_must_declare_slack_post(self):
        allowed = {"access": [{"service": "slack", "can": ["read", "post"]}]}
        self.assertEqual(slack.check_can_post(allowed, "doc-updater")["service"], "slack")
        with self.assertRaises(slack.Refused):
            slack.check_can_post({"access": [{"service": "slack", "can": ["read"]}]}, "doc-updater")
        with self.assertRaises(slack.Refused):
            slack.check_can_post({"access": [{"service": "gmail", "can": ["post"]}]}, "seo")
        with self.assertRaises(slack.Refused):
            slack.check_can_post({}, "seo")

    def test_channel_must_be_registered_and_postable(self):
        entry = slack.find_registry_channel(self.channels, "#marketing")
        self.assertEqual(slack.check_channel_postable(entry, "#marketing"), "C0000000001")
        self.assertIs(slack.find_registry_channel(self.channels, "C0000000001"), entry)
        with self.assertRaises(slack.Refused):
            slack.find_registry_channel(self.channels, "#general")
        with self.assertRaises(slack.Refused):
            slack.check_channel_postable(
                slack.find_registry_channel(self.channels, "release_notes"), "release_notes")
        with self.assertRaises(slack.Refused):
            slack.check_channel_postable(
                slack.find_registry_channel(self.channels, "#agents"), "#agents")

    def test_a_channel_that_says_nothing_about_posting_is_postable(self):
        entry = slack.find_registry_channel(self.channels, "#random")
        self.assertEqual(slack.check_channel_postable(entry, "#random"), "C0000000003")

    def test_externally_shared_channels_are_refused(self):
        slack.check_not_external({"channel": {"name": "marketing"}}, "#marketing")
        for flag in ("is_ext_shared", "is_shared", "is_pending_ext_shared", "is_org_shared"):
            with self.assertRaises(slack.Refused):
                slack.check_not_external({"channel": {"name": "partner", flag: True}}, "#partner")

class DmPolicy(unittest.TestCase):
    allowed = {"ana@acme.example", "cara@acme.example"}

    def person(self, **kw):
        row = {"id": "U9", "name": "cara", "display": "Cara", "real_name": "Cara",
               "email": "cara@acme.example", "is_bot": False, "deleted": False}
        row.update(kw)
        return row

    def test_bots_and_deactivated_accounts_are_refused(self):
        with self.assertRaises(slack.Refused):
            slack.check_recipient(self.person(is_bot=True), self.allowed, "@companyhub")
        with self.assertRaises(slack.Refused):
            slack.check_recipient(self.person(id="USLACKBOT"), self.allowed, "@slackbot")
        with self.assertRaises(slack.Refused):
            slack.check_recipient(self.person(deleted=True), self.allowed, "@gone")

class FakeHTTP:
    """Replaces slack._request. Each response is (status, headers, payload)."""

    def __init__(self, *responses):
        self.responses, self.calls = list(responses), []

    def __call__(self, url, data, headers, timeout):
        self.calls.append({"url": url, "data": json.loads(data) if data else None,
                           "auth": headers.get("Authorization")})
        status, hdrs, payload = self.responses.pop(0)
        return status, hdrs, json.dumps(payload).encode()


DANILLO = {"id": "U9", "name": "cara", "display": "Cara", "real_name": "Cara",
           "email": "cara@acme.example", "is_bot": False, "deleted": False}
ANA = {"id": "U2", "name": "anah", "display": "anah", "real_name": "Ana",
         "email": "ana@acme.example", "is_bot": False, "deleted": False}
A_BOT = {"id": "UB1", "name": "someapp", "display": "Some App", "real_name": "",
         "email": "", "is_bot": True, "deleted": False}


def slack_user(uid, email, name="Cara", **kw):
    """A users.lookupByEmail / users.info payload."""
    row = {"id": uid, "name": name.lower(),
           "profile": {"display_name": name, "real_name": name, "email": email}}
    row.update(kw)
    return row


class FakeSlack(unittest.TestCase):
    """Base for command tests: a token, a fake employee, no disk writes, no network."""

    slug = "doc-updater"

    def setUp(self):
        self.real_request, self.real_projects = slack._request, slack.PROJECTS
        self.real_audit, self.audited = slack.audit, []
        self.old_token = os.environ.get("SLACK_BOT_TOKEN")
        os.environ["SLACK_BOT_TOKEN"] = "xoxb-test"
        slack._CACHE.clear()
        slack._CACHE["directory"] = [DANILLO, ANA, A_BOT]      # no users.list call
        self.tmp = tempfile.TemporaryDirectory()
        slack.PROJECTS = Path(self.tmp.name)
        self.employee("doc-updater", ["read", "post"])
        self.employee("reader", ["read"])
        slack.audit = lambda *a, **k: self.audited.append((a, k))

    def tearDown(self):
        slack._request, slack.PROJECTS, slack.audit = (self.real_request, self.real_projects,
                                                       self.real_audit)
        os.environ.pop("SLACK_BOT_TOKEN", None)
        if self.old_token is not None:
            os.environ["SLACK_BOT_TOKEN"] = self.old_token
        slack._CACHE.clear()
        self.tmp.cleanup()

    def employee(self, slug, can):
        d = Path(self.tmp.name) / f"emp-{slug}"
        d.mkdir(parents=True, exist_ok=True)
        (d / "employee.yaml").write_text(
            "slug: %s\naccess:\n  - service: slack\n    can: [%s]\n" % (slug, ", ".join(can)))

    def run_cli(self, argv, responses=()):
        slack._request = FakeHTTP(*responses)
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            rc = slack.main(argv)
        return rc, out.getvalue(), slack._request.calls


OK_OPEN = (200, {}, {"ok": True, "channel": {"id": "D0123"}})
OK_POST = (200, {}, {"ok": True, "ts": "1756742400.000100"})
OK_AUTH = (200, {}, {"ok": True, "user_id": "U0BOT", "url": "https://acme.slack.com"})


class DmGates(FakeSlack):
    def test_someone_outside_hub_access_is_refused_and_nothing_is_posted(self):
        rc, out, calls = self.run_cli(
            ["dm", "--as", self.slug, "--to", "lead@acme.com", "--text", "hi", "--json"],
            [(200, {}, {"ok": True, "user": slack_user("U77", "lead@acme.com", "Lead")})])
        body = json.loads(out)
        self.assertEqual(rc, 2)
        self.assertEqual(len(calls), 1)                  # the lookup, then it stopped
        self.assertIn("lead@acme.com", body["error"])
        self.assertIn("hub-access.yaml", body["hint"])
        self.assertEqual(self.audited, [])


class ChannelList(FakeSlack):
    """The channel list is the hub's (Settings > Tools > Slack); the old registry file counts only until it is imported."""

    rows = [{"id": "C0000000010", "name": "success_team", "post": True, "readers": ["reader"], "note": ""},
            {"id": "", "name": "agents", "post": True, "readers": [], "note": ""},
            {"id": "C0000000011", "name": "release_notes", "post": False, "readers": [], "note": ""}]

    def setUp(self):
        super().setUp()
        self.real_get, self.asked = slack.HUB_GET, []
        self.file = Path(self.tmp.name) / "slack-channels.yaml"
        self.answer = {"channels": self.rows, "registry_file": {"present": False, "channels": 0, "imported": True}}
        slack.HUB_GET = lambda path: (self.asked.append(path), self.answer)[1]

    def tearDown(self):
        slack.HUB_GET = self.real_get
        super().tearDown()

    def test_a_run_reads_the_list_from_the_hub_and_the_file_only_until_it_is_imported(self):
        self.file.write_text("channels:\n  - {id: C0000000012, name: old_one, readers: reader}\n")
        self.assertEqual([c["name"] for c in slack.load_channels(self.file)], ["success_team", "agents", "release_notes"])
        self.assertEqual(self.asked, ["slack/channels"])
        slack._CACHE.clear()
        self.answer["registry_file"]["imported"] = False
        self.assertEqual([c["name"] for c in slack.load_channels(self.file)],
                         ["success_team", "agents", "release_notes", "old_one"])

    def test_without_the_hub_the_file_is_used_and_with_neither_the_refusal_says_where_the_list_is(self):
        self.answer = None
        with self.assertRaises(slack.Refused) as refused:
            slack.load_channels(self.file)
        self.assertIn("Settings > Tools > Slack", refused.exception.hint)
        slack._CACHE.clear()
        self.file.write_text("channels:\n  - {id: C0000000012, name: old_one}\n")
        self.assertEqual([c["name"] for c in slack.load_channels(self.file)], ["old_one"])

    def test_a_reader_on_the_list_may_read_a_channel_outside_its_declared_scope(self):
        manifest = {"tools": [{"service": "slack", "can": ["read"], "channels": ["agents"]}]}
        rows = slack.load_channels(self.file)
        slack.check_history_scope(manifest, "reader", ["#agents", "C0000000010"], rows)
        with self.assertRaises(slack.Refused):                       # listed, but its reader is someone else
            slack.check_history_scope(manifest, "other-bot", ["#success_team"], rows)
        with self.assertRaises(slack.Refused):                       # not on the list at all
            slack.check_history_scope(manifest, "reader", ["#general"], rows)
        # A declared channel the list does not have no longer refuses every read.
        stale = {"tools": [{"service": "slack", "can": ["read"], "channels": ["gone", "agents"]}]}
        slack.check_history_scope(stale, "reader", ["#agents"], rows)

    def test_a_post_follows_the_list_and_externally_shared_channels_stay_refused(self):
        listing = (200, {}, {"ok": True, "channels": [{"id": "C0000000020", "name": "agents"}]})
        rc, out, calls = self.run_cli(["post", "--as", self.slug, "--channel", "#agents", "--text", "hi", "--json"],
                                      [listing, (200, {}, {"ok": True, "channel": {"id": "C0000000020", "name": "agents"}}),
                                       OK_POST, OK_AUTH])
        self.assertEqual(rc, 0, out)
        self.assertEqual(calls[-2]["data"]["channel"], "C0000000020")      # listed by name: Slack gave the id
        self.assertEqual(len(self.audited), 1)
        self.audited.clear()
        slack._CACHE.clear()
        rc, out, calls = self.run_cli(["post", "--as", self.slug, "--channel", "#release_notes", "--text", "hi", "--json"])
        self.assertEqual((rc, calls), (2, []))                        # the list says bots may not post there
        self.assertIn("Settings > Tools > Slack", json.loads(out)["hint"])
        rc, out, calls = self.run_cli(["post", "--as", self.slug, "--channel", "#general", "--text", "hi", "--json"])
        self.assertEqual((rc, calls), (2, []))                        # not on the list
        slack._CACHE.clear()
        rc, out, calls = self.run_cli(["post", "--as", self.slug, "--channel", "C0000000010", "--text", "hi", "--json"],
                                      [(200, {}, {"ok": True, "channel": {"name": "success_team", "is_ext_shared": True}})])
        self.assertEqual(rc, 2)
        self.assertEqual(len(calls), 1)                               # conversations.info, then it stopped
        self.assertEqual(self.audited, [])


if __name__ == "__main__":
    unittest.main()
