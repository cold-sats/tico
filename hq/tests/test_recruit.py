"""HQ's recruit endpoint: strict input, template ids only, a daily spend cap, and no briefing in any log.

The model is mocked: a function in place of the ranker, or an httpx.MockTransport standing in for OpenAI.
"""
import json
import logging

import httpx
from fastapi import FastAPI
from fastapi.testclient import TestClient

from hq import recruit
from hq.limits import Limiter

CATALOG = recruit.load_catalog()
BRIEFING = "We sell to dental clinics through three resellers; Priya Natarajan runs it"
GOOD = {"department": "sales", "briefing": BRIEFING, "catalog_version": CATALOG["version"],
        "about": {"what": "Scheduling software for clinics", "sells_to": "businesses", "software": True}}
SALES = {card["template"] for card in CATALOG["cards"] if card["department"] == "sales"}
HEAD = recruit.R.head_of(CATALOG, "sales")
OTHER = sorted(SALES - {HEAD})[0]


def client(ranker=None, **options):
    app = FastAPI()
    recruit.install(app, catalog=CATALOG, ranker=ranker, **options)
    return TestClient(app, client=("203.0.113.9", 5000))


def test_only_a_strictly_valid_request_is_answered():
    api = client()
    assert api.post("/v1/recruit", json=GOOD).status_code == 200
    bad = [{**GOOD, "department": "catering"}, {**GOOD, "briefing": "x" * 501}, {**GOOD, "extra": 1},
           {**GOOD, "about": {**GOOD["about"], "what": "x" * 501}}, {**GOOD, "about": {**GOOD["about"], "sells_to": "aliens"}},
           {**GOOD, "about": {**GOOD["about"], "software": "yes"}}, {**GOOD, "about": {**GOOD["about"], "city": "Oslo"}},
           {**GOOD, "install_id": "not-a-uuid"}, {**GOOD, "catalog_version": "../../etc"}, {**GOOD, "briefing": 7},
           {k: v for k, v in GOOD.items() if k != "department"}, ["sales"]]
    for body in bad:
        refused = api.post("/v1/recruit", json=body)
        assert refused.status_code == 422 and refused.json() == {"error": "invalid"}, body   # nothing echoed back
    assert api.post("/v1/recruit", content=b"{not json").status_code == 422
    assert api.post("/v1/recruit", content=json.dumps({**GOOD, "briefing": "x" * 5000}).encode()).status_code == 422


def test_the_model_answer_is_cut_to_the_departments_template_ids_with_the_head_first():
    calls = []

    def model(dept, cards, question):
        calls.append((dept["id"], sorted(card["template"] for card in cards), question))
        return {"bots": [{"template_id": OTHER, "why": "Keeps the CRM\nclean for resellers"},
                         {"template_id": "support-lead", "why": "another department"},
                         {"template_id": "rm -rf /", "why": "not a template"},
                         {"template_id": OTHER, "why": "twice"}, "garbage"],
                "suggested_default": [OTHER, "support-lead"]}
    answer = client(model).post("/v1/recruit", json=GOOD).json()
    assert calls == [("sales", sorted(SALES), {"department": "sales", "briefing": BRIEFING, "install_id": "",
                                               "about": GOOD["about"]})]
    assert answer == {"bots": [{"template_id": HEAD, "why": "Heads Sales and reports to you"},
                               {"template_id": OTHER, "why": "Keeps the CRM clean for resellers"}],
                      "suggested_default": [HEAD, OTHER], "source": "model", "catalog_version": CATALOG["version"]}
    # An answer with no usable id at all is not an answer: HQ ranks locally instead.
    local = client(lambda *a: {"bots": [{"template_id": "nope", "why": "x"}]}).post("/v1/recruit", json=GOOD).json()
    assert local["source"] == "local" and {row["template_id"] for row in local["bots"]} <= SALES


def test_the_openai_request_lists_only_the_departments_ids_and_is_not_stored():
    sent = []

    def openai(request):
        sent.append(json.loads(request.content))
        text = json.dumps({"bots": [{"template_id": HEAD, "why": "Runs the reseller pipeline"}],
                           "suggested_default": [HEAD]})
        return httpx.Response(200, json={"output": [{"type": "message", "content": [{"type": "output_text", "text": text}]}]})
    ranker = recruit.OpenAIRanker("sk-test", transport=httpx.MockTransport(openai))
    answer = client(ranker).post("/v1/recruit", json=GOOD).json()
    assert answer["source"] == "model" and answer["bots"] == [{"template_id": HEAD, "why": "Runs the reseller pipeline"}]
    request = sent[0]
    assert request["model"] == "gpt-6-luna" and request["store"] is False
    schema = request["text"]["format"]["schema"]["properties"]
    assert set(schema["bots"]["items"]["properties"]["template_id"]["enum"]) == SALES == set(schema["suggested_default"]["items"]["enum"])


def test_the_daily_cap_and_a_missing_key_fall_back_to_local_ranking():
    calls = []

    def model(dept, cards, question):
        calls.append(question["briefing"])
        return {"bots": [{"template_id": HEAD, "why": "Model says so"}], "suggested_default": []}
    day = ["2026-09-29"]
    api = client(model, cap=recruit.DailyCap(2, clock=lambda: day[0]))
    sources = [api.post("/v1/recruit", json={**GOOD, "briefing": "answer %d" % i}).json()["source"] for i in range(4)]
    assert sources == ["model", "model", "local", "local"] and len(calls) == 2
    # A repeated question is answered from memory and costs nothing.
    assert api.post("/v1/recruit", json={**GOOD, "briefing": "answer 0"}).json()["source"] == "model"
    assert len(calls) == 2
    day[0] = "2026-09-30"                                              # a new UTC day, a new allowance
    assert api.post("/v1/recruit", json={**GOOD, "briefing": "answer 9"}).json()["source"] == "model"
    # No OPENAI_API_KEY: local ranking, the head first, and still ids only.
    local = client(None).post("/v1/recruit", json=GOOD).json()
    assert local["source"] == "local" and local["bots"][0]["template_id"] == HEAD
    assert all(set(row) == {"template_id", "why"} and row["template_id"] in SALES for row in local["bots"])


def test_no_briefing_reaches_a_log_even_when_the_model_fails_with_it(caplog):
    def model(dept, cards, question):
        raise RuntimeError("upstream said: " + question["briefing"] + question["about"]["what"])
    caplog.set_level(logging.DEBUG)
    answer = client(model).post("/v1/recruit", json={**GOOD, "install_id": "6f1c2a9e-3b7d-4c58-9a10-2d4e8b7f5a63"})
    assert answer.status_code == 200 and answer.json()["source"] == "local"
    assert "RuntimeError" in caplog.text
    for secret in ("dental", "Priya", "Scheduling software", "6f1c2a9e"):
        assert secret not in caplog.text


def test_rate_limits_per_address_and_per_install():
    install = "6f1c2a9e-3b7d-4c58-9a10-2d4e8b7f5a63"
    api = client(per_address=Limiter(limit=3), per_install=Limiter(limit=1))
    assert api.post("/v1/recruit", json={**GOOD, "install_id": install}).status_code == 200
    assert api.post("/v1/recruit", json={**GOOD, "install_id": install}).status_code == 429
    assert api.post("/v1/recruit", json=GOOD).status_code == 200                 # no id: only the address counts
    assert api.post("/v1/recruit", json=GOOD).status_code == 429
