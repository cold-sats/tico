"""A computer's and a bot's "Turns at once": the claim holds new turns at the limit, and says so."""
from backend.store import H
from backend.tests.test_api import api, as_member, claim, get, post  # noqa: F401  (api is a fixture)
from backend.tests.test_task_lanes import new_task, task_bot

NEW_RUNNER = ["task_lanes_v2", "turns_at_once_v1"]


def set_computer(api, machine, limit, expected=200):
    return post(api, f"computers/{machine['runner_id']}/turns-at-once", {"turns_at_once": limit}, expected=expected)


def set_bot(api, limit, expected=200, token="ana-test"):
    revision = get(api, "bots/ops")["revision"]
    return post(api, "bots/ops/turns-at-once", {"turns_at_once": limit, "expected_revision": revision},
                token=token, expected=expected)


def heartbeat(api, machine, capacity, capabilities):
    return post(api, "runners/heartbeat", {"version": "test", "platform": "test", "capacity": capacity,
                                           "readiness": {"ops": True}, "capabilities": capabilities},
                token=machine["token"])


def test_a_lowered_computer_limit_holds_new_turns_at_once_and_clearing_it_restores_the_capacity(api):
    machine = task_bot(api, lanes=True, capacity=4)
    for title in ("first", "second", "third"):
        new_task(api, title)
    assert claim(api, machine) and claim(api, machine)
    assert set_computer(api, machine, 2)["turn_limit"] == 2
    # The server holds the third turn at once: the runner has not heard of the lower limit yet.
    assert claim(api, machine) is None
    assert set_computer(api, machine, None)["turn_limit"] == 4
    assert claim(api, machine)["bot"] == "ops"


def test_a_raised_computer_limit_admits_more_turns_on_a_runner_that_takes_it(api):
    machine = task_bot(api, lanes=True, capacity=2)
    heartbeat(api, machine, 2, NEW_RUNNER)
    for title in ("first", "second", "third", "fourth"):
        new_task(api, title)
    assert set_computer(api, machine, 3)["turn_limit"] == 3
    # The runner learns the limit in its heartbeat reply, which is what it gates its own starts on.
    assert heartbeat(api, machine, 2, NEW_RUNNER)["turns_at_once"] == 3
    assert [claim(api, machine) is not None for _ in range(3)] == [True, True, True]
    assert claim(api, machine) is None


def test_a_runner_that_cannot_take_a_raised_limit_runs_at_the_capacity_it_reports(api):
    machine = task_bot(api, lanes=True, capacity=2)
    for title in ("first", "second", "third"):
        new_task(api, title)
    assert set_computer(api, machine, 5)["turn_limit"] == 2
    assert claim(api, machine) and claim(api, machine)
    assert claim(api, machine) is None


def test_a_bot_at_its_limit_holds_its_work_while_another_bot_on_the_computer_runs(api):
    machine = task_bot(api, lanes=True, capacity=4, others=("finance",))
    ops_tasks = [new_task(api, "first"), new_task(api, "second")]
    new_task(api, "review", owner="finance")
    assert set_bot(api, 1)["turns_at_once"] == 1
    assert claim(api, machine)["bot"] == "ops"
    # ops holds its one turn: its next work waits and says so, and finance's work still starts.
    assert claim(api, machine)["bot"] == "finance"
    assert claim(api, machine) is None
    assert get(api, "tasks/" + ops_tasks[1]["id"])["waiting_for"] == "At its turn limit"
    assert get(api, "bots/ops")["turns_at_once"] == 1


def test_clearing_the_bot_limit_lets_its_queued_work_start_again(api):
    machine = task_bot(api, lanes=True, capacity=4)
    new_task(api, "first")
    new_task(api, "second")
    set_bot(api, 1)
    assert claim(api, machine) is not None
    assert claim(api, machine) is None
    set_bot(api, None)
    assert claim(api, machine) is not None


def test_only_a_bot_manager_or_an_admin_sets_the_limits_and_the_bounds_hold(api):
    machine = task_bot(api, lanes=True)
    as_member(api, "ben@acme.example")
    set_bot(api, 3, expected=403, token="ben-test")
    post(api, f"computers/{machine['runner_id']}/turns-at-once", {"turns_at_once": 3}, token="ben-test", expected=403)
    for bad in (0, 257, -1, "3", True, 1.5):
        set_bot(api, bad, expected=422)
        post(api, f"computers/{machine['runner_id']}/turns-at-once", {"turns_at_once": bad}, expected=422)


def test_the_bot_limit_is_in_the_settings_history_and_undo_restores_the_previous_value(api):
    set_bot(api, 2)
    change = next(row for row in get(api, "settings/history")["changes"] if row["field"] == "turns_at_once")
    post(api, "settings/history/" + change["id"] + "/undo", {"expected_revision": get(api, "bots/ops")["revision"]})
    assert get(api, "bots/ops")["turns_at_once"] is None


def test_health_names_a_bot_at_its_limit_by_its_reason_and_says_so(api):
    machine = task_bot(api, lanes=True, capacity=4)
    new_task(api, "first")
    new_task(api, "second")
    set_bot(api, 1)
    assert claim(api, machine) is not None
    # Health lists work only once it has waited a while (health.QUEUE_MINUTES), like any held work.
    with api.app.state.store.transaction() as c:
        c.execute("UPDATE jobs SET created=? WHERE state='queued'", (H.shift(H.now(), minutes=-30),))
    stuck = [row for row in get(api, "health")["stuck"] if row.get("bot") == "ops"]
    assert [row["reason"] for row in stuck] == ["bot_limit"], stuck
    assert "At its turn limit" in stuck[0]["why"]
