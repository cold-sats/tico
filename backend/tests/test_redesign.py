"""The redesign switch (backend/redesign.py): off by default, only the owner turns it on, and config carries it."""
from backend.tests.test_api import api, get, put  # noqa: F401
from backend.tests.test_member_bots import botops  # noqa: F401  (fixture)


def test_off_by_default_and_config_says_so(api):
    assert get(api, "settings/redesign") == {"enabled": False}
    assert get(api, "config")["redesign"] is False


def test_owner_turns_it_on_and_off(api):
    assert put(api, "settings/redesign", {"enabled": True}) == {"enabled": True}
    assert get(api, "config")["redesign"] is True
    assert get(api, "settings/redesign", token="ben-test") == {"enabled": True}
    put(api, "settings/redesign", {"enabled": False})
    assert get(api, "config")["redesign"] is False


def test_an_admin_may_not_switch_it(api):
    put(api, "settings/redesign", {"enabled": True}, token="ben-test", expected=403)
    assert get(api, "config")["redesign"] is False


def test_hub_tool_reads_and_the_owner_switches_it(api):
    """`hub redesign` / hub_redesign: read for anyone, set by the owner only (the route's own check)."""
    from backend.tests.test_mcp import call
    assert call(api, "hub_redesign", {}) == (False, {"enabled": False})
    assert call(api, "hub_redesign", {"on": True}) == (False, {"enabled": True})
    err, refused = call(api, "hub_redesign", {"on": False}, token="ben-test")
    assert err and "owner" in str(refused), refused
    assert get(api, "config")["redesign"] is True


def test_botops_switches_it_for_the_owner_and_not_for_an_admin(api, botops):
    from backend.tests.test_mcp import call
    from backend.tests.test_member_bots import finish, turn
    ben = turn(api, botops, person="ben-test", text="Turn on the new design")
    err, refused = call(api, "hub_redesign", {"on": True}, ben["token"])
    assert err and get(api, "config")["redesign"] is False, refused
    finish(api, botops, ben)
    ana = turn(api, botops, person="ana-test", text="Turn on the new design")
    assert call(api, "hub_redesign", {"on": True}, ana["token"]) == (False, {"enabled": True})
    finish(api, botops, ana)
    assert get(api, "config")["redesign"] is True
