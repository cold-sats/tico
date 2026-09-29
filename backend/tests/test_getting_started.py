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
                                               "bot_task", "first_update"))
    assert (body["done"], body["total"], body["complete"]) == (1, 8, False)
    assert rows["first_bot"]["action"] == "create-bot"
    assert rows["computer"]["why"] and rows["computer"]["tab"] == "devices"


def test_a_computer_counts_only_while_it_is_heard_from(environment):
    api = environment()
    runner = enrolled(api)
    heartbeat(api, runner, seconds_ago=30)
    assert items(api)[1]["computer"]["done"] is True
    heartbeat(api, runner, seconds_ago=300)
    assert items(api)[1]["computer"]["done"] is False
    with api.app.state.store.transaction() as c:
        c.execute("UPDATE runners SET last_seen=?, revoked_at=? WHERE id=?", (H.now(), H.now(), runner))
    assert items(api)[1]["computer"]["done"] is False


def test_a_model_must_be_installed_and_signed_in_for_the_default_runtime(environment):
    api = environment()                              # the company's default runtime is codex
    runner = enrolled(api)
    heartbeat(api, runner, runtimes={"codex": {"installed": True, "authenticated": "missing"}})
    assert items(api)[1]["model"]["done"] is False
    assert "codex login" in items(api)[1]["model"]["why"]
    heartbeat(api, runner, runtimes={"claude": {"installed": True, "authenticated": "ready"}})
    assert items(api)[1]["model"]["done"] is False          # signed in, but not the company's model
    heartbeat(api, runner, runtimes={"codex": {"installed": False, "authenticated": "ready"}})
    assert items(api)[1]["model"]["done"] is False
    heartbeat(api, runner, runtimes=SIGNED_IN)
    assert items(api)[1]["model"]["done"] is True
    heartbeat(api, runner, seconds_ago=600, runtimes=SIGNED_IN)
    assert items(api)[1]["model"]["done"] is False          # an offline computer signs nothing in


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
    assert items(api)[1]["bot_task"]["done"] is False

    with api.app.state.store.transaction() as c:
        task = H.task_create(c, "human:morgan", "Answer the queue", "Reply to today's tickets.",
                             "bot:support", allow_planned=True)
    assert items(api)[1]["bot_task"]["done"] is False
    with api.app.state.store.transaction() as c:
        c.execute("UPDATE tasks SET status='done' WHERE id=?", (task["id"],))
    assert items(api)[1]["bot_task"]["done"] is True

    assert items(api)[1]["first_update"]["done"] is False
    with api.app.state.store.transaction() as c:
        c.execute("INSERT INTO updates(id,bot,kind,day,headline,body,created,updated) VALUES(?,?,?,?,?,?,?,?)",
                  ("u1", "support", "daily", "2026-01-05", "Cleared the queue", "- Cleared it", H.now(), H.now()))
    assert items(api)[1]["first_update"]["done"] is True


def test_a_task_done_by_a_starting_bot_is_not_the_new_bots_first(environment):
    api = environment()
    activate(api, "botops", "coo")
    with api.app.state.store.transaction() as c:
        task = H.task_create(c, "human:morgan", "Say hello", "Say hello.", "bot:botops", allow_planned=True)
        c.execute("UPDATE tasks SET status='done' WHERE id=?", (task["id"],))
    assert items(api)[1]["bot_task"]["done"] is False


def test_github_is_done_only_once_the_app_is_installed_and_can_be_skipped(environment):
    api = environment()
    assert items(api)[1]["github"]["optional"] is True
    body = api.post("/api/v2/getting-started/state", json={"skip": "github"}, headers=signed_in()).json()
    assert body["skipped"] == ["github"]
    read, rows = items(api)
    assert rows["github"]["skipped"] is True and rows["github"]["done"] is False
    assert read["done"] == 2                                  # signed in, plus the one skipped
    assert api.post("/api/v2/getting-started/state", json={"skip": "computer"},
                    headers=signed_in()).status_code == 422
    # Installing the app is what completes it, whether or not it was skipped.
    service = api.app.state.github_app
    with api.app.state.store.transaction() as c:
        service.save(c, "human:morgan", "AcmeCorp", False,
                     {"id": 7, "slug": "acme-tico", "client_id": "cid", "pem": "pem"})
    assert items(api)[1]["github"]["done"] is False           # connected is not installed
    with api.app.state.store.transaction() as c:
        c.execute("UPDATE github_app SET installation_id=99")
    assert items(api)[1]["github"]["done"] is True


def test_each_person_sees_only_what_they_can_act_on(environment):
    api = environment()
    riley = as_person(api, "riley")                # a bot administrator
    quinn = as_person(api, "quinn")                # neither
    assert [r["id"] for r in items(api)[0]["items"]] == [
        "signed_in", "computer", "model", "github", "botops", "first_bot", "bot_task", "first_update"]
    assert [r["id"] for r in items(api, riley)[0]["items"]] == [
        "signed_in", "botops", "first_bot", "bot_task", "first_update"]
    assert [r["id"] for r in items(api, quinn)[0]["items"]] == ["signed_in", "bot_task", "first_update"]


def test_dismissals_persist_per_person(environment):
    api = environment()
    riley = as_person(api, "riley")
    api.post("/api/v2/getting-started/state",
             json={"tour": True, "checklist": True, "card": "docs"}, headers=signed_in())
    api.post("/api/v2/getting-started/state", json={"card": "market"}, headers=signed_in())
    mine = items(api)[0]
    assert (mine["tour_seen"], mine["dismissed"], mine["cards_dismissed"]) == (True, True, ["docs", "market"])
    theirs = items(api, riley)[0]
    assert (theirs["tour_seen"], theirs["dismissed"], theirs["cards_dismissed"]) == (False, False, [])
    api.post("/api/v2/getting-started/state", json={"checklist": False}, headers=signed_in())
    assert items(api)[0]["dismissed"] is False
    assert items(api)[0]["cards_dismissed"] == ["docs", "market"]        # bringing it back leaves the cards
    assert api.post("/api/v2/getting-started/state", json={"card": "nope"},
                    headers=signed_in()).status_code == 422


def test_a_bot_or_runner_cannot_read_it(environment):
    api = environment()
    assert api.get("/api/v2/getting-started").status_code in (401, 403)


def test_a_new_bot_is_a_task_for_botops_and_needs_botops_active(environment):
    api = environment()
    ask = {"what": "Answer the support inbox every morning", "name": "Help Desk"}
    refused = api.post("/api/v2/getting-started/bot", json=ask, headers=signed_in())
    assert refused.status_code == 409
    activate(api, "botops")
    made = api.post("/api/v2/getting-started/bot", json=ask, headers=signed_in())
    assert made.status_code == 200, made.text
    assert made.json()["slug"] == "help-desk"
    task = api.get("/api/v2/tasks", params={"owner": "botops"}, headers=signed_in()).json()["tasks"][0]
    assert task["title"] == "Build a bot: Help Desk"
    assert "Answer the support inbox every morning" in task["body"]
    assert "- slug: help-desk" in task["body"]
    # The server record exists already, planned, so the bot is on the chart and can take routines.
    with api.app.state.store.read() as c:
        row = c.execute("SELECT b.state,b.model,g.repo,g.description,g.reports_to FROM bots b "
                        "JOIN bot_config g ON g.bot=b.slug WHERE b.slug='help-desk'").fetchone()
    assert (row["state"], row["repo"], row["description"]) == \
        ("planned", "emp-help-desk", "Answer the support inbox every morning")
    assert row["reports_to"].startswith("human:") and row["model"]
    assert "already created, state planned" in task["body"]
    chart = api.get("/api/v2/org", headers=signed_in()).json()
    owner = row["reports_to"].split(":", 1)[1]
    assert any(b["id"] == "help-desk" for b in chart["bots"])
    assert any(owner in (b.get("reports_to") or "") for b in chart["bots"] if b["id"] == "help-desk")
    # A planned bot already counts as the first one, so the rail card and the checklist step settle.
    assert items(api)[1]["first_bot"]["done"] is True
    # A second request with the same name gets its own slug and record.
    again = api.post("/api/v2/getting-started/bot", json=ask, headers=signed_in())
    assert again.status_code == 200, again.text
    assert again.json()["slug"] == "help-desk-2"
    with api.app.state.store.read() as c:
        assert H.bot(c, "help-desk-2")["state"] == "planned"
    # While BotOps works, the checklist points at the task instead of asking again.
    row = items(api)[1]["first_bot"]
    assert row["href"].startswith("#/task/") and row["action"] == ""
    # A person who neither owns the company nor administers bots cannot ask.
    assert api.post("/api/v2/getting-started/bot", json=ask,
                    headers=as_person(api, "quinn")).status_code == 403


def test_docs_and_market_are_the_owners(environment):
    api = environment()
    activate(api, "botops")
    quinn = as_person(api, "quinn")
    assert api.post("/api/v2/getting-started/docs", json={"links": [{"url": "https://drive.example.com/x"}]},
                    headers=quinn).status_code == 403
    assert api.post("/api/v2/getting-started/market", json={"sells": "a", "customers": "b"},
                    headers=quinn).status_code == 403


def test_the_docs_card_turns_pasted_links_into_linked_docs(environment):
    api = environment()
    assert body_of(api)["empty"]["docs"] is True
    made = api.post("/api/v2/getting-started/docs", headers=signed_in(), json={"links": [
        {"url": "https://github.com/AcmeCorp/handbook", "description": "Engineering handbook"},
        {"url": "https://www.notion.so/Acme-Wiki-1"},
        {"url": "https://github.com/AcmeCorp/handbook"},           # a repeat
        {"url": "javascript:alert(1)"}]})
    assert made.status_code == 200, made.text
    linked, skipped = made.json()["linked"], made.json()["skipped"]
    assert [(row["kind"], row["description"]) for row in linked] == [("github", "Engineering handbook"), ("notion", "")]
    assert len(skipped) == 2
    assert [row["title"] for row in api.get("/api/v2/linked-docs", headers=signed_in()).json()["linked"]] == \
        ["github.com/AcmeCorp/handbook", "notion.so/Acme-Wiki-1"]
    assert body_of(api)["empty"]["docs"] is False                # the card's section now has content
    assert api.post("/api/v2/getting-started/docs", json={"links": []}, headers=signed_in()).status_code == 422
    assert api.get("/api/v2/tasks", params={"owner": "botops"}, headers=signed_in()).json()["tasks"] == []


def test_market_answers_are_saved_and_start_research(environment):
    api = environment()
    activate(api, "botops")
    answers = {"sells": "Cleaning for offices", "customers": "Property managers",
               "competitors": "CleanCo", "channels": "r/propertymanagement"}
    # BotOps adding a bot is asked first: nothing is saved or filed until the owner confirms.
    held = api.post("/api/v2/getting-started/market", json=answers, headers=signed_in())
    assert held.status_code == 409 and held.json()["error"]["code"] == "confirm_analyst"
    assert api.get("/api/v2/tasks", params={"owner": "botops"}, headers=signed_in()).json()["tasks"] == []
    asked = api.post("/api/v2/getting-started/market", json={**answers, "add_analyst": True},
                     headers=signed_in()).json()
    assert asked == {"task_id": asked["task_id"], "bot": "botops", "needs_analyst": True}
    with api.app.state.store.read() as c:
        stored = json.loads(c.execute("SELECT value_json FROM registry_metadata WHERE key='market-context'")
                            .fetchone()[0])
    assert stored["sells"] == "Cleaning for offices" and stored["channels"] == "r/propertymanagement"
    add_bot(api, "market-analyst")
    again = api.post("/api/v2/getting-started/market", json=answers, headers=signed_in()).json()
    assert again["bot"] == "market-analyst" and again["needs_analyst"] is False
    task = api.get("/api/v2/tasks", params={"owner": "market-analyst"}, headers=signed_in()).json()["tasks"][0]
    assert "CleanCo" in task["body"] and "r/propertymanagement" in task["body"]


def test_a_section_card_lasts_only_while_its_section_is_empty(environment):
    api = environment()
    assert set(items(api)[0]["empty"].values()) == {True}
    activate(api, "botops")
    api.post("/api/v2/getting-started/market", json={"sells": "a", "customers": "b", "add_analyst": True},
             headers=signed_in())
    body = items(api)[0]
    assert body["empty"]["market"] is False and body["empty"]["tasks"] is False and body["empty"]["docs"] is True
