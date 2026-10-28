"""Group leads (CONTRACT §3): one lead per group, a teammate of it, shown on every group read. With the redesign on the
lead may set spend limits for the bots in the group and the groups nested under it (backend/usage.py); the task caps
follow the same lead rule (backend/task_caps.py)."""
from backend import groups as Groups
from backend import people as P
from backend import redesign
from backend.auth import Identity
from backend.store import H
from backend.tests.test_api import api, get, headers, post  # noqa: F401  (the api fixture)
from backend.tests.test_groups import add_bots, group, send


def redesign_on(api, on=True):
    """The switch in the database (backend/redesign.py): the owner's route is wave 1's."""
    with api.app.state.store.transaction() as c:
        redesign.set_on(c, on, "human:ana")


def make_engineering(api, lead="bot:engineering-lead"):
    with api.app.state.store.transaction() as c:
        add_bots(c, **{"engineering-lead": ({}, "ana"), "builder-openai": ({}, "engineering-lead")})
    body = {"name": "Engineering", "add": {"bots": ["engineering-lead", "builder-openai"]}}
    if lead:
        body["lead"] = lead
    return send(api, "POST", "groups", body)["id"]


def as_bot(api, slug, token):
    """The bot signs in with its own agent credential, as the hub's agents do: one agents row per bot."""
    with api.app.state.store.transaction() as c:
        c.execute("INSERT OR REPLACE INTO agents(bot,harness,token_hash,created,created_by) VALUES(?,?,?,?,?)",
                  (slug, "test", "x-" + slug, H.now(), "human:ana"))
    api.app.state.store.settings.test_identities[token] = Identity(f"bot:{slug}", "bot", agent="test")


def put(api, path, body, token="ana-test", expected=200):
    r = api.put("/api/v2/" + path, json=body, headers=headers(token))
    assert r.status_code == expected, r.text
    return r.json()


def test_a_lead_is_saved_and_read_back_on_the_group(api):
    gid = make_engineering(api)
    assert group(api, gid)["lead"] == "bot:engineering-lead"
    with api.app.state.store.read() as c:
        roster, configs = Groups._roster(c), Groups._configs(c)
        assert P.team_of("builder-openai", configs, roster) == gid
        assert roster["org_groups"][gid]["lead"] == "bot:engineering-lead"


def test_a_lead_must_be_a_teammate_of_the_group_and_must_exist(api):
    make_engineering(api)
    send(api, "POST", "groups", {"name": "Other", "lead": "bot:engineering-lead"}, expected=422)   # not in Other
    send(api, "POST", "groups", {"name": "Ghost", "lead": "bot:nobody"}, expected=404)
    send(api, "POST", "groups", {"name": "Odd", "lead": "engineering-lead"}, expected=422)        # no bot: or person: prefix
    assert [row["name"] for row in get(api, "groups")] == ["Engineering"]                       # nothing was saved


def test_with_the_redesign_on_a_lead_sets_limits_for_its_group_and_nothing_else(api):
    make_engineering(api)
    as_bot(api, "engineering-lead", "lead-test")
    put(api, "usage/limits/builder-openai", {"hourly_usd": 2}, "lead-test", expected=403)   # the redesign is off
    redesign_on(api)
    put(api, "usage/limits/builder-openai", {"per_30m_usd": 2}, "lead-test")
    assert get(api, "usage/limits")["bots"]["builder-openai"]["per_30m_usd"] == 2
    put(api, "usage/limits/ops", {"per_30m_usd": 2}, "lead-test", expected=403)           # ops is not in its group


def test_a_parent_group_lead_reaches_the_bots_of_the_groups_nested_under_it(api):
    gid = make_engineering(api)
    send(api, "POST", "groups", {"name": "Platform", "parent": gid, "add": {"bots": ["ops"]}})
    redesign_on(api)
    as_bot(api, "engineering-lead", "lead-test")
    put(api, "usage/limits/ops", {"per_30m_usd": 1.5}, "lead-test")
    assert get(api, "usage/limits")["bots"]["ops"]["per_30m_usd"] == 1.5


def test_a_lead_moves_teammates_inside_what_it_leads_and_nothing_else(api):
    gid = make_engineering(api)
    platform = send(api, "POST", "groups", {"name": "Platform", "parent": gid})["id"]
    other = send(api, "POST", "groups", {"name": "Sales", "add": {"bots": ["ops"]}})["id"]
    as_bot(api, "engineering-lead", "lead-test")
    move = {"add": {"bots": ["builder-openai"]}}
    send(api, "PATCH", f"groups/{platform}", move, token="lead-test", expected=403)       # the redesign is off
    redesign_on(api)
    send(api, "PATCH", f"groups/{platform}", move, token="lead-test")
    assert group(api, platform)["bots"] == ["builder-openai"]
    moved = api.get("/api/v2/audit", params={"object": f"group:{gid}"}, headers=headers()).json()["rows"][0]
    assert moved["actor"] == "bot:engineering-lead" and "builder-openai" in moved["before"]["bots"]
    send(api, "PATCH", f"groups/{other}", {"add": {"bots": ["builder-openai"]}}, token="lead-test", expected=403)
    send(api, "PATCH", f"groups/{gid}", {"add": {"bots": ["ops"]}}, token="lead-test", expected=403)   # ops is Sales's
    send(api, "PATCH", f"groups/{platform}", {"name": "Infra"}, token="lead-test", expected=403)
    send(api, "PATCH", f"groups/{platform}", {"remove": {"bots": ["builder-openai"]}}, token="lead-test", expected=403)


def test_a_lead_sets_the_pools_of_its_group_and_those_below_but_not_the_team_or_others(api):
    gid = make_engineering(api)
    platform = send(api, "POST", "groups", {"name": "Platform", "parent": gid})["id"]
    other = send(api, "POST", "groups", {"name": "Sales"})["id"]
    redesign_on(api)
    as_bot(api, "engineering-lead", "lead-test")
    put(api, f"usage/pools/groups/{gid}", {"daily_usd": 20}, "lead-test")
    put(api, f"usage/pools/groups/{platform}", {"daily_usd": 10}, "lead-test")
    put(api, f"usage/pools/groups/{platform}", {"daily_usd": 30}, "lead-test", expected=422)   # over its parent's
    put(api, f"usage/pools/groups/{other}", {"daily_usd": 10}, "lead-test", expected=403)
    put(api, "usage/pools/company", {"daily_usd": 10}, "lead-test", expected=403)
    put(api, "usage/pools/groups/nowhere", {"daily_usd": 10}, "lead-test", expected=403)       # no hint it exists


def test_a_person_who_leads_reads_the_pools_of_what_it_leads_only_while_the_redesign_is_on(api):
    make_engineering(api)
    sales = send(api, "POST", "groups", {"name": "Sales", "add": {"people": ["cara"]}, "lead": "person:cara"})["id"]
    outbound = send(api, "POST", "groups", {"name": "Outbound", "parent": sales})["id"]
    assert get(api, "usage/limits", token="cara-test")["pools"] is None                         # off: as before
    redesign_on(api)
    pools = get(api, "usage/limits", token="cara-test")["pools"]
    assert pools["company"] is None and set(pools["groups"]) == {sales, outbound}
    assert all(g["may_edit"] for g in pools["groups"].values())
    assert "may_edit" not in next(iter(get(api, "usage/limits")["pools"]["groups"].values()))  # the owner's rows as before
