"""A job whose claim raises is held with its reason, and no claim evaluates it again; the other bots still start.

The claim checks each candidate job and prepares the one it hands out. An error in either belongs to that job: its
writes are rolled back, its traceback is logged once, and the job is held (backend/claim_holds.py). Storage errors and
errors outside a candidate are not this job's, and they still fail the claim.
"""
import json
import sqlite3

import pytest

from backend import (claim_holds, execution, gateway_connection, health_monitor, read_deps, turn_budgets,
                     task_privacy as privacy)
from backend.store import H
from backend.tests.test_api import (  # noqa: F401 (api is a fixture)
    api, assign, claim, get, headers, post, ready, runner)
from backend.tests.test_held_runs import task_held
from backend.tests.test_run_backoff import complete, setup as budget_setup


def jobs_of(api, bot):
    with api.app.state.store.read() as c:
        return [dict(r) for r in c.execute("SELECT id,state,held,hold_reason,hold_task_id,attempt_id FROM jobs "
                                           "WHERE bot=? ORDER BY created,id", (bot,))]


def task_jobs(api, task_id):
    """ops's jobs for one task, oldest first, with the Needs-you item a claim hold filed."""
    with api.app.state.store.read() as c:
        return [dict(r) for r in c.execute(
            "SELECT j.id,j.state,j.held,j.hold_reason,j.hold_task_id FROM jobs j JOIN messages m ON m.id=j.message_id "
            "JOIN conversations cv ON cv.id=m.conversation_id "
            f"WHERE j.bot='ops' AND {H.MESSAGE_TASK_SQL}=? ORDER BY j.created,j.id", (task_id,))]


def raising_for_ops(monkeypatch):
    """Every job of ops raises as its checks run: an error that belongs to that work."""
    checked = execution.job_refusal

    def raising(c, row, *args, **kwargs):
        if row["bot"] == "ops":
            raise RuntimeError("the export's state cannot be read")
        return checked(c, row, *args, **kwargs)
    monkeypatch.setattr(execution, "job_refusal", raising)


def held_refresh(api, monkeypatch):
    """ops has one task whose job raises in its checks: one claim holds it and files the bot's Needs-you item."""
    machine = runner(api, "ana")
    assign(api, machine, "ops")
    ready(api, machine, ["ops"])
    with api.app.state.store.transaction() as c:
        task_id = H.task_create(c, H.KEEPER, "Refresh the export", "Refresh it.", H.bot_actor("ops"), lint=False)["id"]
    raising_for_ops(monkeypatch)
    assert claim(api, machine) is None
    return machine, task_id


def item_status(api, task_id):
    with api.app.state.store.read() as c:
        return dict(H.task(c, task_id))["status"]


def two_bots_with_chats(api, machine):
    """ops's chat is created first and dated earlier, so its job is the one a claim considers first."""
    assign(api, machine, "ops")
    assign(api, machine, "cpo")
    ready(api, machine, ["ops", "cpo"])
    post(api, "chat/ops", {"text": "Look at the export."})
    post(api, "chat/cpo", {"text": "Look at the pricing."})
    with api.app.state.store.transaction() as c:
        c.execute("UPDATE jobs SET created=? WHERE bot='ops'", (H.shift(H.now(), minutes=-5),))


def test_a_job_whose_checks_raise_is_held_and_the_claim_hands_out_the_next_bots_job(api, monkeypatch, caplog):
    machine = runner(api, "ana")
    two_bots_with_chats(api, machine)
    raised = []
    checked = execution.job_refusal

    def refusing(c, row, *args, **kwargs):
        if row["bot"] == "ops":
            raised.append(row["id"])
            raise RuntimeError("the export's state cannot be read")
        return checked(c, row, *args, **kwargs)
    monkeypatch.setattr(execution, "job_refusal", refusing)

    turn = claim(api, machine)
    assert turn["bot"] == "cpo"
    [bad] = jobs_of(api, "ops")
    assert (bad["held"], bad["hold_reason"], bad["state"]) == (1, claim_holds.REASON, "queued")
    assert raised == [bad["id"]]
    tracebacks = [r for r in caplog.records if r.exc_info and f"claim failed for {bad['id']}" in r.getMessage()]
    assert len(tracebacks) == 1

    # Held, the job is not evaluated again by the next claim, and Health names it.
    assert claim(api, machine) is None
    assert raised == [bad["id"]]
    store = api.app.state.store
    with store.transaction() as c:
        assert "claim_failed" in {f["check_id"] for f in health_monitor.findings(c, store.settings)}

    # The owner's release queues it again. It raises again, so it is held again, and its traceback is not logged twice.
    post(api, "bots/ops/release", {})
    assert jobs_of(api, "ops")[0]["held"] == 0
    assert claim(api, machine) is None
    assert raised == [bad["id"], bad["id"]]
    assert jobs_of(api, "ops")[0]["held"] == 1
    assert len([r for r in caplog.records if r.exc_info and f"claim failed for {bad['id']}" in r.getMessage()]) == 1


def test_the_writes_a_failing_job_made_before_its_error_are_rolled_back(api, monkeypatch):
    machine = runner(api, "ana")
    two_bots_with_chats(api, machine)
    handed_out = gateway_connection.hand_out

    def failing(c, aid, config):
        if c.execute("SELECT bot FROM attempts WHERE id=?", (aid,)).fetchone()[0] == "ops":
            raise RuntimeError("the runtime configuration cannot be built")
        return handed_out(c, aid, config)
    monkeypatch.setattr(gateway_connection, "hand_out", failing)

    turn = claim(api, machine)
    assert turn["bot"] == "cpo"
    with api.app.state.store.read() as c:
        assert c.execute("SELECT count(*) FROM attempts WHERE bot='ops'").fetchone()[0] == 0
        assert c.execute("SELECT count(*) FROM turns WHERE bot='ops'").fetchone()[0] == 0
    [bad] = jobs_of(api, "ops")
    assert (bad["state"], bad["attempt_id"], bad["held"]) == ("queued", None, 1)
    [good] = jobs_of(api, "cpo")
    assert (good["state"], good["attempt_id"]) == ("leased", turn["id"])


def test_a_moved_input_that_failed_on_the_old_upsert_is_held_and_other_bots_still_claim(api, monkeypatch):
    """A moved input whose upsert fails once the history sweep has indexed the earlier run: fold_behind's upsert on it
    raises. The upsert is put back here at the point fold_behind writes; the job it fails for is held, and a second
    bot's job is handed out in the same claim."""
    machine, attempt, task_id, _ = task_held(api)
    store = api.app.state.store
    with store.transaction() as c:
        verdict = c.execute("SELECT m.id FROM jobs j JOIN messages m ON m.id=j.message_id WHERE j.bot='ops' "
                            "AND j.state='queued' AND m.body LIKE 'VERDICT:%'").fetchone()[0]
        c.execute("INSERT INTO attempt_inputs VALUES(?,?,?)", (attempt["id"], verdict, H.now()))
        cpo_task = H.task_create(c, H.KEEPER, "Price list", "Check the list.", H.bot_actor("cpo"), lint=False)["id"]
        H.task_comment(c, H.KEEPER, cpo_task, "The pricing numbers are in.")
    with store.read() as conn:
        read_deps.sweep(conn)
    post(api, f"jobs/{attempt['job_id']}/reconcile", {"attempt_id": attempt["id"], "decision": "resume",
         "note": "Nothing was pushed yet; carry on from the build.", "acknowledge_uncertain_effects": True})
    assign(api, machine, "cpo")
    ready(api, machine, ["ops", "cpo"])

    recorded = privacy.record_moved_input

    def old_upsert(c, prior_attempt, aid, queued):
        recorded(c, prior_attempt, aid, queued)
        c.execute("INSERT INTO attempt_inputs VALUES(?,?,?) ON CONFLICT(message_id) DO UPDATE SET "
                  "attempt_id=excluded.attempt_id,acked_at=excluded.acked_at", (aid, queued["id"], H.now()))
    monkeypatch.setattr(privacy, "record_moved_input", old_upsert)

    # The claim passes over the held run within the same call, handing out the bot's next job, and the claim after
    # it reaches cpo, whose work the held run never blocked.
    turn = claim(api, machine)
    assert turn is not None and turn["job_id"] != attempt["job_id"]
    assert (claim(api, machine) or {}).get("bot") == "cpo"
    [held] = [j for j in jobs_of(api, "ops") if j["id"] == attempt["job_id"]]
    assert (held["held"], held["hold_reason"], held["state"]) == (1, claim_holds.REASON, "queued")
    assert held["attempt_id"] == attempt["id"]
    with store.read() as c:
        error = c.execute("SELECT detail_json FROM events WHERE action='job.claim_failed' AND target=?",
                          (attempt["job_id"],)).fetchone()
        assert error and json.loads(error[0])["error"] == "IntegrityError"
        # The held job's preparation was rolled back: it made no attempt of its own.
        assert c.execute("SELECT count(*) FROM attempts WHERE job_id=?", (attempt["job_id"],)).fetchone()[0] == 1
        assert any("could not start this run" in note["body"] for note in H.task_comments(c, task_id))


def test_an_error_outside_the_candidate_still_fails_the_claim(api, monkeypatch):
    machine = runner(api, "ana")
    two_bots_with_chats(api, machine)

    def broken(*args, **kwargs):
        raise RuntimeError("the company's turn state cannot be read")
    monkeypatch.setattr(execution.org_turns, "observe", broken)

    with pytest.raises(RuntimeError):
        claim(api, machine)
    assert all(not job["held"] for job in jobs_of(api, "ops") + jobs_of(api, "cpo"))


def test_a_storage_error_in_a_job_check_stops_the_claim_instead_of_holding_the_job(api, monkeypatch):
    machine = runner(api, "ana")
    two_bots_with_chats(api, machine)

    def full_disk(c, row, *args, **kwargs):
        if row["bot"] == "ops":
            error = sqlite3.OperationalError("database or disk is full")
            error.sqlite_errorcode = sqlite3.SQLITE_FULL
            raise error
        return checked(c, row, *args, **kwargs)
    checked = execution.job_refusal
    monkeypatch.setattr(execution, "job_refusal", full_disk)

    # A full disk answers the claim with a retryable 503 (the app's storage handler), and holds nothing.
    answer = api.post("/api/v2/jobs/claim", json={"bot": None, "start_places": True},
                      headers=headers(machine["token"]))
    assert answer.status_code == 503, answer.text
    assert answer.json()["error"]["code"] == "storage_unavailable" and answer.json()["error"]["retryable"] is True
    assert [job["held"] for job in jobs_of(api, "ops")] == [0]


def test_a_task_gets_no_second_job_while_its_held_job_waits(api, monkeypatch):
    machine, task_id = held_refresh(api, monkeypatch)
    assert [(job["state"], job["held"]) for job in task_jobs(api, task_id)] == [("queued", 1)]
    assert claim(api, machine) is None
    assert [job["held"] for job in task_jobs(api, task_id)] == [1]


def test_a_held_job_waits_for_its_release_after_its_task_finishes(api, monkeypatch):
    """The obsolete-notice pass leaves a held job alone. Its release closes the Needs-you item, and the next claim
    cancels the job, now that it is free and obsolete."""
    machine, task_id = held_refresh(api, monkeypatch)
    held = task_jobs(api, task_id)[0]
    with api.app.state.store.transaction() as c:
        H.task_update(c, H.KEEPER, task_id, status="done")
    assert claim(api, machine) is None
    assert (task_jobs(api, task_id)[0]["state"], task_jobs(api, task_id)[0]["held"]) == ("queued", 1)
    assert item_status(api, held["hold_task_id"]) in H.ACTIVE_STATUSES
    assert post(api, "bots/ops/release", {})["released"]["claim"] == 1
    assert item_status(api, held["hold_task_id"]) not in H.ACTIVE_STATUSES
    # The job's checks work again. Had they still raised, the release would hold the job again, as its reason says.
    monkeypatch.undo()
    assert claim(api, machine) is None
    assert task_jobs(api, task_id)[0]["state"] == "cancelled"


def test_release_frees_a_held_job_another_path_cancelled_and_closes_its_item(api, monkeypatch):
    """Archiving a bot cancels its queued jobs, held ones too. Release still frees them and closes the Needs-you item
    they filed, so no item waits on a job that can no longer run."""
    machine, task_id = held_refresh(api, monkeypatch)
    held = task_jobs(api, task_id)[0]
    with api.app.state.store.transaction() as c:
        c.execute("UPDATE jobs SET state='cancelled' WHERE bot='ops' AND state='queued'")
    assert post(api, "bots/ops/release", {})["released"]["claim"] == 1
    assert item_status(api, held["hold_task_id"]) not in H.ACTIVE_STATUSES
    assert [(job["state"], job["held"]) for job in task_jobs(api, task_id)] == [("cancelled", 0)]


def test_a_start_retry_never_hands_out_an_obsolete_notice(api, monkeypatch):
    machine = runner(api, "ana")
    assign(api, machine, "ops")
    ready(api, machine, ["ops"])
    store = api.app.state.store
    post(api, "chat/ops", {"text": "Look at the export."})
    with store.read() as c:
        person_job = c.execute("SELECT j.id FROM jobs j JOIN messages m ON m.id=j.message_id "
                               "WHERE j.bot='ops' AND m.from_actor LIKE 'human:%'").fetchone()[0]
    with store.transaction() as c:
        done = H.task_create(c, H.KEEPER, "Finished export", "Done.", H.bot_actor("ops"), lint=False)["id"]
        c.execute("UPDATE tasks SET status='done' WHERE id=?", (done,))
        c.execute("UPDATE jobs SET state='cancelled' WHERE bot='ops' AND state='queued' AND id<>?", (person_job,))
        conversation = H.task(c, done)["conversation_id"]
        # A claim's obsolete pass cancels a page of CLAIM_MAINTENANCE notices, so one is left queued for the retry.
        for n in range(execution.CLAIM_MAINTENANCE + 1):
            H.say(c, H.KEEPER, "bot:ops", f"PR #{n} checks passed", kind="notice", conversation_id=conversation,
                  refs={"task": done, "trigger": "other", "wake": "update"})
    with store.read() as c:
        assert c.execute("SELECT count(*) FROM jobs WHERE bot='ops' AND state='queued' AND held=0").fetchone()[0] == (
            execution.CLAIM_MAINTENANCE + 2)
    handed_out = gateway_connection.hand_out

    def failing(c, aid, config):
        if c.execute("SELECT job_id FROM attempts WHERE id=?", (aid,)).fetchone()[0] == person_job:
            raise RuntimeError("the runtime configuration cannot be built")
        return handed_out(c, aid, config)
    monkeypatch.setattr(gateway_connection, "hand_out", failing)

    # The person's job fails to start and is held. The retry then finds the notice; the claim passes it over, so no
    # attempt starts for the bot.
    assert claim(api, machine) is None
    with store.read() as c:
        assert c.execute("SELECT count(*) FROM attempts WHERE bot='ops'").fetchone()[0] == 0
        held, reason = c.execute("SELECT held,hold_reason FROM jobs WHERE id=?", (person_job,)).fetchone()
    assert (held, reason) == (1, claim_holds.REASON)


def test_a_bot_budget_refusal_holds_no_job_over_several_claims(api, monkeypatch):
    machine = budget_setup(api, monkeypatch, tasks=6)
    budget = get(api, "bots/ops/budget")
    post(api, "bots/ops/budget", {"turns_per_hour": 2, "expected_revision": budget["revision"]})
    for _ in range(2):
        complete(api, machine, claim(api, machine))
    for _ in range(3):
        assert claim(api, machine) is None
    assert get(api, "bots/ops/budget")["held"]
    assert [job for job in jobs_of(api, "ops") if job["held"]] == []


@pytest.mark.parametrize("broken", ["team defaults", "bot budget"])
def test_a_budget_check_that_raises_fails_the_claim_and_holds_no_job(api, monkeypatch, broken):
    machine = budget_setup(api, monkeypatch, tasks=6)

    def unreadable(*args, **kwargs):
        raise RuntimeError(f"the {broken} cannot be read")
    if broken == "team defaults":
        monkeypatch.setattr(turn_budgets, "team", unreadable)
    else:
        monkeypatch.setattr(turn_budgets, "refusal", unreadable)
    for _ in range(3):
        with pytest.raises(RuntimeError):
            claim(api, machine)
    assert [job for job in jobs_of(api, "ops") if job["held"]] == []


def test_a_claim_holds_at_most_claim_starts_jobs_that_fail_to_start(api, monkeypatch):
    machine = runner(api, "ana")
    assign(api, machine, "ops")
    ready(api, machine, ["ops"])
    total = execution.CLAIM_STARTS + 2
    for n in range(total):
        post(api, "chat/ops", {"text": f"Look at item {n}."})
    starts = []

    def failing(c, aid, config):
        starts.append(aid)
        raise RuntimeError("the runtime configuration cannot be built")
    monkeypatch.setattr(gateway_connection, "hand_out", failing)

    assert claim(api, machine) is None
    assert len(starts) == execution.CLAIM_STARTS
    assert sum(job["held"] for job in jobs_of(api, "ops")) == execution.CLAIM_STARTS
    assert claim(api, machine) is None
    assert sum(job["held"] for job in jobs_of(api, "ops")) == total


@pytest.mark.parametrize("obsolete_ahead", [execution.CLAIM_PICKS - 2, execution.CLAIM_PICKS - 1])
def test_a_claim_passes_over_at_most_claim_picks_obsolete_notices(api, monkeypatch, obsolete_ahead):
    """A claim cancels a page of obsolete notices, then drops the candidates it still reaches under its lock: at most
    CLAIM_PICKS in all, the snapshot's stale first pick among them. Past that it answers none, and the next claim
    cancels the rest and hands the open job out."""
    machine = runner(api, "ana")
    assign(api, machine, "ops")
    ready(api, machine, ["ops"])
    store = api.app.state.store
    with store.transaction() as c:
        done = H.task_create(c, H.KEEPER, "Finished export", "Done.", H.bot_actor("ops"), lint=False)["id"]
        c.execute("UPDATE tasks SET status='done' WHERE id=?", (done,))
        c.execute("UPDATE jobs SET state='cancelled' WHERE bot='ops' AND state='queued'")
        conversation = H.task(c, done)["conversation_id"]
        for n in range(execution.CLAIM_MAINTENANCE + obsolete_ahead):
            H.say(c, H.KEEPER, "bot:ops", f"PR #{n} checks passed", kind="notice", conversation_id=conversation,
                  refs={"task": done, "trigger": "other", "wake": "update"})
    with store.read() as c:
        assert c.execute("SELECT count(*) FROM jobs WHERE bot='ops' AND state='queued' AND held=0").fetchone()[0] == (
            execution.CLAIM_MAINTENANCE + obsolete_ahead)
    with store.transaction() as c:
        open_task = H.task_create(c, H.KEEPER, "Open export", "Do it.", H.bot_actor("ops"), lint=False)["id"]
    [open_job] = task_jobs(api, open_task)

    if obsolete_ahead < execution.CLAIM_PICKS - 1:
        assert claim(api, machine)["job_id"] == open_job["id"]
    else:
        assert claim(api, machine) is None
        with store.read() as c:
            assert c.execute("SELECT state FROM jobs WHERE id=?", (open_job["id"],)).fetchone()[0] == "queued"
        assert claim(api, machine)["job_id"] == open_job["id"]
