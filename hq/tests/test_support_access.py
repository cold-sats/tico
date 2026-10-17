"""HQ support access: only the install opens a session (with its ticket's secret), staff calls carry nothing without
the staff key or outside a live session, and a carried call comes back with the install's own answer, or 504."""

import base64
import threading
from datetime import timedelta

import pytest

from hq import support_access
from hq.tests.test_support import STAFF, client, db, file, moment, staff, tickets, ticks  # noqa: F401


def opened(client, moment, tier="app", hours=24):
    made = file(client).json()
    expires = (moment[0] + timedelta(hours=hours)).strftime("%Y-%m-%dT%H:%M:%SZ")
    secret = {"X-Ticket-Secret": made["secret"]}
    r = client.post(f"/v1/support/{made['ticket_id']}/access", json={"tier": tier, "expires_at": expires}, headers=secret)
    assert r.status_code == 201, r.text
    return made["ticket_id"], r.json()["session"], secret


def test_only_the_install_opens_a_session(client, moment):
    made = file(client).json()
    expires = (moment[0] + timedelta(hours=2)).strftime("%Y-%m-%dT%H:%M:%SZ")
    path = f"/v1/support/{made['ticket_id']}/access"
    assert client.post(path, json={"tier": "app", "expires_at": expires}).status_code == 404
    assert client.post(path, json={"tier": "app", "expires_at": expires},
                       headers={"X-Ticket-Secret": "x" * 30}).status_code == 404
    assert client.post(path, json={"tier": "root", "expires_at": expires},
                       headers={"X-Ticket-Secret": made["secret"]}).status_code == 422
    assert client.get("/v1/staff/access", headers=staff()).json()["sessions"] == []
    tid, sid, _ = opened(client, moment)
    (live,) = client.get("/v1/staff/access", headers=staff()).json()["sessions"]
    assert live["session"] == sid and live["ticket_id"] == tid and live["tier"] == "app"


def test_staff_calls_are_refused_without_the_key_or_a_live_session(client, moment):
    tid, sid, secret = opened(client, moment)
    assert client.get(f"/v1/staff/access/{sid}/api/v2/health").status_code == 401
    assert client.get(f"/v1/staff/access/{sid}/api/v2/health", headers=staff("w" * 32)).status_code == 401
    assert client.get("/v1/staff/access/sa_" + "0" * 24 + "/api/v2/health", headers=staff()).status_code == 404
    # Another ticket's secret cannot pull or end this session.
    _, _, other = opened(client, moment)
    assert client.post(f"/v1/support/{tid}/access/{sid}/pull", headers=other).status_code == 404
    # Past its time.
    moment[0] += timedelta(hours=25)
    assert client.get(f"/v1/staff/access/{sid}/api/v2/health", headers=staff()).status_code == 409
    assert client.post(f"/v1/support/{tid}/access/{sid}/pull", headers=secret).json()["ended"] is True
    # Ended by the install.
    moment[0] -= timedelta(hours=25)
    tid, sid, secret = opened(client, moment)
    assert client.post(f"/v1/support/{tid}/access/{sid}/end", headers=secret).status_code == 200
    assert client.get(f"/v1/staff/access/{sid}/api/v2/health", headers=staff()).status_code == 409
    assert sid not in [x["session"] for x in client.get("/v1/staff/access", headers=staff()).json()["sessions"]]


def test_a_call_is_carried_to_the_install_and_its_answer_comes_back(client, moment, monkeypatch):
    monkeypatch.setattr(support_access, "PULL_WAIT", 1)
    tid, sid, secret = opened(client, moment)
    answers = []
    caller = threading.Thread(target=lambda: answers.append(client.post(
        f"/v1/staff/access/{sid}/api/v2/bots?limit=5", content=b'{"a":1}',
        headers={**staff(), "Content-Type": "application/json", "X-Tico-Support-By": "support-agent"})))
    caller.start()
    requests = []
    for _ in range(20):
        requests = client.post(f"/v1/support/{tid}/access/{sid}/pull", headers=secret).json()["requests"]
        if requests:
            break
    (carried,) = requests
    assert carried["method"] == "POST" and carried["path"] == "/api/v2/bots" and carried["query"] == "limit=5"
    assert carried["by"] == "support-agent" and base64.b64decode(carried["body_b64"]) == b'{"a":1}'
    reply = {"rid": carried["rid"], "status": 403, "content_type": "application/json",
             "body_b64": base64.b64encode(b'{"error":"no"}').decode()}
    assert client.post(f"/v1/support/{tid}/access/{sid}/reply", json={"replies": [reply]}, headers=secret).status_code == 200
    caller.join(10)
    (answer,) = answers
    assert answer.status_code == 403 and answer.json() == {"error": "no"}
    (logged,) = client.get(f"/v1/staff/access/{sid}/log", headers=staff()).json()["log"]
    assert (logged["by"], logged["method"], logged["path"], logged["status"]) == ("support-agent", "POST", "/api/v2/bots", 403)
    # Deleting the ticket deletes its sessions and their log.
    assert client.delete(f"/v1/staff/tickets/{tid}", headers=staff()).status_code == 200
    assert client.get(f"/v1/staff/access/{sid}/log", headers=staff()).status_code == 404


def test_an_install_that_does_not_answer_is_a_504(client, moment, monkeypatch):
    monkeypatch.setattr(support_access, "PROXY_WAIT", 0.2)
    _, sid, _ = opened(client, moment)
    r = client.get(f"/v1/staff/access/{sid}/api/v2/health", headers=staff())
    assert r.status_code == 504 and r.json()["error"] == "install_timeout"
