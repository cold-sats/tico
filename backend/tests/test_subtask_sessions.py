"""A subtask continues its parent task's session (hubdb.session_root), and a person finishing one under a
bot's task wakes the bot on the parent."""
import json

from backend.store import H
from backend.tests.test_api import api, assign, claim, get, post, runner  # noqa: F401  (api is a fixture)
from runner import state


def tasks(api, *specs):
    """Each spec is (owner, parent index or None), filed by ana; returns their ids."""
    ids = []
    with api.app.state.store.transaction() as c:
        for n, (owner, parent) in enumerate(specs):
            row = H.task_create(c, "human:ana", f"Step {n} of the launch", "Do this step.", owner,
                                parent_id=ids[parent] if parent is not None else None, lint=False)
            ids.append(row["id"])
    return ids


def test_the_root_walks_up_same_owner_parents_and_stops_at_another_owner_or_a_loop(api):
    top, mid, person, under_person, own = tasks(api, ("bot:ops", None), ("bot:ops", 0), ("human:ana", 1),
                                                ("bot:ops", 2), ("bot:ops", 1))
    with api.app.state.store.transaction() as c:
        assert H.session_root(c, "ops", own) == top
        assert H.session_root(c, "ops", person) == top           # a person's subtask under the bot's task
        assert H.session_root(c, "ops", under_person) == under_person
        assert H.session_root(c, "ops", own, {"subtask_session": "own"}) == own
        # A loop in the parent links ends the walk instead of spinning.
        c.execute("INSERT INTO task_relations(from_task,to_task,kind,created) VALUES(?,?,'parent',?)",
                  (top, own, H.now()))
        assert H.session_root(c, "ops", own) == top


def test_a_private_subtask_shares_a_private_parents_session_only_when_both_have_the_same_readers(api):
    with api.app.state.store.transaction() as c:
        parent = H.task_create(c, "human:ana", "Plan the private launch", "x", "bot:ops", private=True, lint=False)["id"]
        shared = H.task_create(c, "human:ana", "Draft the private copy", "x", "bot:ops", parent_id=parent,
                               private=True, lint=False)["id"]
        # The bot's own private subtask: ana, on the parent, cannot read it.
        apart = H.task_create(c, "human:ana", "Check the private figures", "x", "bot:ops", parent_id=parent,
                              private=True, lint=False)["id"]
        c.execute("UPDATE tasks SET requester='bot:ops' WHERE id=?", (apart,))
        public = H.task_create(c, "human:ana", "Draft the public copy", "x", "bot:ops", parent_id=parent,
                               lint=False)["id"]
        c.execute("UPDATE tasks SET private=0 WHERE id=?", (public,))    # made public later
        assert H.session_root(c, "ops", shared) == parent
        assert H.session_root(c, "ops", apart) == apart
        assert H.session_root(c, "ops", public) == public


def roots_runner(api, capabilities):
    with api.app.state.store.transaction() as c:
        config = json.loads(c.execute("SELECT config_json FROM bot_config WHERE bot='ops'").fetchone()[0])
        c.execute("UPDATE bot_config SET config_json=? WHERE bot='ops'", (json.dumps({**config, "session": "task"}),))
    machine = runner(api)
    assign(api, machine, "ops")
    post(api, "runners/heartbeat", {"version": "test", "platform": "test", "readiness": {"ops": True},
                                    "capabilities": capabilities}, token=machine["token"])
    return machine


def test_a_subtask_turn_runs_in_its_parents_lane_and_session_and_links_and_checkpoints_the_parent(api):
    machine = roots_runner(api, ["task_lanes_v2", "session_roots_v1"])
    parent, sub = tasks(api, ("bot:ops", None), ("bot:ops", 0))
    first = claim(api, machine)
    assert first["lane"] == "task:" + parent and first["task"]["session_task_id"] == parent
    assert claim(api, machine) is None, "the subtask waits behind its parent's turn in the same lane"
    post(api, f"attempts/{first['id']}/started", {"thread_id": "t-parent"}, machine["token"])
    post(api, f"attempts/{first['id']}/complete", {"outcome": "completed", "last_seq": 0, "text": "Planned."},
         machine["token"])
    turn = claim(api, machine)
    assert turn["task"]["id"] == sub
    assert (turn["lane"], turn["task"]["session_task_id"]) == ("task:" + parent, parent)
    assert turn["task"]["checkpoint"] == "Planned.", "a fresh session starts from the root's checkpoint"
    assert state.session_key({"session": "task"}, turn) == "task:" + parent
    post(api, f"attempts/{turn['id']}/started", {"thread_id": "t-parent"}, machine["token"])
    with api.app.state.store.transaction() as c:       # moved out from under the parent mid-turn
        c.execute("DELETE FROM task_relations WHERE from_task=? AND kind='parent'", (sub,))
    post(api, f"attempts/{turn['id']}/complete",
         {"outcome": "completed", "last_seq": 0, "text": "Step 1 drafted."}, machine["token"])
    with api.app.state.store.read() as c:
        assert [link["url"] for link in H.task_links(c, parent) if link["kind"] == "session"] == ["session:ops/t-parent"]
        assert [link for link in H.task_links(c, sub) if link["kind"] == "session"] == []
    assert get(api, "tasks/" + parent)["task"]["checkpoint"] == "Step 1 drafted."
    assert not get(api, "tasks/" + sub)["task"].get("checkpoint")


def test_an_older_runner_and_subtask_session_own_keep_each_subtask_its_own_session(api):
    machine = roots_runner(api, ["task_lanes_v2"])
    parent, sub = tasks(api, ("bot:ops", None), ("bot:ops", 0))
    lanes = {claim(api, machine)["lane"] for _ in range(2)}
    assert lanes == {"task:" + parent, "task:" + sub}
    with api.app.state.store.read() as c:
        assert H.session_root(c, "ops", sub, {"subtask_session": "own"}) == sub
    turn = {"bot": "ops", "task": {"id": sub}}             # no session_task_id: keyed on the subtask
    assert state.session_key({}, turn) == "task:" + sub


def test_a_person_finishing_a_subtask_wakes_the_bot_once_on_the_parent(api):
    parent, = tasks(api, ("bot:ops", None))
    with api.app.state.store.transaction() as c:
        sub = H.task_create(c, "bot:ops", "Approve the launch copy", "Yes or no.", "human:ana", parent_id=parent,
                            lint=False)["id"]

    def notices():
        with api.app.state.store.read() as c:
            return [(json.loads(r[0]).get("task"), json.loads(r[0]).get("subtask")) for r in c.execute(
                "SELECT m.refs_json FROM jobs j JOIN messages m ON m.id=j.message_id "
                "WHERE j.bot='ops' AND j.state='queued' AND m.kind='notice' AND m.rowid>? ORDER BY m.rowid", (since,))]

    with api.app.state.store.read() as c:
        since = c.execute("SELECT max(rowid) FROM messages").fetchone()[0]
    with api.app.state.store.transaction() as c:
        H.task_update(c, "human:ana", sub, status="done", note="Approved.")
    assert notices() == [(parent, sub)]
    with api.app.state.store.transaction() as c:       # closing it after done is acceptance: nothing more
        H.task_close(c, "human:ana", sub)
    assert notices() == [(parent, sub)]
    # A quiet update tells the parent the title and status, never the note.
    with api.app.state.store.transaction() as c:
        quiet = H.task_create(c, "bot:ops", "Approve the budget", "Yes or no.", "human:ana", parent_id=parent,
                              lint=False)["id"]
        H.task_update(c, "human:ana", quiet, status="done", note="Salary detail: 140k.", quiet=True)
        [body] = [m["body"] for m in H.messages(c, H.task(c, parent)["conversation_id"])
                  if (m.get("refs") or {}).get("subtask") == quiet]
    assert "Approve the budget" in body and "140k" not in body


def test_a_turn_reads_only_its_own_lane_of_the_room_and_the_main_chat_keeps_the_task_lines(api):
    from backend import execution
    (tid,) = tasks(api, ("bot:finance", None))
    chat = {"id": "room", "kind": "chat"}
    page = [{"id": "hi", "refs": {}}, {"id": "work", "refs": {"task": tid}},
            {"id": "report", "refs": {"task": tid, "task_report": "done"}}]
    with api.app.state.store.read() as c:
        main = execution.lane_history(c, "finance", {}, page, chat, "main")
        own = execution.lane_history(c, "finance", {}, page, chat, "task:" + tid)
    assert [m["id"] for m in main] == ["hi", "report"] and [m["id"] for m in own] == ["work"]
