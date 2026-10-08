"""`POST /api/v2/judge` (`backend/judge.py`): the judge as a hub tool, audited, budgeted, never the state."""

import json

from backend import judge as B
from backend.tests.test_api import api, get, headers, post, setup_attempt   # noqa: F401
from backend.tests.test_mcp import call

QUESTIONS = {
    "bucket": {"type": "choice", "instructions": "Where does it go?",
               "criteria": {"archive": "noise", "reply": "answer it"}},
    "is_ask": {"type": "noul", "instructions": "Is someone asking for something?"},
}


class FakeJudge:
    def __init__(self):
        self.calls, self.fail = [], None

    def __call__(self, state, questions, label=None):
        self.calls.append({"state": state, "questions": questions, "label": label})
        if self.fail:
            raise self.fail
        return {"model": "judge-1.13.0", "usage": {"input_tokens": 90, "output_tokens": 0}, "ms": 180,
                "answers": {"bucket": {"type": "choice", "choice": "reply", "confidence": 0.8,
                                       "probabilities": {"archive": 0.2, "reply": 0.8}},
                            "is_ask": {"type": "noul", "noul": 0.9}}}


def fake(api):
    engine = FakeJudge()
    api.app.state.judge = engine
    return engine


def events(api, actor):
    with api.app.state.store.read() as c:
        return [(r["target"], json.loads(r["detail_json"])) for r in c.execute(
            "SELECT target, detail_json FROM events WHERE action='judge.call' AND actor=? ORDER BY ts", (actor,))]


def test_a_person_or_a_bot_judges_and_the_audit_keeps_the_answers_not_the_state(api):
    engine = fake(api)
    state = {"subject": "Invoice 4471", "snippet": "the secret body of the mail"}
    out = post(api, "judge", {"state": state, "questions": QUESTIONS, "label": "mail-triage@1"})
    assert out["answers"]["bucket"]["choice"] == "reply" and out["label"] == "mail-triage@1"
    assert out["model"] == "judge-1.13.0" and out["ms"] == 180
    assert engine.calls[-1] == {"state": state, "questions": QUESTIONS, "label": "mail-triage@1"}
    (target, detail), = events(api, "human:ana")
    assert target == "mail-triage@1"
    assert detail["answers"] == {"bucket": {"type": "choice", "value": "reply", "confidence": 0.8},
                                 "is_ask": {"type": "noul", "value": 0.9, "confidence": 0.8}}
    assert detail["usage"]["input_tokens"] == 90 and detail["questions"] == 2
    assert "secret" not in json.dumps(detail)

    r, msg, attempt = setup_attempt(api)
    err, out = call(api, "hub_decision_ask", {"state": state, "questions": QUESTIONS}, token=attempt["token"])
    assert not err and out["answers"]["is_ask"]["noul"] == 0.9
    assert events(api, "bot:ops")[0][0] == ""


def test_rehearsal_decisions_never_reach_a_configured_or_fallback_provider(api, monkeypatch):
    api.app.state.store.settings.rehearsal = True
    engine = fake(api)
    def forbidden(*args, **kwargs):
        raise AssertionError("A rehearsal must not resolve a provider")
    monkeypatch.setattr(B, "fallback_engine", forbidden)
    for configured in (engine, None):
        api.app.state.judge = configured
        assert get(api, "judge")["configured"] is False
        result = api.post("/api/v2/decisions", json={"state": {"team": "Acme"}, "questions": QUESTIONS}, headers=headers())
        assert result.status_code == 503 and result.json()["error"]["code"] == "rehearsal"
    assert engine.calls == [] and events(api, "human:ana") == []


def test_a_slow_or_down_typesafe_falls_back_to_the_companys_model_instead_of_a_503(api, monkeypatch):
    from clients import judge as J
    jev, backup = fake(api), FakeJudge()
    jev.fail = J.JudgeError("unavailable", "TypeSafe did not answer: TimeoutError", retryable=True)
    monkeypatch.setattr(B, "fallback_engine", lambda *args, **kwargs: backup)
    out = post(api, "decisions", {"state": {"subject": "Invoice 4471"}, "questions": QUESTIONS, "label": "mail-triage@1"})
    assert out["answers"]["bucket"]["choice"] == "reply" and len(jev.calls) == 1 and len(backup.calls) == 1
    assert events(api, "human:ana")[-1][1]["fallback"] == "unavailable"
    # With nothing to fall back to, the caller still gets a quick, honest 503; a refused request is not retried elsewhere.
    monkeypatch.setattr(B, "fallback_engine", lambda *args, **kwargs: None)
    result = api.post("/api/v2/decisions", json={"state": {"team": "Acme"}, "questions": QUESTIONS}, headers=headers())
    assert result.status_code == 503 and result.json()["error"]["code"] == "judge_unavailable"
    jev.fail = J.JudgeError("invalid", "TypeSafe refused the request", 422)
    monkeypatch.setattr(B, "fallback_engine", lambda *args, **kwargs: backup)
    result = api.post("/api/v2/decisions", json={"state": {"team": "Acme"}, "questions": QUESTIONS}, headers=headers())
    assert result.status_code == 422 and len(backup.calls) == 1


def test_the_server_asks_typesafe_once_and_briefly():
    from clients import judge as J
    seen = []
    def opener(request, timeout):
        seen.append(timeout)
        raise TimeoutError()
    engine = J.direct("key", timeout=B.JEV_TIMEOUT, retries=0, opener=opener, sleep=lambda s: None)
    try:
        engine({"team": "Acme"}, QUESTIONS)
    except J.JudgeError as exc:
        assert exc.retryable
    assert seen == [B.JEV_TIMEOUT] and B.JEV_TIMEOUT <= 10
