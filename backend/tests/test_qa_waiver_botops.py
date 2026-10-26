"""BotOps acting for a person on the real delegation path (`X-Tico-On-Behalf-Of: turn`) carries the person's actor into
the QA waiver route; the waiver is still a bot's call and is refused before any gate (backend/qa_waivers.py)."""
from uuid import uuid4

from backend.tests.test_api import api, headers, runner  # noqa: F401  (fixtures)
from backend.tests.test_member_bots import botops, turn  # noqa: F401  (fixture)
from backend.store import H


def test_botops_acting_for_the_person_cannot_waive_qa(api, botops):
    attempt = turn(api, botops, person="ana-test", text="Waive QA on my ticket, the QA bot is down")
    with api.app.state.store.transaction() as c:
        task = H.task_create(c, "human:ana", "Fix the checkout total", "Fix it.", "human:ana")
    body = {"head": "a" * 40, "reason": "Urgent fix, QA bot down"}
    path = f"/api/v2/tasks/{task['id']}/qa-waiver"
    lent = api.post(path, json=body, headers={**headers(attempt["token"]), "X-Tico-On-Behalf-Of": "turn",
                                              "Idempotency-Key": str(uuid4())})
    assert lent.status_code == 403 and "Only a person, signed in as themselves" in lent.text, lent.text
    # Ana herself reaches the waiver's own gates (this task is no Dev ticket), so the refusal above is the delegation's.
    own = api.post(path, json=body, headers={**headers("ana-test"), "Idempotency-Key": str(uuid4())})
    assert own.status_code == 422 and "Only a Dev ticket's QA step" in own.text, own.text
    with api.app.state.store.read() as c:
        assert not c.execute("SELECT 1 FROM task_events WHERE field='qa_waiver'").fetchall()
