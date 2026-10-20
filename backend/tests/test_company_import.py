"""A picker export creates the selected team through normal owner-only onboarding."""
import copy

import pytest
from fastapi.testclient import TestClient

from backend import company_file as C
from backend.app import create_app
from backend.auth import Identity
from backend.company_file import starter
from backend.store import H, Problem, encode
from backend.tests.test_sample_company import OWNER_EMAIL, PEOPLE, SEED, environment, machine, rows, settings_for, signed_in


def company_text():
    draft = C.Turn(C.blank()).finish()
    draft["company"].update(name="Acme Finance", about="We help small firms manage their books.")
    draft["bots"] = [b for b in draft["bots"] if b["template"] in {"coo", "botops", "finance-lead", "bookkeeping"}]
    for bot in draft["bots"]:
        bot["start"] = bot["template"] != "bookkeeping"
        if bot["template"] == "bookkeeping":
            bot["title"] = "Acme Bookkeeper"
            bot["routine"] = "Review the books each week"
    return C.to_yaml(draft) + "models:\n  source: gateway\n  by_department:\n    finance: mid\n"


def test_import_preserves_selected_team_builtins_and_later_choice_across_retry_and_runner_enrollment(environment):
    api = environment()
    body = {"company_yaml": company_text()}
    preview = api.post("/api/v2/onboarding/company/preview", json=body, headers=signed_in())
    assert preview.status_code == 200, preview.text
    assert not rows(api, "SELECT slug FROM bots WHERE slug='bookkeeping'")
    body["fingerprint"] = preview.json()["fingerprint"]
    done = api.post("/api/v2/onboarding/company/import", json=body, headers=signed_in())
    assert done.status_code == 200, done.text
    assert done.json()["names"]["company_name"] == "Acme Finance"
    bots = {r["slug"]: r for r in rows(api, "SELECT slug,display_name,state FROM bots")}
    assert bots["bookkeeping"]["display_name"] == "Acme Bookkeeper"
    assert bots["bookkeeping"]["state"] == "paused"
    assert "builder" not in bots and "head-of-product" not in bots
    parents = {r["bot"]: r["reports_to"] for r in rows(api, "SELECT bot,reports_to FROM bot_config")}
    assert parents["bookkeeping"] == "finance-lead"
    assert parents["finance-lead"] == "human:owner"
    templates = rows(api, "SELECT json_extract(config_json,'$.template') AS template FROM bot_config")
    assert sum(r["template"] == "assistant" for r in templates) == 1
    assert sum(r["template"] == "botops" for r in templates) == 1
    assert "model_choices" in done.json()["company_import"]["deferred"]
    assert "routines" in done.json()["company_import"]["deferred"]
    saved = rows(api, "SELECT value_json FROM registry_metadata WHERE key='onboarding.company_file'")[0]
    assert '"finance":"mid"' in saved["value_json"]
    before = rows(api, "SELECT id FROM tasks ORDER BY id")
    again = api.post("/api/v2/onboarding/company/import", json=body, headers=signed_in())
    assert again.status_code == 200 and rows(api, "SELECT id FROM tasks ORDER BY id") == before
    machine(api)
    assert rows(api, "SELECT state FROM bots WHERE slug='bookkeeping'")[0]["state"] == "paused"


def test_import_requires_owner_and_matching_preview_and_refuses_replacing_a_configured_company(environment):
    api = environment()
    body = {"company_yaml": company_text(), "fingerprint": "0" * 64}
    refused = api.post("/api/v2/onboarding/company/import", json=body, headers=signed_in())
    assert refused.status_code == 409
    assert not rows(api, "SELECT slug FROM bots WHERE slug='bookkeeping'")
    assert api.post("/api/v2/onboarding/company/import", json=body).status_code in (401, 403)
    api.app.state.store.settings.test_identities["helper-test"] = Identity("human:helper", "human",
                                                                          email="helper@sample.example")
    assert api.post("/api/v2/onboarding/company/preview", json={"company_yaml": body["company_yaml"]},
                    headers=signed_in() | {"Authorization": "Bearer helper-test"}).status_code == 403
    assert api.post("/api/v2/onboarding/company/import", json=body,
                    headers=signed_in() | {"Authorization": "Bearer helper-test"}).status_code == 403
    preview = api.post("/api/v2/onboarding/company/preview", json={"company_yaml": body["company_yaml"]},
                       headers=signed_in()).json()
    body["fingerprint"] = preview["fingerprint"]
    assert api.post("/api/v2/onboarding/company/import", json=body, headers=signed_in()).status_code == 200
    changed = copy.copy(body)
    changed["company_yaml"] = changed["company_yaml"].replace("Acme Finance", "Another Company")
    changed["fingerprint"] = api.post("/api/v2/onboarding/company/preview",
                                      json={"company_yaml": changed["company_yaml"]}, headers=signed_in()).json()["fingerprint"]
    assert api.post("/api/v2/onboarding/company/import", json=changed, headers=signed_in()).status_code == 409
    assert api.get("/api/v2/config", headers=signed_in()).json()["company_name"] == "Acme Finance"


def test_import_never_replaces_an_existing_paused_employee(environment):
    api = environment()
    config = {"name": "bookkeeping", "status": "paused", "instructions": "Keep the existing employee unchanged"}
    with api.app.state.store.transaction() as c:
        H.sync_registry(c, {**SEED, "bookkeeping": config}, PEOPLE)
        c.execute("INSERT INTO bot_config(bot,config_json,operator,repo) VALUES(?,?,?,?)",
                  ("bookkeeping", encode(config), "owner", "emp-bookkeeping"))
    original = rows(api, "SELECT config_json FROM bot_config WHERE bot='bookkeeping'")
    body = {"company_yaml": company_text()}
    body["fingerprint"] = api.post("/api/v2/setup/company/preview", json=body, headers=signed_in()).json()["fingerprint"]
    assert api.post("/api/v2/setup/company/import", json=body, headers=signed_in()).status_code == 409
    assert rows(api, "SELECT config_json FROM bot_config WHERE bot='bookkeeping'") == original


def test_install_bootstrap_uses_selected_team_once_and_never_falls_back_to_sample(tmp_path):
    from clients.environments import seed_registry
    seed_registry(tmp_path, "Owner", OWNER_EMAIL,
                  {"company_name": "Acme Finance", "app_name": "Tico", "assistant_name": "Assistant"})
    settings = settings_for(tmp_path, company_file_data=starter.pack(company_text()), sample_company=True)
    app = create_app(settings)
    app.state.store.initialize()
    app.state.store.seed()
    with TestClient(app) as api:
        assert rows(api, "SELECT display_name FROM bots WHERE slug='bookkeeping'")[0]["display_name"] == "Acme Bookkeeper"
        assert not rows(api, "SELECT slug FROM bots WHERE slug IN ('builder','head-of-product')")
        machine(api)
        assert rows(api, "SELECT state FROM bots WHERE slug='bookkeeping'")[0]["state"] == "paused"
        initial = api.get("/api/v2/setup", headers=signed_in()).json()["company_import"]
        initial_bots = rows(api, "SELECT slug,display_name,state FROM bots ORDER BY slug")
    with TestClient(create_app(settings)) as api:
        assert api.get("/api/v2/setup", headers=signed_in()).json()["company_import"] == initial
        assert rows(api, "SELECT slug,display_name,state FROM bots ORDER BY slug") == initial_bots
    settings.company_file_data = starter.pack(company_text().replace("Acme Finance", "Another Company"))
    with pytest.raises(Problem, match="already set up"):
        with TestClient(create_app(settings)):
            pass
