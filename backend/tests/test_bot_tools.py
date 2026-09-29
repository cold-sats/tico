"""The Tools row on a bot's page: the route's shape, that no secret can reach it, that a runner from
before the report still gets a row, and that a private bot's tools stay private (docs/creating-bots.md)."""

import json

from backend.tests.test_api import api, assign, get, headers, post, ready, runner  # noqa: F401  (fixtures)

RUNTIMES = {"codex": {"installed": True, "authenticated": "ready"}}
TOOLS = [
    {"service": "posthog", "identity": "PostHog project 12345 (US), personal key", "can": ["read"],
     "scope": {"project": "12345"}, "env": "POSTHOG_KEY", "note": "funnels only", "credential": "missing"},
    {"service": "slack", "identity": "Acme workspace", "can": ["read", "post"],
     "scope": {"channels": ["#ops", "#launch"]}, "env": "SLACK_TOKEN", "credential": "present"},
    {"service": "meeting-notes", "can": ["use"], "credential": "not-declared"},
]


def configure(api, bot="ops"):
    with api.app.state.store.transaction() as c:
        c.execute("UPDATE bot_config SET config_json=?,repo=? WHERE bot=?",
                  (json.dumps({"name": bot, "runtime": "codex", "model": "gpt-6-luna", "reasoning_effort": "high"}),
                   "acme-co/emp-" + bot, bot))


def report(api, machine, bot, tools):
    row = {"ready": True, "runtime": "codex", "model": "gpt-6-luna", "repository_present": True,
           "configuration_valid": True, "problems": [], **({"tools": tools} if tools is not None else {})}
    return api.post("/api/v2/runners/heartbeat", headers=headers(machine["token"]), json={
        "version": "test", "platform": "test",
        "readiness": {"schema_version": 1, "runtimes": RUNTIMES, "bots": {bot: row}}})


def tools_of(api, bot="ops", who="ana-test"):
    return get(api, f"bots/{bot}/tools", token=who)


def test_the_row_lists_the_model_the_repository_and_each_declared_tool(api):
    configure(api)
    machine = runner(api)
    assign(api, machine, "ops")
    assert report(api, machine, "ops", TOOLS).status_code == 200
    page = tools_of(api)
    assert set(page) == {"bot", "tools", "computer", "online", "reported_at"}
    assert page["computer"] == "Test Mac" and page["online"] is True
    by_id = {t["id"]: t for t in page["tools"]}
    assert [t["id"] for t in page["tools"]] == ["model", "repo", "posthog", "slack", "meeting-notes"]
    assert all({"id", "service", "name", "logo_key", "identity", "can", "scope", "note", "status"} <= set(t)
               for t in page["tools"])
    model = by_id["model"]
    assert (model["name"], model["identity"], model["logo_key"], model["status"]) == ("Codex", "openai/gpt-6-luna", "openai", "ready")
    assert model["scope"] == {"effort": "high"}
    assert by_id["repo"]["identity"] == "acme-co/emp-ops" and by_id["repo"]["url"] == "https://github.com/acme-co/emp-ops"
    assert by_id["repo"]["status"] == "ready"
    posthog = by_id["posthog"]
    assert (posthog["name"], posthog["logo_key"], posthog["status"]) == ("PostHog", "posthog", "problem")
    assert posthog["problem"] == "Credential missing on Test Mac" and posthog["env"] == "POSTHOG_KEY"
    assert posthog["scope"] == {"project": "12345"} and posthog["note"] == "funnels only" and posthog["can"] == ["read"]
    assert (by_id["slack"]["status"], by_id["slack"]["scope"]) == ("ready", {"channels": ["#ops", "#launch"]})
    assert by_id["meeting-notes"]["logo_key"] is None and by_id["meeting-notes"]["status"] == "unknown"
    assert "problem" not in by_id["slack"]


def test_no_value_can_reach_the_row(api):
    configure(api)
    machine = runner(api)
    assign(api, machine, "ops")
    # A runner reports names and verbs; a field that could carry a value is refused, not stored.
    leaky = [{**TOOLS[1], "value": "xoxb-not-a-real-token"}]
    assert report(api, machine, "ops", leaky).status_code == 422
    assert report(api, machine, "ops", [{**TOOLS[1], "env": {"SLACK_TOKEN": "xoxb-not-a-real-token"}}]).status_code == 422
    assert report(api, machine, "ops", TOOLS).status_code == 200
    with api.app.state.store.read() as c:
        stored = c.execute("SELECT readiness_json FROM runners").fetchone()[0]
    for text in (api.get("/api/v2/bots/ops/tools", headers=headers()).text, stored,
                 api.get("/api/v2/operations", headers=headers()).text, api.get("/api/v2/bots", headers=headers()).text):
        assert "xoxb-not-a-real-token" not in text
    # The heartbeat copy other pages read does not carry the list at all.
    assert "tools" not in json.loads(api.get("/api/v2/operations", headers=headers()).text)["machines"][0]["readiness"]["bots"]["ops"]


def test_a_runner_from_before_the_report_yields_the_model_and_repository_only(api):
    configure(api)
    machine = runner(api)
    assign(api, machine, "ops")
    ready(api, machine, ["ops"])                            # the oldest heartbeat: a map of booleans
    page = tools_of(api)
    assert [t["id"] for t in page["tools"]] == ["model", "repo"]
    assert page["tools"][0]["status"] == "unknown"          # no runtime report to say
    assert report(api, machine, "ops", None).status_code == 200      # a structured report with no `tools` key
    assert [t["id"] for t in tools_of(api)["tools"]] == ["model", "repo"]
    assert tools_of(api)["tools"][0]["status"] == "ready"
    # A bot with no computer at all still answers.
    bare = tools_of(api, "coo")
    assert bare["computer"] is None and bare["online"] is False and bare["tools"][0]["id"] == "model"


def test_a_private_bots_tools_stay_with_the_people_who_can_see_it(api):
    machine = runner(api)
    assign(api, machine, "inbox")
    assert report(api, machine, "inbox", TOOLS).status_code == 200
    assert api.get("/api/v2/bots/inbox/tools", headers=headers("ben-test")).status_code == 403     # access: read
    assert len(tools_of(api, "inbox")["tools"]) >= 3
    assert api.get("/api/v2/bots/nobody/tools", headers=headers("ana-test")).status_code == 404
