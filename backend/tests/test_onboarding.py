"""First-run onboarding: pick templates, name things, and hand BotOps the setup backlog.

The catalog is written per test, so these assertions never depend on the cards a release
happens to ship. The company is Acme, its app is Atlas, its assistant Morgan.
"""

import uuid
from pathlib import Path

import pytest
import yaml
from fastapi.testclient import TestClient

from backend.app import create_app
from backend.auth import Identity
from backend.config import Settings
from backend.store import H, encode

COMPANY = {"environment_id": "acme-7", "company_name": "Acme", "app_name": "Atlas",
           "assistant_name": "Morgan", "assistant_bot": "coo", "github_owner": "AcmeCorp"}
OWNER_EMAIL = "morgan@acme.example"
PEOPLE = {"default_user": "morgan", "people": [
    {"id": "morgan", "name": "Morgan Reed", "email": OWNER_EMAIL, "primary_for": ["*"]},
    {"id": "riley", "name": "Riley Quinn", "email": "riley@acme.example", "primary_for": []},
    {"id": "quinn", "name": "Quinn Ellis", "email": "quinn@acme.example", "primary_for": []}]}
# What a fresh environment seeds: the assistant people talk to, and the bot that builds the
# rest. Both start planned, exactly as templates/environment-registry/employees.yaml does.
SEED = {"coo": {"name": "coo", "status": "planned"},
        "botops": {"name": "botops", "status": "planned"}}
TOKEN = "local-owner-secret-token-0123456789"

ASSISTANT_CARD = {
    "template": "assistant", "slug": "coo", "name": "{{assistant_name}}", "required": True, "default": True,
    "bootstrap": True, "summary": "The assistant {{company_name}} talks to in {{app_name}}.",
    "owns": ["{{company_name}}'s task list"], "never": ["Spend {{company_name}}'s money"],
    "reasoning_effort": "high", "recommend_when": ["always"]}
BOTOPS_CARD = {
    "template": "botops", "slug": "botops", "name": "BotOps", "required": True,
    "bootstrap": True, "summary": "Sets every other bot up.", "owns": ["bot repositories"],
    "never": ["publishes"],
    "reasoning_effort": "high", "recommend_when": ["always"]}
SUPPORT_CARD = {
    "template": "support", "slug": "support", "name": "Support", "required": False,
    "bootstrap": False, "summary": "Answers the support inbox.", "owns": ["the inbox"],
    "never": ["refunds"],
    "reasoning_effort": "high", "recommend_when": ["has_support_inbox", "uses_tickets"]}
SALES_CARD = {
    "template": "sales", "slug": "sales", "name": "Sales", "required": False,
    "bootstrap": False, "summary": "Researches accounts and drafts outreach.",
    "owns": ["the pipeline"], "never": ["sends"],
    "reasoning_effort": "high",
    "recommend_when": ["sells_to_businesses", "has_pipeline"]}

ASSISTANT_AGENT = "# {{bot_name}}\n\nYou are {{assistant_name}}, {{company_name}}'s assistant in {{app_name}}.\n"
SUPPORT_AGENT = "# {{bot_name}}\n\nYou answer {{company_name}}'s support inbox.\n"


def write_catalog(root, cards):
    """One catalog on disk: a folder, a card, and the AGENT.md a person reviews."""
    root.mkdir(parents=True, exist_ok=True)
    for card, instructions in cards:
        folder = root / card["template"]
        folder.mkdir()
        (folder / "card.yaml").write_text(yaml.safe_dump(card))
        (folder / "AGENT.md").write_text(instructions)
    return root


@pytest.fixture
def environment(tmp_path):
    """A signed-in, loopback environment seeded with just coo and botops, plus a catalog."""
    clients = []

    def build(cards=None, seed=SEED, **overrides):
        index = len(clients)
        registry = tmp_path / ("registry-%d" % index)
        registry.mkdir()
        (registry / "hub-access.yaml").write_text(yaml.safe_dump(
            {"private_owners": [], "bot_admins": ["riley@acme.example"]}))
        token = tmp_path / ("token-%d" % index)
        token.write_text(TOKEN)
        token.chmod(0o600)
        catalog = tmp_path / ("catalog-%d" % index)
        if cards is None:
            cards = [(ASSISTANT_CARD, ASSISTANT_AGENT), (BOTOPS_CARD, ""),
                     (SUPPORT_CARD, SUPPORT_AGENT), (SALES_CARD, "")]
        write_catalog(catalog, cards)
        settings = Settings(db_path=tmp_path / ("hub-%d.db" % index), registry_dir=registry,
                            catalog_dir=catalog, local_owner_token_file=token,
                            **{"owner_email": OWNER_EMAIL, "enabled_providers": ("openai",), **COMPANY, **overrides})
        client = TestClient(create_app(settings))
        client.__enter__()
        clients.append(client)
        with client.app.state.store.transaction() as c:
            H.sync_registry(c, seed, PEOPLE)
            c.execute("INSERT INTO registry_metadata VALUES('people',?)", (encode(PEOPLE),))
            for slug, config in seed.items():
                c.execute("INSERT INTO bot_config(bot,config_json,operator,repo) VALUES(?,?,?,?)",
                          (slug, encode(config), "morgan", "emp-" + slug))
        return client

    yield build
    for client in clients:
        client.__exit__(None, None, None)


def signed_in(token=TOKEN):
    return {"Authorization": "Bearer " + token, "Idempotency-Key": str(uuid.uuid4())}


def as_person(api, person):
    """A signed-in non-owner, without standing an identity proxy up for the test."""
    api.app.state.store.settings.test_identities[person] = Identity(
        "human:" + person, "human", email=person + "@acme.example")
    return signed_in(person)


def machine(api, label="Owner Mac"):
    code = api.post("/api/v2/enrollments", json={"operator": "morgan"}, headers=signed_in()).json()["code"]
    return api.post("/api/v2/runners/enroll", json={"code": code, "label": label, "platform": "test"},
                    headers={"Idempotency-Key": str(uuid.uuid4())}).json()


def draft(api, **overrides):
    body = {"names": {"company_name": "Acme", "app_name": "Atlas", "assistant_name": "Morgan"},
            "answers": {"what_we_do": "We clean apartments.", "customers": "businesses",
                        "team_size": "6-10", "work_arrives": ["email", "tickets"],
                        "repetitive_work": "Answering the same questions.",
                        "never_without_person": ["send", "spend"]},
            "selected": {}}
    body.update(overrides)
    return api.put("/api/v2/onboarding", json=body, headers=signed_in())


def test_completing_twice_duplicates_neither_a_bot_nor_a_task(environment):
    api = environment()
    draft(api, selected={"support": {"template": "support", "display_name": "Help",
                                     "instructions": "Answer within a day."}})
    first = api.post("/api/v2/onboarding/complete", json={}, headers=signed_in()).json()
    again = api.post("/api/v2/onboarding/complete", json={}, headers=signed_in())
    assert again.status_code == 200, again.text
    record = again.json()
    assert record["completed"] == first["completed"]
    assert [row["slug"] for row in record["bots"]] == [row["slug"] for row in first["bots"]]
    assert {row["slug"]: row["setup_task_id"] for row in record["bots"]} == {
        row["slug"]: row["setup_task_id"] for row in first["bots"]}
    tasks = api.get("/api/v2/tasks", params={"owner": "botops"}, headers=signed_in()).json()["tasks"]
    assert len(tasks) == 1


def test_botops_and_the_assistant_are_always_built(environment):
    """An owner who skips every card still gets BotOps and the assistant: both are built in."""
    api = environment(seed={})
    draft(api)
    record = api.post("/api/v2/onboarding/complete", json={}, headers=signed_in()).json()
    bots = {row["slug"]: row for row in record["bots"]}
    assert sorted(bots) == ["botops", "coo"]
    assert all(row["setup_task_id"] is None for row in bots.values())
    cards = {card["slug"]: card for card in api.get("/api/v2/catalog", headers=signed_in()).json()["cards"]}
    assert cards["botops"]["required"] and cards["coo"]["required"]


def test_a_picked_assistant_is_built_under_the_company_s_name_for_it(environment):
    api = environment(seed={})
    draft(api, selected={"coo": {"template": "assistant", "display_name": "Morgan", "instructions": "Route."}})
    record = api.post("/api/v2/onboarding/complete", json={}, headers=signed_in()).json()
    bots = {row["slug"]: row for row in record["bots"]}
    assert sorted(bots) == ["botops", "coo"]
    assert bots["coo"]["display_name"] == "Morgan" and bots["coo"]["template"] == "assistant"
    assert all(row["setup_task_id"] is None for row in bots.values())


def test_an_archived_assistant_is_never_restored_by_finishing_and_an_installed_one_is_untouched(environment):
    api = environment()
    draft(api)
    api.post("/api/v2/onboarding/complete", json={}, headers=signed_in())
    assert _states(api)["coo"] == "planned"
    # A company that set the assistant aside before it was built in keeps it archived until the owner
    # turns it on (Assistant tab or Settings > Bots): finishing again does not bring it back.
    with api.app.state.store.transaction() as c:
        c.execute("UPDATE bots SET state='archived' WHERE slug='coo'")
    api.post("/api/v2/onboarding/complete", json={}, headers=signed_in())
    assert _states(api)["coo"] == "archived"
    # An install that already finished with the assistant, running, is untouched.
    again = environment()
    draft(again, selected={"coo": {"template": "assistant", "display_name": "Morgan", "instructions": ""}})
    again.post("/api/v2/onboarding/complete", json={}, headers=signed_in())
    with again.app.state.store.transaction() as c:
        c.execute("UPDATE bots SET state='active' WHERE slug='coo'")
    draft(again)
    again.post("/api/v2/onboarding/complete", json={}, headers=signed_in())
    assert _states(again)["coo"] == "active"


def test_every_shipped_card_lists_owns_and_never_as_sentences():
    """YAML reads `- The watchlist: names` as a mapping; a card must reach a person as a string."""
    from backend.onboarding import read_cards
    cards = read_cards(Settings(db_path=Path("unused.db")))
    assert cards
    for card in cards:
        for key in ("owns", "never"):
            assert all(isinstance(line, str) and "{" not in line.split(":")[0] for line in card[key]), card["slug"]
    listening = next(card for card in cards if card["slug"] == "listening")
    assert "The watchlist: names, queries and sources one sweep reads" in listening["owns"]


def test_a_mapping_in_a_card_list_becomes_a_sentence():
    from backend.onboarding import _strings
    assert _strings([{"The watchlist": "names and sources"}, "Plain", ""]) == [
        "The watchlist: names and sources", "Plain"]


def test_only_the_owner_sets_the_company_up(environment):
    api = environment()
    riley = as_person(api, "riley")                # a bot administrator, not the owner
    assert api.get("/api/v2/onboarding", headers=riley).status_code == 200
    assert api.put("/api/v2/onboarding", json={"names": {}, "answers": {}, "selected": {}},
                   headers=riley).status_code == 403
    assert api.post("/api/v2/onboarding/complete", json={}, headers=riley).status_code == 403

    quinn = as_person(api, "quinn")               # neither the owner nor a bot administrator
    assert api.get("/api/v2/onboarding", headers=quinn).status_code == 403
    # The catalog itself is readable by anyone who is signed in; it names no company records.
    assert api.get("/api/v2/catalog", headers=quinn).status_code == 200


def test_a_company_that_already_runs_bots_is_never_sent_back_to_the_wizard(environment):
    # Deployments older than onboarding have no record at all, but their bots are live.
    api = environment()
    with api.app.state.store.transaction() as c:
        c.execute("UPDATE bots SET state='active' WHERE slug='coo'")
    assert api.get("/api/v2/config", headers=signed_in()).json()["onboarding_needed"] is False
    assert api.get("/api/v2/onboarding", headers=signed_in()).json()["needed"] is False


# ----------------------------------------------------------------------------- provider choice
def test_the_owner_saves_a_revisioned_choice_and_a_stale_editor_is_refused(environment):
    api = environment(seed={}, enabled_providers=())
    read = api.get("/api/v2/providers", headers=signed_in()).json()
    assert not read["configured"] and read["revision"] == 0
    saved = api.put("/api/v2/providers", headers=signed_in(), json={
        "enabled": ["anthropic", "google"], "expected_revision": 0})
    assert saved.status_code == 200, saved.text
    assert saved.json()["default"] == {"runtime": "claude", "model": "claude-opus-5"}
    assert saved.json()["revision"] == 1
    stale = api.put("/api/v2/providers", headers=signed_in(), json={"enabled": ["openai"], "expected_revision": 0})
    assert stale.status_code == 409
    assert api.get("/api/v2/config", headers=signed_in()).json()["providers_configured"] is True
    models = api.get("/api/v2/models", headers=signed_in()).json()
    assert models["enabled_providers"] == ["anthropic", "google"]
    assert models["default"]["model"] == "claude-opus-5"
    with api.app.state.store.read() as c:
        assert c.execute("SELECT count(*) FROM events WHERE action='providers.updated'").fetchone()[0] == 1


def test_only_the_owner_writes_the_choice(environment):
    api = environment(seed={}, enabled_providers=())
    denied = api.put("/api/v2/providers", json={"enabled": ["openai"]},
                     headers={"Authorization": "Bearer nobody", "Idempotency-Key": "k"})
    assert denied.status_code in (401, 403)


def test_the_environment_seeds_the_choice_once(environment):
    api = environment(seed={}, enabled_providers=("xai", "openai"), default_runtime="codex")
    read = api.get("/api/v2/providers", headers=signed_in()).json()
    assert read["enabled"] == ["xai", "openai"]
    assert read["default"] == {"runtime": "codex", "model": "gpt-6-luna"}
    assert read["source"] == "environment" and read["revision"] == 1
    # After the first boot the database, not the environment, holds the choice.
    saved = api.put("/api/v2/providers", headers=signed_in(), json={"enabled": ["anthropic"], "expected_revision": 1})
    assert saved.json()["enabled"] == ["anthropic"]


def test_nothing_configured_means_an_actionable_error_not_a_vendor(environment):
    api = environment(seed={}, enabled_providers=())
    done = api.post("/api/v2/onboarding/complete", json={}, headers=signed_in())
    assert done.status_code == 409
    assert "Settings > AI providers" in done.json()["error"]["detail"]


def test_with_only_anthropic_enabled_every_bot_gets_a_claude_model(environment):
    api = environment(seed={}, enabled_providers=("anthropic",))
    draft(api, selected={"support": {"template": "support", "display_name": "Help", "instructions": ""}})
    assert api.post("/api/v2/onboarding/complete", json={}, headers=signed_in()).status_code == 200
    with api.app.state.store.read() as c:
        rows = c.execute("SELECT runtime,model FROM bots").fetchall()
    assert rows and {(row["runtime"], row["model"]) for row in rows} == {("claude", "claude-opus-5")}


def _states(api):
    with api.app.state.store.read() as c:
        return {row["slug"]: row["state"] for row in c.execute("SELECT slug,state FROM bots")}


def test_completing_onboarding_activates_the_bootstrap_bots_once_a_machine_hosts_them(environment):
    api = environment(seed={})
    machine(api)
    draft(api, selected={"support": {"template": "support", "display_name": "Support", "instructions": ""},
                         "coo": {"template": "assistant", "display_name": "Morgan", "instructions": ""}})
    api.post("/api/v2/onboarding/complete", json={}, headers=signed_in())
    states = _states(api)
    assert states["botops"] == "active" and states["coo"] == "active"
    assert states["support"] == "planned"          # activating what BotOps builds stays a person's call
    task = api.post("/api/v2/tasks", json={"owner": "botops", "title": "Look at this", "body": "x"},
                    headers=signed_in())
    assert task.status_code == 200, task.text


def test_a_machine_enrolled_after_completion_also_activates_the_bootstrap_bots(environment):
    api = environment(seed={})
    draft(api)
    api.post("/api/v2/onboarding/complete", json={}, headers=signed_in())
    assert _states(api)["botops"] == "planned"
    machine(api)
    assert _states(api)["botops"] == "active"


def test_bots_go_to_the_only_online_machine_when_the_owner_has_none(environment):
    api = environment(seed={})
    code = api.post("/api/v2/enrollments", json={"operator": "riley"}, headers=signed_in()).json()["code"]
    other = api.post("/api/v2/runners/enroll", json={"code": code, "label": "Server", "platform": "linux"},
                     headers={"Idempotency-Key": str(uuid.uuid4())}).json()
    api.post("/api/v2/runners/heartbeat", json={"version": "test", "platform": "linux"},
             headers={"Authorization": "Bearer " + other["token"], "Idempotency-Key": str(uuid.uuid4())})
    draft(api, selected={"coo": {"template": "assistant", "display_name": "Morgan", "instructions": ""}})
    response = api.post("/api/v2/onboarding/complete", json={}, headers=signed_in())
    assert response.status_code == 200, response.text
    record = response.json()
    assert record["assigned_to"]["runner_id"] == other["runner_id"]
    assert {row["slug"] for row in record["bots"] if row["assigned_to"]} == {"botops", "coo"}


def test_provider_details_match_what_each_harness_accepts():
    """Codex and Claude Code both take an API key as well as a subscription (runner/harnesses/*.toml)."""
    from backend import providers
    for harness, key in (("codex", "OPENAI_API_KEY"), ("claude-code", "ANTHROPIC_API_KEY")):
        assert key in (Path("runner/harnesses") / (harness + ".toml")).read_text()
    by_id = {row["id"]: row["detail"] for row in providers.PROVIDERS}
    assert by_id["openai"] == "Codex CLI, with a ChatGPT subscription or an OpenAI API key (OPENAI_API_KEY)"
    assert "Claude subscription or an Anthropic API key (ANTHROPIC_API_KEY)" in by_id["anthropic"]
