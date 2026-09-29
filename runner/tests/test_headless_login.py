"""Readiness accepts logins made on a box with no browser.

Each CLI is a stub script on PATH, so this checks what the runner does with the answers real
CLIs give, not the CLIs themselves.
"""
import os
import stat
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from runner.tests.test_profiles import service

CODEX = """#!/bin/sh
# Signed in only when CODEX_HOME holds auth.json, as `codex login --device-auth` leaves it.
[ "$1" = login ] && [ "$2" = status ] || { echo "codex-cli 9.9.9"; exit 0; }
if [ -f "${CODEX_HOME:-$HOME/.codex}/auth.json" ]; then echo "Logged in using $(cat "${CODEX_HOME:-$HOME/.codex}/auth.json")"; exit 0; fi
echo "Not logged in" >&2; exit 1
"""
CLAUDE = """#!/bin/sh
[ "$1" = auth ] || { echo "claude 9.9.9"; exit 0; }
echo '{"loggedIn": false}'
"""
CLAUDE_CRASH = """#!/bin/sh
[ "$1" = auth ] || { echo "claude 9.9.9"; exit 0; }
echo "not json"
"""


class HeadlessLogin(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.bin = self.root / "bin"
        self.bin.mkdir()
        (self.root / "secrets").mkdir()
        keep = {k: v for k, v in os.environ.items()
                if k not in ("CODEX_HOME", "CLAUDE_CODE_OAUTH_TOKEN", "ANTHROPIC_API_KEY", "GEMINI_API_KEY")}
        patcher = mock.patch.dict(os.environ, {**keep, "PATH": f"{self.bin}:/usr/bin:/bin",
                                               "HOME": str(self.root / "home")}, clear=True)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.runner = service(self.root)

    def stub(self, name, body):
        path = self.bin / name
        path.write_text(body)
        path.chmod(path.stat().st_mode | stat.S_IXUSR)

    def readiness(self, runtime, bots=()):
        assignments = [{"bot": bot, "config": {"runtime": runtime}} for bot in bots]
        return self.runner.runtime_readiness(runtime, assignments)

    def test_codex_device_login_in_codex_home_is_ready(self):
        self.stub("codex", CODEX)
        home = self.root / "codex-home"
        home.mkdir()
        self.assertEqual(self.readiness("codex")["authenticated"], "missing")
        (home / "auth.json").write_text("ChatGPT")
        with mock.patch.dict(os.environ, {"CODEX_HOME": str(home)}):
            row = self.readiness("codex")
        self.assertEqual((row["authenticated"], row["detail"], row["version"]),
                         ("ready", "Signed in with ChatGPT", "codex-cli 9.9.9"))

    def test_codex_api_key_login_is_named(self):
        self.stub("codex", CODEX)
        home = self.root / "codex-home"
        home.mkdir()
        (home / "auth.json").write_text("an API key")
        with mock.patch.dict(os.environ, {"CODEX_HOME": str(home)}):
            self.assertEqual(self.readiness("codex")["detail"], "Signed in with an API key")

    def test_claude_needs_a_login_or_a_token(self):
        self.stub("claude", CLAUDE)
        self.assertEqual(self.readiness("claude")["authenticated"], "missing")
        with mock.patch.dict(os.environ, {"CLAUDE_CODE_OAUTH_TOKEN": "tok"}):
            row = self.readiness("claude")
        self.assertEqual((row["authenticated"], row["detail"]), ("ready", "Signed in with CLAUDE_CODE_OAUTH_TOKEN"))
        with mock.patch.dict(os.environ, {"ANTHROPIC_API_KEY": "sk-x"}):
            self.assertEqual(self.readiness("claude")["authenticated"], "ready")

    def test_claude_token_in_shared_env_counts_even_if_status_is_unreadable(self):
        self.stub("claude", CLAUDE_CRASH)
        self.assertEqual(self.readiness("claude")["authenticated"], "failed")
        (self.root / "secrets" / "_shared.env").write_text("ANTHROPIC_API_KEY=sk-x\n")
        self.assertEqual(self.readiness("claude")["authenticated"], "ready")

    def test_gemini_key_from_shared_env_is_ready(self):
        self.stub("gemini", "#!/bin/sh\necho 0.0.1\n")
        self.assertEqual(self.readiness("gemini", ["coo"])["authenticated"], "missing")
        (self.root / "secrets" / "_shared.env").write_text("GEMINI_API_KEY=k\n")
        self.assertEqual(self.readiness("gemini", ["coo"])["authenticated"], "ready")
        with mock.patch.dict(os.environ, {"GEMINI_API_KEY": "k"}):
            (self.root / "secrets" / "_shared.env").unlink()
            self.assertEqual(self.readiness("gemini", ["coo"])["authenticated"], "ready")


if __name__ == "__main__":
    unittest.main()
