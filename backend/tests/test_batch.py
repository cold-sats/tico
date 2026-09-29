"""A batch: what needs a person, frozen and walked; responses collected, applied together on commit;
the assistant's per-item report opening the next batch. backend/batch.py."""

import json

from backend import batch
from backend.store import H, Problem
from backend.tests.test_api import api, get, post, setup_attempt


def ask_ana(api, bot, text, title="Pick the outbound tool", token=None):
    """A bot that owns a task Ana filed asks him its one question."""
    task = post(api, "tasks", {"title": title, "body": "Decide", "owner": bot})
    token = token or setup_attempt(api, bot)[2]["token"]
    return post(api, f"tasks/{task['id']}/ask", {"text": text}, token=token)


def approval_for_ana(api, bot="finance", kind="spend", payload=None, task=None, token=None):
    attempt = {"token": token} if token else setup_attempt(api, bot)[2]
    body = {"kind": kind, "payload": payload or {"amount": 1200, "account": "ads", "what": "LinkedIn ads"}}
    if task:
        body["task_id"] = task
    return post(api, "approvals", body, token=attempt["token"])


def test_a_batch_holds_only_what_bots_wait_on(api):
    """His own tasks and other people's requests are on the Tasks page, not in
    "who needs me", and nothing is routed to an assistant in between."""
    own = post(api, "tasks", {"title": "Sign the lease", "body": "Ready", "owner": "human:ana"})
    ben = post(api, "tasks", {"title": "Review the Q4 budget", "body": "Numbers", "owner": "human:ana"},
                  token="ben-test")
    _, _, finance = setup_attempt(api, "finance")
    grant = post(api, "tasks", {"title": "Grant the replica", "body": "Read-only", "owner": "human:ana"},
                 token=finance["token"])
    needs = {i["id"] for i in get(api, "needs-you")["items"]}
    assert {own["id"], ben["id"], grant["id"]} <= needs, "the Tasks page still has all three"
    b = post(api, "batch", {})
    assert walk(api, b) == ["task:" + grant["id"]]
    assert [g["who"] for g in b["lineup"]] == ["bot:finance"]
    post(api, f"batch/{b['id']}/abandon", {})
    for scope in ("me", "ben", "nobody-at-all"):
        post(api, "batch", {"bot": scope}, expected=404)


def test_batch_requires_result_for_bot_requested_human_task(api):
    _, _, finance = setup_attempt(api, "finance")
    decision = post(api, "tasks", {"title": "Decide whether to release the draft",
        "body": "Keep the hold or release?", "owner": "human:ana"}, token=finance["token"])
    batch = post(api, "batch", {})
    assert batch["item"]["key"] == "task:" + decision["id"]
    post(api, f"batch/{batch['id']}/respond", {"kind": "decide", "decision": "done"}, expected=422)
    post(api, f"batch/{batch['id']}/respond", {"kind": "decide", "decision": "close"}, expected=422)
    post(api, f"batch/{batch['id']}/respond", {"kind": "decide", "decision": "done",
        "text": "Keep the hold; no release is approved."})
    post(api, f"batch/{batch['id']}/commit", {})
    task = get(api, f"tasks/{decision['id']}")["task"]
    assert task["status"] == "done" and task["note"] == "Keep the hold; no release is approved."


def test_responses_are_recorded_not_applied_and_commit_applies_them_with_the_persons_identity(api):
    _, _, finance = setup_attempt(api, "finance")
    approval = approval_for_ana(api, token=finance["token"])
    ask = ask_ana(api, "finance", "Close or Apollo?", token=finance["token"])
    chore = post(api, "tasks", {"title": "Sign the lease", "body": "Ready", "owner": "human:ana"},
                 token=finance["token"])
    junk = post(api, "tasks", {"title": "Drop the old draft to Yair", "body": "Obsolete", "owner": "human:ana"},
                token=finance["token"])
    b = post(api, "batch", {})
    bid = b["id"]
    assert b["item"]["key"] == "approval:" + approval["id"]

    # Responding records; nothing changes yet.
    r = post(api, f"batch/{bid}/respond", {"kind": "decide", "decision": "approve", "text": "Go ahead", "heard": "yeah go ahead"})
    assert r["recorded"] and r["n"] == 1 and r["response"]["heard"] == "yeah go ahead"
    assert post(api, "batch", {})["item"]["response"] == [r["response"]], "the current item shows its responses"
    assert get(api, f"approvals/{approval['id']}")["decision"] is None
    post(api, f"batch/{bid}/respond", {"kind": "decide", "decision": "done"}, expected=422)      # an approval is approved or declined
    post(api, f"batch/{bid}/respond", {"kind": "needs_info"}, expected=422)                      # a question needs its text
    nxt = post(api, f"batch/{bid}/next", {})
    assert nxt["item"]["kind"] == "question" and nxt["item"]["question"] == "Close or Apollo?"
    post(api, f"batch/{bid}/respond", {"kind": "decide", "decision": "approve"}, expected=422)   # a question is not an approval
    post(api, f"batch/{bid}/respond", {"kind": "decide", "decision": "answer", "text": "Close. Keep the trial seats."})
    # A response can name another item by position, and the last response to an item wins.
    post(api, f"batch/{bid}/respond", {"kind": "skip", "item": 1})
    post(api, f"batch/{bid}/respond", {"kind": "decide", "decision": "approve", "item": 1, "text": "Go ahead"})
    nxt = post(api, f"batch/{bid}/next", {})
    assert nxt["item"]["key"] == "task:" + chore["id"]
    post(api, f"batch/{bid}/respond", {"kind": "decide", "decision": "done", "text": "Signed this morning"})
    nxt = post(api, f"batch/{bid}/next", {})
    assert nxt["item"]["key"] == "task:" + junk["id"]
    post(api, f"batch/{bid}/respond", {"kind": "decide", "decision": "close", "text": "Not needed any more."})
    post(api, f"batch/{bid}/respond", {"kind": "rule", "text": "Always archive postcard complaints.", "item": 4})
    end = post(api, f"batch/{bid}/next", {})
    assert end["end"] and end["summary"]["approving"] == ["Approve this spend"]
    assert end["summary"]["counts"] == {"approve": 1, "answer": 1, "done": 1, "close": 1, "rule": 1}
    assert end["summary"]["responses"] == 5 and end["summary"]["items"] == 4, "a rule beside a decision is two responses"
    assert get(api, f"tasks/{chore['id']}")["task"]["status"] == "open", "still nothing applied"

    done = post(api, f"batch/{bid}/commit", {})
    assert done["committed"] and done["errors"] == []
    assert done["sent"] == {"finance": 1} and done["recorded"] == {"finance": 4}
    assert get(api, f"approvals/{approval['id']}")["decision"] == "approved"
    assert get(api, f"tasks/{chore['id']}")["task"]["status"] == "done"
    assert get(api, f"tasks/{junk['id']}")["task"]["status"] == "closed"
    with api.app.state.store.read() as c:
        reply = c.execute("SELECT body,from_actor FROM messages WHERE in_reply_to=?", (ask["id"],)).fetchone()
        coo = c.execute("SELECT count(*) FROM messages WHERE to_actor='bot:coo' OR from_actor='bot:coo'").fetchone()[0]
        event = c.execute("SELECT detail_json FROM events WHERE action='batch.committed'").fetchone()
    assert reply["body"] == "Close. Keep the trial seats." and reply["from_actor"] == "human:ana"
    assert coo == 0, "nothing is written to the assistant's room"
    assert "Rule for finance: Always archive postcard complaints." in json.loads(event["detail_json"])["applied"]
    assert get(api, "batch")["batch"] is None
    post(api, f"batch/{bid}/commit", {}, expected=409)
    post(api, f"batch/{bid}/respond", {"kind": "skip"}, expected=409)


def test_a_batch_belongs_to_a_person_and_a_failed_item_does_not_stop_the_commit(api):
    _, _, attempt = setup_attempt(api, "finance")
    approval = approval_for_ana(api, token=attempt["token"])
    b = post(api, "batch", {})
    post(api, f"batch/{b['id']}/next", {}, token="ben-test", expected=404)
    post(api, "batch", {}, token=attempt["token"], expected=403)
    post(api, f"batch/{b['id']}/respond", {"kind": "decide", "decision": "approve"})
    # Someone decides the approval by hand before the commit: that item fails, the batch still commits.
    post(api, f"approvals/{approval['id']}", {"decision": "declined"})
    done = post(api, f"batch/{b['id']}/commit", {})
    assert done["committed"] and len(done["errors"]) == 1 and "already declined" in done["errors"][0]
    assert get(api, "batch")["batch"] is None


def walk(api, b):
    """Every item key of a batch, in order, leaving the cursor at the end."""
    keys = [b["item"]["key"]] if b.get("item") else []
    while not b.get("end"):
        b = post(api, f"batch/{b['id']}/next", {})
        if b.get("item"):
            keys.append(b["item"]["key"])
    return keys


def test_who_needs_me_brings_the_bots_one_at_a_time_and_each_hears_about_its_own_items(api):
    """Ana, 2026-09-23: "who needs me" gives one bot's items, most important bot first; what he
    says about them goes straight to that bot, not to the assistant; then the next bot."""
    _, _, finance = setup_attempt(api, "finance")
    approval = approval_for_ana(api, token=finance["token"])
    grant = post(api, "tasks", {"title": "Grant the replica", "body": "Read-only", "owner": "human:ana"},
                 token=finance["token"])
    _, _, inbox = setup_attempt(api, "inbox")
    mails = [post(api, "tasks", {"title": f"Decide mail {n}", "body": "Keep or close", "owner": "human:ana"},
                  token=inbox["token"]) for n in (1, 2)]
    b = post(api, "batch", {"bot": "next"})
    assert b["scope"] == "bot:finance", "an approval makes finance the one that most needs Ana"
    assert [g["who"] for g in b["lineup"]][0] == "bot:finance"
    assert {g["who"]: g["items"] for g in b["lineup"]} == {"bot:finance": 2, "bot:inbox": 2}
    assert b["lineup"][0]["top"] == "Approve this spend"
    keys = walk(api, b)
    assert keys == ["approval:" + approval["id"], "task:" + grant["id"]], "only finance's items"

    post(api, f"batch/{b['id']}/respond", {"kind": "decide", "decision": "approve", "item": 1, "text": "Go"})
    post(api, f"batch/{b['id']}/respond", {"kind": "needs_info", "item": 2, "text": "Which database?"})
    post(api, f"batch/{b['id']}/respond", {"kind": "rule", "item": 2, "text": "Replicas are always read-only."})
    done = post(api, f"batch/{b['id']}/commit", {})
    assert done["errors"] == [] and done["scope"] == "bot:finance"
    assert done["sent"] == {"finance": 2} and done["recorded"] == {"finance": 1}
    assert done["up_next"]["who"] == "bot:inbox", "finance is done; the next bot is offered"
    assert get(api, f"approvals/{approval['id']}")["decision"] == "approved"

    with api.app.state.store.read() as c:
        sent = c.execute("SELECT * FROM messages WHERE json_extract(refs_json,'$.live.kind')='batch'").fetchall()
        jobs = c.execute("SELECT count(*) FROM jobs WHERE bot='finance' AND message_id=?", (sent[0]["id"],)).fetchone()[0]
        coo = c.execute("SELECT count(*) FROM jobs WHERE bot='coo'").fetchone()[0]
    assert len(sent) == 1 and sent[0]["to_actor"] == "bot:finance" and jobs == 1, "one message, one finance turn"
    assert coo == 0, "the assistant is not the middleman"
    body = sent[0]["body"]
    assert " went through what you are waiting on them for." in body.split("\n")[0]
    assert "Already done (applied in the hub; nothing to redo):\n- Approved: Approve this spend: \"Go\"" in body
    assert body.index("Already done") < body.index("For you to act on.")
    assert "[item 2] Grant the replica" in body and "human:ana asks: Which database?" in body
    assert "human:ana sets a standing rule: Replicas are always read-only." in body

    # The next "who needs me" is the inbox bot: finance is waiting on its own reply, nothing new.
    b2 = post(api, "batch", {"bot": "next"})
    assert b2["scope"] == "bot:inbox"
    assert set(walk(api, b2)) == {"task:" + m["id"] for m in mails}
    finance_line = next(g for g in b2["lineup"] if g["who"] == "bot:finance")
    assert finance_line == {**finance_line, "items": 1, "awaiting": 1}
    post(api, f"batch/{b2['id']}/abandon", {})

    # Finance answers; its answer comes back on its item the next time finance comes up, once.
    with api.app.state.store.transaction() as c:
        H.answer(c, "bot:finance", sent[0]["id"], "Noted the rule.\n[item 2] The analytics replica, prod-ro-2.")
    b3 = post(api, "batch", {"bot": "next"})
    assert b3["scope"] == "bot:finance", "an answer back is new again"
    assert b3["item"]["kind"] == "report" and b3["item"]["from"] == "bot:finance"
    assert b3["item"]["body"] == "Noted the rule."
    answered = post(api, f"batch/{b3['id']}/next", {})["item"]
    assert answered["key"] == "task:" + grant["id"] and answered["answer"] == "The analytics replica, prod-ro-2."
    post(api, f"batch/{b3['id']}/abandon", {})
    b4 = post(api, "batch", {"bot": "finance"})
    assert b4["total"] == 1 and "answer" not in b4["item"], "a reply is shown once"
    post(api, f"batch/{b4['id']}/abandon", {})


def test_decisions_alone_leave_a_quiet_record_in_the_bots_chat_signed_with_the_assistant_that_ran_it(api):
    """The bot's own chat is the record of the batch, and says which of his
    assistants (Grok Bot, Meta Muse) went through it for him."""
    token = post(api, "me/tokens", {"label": "grok-bot"})["token"]
    _, _, finance = setup_attempt(api, "finance")
    approval = approval_for_ana(api, token=finance["token"])
    b = post(api, "batch", {"bot": "finance"}, token=token)
    post(api, f"batch/{b['id']}/respond", {"kind": "decide", "decision": "decline", "text": "Not this quarter."},
         token=token)
    done = post(api, f"batch/{b['id']}/commit", {}, token=token)
    assert done["sent"] == {} and done["recorded"] == {"finance": 1}
    assert get(api, f"approvals/{approval['id']}")["decision"] == "declined"
    with api.app.state.store.read() as c:
        msg = c.execute("SELECT * FROM messages WHERE json_extract(refs_json,'$.live.kind')='batch'").fetchone()
        jobs = c.execute("SELECT count(*) FROM jobs WHERE message_id=?", (msg["id"],)).fetchone()[0]
        chat = c.execute("SELECT kind FROM conversations WHERE id=?", (msg["conversation_id"],)).fetchone()
    assert msg["to_actor"] == "bot:finance" and jobs == 0, "a record is read in the room, not run"
    assert chat["kind"] == "chat", "in Ana's own chat with finance"
    assert msg["body"].split("\n")[0].endswith("(via grok-bot) went through what you are waiting on them for.")
    assert '- Declined: Approve this spend: "Not this quarter."' in msg["body"]
    assert msg["body"].endswith("Nothing for you to act on; no reply needed.")
    assert json.loads(msg["refs_json"])["live"]["via"] == "grok-bot"
    # Quiet is the batch's alone: an ordinary message cannot use it to skip a bot's turn.
    post(api, "messages", {"to": "finance", "text": "hi", "refs": {"quiet": True}}, expected=422)
