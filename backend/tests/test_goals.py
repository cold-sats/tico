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

