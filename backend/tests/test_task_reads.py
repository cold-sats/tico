"""Task lists that cost only what changed (backend/task_reads.py): a delta read from a cursor says
what changed and what left, never naming a task the reader could not have seen; a stale cursor
resets; an unchanged full read is a 304."""

from backend import events as E
from backend import hubdb as H
from backend.tests.test_api import api, get, headers, post, restrict  # noqa: F401

ACTIVE = "status=open,doing,waiting,review,ready,declined"


def tasks(api, query, token="ana-test"):
    return get(api, "tasks?" + query, token=token)


def delta(api, query, cursor, token="ana-test"):
    return tasks(api, f"{query}&changed_after={cursor}", token=token)


def test_a_delta_returns_what_changed_and_what_left(api):
    keep = post(api, "tasks", {"owner": "ben", "title": "Draft the agenda", "body": "Please."})
    finish = post(api, "tasks", {"owner": "ben", "title": "Book the room", "body": "Please."})
    trash = post(api, "tasks", {"owner": "ben", "title": "Order lunch", "body": "Please."})
    quiet = post(api, "tasks", {"owner": "ben", "title": "Print the badges", "body": "Please."})
    cursor = tasks(api, ACTIVE)["cursor"]
    assert delta(api, ACTIVE, cursor) == {"tasks": [], "gone": [], "cursor": cursor, "next_offset": None}

    post(api, "tasks/" + keep["id"], {"version": keep["version"], "title": "Draft the agenda today"})
    post(api, "tasks/" + finish["id"], {"version": finish["version"], "status": "done"})
    post(api, "tasks/" + trash["id"] + "/delete", {})
    got = delta(api, ACTIVE, cursor)
    assert [t["title"] for t in got["tasks"]] == ["Draft the agenda today"]
    assert sorted(got["gone"]) == sorted([finish["id"], trash["id"]])
    assert quiet["id"] not in str(got) and got["cursor"] != cursor
    # Nothing since the new cursor.
    assert delta(api, ACTIVE, got["cursor"])["tasks"] == []


def test_a_task_made_private_is_gone_only_for_who_could_see_it(api):
    shared = post(api, "tasks", {"owner": "ben", "title": "Review the launch copy", "body": "Please."})
    secret = post(api, "tasks", {"owner": "ben", "title": "Review the salary bands", "body": "Please.", "private": True})
    before = tasks(api, ACTIVE, token="cara-test")
    cara, ana = before["cursor"], tasks(api, ACTIVE)["cursor"]
    assert shared["id"] in str(before) and secret["id"] not in str(before)

    post(api, "tasks/" + shared["id"], {"version": shared["version"], "private": True})
    post(api, "tasks/" + secret["id"], {"version": secret["version"], "title": "Review the salary bands now"})
    got = delta(api, ACTIVE, cara, token="cara-test")
    assert got["gone"] == [shared["id"]] and got["tasks"] == []
    assert secret["id"] not in str(got)
    # Its parties still get it, private and changed.
    ana = delta(api, ACTIVE, ana)
    assert {t["id"] for t in ana["tasks"]} == {shared["id"], secret["id"]} and ana["gone"] == []


def test_a_cursor_the_log_no_longer_covers_or_other_access_resets(api):
    old = tasks(api, ACTIVE, token="cara-test")["cursor"]
    post(api, "tasks", {"owner": "ben", "title": "Clear the old work", "body": "Please."})
    assert E.sweep(api.app.state.store, H.shift(H.now(), hours=E.KEEP_HOURS + 1)) > 0
    post(api, "tasks", {"owner": "ben", "title": "Plan the new work", "body": "Please."})
    got = delta(api, ACTIVE, old, token="cara-test")
    assert got["reset"] is True and got["tasks"] == [] and got["cursor"] != old
    assert delta(api, ACTIVE, "999999." + old.split(".")[1], token="cara-test")["reset"] is True
    assert delta(api, ACTIVE, "nonsense", token="cara-test")["reset"] is True
    # Access changed since the cursor (ops's activity closed to Cara): read in full.
    fresh = tasks(api, ACTIVE, token="cara-test")["cursor"]
    with api.app.state.store.transaction() as c:
        restrict(c, "ops", people=["ana"])
    assert delta(api, ACTIVE, fresh, token="cara-test")["reset"] is True


def test_an_unchanged_full_read_is_a_304_until_a_task_or_a_grant_changes(api):
    task = post(api, "tasks", {"owner": "ops", "title": "Check the backups", "body": "Please."})

    def read(path, tag=None):
        return api.get("/api/v2/" + path, headers={**headers("cara-test"), **({"If-None-Match": tag} if tag else {})})
    for path in ("tasks?" + ACTIVE, "tasks/labels", "routines"):
        first = read(path)
        tag = first.headers["etag"]
        again = read(path, tag)
        assert again.status_code == 304 and again.content == b"" and again.headers["etag"] == tag, path

    tag = read("tasks?" + ACTIVE).headers["etag"]
    assert read("tasks?" + ACTIVE + "&brief=true", tag).status_code == 200      # another query, another tag
    post(api, "tasks/" + task["id"], {"version": task["version"], "title": "Check the backups twice"})
    changed = read("tasks?" + ACTIVE, tag)
    assert changed.status_code == 200 and "Check the backups twice" in changed.text
    tag = changed.headers["etag"]
    with api.app.state.store.transaction() as c:
        restrict(c, "ops", people=["ana"])
    hidden = read("tasks?" + ACTIVE, tag)
    assert hidden.status_code == 200 and task["id"] not in hidden.text
