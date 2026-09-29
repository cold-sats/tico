"""`bot_contact: replies` — a bot the rest of the fleet cannot ping, and the ways back in.

Every run costs its operator money. A bot with a narrow job and an expensive model should not
be a free help desk for every other bot in the company, but it must still be reachable by a
person, by its manager, and by anyone it asked something of.
"""

from backend.tests.test_api import api, get, headers, post  # noqa: F401


def bot(api, slug, name, reports_to=None):
    return post(api, "bots", {"slug": slug, "display_name": name, "description": "A test bot.",
                              "reports_to": reports_to, "status": "active", "repo": "emp-" + slug,
                              "thread_mode": "personal", "model": "hermes-profile",
                              "effort": "as-configured", "harness": "hermes",
                              "operator": "ana", "owners": ["ana"], "runner_id": None})


def token(api, slug):
    return post(api, "bots/" + slug + "/agent-credential", {})["token"]


def quiet(api, slug, mode="replies", revision=1):
    return post(api, "bots/" + slug + "/definition",
                {"bot_contact": mode, "expected_revision": revision})


def fleet(api):
    """An analyst under a manager, and an unrelated bot with no business with it."""
    bot(api, "boss", "Manager")
    bot(api, "analyst", "Analyst", reports_to="boss")
    bot(api, "stranger", "Stranger")
    quiet(api, "analyst")
    return token(api, "boss"), token(api, "analyst"), token(api, "stranger")


def listed(api, slug):
    return next(row for row in get(api, "bots") if row["slug"] == slug)


def test_an_unrelated_bot_cannot_chat_it_or_put_a_task_on_it(api):
    _, _, stranger = fleet(api)
    refused = post(api, "chat/analyst", {"text": "Quick question about the funnel."},
                   token=stranger, expected=403)
    assert refused["error"]["code"] == "bot_contact"
    assert "manager or a person" in refused["error"]["detail"]
    post(api, "tasks", {"owner": "analyst", "title": "Pull these numbers", "body": "Please."},
         token=stranger, expected=403)
    # And it is not a silent drop: nothing was written either way.
    assert [t for t in get(api, "tasks")["tasks"] if t["owner"] == "bot:analyst"] == []


def test_a_person_is_never_shut_out(api):
    fleet(api)
    assert post(api, "chat/analyst", {"text": "What did the chart say?"})["body"] == "What did the chart say?"
    assert post(api, "tasks", {"owner": "analyst", "title": "Check the cancellations",
                               "body": "Before Thursday."})["owner"] == "bot:analyst"


def test_an_answer_to_its_own_question_always_gets_through(api):
    """`hubdb.answer` checks only that the ask was addressed to you, so a bot blocking on a
    reply can never be stranded by its own contact setting."""
    _, analyst, stranger = fleet(api)
    ask = post(api, "messages", {"to": "stranger", "text": "Which repo owns the capture?",
                                 "kind": "ask"}, token=analyst)
    answered = post(api, "messages/" + ask["id"] + "/answer", {"text": "the admin dashboard."}, token=stranger)
    assert answered["body"] == "the admin dashboard."
    assert get(api, "answers?ids=" + ask["id"], token=analyst)[ask["id"]]["body"] == "the admin dashboard."


# ---------- `tasks`: work arrives as a task and nothing else ----------

def notices_to(api, slug):
    """Every message the hub wrote to this bot, and whether it started a run. A `quiet` ref is
    the difference between news in the room and a whole run spent reading it."""
    import json
    with api.app.state.store.read() as c:
        rows = c.execute("SELECT body,refs_json FROM messages WHERE to_actor=? ORDER BY created",
                         ("bot:" + slug,)).fetchall()
    return [(r["body"].split("\n")[0], bool((json.loads(r["refs_json"] or "{}")).get("quiet")))
            for r in rows]


def tasks_only(api):
    bot(api, "boss", "Manager")
    bot(api, "analyst", "Analyst", reports_to="boss")
    bot(api, "stranger", "Stranger")
    quiet(api, "analyst", "tasks")
    return token(api, "boss"), token(api, "analyst"), token(api, "stranger")


def test_another_bot_may_file_work_and_do_nothing_else(api):
    _, _, stranger = tasks_only(api)
    filed = post(api, "tasks", {"owner": "analyst", "title": "Check the churned feeds",
                                "body": "Two clients still syncing."}, token=stranger)
    assert filed["owner"] == "bot:analyst"
    refused = post(api, "chat/analyst", {"text": "Did you see my ticket?"}, token=stranger, expected=403)
    assert refused["error"]["code"] == "bot_contact"
    assert "takes work as a task and nothing else" in refused["error"]["detail"]
    post(api, "messages", {"to": "analyst", "text": "Which column?", "kind": "ask"},
         token=stranger, expected=403)


def test_a_bot_files_on_another_bot_without_a_parent(api):
    """A subtask is the shape that parks the filer as `waiting`. No parking, no subtasks."""
    _, analyst, stranger = tasks_only(api)
    mine = post(api, "tasks", {"owner": "stranger", "title": "My own parent", "body": "Mine."},
                token=stranger)
    refused = post(api, "tasks", {"owner": "analyst", "title": "Check this bit", "body": "Please.",
                                  "parent_id": mine["id"]}, token=stranger, expected=422)
    assert refused["error"]["code"] == "subtask"
    # Its own sub-work is its own business, and a person may still break work down.
    post(api, "tasks", {"owner": "stranger", "title": "A step of my own", "body": "Mine.",
                        "parent_id": mine["id"]}, token=stranger)
    post(api, "tasks", {"owner": "analyst", "title": "A step Ben broke out", "body": "His.",
                        "parent_id": mine["id"]})


# ---------- news lands in the room; it does not cost a run ----------

def test_a_task_arriving_is_still_work(api):
    """The one thing that should wake a bot still does."""
    _, analyst, stranger = tasks_only(api)
    post(api, "tasks", {"owner": "analyst", "title": "Real work", "body": "Do it."}, token=stranger)
    assert ("New task from bot:stranger: Real work", False) in notices_to(api, "analyst")
