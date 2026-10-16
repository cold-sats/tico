"""The company's check model (backend/providers.py `check_choice`): what a review or check subtask runs on when it
names none. It follows the owner's order and never picks the provider the work was written on."""

import pytest

from backend import providers as P
from backend.store import H
from backend.tests.test_api import api, get  # noqa: F401  (the fixture)

COMPANY = {"enabled": ["anthropic", "xai", "openai"], "runtime": "claude", "model": "claude-opus-5-5"}


def test_the_owners_order_wins_and_the_authors_provider_is_skipped():
    record = P._record({**COMPANY, "check_models": P.normalize_check_models(["grok", "codex:gpt-6.1-sol"], COMPANY)})
    assert [row["model"] for row in P.check_order(record)] == ["grok-4.6", "gpt-6.1-sol"]
    # Written on Claude: Grok first. Written on Grok: never Grok, so Codex.
    assert P.check_choice(record, "anthropic")["model"] == "grok-4.6"
    assert P.check_choice(record, "grok-4.6") == {"runtime": "codex", "model": "gpt-6.1-sol", "provider": "openai"}
    assert P.check_choice(record, "grok")["runtime"] == "codex"
    # Grok is not signed in on any computer: the next in order.
    assert P.check_choice(record, "claude", available={"codex", "claude"})["model"] == "gpt-6.1-sol"


def test_with_no_order_the_enabled_providers_order_stands_in():
    record = P._record(COMPANY)
    assert [row["runtime"] for row in P.check_order(record)] == ["claude", "grok", "codex"]
    # The company default rides its own runtime, as for fallbacks.
    assert P.check_order(record)[0]["model"] == "claude-opus-5-5"
    assert P.check_choice(record, "claude-opus-5-5")["runtime"] == "grok"
    # Turning auto fallback off does not take the check model away.
    assert P.check_choice({**record, "auto_fallback": False}, "anthropic")["runtime"] == "grok"


def test_no_other_provider_is_refused_not_answered_with_the_authors_own():
    record = P._record({"enabled": ["anthropic"], "runtime": "claude", "model": "claude-opus-5-5"})
    with pytest.raises(P.ProviderError) as refused:
        P.check_choice(record, "claude")
    assert refused.value.status == 409 and "other than Anthropic" in refused.value.detail
    # A provider turned off after it was put in the order drops out.
    stale = P._record({**record, "check_models": [{"runtime": "grok", "model": "grok-4.6", "provider": "xai"}]})
    assert P.check_order(stale) == [{"runtime": "claude", "model": "claude-opus-5-5", "provider": "anthropic"}]


@pytest.mark.parametrize("choice", ["gemini", "claude-opus-5"])
def test_a_choice_the_company_cannot_run_is_refused(choice):
    with pytest.raises(P.ProviderError) as refused:
        P.normalize_check_models([choice], COMPANY)
    assert refused.value.code == "check_model" and refused.value.status == 422


def save(api, **extra):
    view = get(api, "providers")
    return api.put("/api/v2/providers", json={**{k: COMPANY[k] for k in ("enabled", "runtime", "model")},
                                               "expected_revision": view["revision"], **extra},
                   headers={"Authorization": "Bearer ana-test", "Idempotency-Key": H.new_id()})


def test_the_owner_saves_the_order_and_a_save_that_omits_it_keeps_it(api):
    assert save(api).json()["check_models"] == []
    view = save(api, check_models=["grok", "codex"]).json()
    assert [row["runtime"] for row in view["check_models"]] == ["grok", "codex"]
    assert [row["model"] for row in view["check_order"]] == ["grok-4.6", "gpt-6-luna"]
    assert [row["runtime"] for row in save(api).json()["check_models"]] == ["grok", "codex"]
    refused = save(api, check_models=["gemini"])
    assert refused.status_code == 422
    assert refused.json()["error"]["detail"] == "Check model 'gemini': its provider (google) is not enabled"
    with api.app.state.store.read() as c:
        event = c.execute("SELECT detail_json FROM events WHERE action='providers.updated' ORDER BY ts DESC LIMIT 1").fetchone()
    assert '"check_models"' in event[0]
    assert save(api, check_models=[]).json()["check_models"] == []
