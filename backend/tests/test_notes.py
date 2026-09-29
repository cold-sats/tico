"""Quiet notes: something for a bot's next run to know, asking nothing.

Ben, 2026-09-24: each monitor leaves the Product Manager a note after its check, the notes
stack up without waking it, and its daily report, which runs after every monitor has checked,
reads them all in one prompt, each with the time it was sent.
"""

from backend.tests.test_api import api, assign, get, headers, post, ready, runner  # noqa: F401
from backend.store import H


def claim(api, r, next_run=True):
    return post(api, "jobs/claim", {"next_run": next_run}, token=r["token"])["attempt"]


def setup(api):
    r = runner(api)
    assign(api, r, "ops")
    ready(api, r, ["ops"])
    return r


def note(api, text="Cancellations are flat; nothing for Ben today.", to="ops", token="ana-test"):
    return post(api, "notes", {"to": to, "text": text}, token=token)["note"]


def jobs(api, bot="ops"):
    with api.app.state.store.read() as c:
        return c.execute("SELECT count(*) FROM jobs WHERE bot=?", (bot,)).fetchone()[0]


def listed(api, slug="ops"):
    return next(row for row in get(api, "bots") if row["slug"] == slug)


def test_a_note_wakes_nobody_and_waits(api):
    r = setup(api)
    n = note(api)
    assert n["waiting"] is True and n["carried"] is False
    assert n["to"] == "bot:ops" and n["from"] == "human:ana"
    assert jobs(api) == 0
    assert claim(api, r) is None
    assert listed(api)["notes"] == 1
    assert listed(api)["queued"] == 0


def test_the_next_run_carries_every_waiting_note_with_its_time(api):
    r = setup(api)
    first = note(api, "Messages: reply time up 20% on Airbnb.")
    second = note(api, "P&L: fees steady at 3.9%.")
    post(api, "chat/ops", {"text": "Write the daily report."})
    attempt = claim(api, r)
    assert attempt["message"]["body"] == "Write the daily report."
    assert [n["id"] for n in attempt["notes"]] == [first["id"], second["id"]], "oldest first"
    assert attempt["notes"][0]["sent"] == first["created"]
    assert attempt["notes"][0]["text"] == "Messages: reply time up 20% on Airbnb."
    assert listed(api)["notes"] == 0
    shown = get(api, "notes?to=ops")["notes"]
    assert all(n["carried"] and not n["waiting"] for n in shown)


def test_an_older_runner_leaves_them_waiting(api):
    r = setup(api)
    note(api)
    post(api, "chat/ops", {"text": "Hello"})
    assert claim(api, r, next_run=False)["notes"] == []
    assert listed(api)["notes"] == 1


def test_a_failed_run_gives_them_back_and_a_finished_one_does_not(api):
    r = setup(api)
    n = note(api)
    post(api, "chat/ops", {"text": "First"})
    first = claim(api, r)
    post(api, f"attempts/{first['id']}/started", {"thread_id": "t1"}, token=r["token"])
    post(api, f"attempts/{first['id']}/complete", {"outcome": "failed", "text": "boom", "last_seq": 0}, token=r["token"])
    with api.app.state.store.transaction() as c:
        c.execute("UPDATE jobs SET state='cancelled' WHERE state='uncertain'")
    post(api, "chat/ops", {"text": "Second"})
    second = claim(api, r)
    assert [x["id"] for x in second["notes"]] == [n["id"]]
    post(api, f"attempts/{second['id']}/started", {"thread_id": "t2"}, token=r["token"])
    post(api, f"attempts/{second['id']}/complete", {"outcome": "completed", "text": "ok", "last_seq": 0}, token=r["token"])
    post(api, "chat/ops", {"text": "Third"})
    assert claim(api, r)["notes"] == []


def test_a_person_can_take_one_back_before_it_goes(api):
    setup(api)
    n = note(api)
    gone = post(api, f"notes/{n['id']}/cancel", {}, token="ana-test")["note"]
    assert gone["cancelled_at"] and not gone["waiting"]
    assert listed(api)["notes"] == 0
    assert get(api, "notes?to=ops&waiting=true")["notes"] == []


def test_a_carried_note_cannot_be_taken_back(api):
    r = setup(api)
    n = note(api)
    post(api, "chat/ops", {"text": "Go"})
    claim(api, r)
    got = api.post(f"/api/v2/notes/{n['id']}/cancel", json={}, headers=headers())
    assert got.status_code >=400 and "already carried" in got.text


def test_only_a_bot_gets_notes_and_never_an_empty_one(api):
    assert api.post("/api/v2/notes", json={"to": "human:ben", "text": "hi"}, headers=headers()).status_code >= 400
    assert api.post("/api/v2/notes", json={"to": "ops", "text": "   "}, headers=headers()).status_code >= 400


def test_listing_filters_by_time_and_by_waiting(api):
    r = setup(api)
    old = note(api, "yesterday")
    with api.app.state.store.transaction() as c:
        c.execute("UPDATE notes SET created='2026-01-01T00:00:00Z' WHERE id=?", (old["id"],))
    note(api, "today")
    recent = get(api, "notes?to=ops&since=2026-06-01T00:00:00Z")["notes"]
    assert [n["text"] for n in recent] == ["today"]
    assert len(get(api, "notes?to=ops&waiting=true")["notes"]) == 2


def test_the_sql_and_the_python_agree(api):
    setup(api)
    n = note(api)
    with api.app.state.store.read() as c:
        assert H.note_waiting(c, H.note(c, n["id"])) is True
        assert [x["id"] for x in H.notes_waiting(c, "ops")] == [n["id"]]


def test_a_bot_leaves_another_bot_a_note_and_sees_only_its_own(api):
    # The monitors' case: a bot's run leaves the Product Manager a note.
    r = setup(api)
    post(api, "chat/ops", {"text": "Run your check"})
    attempt = claim(api, r)
    left = note(api, "Ops check: all green.", to="cpo", token=attempt["token"])
    assert left["from"] == "bot:ops" and left["to"] == "bot:cpo"
    note(api, "Something only ana sent to coo.", to="coo")
    mine = get(api, "notes", token=attempt["token"])["notes"]
    assert [n["text"] for n in mine] == ["Ops check: all green."]
