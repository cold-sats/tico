"""The v0.2.21 REST vocabulary (backend/route_renames.py): the new path is canonical, the old one still answers
for a release, marked deprecated."""
import pytest

from backend.tests.test_api import api, get, headers, post, runner  # noqa: F401

PAIRS = [("/api/humans", "/api/people"), ("/api/v2/templates", "/api/v2/catalog"),
         ("/api/v2/tools", "/api/v2/integrations"), ("/api/v2/decisions", "/api/v2/judge"),
         ("/api/v2/operations/timing", "/api/v2/ops/timing"), ("/api/v2/proposals", "/api/v2/goal-proposals"),
         ("/api/v2/setup/groups", "/api/v2/onboarding/departments"), ("/api/v2/messages", "/api/v2/inbox"),
         ("/api/v2/health/issues", "/api/v2/fleet/check")]


@pytest.mark.parametrize("new,old", PAIRS)
def test_the_old_path_answers_what_the_new_one_does(api, new, old):
    fresh, stale = api.get(new, headers=headers()), api.get(old, headers=headers())
    assert fresh.status_code == stale.status_code == 200, (fresh.text, stale.text)
    volatile = ("checked", "routes", "since", "actor_name", "actors")      # a clock, timings, display names
    strip = lambda body: {k: v for k, v in body.items() if k not in volatile} if isinstance(body, dict) else body
    assert strip(fresh.json()) == strip(stale.json())


def test_the_old_path_is_deprecated_in_openapi_and_the_new_one_is_not(api):
    paths = api.app.openapi()["paths"]
    for new, old, method in [("/api/humans", "/api/people", "get"), ("/api/v2/templates", "/api/v2/catalog", "get"),
                             ("/api/v2/computers/{rid}/revoke", "/api/v2/runners/{rid}/revoke", "post"),
                             ("/api/v2/proposals/{pid}/decide", "/api/v2/goal-proposals/{pid}/decide", "post")]:
        assert paths[old][method].get("deprecated") is True, old
        assert not paths[new][method].get("deprecated"), new
    assert "/api/v2/runners/enroll" in paths and not paths["/api/v2/runners/enroll"]["post"].get("deprecated")


def test_a_computer_is_revoked_at_either_path(api):
    for path in ("/api/v2/computers/%s/revoke", "/api/v2/runners/%s/revoke"):
        found = runner(api)
        assert api.post(path % found["runner_id"], json={}, headers=headers()).json() == {"revoked": True}


def test_messages_lists_the_unread_and_archives_read_one(api):
    assert api.get("/api/v2/messages", params={"unread": "0"}, headers=headers()).status_code == 422
    unread = api.get("/api/v2/messages", params={"unread": "1"}, headers=headers()).json()
    assert {k: v for k, v in unread.items() if k not in ("actor_name", "actors")} == api.get("/api/v2/inbox", headers=headers()).json()
    assert get(api, "archives") == {"archives": []}
    assert api.get("/api/v2/archives", params={"source": "none"}, headers=headers()).status_code == 404
    assert api.get("/api/v2/archive", params={"source": "none"}, headers=headers()).status_code == 404


def test_health_issues_is_the_snapshot_for_the_assistant_and_the_checks_for_everyone_else(api):
    from backend.auth import Identity
    api.app.state.store.settings.test_identities["ana-assistant"] = Identity(
        "human:ana", "owner", "ana@acme.example", via="assistant")
    seen = api.get("/api/v2/health/issues", headers=headers("ana-assistant"))
    assert seen.status_code == 200 and "issues" not in seen.json()
    assert set(seen.json()) == set(api.get("/api/v2/tico/fleet", headers=headers("ana-assistant")).json())
    assert "issues" in api.get("/api/v2/health/issues", headers=headers()).json()
