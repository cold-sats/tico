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


class Workspace(unittest.TestCase):
    """A bot's bot.yaml is found under TICO_PROJECTS_DIR when the runner sets it, else beside the checkout."""

    def projects(self, value):
        import subprocess
        env = {k: v for k, v in os.environ.items() if k != "TICO_PROJECTS_DIR"}
        if value:
            env["TICO_PROJECTS_DIR"] = value
        code = "import browser, slack; print(browser.PROJECTS); print(slack.PROJECTS)"
        out = subprocess.run([sys.executable, "-c", code], cwd=Path(__file__).resolve().parent, env=env,
                             capture_output=True, text=True, check=True)
        return out.stdout.split()

    def test_the_workspace_follows_tico_projects_dir_and_defaults_to_the_folder_around_the_checkout(self):
        with tempfile.TemporaryDirectory() as workspace:
            self.assertEqual(self.projects(workspace), [workspace] * 2)
        self.assertEqual(self.projects(None), [str(Path(__file__).resolve().parents[2])] * 2)

    def test_a_slug_cannot_name_a_folder_outside_the_workspace(self):
        import browser
        with tempfile.TemporaryDirectory() as root:
            workspace, outside = Path(root, "work"), Path(root, "outside")
            (workspace / "bot-real").mkdir(parents=True)
            outside.mkdir()
            (workspace / "bot-real" / "bot.yaml").write_text("tools: []\n")
            (outside / "bot.yaml").write_text("tools: []\n")
            saved = browser.PROJECTS, slack.PROJECTS
            browser.PROJECTS = slack.PROJECTS = workspace
            try:
                self.assertEqual(slack.manifest_of("real")[0], workspace / "bot-real" / "bot.yaml")
                self.assertEqual(browser.load_manifest("real"), {"tools": []})
                for slug in ("real/../../outside", "../outside", "/tmp", "", "real/.."):
                    with self.assertRaises(slack.Refused, msg=slug):
                        slack.manifest_of(slug)
                    with self.assertRaises(browser.Refused, msg=slug):
                        browser.load_manifest(slug)
            finally:
                browser.PROJECTS, slack.PROJECTS = saved


if __name__ == "__main__":
    unittest.main()
