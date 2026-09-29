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


def test_a_busy_bot_waits_its_turn_and_a_run_that_ends_without_a_post_is_missed(api):
    store = api.app.state.store
    r, msg, attempt = setup_attempt(api, "ops")          # ops has a run going
    with store.transaction() as c:
        c.execute("UPDATE update_queue SET state='done'")
        updates.build_queue(c, "2026-09-29", "daily")
        c.execute("UPDATE update_queue SET rank=-1 WHERE bot='ops'")          # ops would be first
        asked = updates.dispatch(c, MORNING)
    assert asked != "ops", "a bot in the middle of a run is passed over"
    with store.transaction() as c:
        row = c.execute("SELECT * FROM update_queue WHERE state='sent'").fetchone()
        c.execute("UPDATE jobs SET state='completed' WHERE message_id=?", (row["message_id"],))
        updates.dispatch(c, MORNING)
        retry = c.execute("SELECT state, tries, rank FROM update_queue WHERE id=?", (row["id"],)).fetchone()
        last = c.execute("SELECT max(rank) FROM update_queue WHERE day='2026-09-29'").fetchone()[0]
    assert retry["state"] in ("queued", "sent") and retry["tries"] == 1 and retry["rank"] == last, \
        "a run that ends without a post is asked once more, at the end of the queue"
    with store.transaction() as c:
        # Everyone else posts; the second request goes out and ends without a post too.
        for other in c.execute("SELECT * FROM update_queue WHERE day='2026-09-29' AND id!=?", (row["id"],)).fetchall():
            c.execute("UPDATE update_queue SET state='posted' WHERE id=?", (other["id"],))
        c.execute("UPDATE jobs SET state='completed' WHERE bot='ops'")
        updates.dispatch(c, MORNING)
        again = c.execute("SELECT * FROM update_queue WHERE id=?", (row["id"],)).fetchone()
        assert again["state"] == "sent"
        c.execute("UPDATE jobs SET state='completed' WHERE message_id=?", (again["message_id"],))
        updates.dispatch(c, MORNING)
        missed = c.execute("SELECT state, reason FROM update_queue WHERE id=?", (row["id"],)).fetchone()
    assert missed["state"] == "missed" and "without posting" in missed["reason"]
    feed = get(api, "updates")
    assert any(m["bot"] == row["bot"] for m in feed["missed"]), "a silent bot shows in the feed"


def test_friday_asks_for_the_week_and_a_bot_can_be_turned_off(api):
    post(api, "bots/finance/updates", {"weekly": False})
    assert get(api, "bots/finance/updates") == {"bot": "finance", "daily": True, "weekly": False}
    with api.app.state.store.transaction() as c:
        updates.dispatch(c, FRIDAY)
        kinds = {r["kind"] for r in c.execute("SELECT kind FROM update_queue WHERE day='2026-10-02'")}
        bots = {r["bot"] for r in c.execute("SELECT bot FROM update_queue WHERE day='2026-10-02'")}
        body = c.execute("SELECT m.body FROM update_queue q JOIN messages m ON m.id=q.message_id").fetchone()[0]
    assert kinds == {"weekly"} and "finance" not in bots
    assert "week in review" in body and "next week" in body and "one to five bullets" in body
    post(api, "bots/finance/updates", {"weekly": True}, token="cara-test", expected=403)


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


def test_a_reply_shows_on_the_update_and_goes_to_the_bots_chat(api):
    store = api.app.state.store
    with store.transaction() as c:
        uid = updates.post(c, "ops", "- Checklist page drafted\n- Publishing it next")["id"]
    out = post(api, f"updates/{uid}/reply", {"text": "Focus on the checklist page first"})
    message = out["message"]
    assert message["to_actor"] == "bot:ops" and "Focus on the checklist page first" in message["body"]
    chat = get(api, "conversations?chat_with=ops")["conversations"]
    assert chat[0]["id"] == message["conversation_id"], "it is in my chat with the bot"
    with store.transaction() as c:
        assert c.execute("SELECT 1 FROM jobs WHERE message_id=?", (message["id"],)).fetchone(), "the bot's session gets it"
        H.say(c, "bot:ops", "human:ana", "On it: checklist first.", conversation_id=message["conversation_id"],
              in_reply_to=message["id"])
    shown = get(api, f"updates/{uid}")
    assert [m["body"] for m in shown["thread"]][-1] == "On it: checklist first.", "its answer shows under the update"
    assert shown["update"]["read"] is True, "replying reads it"
    assert get(api, "updates")["updates"][0]["replies"] == 1
    post(api, "chat/ops", {"text": "hello", "refs": {"update": "nope"}}, expected=422)


def test_a_bot_that_never_starts_does_not_hold_the_queue_and_a_late_post_still_counts(api):
    store = api.app.state.store
    with store.transaction() as c:
        first = updates.dispatch(c, MORNING)
        c.execute("UPDATE update_queue SET sent_at=? WHERE bot=?", (H.shift(H.now(), minutes=-25), first))
        second = updates.dispatch(c, MORNING)
        state = c.execute("SELECT state, reason FROM update_queue WHERE bot=? AND day='2026-09-29'", (first,)).fetchone()
    assert second and second != first and state["state"] == "missed" and "20 minutes" in state["reason"]
    assert any(m["bot"] == first for m in get(api, "updates")["missed"])
    with store.transaction() as c:
        updates.post(c, first, "- Late, but here", day="2026-09-29")
    assert not any(m["bot"] == first for m in get(api, "updates")["missed"]), "a late post clears it"


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


def test_rejected_updates_are_deleted_and_their_bots_asked_again(api):
    """Ana, 2026-09-27: "All of these are rejected should be deleted and redone"."""
    store = api.app.state.store
    day = updates.today()
    with store.transaction() as c:
        updates.build_queue(c, day, updates.kind_for(day))
        c.execute("UPDATE update_queue SET state='posted'")
        now = H.now()
        for uid, bot, body in (("u-old", "ops", "**Done**\n- Drafted the checklist"), ("u-ok", "finance", "- Checked the Brex balance")):
            c.execute("INSERT INTO updates(id,bot,kind,day,headline,body,created,updated) VALUES(?,?,?,?,?,?,?,?)",
                      (uid, bot, updates.kind_for(day), day, "Headline", body, now, now))
        c.execute("UPDATE update_queue SET state='missed', reason='its update was too long, so it counts as not given' "
                  "WHERE bot='cpo'")
        assert updates.purge_rejected(c) == ["ops", "cpo"], "the earlier not-given ones are redone too"
    with store.read() as c:
        assert not updates.one(c, "u-old") and updates.one(c, "u-ok")
        row = c.execute("SELECT state, tries, reason FROM update_queue WHERE bot='ops' AND day=?", (day,)).fetchone()
    assert row["state"] == "queued" and row["tries"] == 0 and "asked again" in row["reason"]
    assert [u["id"] for u in get(api, "updates")["updates"]] == ["u-ok"]
    store.initialize(seed_market=False)       # the hub does this when it starts


def test_the_queue_skips_a_switched_off_bot(api):
    """A bot whose update switches are off is not queued, and is skipped if switched off later."""
    store = api.app.state.store
    with store.transaction() as c:
        updates.set_settings(c, "product-design", daily=False, weekly=False)
        updates.build_queue(c, "2026-09-29", "daily")
        assert not c.execute("SELECT 1 FROM update_queue WHERE bot='product-design'").fetchone(), "off: not queued"
        updates.set_settings(c, "ops", daily=False)          # switched off after the queue was built
        c.execute("UPDATE update_queue SET rank=-1 WHERE bot='ops'")
        assert updates.dispatch(c, MORNING) != "ops"
        assert c.execute("SELECT state FROM update_queue WHERE bot='ops'").fetchone()[0] == "skipped"


def test_my_bots_counts_only_the_bots_i_operate(api):
    """The badge said 14 while every update in the My bots feed was read; the rest
    were Ben's bots. With mine=true the count and the feed are the operator's bots only."""
    store = api.app.state.store
    with store.transaction() as c:
        updates.post(c, "ops", "- Drafted the checklist")            # Ana operates ops
        updates.post(c, "cpo", "- Shipped the stats page")          # Ben operates cpo
    assert get(api, "updates/unread") == {"unread": 2}
    assert get(api, "updates/unread?mine=true") == {"unread": 1}
    assert [u["bot"] for u in get(api, "updates?mine=true")["updates"]] == ["ops"]
    assert get(api, "updates?mine=true")["unread"] == 1
    assert get(api, "updates/unread?mine=true", token="ben-test") == {"unread": 1}
