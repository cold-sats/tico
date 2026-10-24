"""The Updates chat (backend/updates_chat.py; spec: CEO Bot v3, sections 10.8 and 10.9 tests 25, 28 and 29): a question
asked from Updates is a turn of the person's own chat bot, in the same chat as their menu tab, handed the recent updates
that person may read. The server leaves out every update they may not see, and any that links a task, chat or bot they
may not open, so the bot can never quote or link one; each comes ranked by the default order and with its link."""

import json

from backend import updates
from backend.tests.test_api import api, assign, get, post, ready, runner  # noqa: F401
from backend.tests.test_ceo_bot_chat import ceo


def ask(api, text, token, place="updates"):
    return post(api, "assistant/messages", {"text": text, **({"place": place} if place else {})}, token=token)


def claim(api, r, bot, text, token, place="updates"):
    sent = ask(api, text, token, place)
    assert sent["fast"] is False, "a question from Updates is always a turn"
    attempt = post(api, "jobs/claim", {"bot": bot}, token=r["token"])["attempt"]
    post(api, f"attempts/{attempt['id']}/started", {"thread_id": "t-" + attempt["id"]}, token=r["token"])
    post(api, f"attempts/{attempt['id']}/complete", {"outcome": "completed", "text": "Done", "last_seq": 0},
         token=r["token"])
    return sent, attempt


def test_a_question_from_updates_is_handed_only_the_updates_the_person_may_read_and_open(api, monkeypatch):
    from backend.tests.test_api import restrict
    from backend.tests.test_bot_contact import bot
    monkeypatch.setattr(updates, "today", lambda at=None: "2026-09-29")
    for slug, name in (("sales", "Sales"), ("fixer", "Fixer")):
        bot(api, slug, name)
    hidden = post(api, "tasks", {"title": "Quietly let the agency go", "body": "See notes", "owner": "fixer", "private": True})
    with api.app.state.store.transaction() as c:
        restrict(c, "finance", people=["ana"])
        updates.post(c, "sales", "- Closed the Acme renewal", day="2026-09-29")
        updates.post(c, "finance", "- Runway is nine months", day="2026-09-29")
        updates.post(c, "fixer", f"- Sorted out [the agency](#/task/{hidden['id']})", day="2026-09-29")
        updates.post(c, "fixer", f"- Went through {hidden['id']} with the team", day="2026-09-28")
    r = runner(api)
    assign(api, r, "coo")
    ready(api, r, ["coo"])
    # The menu tab's own question is handed no updates; it reads them only as the person, like any reader.
    menu, plain = claim(api, r, "coo", "What's the top update today?", "cara-test", place=None)
    assert plain["updates"] is None
    sent, attempt = claim(api, r, "coo", "What's the top update today?", "cara-test")
    assert sent["message"]["conversation_id"] == menu["message"]["conversation_id"], "the same chat as her menu tab"
    handed = attempt["updates"]
    assert handed["today"] == "2026-09-29"
    assert [u["text"] for u in handed["updates"]] == ["- Closed the Acme renewal"]
    assert handed["updates"][0]["link"] == f"#/updates?kind=daily&day=2026-09-29&update={handed['updates'][0]['id']}"
    text = json.dumps(attempt)
    for secret in ("Runway", "agency", hidden["id"], "Finance"):
        assert secret not in text, secret + " reached the bot"
    # The owner reads Finance's too, in her CEO Bot chat; not the ones that link a private task her CEO Bot is no party to.
    ceo(api)
    assign(api, r, "goal-manager")
    ready(api, r, ["goal-manager"])
    _, owner = claim(api, r, "goal-manager", "What's the top update today?", "ana-test")
    assert sorted(u["text"] for u in owner["updates"]["updates"]) == ["- Closed the Acme renewal", "- Runway is nine months"]


def test_the_default_order_is_a_goal_then_waits_on_you_then_newest(api, monkeypatch):
    from backend.tests.test_bot_contact import bot, token
    monkeypatch.setattr(updates, "today", lambda at=None: "2026-09-29")
    for slug, name in (("boss", "Manager"), ("analyst", "Analyst"), ("writer", "Writer"), ("crier", "Crier")):
        bot(api, slug, name)
    post(api, "goals", {"owner": "boss", "title": "Launch in October"})
    post(api, "tasks", {"title": "Approve the market sizing", "body": "See notes", "owner": "human:cara"}, token=token(api, "analyst"))
    with api.app.state.store.transaction() as c:
        updates.post(c, "boss", "- Planned the launch", day="2026-09-28")
        updates.post(c, "analyst", "- Sized the market", day="2026-09-29")
        updates.post(c, "crier", "- Cara, the press list needs a look", day="2026-09-29")
        updates.post(c, "writer", "- Wrote the launch post", day="2026-09-29")
    r = runner(api)
    assign(api, r, "coo")
    ready(api, r, ["coo"])
    _, attempt = claim(api, r, "coo", "hi", "cara-test")
    ranked = [(u["author"], u["rank"], u["goals"], u["waits_on_you"]) for u in attempt["updates"]["updates"]]
    assert ranked == [("Manager", 1, ["Launch in October"], False), ("Crier", 2, [], True),
                      ("Analyst", 3, [], True), ("Writer", 4, [], False)]
    assert attempt["updates"]["updates"][0]["day"] == "2026-09-28", "the latest earlier day is there to offer"
