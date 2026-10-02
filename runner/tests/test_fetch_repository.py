"""A bot placed on a computer that has never held it gets its repository from GitHub, or a readiness problem
that names why not (never just "Missing bot repository"). No network: GitHub is a local bare repository."""
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from clients.tico import APIError
from runner import git_credentials, service
from runner.service import Runner

REPO = "Acme/emp-helper"
RUNTIMES = {"codex": {"installed": True, "authenticated": "ready", "detail": "", "models": [],
                      "version": "codex 1.0", "controls": []}}
GIT = {"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "bot@acme.example", "GIT_COMMITTER_NAME": "t",
       "GIT_COMMITTER_EMAIL": "bot@acme.example", "PATH": "/usr/bin:/bin:/usr/local/bin:/opt/homebrew/bin", "HOME": "/tmp"}


def git(*args):
    subprocess.run(["git", *args], check=True, capture_output=True, env=GIT)


class Cloud:
    """The server's token route: a token, or the refusal it gives for a repository that is not on GitHub."""

    def __init__(self, refusal=None):
        self.refusal, self.asked = refusal, 0

    def post(self, path, body=None, **_):
        assert path == "github/token"
        self.asked += 1
        if self.refusal:
            raise self.refusal
        return {"configured": True, "token": "ghs_fake", "repository": REPO}


def entry(repository=REPO, runner_id="r1", generation=2):
    return {"bot": "helper", "runner_id": runner_id, "state": "active", "generation": generation,
            "repository": repository, "config": {"runtime": "codex", "model": "gpt-6-sol"}}


class FetchRepository(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.projects = self.root / "workspace"
        self.projects.mkdir()
        seed = self.root / "seed"
        seed.mkdir()
        git("-C", str(seed), "init", "-q", "-b", "main")
        (seed / "AGENT.md").write_text("# Helper\n")
        git("-C", str(seed), "add", "-A")
        git("-C", str(seed), "commit", "-q", "-m", "first")
        self.remote = self.root / "remote.git"
        git("clone", "-q", "--bare", str(seed), str(self.remote))
        real = git_credentials.clone_repository
        patcher = mock.patch.object(git_credentials, "clone_repository",
                                    lambda path, repository, env=None, **kw: real(path, repository, env, url=str(self.remote)))
        patcher.start()
        self.addCleanup(patcher.stop)

    def runner(self, cloud):
        runner = Runner.__new__(Runner)
        runner.config = {"url": "https://acme.test", "token": "t", "runner_id": "r1", "projects_dir": str(self.projects)}
        runner.client, runner._names = cloud, None
        return runner

    def test_clone_repository_fills_only_a_missing_or_empty_folder(self):
        target = self.projects / "emp-elsewhere"
        self.assertEqual(git_credentials.clone_repository(target, REPO), ("cloned", ""))
        self.assertTrue((target / "AGENT.md").is_file())
        state, why = git_credentials.clone_repository(target, REPO)
        self.assertEqual(state, "failed")
        self.assertIn("not an empty folder", why)

    def test_a_bot_assigned_here_with_no_checkout_gets_its_repository(self):
        cloud = Cloud()
        rows = {r["bot"]: r for r in self.runner(cloud).preflight([entry()], RUNTIMES)}
        self.assertEqual(rows["helper"]["problems"], [])
        self.assertTrue(rows["helper"]["repository_present"] and rows["helper"]["ready"])
        self.assertTrue((self.projects / "bot-helper" / "AGENT.md").is_file())
        self.assertEqual(cloud.asked, 1)
        self.assertIs(rows["helper"]["published"], True)          # the clone has its upstream: a move can follow

    def test_a_repository_that_is_not_on_github_is_named_not_called_missing(self):
        cloud = Cloud(APIError("github_repo_missing", f"The repository {REPO} does not exist yet on GitHub. "
                               "Create it with BotOps: `hub bot repo-create helper --empty`.", 409))
        runner = self.runner(cloud)
        first = runner.preflight([entry()], RUNTIMES)[0]
        self.assertFalse(first["ready"])
        self.assertIn(REPO, first["problems"][0])
        self.assertIn("does not exist yet on GitHub", first["problems"][0])
        self.assertNotEqual(first["problems"], ["Missing bot repository or AGENT.md"])
        # Every heartbeat is not another GitHub call: the answer stands until the retry time or a new assignment.
        runner.preflight([entry()], RUNTIMES)
        self.assertEqual(cloud.asked, 1)
        runner.preflight([entry(generation=3)], RUNTIMES)
        self.assertEqual(cloud.asked, 2)

    def test_a_computer_only_fetches_what_is_assigned_to_it(self):
        cloud = Cloud()
        row = self.runner(cloud).preflight([entry(runner_id="another-mac")], RUNTIMES)[0]
        self.assertEqual(row["problems"], ["Missing bot repository or AGENT.md"])
        self.assertEqual(cloud.asked, 0)
        self.assertFalse((self.projects / "bot-helper").exists())

    def test_a_checkout_that_exists_only_here_reports_unpublished(self):
        target = self.projects / "emp-helper"
        target.mkdir()
        git("-C", str(target), "init", "-q", "-b", "main")
        (target / "AGENT.md").write_text("# Helper\n")
        git("-C", str(target), "add", "-A")
        git("-C", str(target), "commit", "-q", "-m", "first")
        cloud = Cloud(APIError("github_repo_missing", f"The repository {REPO} does not exist yet on GitHub.", 409))
        runner = self.runner(cloud)
        row = runner.preflight([entry()], RUNTIMES)[0]
        self.assertTrue(row["ready"])
        self.assertIs(row["published"], False)
        # The runner tries to publish it while it is still assigned here, and says why it could not.
        self.assertIn("does not exist yet on GitHub", runner.publish_notes["helper"])
        self.assertTrue(runner.readiness([entry()], runtimes=RUNTIMES)["bots"]["helper"]["warnings"][0]
                        .startswith("GitHub history not published: "))
        self.assertIs(runner.readiness([entry()], runtimes=RUNTIMES)["bots"]["helper"]["published"], False)

    def test_a_branch_without_an_app_link_clones_the_original_using_personal_git(self):
        cloud = Cloud()
        runner = self.runner(cloud)
        assignment = entry(repository="")
        assignment["bot"] = "helper-ana"
        assignment["config"].update(shared_from="helper", repo="bot-helper", repo_url=str(self.remote))
        row = runner.preflight([assignment], RUNTIMES)[0]
        self.assertTrue(row["ready"] and row["repository_present"])
        self.assertEqual(cloud.asked, 0)
        self.assertEqual(runner.local_path("helper-ana"), self.projects / "bot-helper")
        self.assertEqual(runner.readiness([assignment], runtimes=RUNTIMES)["bots"]["helper-ana"]["repository"],
                         str(self.projects / "bot-helper"))

    def test_a_local_only_branch_reuses_the_originals_sibling_checkout(self):
        git("clone", "-q", str(self.remote), str(self.projects / "emp-helper"))
        runner = self.runner(Cloud())
        for repo in ("bot-helper", ""):
            assignment = entry(repository="")
            assignment["bot"] = "helper-ana"
            assignment["config"].update(shared_from="helper", repo=repo)
            with mock.patch.object(service, "clone_shared") as clone:
                row = runner.preflight([assignment], RUNTIMES)[0]
            self.assertTrue(row["ready"])
            self.assertEqual(runner.local_path("helper-ana"), self.projects / "emp-helper")
            clone.assert_not_called()

    def test_an_unknown_branch_address_is_named_and_retried_only_after_the_delay(self):
        runner = self.runner(Cloud())
        assignment = entry(repository="")
        assignment["config"].update(shared_from="original", repo="bot-original")
        with mock.patch.object(service, "clone_shared", wraps=service.clone_shared) as clone:
            first = runner.preflight([assignment], RUNTIMES)[0]
            self.assertIn("original repository bot-original", first["problems"][0])
            self.assertIn("address is unknown", first["problems"][0])
            runner.preflight([assignment], RUNTIMES)
            self.assertEqual(clone.call_count, 1)

    def test_a_branch_with_an_app_link_keeps_the_scoped_clone_path(self):
        assignment = entry()
        assignment["config"].update(shared_from="original", repo="bot-original")
        cloud = Cloud()
        with mock.patch.object(service, "clone_shared") as personal:
            row = self.runner(cloud).preflight([assignment], RUNTIMES)[0]
        self.assertTrue(row["ready"])
        self.assertEqual(cloud.asked, 1)
        personal.assert_not_called()

    def test_personal_github_clone_uses_safe_git_with_computer_login(self):
        target = self.projects / "bot-original"
        config = {"repo": "Acme/bot-original", "repo_url": "https://github.com/Acme/old-repo"}
        with mock.patch.object(service.isolation, "run", return_value=subprocess.CompletedProcess([], 0, "", "")) as run:
            self.assertEqual(service.clone_shared(target, config), "")
        command = run.call_args.args[0]
        self.assertEqual(command[-4:], ["clone", "--quiet", "https://github.com/Acme/bot-original", str(target)])
        self.assertIn("--no-optional-locks", command)
        self.assertIn("core.fsmonitor=false", command)
        self.assertTrue(any(arg.startswith('core.hooksPath=') for arg in command))
        self.assertEqual(run.call_args.kwargs["env"]["GIT_TERMINAL_PROMPT"], "0")

    def test_personal_clone_never_overwrites_an_existing_folder(self):
        target = self.projects / "bot-original"
        target.mkdir()
        (target / "draft.md").write_text("unfinished")
        with mock.patch.object(service.isolation, "run") as run:
            self.assertIn("left as it is", service.clone_shared(target, {"repo": "Acme/bot-original"}))
        run.assert_not_called()
        self.assertEqual((target / "draft.md").read_text(), "unfinished")

    def test_a_server_before_checkout_paths_still_receives_heartbeats(self):
        runner = self.runner(mock.Mock())
        runner.client.post.side_effect = [APIError("validation", "readiness.bots.helper.repository: Extra inputs are not permitted", 422), {}]
        body = {"readiness": {"bots": {"helper": {"ready": False, "repository": "/projects/bot-helper"}}}}
        self.assertEqual(runner.report_heartbeat(body), {})
        self.assertEqual(runner.client.post.call_count, 2)
        self.assertNotIn("repository", body["readiness"]["bots"]["helper"])
        self.assertGreater(runner._repository_after, 0)


if __name__ == "__main__":
    unittest.main()
