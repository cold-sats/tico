"""The redesign's audit trail (backend/audit_log.py): rows written with their change, read newest first, paged,
the owner seeing all and anyone else only their own, and the route gone while the redesign is off."""
from urllib.parse import urlencode

from backend import audit_log, redesign
from backend.tests.test_api import api, get  # noqa: F401


def _write(api, *changes):
    with api.app.state.store.transaction() as c:
        redesign.set_on(c, True, "human:ana")
        for actor, obj, before, after in changes:
            audit_log.write(c, actor, obj, before, after)


def test_off_the_route_is_not_there(api):
    get(api, "audit", expected=404)


def test_owner_reads_every_row_newest_first_with_before_and_after(api):
    _write(api, ("human:ana", "task_cap:1", None, {"per_day": 5}),
           ("human:ben", "task_cap:1", {"per_day": 5}, {"per_day": 7}))
    rows = get(api, "audit?object=task_cap:1")["rows"]
    assert [(r["actor"], r["before"], r["after"]) for r in rows] == [
        ("human:ben", {"per_day": 5}, {"per_day": 7}), ("human:ana", None, {"per_day": 5})]


def test_anyone_else_reads_only_their_own_changes(api):
    _write(api, ("human:ana", "automation:a", None, {"n": 1}), ("human:ben", "automation:b", None, {"n": 2}))
    assert [r["object"] for r in get(api, "audit", token="ben-test")["rows"]] == ["automation:b"]


def test_pages_by_before(api):
    _write(api, *[("human:ana", f"group:{i}", None, {"i": i}) for i in range(5)])
    first = get(api, "audit?limit=2")
    assert len(first["rows"]) == 2 and first["next"]
    rest = get(api, "audit?" + urlencode({"limit": 10, "before": first["next"]}))
    assert len(rest["rows"]) == 3 and rest["next"] is None


def test_rows_sharing_a_time_are_never_skipped(api, monkeypatch):
    from backend import audit_log as A
    monkeypatch.setattr(A.H, "now", lambda: "2026-10-28T00:00:00.000000Z")
    _write(api, *[("human:ana", f"group:{i}", None, {"i": i}) for i in range(5)])
    seen, cursor = [], None
    while True:
        page = get(api, "audit?" + urlencode({"limit": 2, **({"before": cursor} if cursor else {})}))
        seen += [r["object"] for r in page["rows"]]
        if not (cursor := page["next"]):
            break
    assert sorted(seen) == [f"group:{i}" for i in range(5)]
