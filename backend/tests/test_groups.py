"""Groups: one model for the old teams, org groups and derived departments (backend/groups.py, docs/org-chart.md).

The migration keeps every grouping there was, the API lets owners and admins change groups while members read them,
the older `team` and `department` fields follow group membership, and access lists naming a group reach the groups
nested in it.
"""
import json

import yaml

from backend import botops_act, recruit
from backend import groups as Groups
from backend import people as P
from backend.store import H, encode
from backend.tests.test_api import api, get, headers, post  # noqa: F401  (the api fixture)
from backend.tests.test_onboarding import ASSISTANT_AGENT, ASSISTANT_CARD, BOTOPS_CARD, environment, signed_in  # noqa: F401

EVERYONE = {"everyone": True, "people": [], "teams": [], "bots": []}


def send(api, method, path, body=None, token="ana-test", expected=200):
    r = api.request(method, "/api/v2/" + path, json=body, headers=headers(token))
    assert r.status_code == expected, r.text
    return r.json()


def group(api, gid, token="ana-test"):
    return next(row for row in get(api, "groups", token=token) if row["id"] == gid)


def roster_of(api):
    with api.app.state.store.read() as c:
        return json.loads(c.execute("SELECT value_json FROM registry_metadata WHERE key='people'").fetchone()[0])


def set_roster(api, doc):
    with api.app.state.store.transaction() as c:
        c.execute("UPDATE registry_metadata SET value_json=? WHERE key='people'", (encode(doc),))


def add_bots(c, **bots):
    """{slug: (config, reports_to)}: bots straight into the database."""
    for slug, (config, reports_to) in bots.items():
        if not H.bot(c, slug):
            c.execute("INSERT INTO bots(slug,display_name,runtime,model,effort,cwd,host,state,created) "
                      "VALUES(?,?,?,?,?,'','keeper','active',?)", (slug, slug, "fake", "m", "", H.now()))
        c.execute("DELETE FROM bot_config WHERE bot=?", (slug,))
        c.execute("INSERT INTO bot_config(bot,config_json,operator,reports_to) VALUES(?,?,?,?)",
                  (slug, encode({"name": slug, **config}), "ana", reports_to))


def teams_now(api):
    """{bot: group id} as the server reads it now."""
    with api.app.state.store.read() as c:
        roster, configs = Groups._roster(c), Groups._configs(c)
        return {slug: P.team_of(slug, configs, roster) for slug in configs}


# ----------------------------------------------------------------------------- the API
def test_owners_and_admins_manage_groups_and_members_read(api):
    assert get(api, "groups", token="cara-test") == []
    body = {"name": "Marketing", "add": {"people": ["ana"], "bots": ["ops"]}}
    send(api, "POST", "groups", body, token="cara-test", expected=403)
    send(api, "PATCH", "groups/marketing", {"name": "Growth"}, token="cara-test", expected=403)
    send(api, "DELETE", "groups/marketing", token="cara-test", expected=403)
    made = send(api, "POST", "groups", body, token="ben-test")                       # Ben is an admin
    assert {k: made[k] for k in ("id", "name", "parent", "people", "bots")} == {
        "id": "marketing", "name": "Marketing", "parent": "", "people": ["ana"], "bots": ["ops"]}
    assert get(api, "groups", token="cara-test")[0]["bots"] == ["ops"]                # a member reads
    send(api, "POST", "groups", {"name": "marketing"}, expected=409)                 # a name is used once per level
    send(api, "POST", "groups", {"name": "Lost", "parent": "nowhere"}, expected=404)


def test_groups_nest_and_teammates_move_between_them(api):
    send(api, "POST", "groups", {"name": "Marketing"})
    seo = send(api, "POST", "groups", {"name": "SEO", "parent": "marketing", "add": {"people": ["cara"], "bots": ["cpo"]}})
    assert seo["parent"] == "marketing" and seo["people"] == ["cara"] and seo["bots"] == ["cpo"]
    send(api, "POST", "groups", {"name": "Sales"})
    # A teammate added to a group leaves the one it was in.
    moved = send(api, "PATCH", "groups/sales", {"add": {"people": ["cara"], "bots": ["cpo", "ops"]}})
    assert moved["people"] == ["cara"] and moved["bots"] == ["cpo", "ops"]
    assert group(api, "seo")["people"] == [] and group(api, "seo")["bots"] == []
    send(api, "PATCH", "groups/sales", {"remove": {"people": ["cara"], "bots": ["ops"]}})
    assert group(api, "sales")["people"] == [] and group(api, "sales")["bots"] == ["cpo"]
    # Rename and move; nothing goes under itself or a group inside it; only real, live teammates go in.
    send(api, "PATCH", "groups/seo", {"name": "Search", "parent": "sales"})
    assert (group(api, "seo")["name"], group(api, "seo")["parent"]) == ("Search", "sales")
    send(api, "PATCH", "groups/sales", {"parent": "seo"}, expected=422)
    send(api, "PATCH", "groups/seo", {"parent": ""})
    assert group(api, "seo")["parent"] == ""
    send(api, "PATCH", "groups/seo", {"add": {"people": ["nobody"]}}, expected=404)
    send(api, "PATCH", "groups/seo", {"add": {"bots": ["nobody"]}}, expected=404)
    send(api, "PATCH", "groups/nowhere", {"name": "X"}, expected=404)
    # The Assistant and the other built-ins stay outside groups.
    for built_in in ("coo", "botops"):
        send(api, "PATCH", "groups/seo", {"add": {"bots": [built_in]}}, expected=404 if built_in == "botops" else 422)


def test_deleting_a_group_moves_its_teammates_and_groups_up(api):
    send(api, "POST", "groups", {"name": "Marketing"})
    send(api, "POST", "groups", {"name": "SEO", "parent": "marketing", "add": {"people": ["cara"], "bots": ["cpo"]}})
    send(api, "POST", "groups", {"name": "Links", "parent": "seo", "add": {"bots": ["ops"]}})
    send(api, "DELETE", "groups/seo")
    assert group(api, "links")["parent"] == "marketing"
    assert group(api, "marketing")["people"] == ["cara"] and group(api, "marketing")["bots"] == ["cpo"]
    send(api, "DELETE", "groups/marketing")                                           # the last one up: no group at all
    assert group(api, "links")["parent"] == "" and get(api, "groups")[0]["bots"] == ["ops"]
    assert teams_now(api)["cpo"] is None and roster_of(api)["people"][2]["team"] == ""


def test_botops_changes_groups_as_the_person_who_asked(api):
    for method, path in (("POST", "groups"), ("PATCH", "groups/marketing"), ("DELETE", "groups/marketing")):
        assert botops_act.classify(method, "/api/v2/" + path) == "do"


# ----------------------------------------------------------------------------- what still reads a bot's team and department
def test_the_older_team_and_department_fields_follow_group_membership(api):
    send(api, "POST", "groups", {"name": "Marketing", "add": {"bots": ["ops"]}})
    send(api, "POST", "groups", {"name": "Customer Support", "parent": "marketing",
                                 "add": {"people": ["cara"], "bots": ["cpo"]}})
    chart = get(api, "org")
    bots = {row["id"]: row for row in chart["bots"]}
    assert (bots["ops"]["team"], bots["ops"]["department"]) == ("marketing", "Marketing")
    assert (bots["cpo"]["team"], bots["cpo"]["department"]) == ("customer-support", "Customer Support")
    assert (bots["finance"]["team"], bots["finance"]["department"]) == ("", "")
    assert {p["id"]: p["team"] for p in chart["people"]}["cara"] == "customer-support"
    assert {g["id"]: g["parent"] for g in chart["org_groups"]} == {"marketing": "", "customer-support": "marketing"}
    assert get(api, "bots/cpo")["team"] == "customer-support"
    # `hub team show --team marketing` is the group and the ones in it.
    inside = get(api, "org?team=marketing")
    assert {row["id"] for row in inside["bots"]} == {"ops", "cpo"} and {g["id"] for g in inside["org_groups"]} == {
        "marketing", "customer-support"}


def test_naming_a_group_in_an_access_list_reaches_the_groups_nested_in_it(api):
    send(api, "POST", "groups", {"name": "Marketing"})
    send(api, "POST", "groups", {"name": "SEO", "parent": "marketing", "add": {"people": ["cara"]}})
    current = get(api, "bots/finance/access")
    send(api, "PUT", "bots/finance/access", {"see": EVERYONE, "write": EVERYONE, "revision": current["revision"],
                                              "read": {"everyone": False, "people": [], "teams": ["marketing"], "bots": []}})
    assert get(api, "bots/finance", token="cara-test")["access"]["read"] is True          # in SEO, which is in Marketing
    send(api, "PATCH", "groups/seo", {"parent": ""})
    assert get(api, "bots/finance", token="cara-test")["access"]["read"] is False
    assert {"id": "seo", "name": "SEO"} in get(api, "bots/finance/access")["teams"]


def test_a_person_primary_for_a_group_is_primary_for_the_bots_in_the_groups_under_it():
    roster = P.load({"people": [{"id": "ana", "primary_for": ["*"]}, {"id": "ben", "primary_for": ["marketing"]},
                                {"id": "cal", "primary_for": ["seo"]}, {"id": "dee"}],
                     "org_groups": {"marketing": {"name": "Marketing"}, "seo": {"name": "SEO", "parent": "marketing"}}})
    employees = {"cmo": {"team": "marketing"}, "writer": {"team": "seo"}, "loose": {"team": ""}}
    users = lambda slug: {p["id"] for p in P.primary_users(slug, roster, employees)}       # noqa: E731
    assert users("cmo") == {"ana", "ben"} and users("writer") == {"ana", "ben", "cal"} and users("loose") == {"ana"}
    assert P.group_chain("seo", roster) == ["seo", "marketing"] and P.group_and_below("marketing", roster) == {"marketing", "seo"}
    assert P.bot_departments(employees, roster) == {"cmo": "Marketing", "writer": "SEO"}
    # A group that leads back to itself, or under one that is not there, is no child.
    odd = P.load({"org_groups": {"a": {"parent": "b"}, "b": {"parent": "a"}, "c": {"parent": "gone"}}})
    assert odd["org_groups"]["c"]["parent"] == "" and not (odd["org_groups"]["a"]["parent"] and odd["org_groups"]["b"]["parent"])


# ----------------------------------------------------------------------------- the migration
def migrated(api, doc, bots):
    with api.app.state.store.transaction() as c:
        c.execute("DELETE FROM bot_config")
        c.execute("UPDATE registry_metadata SET value_json=? WHERE key='people'", (encode(doc),))
        add_bots(c, **bots)
    with api.app.state.store.transaction() as c:
        return Groups.migrate(c, api.app.state.store.settings)


def test_teams_org_groups_and_person_teams_become_groups_and_no_bot_changes_group(api):
    doc = {"default_user": "ana", "teams": {"marketing": {"root": "cmo"}, "product": {"root": "cpo"}},
           "org_groups": {"product": {"name": "Product team", "reports_to": "ana"}, "ops": {"name": "Operations"}},
           "people": [{"id": "ana", "email": "ana@acme.example", "team": "marketing"},
                      {"id": "ben", "email": "ben@acme.example", "team": "Success Team", "reports_to": "ana"},
                      {"id": "cara", "email": "cara@acme.example", "team": "product"}]}
    bots = {"cmo": ({}, None), "seo": ({}, "cmo"), "cpo": ({"team": "product"}, "human:ana"), "design": ({}, "cpo"),
            "coach": ({}, None), "planner": ({"team": ""}, "cmo")}
    with api.app.state.store.transaction() as c:
        c.execute("DELETE FROM bot_config")
        c.execute("UPDATE registry_metadata SET value_json=? WHERE key='people'", (encode(doc),))
        add_bots(c, **bots)
        roster, configs = Groups._roster(c), Groups._configs(c)
        before = {slug: P.team_of(slug, configs, roster) for slug in configs}
    assert before == {"cmo": "marketing", "seo": "marketing", "cpo": "product", "design": "product", "coach": None,
                      "planner": None}
    with api.app.state.store.transaction() as c:
        assert Groups.migrate(c, api.app.state.store.settings) is True
    assert teams_now(api) == before                                        # nobody changed group
    stored = roster_of(api)
    assert "teams" not in stored and stored["groups_migrated"] is True
    assert set(stored["org_groups"]) == {"product", "ops", "marketing", "success-team"}
    assert stored["org_groups"]["product"] == {"name": "Product team", "reports_to": "ana"}     # `reports_to` is not touched
    assert stored["org_groups"]["success-team"] == {"name": "Success Team"}
    assert {p["id"]: p["team"] for p in stored["people"]} == {"ana": "marketing", "ben": "success-team", "cara": "product"}
    with api.app.state.store.read() as c:
        assert json.loads(c.execute("SELECT config_json FROM bot_config WHERE bot='coach'").fetchone()[0])["team"] == ""
        assert c.execute("SELECT team FROM bot_config WHERE bot='design'").fetchone()[0] == "product"
        assert P.by_team(Groups._roster(c))["success-team"] == ["ben"]
        assert json.loads(H.human(c, "ben")["teams_json"]) == ["success-team"]
    # Idempotent: again changes nothing, even when the flag is cleared.
    with api.app.state.store.transaction() as c:
        assert Groups.migrate(c, api.app.state.store.settings) is False
    once = roster_of(api)
    set_roster(api, {k: v for k, v in once.items() if k != "groups_migrated"})
    with api.app.state.store.transaction() as c:
        assert Groups.migrate(c, api.app.state.store.settings) is True
    assert roster_of(api) == once and teams_now(api) == before


def test_a_team_with_no_groups_gets_one_per_template_group_with_its_lead_in_it(api):
    """A team with no org groups and bots the team builder made from templates in four groups: four groups, each with its lead."""
    homes = recruit.template_groups(api.app.state.store.settings)
    lead = {"marketing": "marketing-lead", "engineering": "engineering-lead", "product": "product-lead",
            "support": "support-lead"}
    other = {"marketing": "content", "engineering": "docs-writer", "product": "pricing", "support": "retention"}
    bots = {"botops": ({"template": "botops"}, "human:ana"), "coo": ({"template": "assistant"}, "human:ana")}
    for dept in ("engineering", "support", "marketing", "product"):                    # in no particular order
        assert homes[lead[dept]]["id"] == dept and homes[other[dept]]["id"] == dept
        bots[lead[dept]] = ({"template": lead[dept]}, "human:ana")
        bots[other[dept]] = ({"template": other[dept]}, lead[dept])
    bots["custom"] = ({}, "human:ana")                                                 # made by hand: in no group
    bots["helper-of-custom"] = ({}, "custom")
    assert migrated(api, {"default_user": "ana", "people": [{"id": "ana", "email": "ana@acme.example"}]}, bots) is True
    stored = roster_of(api)
    assert stored["org_groups"] == {"marketing": {"name": "Marketing"}, "support": {"name": "Customer Support"},
                                    "product": {"name": "Product"}, "engineering": {"name": "Engineering"}}
    with api.app.state.store.read() as c:
        listed = {row["id"]: row for row in Groups.rows(Groups._roster(c), Groups._configs(c))}
    for dept in lead:
        assert listed[dept]["bots"] == sorted([lead[dept], other[dept]]), dept
    assert teams_now(api)["botops"] is None and teams_now(api)["coo"] is None
    assert teams_now(api)["custom"] is None and teams_now(api)["helper-of-custom"] is None
    # The department the chart shows for a bot is its group's name.
    with api.app.state.store.read() as c:
        assert P.bot_departments(Groups._configs(c), Groups._roster(c))["support-lead"] == "Customer Support"


def test_the_team_builder_makes_or_reuses_the_group_of_each_template(environment):
    def card(template, group, **more):
        return {"template": template, "slug": template, "name": template.title(), "required": False, "bootstrap": False,
                "summary": "Does " + template + ".", "owns": [], "never": [], "reasoning_effort": "high",
                "group": group, **more}
    api = environment(cards=[(ASSISTANT_CARD, ASSISTANT_AGENT), (BOTOPS_CARD, ""), (card("seo", "marketing"), ""),
                             (card("brand", "marketing"), ""), (card("tickets", "support"), ""), (card("misc", ""), "")])
    (recruit.Path(api.app.state.store.settings.catalog_dir).parent / "groups.yaml").write_text(yaml.safe_dump({"departments": [
        {"id": "marketing", "name": "Marketing"}, {"id": "support", "name": "Customer Support"}]}))
    # The team already has a group called Marketing, under another id: it is reused, not doubled.
    with api.app.state.store.transaction() as c:
        roster = json.loads(c.execute("SELECT value_json FROM registry_metadata WHERE key='people'").fetchone()[0])
        c.execute("UPDATE registry_metadata SET value_json=? WHERE key='people'",
                  (encode({**roster, "org_groups": {"growth": {"name": "marketing"}}}),))
    api.put("/api/v2/onboarding", headers=signed_in(), json={
        "names": {"company_name": "Acme", "app_name": "Atlas", "assistant_name": "Morgan"},
        "answers": {"what_we_do": "We clean apartments.", "customers": "businesses"},
        "selected": {slug: {"template": slug, "display_name": slug.title(), "instructions": "x"}
                     for slug in ("seo", "brand", "tickets", "misc")}})
    assert api.post("/api/v2/onboarding/complete", json={}, headers=signed_in()).status_code == 200
    listed = {row["id"]: row for row in api.get("/api/v2/groups", headers=signed_in()).json()}
    assert list(listed) == ["growth", "support"] and listed["growth"]["bots"] == ["brand", "seo"]
    assert listed["support"]["name"] == "Customer Support" and listed["support"]["bots"] == ["tickets"]
    # Built-ins and a template in no group stay outside; completing again changes nothing.
    assert api.post("/api/v2/onboarding/complete", json={}, headers=signed_in()).status_code == 200
    assert api.get("/api/v2/groups", headers=signed_in()).json() == list(listed.values())
    bots = {row["id"]: row for row in api.get("/api/v2/org", headers=signed_in()).json()["bots"]}
    assert bots["seo"]["department"] == "marketing" and bots["misc"]["team"] == "" and bots["botops"]["team"] == ""
    assert bots["coo"]["team"] == ""


def test_a_bot_with_no_group_of_its_own_is_in_its_managers_until_taken_out(api):
    send(api, "POST", "groups", {"name": "Marketing", "add": {"bots": ["ops"]}})
    with api.app.state.store.transaction() as c:
        add_bots(c, seo=({}, "ops"), links=({}, "seo"))
        roster = Groups._roster(c)
        assert P.team_of("seo", Groups._configs(c), roster) == P.team_of("links", Groups._configs(c), roster) == "marketing"
        c.execute("UPDATE bot_config SET config_json=? WHERE bot='seo'", (encode({"name": "seo", "team": ""}),))
        assert P.team_of("seo", Groups._configs(c), roster) is None            # taken out of the group on purpose
        assert P.team_of("links", Groups._configs(c), roster) is None          # and so is what reports to it
