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


def signed_in(settings):
    client = TestClient(create_app(settings), base_url="http://127.0.0.1:8765")
    client.headers["Authorization"] = "Bearer " + settings.local_owner_token_file.read_text().strip()
    return client


def test_only_localhost_may_ask(built):
    with signed_in(built[1]) as api:
        assert api.get("/api/v2/config", headers={"Host": "192.168.1.20:8765"}).status_code == 421
        assert api.get("/api/v2/config", headers={"Host": "localhost:8765"}).status_code == 200


def test_a_public_demo_is_read_only(tmp_path):
    settings = demo.build(tmp_path, now=NOW, url="https://demo.example.com", public=True)
    with signed_in(settings) as api:
        api.headers["Host"] = "demo.example.com"
        assert api.get("/api/v2/config").status_code == 200
        blocked = api.post("/api/v2/tasks", json={"title": "x", "owner": "bot:support"}, headers={"Idempotency-Key": "p1"})
        assert blocked.status_code == 403 and blocked.json()["error"]["code"] == "demo"
        assert api.post("/api/v2/updates/read", json={"ids": []}, headers={"Idempotency-Key": "p2"}).status_code == 200


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



def test_a_local_demo_uses_its_explicit_address_and_accepts_its_browser_origin(tmp_path, monkeypatch):
    settings = demo.prepare(tmp_path, url="http://localhost:8877")
    assert settings.public_url == settings.runner_url == "http://localhost:8877"
    assert settings.allows_origin("http://127.0.0.1:8877")
    assert not settings.allows_origin("http://localhost:8765")

    import uvicorn
    import backend.app as app_module
    seen = {}
    monkeypatch.setattr(demo, "build", lambda directory, url, public: demo.prepare(directory, url, public))
    monkeypatch.setattr(app_module, "create_app", lambda settings: settings)
    monkeypatch.setattr(uvicorn, "run", lambda settings, **kwargs: seen.update(public=settings.public_url, runner=settings.runner_url))
    demo.main(["--port", "8877", "--data-dir", str(tmp_path / "port-only")])
    assert seen["public"] == seen["runner"] == "http://127.0.0.1:8877"


def test_demo_runs_message_sources_and_deliverables_are_browsable(built):
    from backend import demo_content
    with signed_in(built[1]) as api:
        runs = api.get("/api/runs").json()
        assert len(runs) == len(demo_content.TURNS)
        assert all(run["exit"] == 0 for run in runs)
        bots = api.get("/api/v2/messaging/bots").json()["bots"]
        assert any(source["kind"] == "email" for bot in bots for source in bot["sources"])
        assert any(source["kind"] == "slack" for bot in bots for source in bot["sources"])
        mail = api.get("/api/v2/mail/messages").json()["messages"]
        assert len(mail) == 3 and any("DRAFT" in message["labels"] for message in mail)
        report = api.get("/api/v2/bots/content/files").json()["files"][0]
        assert report["version"] == 2
        csv = api.get("/api/v2/bots/support/files").json()["files"][0]
        assert csv["mime"] == "text/csv"
        link = api.get("/api/v2/bots/sales/files").json()["files"][0]
        assert link["locator"] == "remote_link"
