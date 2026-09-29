"""Subscription profiles: which provider login a bot's turn and readiness check run against.

No CLI is started. The hosts are inspected for the homes they were built with, and the readiness
checks are driven through a fake `subprocess.run` that records the environment it was given.
"""

import os
import tempfile
import unittest
from pathlib import Path

from runner import profiles
from runner.service import Runner

BOT = {"bot": "sales", "id": "a1", "token": "t", "config": {"runtime": "codex"},
       "conversation": {"id": "c1"}}


def attempt(bot="sales", runtime="codex", **config):
    return {**BOT, "bot": bot, "config": {"runtime": runtime, **config}}


def service(tmp, **config):
    """A Runner with no outbox, client, or threads: `doctor` builds one the same way."""
    runner = Runner.__new__(Runner)
    runner.config = {"url": "https://example.test", "token": "t", "projects_dir": str(tmp), **config}
    runner.state = type("S", (), {"directory": Path(tmp) / "state"})()
    return runner


class Readiness(unittest.TestCase):
    """The sign-in check has to look in the profile's home, and say whose it is."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        self.one = profiles.create(root / "profiles", "one")
        self.two = profiles.create(root / "profiles", "two")
        self.runner = service(self.tmp.name, profiles={"one": self.one, "two": self.two},
                              default_profile="one", bot_profiles={"sales": "two"})
        self.seen = []

        def run(argv, **kwargs):
            """Only the profile `one` home holds a Codex login."""
            home = (kwargs.get("env") or {}).get("CODEX_HOME", "")
            self.seen.append((argv, home))
            signed_in = home.startswith(self.one["dir"])
            return type("R", (), {"returncode": 0 if signed_in else 1,
                                  "stdout": "Logged in using ChatGPT" if signed_in else "",
                                  "stderr": ""})()
        self.run = run

    def report(self):
        import runner.service as service_module
        original_run, original_which = service_module.subprocess.run, service_module.shutil.which
        service_module.subprocess.run = self.run
        service_module.shutil.which = lambda name: "/usr/local/bin/" + name
        try:
            assignments = [{"bot": "coo", "config": {"runtime": "codex"}},
                           {"bot": "sales", "config": {"runtime": "codex"}}]
            return assignments, self.runner.runtime_report(assignments)
        finally:
            service_module.subprocess.run, service_module.shutil.which = original_run, original_which

    def test_a_bot_is_blocked_only_by_its_own_profile(self):
        assignments, report = self.report()
        rows = {row["bot"]: row for row in self.runner.preflight(assignments, report)}
        self.assertEqual(rows["coo"]["profile"], "one")
        self.assertEqual(rows["sales"]["profile"], "two")
        self.assertEqual(rows["coo"]["problems"], ["Missing bot repository or AGENT.md"])
        self.assertIn("two: Codex login required", rows["sales"]["problems"])
