"""A computer's Screen setting starts at View the first time it offers a screen, unless a person already chose one."""

from backend.tests.test_api import api, get, post, runner  # noqa: F401  (the api fixture)


def heartbeat(api, r, offers):
    readiness = {"schema_version": 1, **({"screen": {"available": True, "width": 1440, "height": 900}} if offers else {})}
    post(api, "runners/heartbeat", {"version": "test", "platform": "test", "capabilities": ["screen_v1"] if offers else [],
                                    "readiness": readiness}, token=r["token"])


def mode(api, rid):
    return next(m for m in get(api, "operations")["computers"] if m["id"] == rid)["screen"]


def test_a_computer_offering_its_screen_starts_at_view_and_a_persons_choice_stands(api):
    r = runner(api)
    rid = r["runner_id"]
    heartbeat(api, r, False)
    assert mode(api, rid) == "off"                      # no screen offered, nothing to view
    heartbeat(api, r, True)
    assert mode(api, rid) == "view"
    with api.app.state.store.read() as c:
        rows = c.execute("SELECT actor FROM events WHERE action='runner.screen' AND target=?", (rid,)).fetchall()
    assert [row["actor"] for row in rows] == ["system"]

    post(api, f"computers/{rid}/screen", {"mode": "off"})
    heartbeat(api, r, False)                            # the display restarts: the screen goes and comes back
    heartbeat(api, r, True)
    assert mode(api, rid) == "off"


def test_a_choice_made_before_the_first_offer_stands(api):
    r = runner(api)
    rid = r["runner_id"]
    heartbeat(api, r, True)
    post(api, f"computers/{rid}/screen", {"mode": "control"})
    heartbeat(api, r, False)
    heartbeat(api, r, True)
    assert mode(api, rid) == "control"
    post(api, f"computers/{rid}/screen", {"mode": "off"})
    heartbeat(api, r, True)
    assert mode(api, rid) == "off"


def test_a_computer_that_never_offers_a_screen_stays_off(api):
    r = runner(api)
    heartbeat(api, r, False)
    heartbeat(api, r, False)
    assert mode(api, r["runner_id"]) == "off"
