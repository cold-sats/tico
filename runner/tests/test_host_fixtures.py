"""Harness wire formats both runner engines replay (runner/tests/fixtures/<harness>/*.jsonl).

Each fixture is what the harness writes on stdout for one turn; `<name>.expected.json` is the events the
Python host makes of it, with the per-run thread and turn ids left out for Claude. The Rust runner's host
tests (runner-rs/src/hosts) replay the same files against the same expected events, so the two engines
read a harness the same way. `python -m runner.tests.test_host_fixtures --write` refreshes the expected files.
"""

import json
import sys
import unittest
from pathlib import Path

from runner.hosts.claude import ClaudeHost
from runner.hosts.codex import CodexHost

FIXTURES = Path(__file__).parent / "fixtures"


class _Claude:
    """`claude -p` for one turn: the fixture's lines on stdout once the prompt is written, exit 0 on stdin close."""

    def __init__(self, lines):
        import queue
        self.lines, self.out, self.pid, self.rc = lines, queue.Queue(), 4243, None
        self.stdin, self.stdout = self, iter(self.out.get, None)

    def write(self, text):
        for line in self.lines:
            self.out.put(line + "\n")
        self.lines = []

    def flush(self):
        pass

    def close(self):
        if self.rc is None:
            self.rc = 0
            self.out.put(None)

    def poll(self):
        return self.rc

    def terminate(self):
        self.close()

    kill = terminate

    def wait(self, timeout=None):
        return self.rc if self.rc is not None else 0


def claude_events(path):
    lines = [line for line in path.read_text().splitlines() if line.strip()]
    host = ClaudeHost(bot="acme", spawn=lambda argv, **kw: _Claude(lines),
                      version=lambda: "2.1.296 (Claude Code)", help=lambda: "--autocompact")
    host.start()
    thread = host.start_thread("acme", {"cwd": "/tmp", "env": {}})
    host.start_turn(thread, "hello")
    host._reader.join(timeout=5)
    return [{k: v for k, v in ev.items() if k not in ("thread_id", "turn_id")} for ev in host.drain()]


def codex_events(path):
    host = CodexHost(config={}, spawn=lambda *a, **k: None)
    for line in path.read_text().splitlines():
        if line.strip():
            host._on_message(json.loads(line))
    return host.drain()


READERS = {"claude": claude_events, "codex": codex_events}


def cases():
    for harness, read in READERS.items():
        for path in sorted((FIXTURES / harness).glob("*.jsonl")):
            yield harness, path, read


class HostFixtures(unittest.TestCase):
    def test_every_fixture_gives_its_expected_events(self):
        for harness, path, read in cases():
            with self.subTest(fixture=f"{harness}/{path.name}"):
                expected = json.loads(path.with_suffix(".expected.json").read_text())
                self.assertEqual(read(path), expected)


if __name__ == "__main__" and "--write" in sys.argv:
    for harness, path, read in cases():
        path.with_suffix(".expected.json").write_text(json.dumps(read(path), indent=1) + "\n")
