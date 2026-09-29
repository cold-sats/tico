"""Updates: every bot reports in once a day, one bot asked at a time; Friday is
the week in review; read state is per person; a reply is both a comment on the update and a
message in the bot's chat."""

from datetime import datetime, timezone

from backend import updates
from backend.store import H
from backend.tests.test_api import api, get, headers, post, setup_attempt  # noqa: F401

MORNING = datetime(2026, 9, 29, 13, 0, tzinfo=timezone.utc)      # Tuesday 06:00 Pacific
FRIDAY = datetime(2026, 10, 2, 13, 0, tzinfo=timezone.utc)
NIGHT = datetime(2026, 9, 29, 10, 0, tzinfo=timezone.utc)        # 03:00 Pacific, before the queue


def out(c):
    return [dict(r) for r in c.execute("SELECT bot, state, kind FROM update_queue WHERE state='sent'")]


def test_the_queue_asks_one_bot_at_a_time_and_moves_on_when_it_posts(api):
    store = api.app.state.store
    with store.transaction() as c:
        assert updates.dispatch(c, NIGHT) is None and not c.execute("SELECT 1 FROM update_queue").fetchone()
        first = updates.dispatch(c, MORNING)
        queued = c.execute("SELECT count(*) FROM update_queue WHERE day='2026-09-29'").fetchone()[0]
        active = c.execute("SELECT count(*) FROM bots WHERE state='active'").fetchone()[0]
    assert first and queued == active, "every active bot is queued, and the first one asked"
    with store.transaction() as c:
        assert updates.dispatch(c, MORNING) is None, "one at a time: nothing more while it is out"
        request = c.execute("SELECT m.body, m.refs_json FROM update_queue q JOIN messages m ON m.id=q.message_id "
                            "WHERE q.state='sent'").fetchone()
        assert "hub_update_post" in request["body"] and "Finished since your last update" in request["body"]
        assert c.execute("SELECT 1 FROM jobs WHERE bot=?", (first,)).fetchone(), "the request wakes the bot"
        updates.post(c, first, "- Shipped the pricing page", day="2026-09-29")
        second = updates.dispatch(c, MORNING)
        assert second and second != first
        assert c.execute("SELECT state FROM update_queue WHERE bot=? AND day='2026-09-29'", (first,)).fetchone()[0] == "posted"


def test_a_bot_posts_once_a_day_and_each_person_has_their_own_read_state(api):
    r, msg, attempt = setup_attempt(api, "ops")
    bot = {"Authorization": "Bearer " + attempt["token"]}
    first = api.post("/api/v2/updates", json={"body": "- Drafted the checklist"},
                     headers={**bot, "Idempotency-Key": "u1"})
    assert first.status_code == 200, first.text
    again = api.post("/api/v2/updates", json={"body": "- Drafted and sent the checklist"},
                     headers={**bot, "Idempotency-Key": "u2"}).json()["update"]
    assert again["id"] == first.json()["update"]["id"], "posting again replaces the day's update"
    post(api, "updates", {"body": "- Me too"}, expected=403)           # people read, bots post
    feed = get(api, "updates")
    assert [u["headline"] for u in feed["updates"]] == ["Drafted and sent the checklist"]
    assert feed["updates"][0]["read"] is False and feed["unread"] == 1
    post(api, "updates/read", {"ids": [again["id"]]})
    assert get(api, "updates")["unread"] == 0 and get(api, "updates/unread") == {"unread": 0}
    assert get(api, "updates", token="ben-test")["unread"] == 1, "Ana reading it is not Ben reading it"
    post(api, "updates/read", {"ids": [again["id"]], "read": False})
    assert get(api, "updates?unread=true")["updates"][0]["id"] == again["id"]
    post(api, "updates/read", {"all": True})
    assert get(api, "updates")["unread"] == 0


def test_an_update_is_one_to_five_plain_bullets_or_it_is_refused(api):
    """Ana, 2026-09-27: "No title, no sections ... I just want my 1-5 bullets", "Never send me task
    ids", shorter again; refused with how to write it, never a quarantine."""
    r, msg, attempt = setup_attempt(api, "ops")
    bot = {"Authorization": "Bearer " + attempt["token"]}
    send = lambda body, n: api.post("/api/v2/updates", json={"body": body}, headers={**bot, "Idempotency-Key": f"k-{n}"})
    bad = {
        "sections": "**Done**\n- Drafted the checklist\n**Next**\n- Publish it",
        "title": "Big day\n- Drafted the checklist",
        "label": "- **Done**: drafted the checklist",
        "task id": "- Closed task 3233ce3a for Legal",
        "uuid": "- Finished bb68f3ce-12c1-45f3-aac3-fd159e2be06e",
        "six bullets": "\n".join(f"- Shipped part {n}" for n in range(6)),
        "long bullet": "- " + " ".join(["word"] * 30),
        "too many words": "\n".join("- " + " ".join(["word"] * 20) for _ in range(5)),
    }
    for n, (name, body) in enumerate(bad.items()):
        refused = send(body, n)
        assert refused.status_code == 422, (name, refused.text)
        assert "one to five bullets in plain English" in refused.json()["error"]["detail"], name
    assert "task id" in send(bad["task id"], 90).json()["error"]["detail"]
    with api.app.state.store.read() as c:
        assert H.bot(c, "ops")["state"] == "active", "a writing correction never quarantines"
        assert not c.execute("SELECT 1 FROM updates").fetchone()
    good = "- Published the checklist page and linked it from six posts\n- Pitching it to three host newsletters next\n" \
           "- Merged PR #618; [the addendum](https://hub.acme.example/#/task/bb68f3ce-12c1-45f3-aac3-fd159e2be06e) is signed"
    ok = send(good, 99)
    assert ok.status_code == 200, ok.text
    assert ok.json()["update"]["headline"] == "Published the checklist page and linked it from six posts"
    assert updates.lint("\n".join("- " + " ".join(["word"] * 30) for _ in range(5)), "weekly") is None, "the week may run longer"

