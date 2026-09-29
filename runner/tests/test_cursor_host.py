"""The Cursor host (runner/hosts/cursor.py) against recorded `stream-json` output from Cursor Agent
2026.09.28. No process is started: a fake Popen replays the fixtures."""
import json
import subprocess
import time
import unittest

from runner.hosts.base import HostError
from runner.hosts.cursor import CHAT_ID, CursorHost, message_text, model_for, usage_tokens

CHAT = "99315a93-89be-4411-a713-a5f615272ab0"
SUCCESS = [
    {"type": "system", "subtype": "init", "apiKeySource": "login", "cwd": "/repo", "session_id": CHAT, "model": "Auto",
     "permissionMode": "default"},
    {"type": "user", "message": {"role": "user", "content": [{"type": "text", "text": "hi"}]}, "session_id": CHAT},
    {"type": "thinking", "subtype": "delta", "text": "hmm", "session_id": CHAT, "timestamp_ms": 1},
    {"type": "tool_call", "subtype": "started", "call_id": "c1", "tool_call": {"readToolCall": {"args": {"path": "a"}}},
     "session_id": CHAT},
    {"type": "tool_call", "subtype": "completed", "call_id": "c1", "tool_call": {"readToolCall": {"args": {"path": "a"}}},
     "session_id": CHAT},
    {"type": "assistant", "message": {"role": "assistant", "content": [{"type": "text", "text": "first"}]}, "session_id": CHAT},
    {"type": "assistant", "message": {"role": "assistant", "content": [{"type": "text", "text": "ok"}]}, "session_id": CHAT},
    {"type": "result", "subtype": "success", "duration_ms": 6776, "is_error": False, "result": "ok", "session_id": CHAT,
     "request_id": "r", "usage": {"inputTokens": 16166, "outputTokens": 521, "cacheReadTokens": 1152, "cacheWriteTokens": 0}},
]
FAILED = [SUCCESS[0], {"type": "result", "subtype": "error", "is_error": True, "result": "You've hit your usage limit",
                       "session_id": CHAT}]


class FakeProc:
    def __init__(self, lines, rc=0):
        self.lines, self.rc, self.sent, self.closed = lines, rc, [], False
        self.pid = 1
        outer = self

        class Stdin:
            def write(self, text):
                outer.sent.append(text)

            def close(self):
                outer.closed = True
        self.stdin = Stdin()
        self.stdout = iter([json.dumps(line) + "\n" for line in lines] + ["not json\n"])

    def wait(self, timeout=None):
        return self.rc

    def terminate(self):
        pass

    kill = terminate


def host(lines, rc=0, chat=CHAT):
    procs, runs = [], []

    def spawn(argv, **kwargs):
        procs.append((argv, kwargs, FakeProc(lines, rc)))
        return procs[-1][2]

    def run(argv, **kwargs):
        runs.append((argv, kwargs))
        return subprocess.CompletedProcess(argv, 0, chat + "\n", "")
    h = CursorHost(bot="coo", spawn=spawn, run=run)
    h.start()
    return h, procs, runs


def events(h, until="status", state="idle", timeout=3):
    got, end = [], time.monotonic() + timeout
    while time.monotonic() < end:
        got += h.drain()
        if any(e["kind"] == until and e.get("state") == state and len(got) > 2 for e in got):
            return got
        time.sleep(0.01)
    raise AssertionError(got)


class Cursor(unittest.TestCase):
    settings = {"cwd": "/repo", "model": "cursor-auto", "env": {"HOME": "/home/x", "CURSOR_API_KEY": "k"}}

    def test_a_turn_streams_messages_tools_tokens_and_the_final_answer(self):
        h, procs, runs = host(SUCCESS)
        tid = h.start_thread("coo", self.settings)
        self.assertEqual(tid, CHAT)
        self.assertEqual(runs[0][0], ["cursor-agent", "create-chat"])
        turn = h.start_turn(tid, "do the thing")
        got = events(h)
        argv, kwargs, proc = procs[0]
        self.assertEqual(argv[:1] + argv[1:4], ["cursor-agent", "-p", "--output-format", "stream-json"])
        for flag in ("--force", "--trust"):
            self.assertIn(flag, argv)
        self.assertEqual(argv[argv.index("--model") + 1], "auto")            # the catalog id maps to the CLI's
        self.assertEqual(argv[argv.index("--resume") + 1], CHAT)
        self.assertEqual(argv[argv.index("--workspace") + 1], "/repo")
        self.assertEqual(proc.sent, ["do the thing"])                        # the prompt is on stdin, not argv
        self.assertTrue(proc.closed)
        self.assertNotIn("do the thing", argv)
        self.assertEqual(kwargs["cwd"], "/repo")
        self.assertEqual(kwargs["env"]["CURSOR_API_KEY"], "k")
        kinds = [(e["kind"], e.get("text") or e.get("status") or e.get("name")) for e in got]
        self.assertIn(("tool", "readToolCall"), kinds)
        self.assertIn(("message", "first"), kinds)
        final = [e for e in got if e["kind"] == "message" and e["final"]]
        self.assertEqual([e["text"] for e in final], ["ok"])
        tokens = next(e for e in got if e["kind"] == "tokens")
        self.assertEqual((tokens["input"], tokens["output"], tokens["total"]), (17318, 521, 17839))
        done = [e for e in got if e["kind"] == "turn_completed"]
        self.assertEqual([(e["turn_id"], e["status"]) for e in done], [(turn, "completed")])

    def test_a_later_turn_and_a_restart_resume_the_same_chat(self):
        h, procs, runs = host(SUCCESS)
        h.resume_thread("coo", CHAT, self.settings)
        h.start_turn(CHAT, "again")
        events(h)
        self.assertEqual(runs, [], "no new chat is made when one is resumed")
        self.assertEqual(procs[0][0][procs[0][0].index("--resume") + 1], CHAT)

    def test_an_error_result_fails_the_turn_and_flags_a_usage_limit(self):
        h, procs, _ = host(FAILED, rc=1)
        tid = h.start_thread("coo", self.settings)
        h.start_turn(tid, "x")
        got = events(h)
        failed = next(e for e in got if e["kind"] == "turn_failed")
        self.assertEqual(failed["error"], "You've hit your usage limit")
        self.assertTrue(failed["limit"])
        self.assertFalse(any(e["kind"] == "turn_completed" for e in got))

    def test_a_process_that_ends_without_a_result_is_a_failed_turn(self):
        h, procs, _ = host(SUCCESS[:2], rc=0)
        tid = h.start_thread("coo", self.settings)
        h.start_turn(tid, "x")
        got = events(h)
        self.assertTrue(any(e["kind"] == "turn_failed" for e in got))

    def test_one_turn_at_a_time_no_steering_and_a_missing_chat_is_refused(self):
        h, procs, _ = host(SUCCESS)
        tid = h.start_thread("coo", self.settings)
        with self.assertRaises(HostError):
            h.steer(tid, "t", "x")
        with self.assertRaises(HostError):
            h.start_turn("nonesuch", "x")
        h.stop()
        with self.assertRaises(HostError):
            h.start_turn(tid, "x")

    def test_create_chat_that_fails_is_a_host_error(self):
        h = CursorHost(run=lambda argv, **kw: subprocess.CompletedProcess(argv, 1, "", "not logged in"))
        h.start()
        with self.assertRaisesRegex(HostError, "not logged in"):
            h.start_thread("coo", self.settings)

    def test_helpers(self):
        self.assertEqual((model_for(""), model_for("default"), model_for("cursor-auto"), model_for("gpt-5.3-codex")),
                         ("auto", "auto", "auto", "gpt-5.3-codex"))
        self.assertEqual(usage_tokens(None), (0, 0, 0))
        self.assertEqual(message_text({"content": [{"type": "text", "text": "a"}, {"type": "image"}, {"type": "text", "text": "b"}]}), "ab")
        self.assertTrue(CHAT_ID.fullmatch(CHAT))


if __name__ == "__main__":
    unittest.main()


class Wiring(unittest.TestCase):
    """`runtime: cursor` is a runtime like the others: preflight accepts it, readiness reports it,
    and the runner builds its host."""

    def test_preflight_no_longer_calls_cursor_retired(self):
        from unittest import mock
        from clients import preflight
        lines = []

        class Report(preflight.Report):
            def line(self, level, text):
                lines.append((level, text))
        entry = {"name": "coo", "runtime": "cursor", "model": "cursor-auto"}
        with mock.patch.object(preflight.REG, "merge_employee", side_effect=lambda e, d: e), \
                mock.patch.object(preflight.shutil, "which", return_value="/tools/bin/cursor-agent"):
            preflight.check_runtime(Report("coo"), entry, {})
        self.assertFalse([text for _, text in lines if "retired" in text], lines)
        self.assertIn(("PASS", "runtime: `cursor-agent` on PATH at /tools/bin/cursor-agent"), lines)

    def test_readiness_reads_the_cursor_login_and_the_api_key(self):
        import os
        import tempfile
        from pathlib import Path
        from unittest import mock
        from runner import service as service_module
        from runner.tests.test_profiles import service

        def run(output, code=0):
            return lambda argv, **kw: subprocess.CompletedProcess(argv, code, output, "")
        with tempfile.TemporaryDirectory() as tmp:
            runner = service(tmp)
            (Path(tmp) / "secrets").mkdir()
            with mock.patch.object(service_module.shutil, "which", lambda name: "/bin/" + name), \
                    mock.patch.dict(os.environ, {}, clear=False):
                os.environ.pop("CURSOR_API_KEY", None)
                for output, code, expected in (("✓ Logged in as a@b.c", 0, "ready"), ("Not logged in", 1, "missing")):
                    with mock.patch.object(service_module.subprocess, "run", run(output, code)):
                        row = runner.runtime_readiness("cursor", [])
                    self.assertEqual(row["authenticated"], expected)
                    self.assertTrue(row["installed"])
                self.assertEqual(row["models"], ["cursor-auto"])
                (Path(tmp) / "secrets" / "_shared.env").write_text("CURSOR_API_KEY=k\n")
                with mock.patch.object(service_module.subprocess, "run", run("Not logged in", 1)):
                    self.assertEqual(runner.runtime_readiness("cursor", [])["authenticated"], "ready")
            self.assertEqual(service_module.harness_tools.executable_for("cursor"), "cursor-agent")

    def test_the_runner_builds_a_cursor_host(self):
        from runner.tests.test_profiles import service
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            runner = service(tmp)
            runner.profile = lambda bot: None
            host = runner.make_host({"bot": "coo", "config": {"runtime": "cursor"}}, {})
            self.assertIsInstance(host, CursorHost)
