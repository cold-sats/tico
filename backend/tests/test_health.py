"""Health: every check is computed from live state, and people who are not administrators see counts only."""

import pytest

from backend import onboarding, releases
from backend.store import H
from backend.tests.test_getting_started import SIGNED_IN, activate, add_bot, enrolled, heartbeat  # noqa: F401
from backend.tests.test_onboarding import as_person, environment, signed_in  # noqa: F401
from backend import health


@pytest.fixture(autouse=True)
def quiet(monkeypatch):
    monkeypatch.setattr(releases, "CHECKER", releases.Checker())
    monkeypatch.setenv("TICO_UPDATE_CHECK", "off")


def queue(c, bot, minutes_ago, ident):
    """A message to the bot, which the database turns into a queued job."""
    c.execute("INSERT INTO messages(id,from_actor,to_actor,kind,body,created) VALUES(?,?,?,?,?,?)",
              (ident, "human:ana", "bot:" + bot, "request", "hi", H.shift(H.now(), minutes=-minutes_ago)))


def health_of(api, headers=None):
    body = api.get("/api/v2/health", headers=headers or signed_in()).json()
    return body, {row["id"]: row for row in body["checks"]}


def with_backup(monkeypatch, backup):
    real = onboarding.config_view
    monkeypatch.setattr(onboarding, "config_view", lambda *a, **k: {**real(*a, **k), **({"backup": backup} if backup else {})})


def test_a_fresh_server_names_the_missing_computer(environment):
    body, checks = health_of(environment())
    assert checks["computers"]["status"] == "bad" and checks["computers"]["fixes"][0]["tab"] == "devices"
    assert checks["backups"]["status"] == "unknown"        # not reporting is not the same as fine
    assert checks["failed"]["status"] == "ok" and checks["waiting"]["status"] == "ok"
    assert body["audience"] == "owner" and body["attention"] >= 1


def test_all_good(environment, monkeypatch):
    api = environment()
    runner = enrolled(api)
    heartbeat(api, runner, seconds_ago=5, runtimes=SIGNED_IN)
    with_backup(monkeypatch, {"mode": "remote", "last_replicated_at": H.now(), "target_kind": "s3"})
    monkeypatch.setenv("TICO_AUTH_PROXY", "oidc") if False else None
    body, checks = health_of(api)
    assert {k: v["status"] for k, v in checks.items() if k != "signin"} == {
        "version": "ok", "computers": "ok", "models": "ok", "waiting": "ok", "queue": "ok",
        "github": "info", "backups": "ok", "failed": "ok"}
    assert body["computers"][0]["online"] and body["computers"][0]["runtimes"][0]["ready"]


def test_an_offline_computer_holds_its_bots(environment):
    api = environment()
    runner = enrolled(api)
    add_bot(api, "helper")
    heartbeat(api, runner, seconds_ago=600, runtimes=SIGNED_IN)
    with api.app.state.store.transaction() as c:
        c.execute("INSERT INTO assignments(bot,runner_id,generation,updated,updated_by) VALUES('helper',?,1,?,'t')",
                  (runner, H.now()))
    body, checks = health_of(api)
    assert checks["computers"]["status"] == "bad" and checks["waiting"]["status"] == "bad"
    assert body["waiting"][0]["bot"] == "helper" and body["waiting"][0]["reason"] == "computer_offline"
    assert body["computers"][0]["last_seen"]
    # A second computer that is up makes it a warning, not an outage.
    heartbeat(api, runner, seconds_ago=5, runtimes=SIGNED_IN)
    with api.app.state.store.transaction() as c:
        c.execute("INSERT INTO runners(id,label,operator,token_hash,created,last_seen) "
                  "SELECT 'r2','Old laptop',operator,'h2',created,? FROM runners WHERE id=?",
                  (H.shift(H.now(), hours=-2), runner))
    body, checks = health_of(api)
    assert checks["computers"]["status"] == "warn" and "Old laptop" in checks["computers"]["summary"]


def test_work_that_waits_too_long_on_a_running_computer(environment):
    api = environment()
    runner = enrolled(api)
    add_bot(api, "helper")
    heartbeat(api, runner, seconds_ago=5, runtimes=SIGNED_IN)
    with api.app.state.store.transaction() as c:
        c.execute("INSERT INTO assignments(bot,runner_id,generation,updated,updated_by) VALUES('helper',?,1,?,'t')",
                  (runner, H.now()))
        queue(c, "helper", 30, "m1")
    body, checks = health_of(api)
    assert checks["queue"]["status"] == "warn" and body["slow"][0]["bot"] == "helper"


def test_backups_local_only_and_stale(environment, monkeypatch):
    api = environment()
    with_backup(monkeypatch, {"mode": "local-only", "last_replicated_at": None, "target_kind": "local"})
    assert health_of(api)[1]["backups"]["status"] == "warn"
    old = H.shift(H.now(), hours=-30)
    with_backup(monkeypatch, {"mode": "remote", "last_replicated_at": old, "target_kind": "s3"})
    assert health_of(api)[1]["backups"]["status"] == "warn"
    with_backup(monkeypatch, {"mode": "off"})
    assert health_of(api)[1]["backups"]["status"] == "bad"


def test_an_update_is_offered_with_its_fix(environment, monkeypatch):
    api = environment()
    monkeypatch.setenv("TICO_VERSION", "0.1.0")
    monkeypatch.setenv("TICO_UPDATE_CHECK", "on")
    releases.CHECKER.release = {"tag": "v0.2.0", "url": "u", "published_at": "", "name": "n"}
    releases.CHECKER.checked = releases.CHECKER.clock()
    _, checks = health_of(api)
    assert checks["version"]["status"] == "warn" and "0.2.0" in checks["version"]["summary"]
    assert checks["version"]["fixes"][0]["click"] == "#new-version"


def test_failed_runs_in_the_last_day_only(environment):
    api = environment()
    runner = enrolled(api)
    add_bot(api, "helper")
    with api.app.state.store.transaction() as c:
        for n, ago in enumerate((1, 30)):
            queue(c, "helper", 1, f"j{n}")
            c.execute("INSERT INTO attempts(id,job_id,bot,runner_id,generation,token_hash,state,lease_until,created,finished) "
                      "VALUES(?,?,?,?,1,?,'failed',?,?,?)",
                      (f"a{n}", f"j{n}", "helper", runner, f"t{n}", H.now(), H.now(), H.shift(H.now(), hours=-ago)))
    body, checks = health_of(api)
    assert checks["failed"]["status"] == "warn" and "1 run failed" in checks["failed"]["summary"]
    assert len(body["failures"]) == 1


def test_a_refused_github_token_shows_until_it_recovers(environment):
    api = environment()
    store = api.app.state.store
    health.note_github_token(store, "GitHub would not issue an installation token")
    with store.read() as c:
        assert c.execute("SELECT last_error FROM service_health WHERE service='github:token'").fetchone()[0]
    health.note_github_token(store)
    with store.read() as c:
        assert c.execute("SELECT last_error FROM service_health WHERE service='github:token'").fetchone()[0] is None


def test_an_unset_optional_service_is_info_not_ok_or_a_warning(environment):
    body, checks = health_of(environment())
    assert checks["github"]["status"] == "info" and "Optional" in checks["github"]["summary"]
    assert checks["github"]["fixes"]
    # It is not something to look at: only warn and bad count.
    assert body["attention"] == sum(1 for row in checks.values() if row["status"] in ("warn", "bad"))


def test_only_harnesses_someone_needs_are_listed(environment):
    api = environment()                      # openai is the enabled provider: codex is needed
    runner = enrolled(api)
    add_bot(api, "helper")
    heartbeat(api, runner, seconds_ago=5, runtimes={
        "codex": {"installed": False}, "claude": {"installed": False}, "cursor": {"installed": False},
        "gemini": {"installed": True, "authenticated": "missing"}, "pi": {"installed": False}})
    body, _ = health_of(api)
    listed = {row["name"]: row for row in body["computers"][0]["runtimes"]}
    assert set(listed) == {"codex", "gemini"}          # claude, cursor and pi are nobody's business
    assert listed["codex"]["needed"] and not listed["gemini"]["needed"]
    # A bot assigned here that runs on claude makes its absence a real problem.
    with api.app.state.store.transaction() as c:
        c.execute("INSERT INTO assignments(bot,runner_id,generation,updated,updated_by) VALUES('helper',?,1,?,'t')",
                  (runner, H.now()))
        c.execute("INSERT INTO bot_config(bot,config_json,operator) VALUES('helper',?,'morgan')",
                  ('{"runtime": "claude", "model": "claude-sonnet-4-6"}',))
    body, _ = health_of(api)
    listed = {row["name"]: row for row in body["computers"][0]["runtimes"]}
    assert set(listed) == {"claude", "codex", "gemini"} and listed["claude"]["needed"]
    operations = api.get("/api/v2/operations", headers=signed_in()).json()
    assert operations["machines"][0]["needed_runtimes"] == ["claude", "codex"]


def test_a_refused_key_is_bad_with_its_fix_not_signed_in(environment):
    api = environment()
    runner = enrolled(api)
    heartbeat(api, runner, seconds_ago=5, runtimes={"codex": {
        "installed": True, "authenticated": "rejected", "rejected_at": "2026-10-01T10:00:00Z",
        "rejected_reason": "unexpected status 401 Unauthorized: Incorrect API key provided"}})
    body, checks = health_of(api)
    assert checks["models"]["status"] == "bad"
    assert "Sign-in rejected for codex" in checks["models"]["summary"] and "Incorrect API key" in checks["models"]["summary"]
    assert "Replace the key" in checks["models"]["summary"] and "Settings > Devices" in checks["models"]["summary"]
    row = body["computers"][0]["runtimes"][0]
    assert row["rejected"] and not row["ready"] and row["signable"] and row["rejected_reason"]
    # Signed in on a second computer: still worth a look, but not an outage.
    with api.app.state.store.transaction() as c:
        c.execute("INSERT INTO runners(id,label,operator,token_hash,created,last_seen,readiness_json) "
                  "SELECT 'r2','Second',operator,'h2',created,?,? FROM runners WHERE id=?",
                  (H.now(), '{"schema_version": 1, "bots": {}, "runtimes": {"codex": {"installed": true, "authenticated": "ready"}}}', runner))
    _, checks = health_of(api)
    assert checks["models"]["status"] == "warn" and "codex is signed in on another computer" in checks["models"]["summary"]


def test_health_carries_the_current_update_notice(environment, monkeypatch):
    monkeypatch.setenv("TICO_UPDATE_CHECK", "on")
    monkeypatch.setenv("TICO_VERSION", "0.2.0")
    checker = releases.Checker()
    checker.release = {"tag": "v0.3.0", "url": "https://x", "published_at": "", "name": "0.3.0"}
    checker.checked = checker.clock()
    monkeypatch.setattr(releases, "CHECKER", checker)
    body, checks = health_of(environment())
    assert body["update"]["latest"] == "0.3.0" and checks["version"]["status"] == "warn"


def test_others_see_counts_not_details(environment):
    api = environment()
    runner = enrolled(api)
    heartbeat(api, runner, seconds_ago=600)
    body, checks = health_of(api, as_person(api, "quinn"))
    assert body["audience"] == "human" and body["computers"] == [] and body["waiting"] == []
    assert set(checks) == {"computers", "waiting", "queue", "failed"}
    assert all(not row["fixes"] for row in checks.values())
    assert "helper" not in checks["waiting"]["summary"]
