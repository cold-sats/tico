"""Demo mode: a fixed fictional company that passes the app's own rules, cannot be mistaken for an
install, listens only where it may, and never touches the network."""

import socket
import sqlite3
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

from backend import demo
from backend.app import create_app

NOW = datetime(2026, 9, 25, 18, 30, tzinfo=timezone.utc)      # a Friday, so a week in review exists


@pytest.fixture(scope="module")
def built(tmp_path_factory):
    directory = tmp_path_factory.mktemp("demo")
    return directory, demo.build(directory, now=NOW)


def rows(path):
    with sqlite3.connect(path) as db:
        return {table: db.execute(f'SELECT * FROM "{table}" ORDER BY 1,2').fetchall()
                for (table,) in db.execute("SELECT name FROM sqlite_master WHERE type='table' "
                                           "AND name NOT LIKE 'sqlite_%' ORDER BY name")}


def test_the_same_moment_builds_the_same_company(built, tmp_path):
    other = demo.build(tmp_path, now=NOW)
    first, second = rows(built[1].db_path), rows(other.db_path)
    assert first.keys() == second.keys()
    for table in first:
        assert first[table] == second[table], table


def signed_in(settings):
    client = TestClient(create_app(settings), base_url="http://127.0.0.1:8765")
    client.headers["Authorization"] = "Bearer " + settings.local_owner_token_file.read_text().strip()
    return client


def test_the_sample_company_is_rich_and_valid(built):
    settings = built[1]
    with sqlite3.connect(settings.db_path) as db:
        assert db.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert db.execute("PRAGMA foreign_key_check").fetchall() == []
        assert db.execute("SELECT count(*) FROM jobs WHERE state='queued'").fetchone()[0] == 0
        assert db.execute("SELECT count(*) FROM humans WHERE email NOT LIKE '%@acme.example'").fetchone()[0] == 0
    with signed_in(settings) as api:
        read = lambda path: api.get(path).json()
        assert api.get("/healthz").status_code == 200
        config = read("/api/v2/config")
        assert config["demo"] is True and config["company_name"] == "Acme"
        assert {b["name"] for b in read("/api/employees")} >= {"coo", "botops", "support", "sales", "inbox", "content"}
        assert len(read("/api/v2/updates?limit=100")["updates"]) >= 30
        assert {t["status"] for t in read("/api/v2/tasks?status=all")["tasks"]} >= {"open", "doing", "waiting", "review", "done", "declined"}
        needs = read("/api/v2/needs-you")["items"]
        assert {"approval", "task", "declined"} <= {item["kind"] for item in needs}
        assert len(read("/api/meetings")) == 3 and read("/api/meetings")[0]["title"]
        assert read("/api/v2/docs")["docs"] and read("/api/v2/linked-docs")["linked"]
        assert len(read("/api/v2/market/entities")["entities"]) >= 7
        assert read("/api/v2/goals")
        health = read("/api/v2/health")
        assert health["attention"] == 0 and all(check["status"] in ("ok", "info") for check in health["checks"])
        assert len([c for c in health["computers"] if c["online"]]) == 2
        for path in ("/api/me", "/api/people", "/api/status", "/api/v2/status", "/api/v2/org", "/api/v2/getting-started",
                     "/api/v2/providers", "/api/v2/routines", "/api/v2/conversations", "/api/v2/access", "/api/v2/catalog"):
            assert api.get(path).status_code == 200, path


def test_a_message_to_a_bot_is_answered_that_this_is_a_demo(built):
    settings = built[1]
    with signed_in(settings) as api:
        sent = api.post("/api/v2/chat/support", json={"text": "Can you refund order 41?"},
                        headers={"Idempotency-Key": "demo-test-1"}).json()["message"]
        demo.tick(api.app.state.store)
        thread = api.get(f"/api/v2/conversations/{sent['conversation_id']}/messages").json()["messages"]
        assert thread[-1]["from_actor"] == "bot:support" and "demo" in thread[-1]["body"]


def test_starting_a_bot_explains_that_this_is_a_demo(built):
    with signed_in(built[1]) as api:
        for path in ("/api/v2/tasks/anything/run-now", "/api/v2/routines/support:triage/run", "/api/v2/page-chat"):
            reply = api.post(path, json={}, headers={"Idempotency-Key": "demo-test-2"})
            assert reply.status_code == 409 and reply.json()["error"]["code"] == "demo", path
            assert "demo" in reply.json()["error"]["detail"]


def test_only_localhost_may_ask(built):
    with signed_in(built[1]) as api:
        assert api.get("/api/v2/config", headers={"Host": "192.168.1.20:8765"}).status_code == 421
        assert api.get("/api/v2/config", headers={"Host": "localhost:8765"}).status_code == 200


def test_the_first_page_visit_signs_in(built):
    with TestClient(create_app(built[1]), base_url="http://127.0.0.1:8765", follow_redirects=False) as api:
        first = api.get("/")
        assert first.status_code == 302 and first.headers["location"].startswith("/api/v2/local-signin?token=")
        followed = api.get(first.headers["location"])
        assert followed.status_code == 302 and "tico_local_session" in followed.headers["set-cookie"]
        assert api.get("/api/me").status_code == 200


def test_a_public_demo_is_read_only(tmp_path):
    settings = demo.build(tmp_path, now=NOW, url="https://demo.example.com", public=True)
    with signed_in(settings) as api:
        api.headers["Host"] = "demo.example.com"
        assert api.get("/api/v2/config").status_code == 200
        blocked = api.post("/api/v2/tasks", json={"title": "x", "owner": "bot:support"}, headers={"Idempotency-Key": "p1"})
        assert blocked.status_code == 403 and blocked.json()["error"]["code"] == "demo"
        assert api.post("/api/v2/updates/read", json={"ids": []}, headers={"Idempotency-Key": "p2"}).status_code == 200


@pytest.mark.parametrize("host", ["0.0.0.0", "192.168.1.20", "demo.example.com", ""])
def test_a_non_loopback_address_is_refused(host):
    with pytest.raises(SystemExit) as refusal:
        demo.check_bind(host)
    assert "--public-demo" in str(refusal.value)
    with pytest.raises(SystemExit):
        demo.main(["--host", host or "0.0.0.0"])     # refused before anything is built or started


@pytest.mark.parametrize("host", ["127.0.0.1", "localhost", "::1", "[::1]"])
def test_loopback_is_allowed(host):
    demo.check_bind(host)


def test_a_public_demo_and_a_container_may_bind_widely():
    demo.check_bind("0.0.0.0", public_demo=True)
    demo.check_bind("0.0.0.0", in_container=True)
    with pytest.raises(SystemExit):
        demo.main(["--public-demo"])                  # it needs the address people will open


def test_nothing_leaves_the_machine(built):
    server = socket.socket()
    server.bind(("127.0.0.1", 0))
    server.listen()
    demo.ATTEMPTS.clear()
    with demo.network_blocked():
        for target in (("example.com", 80), ("93.184.216.34", 443)):
            with pytest.raises(OSError, match="no outbound"):
                socket.create_connection(target, timeout=1)
        with pytest.raises(OSError):
            socket.getaddrinfo("api.github.com", 443)
        socket.create_connection(server.getsockname(), timeout=1).close()      # this machine is fine
        with signed_in(built[1]) as api:                                       # and so is every page of the demo
            for path in ("/api/v2/config", "/api/v2/health", "/api/v2/updates", "/api/v2/market/entities"):
                assert api.get(path).status_code == 200
            assert api.post("/api/v2/market/ask", json={"question": "Who competes with us?"},
                            headers={"Idempotency-Key": "net-1"}).status_code == 200      # falls back to the graph, no model
    server.close()
    assert demo.ATTEMPTS == ["example.com", "93.184.216.34", "api.github.com"]     # only the three we tried
    with pytest.raises(OSError):                                                   # and the block is gone outside
        socket.create_connection(("192.0.2.1", 9), timeout=0.2)


def test_the_update_check_is_off(built):
    from backend import releases
    assert releases.Checker.enabled() is False
