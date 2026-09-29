"""A runner follows its server's release: the checkout update against a temp repository, and the runner's decisions."""
import subprocess

import pytest

from clients.tico import APIError
from runner import release_update as ru


def sh(cwd, *args):
    return subprocess.run(args, cwd=cwd, check=True, capture_output=True, text=True).stdout.strip()


def commit(repo, name, text="x", message=None):
    (repo / name).parent.mkdir(parents=True, exist_ok=True)
    (repo / name).write_text(text)
    sh(repo, "git", "add", "-A")
    sh(repo, "git", "-c", "user.name=t", "-c", "user.email=t@example.com", "commit", "-qm", message or name)
    return sh(repo, "git", "rev-parse", "HEAD")


@pytest.fixture
def repos(tmp_path):
    """A public repo with releases 0.1.0 and 0.2.0 (0.2.0 changes the dependencies) plus a checkout on main at 0.1.0."""
    public = tmp_path / "public"
    public.mkdir()
    sh(public, "git", "init", "-q", "-b", "main")
    commit(public, "app.py", "one")
    commit(public, "backend/requirements.txt", "httpx==1\n")
    sh(public, "git", "tag", "v0.1.0")
    commit(public, "app.py", "two")
    commit(public, "backend/requirements.txt", "httpx==2\n")
    sh(public, "git", "tag", "v0.2.0")
    commit(public, "app.py", "unreleased main")
    checkout = tmp_path / "checkout"
    sh(tmp_path, "git", "clone", "-q", str(public), "checkout")
    sh(checkout, "git", "reset", "-q", "--hard", "v0.1.0")
    sh(checkout, "git", "tag", "-d", "v0.2.0")       # the checkout has not seen that release yet
    state = tmp_path / "state"
    state.mkdir()
    return public, checkout, state


class Calls:
    def __init__(self, healthy=(True,), install_error=""):
        self.restarts, self.installs, self.checks = 0, [], []
        self.answers, self.install_error = list(healthy), install_error

    def restart(self):
        self.restarts += 1

    def install(self, root, old, new):
        self.installs.append((old, new))
        return self.install_error if len(self.installs) == 1 else ""

    def healthy(self, commit, since):
        self.checks.append(commit)
        return self.answers.pop(0) if self.answers else True


def run_apply(checkout, state, version="0.2.0", calls=None, **kw):
    calls = calls or Calls()
    result = ru.apply(checkout, version, state, install=calls.install, restart=calls.restart, healthy=calls.healthy, **kw)
    return result, calls


def head(repo):
    return sh(repo, "git", "rev-parse", "HEAD")


def test_versions_compare_like_the_server_does():
    assert ru.behind("0.1.0", "0.2.0") and ru.behind("", "0.2.0") and ru.behind("dev", "0.2.0")
    assert not ru.behind("0.2.0", "0.2.0") and not ru.behind("0.3.0", "0.2.0") and not ru.behind("0.1.0", "")
    assert ru.behind("0.10.0-rc.1", "0.10.0") and not ru.behind("0.10.0", "0.10.0-rc.1")
    assert ru.key("v1.2.3") == ru.key("1.2.3") and ru.key("main") is None
    assert ru.key("0.9.0") < ru.key("0.10.0") < ru.key("1.0.0-rc.1") < ru.key("1.0.0")


def test_the_release_a_checkout_is_on(repos):
    public, checkout, state = repos
    assert ru.checkout_release(checkout) == "0.1.0"
    sh(checkout, "git", "checkout", "-q", "origin/main")
    assert ru.checkout_release(checkout) == ""               # main after a release is not a release


def test_update_switches_to_the_servers_tag_not_main(repos):
    public, checkout, state = repos
    result, calls = run_apply(checkout, state)
    assert result["state"] == "healthy" and ru.checkout_release(checkout) == "0.2.0"
    assert head(checkout) == sh(public, "git", "rev-parse", "v0.2.0") != head(public)   # main moved on; the runner did not
    assert calls.restarts == 1 and calls.installs == [(sh(checkout, "git", "rev-parse", "v0.1.0"), head(checkout))]
    assert calls.checks == [head(checkout)]
    assert ru.read_status(state)["state"] == "healthy" and ru.read_status(state)["target"] == "0.2.0"


def test_a_checkout_with_changes_is_refused_and_left_alone(repos):
    public, checkout, state = repos
    (checkout / "app.py").write_text("my local edit")
    before = head(checkout)
    result, calls = run_apply(checkout, state)
    assert result["state"] == "blocked" and "1 changed file" in result["error"]
    assert (checkout / "app.py").read_text() == "my local edit" and head(checkout) == before
    assert calls.restarts == 0 and ru.read_status(state)["state"] == "blocked"
    assert sh(checkout, "git", "branch", "--show-current") == "main"


def test_untracked_files_do_not_stop_an_update(repos):
    public, checkout, state = repos
    (checkout / "notes.txt").write_text("keep me")
    assert run_apply(checkout, state)[0]["state"] == "healthy"
    assert (checkout / "notes.txt").read_text() == "keep me"


def test_a_missing_release_is_reported_and_nothing_changes(repos):
    public, checkout, state = repos
    before = head(checkout)
    result, calls = run_apply(checkout, state, "0.9.0")
    assert result["state"] == "failed" and "v0.9.0 was not found" in result["error"]
    assert head(checkout) == before and calls.restarts == 0


def test_a_tag_that_moved_upstream_is_not_trusted(repos):
    public, checkout, state = repos
    run_apply(checkout, state)                                  # the checkout now has v0.2.0
    sh(checkout, "git", "checkout", "-q", "main")
    sh(public, "git", "tag", "-f", "v0.2.0", "main")            # someone re-points the release
    result, _ = run_apply(checkout, state)
    assert result["state"] == "failed" and "differs" in result["error"]


def test_a_checkout_on_another_branch_is_refused(repos):
    public, checkout, state = repos
    sh(checkout, "git", "checkout", "-q", "-b", "feature")
    result, calls = run_apply(checkout, state)
    assert result["state"] == "blocked" and "branch feature" in result["error"] and calls.restarts == 0


def test_a_running_turn_holds_the_switch(repos):
    public, checkout, state = repos
    before = head(checkout)
    result, calls = run_apply(checkout, state, busy=lambda: 1)
    assert result["state"] == "waiting" and head(checkout) == before and calls.restarts == 0


def test_already_on_the_release_restarts_nothing(repos):
    public, checkout, state = repos
    result, calls = run_apply(checkout, state, "0.1.0")
    assert result["state"] == "healthy" and calls.restarts == 0


def test_rollback_when_the_new_release_does_not_come_back(repos):
    public, checkout, state = repos
    before = head(checkout)
    result, calls = run_apply(checkout, state, calls=Calls(healthy=(False, True)))
    assert result["state"] == "rolled_back" and "did not report in" in result["error"]
    assert head(checkout) == before and sh(checkout, "git", "branch", "--show-current") == "main"
    assert calls.restarts == 2 and len(calls.installs) == 2       # forward, then the old dependencies back
    assert ru.read_status(state)["state"] == "rolled_back"


def test_rollback_that_also_fails_says_so(repos):
    public, checkout, state = repos
    result, _ = run_apply(checkout, state, calls=Calls(healthy=(False, False)))
    assert result["state"] == "failed" and "previous release did not start either" in result["error"]


def test_a_failed_install_puts_the_old_code_back(repos):
    public, checkout, state = repos
    before = head(checkout)
    result, calls = run_apply(checkout, state, calls=Calls(install_error="pip install failed: no network"))
    assert result["state"] == "rolled_back" and "no network" in result["error"] and head(checkout) == before


# -- the runner's side -----------------------------------------------------------------------------

class Server:
    def __init__(self, version="0.2.0"):
        self.version, self.error = version, None

    def get(self, path):
        assert path == "runners/desired"
        if self.error:
            raise self.error
        return {"version": self.version, "min_runner": "0.1.0"}


class Clock:
    t = 0.0

    def __call__(self):
        return self.t


def follower(checkout, state, server=None, config=None, env=None, launched=None, supervised=True, **kw):
    launched = [] if launched is None else launched
    f = ru.Follower(config or {}, state, server or Server(), root=checkout, env=env or {},
                    supervised=lambda: supervised, launch=lambda *a: launched.append(a), clock=Clock(), wall=Clock(), **kw)
    f.poll()
    return f, launched


def test_a_behind_runner_waits_for_quiet_then_starts_one_update(repos):
    public, checkout, state = repos
    f, launched = follower(checkout, state)
    assert (f.pending, f.state, f.release) == ("0.2.0", "waiting", "0.1.0")
    assert f.blocks_claims(active=True) is False and launched == []      # a turn is running: keep working
    assert f.blocks_claims(active=False) is True and len(launched) == 1  # quiet: go, and claim nothing meanwhile
    assert launched[0][1] == "0.2.0" and f.state == "updating"
    assert f.blocks_claims(active=False) is True and len(launched) == 1
    assert f.fields() == {"release": "0.1.0", "kind": f.kind, "update": {"state": "updating", "target": "0.2.0", "error": ""}}


def test_a_long_turn_cannot_hold_the_update_back_for_ever(repos):
    public, checkout, state = repos
    f, launched = follower(checkout, state)
    f.clock.t = ru.DRAIN_S + 1
    assert f.blocks_claims(active=True) is True and launched == []       # stop claiming so the turn can finish


def test_a_runner_on_the_release_or_newer_does_nothing(repos):
    public, checkout, state = repos
    for version in ("0.1.0", "0.0.9"):
        f, launched = follower(checkout, state, Server(version))
        assert f.pending is None and f.state == "idle" and not f.blocks_claims(False)


def test_pinned_runners_stay_and_say_so(repos):
    public, checkout, state = repos
    for kw in ({"config": {"pinned": True}}, {"env": {"TICO_RUNNER_PINNED": "1"}}, {"config": {"self_update": False}}):
        f, launched = follower(checkout, state, **kw)
        assert f.state == "pinned" and "server runs 0.2.0" in f.error and not f.blocks_claims(False) and launched == []
        assert f.fields()["update"]["state"] == "pinned"


def test_an_unsupervised_runner_does_not_restart_itself(repos):
    public, checkout, state = repos
    f, launched = follower(checkout, state, supervised=False)
    assert f.state == "blocked" and "restart it by hand" in f.error and launched == []


def test_a_refused_update_is_reported_and_not_retried_until_the_release_changes(repos):
    public, checkout, state = repos
    ru.write_status(state, state="blocked", target="0.2.0", error="the checkout has 2 changed files", at=0.0)
    server = Server()
    f, launched = follower(checkout, state, server)
    assert (f.state, f.error, f.pending) == ("blocked", "the checkout has 2 changed files", None)
    assert not f.blocks_claims(False) and launched == []
    server.version = "0.3.0"
    f.poll()
    assert f.pending == "0.3.0"                                          # a new release is a new attempt
    f.wall.t = ru.RETRY_AFTER_S + 1
    server.version = "0.2.0"
    f.poll()
    assert f.pending == "0.2.0"                                          # and so is enough time


def test_an_update_that_never_finished_counts_as_failed(repos):
    public, checkout, state = repos
    ru.write_status(state, state="updating", target="0.2.0", error="", at=0.0)
    f, _ = follower(checkout, state)
    assert f.state == "updating" and f.blocks_claims(False)
    f.wall.t = ru.STALE_UPDATING_S + 1
    f.poll()
    assert f.state == "failed" and "without an outcome" in f.error


def test_an_older_server_gets_nothing_new_and_the_runner_follows_main(repos):
    public, checkout, state = repos
    server = Server()
    server.error = APIError("not_found", "no such route", status=404)
    f, launched = follower(checkout, state, server)
    assert f.desired is None and not f.following and f.fields() == {} and launched == []
    server.error = APIError("busy", "try later", status=503, retryable=True)
    f.poll()                                                             # a blip keeps the last answer
    assert f.desired is None
    f.desired = "0.2.0"
    f.poll()
    assert f.desired == "0.2.0"


def test_a_server_build_without_a_release_is_not_followed(repos):
    public, checkout, state = repos
    f, launched = follower(checkout, state, Server(""))
    assert f.desired == "" and not f.following and f.state == "idle" and f.fields()["release"] == "0.1.0"


def test_untagged_checkouts_report_dev(repos):
    public, checkout, state = repos
    sh(checkout, "git", "checkout", "-q", "origin/main")
    f, _ = follower(checkout, state)
    assert f.fields()["release"] == "dev" and f.pending == "0.2.0"


class Sidecar:
    def __init__(self, status=None, url="http://updater:8080"):
        self.url, self._status, self.started = url, status, []

    def configured(self):
        return bool(self.url)

    def status(self):
        return self._status

    def start(self, version):
        self.started.append(version)


DOCKER = {"TICO_RUNNER_KIND": "docker", "TICO_VERSION": "v0.1.0"}


def test_a_docker_runner_asks_its_sidecar_when_quiet(repos):
    public, checkout, state = repos
    sidecar = Sidecar()
    f, _ = follower(checkout, state, env=DOCKER, sidecar=sidecar, config={"self_update": False})
    assert f.kind == "docker" and f.release == "0.1.0" and f.pending == "0.2.0"
    assert f.blocks_claims(active=False) and sidecar.started == ["0.2.0"]


def test_a_docker_runner_reports_the_sidecars_failure_and_does_not_loop(repos):
    public, checkout, state = repos
    status = {"state": "rolled_back", "to": "v0.2.0", "message": "the runner did not come up healthy. Went back to v0.1.0."}
    f, _ = follower(checkout, state, env=DOCKER, sidecar=Sidecar(status))
    assert (f.state, f.pending) == ("rolled_back", None) and "Went back" in f.error
    healthy = {"state": "healthy", "to": "v0.2.0", "message": ""}
    f, _ = follower(checkout, state, env=DOCKER, sidecar=Sidecar(healthy))
    assert f.state == "failed" and "still reports" in f.error and f.pending is None


def test_a_docker_runner_without_a_sidecar_says_what_to_run(repos):
    public, checkout, state = repos
    f, _ = follower(checkout, state, env=DOCKER, sidecar=Sidecar(url=""))
    # A bare `docker run` has no compose file: the way to an updater is the installer, pinned to the server's release.
    assert f.state == "blocked" and "docker compose pull" not in f.error
    assert "releases/download/v0.2.0/install.sh | sh -s -- --runner" in f.error
    f, _ = follower(checkout, state, env={**DOCKER, "TICO_RUNNER_COMPOSE": "1"}, sidecar=Sidecar(url=""))
    assert f.state == "blocked" and "docker compose pull" in f.error


def test_sidecar_conflict_means_an_update_is_already_running(repos):
    import urllib.error
    public, checkout, state = repos

    class Busy(Sidecar):
        def start(self, version):
            raise urllib.error.HTTPError("u", 409, "conflict", {}, None)
    f, _ = follower(checkout, state, env=DOCKER, sidecar=Busy())
    assert f.blocks_claims(False) and f.state == "updating"


def test_a_launch_that_cannot_start_is_reported(repos):
    public, checkout, state = repos

    def boom(*a):
        raise OSError("no")
    f = ru.Follower({}, state, Server(), root=checkout, env={}, supervised=lambda: True, launch=boom, clock=Clock(), wall=Clock())
    f.poll()
    assert f.blocks_claims(False) and f.state == "failed" and "OSError" in f.error
    assert ru.read_status(state)["state"] == "failed"
