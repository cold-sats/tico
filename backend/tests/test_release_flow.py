"""The release rhythm: one daily Release task, `release now`, and the wakes a published release sends."""

import json
from datetime import datetime, timezone

from backend import hubdb as H
from backend import release_flow as RF
from backend.store import encode
from backend.tests.test_github import PR, api, get, headers, hook, pr_event, post  # noqa: F401

RELEASE_URL = "https://github.com/ticoteam/tico/releases/tag/v1.2.3"


def _team(api):
    """cmo is the Release Manager and cpo the Technical Writer (by starter template); Dev tickets has a Pending Release."""
    with api.app.state.store.transaction() as c:
        bots = {slug: {"name": slug, "runtime": "fake", "status": "active"} for slug in ("cpo", "cmo", "qab")}
        H.sync_registry(c, bots, {"people": [{"id": "ana", "email": "ana@acme.example", "team": "leadership"}]})
        for slug, template in (("cmo", RF.MANAGER), ("cpo", RF.WRITER), ("qab", RF.QA)):
            c.execute("INSERT OR REPLACE INTO bot_config(bot,config_json,team,operator) VALUES(?,?,?,?)",
                      (slug, encode({**bots[slug], "template": template}), "product", "ana"))
        dev = H.type_create(c, "human:ana", "Dev tickets", numbered=True, steps=[
            {"name": "In QA", "status": "review"}, {"name": "Pending Release", "status": "review"},
            {"name": "Post Release QA", "status": "review"}, {"name": "Done", "status": "done"}])
    return dev


def _ticket(api, dev, title, number=412, tags=()):
    url = PR.replace("/412", f"/{number}")
    ticket = post(api, "tasks", {"owner": "cpo", "title": title, "body": "x", "links": [url], "type": dev["id"],
                                 "step": "Pending Release", "labels": list(tags)})
    hook(api, "pull_request", pr_event("closed", html_url=url, merged=True, merge_commit_sha="abc%d" % number,
                                       merged_at="2026-10-19T12:42:19Z"))
    return ticket


def _tasks(api, owner):
    with api.app.state.store.read() as c:
        return [r["title"] for r in c.execute("SELECT title FROM tasks WHERE owner=? AND title LIKE 'Release:%'",
                                              (H.bot_actor(owner),))]


def _release_wakes(api, ticket):
    with api.app.state.store.read() as c:
        return [(r["body"], r["refs_json"]) for r in c.execute(
            "SELECT m.body, m.refs_json FROM messages m JOIN conversations cv ON cv.id=m.conversation_id "
            f"WHERE {H.MESSAGE_TASK_SQL}=? AND json_extract(m.refs_json,'$.wake')='release_published'", (ticket["id"],))]


def test_the_daily_hour_sends_one_task_and_nothing_when_nothing_is_pending(api):
    dev = _team(api)
    store = api.app.state.store
    # 10:00 company time on a day in October (PDT, UTC-7) is 17:00Z
    hour = datetime(2026, 10, 20, 17, 5, tzinfo=timezone.utc)
    with store.transaction() as c:
        assert RF.tick(c, hour)["reason"] == "nothing_pending"
    assert _tasks(api, "cmo") == []
    _ticket(api, dev, "Visual replies", 412)
    _ticket(api, dev, "Pricing page", 413)
    later = datetime(2026, 10, 21, 17, 5, tzinfo=timezone.utc)
    with store.transaction() as c:
        assert RF.tick(c, later)["sent"] is True
        assert RF.tick(c, later) is None, "an hour is handled once"
    assert _tasks(api, "cmo") == ["Release: 2 tickets at Pending Release"]


def test_release_now_is_for_those_who_move_dev_tickets_and_wakes_an_open_release_task(api):
    dev = _team(api)
    _ticket(api, dev, "Hotfix", 412)
    refused = api.post("/api/v2/release/now", json={}, headers={**headers(), "Authorization": "Bearer nobody"})
    assert refused.status_code in (401, 403)
    first = post(api, "release/now", {"note": "hotfix"})
    assert first["sent"] is True and _tasks(api, "cmo") == ["Release: 1 ticket at Pending Release"]
    again = post(api, "release/now", {})
    assert again["reason"] == "already_open" and again["task"] == first["task"]
    assert len(_tasks(api, "cmo")) == 1, "a second Release task is never filed beside an open one"


def test_a_published_release_wakes_qa_and_the_writer_once_per_ticket(api):
    dev = _team(api)
    tested = _ticket(api, dev, "Visual replies", 412, tags=["qa"])
    plain = _ticket(api, dev, "Typo fix", 413)
    event = {"action": "published", "release": {"tag_name": "v1.2.3", "html_url": RELEASE_URL},
             "repository": {"full_name": "ticoteam/tico"}}
    hook(api, "release", event)
    hook(api, "release", event)      # the same delivery again
    assert [json.loads(r)["role"] for _, r in _release_wakes(api, plain)] == ["docs"], "no qa label: the writer only"
    assert sorted(json.loads(r)["role"] for _, r in _release_wakes(api, tested)) == ["docs", "qa"]
