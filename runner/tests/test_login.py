"""Browser sign-in on the runner: the relay, the pasted code, cancel and timeout, and no leaks.

Each CLI is a stub script on PATH that prints what the real one prints (checked against
codex 0.157 and Claude Code 2.1.284), so this exercises the runner's handling, not the CLIs.
"""
import json
import os
import stat
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

from runner import profiles
from runner.login import Logins, parse
from runner.tests.test_profiles import service

JWT = "eyJhbGciOiJSUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.c2lnbmF0dXJlc2lnbmF0dXJl"
CREDENTIAL = "credential-body-" + "Zq9" * 12

CODEX = f"""#!/bin/sh
home="${{CODEX_HOME:-$HOME/.codex}}"
if [ "$1 $2" = "login status" ]; then
  [ -f "$home/auth.json" ] && {{ echo "Logged in using ChatGPT"; exit 0; }}
  echo "Not logged in" >&2; exit 1
fi
[ "$1 $2" = "login --device-auth" ] || {{ echo "codex-cli 9.9.9"; exit 0; }}
echo $$ > "$TICO_PIDFILE"
printf '\\nWelcome to Codex [v\\033[90m9.9.9\\033[0m]\\n\\n1. Open this link in your browser\\n   \\033[94mhttps://auth.example/codex/device\\033[0m\\n\\n'
printf '2. Enter this one-time code \\033[90m(expires in 15 minutes)\\033[0m\\n   \\033[94mAB12-CD345\\033[0m\\n\\n'
echo "debug token: {JWT}"
sleep "${{TICO_DELAY:-1}}"
mkdir -p "$home"; echo '{CREDENTIAL}' > "$home/auth.json"
echo "Successfully logged in"
"""

# Claude Code draws with a terminal: hyperlinks are OSC 8 and the prompt has no newline.
CLAUDE = f"""#!/bin/sh
dir="${{CLAUDE_CONFIG_DIR:-$HOME/.claude}}"
if [ "$1" = auth ] && [ "$2" = status ]; then
  [ -f "$dir/creds" ] && echo '{{"loggedIn": true, "authMethod": "claude.ai"}}' || echo '{{"loggedIn": false}}'
  exit 0
fi
[ "$1 $2" = "auth login" ] || {{ echo "claude 9.9.9"; exit 0; }}
echo $$ > "$TICO_PIDFILE"
printf 'Opening browser to sign in\\342\\200\\246\\nIf the browser did not open, visit: '
printf '\\033]8;id=1;https://claude.example/authorize?state=abc\\007https://claude.example/auth\\033]8;;\\007\\n'
printf 'Paste\\033[8Gcode\\033[13Ghere > '
read -r code
if [ "$code" = "good-code#state-1234" ]; then mkdir -p "$dir"; echo '{CREDENTIAL}' > "$dir/creds"; echo "Login successful"; exit 0; fi
echo "Login failed"; exit 1
"""


class Client:
    def __init__(self):
        self.posts, self.wanted = [], []

    def get(self, path):
        return {"logins": list(self.wanted)}

    def post(self, path, body=None):
        self.posts.append((path, body))
        return {}


class Login(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.bin = self.root / "bin"
        self.bin.mkdir()
        (self.root / "secrets").mkdir()
        self.pidfile = self.root / "pid"
        keep = {k: v for k, v in os.environ.items()
                if k not in ("CODEX_HOME", "CLAUDE_CONFIG_DIR", "CLAUDE_CODE_OAUTH_TOKEN", "ANTHROPIC_API_KEY")}
        patcher = mock.patch.dict(os.environ, {**keep, "PATH": f"{self.bin}:/usr/bin:/bin", "HOME": str(self.root / "home"),
                                               "CODEX_HOME": str(self.root / "codex-home"),
                                               "CLAUDE_CONFIG_DIR": str(self.root / "claude-home"),
                                               "TICO_PIDFILE": str(self.pidfile)}, clear=True)
        patcher.start()
        self.addCleanup(patcher.stop)
        quiet = mock.patch("runner.login.log")
        quiet.start()
        self.addCleanup(quiet.stop)
        self.runner = service(self.root)
        self.runner.client, self.runner.last_heartbeat = Client(), 99
        self.logins = Logins(self.runner)
        self.addCleanup(self.logins.stop)

    def stub(self, name, body):
        path = self.bin / name
        path.write_text(body)
        path.chmod(path.stat().st_mode | stat.S_IXUSR)

    def drive(self, until, timeout=20):
        """Poll the way the runner's loop does until `until()` holds."""
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            self.logins.poll(force=True)
            if until():
                return
            time.sleep(0.1)
        self.fail("gave up waiting; reports: " + json.dumps([b for _, b in self.runner.client.posts])[-800:])

    def states(self, lid=None):
        return [b["state"] for path, b in self.runner.client.posts if lid is None or lid in path]

    def alive(self):
        try:
            os.kill(int(self.pidfile.read_text()), 0)
            return True
        except (OSError, ValueError):
            return False

    def test_codex_link_and_code_are_relayed_and_success_needs_readiness(self):
        self.stub("codex", CODEX)
        client = self.runner.client
        client.wanted = [{"id": "l1", "runtime": "codex", "profile": ""}]
        self.drive(lambda: "signed_in" in self.states())
        waiting = next(b for _, b in client.posts if b["state"] == "waiting")
        self.assertEqual((waiting["url"], waiting["code"]), ("https://auth.example/codex/device", "AB12-CD345"))
        self.assertTrue(any("one-time code" in line for line in waiting["lines"]))
        self.assertEqual(self.runner.last_heartbeat, 0)            # readiness is re-reported now
        self.assertTrue((self.root / "codex-home" / "auth.json").is_file())

    def test_nothing_secret_leaves_the_machine(self):
        self.stub("codex", CODEX)
        self.runner.client.wanted = [{"id": "l1", "runtime": "codex", "profile": ""}]
        self.drive(lambda: "signed_in" in self.states())
        sent = json.dumps(self.runner.client.posts)
        for secret in (JWT, "eyJ", CREDENTIAL, "auth.json"):
            self.assertNotIn(secret, sent)
        self.assertIn("[redacted]", sent)

    def test_a_pasted_code_is_typed_into_the_cli_and_never_reported(self):
        self.stub("claude", CLAUDE)
        client = self.runner.client
        client.wanted = [{"id": "c1", "runtime": "claude", "profile": ""}]
        self.drive(lambda: any(b["state"] == "waiting" and b["url"] for _, b in client.posts))
        first = next(b for _, b in client.posts if b["state"] == "waiting")
        self.assertEqual(first["url"], "https://claude.example/authorize?state=abc")
        self.assertTrue(any("Paste code here" in line for line in first["lines"]))
        client.wanted = [{"id": "c1", "runtime": "claude", "profile": "", "code": "good-code#state-1234"}]
        self.drive(lambda: "signed_in" in self.states())
        self.assertTrue(any(b.get("code_taken") for _, b in client.posts))
        sent = json.dumps(client.posts)
        for secret in ("good-code", CREDENTIAL, "state-1234"):
            self.assertNotIn(secret, sent)

    def test_a_wrong_code_is_a_failure_with_the_cli_words(self):
        self.stub("claude", CLAUDE)
        client = self.runner.client
        client.wanted = [{"id": "c1", "runtime": "claude", "profile": ""}]
        self.drive(lambda: "waiting" in self.states())
        client.wanted = [{"id": "c1", "runtime": "claude", "profile": "", "code": "wrong-code#nope-0000"}]
        self.drive(lambda: "failed" in self.states())
        last = client.posts[-1][1]
        self.assertEqual(last["state"], "failed")
        self.assertTrue(any("Login failed" in line for line in last["lines"]))
        self.assertNotIn("wrong-code", json.dumps(client.posts))

    def test_cancel_from_the_server_kills_the_cli(self):
        self.stub("codex", CODEX)
        with mock.patch.dict(os.environ, {"TICO_DELAY": "60"}):
            self.runner.client.wanted = [{"id": "l1", "runtime": "codex", "profile": ""}]
            self.drive(lambda: "waiting" in self.states())
            self.assertTrue(self.alive())
            self.runner.client.wanted = []                          # the server dropped it
            self.drive(lambda: not self.alive(), timeout=10)
        self.assertNotIn("failed", self.states())
        self.assertFalse((self.root / "codex-home" / "auth.json").exists())

    def test_the_login_is_killed_when_time_runs_out(self):
        self.stub("codex", CODEX)
        self.logins.lifetime = 1
        with mock.patch.dict(os.environ, {"TICO_DELAY": "60"}):
            self.runner.client.wanted = [{"id": "l1", "runtime": "codex", "profile": ""}]
            self.drive(lambda: "failed" in self.states(), timeout=10)
        self.assertIn("in time", self.runner.client.posts[-1][1]["message"])
        self.assertFalse(self.alive())

    def test_a_command_that_exits_without_signing_in_fails(self):
        self.stub("codex", CODEX.replace("mkdir -p \"$home\"; echo", ": #"))
        self.runner.client.wanted = [{"id": "l1", "runtime": "codex", "profile": ""}]
        self.drive(lambda: "failed" in self.states())
        self.assertIn("still not signed in", self.runner.client.posts[-1][1]["message"])

    def test_one_login_at_a_time_per_runtime(self):
        self.stub("codex", CODEX)
        with mock.patch.dict(os.environ, {"TICO_DELAY": "60"}):
            self.runner.client.wanted = [{"id": "l1", "runtime": "codex", "profile": ""},
                                         {"id": "l2", "runtime": "codex", "profile": ""}]
            self.drive(lambda: "failed" in self.states("l2") and "waiting" in self.states("l1"))
            self.assertIn("already running", next(b for p, b in self.runner.client.posts if "l2" in p)["message"])
            self.assertNotIn("failed", self.states("l1"))

    def test_the_login_runs_in_the_profile_home_the_readiness_check_reads(self):
        self.stub("codex", CODEX)
        entry = profiles.create(self.root / "profiles", "acme")
        self.runner.config.update({"profiles": {"acme": entry}, "default_profile": "acme"})
        self.runner.client.wanted = [{"id": "l1", "runtime": "codex", "profile": ""}]
        self.drive(lambda: "signed_in" in self.states())
        self.assertTrue((Path(entry["dir"]) / "codex" / "auth.json").is_file())
        self.assertFalse((self.root / "codex-home" / "auth.json").exists())

    def test_unknown_profile_or_runtime_is_refused_without_running_anything(self):
        self.stub("codex", CODEX)
        self.runner.client.wanted = [{"id": "l1", "runtime": "codex", "profile": "nope"},
                                     {"id": "l2", "runtime": "gemini", "profile": ""}]
        self.drive(lambda: len(self.runner.client.posts) >= 2)
        self.assertEqual(self.states(), ["failed", "failed"])
        self.assertFalse(self.pidfile.exists())

    def test_a_missing_cli_is_reported(self):
        self.runner.client.wanted = [{"id": "l1", "runtime": "codex", "profile": ""}]
        self.drive(lambda: "failed" in self.states())
        self.assertIn("not installed", self.runner.client.posts[-1][1]["message"])


class Parse(unittest.TestCase):
    def test_codex_output_as_printed(self):
        raw = ("\nWelcome to Codex [v\x1b[90m0.157.1\x1b[0m]\n\n1. Open this link in your browser\n"
               "   \x1b[94mhttps://auth.openai.com/codex/device\x1b[0m\n\n2. Enter this one-time code "
               "\x1b[90m(expires in 15 minutes)\x1b[0m\n   \x1b[94m3U9T-B3TD5\x1b[0m\n\n")
        got = parse(raw)
        self.assertEqual((got["url"], got["code"]), ("https://auth.openai.com/codex/device", "3U9T-B3TD5"))

    def test_claude_output_with_cursor_moves_and_wrapped_hyperlinks(self):
        url = "https://claude.com/cai/oauth/authorize?code=true&client_id=abc&state=" + "x" * 43
        link = lambda part: f"\x1b]8;id=1;{url}\x07{part}\x1b]8;;\x07\r\r\n"
        raw = ("\x1b[2GOpening\x1b[12Gbrowser\r\r\n" + link(url[:60]) + link(url[60:]) +
               "\x1b[2GPaste\x1b[8Gcode\x1b[13Ghere\x1b[18Gif\x1b[21Gprompted\x1b[30G>\r\r\n")
        got = parse(raw)
        self.assertEqual(got["url"], url)
        self.assertTrue(got["prompt"])
        self.assertIn("Paste code here if prompted >", got["lines"])
        self.assertFalse(any("x" * 20 in line for line in got["lines"]))     # no link fragments

    def test_an_unknown_format_still_shows_what_the_cli_said(self):
        got = parse("Please visit the portal and approve this device.\nThen wait here.\n")
        self.assertEqual((got["url"], got["code"]), ("", ""))
        self.assertEqual(got["lines"], ["Please visit the portal and approve this device.", "Then wait here."])

    def test_a_link_still_arriving_is_not_taken_for_the_whole_link(self):
        self.assertEqual(parse("open https://auth.example/de")["url"], "")

    def test_tokens_are_scrubbed_from_relayed_lines(self):
        got = parse(f"Your token: sk-ant-oat01-{'Ab1' * 12}\nid {JWT}\nblob {'QUJD' * 12}\nfine line here\n")
        text = " ".join(got["lines"])
        for secret in ("sk-ant", "eyJ", "QUJD"):
            self.assertNotIn(secret, text)
        self.assertIn("fine line here", text)

    def test_an_echoed_pasted_code_is_hidden(self):
        got = parse("Paste code > good-code#state-1234\nLogin successful\n", hide="good-code#state-1234")
        self.assertEqual(got["lines"], ["Login successful"])


if __name__ == "__main__":
    unittest.main()
