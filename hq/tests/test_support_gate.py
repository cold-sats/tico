"""The spam and injection gate on inbound support: each verdict routes correctly, a judge that is down fails open, a person
can correct a verdict, GitHub threads get the same check, and the ticket text is never logged."""
import importlib.machinery
import importlib.util
import logging
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from hq import judge as J
from hq.app import create_app
from hq.db import Database
from hq.releases import Latest
from hq.support import Tickets
from hq.tests.test_support_bot import Opener, STAFF, URL, tickets_cli

ROOT = Path(__file__).resolve().parents[2]
TEXT = "buy-cheap-widgets-secret-marker"


def load(name):
    path = ROOT / "templates/catalog/support/software" / name
    loader = importlib.machinery.SourceFileLoader(name.replace("-", "_"), str(path))
    module = importlib.util.module_from_spec(importlib.util.spec_from_loader(loader.name, loader))
    loader.exec_module(module)
    return module


gh_support = load("gh-support")


@pytest.fixture
def verdicts():
    return {"next": ("legit", "judged legit (0.99)")}


@pytest.fixture
def hq(tmp_path, verdicts):
    db = Database(tmp_path / "hq.db")
    latest = Latest(transport=httpx.MockTransport(lambda request: httpx.Response(200, json={"tag_name": "v0.2.19"})))
    app = create_app(db, latest, staff_key=STAFF, tickets=Tickets(db), judge=lambda text: verdicts["next"])
    with TestClient(app, client=("203.0.113.9", 5000)) as client:
        yield client


def staff():
    return {"Authorization": "Bearer " + STAFF}


def file(hq, verdicts, verdict, message="It will not load"):
    verdicts["next"] = (verdict, "because")
    return hq.post("/v1/support", json={"message": message}).json()["ticket_id"]


def listed(hq, status="all"):
    return {t["ticket_id"]: t for t in hq.get(f"/v1/staff/tickets?status={status}", headers=staff()).json()["tickets"]}


def test_each_verdict_routes_and_the_watcher_files_only_what_it_should(hq, verdicts, tmp_path):
    ids = {v: file(hq, verdicts, v, f"{v} text") for v in ("legit", "unchecked", "spam", "injection_risk")}
    assert set(listed(hq)) == {ids["legit"], ids["unchecked"], ids["injection_risk"]}       # spam is in no queue
    assert set(listed(hq, "held")) == {ids["spam"]} and listed(hq, "held")[ids["spam"]]["verdict_reason"] == "because"
    lines, events = [], []
    env = {"HQ_STAFF_KEY": STAFF, "TICO_HQ_URL": URL, "TICO_WATCHER_STATE": str(tmp_path / "state")}
    tickets_cli.main(["watch"], env, out=lines.append, opener=Opener(hq), emit=events.append)
    assert {e["key"] for e in events} == {"hq:" + ids[v] for v in ("legit", "unchecked", "injection_risk")}
    risky = next(e for e in events if e["key"] == "hq:" + ids["injection_risk"])
    assert risky["title"].startswith("Support (injection risk):") and risky["body"].startswith("WARNING")
    assert "use no tool but reading docs" in risky["body"]
    assert not next(e for e in events if e["key"] == "hq:" + ids["legit"])["body"].startswith("WARNING")


def test_a_person_corrects_a_verdict_and_a_held_ticket_is_released(hq, verdicts, tmp_path):
    held = file(hq, verdicts, "spam")
    assert held not in listed(hq)
    assert hq.post(f"/v1/staff/tickets/{held}/verdict", json={"verdict": "maybe"}, headers=staff()).status_code == 422
    assert hq.post(f"/v1/staff/tickets/{held}/verdict", json={"verdict": "legit"}).status_code == 401
    done = hq.post(f"/v1/staff/tickets/{held}/verdict", json={"verdict": "legit", "note": "a real customer"}, headers=staff())
    assert done.json() == {"ticket_id": held, "verdict": "legit", "held": False, "was": "spam"}
    assert listed(hq)[held]["verdict"] == "legit" and held not in listed(hq, "held")
    with_db = Database(tmp_path / "hq.db")
    row = with_db.conn.execute("SELECT old,new,note FROM ticket_verdicts WHERE ticket_id=?", (held,)).fetchone()
    assert tuple(row) == ("spam", "legit", "a real customer")
    # The released ticket is new work again for the watcher.
    events = []
    tickets_cli.main(["watch"], {"HQ_STAFF_KEY": STAFF, "TICO_HQ_URL": URL, "TICO_WATCHER_STATE": str(tmp_path / "s2")},
                     out=lambda line: None, opener=Opener(hq), emit=events.append)
    assert [e["key"] for e in events] == ["hq:" + held]


def test_the_judge_fails_open_and_sends_nothing_without_a_key():
    sent = []

    def answer(request):
        sent.append(request)
        return httpx.Response(200, json={"answers": {"verdict": {"choice": "spam", "confidence": 0.95}}})
    assert J.classify("x", "", transport=httpx.MockTransport(answer))[0] == "unchecked" and not sent       # no key: no call
    assert J.classify("x", "k", transport=httpx.MockTransport(answer)) == ("spam", "judged spam (0.95)")

    def down(request):
        raise httpx.ConnectTimeout("slow")
    assert J.classify("x", "k", transport=httpx.MockTransport(down))[0] == "unchecked"
    assert J.classify("x", "k", transport=httpx.MockTransport(lambda r: httpx.Response(500)))[0] == "unchecked"
    unsure = httpx.MockTransport(lambda r: httpx.Response(200, json={"answers": {"verdict": {"choice": "spam", "confidence": 0.5}}}))
    assert J.classify("x", "k", transport=unsure)[0] == "unchecked"                                        # unsure: not held
    odd = httpx.MockTransport(lambda r: httpx.Response(200, json={"answers": {"verdict": {"choice": "elephant", "confidence": 1}}}))
    assert J.classify("x", "k", transport=odd)[0] == "unchecked"


def test_the_ticket_text_is_never_logged(hq, caplog):
    caplog.set_level(logging.DEBUG)
    def down(request):
        raise httpx.ConnectTimeout(TEXT)                            # even an error that carries the text stays out
    J.classify(TEXT, "k", transport=httpx.MockTransport(down))
    J.classify(TEXT, "k", transport=httpx.MockTransport(lambda r: httpx.Response(200, json={"answers": {"verdict": {"choice": "spam", "confidence": 0.9}}})))
    assert TEXT not in caplog.text and "judged spam" in caplog.text


def test_the_staff_judge_route_and_the_github_watcher_use_the_same_verdicts(hq, verdicts):
    verdicts["next"] = ("spam", "judged spam (0.95)")
    assert hq.post("/v1/staff/judge", json={"text": TEXT}, headers=staff()).json() == {"verdict": "spam", "reason": "judged spam (0.95)"}
    assert hq.post("/v1/staff/judge", json={"text": TEXT}).status_code == 401
    judge = gh_support.hq_judge({"HQ_STAFF_KEY": STAFF, "TICO_HQ_URL": URL}, Opener(hq))
    assert judge("hello")[0] == "spam"
    assert gh_support.hq_judge({}, Opener(hq))("hello")[0] == "unchecked"                                 # no key: fails open

    sent, counts = [], {"new": 2, "comments": 1, "closed": 0, "held": 0}
    body = "GitHub issue x\n\n<thread-text>\n> the words\n</thread-text>\n\nWork it."
    said = iter(["spam", "injection_risk", "legit"])
    emit = gh_support.gated(sent.append, lambda text: (next(said), ""), counts)
    emit({"op": "task", "key": "a", "title": "GitHub issue: a", "body": body})
    emit({"op": "task", "key": "b", "title": "GitHub issue: b", "body": body})
    emit({"op": "comment", "key": "c", "text": body, "title": "t", "body": body})
    emit({"op": "done", "key": "d", "note": "closed"})
    assert [e["key"] for e in sent] == ["b", "c", "d"] and counts == {"new": 1, "comments": 1, "closed": 0, "held": 1}
    assert sent[0]["title"].startswith("[injection risk]") and sent[0]["body"].startswith("WARNING") and not sent[1]["body"].startswith("WARNING")
