"""A job whose claim raises is held with its reason, and no claim evaluates it again; the other bots still start.

The claim checks each candidate job and prepares the one it hands out. An error in either belongs to that job: its
writes are rolled back, its traceback is logged once, and the job is held (backend/claim_holds.py). Storage errors and
errors outside a candidate are not this job's, and they still fail the claim.
"""
import json
import sqlite3

import pytest

from backend import claim_holds, execution, gateway_connection, health_monitor, read_deps, task_privacy as privacy
from backend.store import H
from backend.tests.test_api import api, assign, claim, headers, post, ready, runner  # noqa: F401 (api is a fixture)
from backend.tests.test_held_runs import task_held


def jobs_of(api, bot):
    with api.app.state.store.read() as c:
        return [dict(r) for r in c.execute("SELECT id,state,held,hold_reason,hold_task_id,attempt_id FROM jobs "
                                           "WHERE bot=? ORDER BY created,id", (bot,))]


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
    """The failure 3904d736d fixed: fold_behind's upsert on a moved input fails once the history sweep has indexed the
    earlier run. The upsert is put back here at the point fold_behind writes; the job it fails for is held, and a
    second bot's job is handed out in the same claim."""
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
