"""POST /api/v2/sql shows each caller exactly the rows the JSON API lets them read.

backend/sql.py restates the visibility rules of backend/auth.py in SQL, so the two can drift, and a
drift is a data leak through the door nobody watches. Every check here asks both doors the same
question about the same records and requires the same answer: private rooms and their messages,
tasks, meetings, for the owner, a member, a person with a private room and a bot; and a bot whose
turn was taken away by a reassignment. A record the API refuses must not be in SQL, and the other way.
"""
import pytest

from backend.tests.test_api import api, assign, claim, expire, get, headers, post, ready, runner  # noqa: F401
from backend.tests.test_media import import_meeting
from backend.tests.test_sql import query


@pytest.fixture
def seeded(api):
    """Rooms, tasks and meetings belonging to different people, and a bot mid-turn on `ops`."""
    post(api, "bots/cpo/owners", {"owners": ["cara"], "expected_revision": 1})      # Cara operates a bot of her own
    chats = {}
    for name, token, bot in (("ana", "ana-test", "ops"), ("ben", "ben-test", "ops"), ("cara", "cara-test", "cpo")):
        chats[name] = post(api, f"chat/{bot}", {"text": f"{name} in the private room"}, token=token)["conversation_id"]
        post(api, f"chat/{bot}", {"text": f"{name} again"}, token=token)
    tasks = [post(api, "tasks", {"owner": owner, "title": f"{who} to {owner}", "body": "Do it."}, token=token)["id"]
             for who, token, owner in (("ana", "ana-test", "ops"), ("ana", "ana-test", "inbox"), ("ben", "ben-test", "finance"),
                                       ("cara", "cara-test", "ops"), ("cara", "cara-test", "coo"))]
    meetings = [import_meeting(api, token, title=title, external_id=title.replace(" ", "-"), **extra)["id"] for title, token, extra in (
        ("company call", "ana-test", {}),
        ("ben private", "ben-test", {"private": True, "participants": ["cara@acme.example"]}),
        ("cara private", "cara-test", {"private": True}),
        ("ben open", "ben-test", {}))]
    gone = import_meeting(api, "ben-test", title="deleted", external_id="deleted")["id"]
    assert api.post(f"/api/meetings/{gone}/delete", json={}, headers=headers("ben-test")).status_code == 200
    machine = runner(api)
    assign(api, machine, "ops")
    ready(api, machine, ["ops"])
    attempt = claim(api, machine)
    return {"rooms": list(chats.values()), "tasks": tasks, "meetings": [*meetings, gone], "machine": machine,
            "attempt": attempt}


def actors(seeded):
    return {"owner": "ana-test", "member": "ben-test", "person with a private room": "cara-test",
            "bot": seeded["attempt"]["token"]}


def sql_ids(api, table, token, where=""):
    return {row[0] for row in query(api, f"SELECT id FROM {table} {where}", token)["rows"]}


def allowed(api, path, token):
    status = api.get("/api/v2/" + path if not path.startswith("/") else path, headers=headers(token)).status_code
    assert status in (200, 403, 404), (path, status)
    return status == 200


def test_tasks_are_visible_through_sql_exactly_when_the_api_shows_them(api, seeded):
    for name, token in actors(seeded).items():
        in_sql = sql_ids(api, "tasks", token)
        through_api = {tid for tid in seeded["tasks"] if allowed(api, "tasks/" + tid, token)}
        assert in_sql == through_api, name
    for name in ("owner", "member", "person with a private room"):     # the list endpoint too, for people
        listed = {t["id"] for t in get(api, "tasks?status=all", actors(seeded)[name])["tasks"]}
        assert listed == sql_ids(api, "tasks", actors(seeded)[name]), name


def test_private_rooms_and_their_messages_are_visible_through_sql_exactly_when_the_api_shows_them(api, seeded):
    with api.app.state.store.read() as c:      # every conversation there is, whoever may read it
        every_room = {row[0] for row in c.execute("SELECT id FROM conversations")}
    assert set(seeded["rooms"]) <= every_room
    for name, token in actors(seeded).items():
        readable, message_ids = set(), set()
        for room in every_room:
            if allowed(api, f"conversations/{room}/messages", token):
                readable.add(room)
                message_ids |= {m["id"] for m in get(api, f"conversations/{room}/messages", token)}
        assert sql_ids(api, "conversations", token) == readable, name
        assert sql_ids(api, "messages", token) == message_ids, name


def test_a_bot_whose_turn_was_reassigned_is_refused_by_both_doors(api, seeded):
    token = seeded["attempt"]["token"]
    assert query(api, "SELECT count(*) FROM tasks", token)["rows"]
    expire(api, seeded["attempt"]["id"])       # the first Mac stops renewing; the bot moves to another
    other = runner(api, label="Second Mac")
    assign(api, other, "ops", generation=1)
    ready(api, other, ["ops"])
    refused = api.get("/api/v2/tasks/" + seeded["tasks"][0], headers=headers(token)).status_code
    sql = api.post("/api/v2/sql", json={"sql": "SELECT id FROM tasks"}, headers=headers(token))
    assert refused != 200 and sql.status_code == refused, (refused, sql.status_code, sql.text)
