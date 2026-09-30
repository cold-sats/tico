"""A granted secret never leaves the runner as text (runner/redact.py): not in events or the reply, not in the
log, not in a file the turn left in the repository, and a commit that holds one is not pushed."""
import base64
import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from urllib.parse import quote

from runner import redact
from runner.hosts.fake import FakeHost
from runner.service import Runner
from runner.tests.test_runner_resilience import FakeClient, attempt

SECRET = "jira-token/ABC def+123=="
TAIL = "AtlassianApiToken12345"
BASIC = "ana@acme.example:" + TAIL


class Scrub(unittest.TestCase):
    def test_a_secret_is_replaced_in_the_forms_it_turns_up_in(self):
        r = redact.Redactor([SECRET, BASIC])
        b64 = base64.b64encode(BASIC.encode()).decode()
        text = f"a {SECRET} b {quote(SECRET, safe='')} c Basic {b64} d {TAIL} e"
        out = r.scrub_text(text)
        for leak in (SECRET, quote(SECRET, safe=""), b64, TAIL):
            self.assertNotIn(leak, out)
        self.assertEqual(out.count(redact.MASK), 4)
        self.assertIn("Basic " + redact.MASK, out)

    def test_json_keeps_its_shape_and_short_or_common_values_are_ignored(self):
        r = redact.Redactor([SECRET, "short", "localhost", "aaaaaaaaaaaa", ""])
        payload = {"kind": "tool", "n": 3, "ok": True, "items": [{"text": f"x {SECRET}"}, None, "short"]}
        self.assertEqual(r.scrub_json(payload),
                         {"kind": "tool", "n": 3, "ok": True, "items": [{"text": "x " + redact.MASK}, None, "short"]})
        self.assertEqual(r.scrub_text("short localhost aaaaaaaaaaaa"), "short localhost aaaaaaaaaaaa")
        self.assertIsNone(redact.for_turn({"PATH": "/usr/bin", "NAME": "x"}, ["short", "localhost"]))

    def test_an_internal_error_fails_closed(self):
        r = redact.Redactor([SECRET])

        class Broken:
            def sub(self, *_):
                raise RuntimeError("boom")
        r.pattern = Broken()
        self.assertEqual(r.scrub_text("has " + SECRET), redact.ERROR)


class Turn(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.repo = self.root / "emp-coo"
        self.repo.mkdir()
        self.git("init", "-q", "-b", "main")
        (self.repo / "state.md").write_text("start\n")
        self.git("add", "-A")
        self.git("commit", "-q", "-m", "init")

    def tearDown(self):
        self.tmp.cleanup()

    def git(self, *args):
        env = {"PATH": "/usr/bin:/bin:/usr/local/bin:/opt/homebrew/bin", "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@e.x",
               "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@e.x", "HOME": self.tmp.name, "GIT_CONFIG_NOSYSTEM": "1"}
        return subprocess.run(["git", "-C", str(self.repo), *args], check=True, capture_output=True, text=True, env=env).stdout

    def run_turn(self, act, reply):
        """One turn on a fake host; `act()` is what the bot does in its checkout. Returns (posts, pushes, published, runner)."""
        client, pushes, published = FakeClient(), [], []
        host = FakeHost(replies=[reply])
        real_start = host.start_turn

        def start_turn(*a, **k):
            act()
            return real_start(*a, **k)
        host.start_turn = start_turn
        runner = Runner({"url": "https://runner.example", "token": "m", "projects_dir": str(self.root), "capacity": 1},
                        self.root / "state", host_factory=lambda att, env: host, client=client,
                        push=lambda path, env=None: pushes.append(str(path)) or (0, ""))
        runner.environment = lambda att: {"JIRA_BASIC_AUTH": SECRET, "PATH": "/usr/bin:/bin"}
        runner.vault_values["att-1"] = [SECRET]
        from unittest import mock
        with mock.patch("runner.files_publish.after_turn", lambda r, a, root, pushed=False, skip=(): published.append((pushed, list(skip)))), \
                mock.patch.object(Runner, "publish", lambda *a, **k: None):
            runner.execute(attempt(bot="coo"))
        return client, pushes, published

    def test_nothing_with_the_secret_is_posted_written_or_pushed(self):
        def act():
            (self.repo / "state.md").write_text(f"token is {SECRET}\n")
            (self.repo / "reports").mkdir()
            (self.repo / "reports" / "r.md").write_text(f"see {SECRET}")
            (self.repo / "blob.bin").write_bytes(b"\0\1" + SECRET.encode())
        client, pushes, published = self.run_turn(act, f"Connected with {SECRET}")
        wire = json.dumps(client.posts)
        self.assertNotIn(SECRET, wire)
        self.assertIn(redact.MASK, client.completion()["text"])
        self.assertIn("left out of the commit: blob.bin (contains a secret)", client.completion()["text"])
        self.assertNotIn(SECRET, (self.repo / "state.md").read_text())
        self.assertNotIn(SECRET, (self.repo / "reports" / "r.md").read_text())
        self.assertEqual(published, [(True, ["blob.bin"])])
        self.assertEqual(len(pushes), 1)

    def test_a_commit_that_holds_the_secret_is_not_pushed(self):
        def act():
            (self.repo / "state.md").write_text(f"token is {SECRET}\n")
            self.git("commit", "-q", "-am", "oops")
        client, pushes, published = self.run_turn(act, "done")
        self.assertEqual(pushes, [])
        self.assertIn("not pushed", client.completion()["text"])
        self.assertNotIn(SECRET, json.dumps(client.posts))

    def test_the_log_never_carries_a_running_turns_secret(self):
        r = redact.Redactor([SECRET])
        r.register("a1")
        try:
            self.assertNotIn(SECRET, redact.scrub_log("failed: " + SECRET))
        finally:
            redact.release("a1")
        self.assertIn(SECRET, redact.scrub_log("failed: " + SECRET))


if __name__ == "__main__":
    unittest.main()
