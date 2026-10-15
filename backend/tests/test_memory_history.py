"""Learnings history: a computer reports memory commits; readers see them, a source only when they may read it."""

from backend.tests.test_api import api, assign, claim, headers, post, ready, runner  # noqa: F401  (fixtures)

SHA = "a" * 40


def commit(sha=SHA, **extra):
    return {"sha": sha, "subject": "Check the live PR before saying a release shipped", "author": "ops",
            "committed": "2026-10-05T10:00:00+02:00", "files": ["memory/learnings.md"], **extra}


def history(api, who, bot="ops"):
    r = api.get(f"/api/v2/bots/{bot}/memory", headers=headers(who))
    assert r.status_code == 200, r.text
    return r.json()


def test_a_reported_update_shows_its_source_only_to_readers_of_that_chat(api):
    machine = runner(api)
    assign(api, machine, "ops")
    ready(api, machine, ["ops"])
    post(api, "chat/ops", {"text": "Remember to check the live PR"}, "ben-test")
    attempt = claim(api, machine, "ops")
    body = {"commits": [commit(attempt=attempt["id"], shared=True, diff="+- Check the live PR")],
            "documents": {"memory/learnings.md": "# Learnings\n- Check the live PR\n", "secrets/x": "no"}}
    assert post(api, "bots/ops/memory/report", body, machine["token"])["recorded"] == 1
    # The same report again, or one naming a run of another bot, changes nothing.
    assert post(api, "bots/ops/memory/report", body, machine["token"])["recorded"] == 0

    mine = history(api, "ben-test")["updates"][0]
    assert mine["source"]["conversation"] and "live PR" in mine["source"]["excerpt"]
    assert mine["when"] == "2026-10-05T08:00:00.000000Z" and mine["shared"] and mine["diff"]
    with api.app.state.store.transaction() as c:       # a repository on GitHub gives each pushed commit a link
        c.execute("UPDATE bot_config SET repo='acme/bot-ops' WHERE bot='ops'")
    assert history(api, "ben-test")["updates"][0]["url"] == "https://github.com/acme/bot-ops/commit/" + SHA
    for other in ("ana-test", "cara-test"):      # the owner included: a direct chat is not theirs
        theirs = history(api, other)
        assert theirs["updates"][0]["source"] is None and "live PR" not in str(theirs["updates"][0]["source"])
    files = api.get("/api/employees/ops/files", headers=headers("ben-test")).json()
    assert "Check the live PR" in files["memory/learnings.md"]


def test_only_the_assigned_computer_reports_and_runs_must_be_the_bots_own(api):
    machine, other = runner(api), runner(api, label="Other Mac")
    assign(api, machine, "ops")
    post(api, "bots/ops/memory/report", {"commits": [commit()]}, other["token"], expected=403)
    post(api, "bots/ops/memory/report", {"commits": [commit()]}, "ben-test", expected=403)
    post(api, "bots/ops/memory/report", {"commits": [commit(files=["AGENT.md"])]}, machine["token"])
    post(api, "bots/ops/memory/report", {"commits": [commit("b" * 40, attempt="not-a-run")]}, machine["token"])
    rows = history(api, "ben-test")["updates"]
    assert [r["sha"] for r in rows] == ["b" * 40] and rows[0]["source"] is None
