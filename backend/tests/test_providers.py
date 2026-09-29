"""The provider choice (backend/providers.py): stored, revisioned, seeded from the environment,
and the only thing that decides a bot's runtime and model when the bot names none."""

import re
from pathlib import Path

import pytest

from backend import providers as P
from backend.tests.test_api import api  # noqa: F401  (the fixture)

ROOT = Path(__file__).resolve().parents[2]


def test_resolution_order_bot_then_company_then_first_provider_then_error():
    none = P._record({})
    company = P._record({"enabled": ["anthropic", "openai"], "runtime": "codex", "model": "gpt-6-sol"})
    assert P.resolve(company, {"runtime": "claude", "model": "claude-opus-5"}) == ("claude", "claude-opus-5")
    assert P.resolve(company, {"model": "claude-opus-5-5"}) == ("claude", "claude-opus-5-5")
    assert P.resolve(company, {"runtime": "default", "model": "default"}) == ("codex", "gpt-6-sol")
    assert P.resolve(company, {"runtime": "claude"}) == ("claude", "claude-opus-5")
    first = P._record({"enabled": ["google", "openai"]})
    assert P.resolve(first, {}) == ("gemini", "gemini-3.8-flash")
    with pytest.raises(P.NoProvider) as refused:
        P.resolve(none, {})
    assert "Settings > AI providers" in refused.value.detail and refused.value.status == 409


def test_choice_validation():
    assert P.complete_choice("openai,anthropic") == ("codex", "gpt-6-luna")
    assert P.complete_choice(["anthropic"], model="claude-opus-5-5") == ("claude", "claude-opus-5-5")
    with pytest.raises(P.ProviderError):
        P.complete_choice(["anthropic"], model="gpt-6-sol")           # its provider is not enabled
    with pytest.raises(P.ProviderError):
        P.complete_choice(["anthropic"], runtime="claude", model="gpt-6-sol")
    with pytest.raises(P.ProviderError):
        P.complete_choice(["anthropic"], model="gpt-5.6-sol")         # retired
    with pytest.raises(P.ProviderError):
        P.normalize_enabled("anthropic,nobody")


def test_every_provider_has_a_recommended_model_and_the_catalog_has_no_orphans():
    for row in P.PROVIDERS:
        assert P.recommended(row["id"])["runtime"] == row["runtime"]
    assert all(m["provider"] in P.PROVIDER_BY_ID or m["provider"] == "" for m in P.MODEL_CATALOG)


def test_no_template_or_source_hardcodes_a_vendor_default():
    """Templates carry no runtime or model; the catalog in providers.py is the only list."""
    for path in (ROOT / "templates").rglob("*.yaml"):
        assert not re.search(r"^\s*(runtime|model):", path.read_text(), re.M), path
    pattern = re.compile(r"""get\(\s*["']runtime["']\s*,\s*["'](codex|claude|gemini|grok|pi)["']\)|"""
                         r"""or\s+["'](codex|claude)["']\s*$|DEFAULT_MODEL\s*=""")
    for name in ("backend/execution.py", "backend/views.py", "backend/onboarding.py",
                 "runner/service.py", "clients/preflight.py"):
        for number, line in enumerate((ROOT / name).read_text().splitlines(), 1):
            assert not pattern.search(line), f"{name}:{number}: {line.strip()}"


def test_a_claimed_attempt_carries_the_company_default_for_a_bot_that_names_none(api):
    """Found by the Linux rehearsal: onboarding creates bots that follow the company default, and
    the runner got an empty runtime from the claim, so no turn ever started."""
    from backend.store import encode
    from backend.tests.test_api import claim, post, put, runner, assign, ready
    put(api, "providers", {"enabled": ["openai"], "runtime": "codex", "model": "gpt-6-luna", "expected_revision": 0})
    with api.app.state.store.transaction() as c:
        c.execute("UPDATE bot_config SET config_json=? WHERE bot='ops'", (encode({"name": "ops", "status": "active"}),))
    r = runner(api)
    assign(api, r, "ops")
    ready(api, r, ["ops"])
    post(api, "chat/ops", {"text": "Say hello."})
    config = claim(api, r)["config"]
    assert (config["runtime"], config["model"]) == ("codex", "gpt-6-luna")


def test_providers_without_a_cli_run_on_the_catch_all_through_openrouter():
    for name in ("deepseek", "moonshot", "meta", "mistral", "openrouter"):
        assert P.PROVIDER_BY_ID[name]["runtime"] == "pi" and P.PROVIDER_BY_ID[name]["harness"] == "pi"
        assert P.recommended(name)["runtime"] == "pi", name
    assert P.PROVIDER_BY_ID["xai"]["runtime"] == "grok"           # xAI has its own CLI
    assert P.PROVIDER_BY_RUNTIME["pi"]["id"] == "openrouter"      # a bot that names only `pi`
    # OpenRouter serves every pi model; a vendor's own provider serves only its models.
    assert {m["id"] for m in P.provider_models("openrouter")} == {m["id"] for m in P.MODEL_CATALOG if m["runtime"] == "pi"}
    assert {m["provider"] for m in P.provider_models("moonshot")} == {"moonshot"}


def test_a_company_with_only_kimi_gets_kimi_and_cannot_pick_another_vendors_model():
    assert P.complete_choice(["moonshot"]) == ("pi", "kimi-k3")
    assert P.complete_choice(["moonshot"], runtime="pi") == ("pi", "kimi-k3")
    assert P.complete_choice(["openrouter"], model="devstral-2512") == ("pi", "devstral-2512")
    with pytest.raises(P.ProviderError):
        P.complete_choice(["moonshot"], model="llama-4-maverick")
    with pytest.raises(P.ProviderError):
        P.complete_choice(["openai"], runtime="pi")               # nothing assumed: no provider, no runtime


def test_every_pi_model_maps_to_an_openrouter_id():
    from runner.hosts.pi import MODELS
    assert {m["id"] for m in P.MODEL_CATALOG if m["runtime"] == "pi"} == set(MODELS)
    assert all("/" in target for target in MODELS.values())


def test_cursor_is_a_provider_with_its_own_harness_and_runtime():
    row = P.PROVIDER_BY_ID["cursor"]
    assert (row["runtime"], row["harness"]) == ("cursor", "cursor-agent")
    assert P.recommended("cursor")["id"] == "cursor-auto"
    assert P.complete_choice(["cursor"]) == ("cursor", "cursor-auto")
    from runner.hosts.cursor import MODELS
    assert {m["id"] for m in P.MODEL_CATALOG if m["runtime"] == "cursor"} == set(MODELS)
