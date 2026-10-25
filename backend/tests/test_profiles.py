"""Bot profiles (backend/profiles.py): the migration by name, what a Responder and a Reviewer refuse, what each profile
wakes for, a Lead's daily digest, and who may set a profile."""

import json

import pytest

from backend import hubdb as H
from backend import profiles as P
from backend import rules as R
from backend import wake_presets as W
from backend.store import encode
from backend.tests.test_api import api, get, post  # noqa: F401  (api is a fixture)
from backend.tests.test_wake_rules import jobs, news


def add_bot(c, slug, **config):
    H.sync_registry(c, {slug: {"name": slug, "runtime": "fake", "status": "active"}}, {"people": []})
    c.execute("INSERT INTO bot_config(bot,config_json,team,operator) VALUES(?,?,?,?)",
              (slug, encode({"name": slug, "runtime": "fake", "status": "active", **config}), None, "ana"))


def profile_of(c, slug):
    return json.loads(c.execute("SELECT config_json FROM bot_config WHERE bot=?", (slug,)).fetchone()[0])


def put(c, slug, name, **options):
    """Give an existing bot a profile the way the API does (without the CEO gate or audit)."""
    declared = profile_of(c, slug)
    c.execute("UPDATE bot_config SET config_json=? WHERE bot=?", (encode(P.apply(declared, name, options)), slug))


def test_migration_gives_each_bot_a_profile_by_name_once_and_tells_its_owner(api):
    slugs = {"engineering-lead": P.LEAD, "cmo": P.LEAD, "release-manager": P.LEAD, "sentry-triage": P.MONITOR,
             "uptime-monitor": P.MONITOR, "qa-web": P.REVIEWER, "security-audit": P.REVIEWER, "pr-reviewer-sol": P.REVIEWER,
             "assistant": P.RESPONDER, "botops": P.CUSTOM, "task-manager": P.CUSTOM, "writer": P.DOER}
    with api.app.state.store.transaction() as c:
        for slug in slugs:
            add_bot(c, slug)
        add_bot(c, "saver", wake_preset="token_saver")
        add_bot(c, "grok-designer", harness="grokbot")
        # The starter factory's Builder is called pr-reviewer and owns the Dev tickets: it stays a doer.
        add_bot(c, "pr-reviewer")
        add_bot(c, "pr-reviewer-2")
        kind = c.execute("SELECT id FROM task_types WHERE name='Dev tickets'").fetchone()
        if kind is None:
            c.execute("INSERT INTO task_types(id,name,created,updated) VALUES('dev','Dev tickets',?,?)", (H.now(), H.now()))
        H.task_create(c, "human:ana", "Fix login", "x", "bot:pr-reviewer", type="Dev tickets")
        c.execute("UPDATE bot_config SET config_json=json_set(config_json,'$.profile','doer') WHERE bot='cpo'")
        told = P.migrate(c)
        got = {slug: profile_of(c, slug) for slug in (*slugs, "saver", "grok-designer", "pr-reviewer", "cpo")}
        assert {slug: got[slug]["profile"] for slug in slugs} == slugs
        assert got["grok-designer"]["profile"] == P.RESPONDER and got["cpo"]["profile"] == "doer"
        assert got["pr-reviewer"]["profile"] == P.DOER and profile_of(c, "pr-reviewer-2")["profile"] == P.REVIEWER
        # A former Token saver bot keeps its 30-minute window as a value of its own; Performance is the Doer's.
        assert got["saver"]["profile"] == P.DOER and got["saver"]["wake_preset"] == "token_saver"
        assert got["saver"]["profile_options"]["batch_seconds"] == 1800 and got["writer"]["wake_preset"] == "performance"
        assert told > 12
        notes = [m for m in H.notices(c, "human:ana") if "gave each of your bots a profile" in m["body"]]
        assert len(notes) == 1 and "engineering-lead" in notes[0]["body"] and "Lead" in notes[0]["body"]
        # Run again: nothing changes and nobody is told twice.
        revision = c.execute("SELECT sum(revision) FROM bot_config").fetchone()[0]
        assert P.migrate(c) == 0 and c.execute("SELECT sum(revision) FROM bot_config").fetchone()[0] == revision
        assert len([m for m in H.notices(c, "human:ana") if "gave each of your bots a profile" in m["body"]]) == 1


def test_a_responder_takes_no_task_and_runs_no_routine(api):
    with api.app.state.store.transaction() as c:
        add_bot(c, "helper")
        put(c, "helper", P.RESPONDER)
        for owner_change in (False, True):
            with pytest.raises(H.Refused) as raised:
                if owner_change:
                    mine = H.task_create(c, "human:ana", "Something", "x", "bot:ops")
                    H.task_update(c, "human:ana", mine["id"], owner="bot:helper")
                else:
                    H.task_create(c, "human:ana", "Redo the logo", "x", "bot:helper")
            assert raised.value.rule == "external-bot" and "takes no tasks" in str(raised.value)
        from backend import routines
        with pytest.raises(H.Refused):
            routines.create(c, "human:ana", "helper", {"title": "Notes", "on": "meeting.ready"})
        c.execute("INSERT INTO schedules(id,bot,event_name,title,playbook) VALUES('old','helper','meeting.ready','Notes','x')")
        assert routines.emit(c, "meeting.ready", "m1") == []
        # People can still write to it: the chat is how a Responder is used.
        H.say(c, "human:ana", "bot:helper", "Hello")
        assert jobs(c, "helper") == 1


def test_a_reviewer_takes_review_children_only_and_wakes_for_its_request_and_people(api):
    with api.app.state.store.transaction() as c:
        add_bot(c, "checker")
        put(c, "checker", P.REVIEWER)
        with pytest.raises(H.Refused) as raised:
            H.task_create(c, "bot:ops", "Build the thing", "x", "bot:checker")
        assert raised.value.rule == "profile" and "reviewer" in str(raised.value)
        parent = H.task_create(c, "bot:ops", "Build 1/9", "x", "bot:cpo")
        review = H.task_create(c, "bot:ops", "QA: check the build", "x", "bot:checker", parent_id=parent["id"])
        assert review["owner"] == "bot:checker"
        # Its own work is not pulled by itself unless it is a review (auto_tasks), and nothing else stirs it.
        c.execute("DELETE FROM jobs")
        mine = H.task(c, review["id"])
        assert news(c, mine)["refs"]["rule"] == "profile_reviewer_note" and jobs(c, "checker") == 0
        found = R.judge(c, H.KEEPER, "bot:checker", "message", {"task": review["id"]}, "Ready for review: x", None)
        assert found.outcome == "wake"
        person = R.judge(c, "human:ana", "bot:checker", "message", {}, "Did you look?", None)
        assert person.outcome == "wake"
        # A review is startable on its own; another task owned by the reviewer is not pulled.
        assert P.pull_refusal(c, mine, profile_of(c, "checker")) is None
        other = dict(mine, id="x", title="Something else")
        assert P.pull_refusal(c, other, profile_of(c, "checker")) == "auto_start_off"
        assert P.mismatches(c) == []
        c.execute("INSERT INTO tasks(id,title,body,owner,requester,status,created,updated) "
                  "VALUES('t-odd','Odd job','x','bot:checker','human:ana','open',?,?)", (H.now(), H.now()))
        assert P.mismatches(c) == [("reviewer_holds_tasks", "checker", 1)]


def test_sweeps_follow_the_profile_and_a_custom_bot_reads_its_own_setting(api):
    with api.app.state.store.transaction() as c:
        for slug, name, options in (("d", P.DOER, {}), ("r", P.REVIEWER, {}), ("l", P.LEAD, {}), ("m", P.MONITOR, {}),
                                    ("c1", P.CUSTOM, {}), ("c2", P.CUSTOM, {"sweeps": False})):
            add_bot(c, slug)
            put(c, slug, name, **options)
        assert [R.sweeps_on(c, "bot:" + s) for s in ("d", "r", "l", "m", "c1", "c2", "ops")] == [
            True, False, False, False, True, False, True]


def test_a_lead_is_woken_by_people_and_hears_the_rest_once_a_day(api):
    with api.app.state.store.transaction() as c:
        add_bot(c, "boss")
        put(c, "boss", P.LEAD)
        task = H.task_create(c, "bot:ops", "Ship it", "x", "bot:cpo")
        mine = H.task_create(c, "bot:boss", "Ask around", "x", "bot:ops")
        c.execute("DELETE FROM jobs")
        # News about its task is held for the digest: the job waits, then a tick plans it for the next 09:00.
        held = news(c, H.task(c, mine["id"]) | {"owner": "bot:boss"}, "Step moved: Open -> Doing")
        assert held["refs"]["rule"] == "profile_lead_digest" and held["refs"]["wake_batch"] == "rule"
        job = c.execute("SELECT id,held,created FROM jobs WHERE bot='boss'").fetchone()
        assert job["held"] == 1
        W.tick(c, job["created"])
        due = c.execute("SELECT hold_until FROM jobs WHERE id=?", (job["id"],)).fetchone()[0]
        assert due == W.digest_time(job["created"], 9) and due > job["created"]
        # A person's message, and a declined ticket it asked for, wake it at once.
        assert R.judge(c, "human:ana", "bot:boss", "message", {}, "Status?", None).outcome == "wake"
        assert task["id"]


def test_digest_time_is_the_next_hour_in_team_time():
    # 2026-10-24 12:00 UTC is 05:00 in Los Angeles (PDT): the digest at 09:00 is the same day, 16:00 UTC.
    assert W.digest_time("2026-10-24T12:00:00.000000Z", 9) == "2026-10-24T16:00:00.000000Z"
    assert W.digest_time("2026-10-24T17:00:00.000000Z", 9) == "2026-10-25T16:00:00.000000Z"


def set_profile(api, bot, name, token="ana-test", expected=200, **extra):
    revision = get(api, "bots/" + bot)["revision"]
    return post(api, f"bots/{bot}/profile", {"profile": name, "expected_revision": revision, **extra},
                token=token, expected=expected)


def test_setting_a_profile_needs_the_bots_manager_and_the_current_revision(api):
    first = set_profile(api, "ops", "reviewer")
    assert first["profile"]["name"] == "reviewer" and first["profile"]["takes"] == "review"
    shown = get(api, "bots/ops")
    assert shown["profile"]["name"] == "reviewer" and shown["wake"]["profile"] == "reviewer"
    # Cara owns nothing and manages nothing here.
    set_profile(api, "ops", "doer", token="cara-test", expected=403)
    # A stale revision is a conflict, not an overwrite.
    post(api, "bots/ops/profile", {"profile": "doer", "expected_revision": 1}, expected=409)
    # The numbers belong to the profile that reads them.
    set_profile(api, "ops", "doer", pulls="none", expected=422)
    set_profile(api, "ops", "doer", digest_hour=7, expected=422)
    assert set_profile(api, "ops", "lead", digest_hour=7)["profile"]["digest_hour"] == 7
    # The old wake-preset route still works and leaves the profile where it is.
    post(api, "bots/ops/wake-preset", {"wake_preset": "token_saver", "expected_revision": get(api, "bots/ops")["revision"]})
    assert get(api, "bots/ops")["profile"]["name"] == "lead"


def test_custom_copies_the_rows_and_leaving_it_needs_a_confirm(api):
    set_profile(api, "ops", "reviewer")
    custom = set_profile(api, "ops", "custom")
    assert custom["rules"] >= 3 and custom["profile"]["name"] == "custom"
    with api.app.state.store.read() as c:
        assert c.execute("SELECT count(*) FROM rules WHERE scope_kind='bot' AND scope_id='ops' AND created_by='profile'"
                         ).fetchone()[0] == custom["rules"]
    set_profile(api, "ops", "doer", expected=409)
    back = set_profile(api, "ops", "doer", confirm_drop_rules=True)
    assert back["rules"] == 0 and back["profile"]["name"] == "doer"


def test_the_choices_describe_each_profile(api):
    listed = get(api, "profiles")["profiles"]
    assert [p["name"] for p in listed] == list(P.NAMES) and all(p["description"] for p in listed)
