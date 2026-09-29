"""The running version, the update notice and the owner's "Update now"."""

import json
from pathlib import Path

import httpx
import pytest

from backend import releases
from backend.tests.test_onboarding import as_person, environment, signed_in  # noqa: F401

RELEASE = {"tag_name": "v0.2.0", "html_url": "https://github.com/ticoteam/tico/releases/tag/v0.2.0",
           "published_at": "2026-10-20T10:00:00Z", "name": "Tico 0.2.0"}


@pytest.fixture(autouse=True)
def isolated(monkeypatch):
    monkeypatch.setattr(releases, "CHECKER", releases.Checker())
    monkeypatch.setattr(releases, "TRANSPORT", None)
    monkeypatch.delenv("TICO_UPDATER_URL", raising=False)
    monkeypatch.delenv("TICO_UPDATER_TOKEN", raising=False)
    monkeypatch.setenv("TICO_UPDATE_CHECK", "on")
    monkeypatch.setenv("TICO_VERSION", "0.1.0")


def network(monkeypatch, handler):
    monkeypatch.setattr(releases, "TRANSPORT", httpx.MockTransport(handler))


def test_semver_comparison():
    assert releases.newer("0.2.0", "0.1.0") and releases.newer("v1.0.0", "0.9.9")
    assert releases.newer("0.10.0", "0.9.0")
    assert not releases.newer("0.1.0", "0.1.0") and not releases.newer("0.1.0", "0.2.0")
    assert releases.newer("1.0.0", "1.0.0-rc.1") and not releases.newer("1.0.0-rc.1", "1.0.0")
    assert releases.newer("1.0.0-rc.10", "1.0.0-rc.2")
    assert not releases.newer("0.2.0", "dev") and not releases.newer("latest", "0.1.0")


def test_refresh_caches_and_revalidates_with_the_etag(monkeypatch):
    seen = []

    def handler(request):
        seen.append(request.headers.get("if-none-match"))
        if request.headers.get("if-none-match") == '"abc"':
            return httpx.Response(304)
        return httpx.Response(200, json=RELEASE, headers={"etag": '"abc"'})
    network(monkeypatch, handler)
    checker = releases.Checker()
    checker.refresh()
    checker.refresh()
    assert seen == [None, '"abc"']
    assert checker.view("0.1.0") == {"current": "0.1.0", "latest": "0.2.0", "available": True,
                                     "url": RELEASE["html_url"], "published_at": RELEASE["published_at"],
                                     "name": "Tico 0.2.0"}
    assert checker.view("0.2.0")["available"] is False


def test_failures_are_silent_keep_the_last_answer_and_back_off(monkeypatch):
    now = [0.0]
    checker = releases.Checker(clock=lambda: now[0])
    network(monkeypatch, lambda request: httpx.Response(200, json=RELEASE))
    checker.refresh()

    def boom(request):
        raise httpx.ConnectTimeout("slow")
    network(monkeypatch, boom)
    now[0] += releases.TTL + 1
    checker.refresh()
    assert checker.view("0.1.0")["available"] is True
    assert checker.retry_at > now[0]
    network(monkeypatch, lambda request: httpx.Response(403))
    checker.refresh()
    assert checker.release["tag"] == "v0.2.0"


def test_disabled_and_dev_builds_show_no_notice_and_make_no_request(monkeypatch):
    def forbidden(request):
        raise AssertionError("no request expected")
    network(monkeypatch, forbidden)
    monkeypatch.setenv("TICO_UPDATE_CHECK", "off")
    checker = releases.Checker()
    assert checker.view("0.1.0")["available"] is False
    monkeypatch.setenv("TICO_UPDATE_CHECK", "on")
    assert checker.view("dev") == {"current": "dev", "latest": "", "available": False, "url": "",
                                   "published_at": "", "name": ""}
    assert checker.view("abc1234")["available"] is False


def test_check_now_bypasses_the_cache_and_is_rate_limited(monkeypatch):
    now, calls = [1000.0], []

    def handler(request):
        calls.append(1)
        return httpx.Response(200, json=RELEASE)
    network(monkeypatch, handler)
    checker = releases.Checker(clock=lambda: now[0])
    checker.refresh()
    checker.check_now()
    assert len(calls) == 2                     # a fresh cache does not stop an explicit check
    with pytest.raises(releases.Problem) as refused:
        checker.check_now()
    assert refused.value.status == 429 and len(calls) == 2
    now[0] += releases.FORCE_GAP + 1
    checker.check_now()
    assert len(calls) == 3


def test_check_for_updates_endpoint_is_owner_only_and_returns_the_notice(environment, monkeypatch):
    api = environment()
    network(monkeypatch, lambda request: httpx.Response(200, json=RELEASE))
    person = as_person(api, "riley")
    assert api.post("/api/v2/system/update/check", headers=person).status_code == 403
    got = api.post("/api/v2/system/update/check", headers=signed_in())
    assert got.status_code == 200 and got.json()["latest"] == "0.2.0" and got.json()["available"] is True
    assert api.post("/api/v2/system/update/check", headers=signed_in()).status_code == 429


def test_update_is_owner_only(environment):
    api = environment()
    person = as_person(api, "riley")
    assert api.post("/api/v2/system/update", json={"version": "0.2.0"}, headers=person).status_code == 403
    assert api.get("/api/v2/system/update", headers=person).status_code == 403


def test_update_is_forwarded_to_the_updater_with_the_token(environment, monkeypatch):
    seen = []

    def updater(request):
        seen.append((request.method, request.url.path, request.headers["authorization"],
                     json.loads(request.content) if request.content else None))
        return httpx.Response(200, json={"state": "pulling", "from": "0.1.0", "to": "0.2.0", "message": ""})
    network(monkeypatch, updater)
    monkeypatch.setenv("TICO_UPDATER_URL", "http://updater:9000/")
    monkeypatch.setenv("TICO_UPDATER_TOKEN", "s3cret")
    api = environment()
    r = api.post("/api/v2/system/update", json={"version": "v0.2.0"}, headers=signed_in())
    assert r.status_code == 200 and r.json()["state"] == "pulling"
    assert seen[0] == ("POST", "/update", "Bearer s3cret", {"version": "0.2.0"})
    assert seen[1][:3] == ("GET", "/status", "Bearer s3cret")
    got = api.get("/api/v2/system/update", headers=signed_in()).json()
    assert got == {"configured": True, "state": "pulling", "from": "0.1.0", "to": "0.2.0", "message": "",
                   "snapshot": "", "restored": False}


def test_bad_version_and_dead_updater(environment, monkeypatch):
    api = environment()
    assert api.post("/api/v2/system/update", json={"version": "latest"}, headers=signed_in()).status_code == 422

    def dead(request):
        raise httpx.ConnectError("down")
    network(monkeypatch, dead)
    monkeypatch.setenv("TICO_UPDATER_URL", "http://updater:9000")
    r = api.post("/api/v2/system/update", json={"version": "0.2.0"}, headers=signed_in())
    assert r.status_code == 502 and r.json()["error"]["command"]


def test_changelog_section_extraction():
    from scripts.changelog_notes import section
    text = "# Changelog\n\n## [Unreleased]\n\n- b\n\n## [0.1.0] - 2026-09-29\n\n### Added\n- a\n\n[0.1.0]: https://x\n"
    assert section(text, "v0.1.0") == "### Added\n- a"
    assert section(text, "0.9.0") == ""
    # Versions whose tags no longer exist are plain headings; the section before them still ends there.
    text = "## [0.2.3] - d\n\n- new\n\n## 0.2.2 - d\n\n- old\n\n## 0.2.20 - d\n\n- other\n"
    assert section(text, "0.2.3") == "- new"
    assert section(text, "0.2.2") == "- old"


def events_of(api, action):
    with api.app.state.store.read() as c:
        return [dict(r) for r in c.execute("SELECT actor,target,detail_json FROM events WHERE action=?", (action,))]


def test_update_start_and_outcome_are_audited_once(environment, monkeypatch):
    state = {"state": "pulling", "from": "0.1.0", "to": "0.2.0", "message": ""}
    network(monkeypatch, lambda request: httpx.Response(200, json=dict(state)))
    monkeypatch.setenv("TICO_UPDATER_URL", "http://updater:9000")
    monkeypatch.setenv("TICO_UPDATER_TOKEN", "s3cret")
    api = environment()
    api.post("/api/v2/system/update", json={"version": "v0.2.0"}, headers=signed_in())
    started = events_of(api, "system.update.started")
    assert len(started) == 1 and json.loads(started[0]["detail_json"]) == {"from": "0.1.0", "to": "0.2.0"}
    api.get("/api/v2/system/update", headers=signed_in())
    assert events_of(api, "system.update.finished") == []
    state.update(state="rolled_back", message="did not answer")
    api.get("/api/v2/system/update", headers=signed_in())
    api.get("/api/v2/system/update", headers=signed_in())
    finished = events_of(api, "system.update.finished")
    assert len(finished) == 1 and finished[0]["actor"] == started[0]["actor"]
    assert json.loads(finished[0]["detail_json"])["outcome"] == "rolled_back"


def test_refused_update_leaves_no_audit_event(environment):
    api = environment()
    assert api.post("/api/v2/system/update", json={"version": "0.2.0"}, headers=signed_in()).status_code == 409
    assert events_of(api, "system.update.started") == []


def test_docker_updater_speaks_the_servers_contract(environment, monkeypatch, tmp_path):
    """The real docker/updater.py behind the real client: version spelling, token, status shape."""
    import importlib.util
    import threading
    from http.server import ThreadingHTTPServer
    spec = importlib.util.spec_from_file_location("tico_updater", Path(__file__).resolve().parents[2] / "docker/updater.py")
    updater = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(updater)
    (tmp_path / "token").write_text("s3cret\n")
    started = []
    monkeypatch.setattr(updater, "TOKEN_FILE", str(tmp_path / "token"))
    monkeypatch.setattr(updater, "update", lambda version: started.append(version))
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), updater.Handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    try:
        monkeypatch.setenv("TICO_UPDATER_URL", "http://127.0.0.1:%d" % httpd.server_address[1])
        monkeypatch.setenv("TICO_UPDATER_TOKEN", "s3cret")
        api = environment()
        r = api.post("/api/v2/system/update", json={"version": "0.2.0"}, headers=signed_in())
        assert r.status_code == 200 and r.json()["configured"] is True and r.json()["state"] == "pulling"
        assert r.json()["to"] == "v0.2.0"
        monkeypatch.setenv("TICO_UPDATER_TOKEN", "wrong")
        assert api.get("/api/v2/system/update", headers=signed_in()).status_code == 502
    finally:
        httpd.shutdown()
    import time
    time.sleep(0.2)
    assert started == ["v0.2.0"]

