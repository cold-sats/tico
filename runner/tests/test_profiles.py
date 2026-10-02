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

    def test_server_profile_overrides_local_and_missing_profile_warns(self):
        config = self.runner.config
        self.assertEqual(profiles.select(config, 'sales', 'one').name, 'one')
        self.assertEqual(profiles.select(config, 'sales', 'absent').name, 'two')
        self.assertEqual(profiles.missing(config, 'absent'), 'profile absent not on this computer')
        assignments, report = self.report()
        assignments[1]['profile'] = 'absent'
        row = self.runner.preflight(assignments, report)[1]
        self.assertIn('profile absent not on this computer', row['warnings'])
        self.assertEqual(row['profile'], 'two')

    def test_reports_all_profiles_and_sign_in_state(self):
        self.runner.runtime_readiness = lambda runtime, assignments, profile: {
            'authenticated': 'ready' if profile.name == 'one' else 'missing'}
        rows = self.runner.profile_report()
        self.assertEqual([r['name'] for r in rows], ['one', 'two'])
        self.assertTrue(rows[0]['runtimes']['codex']['signed_in'])
        self.assertFalse(rows[1]['runtimes']['claude']['signed_in'])

    def test_named_profile_is_persisted_without_replacing_local_assignments(self):
        import json
        path = Path(self.tmp.name) / 'runner.json'
        path.write_text(json.dumps(self.runner.config))
        self.runner.config_path = path
        self.runner.add_profile('engineering')
        stored = json.loads(path.read_text())
        self.assertEqual(stored['default_profile'], 'one')
        self.assertEqual(stored['bot_profiles'], {'sales': 'two'})
        self.assertIn('engineering', stored['profiles'])
        self.assertEqual(path.stat().st_mode & 0o777, 0o600)
        self.assertEqual(Path(stored['profiles']['engineering']['dir']).stat().st_mode & 0o777, 0o700)

    def test_old_server_rejects_profiles_without_losing_heartbeat(self):
        from clients.tico import APIError
        class Client:
            def post(self, path, body):
                if 'profiles' in body:
                    raise APIError('validation', 'Extra inputs are not permitted: profiles', 422)
                return {'server_time': 'now'}
        self.runner.client = Client()
        body = {'readiness': {}, 'profiles': [{'name': 'one', 'runtimes': {}}]}
        self.assertEqual(self.runner.report_heartbeat(body), {'server_time': 'now'})
        self.assertNotIn('profiles', body)

    def test_claim_profile_controls_environment_and_host_home(self):
        from unittest import mock
        work = {**BOT, 'profile': 'one'}
        self.runner.credential_environment = lambda *args: {'CLAUDE_CONFIG_DIR': '/operator/.claude'}
        self.runner.vault_values = {}
        env = self.runner.environment(work)
        self.assertEqual(env['CODEX_HOME'], str(Path(self.one['dir']) / 'codex'))
        with mock.patch('runner.hosts.codex.mcp_disable_config') as disable:
            self.runner.make_host(work, env)
        disable.assert_called_once_with(Path(self.one['dir']) / 'codex')
        work['config'] = {'runtime': 'claude'}
        env = self.runner.environment(work)
        self.assertEqual(env['HOME'], str(Path(self.one['dir']) / 'claude'))
        self.assertEqual(env['CLAUDE_CONFIG_DIR'], str(Path(self.one['dir']) / 'claude/.claude'))

    def test_readiness_reports_the_actual_local_fallback_profile(self):
        assignments, report = self.report()
        self.runner.tools = None
        checks = self.runner.preflight(assignments, report)
        body = self.runner.readiness(assignments, checks, report)
        self.assertEqual(body['bots']['sales']['profile'], 'two')
        self.assertEqual(body['bots']['sales']['sign_in'], 'missing')

    def test_named_profile_cannot_write_through_a_workspace_symlink(self):
        root = Path(self.tmp.name)
        destination = root / 'other-directory'
        destination.mkdir()
        (root / '.profiles').symlink_to(destination, target_is_directory=True)
        with self.assertRaises(ValueError):
            self.runner.add_profile('engineering')
        self.assertEqual(list(destination.iterdir()), [])
