"""The runner counts a turn's tokens once and sends them with its result (runner/usage.py): the meter, the
hosts' increments, the subscription rule, and a server that predates the field."""
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from clients.tico import APIError
from runner.hosts.codex import CodexHost
from runner.hosts.fake import FakeHost
from runner.hosts.pi import usage_increment
from runner.service import Runner
from runner.tests.test_runner_resilience import FakeClient, attempt
from runner.usage import Meter, billing_for


class Counting(unittest.TestCase):
    def test_the_meter_sums_increments_and_splits_cached_from_uncached_input(self):
        meter = Meter()
        for event in ({"kind": "tokens", "usage": {"input": 1000, "cached": 800, "output": 50}},
                      {"kind": "tokens", "usage": {"input": 500, "cached": 0, "output": 25}},
                      {"kind": "tokens", "input": 99999, "output": 99999},         # a running total, not an increment
                      {"kind": "tokens", "usage": {"input": "x", "cached": None}}):
            meter.add(event)
        self.assertEqual(meter.report("gpt-6-sol", "codex", "api"),
                         {"input_tokens": 700, "cached_tokens": 800, "output_tokens": 75, "model": "gpt-6-sol",
                          "runtime": "codex", "billing": "api"})
        self.assertIsNone(Meter().report("m", "r"))                                 # nothing counted, nothing sent

    def test_codex_reports_running_totals_and_only_the_growth_is_counted(self):
        host = SimpleNamespace(_token_seen={})

        def update(total, last):
            row = lambda i, c, o: {"inputTokens": i, "cachedInputTokens": c, "outputTokens": o, "totalTokens": i + o}   # noqa: E731
            return CodexHost._token_increment(host, "th", {"total": row(*total), "last": row(*last)})
        # A resumed thread: 50k tokens from earlier turns are in the total, so the first report counts `last`.
        self.assertEqual(update((50_000, 40_000, 2_000), (1_000, 800, 100)), {"input": 1000, "cached": 800, "output": 100})
        self.assertEqual(update((52_000, 41_500, 2_150), (1_000, 700, 50)), {"input": 2000, "cached": 1500, "output": 150})
        self.assertEqual(update((52_000, 41_500, 2_150), (1_000, 700, 50)), {"input": 0, "cached": 0, "output": 0})     # a repeat

    def test_pi_counts_cache_reads_and_writes_as_input(self):
        self.assertEqual(usage_increment({"input": 10, "output": 5, "cacheRead": 200, "cacheWrite": 30}),
                         {"input": 240, "cached": 200, "output": 5})

    def test_only_a_plan_sign_in_is_a_subscription(self):
        cases = [("codex", "Signed in with ChatGPT", "subscription"), ("codex", "Signed in with an API key", "api"),
                 ("claude", "Signed in with claude.ai", "subscription"),
                 ("claude", "Signed in with CLAUDE_CODE_OAUTH_TOKEN", "subscription"),
                 ("claude", "Signed in with ANTHROPIC_API_KEY", "api"), ("claude", "Claude login required", "api"),
                 ("cursor", "Signed in to Cursor", "subscription"), ("cursor", "Signed in with CURSOR_API_KEY", "api"),
                 ("gemini", "Gemini API key configured", "api"), ("pi", "OpenRouter API key configured", "api"),
                 ("codex", "", "api")]
        for runtime, detail, expected in cases:
            self.assertEqual(billing_for(runtime, detail), expected, (runtime, detail))


class Sending(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        (root / "emp-coo").mkdir()
        self.config = {"url": "https://runner.example", "token": "machine", "projects_dir": str(root), "capacity": 1}

    def tearDown(self):
        self.tmp.cleanup()

    def runner(self, client):
        runner = Runner(self.config, Path(self.tmp.name) / "state", host_factory=lambda a, env: FakeHost(replies=["done"]),
                        client=client, push=lambda path, env=None: (0, ""))
        runner.renew_interval = 0.05
        return runner

    def run_turn(self, client, detail=None):
        runner = self.runner(client)
        if detail:
            runner.runtime_rows = {"codex": {"detail": detail}}
        row = attempt()
        row["config"]["model"] = "gpt-6-sol"
        runner.execute(row)
        return client.completion()

    def test_the_result_carries_the_turns_tokens_the_model_and_how_it_is_billed(self):
        done = self.run_turn(FakeClient())
        self.assertEqual(done["usage"], {"input_tokens": 100, "cached_tokens": 0, "output_tokens": 4, "model": "gpt-6-sol",
                                         "runtime": "codex", "billing": "api"})
        self.assertEqual(self.run_turn(FakeClient(), "Signed in with ChatGPT")["usage"]["billing"], "subscription")

    def test_a_server_from_before_usage_gets_the_result_again_without_it(self):
        class Old(FakeClient):
            def post(self, path, body=None, key=None):
                if path.endswith("/complete") and body and "usage" in body:
                    self.posts.append((path, body))
                    raise APIError("validation", "extra fields not permitted", 422, False)
                return super().post(path, body, key)
        client = Old()
        done = self.run_turn(client)
        result = [body for path, body in client.posts if path.endswith("/complete")][-1]      # a lease renewal may land after it
        self.assertNotIn("usage", result)
        self.assertEqual(result["text"], done["text"])
