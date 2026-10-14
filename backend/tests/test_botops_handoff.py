"""A person asks another bot for something only BotOps can do: the bot hands it on with the person's own message, and
BotOps acts as them; a hand-off that lends nothing reaches the person as a Confirm card, not a refusal."""
from fastapi import Request

from backend.tests.test_api import api, assign, claim, get, headers, post, ready  # noqa: F401  (fixture)
from backend.tests.test_member_bots import botops, finish  # noqa: F401  (fixture)
from backend.store import H


def _identity_route(api):
    def identity(request: Request):
        who = request.state.identity
        return {"actor": who.actor, "role": who.role}
    api.app.add_api_route("/api/v2/qa-handoff-identity", identity, methods=["GET"])
    api.app.router.routes.insert(0, api.app.router.routes.pop())


def _hand_off(api, machine, cite):
    """Ana asks Ops in her chat with it; Ops files the work for BotOps, citing her message or not; BotOps picks it up."""
    post(api, "chat/ops", {"text": "Give yourself read access to the acme site repository"}, token="ana-test")
    ops = claim(api, machine, "ops")
    task = post(api, "tasks", {"owner": "botops", "title": "Give Ops read access to the acme site repository",
                               "body": "Ana asked for it in her chat with Ops.", **({"request_id": cite} if cite else {})},
                token=ops["token"])
    finish(api, machine, ops)
    return task, claim(api, machine, "botops")


def test_a_bot_hands_botops_the_persons_own_request_and_botops_acts_as_them(api, botops):
    assign(api, botops, "ops")
    ready(api, botops, ["botops", "ops"])
    _identity_route(api)
    task, attempt = _hand_off(api, botops, "turn")
    with api.app.state.store.read() as c:
        carried = c.execute("SELECT detail_json FROM events WHERE action='botops.request_carried' AND target=?",
                            (task["id"],)).fetchone()
        assert H._json(carried["detail_json"], {})["lends"] is True
        quoted = c.execute("SELECT body FROM messages WHERE to_actor='bot:botops' AND body LIKE '%in their words%'"
                           ).fetchone()
        assert "> Give yourself read access" in quoted["body"]
    assert get(api, "qa-handoff-identity", attempt["token"]) == {"actor": "human:ana", "role": "owner"}

    # Once the message is more than a week old it lends nothing: BotOps has only Ops' rights again.
    with api.app.state.store.transaction() as c:
        c.execute("UPDATE messages SET created=? WHERE id=?",
                  (H.shift(H.now(), days=-8), H._json(carried["detail_json"], {})["message_id"]))
    assert get(api, "qa-handoff-identity", attempt["token"]) == {"actor": "bot:ops", "role": "bot"}


def test_a_hand_off_that_lends_nothing_puts_a_confirm_card_to_the_person(api, botops):
    assign(api, botops, "ops")
    ready(api, botops, ["botops", "ops"])
    task, attempt = _hand_off(api, botops, None)        # Ops did not cite her message
    tried = api.put("/api/v2/bots/ops/repositories", json={"mode": "all", "all_access": "read"},
                    headers=headers(attempt["token"]))
    assert tried.status_code == 200, tried.text
    card = tried.json()
    assert card["needs_confirm"] is True and card["action"]["status"] == "pending"
    with api.app.state.store.read() as c:
        row = c.execute("SELECT owner,method,path,proposer FROM assistant_actions WHERE id=?",
                        (card["action"]["id"],)).fetchone()
        assert dict(row) == {"owner": "human:ana", "method": "PUT", "path": "/api/v2/bots/ops/repositories",
                             "proposer": "botops"}
        # Nothing changed and no free-text task was filed for her: the card is in her chat with BotOps.
        assert not c.execute("SELECT 1 FROM tasks WHERE owner='human:ana' AND requester='bot:botops'").fetchone()
        said = H.message(c, card["message_id"])
        assert said["to_actor"] == "human:ana" and said["from_actor"] == "bot:botops"
