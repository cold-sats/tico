"""Runner versions: comparison, the range a server accepts, claim gating and what Health and Devices show."""
from types import SimpleNamespace

import pytest

from backend import releases, runner_versions
from backend.tests.test_api import api, assign, get, post, ready, runner  # noqa: F401
from backend.tests.test_getting_started import SIGNED_IN, enrolled, heartbeat
from backend.tests.test_onboarding import as_person, environment, signed_in  # noqa: F401


@pytest.fixture(autouse=True)
def server_release(monkeypatch):
    monkeypatch.setenv("TICO_VERSION", "0.3.0")
    monkeypatch.setattr(runner_versions, "MIN_RUNNER_RELEASE", "0.2.0")
    monkeypatch.setattr(releases, "CHECKER", releases.Checker())


def report(api, r, release, kind="mac", update=None, **extra):
    body = {"version": "test", "platform": "test", "readiness": {"ops": True}, "release": release, "kind": kind, **extra}
    if update:
        body["update"] = update
    return post(api, "runners/heartbeat", body, token=r["token"])


def queue_work(api):
    r = runner(api)
    assign(api, r, "ops")
    ready(api, r, ["ops"])
    post(api, "chat/ops", {"text": "Work for the runner"})
    return r


def test_states_against_the_servers_release():
    state = runner_versions.state
    assert state("0.3.0") == "current" and state("0.4.0") == "current"          # a newer runner still works
    assert state("0.2.5") == "needs_update" and state("0.2.0") == "needs_update"
    assert state("0.1.9") == "incompatible" and state("0.1.9", "updating") == "incompatible"
    assert state("0.2.5", "updating") == "updating"
    assert state("dev") == "unknown" and state("") == "unknown"                  # not on a release: never paused
    assert state("0.3.0-rc.1") == "needs_update"                                 # a release outranks its candidates
    assert state("0.2.5", server="dev") == "unknown"
    assert not runner_versions.incompatible("dev") and not runner_versions.incompatible("")


def test_the_server_names_its_release_and_range(api):
    r = runner(api)
    assert get(api, "runners/desired", token=r["token"]) == {"version": "0.3.0", "min_runner": "0.2.0"}
    assert get(api, "config")["runner_compat"] == {"version": "0.3.0", "min_runner": "0.2.0"}
    assert get(api, "runners/desired", token="ana-test", expected=403) is not None


def test_a_development_build_names_no_release(api, monkeypatch):
    monkeypatch.delenv("TICO_VERSION")
    assert get(api, "runners/desired", token=runner(api)["token"])["version"] == ""


def test_an_incompatible_runner_does_not_claim(api):
    r = queue_work(api)
    report(api, r, "0.1.0")
    reply = post(api, "jobs/claim", {"bot": None}, token=r["token"])
    assert reply["attempt"] is None and "0.2.0 or later" in reply["paused"] and "paused" in reply["paused"]
    report(api, r, "0.2.1")                                    # it updated
    assert post(api, "jobs/claim", {"bot": None}, token=r["token"])["attempt"]["bot"] == "ops"


def test_a_runner_that_does_not_report_a_release_is_never_paused(api):
    r = queue_work(api)                                        # heartbeats of before this existed
    assert "paused" not in post(api, "jobs/claim", {"bot": None}, token=r["token"])


def test_heartbeat_records_release_kind_and_update(api):
    r = runner(api)
    report(api, r, "0.2.5", kind="docker", update={"state": "failed", "target": "0.3.0", "error": "no image"})
    with api.app.state.store.read() as c:
        row = runner_versions.load(c)[r["runner_id"]]
    assert (row["release"], row["kind"], row["update_state"], row["update_error"]) == ("0.2.5", "docker", "failed", "no image")
    assert post(api, "runners/heartbeat", {"version": "t", "platform": "t", "release": "0.2.5", "kind": "bsd"},
                token=r["token"], expected=422)


def test_following_a_release_clears_the_old_behind_main_note(api):
    r = runner(api)
    checkout = {"head": "a" * 40, "running": "a" * 40, "ahead": 0, "behind": 3, "checked_at": "2026-01-01T00:00:00Z"}
    report(api, r, "0.2.5", checkout=checkout)
    with api.app.state.store.read() as c:
        assert c.execute("SELECT checkout_json FROM runners").fetchone()[0]
    report(api, r, "0.3.0")
    with api.app.state.store.read() as c:
        assert c.execute("SELECT checkout_json FROM runners").fetchone()[0] is None


def machine_update(api, states):
    ids = {}
    for label, release, update in states:
        with api.app.state.store.transaction() as c:
            c.execute("INSERT INTO runners(id,label,operator,token_hash,created,last_seen) "
                      "SELECT ?,?,operator,?,created,? FROM runners LIMIT 1", (label, label, "h" + label, "2999-01-01T00:00:00Z"))
            runner_versions.record(c, label, SimpleNamespace(release=release, kind="mac", checkout=object(),
                                                             update=SimpleNamespace(**update) if update else None))
        ids[label] = label
    return ids


def test_health_and_devices_show_each_computers_state(environment):
    api = environment()
    enrolled(api)
    machine_update(api, [("current", "0.3.0", None),
                         ("behind", "0.2.5", {"state": "waiting", "target": "0.3.0", "error": ""}),
                         ("old", "0.1.0", None),
                         ("busy", "0.2.5", {"state": "updating", "target": "0.3.0", "error": ""}),
                         ("stuck", "0.2.5", {"state": "blocked", "target": "0.3.0", "error": "the checkout has 2 changed files"})])
    body = api.get("/api/v2/health", headers=signed_in()).json()
    states = {x["label"]: x["update"] for x in body["computers"]}
    assert {k: v["state"] for k, v in states.items() if k != "Owner Mac"} == {
        "current": "current", "behind": "needs_update", "old": "incompatible", "busy": "updating", "stuck": "needs_update"}
    assert states["old"]["label"] == "Incompatible (bots paused)" and states["stuck"]["error"].startswith("the checkout")
    check = {x["id"]: x for x in body["checks"]}["runners"]
    assert check["status"] == "bad" and "old" in check["summary"]
    devices = api.get("/api/v2/operations", headers=signed_in()).json()["machines"]
    assert {m["label"]: m["update"]["state"] for m in devices}["old"] == "incompatible"


def test_health_check_levels():
    def rows(*entries):
        return [{"label": name, "online": online, "update": runner_versions.view(
            {"release": rel, "update_state": st, "update_error": err} if rel else None)}
            for name, online, rel, st, err in entries]
    check = runner_versions.health_check
    assert check(rows(("a", True, "0.3.0", "", "")))["status"] == "ok"
    assert check(rows(("a", True, "0.2.5", "", "")))["status"] == "warn"
    assert "Last update error: boom" in check(rows(("a", True, "0.2.5", "failed", "boom")))["summary"]
    assert check(rows(("a", False, "0.1.0", "", "")))["status"] == "ok"        # offline: Health already says so
    assert check(rows(("a", True, "0.1.0", "", "")))["status"] == "bad"
    assert check(rows(("a", True, "0.3.0", "", "")), server="dev") is None


def test_health_names_the_check_only_for_administrators(environment):
    api = environment()
    person = as_person(api, "quinn")
    assert "runners" not in {x["id"] for x in api.get("/api/v2/health", headers=person).json()["checks"]}
