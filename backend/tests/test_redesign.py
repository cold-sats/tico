"""The redesign switch (backend/redesign.py): off by default, only the owner turns it on, and config carries it."""
from backend.tests.test_api import api, get, put  # noqa: F401


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
