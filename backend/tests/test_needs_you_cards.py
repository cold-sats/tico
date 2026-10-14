"""Needs you cards say what they approve, lead with what is due, carry the group they belong in and the bot's
recommendation, show one card per blocker, and the list says how many items went away on their own this week."""

from backend import hubdb as H
from backend.tests.test_api import api, get, post, setup_attempt  # noqa: F401
from backend.tests.test_batch import approval_for_ana

SEND = {"to": ["Jennie Ooten <jennie@acme.example>"], "cc": [], "subject": "$200 for each rental owner you introduce",
        "body_sha256": "a" * 64, "mailbox": "work"}


def test_cards_are_titled_dated_grouped_and_one_per_blocker(api):
    _, _, finance = setup_attempt(api, "finance")
    deal = post(api, "tasks", {"title": "Referral deal for rental owners", "body": "x", "owner": "bot:finance"})
    send = approval_for_ana(api, kind="send", payload=SEND, task=deal["id"], token=finance["token"])
    merge = approval_for_ana(api, kind="merge", payload={"repo": "acme/site", "pr": 12}, task=deal["id"],
                             token=finance["token"])
    keys = post(api, "tasks", {"title": "Add the new OpenAI keys", "body": "Rotate them", "owner": "human:ana",
                               "due": H.shift(H.now(), days=8)}, token=finance["token"])
    murphy = post(api, "tasks", {"title": "Call Murphy back", "body": "About the lease", "owner": "human:ana",
                                 "due": H.shift(H.now(), days=2)}, token=finance["token"])
    # A bot's task waiting on Ana, its BotOps child waiting on her too (parked on her directly, as before a wait
    # became a subtask), and the subtask that asks her: one card.
    vendor = post(api, "tasks", {"title": "Switch the payroll vendor", "body": "x", "owner": "bot:finance"})
    with api.app.state.store.transaction() as c:
        fix = H.task_create(c, "bot:finance", "Give finance the payroll connector", "x", "bot:ops",
                            parent_id=vendor["id"])
        pick = H.task_create(c, "bot:finance", "Gusto or Rippling for payroll?", "Should payroll move to Gusto or Rippling?",
                             "human:ana", parent_id=vendor["id"])
        c.executemany("UPDATE tasks SET status='waiting', waiting_on='human:ana', note=? WHERE id=?",
                      [("Waiting on Ana to pick the vendor.", vendor["id"]), ("Same pick.", fix["id"])])
        gusto = H.say(c, "bot:finance", "human:ana", "Gusto or Rippling?", kind="ask",
              conversation_id=H.task(c, pick["id"])["conversation_id"],
              refs={"task": pick["id"], "if_no_answer": {"do": "Gusto", "kind": "reversible"},
                    "questions": [{"id": "q", "question": "Which?", "multi": False, "other": False,
                                   "options": [{"label": "Gusto"}, {"label": "Rippling"}]}]})
    page = get(api, "needs-you")
    items = {i["id"]: i for i in page["items"]}

    assert items[send["id"]]["title"] == "Send: '$200 for each rental owner you introduce' to Jennie Ooten"
    assert items[merge["id"]]["title"] == "Merge: 'Referral deal for rental owners' (acme/site #12)"
    assert (items[send["id"]]["need"], items[merge["id"]]["need"], items[keys["id"]]["need"]) == ("review", "review",
                                                                                                    "connect")
    # Due first, soonest first.
    assert [i["id"] for i in page["items"][:2]] == [murphy["id"], keys["id"]]

    card = items[pick["id"]]
    assert card["need"] == "decide" and card["recommend"]["do"] == "Gusto" and card["recommend"]["option"] == "Gusto"
    assert vendor["id"] not in items and fix["id"] not in items
    assert {f["id"] for f in card["folded"]} == {vendor["id"], fix["id"]}
    assert get(api, "needs-you?count=1")["count"] == len(page["items"])

    # Two cards asking Ana different things in one family both stay.
    with api.app.state.store.transaction() as c:
        H.task_create(c, "bot:finance", "Sign the payroll contract", "Can you sign the payroll contract today?", "human:ana",
                      parent_id=vendor["id"])
    assert pick["id"] in {i["id"] for i in get(api, "needs-you")["items"]}
    assert vendor["id"] in {i["id"] for i in get(api, "needs-you")["items"]}

    assert page["went_away"]["total"] == 0
    with api.app.state.store.transaction() as c:
        H.event(c, H.KEEPER, "ask.expired", "m1", {"to": "human:ana", "bot": "bot:finance"})
        H.event(c, H.KEEPER, "ask.went_ahead", "m2", {"to": "human:ben", "bot": "bot:finance"})
    assert get(api, "needs-you")["went_away"]["expired"] == 1

    # Taking the recommendation picks the option it names, as a tap on it would, and finishes Ana's card.
    post(api, "needs-you/recommended", {"ask": gusto["id"]})
    assert get(api, f"tasks/{pick['id']}")["task"]["status"] == "done"
    assert get(api, f"tasks/{pick['id']}/answers")["answers"][0]["answers"] == {"q": ["Gusto"]}


def test_do_what_you_recommend_answers_and_closes_the_card(api):
    _, _, finance = setup_attempt(api, "finance")
    tool = post(api, "tasks", {"title": "Pick the outbound tool", "body": "x", "owner": "bot:finance"})
    with api.app.state.store.transaction() as c:
        conv = H.task(c, tool["id"])["conversation_id"]
        plain = H.say(c, "bot:finance", "human:ana", "Which day suits?", kind="ask", conversation_id=conv,
                      refs={"task": tool["id"]})
        asked = H.say(c, "bot:finance", "human:ana", "Shall I go with Apollo?", kind="ask", conversation_id=conv,
                      refs={"task": tool["id"], "if_no_answer": {"do": "Go with Apollo", "kind": "reversible"}})
        c.execute("UPDATE tasks SET status='waiting', waiting_on='human:ana' WHERE id=?", (tool["id"],))
    card = next(i for i in get(api, "needs-you")["items"] if i["id"] == tool["id"])
    assert card["recommend"]["do"] == "Go with Apollo" and card["need"] == "decide"
    post(api, "needs-you/recommended", {"ask": plain["id"]}, expected=409)        # no recommendation to take
    post(api, "needs-you/recommended", {"ask": asked["id"]}, token="ben-test", expected=403)
    post(api, "needs-you/recommended", {"ask": asked["id"]})
    with api.app.state.store.read() as c:
        said = c.execute("SELECT body FROM messages WHERE in_reply_to=? AND kind='answer'", (asked["id"],)).fetchone()
        assert said["body"] == "Yes, do what you recommend: Go with Apollo"
        assert not H.task(c, tool["id"])["waiting_on"]
    post(api, "needs-you/recommended", {"ask": asked["id"]}, expected=409)        # once
