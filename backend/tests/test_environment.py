"""One backend process serves one company, named and signed in by configuration alone.

Nothing here reads Acme's registry: the environment is Acme, its app is Atlas, and its owner
is Morgan, so a value that leaked back into the code would fail rather than pass by accident.
"""

import json
import uuid

import pytest
import yaml
from fastapi.testclient import TestClient

from backend import manage
from backend.app import create_app
from backend.auth import LOCAL_COOKIE
from backend.config import Settings
from backend.store import H, encode, repo_url

COMPANY = {"environment_id": "acme-7", "company_name": "Acme", "app_name": "Atlas",
           "assistant_name": "Morgan", "assistant_bot": "coo", "github_owner": "AcmeCorp"}
OWNER_EMAIL = "Morgan@ACME.example"
PEOPLE = {"default_user": "morgan", "people": [
    {"id": "morgan", "name": "Morgan Reed", "email": "Morgan@acme.example", "primary_for": ["*"]},
    {"id": "riley", "name": "Riley Quinn", "email": "riley@acme.example", "primary_for": ["support"]}]}
BOTS = {"coo": {"name": "coo", "runtime": "fake", "status": "active"},
        "support": {"name": "support", "runtime": "fake", "status": "active"}}
REPOS = {"coo": "emp-coo", "support": "OtherOrg/support-bot"}
TOKEN = "local-owner-secret-token-0123456789"


def local_token_file(tmp_path, token=TOKEN):
    path = tmp_path / "local-token"
    path.write_text(token)
    path.chmod(0o600)
    return path


@pytest.fixture
def environment(tmp_path):
    """Build one configured environment per call; each gets its own database and registry."""
    clients = []

    def build(roster=PEOPLE, **overrides):
        registry = tmp_path / ("registry-%d" % len(clients))
        registry.mkdir()
        (registry / "hub-access.yaml").write_text(yaml.safe_dump({"private_owners": []}))
        settings = Settings(db_path=tmp_path / ("hub-%d.db" % len(clients)), registry_dir=registry,
                            **{"owner_email": OWNER_EMAIL, **COMPANY, **overrides})
        client = TestClient(create_app(settings))
        client.__enter__()
        clients.append(client)
        with client.app.state.store.transaction() as c:
            H.sync_registry(c, BOTS, roster)
            c.execute("INSERT INTO registry_metadata VALUES('people',?)", (encode(roster),))
            for slug, config in BOTS.items():
                c.execute("INSERT INTO bot_config(bot,config_json,team,operator,repo) VALUES(?,?,?,?,?)",
                          (slug, encode(config), None, "riley" if slug == "support" else "morgan",
                           REPOS[slug]))
        return client

    yield build
    for client in clients:
        client.__exit__(None, None, None)


def signed_in(token=TOKEN):
    return {"Authorization": "Bearer " + token, "Idempotency-Key": str(uuid.uuid4())}


def test_the_owner_is_whoever_TICO_OWNER_EMAIL_names_whatever_its_case(environment, tmp_path):
    api = environment(local_owner_token_file=local_token_file(tmp_path))
    me = api.get("/api/me", headers=signed_in()).json()
    assert (me["id"], me["role"], me["owner_id"]) == ("morgan", "owner", "morgan")


def test_a_world_readable_token_file_stops_local_sign_in_loudly(environment, tmp_path):
    api = environment(local_owner_token_file=local_token_file(tmp_path))
    (tmp_path / "local-token").chmod(0o644)
    refused = api.get("/api/v2/me", headers=signed_in())
    assert refused.status_code == 500 and "chmod 600" in refused.json()["error"]["detail"]


def test_local_signin_never_redirects_off_this_origin(environment, tmp_path):
    api = environment(local_owner_token_file=local_token_file(tmp_path))
    for target in ("//evil.example/steal", "https://evil.example", "not-a-path"):
        response = api.get("/api/v2/local-signin", params={"token": TOKEN, "next": target},
                           follow_redirects=False)
        assert response.headers["location"] == "/"


def test_local_signin_refuses_to_start_on_a_public_address(tmp_path):
    with pytest.raises(RuntimeError, match="loopback"):
        Settings(db_path=tmp_path / "hub.db", public_url="https://atlas.acme.example",
                 local_owner_token_file=local_token_file(tmp_path))
