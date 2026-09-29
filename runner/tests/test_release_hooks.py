"""The running runner follows its server: what it reports, when it holds work back, and the paused reply."""
import pytest

from backend import releases, runner_versions
from backend.tests.test_api import api, assign, get, post, ready, runner  # noqa: F401
from backend.tests.test_runner import live  # noqa: F401
from runner.hosts.fake import FakeHost
from runner.service import Runner


@pytest.fixture(autouse=True)
def server_release(monkeypatch):
    monkeypatch.setenv("TICO_VERSION", "0.3.0")
    monkeypatch.setenv("TICO_RUNNER_KIND", "mac")
    monkeypatch.setattr(runner_versions, "MIN_RUNNER_RELEASE", "0.2.0")
    monkeypatch.setattr(releases, "CHECKER", releases.Checker())


def start(api, live, tmp_path, config=None, launched=None):
    r = runner(api)
    assign(api, r, "ops")
    ready(api, r, ["ops"])
    post(api, "chat/ops", {"text": "Please answer"})
    service = Runner({"url": live, "token": r["token"], "projects_dir": str(tmp_path), **(config or {})}, tmp_path / "runner",
                     host_factory=lambda attempt, env: FakeHost(replies=["done"]))
    service.follower.supervised = lambda: True
    service.follower._launch = lambda *args: (launched if launched is not None else []).append(args)
    service.follower.release = "0.1.0"
    service.follower.root = tmp_path        # not a checkout: the release comes from the test
    return r, service


def test_the_runner_reports_its_release_and_holds_work_while_it_updates(api, live, tmp_path, monkeypatch):
    launched = []
    r, service = start(api, live, tmp_path, launched=launched)
    monkeypatch.setattr("runner.release_update.current_release", lambda *a, **k: "0.1.0")
    service.maintain()
    with api.app.state.store.read() as c:
        row = runner_versions.load(c)[r["runner_id"]]
    assert (row["release"], row["kind"], row["update_state"], row["update_target"]) == ("0.1.0", "mac", "waiting", "0.3.0")
    service.tick()                                    # quiet, so the update starts; no work is taken meanwhile
    assert len(launched) == 1 and launched[0][1] == "0.3.0" and service.active == {}
    with api.app.state.store.read() as c:
        assert c.execute("SELECT state FROM jobs").fetchone()[0] == "queued"
    service.pool.shutdown()


def test_a_pinned_runner_keeps_working_and_says_pinned(api, live, tmp_path, monkeypatch):
    launched = []
    r, service = start(api, live, tmp_path, config={"pinned": True}, launched=launched)
    monkeypatch.setattr("runner.release_update.current_release", lambda *a, **k: "0.2.5")
    service.maintain()
    ready(api, r, ["ops"])                            # the fake bot has no checkout here; say it is ready
    with api.app.state.store.read() as c:
        row = runner_versions.load(c)[r["runner_id"]]
    assert row["update_state"] == "pinned" and runner_versions.view(row)["state"] == "needs_update"
    service.tick()
    assert launched == [] and len(service.active) == 1
    service.pool.shutdown()


def test_an_incompatible_runner_learns_why_it_gets_no_work(api, live, tmp_path, monkeypatch):
    said = []
    monkeypatch.setattr("runner.service.log", said.append)
    r, service = start(api, live, tmp_path, config={"pinned": True})
    monkeypatch.setattr("runner.release_update.current_release", lambda *a, **k: "0.1.0")
    service.maintain()
    ready(api, r, ["ops"])
    service.tick()
    service.tick()
    assert service.active == {}
    assert len([line for line in said if "not giving this computer work" in line and "0.2.0 or later" in line]) == 1
    with api.app.state.store.read() as c:
        assert c.execute("SELECT state FROM jobs").fetchone()[0] == "queued"      # held, not failed
    service.pool.shutdown()
