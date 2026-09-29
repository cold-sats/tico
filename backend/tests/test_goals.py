"""Goals: every node on the org chart says what it is for; colours, not percentages; KPIs anyone
may log."""

import textwrap

from backend.store import H
from backend.tests.test_api import api, get, headers, post, setup_attempt  # noqa: F401


def company_goal(api, title="Grow revenue 30% this year"):
    return post(api, "goals", {"title": title, "owner": "ana"})["goal"]


def test_company_goals_are_the_owners_and_a_proposal_is_accepted_by_the_parents_owner(api):
    top = company_goal(api)
    assert top["status"] is None and top["parent_id"] is None and top["owner"] == "human:ana"
    # Only the owner of the environment sets a company goal.
    post(api, "goals", {"title": "Ship faster", "owner": "ben"}, token="ben-test", expected=403)
    # Ben proposes his own goal under it: proposed, no colour yet.
    mine = post(api, "goals", {"title": "Ship the rental stats page", "owner": "me", "parent_id": top["id"]},
                token="ben-test")["goal"]
    assert mine["owner"] == "human:ben" and mine["status"] is None and mine["chain"][0]["id"] == top["id"]
    # He cannot accept it himself; Ana, who owns the parent, does, and a colour needs a sentence.
    post(api, f"goals/{mine['id']}/status", {"status": "green", "note": "on track"}, token="ben-test", expected=403)
    post(api, f"goals/{mine['id']}/status", {"status": "green"}, expected=422)
    accepted = post(api, f"goals/{mine['id']}/status", {"status": "green", "note": "Design is done, build starts Monday."})["goal"]
    assert accepted["status"] == "green" and accepted["status_by"] == "human:ana" and accepted["status_at"]
    # From then on the owner sets the colour, and the history says who said what.
    yellow = post(api, f"goals/{mine['id']}/status", {"status": "yellow", "note": "Backend is late."}, token="ben-test")["goal"]
    assert yellow["status"] == "yellow"
    assert [e["new"] for e in yellow["events"] if e["field"] == "status"] == ["green", "yellow"]
    # Cara is neither the owner nor above him.
    post(api, f"goals/{mine['id']}/status", {"status": "red", "note": "Nope."}, token="cara-test", expected=403)


def test_kpis_are_logged_by_anyone_and_an_estimate_never_counts_as_measured(api):
    top = company_goal(api)
    goal = post(api, "goals", {"title": "Book 50% more rental demos every two weeks", "owner": "cpo",
                               "parent_id": top["id"]})["goal"]
    kpi = post(api, f"goals/{goal['id']}/kpis", {"name": "booked Calendly demos per two weeks", "unit": "demos",
                                                 "target": 48})["kpi"]
    assert kpi["target"] == 48 and kpi["unit"] == "demos"
    # Cara is nobody on this goal and still logs a fact; the baseline weeks keep their real dates.
    post(api, f"kpis/{kpi['id']}/readings", {"value": 17, "at": "2026-08-17", "note": "week of 11 Aug"}, token="cara-test")
    post(api, f"kpis/{kpi['id']}/readings", {"value": 15, "at": "2026-08-24T00:00:00Z"}, token="cara-test")
    post(api, f"kpis/{kpi['id']}/readings", {"value": 40, "source": "estimate", "note": "pace so far"}, token="ben-test")
    shown = get(api, f"goals/{goal['id']}")["goal"]
    measure = shown["kpis"][0]
    assert measure["readings"] == 3
    assert measure["latest"]["source"] == "estimate" and measure["latest"]["value"] == 40
    assert measure["latest_measured"]["value"] == 15 and measure["latest_measured"]["ts"].startswith("2026-08-24")
    series = get(api, f"kpis/{kpi['id']}/readings")["readings"]
    assert [r["value"] for r in series] == [17, 15, 40]
    # A reading is a goal event too, so the history reads as one story.
    assert [e["new"] for e in shown["events"] if e["field"] == "reading"][0] == "booked Calendly demos per two weeks: 17 demos"
    # A bad date is refused, nothing written.
    post(api, f"kpis/{kpi['id']}/readings", {"value": 1, "at": "yesterday"}, expected=422)
    # Only the goal's owner or someone above changes the measure itself.
    post(api, f"kpis/{kpi['id']}", {"target": 60}, token="cara-test", expected=403)
    assert post(api, f"kpis/{kpi['id']}", {"target": 60})["kpi"]["target"] == 60


def test_a_goals_owner_links_and_removes_it_without_waiting_for_acceptance(api):
    """Goals are plain lines on the org chart; the link icon picks the goal it
    supports and an emptied line is removed, both by whoever owns the goal."""
    top = company_goal(api)
    other = company_goal(api, "Keep churn under 2%")
    mine = post(api, "goals", {"title": "Ship the rental stats page", "owner": "me", "parent_id": top["id"]},
                token="ben-test")["goal"]
    # Ben links his own proposed goal to another goal.
    moved = post(api, f"goals/{mine['id']}", {"parent_id": other["id"]}, token="ben-test")["goal"]
    assert moved["parent_id"] == other["id"]
    # Cara neither owns it nor sits above it.
    post(api, f"goals/{mine['id']}", {"parent_id": top["id"]}, token="cara-test", expected=403)
    # Making it a company goal, or handing it to someone else, is still not his.
    post(api, f"goals/{mine['id']}", {"parent_id": ""}, token="ben-test", expected=403)
    post(api, f"goals/{mine['id']}", {"owner": "cara"}, token="ben-test", expected=403)
    # A loop is refused.
    post(api, f"goals/{other['id']}", {"parent_id": mine["id"]}, expected=422)
    # He removes it; accepting it is still not his.
    post(api, f"goals/{mine['id']}/status", {"status": "green", "note": "fine"}, token="ben-test", expected=403)
    dropped = post(api, f"goals/{mine['id']}/status", {"status": "dropped", "note": ""}, token="ben-test")["goal"]
    assert dropped["status"] == "dropped"
