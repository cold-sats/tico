"""Getting started: every tick is computed from live state, and each person keeps their own choices."""

import json

from backend.store import H, encode

from backend.tests.test_onboarding import as_person, environment, machine, signed_in  # noqa: F401


def items(api, headers=None):
    body = api.get("/api/v2/getting-started", headers=headers or signed_in()).json()
    return body, {row["id"]: row for row in body["items"]}


def body_of(api):
    return api.get("/api/v2/getting-started", headers=signed_in()).json()


def heartbeat(api, runner_id, *, seconds_ago=0, runtimes=None):
    """A runner's last word, as the heartbeat stores it."""
    with api.app.state.store.transaction() as c:
        c.execute("UPDATE runners SET last_seen=?, readiness_json=? WHERE id=?",
                  (H.shift(H.now(), seconds=-seconds_ago),
                   json.dumps({"schema_version": 1, "runtimes": runtimes or {}, "bots": {}}), runner_id))


def enrolled(api):
    machine(api)
    with api.app.state.store.read() as c:
        return c.execute("SELECT id FROM runners").fetchone()["id"]


def activate(api, *slugs):
    with api.app.state.store.transaction() as c:
        for slug in slugs:
            c.execute("UPDATE bots SET state='active' WHERE slug=?", (slug,))


def add_bot(api, slug, state="active"):
    with api.app.state.store.transaction() as c:
        H.sync_registry(c, {slug: {"name": slug, "status": state}}, None)


SIGNED_IN = {"codex": {"installed": True, "authenticated": "ready"}}


def test_a_fresh_company_has_only_the_first_step(environment):
    api = environment()
    body, rows = items(api)
    assert rows["signed_in"]["done"] is True
    assert not any(rows[k]["done"] for k in ("computer", "model", "github", "botops", "first_bot",
                                               "first_output", "first_update"))
    assert (body["done"], body["total"], body["complete"]) == (2, 9, False)     # signed in, and nothing waits for setup
    assert rows["first_bot"]["action"] == "create-bot"
    assert rows["computer"]["why"] and rows["computer"]["tab"] == "devices"


def test_botops_first_bot_task_and_update_follow_the_database(environment):
    api = environment()
    assert items(api)[1]["botops"]["done"] is False
    activate(api, "botops")
    assert items(api)[1]["botops"]["done"] is True

    # The assistant is one of the two bots the company starts with, so it is not a first bot.
    activate(api, "coo")
    assert items(api)[1]["first_bot"]["done"] is False
    add_bot(api, "support")
    assert items(api)[1]["first_bot"]["done"] is True
    assert items(api)[1]["first_output"]["done"] is False

    # A starter that is parked is the next thing to set up; the first approved output is the bot saying so.
    with api.app.state.store.transaction() as c:
        c.execute("INSERT INTO bot_config(bot,config_json,operator,onboarding_state) VALUES('support',?,'morgan','needs_onboarding')",
                  (encode({"name": "support", "template": "support", "setup_rank": 0}),))
    waiting = items(api)[1]["next_bot"]
    assert waiting["done"] is False and waiting["href"] == "#/bot/support" and "Start setup" in waiting["why"]
    assert items(api)[1]["first_output"]["done"] is False
    with api.app.state.store.transaction() as c:
        c.execute("UPDATE bot_config SET onboarding_state='onboarded' WHERE bot='support'")
    assert items(api)[1]["first_output"]["done"] is True and items(api)[1]["next_bot"]["done"] is True

    assert items(api)[1]["first_update"]["done"] is False
    with api.app.state.store.transaction() as c:
        c.execute("INSERT INTO updates(id,bot,kind,day,headline,body,created,updated) VALUES(?,?,?,?,?,?,?,?)",
                  ("u1", "support", "daily", "2026-01-05", "Cleared the queue", "- Cleared it", H.now(), H.now()))
    assert items(api)[1]["first_update"]["done"] is True


def test_each_person_sees_only_what_they_can_act_on(environment):
    api = environment()
    riley = as_person(api, "riley")                # a bot administrator
    quinn = as_person(api, "quinn")                # neither
    assert [r["id"] for r in items(api)[0]["items"]] == [
        "signed_in", "computer", "model", "github", "botops", "first_bot", "next_bot", "first_output", "first_update"]
    assert [r["id"] for r in items(api, riley)[0]["items"]] == [
        "signed_in", "botops", "first_bot", "next_bot", "first_output", "first_update"]
    assert [r["id"] for r in items(api, quinn)[0]["items"]] == ["signed_in", "first_output", "first_update"]


def test_a_bot_or_runner_cannot_read_it(environment):
    api = environment()
    assert api.get("/api/v2/getting-started").status_code in (401, 403)


def test_the_market_box_is_a_task_for_the_librarian(environment):
    api = environment()
    ask = {"text": "https://northwind.example\nOffice cleaning for property managers."}
    # The Librarian must be running: a task for a bot that is not would wait for nothing.
    refused = api.post("/api/v2/getting-started/market", json=ask, headers=signed_in())
    assert refused.status_code == 409
    add_bot(api, "librarian")
    made = api.post("/api/v2/getting-started/market", json=ask, headers=signed_in())
    assert made.status_code == 200, made.text
    assert made.json()["bot"] == "librarian"
    task = api.get("/api/v2/tasks", params={"owner": "librarian"}, headers=signed_in()).json()["tasks"][0]
    assert task["id"] == made.json()["task_id"] and task["title"] == "Set up the market map"
    assert "https://northwind.example" in task["body"] and "Office cleaning for property managers." in task["body"]
    assert "playbooks/market-setup.md" in task["body"]
    # Asking again while that task is open gets its own title, not a refusal.
    again = api.post("/api/v2/getting-started/market", json=ask, headers=signed_in())
    assert again.status_code == 200, again.text
    titles = {row["title"] for row in api.get("/api/v2/tasks", params={"owner": "librarian"}, headers=signed_in()).json()["tasks"]}
    assert titles == {"Set up the market map", "Set up the market map (2)"}
    # Only the owner asks, and the box may not be empty.
    assert api.post("/api/v2/getting-started/market", json=ask, headers=as_person(api, "quinn")).status_code == 403
    assert api.post("/api/v2/getting-started/market", json={"text": ""}, headers=signed_in()).status_code == 422
