"""A bot's question to a person is never silently lost: the ask returns its id even when the wait for the answer
fails, a retried ask is not sent twice, and a task left waiting on someone who was never asked shows in Health."""
import uuid

from backend.store import H
from backend.tests.test_api import api, headers, post  # noqa: F401
from backend.tests.test_tasks_board import bot_token
from clients import hubtools
from clients.tico import APIError


class Api:
    """hubtools' client over the test server, as one bot; the answer poll fails the way a dropped connection does."""
    def __init__(self, client, token):
        self.client, self.token = client, token

    def post(self, path, body, key=None):
        r = self.client.post("/api/v2/" + path, json=body, headers={
            "Authorization": "Bearer " + self.token, "Idempotency-Key": key or str(uuid.uuid4())})
        if r.status_code != 200:
            raise APIError("refused", r.text, r.status_code)
        return r.json()

    def get(self, path, **query):
        raise APIError("unavailable", "Tico could not confirm this request", retryable=True)


def test_an_ask_whose_wait_fails_still_returns_its_id_and_a_retry_is_not_sent_twice(api):
    bot = Api(api, bot_token(api, "ops"))
    args = {"bots": ["ana"], "text": "Which vendor should Acme pay first this week?", "wait_s": 30}
    first = hubtools.ask(bot, args)
    assert first["ana"]["timeout"] and first["ana"]["message_id"]
    assert hubtools.ask(bot, args) == first
    with api.app.state.store.read() as c:
        sent = c.execute("SELECT id FROM messages WHERE from_actor='bot:ops' AND to_actor='human:ana' "
                         "AND kind='ask'").fetchall()
    assert [r[0] for r in sent] == [first["ana"]["message_id"]]


def test_a_task_waiting_on_a_person_nobody_asked_shows_in_health_until_they_are_asked(api):
    tid = post(api, "tasks", {"owner": "ops", "title": "Renew the Acme domain", "body": "x"})["id"]
    with api.app.state.store.transaction() as c:
        H.task_update(c, "bot:ops", tid, status="waiting", waiting_on="ana")
        c.execute("UPDATE task_events SET ts=? WHERE task_id=? AND field='waiting_on'",
                  (H.shift(H.now(), hours=-2), tid))

    def check():
        body = api.get("/api/v2/health", headers=headers()).json()
        return next((row for row in body["checks"] if row["id"] == "silent_waits"), None)

    found = check()
    assert "Renew the Acme domain waits on" in found["summary"] and "nothing was asked" in found["summary"]
    assert found["fixes"][0]["href"] == "#/task/" + tid
    with api.app.state.store.transaction() as c:
        H.task_ask(c, "bot:ops", tid, "Should the domain renew for one year or three?")
    assert check() is None
