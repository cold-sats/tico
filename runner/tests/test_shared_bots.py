"""Shared bots on the runner (backend/shared_bots.py): a copy works in the shared repository's checkout, starts
every turn level with its remote without losing a lesson, pushes over another copy's push, and runs from a clean
Claude setup."""
import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from runner import service
from runner.hosts import base
from runner.service import Runner
from runner.tests.test_hosts import ClaudeProcess, make_claude

ENV = {**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.com", "GIT_COMMITTER_NAME": "t",
       "GIT_COMMITTER_EMAIL": "t@example.com", "GIT_CONFIG_GLOBAL": "/dev/null", "GIT_CONFIG_SYSTEM": "/dev/null"}
COPY = {"shared_from": "architect", "repo": "bot-architect", "runtime": "claude"}


def git(path, *args):
    return subprocess.run(["git", "-C", str(path), *args], check=True, capture_output=True, text=True, env=ENV)


class TwoCopies(unittest.TestCase):
    """The remote is a bare repository; Ana's and Ben's computers each have a clone of it."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.origin, self.ana, self.ben = root / "origin.git", root / "ana", root / "ben"
        git(root, "init", "-q", "--bare", "-b", "main", str(self.origin))
        git(root, "clone", "-q", str(self.origin), str(self.ana))
        git(self.ana, "checkout", "-q", "-b", "main")
        self.write(self.ana, "AGENT.md", "rules\n")
        git(self.ana, "push", "-q", "-u", "origin", "main")
        git(root, "clone", "-q", str(self.origin), str(self.ben))
        self.env_patch = mock.patch.dict(os.environ, {k: ENV[k] for k in ENV if k.startswith("GIT_")})
        self.env_patch.start()

    def tearDown(self):
        self.env_patch.stop()
        self.tmp.cleanup()

    def write(self, path, name, text):
        (path / name).parent.mkdir(parents=True, exist_ok=True)
        (path / name).write_text(text)
        git(path, "add", name)
        git(path, "commit", "-q", "-m", name)

    def test_a_turn_starts_from_what_the_other_copy_pushed_and_a_conflict_loses_nothing(self):
        self.write(self.ana, "memory/learnings.md", "ana's lesson\n")
        git(self.ana, "push", "-q")
        self.write(self.ben, "memory/decisions.md", "ben's unpushed lesson\n")
        self.assertEqual(service.sync_shared(self.ben), "")
        self.assertEqual((self.ben / "memory/learnings.md").read_text(), "ana's lesson\n")
        self.assertEqual((self.ben / "memory/decisions.md").read_text(), "ben's unpushed lesson\n")

        self.write(self.ana, "memory/learnings.md", "ana's second lesson\n")
        git(self.ana, "push", "-q")
        self.write(self.ben, "memory/learnings.md", "ben's lesson\n")
        problem = service.sync_shared(self.ben)
        self.assertIn("conflict", problem)
        self.assertEqual((self.ben / "memory/learnings.md").read_text(), "ben's lesson\n")
        self.assertFalse((self.ben / ".git" / "rebase-merge").exists())
        (self.ben / "scratch.md").write_text("half done")
        self.assertIn("uncommitted", service.sync_shared(self.ben))
        self.assertIn("Before anything else", Runner.shared_lines("architect-ben", COPY, problem)[-1])

    def test_a_push_another_copy_beat_is_rebased_and_pushed_again(self):
        self.write(self.ana, "memory/learnings.md", "ana's lesson\n")
        git(self.ana, "push", "-q")
        self.write(self.ben, "memory/decisions.md", "ben's lesson\n")
        runner = Runner({"url": "https://runner.example", "token": "m", "projects_dir": self.tmp.name},
                        Path(self.tmp.name) / "state", host_factory=lambda a, e: None, client=mock.Mock())
        self.assertFalse(runner.push(self.ben))
        self.assertTrue(runner.push(self.ben, shared=True))
        self.assertEqual(git(self.ben, "rev-parse", "HEAD").stdout, git(self.origin, "rev-parse", "main").stdout)


class Copy(unittest.TestCase):
    def test_a_copy_works_in_the_shared_repositorys_checkout_and_keeps_its_paths_in_a_reply(self):
        runner = Runner({"url": "https://runner.example", "token": "m", "projects_dir": "/w"}, tempfile.mkdtemp(),
                        host_factory=lambda a, e: None, client=mock.Mock())
        self.assertEqual(runner.local_path("architect-ben", COPY), Path("/w/bot-architect"))
        self.assertEqual(runner.local_path("architect-ben"), Path("/w/bot-architect"), "remembered for callers without it")
        known = {"bot-architect", "bot-legal"}
        text = "See bot-architect/memory/learnings.md and bot-legal/x.md"
        scrubbed = service.scrub_reply(text, "architect-ben", known, own="bot-architect")
        self.assertIn("bot-architect/memory/learnings.md", scrubbed)
        self.assertNotIn("bot-legal/", scrubbed)
        lines = " ".join(Runner.shared_lines("architect-ben", COPY))
        self.assertIn("a copy of `architect`", lines)
        self.assertIn("never who asked", lines)


class CleanClaude(unittest.TestCase):
    def test_a_shared_bot_runs_without_the_operators_own_claude_setup_and_no_other_bot_changes(self):
        with tempfile.TemporaryDirectory() as repo:
            Path(repo, ".mcp.json").write_text(json.dumps({"mcpServers": {"docs": {"command": "docs-server"}}}))
            host = make_claude()
            settings = base.settings(repo, env={"HUB_TOKEN": "t0k", "HUB_API_URL": "https://tico.acme.example",
                                                "PATH": "/bin"}, shared=True)
            host.start_turn(host.start_thread("cpo", settings), "hello")
            proc = ClaudeProcess.instances[-1]
            argv = proc.argv
            self.assertEqual(argv[argv.index("--setting-sources") + 1], "project,local")
            self.assertIn("--strict-mcp-config", argv)
            servers = json.loads(argv[argv.index("--mcp-config") + 1])["mcpServers"]
            self.assertEqual(sorted(servers), ["docs", "hub"])
            self.assertEqual(proc.kwargs["env"]["CLAUDE_CODE_DISABLE_AUTO_MEMORY"], "1")
            host.stop()
        host = make_claude()
        host.start_turn(host.start_thread("cpo", base.settings("/tmp/bot-cpo", env={"PATH": "/bin"})), "hello")
        self.assertNotIn("--setting-sources", ClaudeProcess.instances[-1].argv)
        self.assertNotIn("CLAUDE_CODE_DISABLE_AUTO_MEMORY", ClaudeProcess.instances[-1].kwargs["env"])
        host.stop()
