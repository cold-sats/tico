"""Writes to a paused or quarantined bot: kept and said so, or refused without counting against the sender."""
from backend.tests.test_api import api, api_settings, post, setup_attempt  # noqa: F401  (fixtures)
from backend.store import H


def test_a_bot_writing_to_a_quarantined_bot_is_told_it_is_kept_and_stays_active(api):
    _, _, attempt = setup_attempt(api)
    task = post(api, "tasks", {"owner": "finance", "title": "Check the invoice run", "body": "Read the fixture invoices"},
                token=attempt["token"])
    with api.app.state.store.transaction() as c:
        H.quarantine(c, "finance", "10 repeated refusals today")
    for i in range(6):
        sent = post(api, "messages", {"to": "finance", "text": f"Review {i} is ready"}, token=attempt["token"])
        assert "is kept" in sent["warning"] and "until about" in sent["warning"], sent
        comment = post(api, f"tasks/{task['id']}/comments", {"text": f"Finding {i}"}, token=attempt["token"])
        assert "is kept" in comment["warning"], comment
    refused = post(api, "tasks", {"owner": "finance", "title": "Check the payroll run", "body": "Read it"},
                   token=attempt["token"], expected=422)
    assert "does not count against you" in str(refused), refused
    with api.app.state.store.read() as c:
        assert H.bot(c, "ops")["state"] == "active"
