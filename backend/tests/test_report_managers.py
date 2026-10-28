"""A manager bot changes its direct reports as itself (backend/report_managers.py, docs/permissions.md): its model, its task
model, and its name and description, each recorded with via `report_manager`. The owner's team rule and the manager's own
switch turn that off. A person who manages the report sees and undoes such a change. Routines and the hub tools follow it.
"""

from backend import automations
from backend.auth import Identity
from backend.tests.test_api import api, get, headers, post, put  # noqa: F401  (api is a fixture)
from backend.tests.test_mcp import call

HAIKU = {"harness": "claude", "model": "claude-haiku-5-5", "effort": "low"}


def bot(api, slug, reports_to=None):
    """A bot the owner makes; the returned token is its agent credential, which acts as the bot."""
    post(api, "bots", {"slug": slug, "display_name": slug.title(), "description": "A test bot.",
                       "reports_to": reports_to, "status": "active", "repo": "emp-" + slug, "thread_mode": "personal",
                       "model": "hermes-profile", "effort": "as-configured", "harness": "hermes", "operator": "ana",
                       "owners": ["ana"], "runner_id": None})
    return post(api, f"bots/{slug}/agent-credential", {})["token"]


def revision(api, slug, token="ana-test"):
    return get(api, f"bots/{slug}", token=token)["revision"]


def task_model(api, token, slug="counsel", expected=200):
    return post(api, f"bots/{slug}/task-model", {"task_model": HAIKU, "expected_revision": revision(api, slug)},
                token=token, expected=expected)


def changes_to(api, bot_slug, field):
    return [row for row in get(api, "settings/history")["changes"] if row["bot"] == bot_slug and row["field"] == field]


def test_a_manager_bot_changes_its_reports_task_model_as_itself(api):
    lead = bot(api, "lead")
    bot(api, "counsel", reports_to="lead")
    task_model(api, lead)
    [row] = changes_to(api, "counsel", "task_model")
    assert row["via"] == "report_manager" and row["actor"] == "bot:lead"
    assert row["after"]["model"] == "claude-haiku-5-5"


def test_a_manager_bot_changes_only_its_reports_name_and_description(api):
    lead = bot(api, "lead")
    bot(api, "counsel", reports_to="lead")
    post(api, "bots/counsel/definition", {"display_name": "Counsel Two", "description": "Reviews the NDAs.",
                                          "expected_revision": revision(api, "counsel")}, token=lead)
    [row] = changes_to(api, "counsel", "identity")
    assert row["via"] == "report_manager"
    assert row["after"] == {"display_name": "Counsel Two", "description": "Reviews the NDAs."}
    assert get(api, "bots/counsel")["display_name"] == "Counsel Two"
    # Its status and its place in the org stay the people's to change.
    post(api, "bots/counsel/definition", {"status": "paused", "expected_revision": revision(api, "counsel")},
         token=lead, expected=403)
    post(api, "bots/counsel/definition", {"reports_to": None, "expected_revision": revision(api, "counsel")},
         token=lead, expected=403)


def test_a_manager_bot_changes_only_its_direct_reports(api):
    lead = bot(api, "lead")
    bot(api, "counsel", reports_to="lead")
    bot(api, "junior", reports_to="counsel")
    bot(api, "stranger")
    for slug in ("junior", "lead", "stranger"):
        task_model(api, lead, slug=slug, expected=403)
    assert changes_to(api, "junior", "task_model") == []


def test_the_owners_team_rule_turns_the_managers_off_for_every_bot(api):
    lead = bot(api, "lead")
    bot(api, "counsel", reports_to="lead")
    put(api, "access/rules", {"managers_manage_reports": False})
    task_model(api, lead, expected=403)
    put(api, "access/rules", {"managers_manage_reports": False}, token="ben-test", expected=403)
    put(api, "access/rules", {"managers_manage_reports": True})
    task_model(api, lead)


def test_a_managers_own_switch_is_set_by_a_person_who_manages_it(api):
    lead = bot(api, "lead")
    bot(api, "counsel", reports_to="lead")

    def switch(value, token="ana-test", expected=200):
        return post(api, "bots/lead/manages-reports", {"manages_reports": value,
                    "expected_revision": revision(api, "lead")}, token=token, expected=expected)

    assert switch(False)["manages_reports"] is False
    task_model(api, lead, expected=403)
    switch(True, token=lead, expected=403)              # a bot cannot set its own switch
    switch(True, token="cara-test", expected=403)       # nor can someone who does not manage it
    switch(True)
    task_model(api, lead)
    assert [row["after"] for row in changes_to(api, "lead", "manages_reports")] == [True, False]   # newest first


def test_a_person_who_manages_the_report_sees_and_undoes_the_managers_change(api):
    lead = bot(api, "lead", reports_to="human:ben")
    bot(api, "counsel", reports_to="lead")
    task_model(api, lead)
    [row] = [c for c in get(api, "settings/history", token="ben-test")["changes"] if c["bot"] == "counsel"]
    assert row["via"] == "report_manager" and row["can_undo"] is True
    assert get(api, "settings/history", token="ben-test")["transitions"] == []
    assert get(api, "settings/history", token="cara-test")["changes"] == []
    undo = f"settings/history/{row['id']}/undo"
    post(api, undo, {"expected_revision": revision(api, "counsel")}, token="cara-test", expected=403)
    post(api, undo, {"expected_revision": revision(api, "counsel", "ben-test")}, token="ben-test")
    assert get(api, "bots/counsel")["task_model"] is None
    assert [r["undone_at"] is not None for r in changes_to(api, "counsel", "task_model") if r["id"] == row["id"]] == [True]


def test_a_routine_a_manager_bot_reaches_follows_both_switches(api):
    lead = bot(api, "lead")
    bot(api, "counsel", reports_to="lead")
    store = api.app.state.store
    flow, who = {"owner": "bot:counsel"}, Identity("bot:lead", "bot")
    with store.read() as c:
        assert automations.may_change(c, who, flow)
    post(api, "bots/lead/manages-reports", {"manages_reports": False, "expected_revision": revision(api, "lead")})
    with store.read() as c:
        assert not automations.may_change(c, who, flow)
    post(api, "bots/lead/manages-reports", {"manages_reports": True, "expected_revision": revision(api, "lead")})
    team_off = {"managers_manage_reports": False}
    put(api, "access/rules", team_off)
    with store.read() as c:
        assert not automations.may_change(c, who, flow)


def test_the_hub_tools_and_the_model_route_work_for_a_manager_bot(api):
    lead = bot(api, "lead")
    bot(api, "counsel", reports_to="lead")
    err, out = call(api, "hub_bot_update", {"slug": "counsel", "display_name": "Counsel Lead",
                                             "description": "Reviews contracts."}, token=lead)
    assert not err, out
    assert changes_to(api, "counsel", "identity")[0]["via"] == "report_manager"
    # The model route: the manager changes its report's model (no computer yet, so nothing else blocks it). A bot that
    # manages no one else is refused.
    stranger = bot(api, "stranger")
    body = {"model": "claude-haiku-5-5", "expected_revision": revision(api, "counsel")}
    r = api.post("/api/v2/bots/counsel/model", json=body, headers=headers(stranger))
    assert r.status_code == 403, r.text
    r = api.post("/api/v2/bots/counsel/model", json=body, headers=headers(lead))
    assert r.status_code == 200, r.text
    assert any(row["via"] == "report_manager" and row["after"]["model"] == "claude-haiku-5-5"
               for row in changes_to(api, "counsel", "model"))
    err, out = call(api, "hub_bot_model", {"bot": "counsel", "model": "claude-sonnet-5-5"}, token=lead)
    assert not err, out
    assert any(row["after"]["model"] == "claude-sonnet-5-5" and row["via"] == "report_manager"
               for row in changes_to(api, "counsel", "model"))
