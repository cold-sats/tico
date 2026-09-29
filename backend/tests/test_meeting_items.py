"""The three sections of a meeting, and Push.

The task, doc and feature pushes go through the real hub task path, because that is the point of them.
"""

import json

import pytest

from backend import meeting_items as MI
from backend.store import H
from backend.tests.test_api import api, get, headers, post   # noqa: F401


def record(api, body=None, token="ana-test"):
    """A finished meeting of the caller's, filed through the import API."""
    body = body or {}
    calendar = body.pop("calendar", None)
    r = api.post("/api/v2/meetings/import",
                 json={"title": "Pricing call", "transcript": "Dana: We agreed to ship on Friday.",
                       **({"participants": calendar["attendees"]} if calendar else {}), **body},
                 headers=headers(token))
    assert r.status_code == 200, r.text
    return r.json()["id"]


def items(api, rid, token="ana-test", expected=200):
    r = api.get(f"/api/meetings/{rid}/items", headers=headers(token))
    assert r.status_code == expected, r.text
    return r.json()


def add(api, rid, body, token="ana-test", expected=200, key=None):
    r = api.post(f"/api/meetings/{rid}/items", json=body, headers=headers(token, key))
    assert r.status_code == expected, r.text
    return r.json()


def change(api, rid, iid, body, token="ana-test", expected=200, key=None):
    r = api.post(f"/api/meetings/{rid}/items/{iid}", json=body, headers=headers(token, key))
    assert r.status_code == expected, r.text
    return r.json()


def push(api, rid, iid, body=None, token="ana-test", expected=200, key=None):
    r = api.post(f"/api/meetings/{rid}/items/{iid}/push", json=body or {}, headers=headers(token, key))
    assert r.status_code == expected, r.text
    return r.json()


def test_anyone_who_can_read_the_room_edits_and_deletes_but_only_the_owner_pushes(api):
    rid = record(api, {"title": "Weekly sync"}, "ben-test")
    iid = add(api, rid, {"section": "feature", "text": "Bulk edit for guidebooks",
                         "detail": {"side": "F"}}, "ben-test")["item"]["id"]
    # A viewer may correct the text and delete an item; the row is kept with who did it.
    edited = change(api, rid, iid, {"text": "Bulk edit for guidebook entries"}, "cara-test")["item"]
    assert edited["text"] == "Bulk edit for guidebook entries" and edited["updated_by"] == "human:cara"
    assert items(api, rid, "cara-test")["can_push"] is False
    push(api, rid, iid, {}, "cara-test", expected=403)
    dismissed = change(api, rid, iid, {"status": "dismissed"}, "cara-test")["item"]
    assert dismissed["status"] == "dismissed" and dismissed["updated_by"] == "human:cara"
    push(api, rid, iid, {}, "ben-test", expected=409)
    change(api, rid, iid, {"status": "dismissed"}, "ben-test", expected=409)
    # A bot has no business in a meeting room at all.
    from backend.tests.test_api import setup_attempt
    _, _, attempt = setup_attempt(api)
    items(api, rid, attempt["token"], expected=403)
    add(api, rid, {"section": "task", "text": "From a bot"}, attempt["token"], expected=403)


def test_a_private_meeting_keeps_its_items_to_the_people_the_invite_names(api):
    """Items inherit the room's visibility; `backend/media.authorized` is the only gate."""
    rid = record(api, {"title": "Comp review", "private": True,
                       "calendar": {"event_id": "e1", "title": "Comp review",
                                    "attendees": ["Ana@Acme.example"]}}, "ben-test")
    add(api, rid, {"section": "doc", "text": "Write down the band for a senior"}, "ben-test")
    assert len(items(api, rid, "ana-test")["sections"]["doc"]) == 1         # named, and the owner
    items(api, rid, "cara-test", expected=403)                             # not on the invite
    add(api, rid, {"section": "task", "text": "Not mine to add"}, "cara-test", expected=403)
    # Making it a company meeting again opens the items with it.
    api.post(f"/api/meetings/{rid}/edit", json={"private": False, "version": 1},
             headers=headers("ben-test"))
    assert items(api, rid, "cara-test")["can_push"] is False


# ----------------------------------------------------------------------------- comments


def test_a_pushed_item_is_a_hub_task_with_the_meeting_it_came_from(api):
    rid = record(api, {"title": "Weekly sync"})
    iid = add(api, rid, {"section": "task", "text": "Send Dana the pricing sheet", "quote": "We agreed to ship on Friday.",
                         "detail": {"owner": "human:ben", "priority": "p1"}})["item"]["id"]
    pushed = push(api, rid, iid)
    assert pushed["pushed"] and pushed["item"]["status"] == "pushed"
    task = get(api, "tasks/" + pushed["item"]["result_ref"])["task"]
    assert task["owner"] == "human:ben" and task["title"] == "Send Dana the pricing sheet"
    assert "From meeting: Weekly sync" in task["body"] and "> We agreed to ship on Friday." in task["body"]
    assert f"#/meetings?meeting={rid}" in task["body"]
    # A second push is one result, not a second task.
    assert push(api, rid, iid)["pushed"] is False
    # A task with no owner is refused rather than guessed.
    bare = add(api, rid, {"section": "task", "text": "Someone should follow up"})["item"]["id"]
    push(api, rid, bare, expected=422)


def test_the_thread_on_a_meeting_is_open_to_whoever_can_read_it(api):
    rid = record(api)
    r = api.post(f"/api/meetings/{rid}/comments", json={"text": "Agreed on the date", "at_ms": 5000}, headers=headers("cara-test"))
    assert r.status_code == 200 and r.json()["comment"]["author_name"]
    thread = api.get(f"/api/meetings/{rid}/comments", headers=headers("ben-test")).json()["comments"]
    assert [c["text"] for c in thread] == ["Agreed on the date"]
