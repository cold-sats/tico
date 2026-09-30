"""Goals: every node on the org chart says what it is for; colours, not percentages; KPIs anyone
may log."""

import textwrap

from backend.store import H
from backend.tests.test_api import api, get, headers, post, setup_attempt  # noqa: F401


def company_goal(api, title="Grow revenue 30% this year"):
    return post(api, "goals", {"title": title, "owner": "company"})["goal"]


def test_company_goals_are_the_owners_and_a_proposal_is_accepted_by_the_parents_owner(api):
    top = company_goal(api)
    assert top["status"] is None and top["parent_id"] is None and top["owner"] == "company"
    # Only the owner of the environment sets a company goal, and it supports nothing.
    post(api, "goals", {"title": "Ship faster", "owner": "company"}, token="ben-test", expected=403)
    post(api, "goals", {"title": "Nested", "owner": "company", "parent_id": top["id"]}, expected=422)
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



def test_a_bot_goal_with_no_parent_is_not_a_company_goal(api):
    """A goal's level comes from its owner. A bot's or a person's own goal needs no parent, and a
    company goal is optional: with none there is no company section at all."""
    r, _, attempt = setup_attempt(api, "ops")
    # The bot sets its own goal with nothing above it: no parent to ask a person for.
    mine = post(api, "goals", {"title": "Keep permissions tight", "owner": "me"}, token=attempt["token"])["goal"]
    assert mine["owner"] == "bot:ops" and mine["parent_id"] is None
    # A person sets their own the same way.
    ben = post(api, "goals", {"title": "Ship the rental stats page", "owner": "me"}, token="ben-test")["goal"]
    assert ben["owner"] == "human:ben" and ben["parent_id"] is None
    tree = get(api, "goals/tree")
    assert {g["id"] for g in tree["goals"]} == {mine["id"], ben["id"]}
    assert [g for g in tree["goals"] if g["owner"] == "company"] == []
    assert tree["owners"]["bot:ops"]["kind"] == "bot" and "company" not in tree["owners"]
    # Nobody else's goal is a company goal for `hub goals` either.
    assert get(api, "goals?owner=ops")["company"] == []
    # A bot may not set the company's, nor put a goal on someone above it.
    post(api, "goals", {"title": "Rule the world", "owner": "company"}, token=attempt["token"], expected=403)
    post(api, "goals", {"title": "For Ben", "owner": "ben"}, token=attempt["token"], expected=403)
    # A company goal shows up once the owner sets one, owned by `company`, and unlinking still works.
    top = company_goal(api)
    tree = get(api, "goals/tree")
    assert [g["id"] for g in tree["goals"] if g["owner"] == "company"] == [top["id"]]
    assert tree["owners"]["company"]["kind"] == "company"
    linked = post(api, f"goals/{mine['id']}", {"parent_id": top["id"]}, token=attempt["token"])["goal"]
    assert linked["parent_id"] == top["id"]
    assert post(api, f"goals/{mine['id']}", {"parent_id": ""}, token=attempt["token"])["goal"]["parent_id"] is None


def test_a_person_goal_with_goals_under_it_becomes_the_company_goal_on_upgrade(api):
    """Before an owner existed for goals, a goal with no parent and goals under it was the company goal."""
    old = post(api, "goals", {"title": "Grow", "owner": "ana"})["goal"]
    post(api, "goals", {"title": "Ship", "owner": "ben", "parent_id": old["id"]})
    alone = post(api, "goals", {"title": "Rest", "owner": "cara"})["goal"]
    with api.app.state.store.transaction() as c:
        c.execute("DELETE FROM cloud_migrations WHERE version=43")
    api.app.state.store.initialize(seed_market=False)
    assert owner_of(api, old["id"]) == "company" and owner_of(api, alone["id"]) == "human:cara"


def owner_of(api, goal_id):
    with api.app.state.store.read() as c:
        return c.execute("SELECT owner FROM goals WHERE id=?", (goal_id,)).fetchone()[0]
