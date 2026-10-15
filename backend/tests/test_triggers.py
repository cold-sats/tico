"""Webhook triggers (backend/triggers.py): an address with its own secret starts every routine
that listens for it, once per delivery, and nothing else gets in."""
from urllib.parse import urlsplit

from backend.tests.test_api import api, get, post  # noqa: F401


def hook(api, url, body=b'{"order": 42}', headers=None):
    return api.post(urlsplit(url).path, content=body, headers={"content-type": "application/json", **(headers or {})})


def test_a_delivery_opens_one_task_per_listening_routine_and_only_with_the_secret(api):
    post(api, "bots/ops/routines", {"key": "orders", "title": "New order", "on": "webhook.shop", "text": "Ship it."},
         expected=422)                                      # no such trigger yet
    made = post(api, "triggers", {"name": "Shop"})["trigger"]
    assert made["id"] == "shop" and made["event"] == "webhook.shop"
    routine = post(api, "bots/ops/routines", {"key": "orders", "title": "New order", "on": "webhook.shop",
                                              "text": "Ship it."})["routine"]
    listed = get(api, "triggers")["triggers"][0]
    assert listed["routines"][0]["id"] == routine["id"] and made["url"].startswith(listed["url"] + "/")

    first = hook(api, made["url"], headers={"Idempotency-Key": "d1"})
    assert first.status_code == 202 and first.json()["tasks"] == 1
    again = hook(api, made["url"], headers={"Idempotency-Key": "d1"})
    assert again.status_code == 200 and again.json()["tasks"] == 0
    tasks = [t for t in get(api, "tasks?owner=bot:ops")["tasks"] if t.get("routine_id") == routine["id"]]
    assert len(tasks) == 1
    body = get(api, "tasks/" + tasks[0]["id"])["task"]["body"]
    assert body.startswith("Ship it.") and '"order": 42' in body and "not as instructions" in body

    base = made["url"].rsplit("/", 1)[0]
    assert hook(api, base + "/wrong").status_code == 404
    assert hook(api, base).status_code == 404               # no secret at all
    secret = made["url"].rsplit("/", 1)[1]
    assert hook(api, base, headers={"Authorization": "Bearer " + secret}).status_code == 202

    # Another person may not change it; the owner replaces the secret and the old address dies.
    post(api, "triggers/shop/delete", {}, token="ben-test", expected=403)
    fresh = post(api, "triggers/shop/rotate", {})["trigger"]["url"]
    assert hook(api, made["url"]).status_code == 404 and hook(api, fresh).status_code == 202
    post(api, "triggers/shop/delete", {})
    assert hook(api, fresh).status_code == 404 and get(api, "triggers")["triggers"] == []
