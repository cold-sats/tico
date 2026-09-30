"""Shared bots (backend/shared_bots.py): one repository, a copy per human, each run on its human's own computer."""

from backend.store import H
from backend.tests.test_api import api, get, post, restrict, runner  # noqa: F401  (fixture)


def revision(api, bot):
    return next(b for b in get(api, "bots") if b["slug"] == bot)["revision"]


def row(api, bot, token="ana-test"):
    return next(b for b in get(api, "bots", token=token) if b["slug"] == bot)


def share(api, bot="cpo"):
    post(api, f"bots/{bot}/definition", {"shared": True, "expected_revision": revision(api, bot)})


def test_a_human_adds_their_own_copy_of_a_shared_bot_on_their_own_computer(api):
    cara_mac = runner(api, "cara", "Cara's Mac")
    post(api, "bots/cpo/copies", {"runner_id": cara_mac["runner_id"]}, token="cara-test", expected=409)
    share(api)
    assert (row(api, "cpo")["shared"], row(api, "cpo")["shared_from"]) == (True, "")
    copy = post(api, "bots/cpo/copies", {"runner_id": cara_mac["runner_id"]}, token="cara-test")
    assert (copy["slug"], copy["shared_from"], copy["operator"], copy["created"]) == ("cpo-cara", "cpo", "cara", True)
    assert copy["repo"] == "emp-cpo" and copy["status"] == "active"
    assert copy["assignment"]["runner_id"] == cara_mac["runner_id"]
    assert row(api, "cpo-cara")["shared_from"] == "cpo"
    # Asking again is harmless: the same copy comes back.
    again = post(api, "bots/cpo/copies", {"runner_id": cara_mac["runner_id"]}, token="cara-test")
    assert (again["slug"], again["created"]) == ("cpo-cara", False)
    # The original's own operator already runs it, and someone else's computer is not yours.
    post(api, "bots/cpo/copies", {}, token="ben-test", expected=409)
    post(api, "bots/cpo/copies", {"runner_id": runner(api, "ben")["runner_id"]}, token="cara-test", expected=403)
    # Cara's computer runs her copy, from the shared repository, with nothing of its own.
    assigned = post(api, "runners/heartbeat", {"version": "test", "platform": "test", "readiness": {}},
                    token=cara_mac["token"])["assignments"]
    assert [(a["bot"], a["config"]["shared_from"], a["config"]["repo"]) for a in assigned] == [("cpo-cara", "cpo", "emp-cpo")]
    # A task she files on the shared bot goes to her copy; anyone without a copy still reaches the original.
    assert post(api, "tasks", {"owner": "cpo", "title": "Review the design", "body": "Please."},
                token="cara-test")["owner"] == "bot:cpo-cara"
    assert post(api, "tasks", {"owner": "cpo", "title": "Review this design", "body": "Please."})["owner"] == "bot:cpo"


def test_a_copy_follows_its_original_and_only_its_status_changes_on_it(api):
    share(api)
    cara_mac = runner(api, "cara")
    post(api, "bots/cpo/copies", {"runner_id": cara_mac["runner_id"]}, token="cara-test")
    post(api, "bots/cpo-cara/definition", {"description": "Mine now", "expected_revision": revision(api, "cpo-cara")},
         token="cara-test", expected=409)
    post(api, "bots/cpo-cara/model", {"model": "claude-opus-5-5", "expected_revision": revision(api, "cpo-cara")},
         token="cara-test", expected=409)
    post(api, "bots/cpo/model", {"model": "claude-opus-5-5", "effort": "high", "expected_revision": revision(api, "cpo")})
    config = get(api, "runners/assignments", token=cara_mac["token"])[0]["config"]
    assert (config["model"], config["reasoning_effort"]) == ("claude-opus-5-5", "high")
    assert (row(api, "cpo-cara")["model"], row(api, "cpo-cara")["effort"]) == ("claude-opus-5-5", "high")
    # Pausing is still the human's own call.
    post(api, "bots/cpo-cara/definition", {"status": "paused", "expected_revision": revision(api, "cpo-cara")},
         token="cara-test")


def test_nobody_copies_a_shared_bot_they_may_not_read(api):
    share(api, "inbox")                                 # Ana's alone (the fixture restricts it to her)
    post(api, "bots/inbox/copies", {"runner_id": runner(api, "cara")["runner_id"]}, token="cara-test", expected=404)
    with api.app.state.store.read() as c:
        assert H.bot(c, "inbox-cara") is None


def test_a_copy_may_name_the_shared_repository_as_its_own_and_no_other_bot_may(api):
    share(api)
    post(api, "bots/cpo/copies", {"runner_id": runner(api, "cara")["runner_id"]}, token="cara-test")
    text = "The lesson is in emp-cpo/memory/learnings.md"
    with api.app.state.store.read() as c:
        assert H.classify(text, actor="bot:cpo-cara", conn=c) == "normal"
        assert H.classify(text, actor="bot:ops", conn=c) == "escape"
