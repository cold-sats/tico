"""Allowance reads use fake transports and temporary profiles, never real accounts."""
import os
import tempfile
import threading
import time
import unittest
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import patch

from runner.profiles import Profile
from runner.subscription_refresh import read_codex, Refreshes


class Host:
    calls = []
    response = {}
    last = None
    def __init__(self, **kwargs):
        Host.last = self
        self.kwargs, self.stopped = kwargs, False
    def start(self):
        pass
    def request(self, method, **kwargs):
        Host.calls.append(method)
        return Host.response
    def stop(self):
        self.stopped = True


class Refresh(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.profile = Profile('sample', self.temp.name)
        Host.calls = []
        Host.response = {'rateLimits': {'limitId': 'codex', 'secondary': {
            'windowDurationMins': 10080, 'usedPercent': 42,
            'resetsAt': datetime.now(timezone.utc).timestamp() + 1000}}}

    @patch('runner.subscription_refresh.shutil.which', return_value='/fake/codex')
    def test_account_read_only_and_isolated_env(self, _):
        with patch.dict(os.environ, {'OPENAI_API_KEY': 'fake-key', 'CODEX_API_KEY': 'fake-key'}):
            result = read_codex(self.profile, Host)
        self.assertEqual(result['state'], 'succeeded')
        self.assertEqual(result['weekly']['used_percent'], 42)
        self.assertEqual(Host.calls, ['account/rateLimits/read'])
        self.assertTrue(Host.last.stopped)
        self.assertNotIn('OPENAI_API_KEY', Host.last.kwargs['env'])
        self.assertEqual(Host.last.kwargs['env']['CODEX_HOME'], str(self.profile.home('codex')))

    @patch('runner.subscription_refresh.shutil.which', return_value='/fake/codex')
    def test_no_weekly_and_other_bucket_are_unknown(self, _):
        Host.response['rateLimits']['secondary']['windowDurationMins'] = 300
        self.assertEqual(read_codex(self.profile, Host)['state'], 'unavailable')
        Host.response = {'rateLimitsByLimitId': {'different-model': {'secondary': {
            'windowDurationMins': 10080, 'usedPercent': 5}}}}
        self.assertEqual(read_codex(self.profile, Host)['state'], 'unavailable')

    @patch('runner.subscription_refresh.shutil.which', return_value='/fake/codex')
    def test_bad_percent_or_expired_reset_is_failed(self, _):
        for percent in (float('nan'), -1, 101, True, None):
            Host.response['rateLimits']['secondary']['usedPercent'] = percent
            self.assertEqual(read_codex(self.profile, Host)['state'], 'failed')
        Host.response['rateLimits']['secondary'].update(usedPercent=5, resetsAt=1)
        self.assertEqual(read_codex(self.profile, Host)['state'], 'failed')

    @patch('runner.subscription_refresh.shutil.which', return_value='/fake/codex')
    def test_exception_is_redacted_and_process_stopped(self, _):
        with patch.object(Host, 'request', side_effect=RuntimeError('fake-secret')):
            self.assertEqual(read_codex(self.profile, Host), {'state': 'failed'})
        self.assertTrue(Host.last.stopped)

    @patch('runner.subscription_refresh.shutil.which', return_value='/fake/codex')
    def test_shutdown_cancels_before_any_account_read(self, _):
        cancelled = threading.Event()
        cancelled.set()
        self.assertEqual(read_codex(self.profile, Host, cancelled), {'state': 'failed'})
        self.assertEqual(Host.calls, [])
        self.assertTrue(Host.last.stopped)

    def test_missing_profile_never_uses_default_and_one_worker(self):
        class Client:
            def __init__(self): self.posts = []
            def get(self, _): return {'refreshes': [{'id': 'r', 'profile': 'missing', 'runtime': 'codex'}]}
            def post(self, path, body): self.posts.append(body)
        runner = SimpleNamespace(config={'profiles': {'sample': {'dir': self.temp.name}}, 'default_profile': 'sample'}, client=Client())
        manager = Refreshes(runner)
        with patch('runner.subscription_refresh.read_codex') as read:
            manager.poll()
            manager.thread.join(1)
            manager.polled = -15
            manager.poll()
            self.assertEqual(runner.client.posts[0]['state'], 'unavailable')
            read.assert_not_called()
