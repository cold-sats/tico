"""The runner's loop behaviour (runner/service.py, runner/outage.py): quiet outage logging with
backoff, lease renewal that survives a cloud deploy, usage-limit completions, and the push of a
bot's commits after a completed turn. A `FakeHost` answers turns; `FakeClient` stands in for
the cloud and can be scripted to fail renewals."""
import json
import os
import subprocess
import tempfile
import threading
import time
import unittest
from concurrent.futures import Future
from pathlib import Path
from unittest import mock

from clients.tico import APIError
from runner import service
from runner.hosts.fake import FakeHost
from runner.outage import Outage, describe, span
from runner.service import Runner
from runner.state import BOT_THREAD

CLOUDFLARE = APIError("http_error", "HTTP 530: Error 1033: Cloudflare Tunnel error", 530, True)
GONE = APIError("conflict", "Attempt is no longer leased to this runner", 409, False)


class FakeClient:
    def __init__(self, renew_error=None):
        self.posts, self.renew_error, self.renewals = [], renew_error, 0

    def post(self, path, body=None, key=None):
        self.posts.append((path, body))
        if path == "jobs/claim":
            return {"attempt": None}
        if path.endswith("/renew"):
            self.renewals += 1
            if self.renew_error:
                raise self.renew_error
            return {"lease_seconds": 90}
        if path.endswith("/events"):
            return {"ack_seq": body["events"][-1]["seq"]}
        if path.endswith("/inputs"):
            return {"messages": []}
        return {}

    def get(self, path, **query):
        return {}

    def completion(self):
        return next(body for path, body in self.posts if path.endswith("/complete"))


def attempt(aid="att-1", bot="coo", lease_seconds=90):
    return {"id": aid, "bot": bot, "token": "turn-token", "lease_seconds": lease_seconds,
            "config": {"runtime": "codex", "max_run_minutes": 1},
            "conversation": {"id": "conv-1", "scope": "shared", "kind": "chat"},
            "message": {"id": "msg-1", "body": "hello", "from_actor": "human:ana"}, "history": []}


class Execution(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        (root / "emp-coo").mkdir()
        self.host = FakeHost(replies=["done"])
        self.config = {"url": "https://runner.example", "token": "machine", "projects_dir": str(root), "capacity": 1}

    def tearDown(self):
        self.tmp.cleanup()

    def runner(self, client, push=None):
        runner = Runner(self.config, Path(self.tmp.name) / "state", host_factory=lambda attempt, env: self.host,
                        client=client, push=push or (lambda path, env=None: (0, "")))
        runner.renew_interval = 0.05
        return runner

    def test_a_refused_key_is_held_until_a_credential_changes_or_the_recheck(self):
        runner = self.runner(FakeClient())
        (Path(self.tmp.name) / "secrets").mkdir()
        runner.reject("codex", "unexpected status 401 Unauthorized: Incorrect API key provided: sk-abcdef123456")
        held = runner.rejection("codex")
        self.assertTrue(held and "sk-abc" not in held["reason"])
        self.assertEqual(runner.last_heartbeat, float("-inf"), "the server hears of it at once")
        with mock.patch.object(Runner, "runtime_readiness", return_value={
                "installed": True, "authenticated": "ready", "version": "", "models": [], "controls": [], "detail": ""}):
            row = runner.runtime_report([])["codex"]
            self.assertEqual((row["authenticated"], row["rejected_at"]), ("rejected", held["at"]))
        (Path(self.tmp.name) / "secrets" / "_shared.env").write_text("OPENAI_API_KEY=new\n")
        self.assertIsNone(runner.rejection("codex"), "a changed secrets file lifts it")
        runner.reject("codex", "Incorrect API key")
        with mock.patch("runner.service.time.monotonic", return_value=time.monotonic() + service.REJECT_RECHECK_S + 1):
            self.assertIsNone(runner.rejection("codex"), "after a few minutes one turn may find out again")

    def test_a_due_self_update_exits_when_idle_and_drains_after_a_while(self):
        # The runner updates itself instead of asking a person to pull and restart.
        client = FakeClient()
        runner = self.runner(client)
        runner.capacity = 2
        runner.last_heartbeat = time.monotonic()
        busy = Future()
        runner.active["att-1"] = busy
        runner.restart_due = time.monotonic()
        with mock.patch("runner.service.log"):
            runner.tick()
        self.assertFalse(runner.stop.is_set(), "a running turn is never cut off")
        self.assertTrue(any(path == "jobs/claim" for path, _ in client.posts), "claims go on at first")
        # An automatic update never stops the other bots on this Mac; it waits for
        # a moment with nothing running, however long that takes.
        client.posts.clear()
        runner.next_claim = 0           # the idle back-off is not what this test is about
        runner.restart_due = time.monotonic() - service.SELF_UPDATE_DRAIN_S
        with mock.patch("runner.service.log"):
            runner.tick()
        self.assertTrue(any(path == "jobs/claim" for path, _ in client.posts), "an automatic update keeps claiming")
        self.assertFalse(runner.stop.is_set())
        # Only a restart a person asked for drains after a while.
        client.posts.clear()
        runner.restart_forced = True
        runner.next_claim = 0
        with mock.patch("runner.service.log"):
            runner.tick()
        self.assertFalse(any(path == "jobs/claim" for path, _ in client.posts), "a requested restart stops claiming after a while")
        self.assertFalse(runner.stop.is_set())
        busy.set_result(None)
        with mock.patch("runner.service.log"):
            runner.tick()
        self.assertTrue(runner.stop.is_set(), "quiet: exit so the supervisor starts the new code")
        self.assertFalse(any(path == "jobs/claim" for path, _ in client.posts))

    def test_a_worker_exception_does_not_kill_claiming_and_is_recovered(self):
        client = FakeClient()
        runner = self.runner(client)
        runner.state.record(attempt())
        failed = Future()
        failed.set_exception(RuntimeError("worker crashed"))
        runner.active["att-1"] = failed
        runner.last_heartbeat = time.monotonic()
        with mock.patch("runner.service.log") as log:
            runner.tick()
        self.assertEqual(runner.active, {})
        self.assertTrue(any(path == "jobs/claim" for path, _ in client.posts))
        log.assert_called_once()
        runner.recover_output()
        self.assertEqual(client.completion()["outcome"], "interrupted")
        self.assertEqual(runner.state.unfinished(), [])

    def test_a_turn_outlives_a_cloud_outage_longer_than_its_lease(self):
        client = FakeClient(renew_error=CLOUDFLARE)
        runner = self.runner(client)
        self.host.hold_next_turn()
        worker = threading.Thread(target=runner.execute, args=(attempt(lease_seconds=16),))
        with mock.patch("runner.outage.log"):
            worker.start()
            deadline = time.monotonic() + 5
            while not self.host.turn_of and time.monotonic() < deadline:
                time.sleep(0.02)
            time.sleep(1.5)                                    # the 1 s lease deadline passes while renew keeps failing
            self.assertTrue(client.renewals >= 5)
            self.assertTrue(worker.is_alive())
            self.host.complete(next(iter(self.host.turn_of)), "finished anyway")
            worker.join(timeout=10)
        self.assertFalse(worker.is_alive())
        self.assertEqual(self.host.interrupts, [])
        self.assertEqual(client.completion()["outcome"], "completed")
        self.assertEqual(client.completion()["text"], "finished anyway")

    def test_a_definite_refusal_to_renew_interrupts_the_turn(self):
        client = FakeClient(renew_error=GONE)
        runner = self.runner(client)
        self.host.hold_next_turn()
        post = client.post

        def renew_after_turn_starts(path, body=None, key=None):
            # Runtime preparation can exceed the 50 ms renewal interval on CI.
            # Exercise loss during an active turn, not the separate pre-start fence.
            if path.endswith("/renew") and not self.host.turn_of:
                return {"lease_seconds": 90}
            return post(path, body, key)

        with mock.patch.object(client, "post", side_effect=renew_after_turn_starts):
            runner.execute(attempt())
        self.assertEqual(client.completion()["outcome"], "interrupted")
        self.assertTrue(self.host.interrupts)


def git(path, *args, env=None):
    return subprocess.run(["git", "-C", str(path), *args], check=True, capture_output=True, text=True, env=env)


class Pushing(unittest.TestCase):
    """A bare `origin` and a clone with a local commit stand in for GitHub and the emp-* checkout."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.env = {**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@x", "GIT_COMMITTER_NAME": "t",
                    "GIT_COMMITTER_EMAIL": "t@x", "GIT_CONFIG_GLOBAL": "/dev/null", "GIT_CONFIG_SYSTEM": "/dev/null"}
        self.origin, self.repo = root / "origin.git", root / "emp-coo"
        git(root, "init", "-q", "--bare", str(self.origin), env=self.env)
        # Ubuntu's git still names the unborn branch master; the checkouts below expect main.
        git(self.origin, "symbolic-ref", "HEAD", "refs/heads/main", env=self.env)
        git(root, "clone", "-q", str(self.origin), str(self.repo), env=self.env)
        git(self.repo, "checkout", "-q", "-b", "main", env=self.env)
        git(self.repo, "commit", "-q", "--allow-empty", "-m", "init", env=self.env)
        git(self.repo, "push", "-q", "-u", "origin", "main", env=self.env)
        self.commit("memory")
        self.host = FakeHost(replies=["done"])
        self.config = {"url": "https://runner.example", "token": "machine", "projects_dir": str(root),
                       "capacity": 1, "repos": {"coo": str(self.repo)}}
        self.client = FakeClient()
        self.runner = Runner(self.config, root / "state", host_factory=lambda attempt, env: self.host, client=self.client)

    def tearDown(self):
        self.tmp.cleanup()

    def commit(self, name, path=None):
        path = path or self.repo
        (path / name).write_text(name)
        git(path, "add", name, env=self.env)
        git(path, "commit", "-q", "-m", name, env=self.env)

    def head(self, path, ref="HEAD"):
        return git(path, "rev-parse", ref, env=self.env).stdout.strip()

    def test_a_diverged_origin_is_left_for_a_person_and_said_once(self):
        other = Path(self.tmp.name) / "other"
        git(self.tmp.name, "clone", "-q", "-b", "main", str(self.origin), str(other), env=self.env)
        self.commit("elsewhere", other)
        git(other, "push", "-q", "origin", "main", env=self.env)
        before = self.head(self.origin, "main")
        with mock.patch.dict(os.environ, self.env), mock.patch("runner.service.log") as log:
            self.runner.execute(attempt())
            self.runner.push(self.repo)                          # the hourly cap: a second failure is quiet
        self.assertEqual(self.client.completion()["outcome"], "completed")
        self.assertEqual(self.head(self.origin, "main"), before)
        messages = [call.args[0] for call in log.call_args_list]
        self.assertTrue(any("pull before coo turn failed" in m and "using the local tree" in m for m in messages), messages)
        self.assertEqual(messages[-1], "Tico runner: emp-coo has 1 unpushed commits and push failed (non-fast-forward); leaving it for a person")
        self.assertEqual(len(messages), 2)

def _git(cwd, *args):
    subprocess.run(["git", "-C", str(cwd), *args], check=True, capture_output=True,
                   env={**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.test",
                        "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@example.test"})


def _behind_checkout(tmp, change="README"):
    """An origin with one commit the checkout does not have yet; returns the checkout and its HEAD."""
    origin, work, clone = Path(tmp, "origin.git"), Path(tmp, "work"), Path(tmp, "clone")
    _git(tmp, "init", "-q", "--bare", "-b", "main", str(origin))
    _git(tmp, "clone", "-q", str(origin), str(work))
    (work / "README").write_text("one\n")
    _git(work, "add", ".")
    _git(work, "commit", "-qm", "one")
    _git(work, "push", "-q", "origin", "HEAD:main")
    _git(tmp, "clone", "-q", "-b", "main", str(origin), str(clone))
    first = subprocess.run(["git", "-C", str(clone), "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()
    Path(work, change).parent.mkdir(parents=True, exist_ok=True)
    Path(work, change).write_text("two\n")
    _git(work, "add", ".")
    _git(work, "commit", "-qm", "two")
    _git(work, "push", "-q", "origin", "HEAD:main")
    return clone, first


def test_self_update_fast_forwards_a_clean_checkout_and_asks_for_a_restart():
    with tempfile.TemporaryDirectory() as tmp, mock.patch("runner.service.log"):
        clone, first = _behind_checkout(tmp)
        assert service.self_update(clone, running=first) == (True, "")
        assert Path(clone, "README").read_text() == "two\n"
        assert service.self_update(clone, running=first) == (True, ""), "pulled but not restarted still restarts"


SUPERVISOR_VARS = ("XPC_SERVICE_NAME", "TICO_SUPERVISED", "TICO_RUNNER_SELF_UPDATE")


def clean_env(**extra):
    env = {k: v for k, v in os.environ.items() if k not in SUPERVISOR_VARS}
    env.update(extra)
    return mock.patch.dict(os.environ, env, clear=True)


def test_only_a_supervisor_lets_the_runner_exit_to_update():
    for extra in ({"XPC_SERVICE_NAME": "team.tico-bot"}, {"TICO_SUPERVISED": "1"}):
        with clean_env(**extra):
            assert service.supervised() is True
            assert service.under_supervisor({}) is True
            assert service.under_supervisor({"self_update": False}) is False
            with mock.patch.dict(os.environ, {"TICO_RUNNER_SELF_UPDATE": "0"}):
                assert service.under_supervisor({}) is False
    for extra in ({}, {"XPC_SERVICE_NAME": "0"}, {"XPC_SERVICE_NAME": "application.com.other"},
                  {"TICO_SUPERVISED": "0"}):
        with clean_env(**extra):
            assert service.supervised() is False
            assert service.under_supervisor({}) is False


if __name__ == "__main__":
    unittest.main()


def antigravity(**over):
    a = attempt()
    a["config"] = {"runtime": "gemini", "harness": "antigravity", "model": "gemini-3.8-flash",
                   "reasoning_effort": "low", "max_run_minutes": 1}
    a["conversation"] = {"id": "private-ana", "scope": "personal", "kind": "chat"}
    a["principal"] = "human:ana"
    a.update(over)
    return a


def with_fallback(row=None):
    row = row or antigravity()
    row["config"] = {**row["config"], "fallback": {
        "harness": "gemini", "model": "gemini-3.8-flash", "reasoning_effort": "low"}}
    return row


class Fallback(unittest.TestCase):
    """A configured fallback harness reruns the turn when the primary is unavailable."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        (root / "emp-coo").mkdir()
        self.config = {"url": "https://runner.example", "token": "machine", "projects_dir": str(root), "capacity": 1}
        self.calls = []
        self.hosts = {"antigravity": FakeHost(), "gemini": FakeHost(replies=["Answered on the fallback"])}
        self.hosts["antigravity"].fail_next_turn("UNAVAILABLE (code 503): No capacity available for model gemini-3.8-flash-low")

    def tearDown(self):
        self.tmp.cleanup()

    def factory(self, attempt, env):
        which = attempt.get("fallback") or attempt["config"].get("harness")
        self.calls.append((which, attempt["config"].get("harness"), env["HUB_TOKEN"]))
        return self.hosts[which]

    def runner(self, client):
        runner = Runner(self.config, Path(self.tmp.name) / "state", host_factory=self.factory, client=client,
                        push=lambda path, env=None: (0, ""))
        runner.renew_interval = 0.05
        return runner

    def test_a_limited_turn_runs_on_the_configured_fallback(self):
        client = FakeClient()
        with mock.patch.dict(os.environ, {"GEMINI_API_KEY": "test-key-1234567890"}), \
                mock.patch("runner.service.log") as log:
            runner = self.runner(client)
            runner.execute(with_fallback())
        completion = client.completion()
        self.assertEqual(completion["outcome"], "completed")
        self.assertEqual(completion["text"], "Answered on the fallback")
        self.assertEqual(completion["fallback"], "gemini")
        self.assertNotIn("limited", completion)
        log.assert_called_once_with("Tico runner: coo: antigravity unavailable; ran the turn on gemini")
        self.assertEqual([c[0] for c in self.calls], ["antigravity", "gemini"])
        self.assertEqual(self.calls[1][1], "gemini")
        self.assertTrue(self.calls[0][2].startswith("tico-file:") and self.calls[1][2] == "turn-token")
        settings = next(iter(self.hosts["gemini"].threads.values()))["settings"]
        self.assertEqual((settings["model"], settings["effort"], settings["cwd"]),
                         ("gemini-3.8-flash", "low", str(Path(self.tmp.name) / "emp-coo")))
        self.assertEqual(settings["env"]["GEMINI_API_KEY"], "test-key-1234567890")
        self.assertIn("hello", self.hosts["gemini"].prompts[0][1])
        self.assertEqual(runner.warm.entries, {})
        self.assertFalse(self.hosts["antigravity"].alive())
        self.assertEqual(runner.state.unfinished(), [])
        kinds = [json.loads(p)["text"] for (k, p) in self.events(runner, "diagnostic")]
        self.assertIn("antigravity unavailable; running this turn on gemini", kinds)

    @staticmethod
    def events(runner, kind):
        with runner.state.connect() as c:
            return [(r["kind"], r["payload"]) for r in c.execute("SELECT kind,payload FROM events WHERE kind=?", (kind,))]


class ThreadContinuity(unittest.TestCase):
    """A bot keeps one thread. Nothing here ends it; the runtime compacts it when it fills."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        (root / "emp-coo").mkdir()
        self.config = {"url": "https://runner.example", "token": "machine", "projects_dir": str(root), "capacity": 1}
        self.hosts = []

    def tearDown(self):
        self.tmp.cleanup()

    def factory(self, attempt, env):
        host = FakeHost(replies=["one", "two", "three"])
        if getattr(self, "factory_fails", False):
            self.factory_fails = False
            host.fail_next_turn("the model returned garbage")
        self.hosts.append(host)
        return host

    def runner(self):
        runner = Runner(self.config, Path(self.tmp.name) / "state", host_factory=self.factory, client=FakeClient(),
                        push=lambda path, env=None: (0, ""))
        runner.renew_interval = 0.05
        return runner

    def test_every_turn_resumes_the_same_thread(self):
        runner = self.runner()
        with mock.patch("runner.service.log") as log:
            runner.execute(attempt("a1"))
            runner.execute(attempt("a2"))
            runner.execute(attempt("a3"))
            self.assertEqual(len(self.hosts[1].resumes), 1)
            self.assertEqual(len(self.hosts[2].resumes), 1)     # heavy or not, it is the same thread
            log.assert_not_called()
            first = self.hosts[0].prompts[0][0]
            self.assertEqual(next(iter(self.hosts[2].threads)), first)
            self.assertEqual(runner.state.session("coo", BOT_THREAD, "codex"), first)

class RefusedReplies(unittest.TestCase):
    """The COO, 2026-09-28: a reply with Codex's local file links into another bot's repository
    was refused on completion twice, and the job read as a run that stopped partway."""
    CODEX = ("Task [`1b874fee`](file:///Volumes/x/projects/emp-coo/state.md#L13-L20) is open "
             "([`emp-legal/reports/2026-09-28-inbound-findings.md`](file:///Volumes/x/projects/emp-legal/reports/f.md)). "
             "See emp-legal/reports/a.md, emp-coo/knowledge/needs.md and ../secrets/_shared.env. "
             "PR https://github.com/acme/emp-legal/pull/3.")

    def test_the_scrubbed_reply_passes_the_hubs_own_rule_and_keeps_the_rest(self):
        from backend import hubdb
        self.assertEqual(hubdb.classify(self.CODEX, where="message", actor="bot:coo"), "escape")
        clean = service.scrub_reply(self.CODEX, "coo")
        self.assertNotEqual(hubdb.classify(clean, where="message", actor="bot:coo"), "escape")
        self.assertIn("Task `1b874fee` is open", clean)
        self.assertIn("emp-coo/knowledge/needs.md", clean, "its own repository is not an escape")
        self.assertIn("(a file in legal's repository), emp-coo", clean, "the comma survives")
        self.assertNotIn("file://", clean)
        self.assertEqual(service.scrub_reply("All clear.", "coo"), "All clear.")

    def test_a_refused_reply_settles_the_attempt_instead_of_letting_the_lease_lapse(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        (Path(tmp.name) / "emp-coo").mkdir()
        client = FakeClient()
        plain = client.post

        def post(path, body=None, key=None):
            if path.endswith("/complete") and body["outcome"] == "completed":
                client.posts.append((path, body))
                raise APIError("escape", "The message includes a secrets path or another bot’s workspace path.", 403, False)
            return plain(path, body, key)
        client.post = post
        runner = Runner({"url": "https://runner.example", "token": "machine", "projects_dir": tmp.name, "capacity": 1},
                        Path(tmp.name) / "state", host_factory=lambda a, env: FakeHost(replies=["done"]),
                        client=client, push=lambda path, env=None: (0, ""))
        with mock.patch("runner.service.log"):
            runner.execute(attempt())
        completes = [body for path, body in client.posts if path.endswith("/complete")]
        self.assertEqual([c["outcome"] for c in completes], ["completed", "failed"])
        self.assertIn("refused this turn's reply", completes[1]["text"])
