"""First-run onboarding: pick templates, name things, and hand BotOps the setup backlog.

The catalog is written per test, so these assertions never depend on the cards a release
happens to ship. The company is Acme, its app is Atlas, its assistant Morgan.
"""

import json
import uuid
from pathlib import Path

import pytest
import yaml
from fastapi.testclient import TestClient

from backend import providers
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
            {"bot_admins": ["riley@acme.example"]}))
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
    saved = draft(api)
    assert saved.status_code == 200 and "never_without_person" not in saved.json()["answers"]
    with api.app.state.store.read() as c:
        kept = c.execute("SELECT value_json FROM registry_metadata WHERE key='onboarding'").fetchone()[0]
        assert "never_without_person" not in kept
    record = api.post("/api/v2/onboarding/complete", json={}, headers=signed_in()).json()
    bots = {row["slug"]: row for row in record["bots"]}
    assert sorted(bots) == ["botops", "coo"]
    assert all(row["setup_task_id"] is None for row in bots.values())
    cards = {card["slug"]: card for card in api.get("/api/v2/catalog", headers=signed_in()).json()["cards"]}
    assert cards["botops"]["required"] and cards["coo"]["required"]


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


def test_an_assistant_named_after_the_company_becomes_assistant_once(environment):
    from types import SimpleNamespace
    from backend.onboarding import Onboarding
    api = environment()
    store = api.app.state.store
    fix = lambda c: Onboarding.name_default_assistant(SimpleNamespace(settings=store.settings), c)
    with store.transaction() as c:
        c.execute("UPDATE bots SET display_name='Acme' WHERE slug='coo'")
        assert fix(c) is True
        assert H.bot(c, "coo")["display_name"] == "Assistant"
        assert fix(c) is False                       # idempotent
        c.execute("UPDATE bots SET display_name='Ace' WHERE slug='coo'")
        assert fix(c) is False                       # a name someone chose stays


# ----------------------------------------------------------------------------- provider choice
def test_the_owner_saves_a_revisioned_choice_and_a_stale_editor_is_refused(environment):
    api = environment(seed={}, enabled_providers=())
    read = api.get("/api/v2/providers", headers=signed_in()).json()
    assert not read["configured"] and read["revision"] == 0
    # No model to sign in to before a provider is chosen: the config carries no runtime until then.
    assert api.get("/api/v2/config", headers=signed_in()).json()["default_runtime"] == ""
    saved = api.put("/api/v2/providers", headers=signed_in(), json={
        "enabled": ["anthropic", "google"], "expected_revision": 0})
    assert saved.status_code == 200, saved.text
    assert saved.json()["default"] == {"runtime": "claude", "model": "claude-opus-5"}
    assert saved.json()["revision"] == 1
    stale = api.put("/api/v2/providers", headers=signed_in(), json={"enabled": ["openai"], "expected_revision": 0})
    assert stale.status_code == 409
    config = api.get("/api/v2/config", headers=signed_in()).json()
    assert config["providers_configured"] is True and config["default_runtime"] == "claude"
    models = api.get("/api/v2/models", headers=signed_in()).json()
    assert models["enabled_providers"] == ["anthropic", "google"]
    assert models["default"]["model"] == "claude-opus-5"
    with api.app.state.store.read() as c:
        assert c.execute("SELECT count(*) FROM events WHERE action='providers.updated'").fetchone()[0] == 1


def test_the_team_is_created_with_no_provider_and_no_computer_and_starts_once_they_exist(environment):
    api = environment(seed={}, enabled_providers=())
    draft(api, selected={"support": {"template": "support", "display_name": "Support", "instructions": ""}})
    done = api.post("/api/v2/onboarding/complete", json={}, headers=signed_in())
    assert done.status_code == 200, done.text
    assert {"botops", "support"} <= {row["slug"] for row in done.json()["bots"]}
    with api.app.state.store.read() as c:
        config = json.loads(c.execute("SELECT config_json FROM bot_config WHERE bot='support'").fetchone()[0])
        assert not c.execute("SELECT 1 FROM assignments").fetchone()
    assert not {"model", "runtime"} & set(config)                # it follows the company default, once there is one
    assert _states(api)["botops"] == "planned"                   # nothing is placed or running yet
    machine(api)                                                 # a computer appears: the bots are placed
    assert _states(api)["botops"] == "active"
    with api.app.state.store.read() as c:
        assert c.execute("SELECT 1 FROM assignments WHERE bot='support'").fetchone()
    api.put("/api/v2/providers", headers=signed_in(), json={"enabled": ["openai"], "expected_revision": 0})
    with api.app.state.store.read() as c:                        # a provider is added: the bot resolves to it
        assert providers.bot_choice(c, api.app.state.store.settings, config)[0] == "codex"


def test_a_gmail_owner_names_the_team_domain_once_and_members_may_add_coworkers_there(environment):
    api = environment(owner_email="morgan@gmail.com")
    def domains():
        return api.get("/api/me", headers=signed_in()).json()["company_domains"]
    with api.app.state.store.transaction() as c:     # the roster has no company address either
        c.execute("DELETE FROM registry_metadata WHERE key='people'")
        c.execute("UPDATE humans SET email='morgan@gmail.com'")
    assert domains() == []
    body = {"names": {"company_name": "Acme", "app_name": "Atlas", "team_domain": "@Initech.example"}}
    assert api.put("/api/v2/onboarding", json=body, headers=signed_in()).json()["names"]["team_domain"] == "initech.example"
    assert domains() == ["initech.example"]
    assert api.put("/api/v2/onboarding", json={"names": {"team_domain": "gmail.com"}}, headers=signed_in()).status_code == 422
    kept = api.put("/api/v2/onboarding", json={"names": {"company_name": "Acme"}}, headers=signed_in())
    assert kept.json()["names"]["team_domain"] == "initech.example"           # a client that never asks leaves it
    cleared = api.put("/api/v2/onboarding", json={"names": {"team_domain": ""}}, headers=signed_in())
    assert cleared.json()["names"]["team_domain"] == "" and domains() == []


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


LIBRARIAN_CARD = {
    "template": "librarian", "slug": "librarian", "name": "Librarian", "required": True,
    "bootstrap": True, "summary": "Answers from the docs.", "owns": ["the map"], "never": ["invents"],
    "reasoning_effort": "medium", "recommend_when": ["always"]}
LIBRARIAN_MANIFEST = {"name": "librarian", "schedules": [{
    "id": "refresh-the-map", "title": "Refresh the map", "cron": "30 3 * * *", "timezone": "America/Los_Angeles",
    "template": "playbooks/refresh-the-map.md"}]}


def with_librarian_template(api):
    """The catalog a release ships the Librarian in: its card, and the routine it starts with."""
    folder = Path(api.app.state.store.settings.catalog_dir) / "librarian"
    (folder / "playbooks").mkdir(parents=True)
    (folder / "card.yaml").write_text(yaml.safe_dump(LIBRARIAN_CARD))
    (folder / "AGENT.md").write_text("# {{bot_name}}\n")
    (folder / "employee.yaml").write_text(yaml.safe_dump(LIBRARIAN_MANIFEST))
    (folder / "playbooks/refresh-the-map.md").write_text("Refresh {{company_name}}'s map of the docs.\n")


def _routines(api):
    with api.app.state.store.read() as c:
        return [dict(row) for row in c.execute(
            "SELECT id,cron,playbook,deleted_at FROM schedules WHERE bot='librarian'")]


def test_the_librarian_is_always_built_with_its_daily_routine_seeded_once(environment):
    api = environment(seed={}, cards=[(ASSISTANT_CARD, ASSISTANT_AGENT), (BOTOPS_CARD, ""), (LIBRARIAN_CARD, "# L\n")])
    machine(api)
    folder = Path(api.app.state.store.settings.catalog_dir) / "librarian"
    (folder / "playbooks").mkdir()
    (folder / "employee.yaml").write_text(yaml.safe_dump(LIBRARIAN_MANIFEST))
    (folder / "playbooks/refresh-the-map.md").write_text("Refresh {{company_name}}'s map of the docs.\n")
    draft(api)
    record = api.post("/api/v2/onboarding/complete", json={}, headers=signed_in()).json()
    assert sorted(row["slug"] for row in record["bots"]) == ["botops", "coo", "librarian"]
    assert all(row["setup_task_id"] is None for row in record["bots"])         # the runner sets it up, not BotOps
    assert _states(api)["librarian"] == "active"
    (routine,) = _routines(api)
    assert routine["id"] == "librarian:refresh-the-map" and routine["cron"] == "30 3 * * *"
    assert routine["playbook"].strip() == "Refresh Acme's map of the docs."      # the company's words, filled in
    api.post("/api/v2/onboarding/complete", json={}, headers=signed_in())
    assert len(_routines(api)) == 1                                              # twice is still one
    with api.app.state.store.transaction() as c:                                 # a person deleted it
        c.execute("UPDATE schedules SET deleted_at=? WHERE bot='librarian'", (H.now(),))
    api.post("/api/v2/onboarding/complete", json={}, headers=signed_in())
    assert [r["deleted_at"] is not None for r in _routines(api)] == [True]       # and it stays deleted



def _botops_goals(api):
    with api.app.state.store.read() as c:
        return [dict(row) for row in c.execute("SELECT * FROM goals WHERE owner='bot:botops'")]


def test_builtin_bots_get_no_default_goals_on_setup_or_upgrade(environment):
    api = environment(seed={})
    machine(api)
    draft(api)
    api.post("/api/v2/onboarding/complete", json={}, headers=signed_in())
    assert _botops_goals(api) == []
    api.app.state.store.initialize(seed_market=False)
    api.post("/api/v2/onboarding/complete", json={}, headers=signed_in())
    assert _botops_goals(api) == []


def test_existing_builtin_goals_survive_upgrade(environment):
    api = environment()
    assert _botops_goals(api) == []
    made = api.post("/api/v2/goals", json={"title": "Own goal", "owner": "botops"}, headers=signed_in())
    assert made.status_code == 200, made.text
    api.app.state.store.initialize(seed_market=False)
    assert [g["title"] for g in _botops_goals(api)] == ["Own goal"]


def test_the_assistant_is_called_assistant_unless_someone_named_it_and_never_by_the_company_name(environment):
    """The container used to default TICO_ASSISTANT_NAME to the company, so the Review step listed the assistant as
    "Tico Team". Unset, it is "Assistant", and a draft that carries the company's name gets "Assistant" too."""
    from backend.onboarding import display_names
    assert Settings(db_path=Path("x.db")).assistant_name == "Assistant"
    api = environment(company_name="Tico Team", assistant_name="Tico Team")
    settings = api.app.state.store.settings
    assert display_names(settings, {"names": {}})["assistant_name"] == "Assistant"
    assert display_names(settings, {"names": {"assistant_name": "Ada"}})["assistant_name"] == "Ada"
    assert api.get("/api/v2/config", headers=signed_in()).json()["assistant_name"] == "Assistant"
    assert "Tico Team" not in [card["name"] for card in api.get("/api/v2/catalog", headers=signed_in()).json()["cards"]
                               if card["template"] == "assistant"]


def test_the_owners_name_from_the_names_step_lands_on_their_roster_entry(environment):
    api = environment()
    with api.app.state.store.transaction() as c:                 # first run knew only the owner's address
        c.execute("UPDATE humans SET name=? WHERE id='morgan'", (OWNER_EMAIL,))
    names = {"company_name": "Acme", "app_name": "Atlas", "assistant_name": "Morgan", "owner_name": "  Morgan  Reed-Ellis "}
    saved = api.put("/api/v2/onboarding", json={"names": names}, headers=signed_in())
    assert saved.status_code == 200 and saved.json()["names"]["owner_name"] == "Morgan  Reed-Ellis"
    with api.app.state.store.read() as c:
        assert c.execute("SELECT name FROM humans WHERE id='morgan'").fetchone()[0] == "Morgan Reed-Ellis"
    assert api.get("/api/people", headers=signed_in()).json()["people"][0]["name"] == "Morgan Reed-Ellis"
    # Blank leaves the name alone; saving again changes nothing.
    api.put("/api/v2/onboarding", json={"names": {**names, "owner_name": ""}}, headers=signed_in())
    with api.app.state.store.read() as c:
        assert c.execute("SELECT name FROM humans WHERE id='morgan'").fetchone()[0] == "Morgan Reed-Ellis"


def test_the_config_says_when_the_server_is_a_container_so_first_run_offers_a_linux_computer_first(environment, monkeypatch):
    from backend import onboarding
    api = environment()
    monkeypatch.setattr(onboarding, "running_in_docker", lambda: True)
    assert api.get("/api/v2/config", headers=signed_in()).json()["in_docker"] is True
    monkeypatch.undo()
    monkeypatch.delenv("TICO_IN_DOCKER", raising=False)
    monkeypatch.setattr(onboarding.Path, "exists", lambda self: False)
    assert onboarding.running_in_docker() is False
    monkeypatch.setenv("TICO_IN_DOCKER", "1")
    assert onboarding.running_in_docker() is True


@pytest.mark.parametrize("state,draining", [("active", 1), ("paused", 0), ("paused", 1)])
def test_enrollment_places_paused_and_draining_bots_but_skips_archived(environment, state, draining):
    from backend import onboarding
    api = environment(seed={"ana": {"name": "Ana", "status": "active", "template": "assistant"},
                            "sam": {"name": "Sam", "status": "archived", "template": "assistant"},
                            "waiting": {"name": "Waiting", "status": state, "template": "assistant"}})
    placement = api.app.state.execution.runner_enrolled.__self__
    with api.app.state.store.transaction() as c:
        c.execute("INSERT INTO bot_control(bot,draining) VALUES('waiting',?)", (draining,))
        if draining:
            H.event(c, "system:deploy", "bot.drain", "waiting", {"release": "test-release"})
        record = onboarding.load(c)
        record["completed"] = H.now()
        placement._store(c, record, placement.auth.owner_identity(c).actor)
    computer = machine(api)
    with api.app.state.store.transaction() as c:
        assert placement.assign_pending(c, computer["runner_id"]) == []
        rows = c.execute("SELECT bot,runner_id FROM assignments ORDER BY bot").fetchall()
        assert [(row["bot"], row["runner_id"]) for row in rows] == [
            ("ana", computer["runner_id"]), ("waiting", computer["runner_id"])]
        assert c.execute("SELECT state FROM bots WHERE slug='sam'").fetchone()[0] == "archived"
        assert c.execute("SELECT state FROM bots WHERE slug='waiting'").fetchone()[0] == state
        assert c.execute("SELECT draining FROM bot_control WHERE bot='waiting'").fetchone()[0] == draining


def test_automatic_placement_includes_legacy_config_without_a_bot_row(environment):
    api = environment(seed={})
    computer = machine(api)
    placement = api.app.state.execution.runner_enrolled.__self__
    with api.app.state.store.read() as c:
        c.execute("PRAGMA foreign_keys=OFF")  # legacy databases can contain rows predating these constraints
        c.execute("INSERT INTO bot_config(bot,config_json,operator) VALUES('legacy',?,?)",
                  (encode({"template": "assistant"}), placement.auth.owner_id(c)))
        assert placement.assign_pending(c, computer["runner_id"]) == ["legacy"]
        assert c.execute("SELECT runner_id FROM assignments WHERE bot='legacy'").fetchone()[0] == computer["runner_id"]
