"""The SCIM 2.0 endpoint an identity provider pushes people to (Okta, Entra, JumpCloud)."""
import json
import uuid

import pytest

from backend.tests.test_directory import events, roster_of
from backend.tests.test_onboarding import OWNER_EMAIL, environment, signed_in  # noqa: F401
from backend.tests.test_people_access import person_headers

USER = "urn:ietf:params:scim:schemas:core:2.0:User"
ENTERPRISE = "urn:ietf:params:scim:schemas:extension:enterprise:2.0:User"
PATCH = "urn:ietf:params:scim:api:messages:2.0:PatchOp"


@pytest.fixture
def scim(environment):
    api = environment()
    token = api.post("/api/v2/directory/scim-token", json={}, headers=signed_in()).json()["token"]
    r = api.put("/api/v2/directory", json={"source": "scim", "expected_revision": 0}, headers=signed_in())
    assert r.status_code == 200, r.text
    api.scim_headers = {"Authorization": "Bearer " + token, "Content-Type": "application/scim+json"}
    return api


def call(api, method, path, body=None, headers=None, expected=None, **kw):
    r = api.request(method, "/scim/v2" + path, content=None if body is None else json.dumps(body),
                    headers=headers if headers is not None else api.scim_headers, **kw)
    if expected:
        assert r.status_code == expected, r.text
    return r


def create(api, email="kim@acme.example", **more):
    body = {"schemas": [USER], "userName": email, "name": {"givenName": "Kim", "familyName": "Lee"},
            "title": "Designer", "emails": [{"value": email, "type": "work", "primary": True}], "active": True,
            "externalId": "ext-" + email, "password": "ignored", **more}
    return call(api, "POST", "/Users", body)


def test_auth_is_a_bearer_token_and_the_endpoint_is_off_until_scim_is_the_source(environment):
    api = environment()
    assert api.get("/scim/v2/Users").status_code == 401                          # no token at all
    token = api.post("/api/v2/directory/scim-token", json={}, headers=signed_in()).json()["token"]
    assert token.startswith("scim_")
    good = {"Authorization": "Bearer " + token}
    assert api.get("/scim/v2/Users", headers=good).status_code == 401           # source is not scim yet
    api.put("/api/v2/directory", json={"source": "scim", "expected_revision": 0}, headers=signed_in())
    assert api.get("/scim/v2/Users", headers=good).status_code == 200
    assert api.get("/scim/v2/Users", headers={"Authorization": token}).status_code == 200   # Okta header auth, verbatim
    for bad in ({"Authorization": "Bearer nope"}, {"Authorization": "Basic " + token}, {}):
        r = api.get("/scim/v2/Users", headers=bad)
        assert r.status_code == 401 and r.headers["www-authenticate"] == "Bearer"
        assert r.headers["content-type"].startswith("application/scim+json")
        assert r.json()["schemas"] == ["urn:ietf:params:scim:api:messages:2.0:Error"]
    # A person's API token or the owner's session is not the SCIM token.
    assert api.get("/scim/v2/Users", headers=person_headers(api, "riley")).status_code == 401
    assert api.get("/scim/v2/Users", headers=signed_in()).status_code == 401
    with api.app.state.store.read() as c:
        assert token not in json.dumps([dict(r) for r in c.execute("SELECT * FROM registry_metadata")])   # hash only


def test_only_the_owner_creates_the_token(environment):
    api = environment()
    r = api.post("/api/v2/directory/scim-token", json={}, headers=person_headers(api, "riley"))
    assert r.status_code == 403


def test_entra_test_connection_gets_an_empty_list(scim):
    r = call(scim, "GET", '/Users?filter=userName eq "0f1b6c3e-9a5b-4c1e-8f33-0d1e2f3a4b5c"')
    assert r.status_code == 200 and r.headers["content-type"].startswith("application/scim+json")
    assert r.json() == {"schemas": ["urn:ietf:params:scim:api:messages:2.0:ListResponse"], "totalResults": 0,
                        "startIndex": 1, "itemsPerPage": 0, "Resources": []}
    assert call(scim, "GET", "/Groups?excludedAttributes=members&filter=displayName eq \"x\"").json()["totalResults"] == 0


def test_create_returns_201_and_a_duplicate_is_409(scim):
    r = create(scim)
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["userName"] == "kim@acme.example" and body["active"] is True and body["externalId"] == "ext-kim@acme.example"
    assert body["name"]["givenName"] == "Kim" and body["title"] == "Designer" and "password" not in body
    assert r.headers["location"].endswith("/scim/v2/Users/" + body["id"])
    again = create(scim)
    assert again.status_code == 409 and again.json()["scimType"] == "uniqueness"
    people = roster_of(scim)
    assert people["kim@acme.example"]["directory"] == "scim" and people["kim@acme.example"]["name"] == "Kim Lee"
    assert len(events(scim, "directory.person_added")) == 1                     # the replay changed nothing


def test_filter_by_username_case_insensitively_quoted_or_bare_and_and_joins(scim):
    kim = create(scim).json()
    for text in ('userName eq "KIM@acme.example"', "userName eq kim@acme.example", 'USERNAME EQ "kim@acme.example"',
                 'externalId eq "ext-kim@acme.example"', f'id eq "{kim["id"]}"',
                 'userName eq "kim@acme.example" and externalId eq "ext-kim@acme.example"'):
        r = call(scim, "GET", "/Users?filter=" + text)
        assert r.json()["totalResults"] == 1, text
        assert r.json()["Resources"][0]["id"] == kim["id"]
    assert call(scim, "GET", '/Users?filter=userName sw "k"').status_code == 400
    assert call(scim, "GET", '/Users?filter=userName sw "k"').json()["scimType"] == "invalidFilter"


def test_pagination_is_one_based_and_capped(scim):
    for n in range(5):
        create(scim, f"u{n}@acme.example")
    total = call(scim, "GET", "/Users").json()["totalResults"]                   # the environment's own people too
    page = call(scim, "GET", "/Users?startIndex=2&count=2").json()
    assert page["totalResults"] == total and page["startIndex"] == 2 and page["itemsPerPage"] == 2
    everyone = call(scim, "GET", "/Users?count=1000").json()
    assert everyone["itemsPerPage"] == total <= 200
    assert [u["id"] for u in page["Resources"]] == [u["id"] for u in everyone["Resources"][1:3]]
    assert call(scim, "GET", "/Users?count=0").json()["Resources"] == []
    assert call(scim, "GET", "/Users?startIndex=abc").status_code == 400


def test_okta_deactivates_with_a_pathless_patch_and_the_user_stays_listed(scim):
    kim = create(scim).json()
    with scim.app.state.store.transaction() as c:
        c.execute("INSERT INTO human_tokens(id,human,label,token_hash,created,created_by) VALUES(?,?,?,?,?,?)",
                  (uuid.uuid4().hex, kim["id"], "t", "h", "2026-01-01T00:00:00+00:00", "test"))
    body = {"schemas": [PATCH], "Operations": [{"op": "replace", "value": {"active": False}}]}
    r = call(scim, "PATCH", "/Users/" + kim["id"], body)
    assert r.status_code == 200 and r.json()["active"] is False
    assert roster_of(scim)["kim@acme.example"]["hidden"] is True                 # left, not deleted
    with scim.app.state.store.read() as c:
        assert c.execute("SELECT COUNT(*) FROM human_tokens WHERE human=? AND revoked_at IS NULL", (kim["id"],)).fetchone()[0] == 0
    assert call(scim, "GET", "/Users/" + kim["id"]).json()["active"] is False
    call(scim, "PATCH", "/Users/" + kim["id"], body, expected=200)             # replayed: same state, one event
    assert len(events(scim, "directory.person_left")) == 1
    back = call(scim, "PATCH", "/Users/" + kim["id"], {"schemas": [PATCH], "Operations": [
        {"op": "replace", "value": {"active": True}}]})
    assert back.json()["active"] is True and roster_of(scim)["kim@acme.example"]["hidden"] is False


def test_entra_patch_uses_capitalised_ops_text_booleans_and_attribute_paths(scim):
    kim, boss = create(scim).json(), create(scim, "boss@acme.example", externalId="boss-ext").json()
    ops = [{"op": "Replace", "path": "name.familyName", "value": "Park"},
           {"op": "Replace", "path": "title", "value": "Lead Designer"},
           {"op": "Replace", "path": 'emails[type eq "work"].value', "value": "other@acme.example"},   # mapped separately
           {"op": "Add", "path": ENTERPRISE + ":manager", "value": "boss-ext"},
           {"op": "Add", "path": "addresses[type eq \"work\"].country", "value": "ML"}]              # ignored
    r = call(scim, "PATCH", "/Users/" + kim["id"], {"schemas": [PATCH], "Operations": ops})
    assert r.status_code == 200, r.text
    row = roster_of(scim)["kim@acme.example"]
    assert row["name"] == "Kim Park" and row["title"] == "Lead Designer" and row["reports_to"] == boss["id"]
    assert r.json()[ENTERPRISE]["manager"]["value"] == boss["id"]
    off = call(scim, "PATCH", "/Users/" + kim["id"], {"schemas": [PATCH], "Operations": [
        {"op": "Replace", "path": "active", "value": "False"}]})
    assert off.json()["active"] is False


def test_put_replaces_the_profile_and_delete_marks_left(scim):
    kim = create(scim).json()
    body = {"schemas": [USER], "userName": "kim@acme.example", "displayName": "Kimberly Lee", "title": "VP", "active": True}
    r = call(scim, "PUT", "/Users/" + kim["id"], body, expected=200)
    assert r.json()["displayName"] == "Kimberly Lee" and r.json()["title"] == "VP"
    call(scim, "DELETE", "/Users/" + kim["id"], expected=204)
    call(scim, "DELETE", "/Users/" + kim["id"], expected=204)                  # idempotent
    assert roster_of(scim)["kim@acme.example"]["hidden"] is True
    assert call(scim, "GET", "/Users/nobody").status_code == 404
    assert call(scim, "PUT", "/Users/" + kim["id"], {**body, "userName": "renamed@acme.example"}).status_code == 400


def test_people_added_by_hand_and_the_owner_cannot_be_deactivated_by_scim(scim):
    hand = scim.post("/api/v2/access/people", json={"name": "Hand Made", "email": "hand@acme.example"}, headers=signed_in())
    assert hand.status_code == 200
    ids = {p["email"]: p["id"] for p in roster_of(scim).values()}
    off = {"schemas": [PATCH], "Operations": [{"op": "replace", "value": {"active": False}}]}
    for email in ("hand@acme.example", OWNER_EMAIL):
        r = call(scim, "PATCH", "/Users/" + ids[email], off)
        assert r.status_code == 200 and r.json()["active"] is True              # truthful: nothing changed
    assert not roster_of(scim)[OWNER_EMAIL]["hidden"] and not roster_of(scim)["hand@acme.example"]["hidden"]
    assert call(scim, "POST", "/Users", {"schemas": [USER], "userName": "hand@acme.example"}).status_code == 409
    # It may fill a blank on someone added by hand, but not overwrite.
    r = call(scim, "PATCH", "/Users/" + ids["hand@acme.example"], {"schemas": [PATCH], "Operations": [
        {"op": "replace", "path": "title", "value": "Ops"}, {"op": "replace", "path": "displayName", "value": "Overwrite"}]})
    row = roster_of(scim)["hand@acme.example"]
    assert row["title"] == "Ops" and row["name"] == "Hand Made"


def test_a_burst_of_deactivations_stops_at_the_mass_leave_limit(scim):
    scim.put("/api/v2/directory", json={"source": "scim", "mass_leave_limit": 2, "expected_revision": 1}, headers=signed_in())
    ids = [create(scim, f"u{n}@acme.example").json()["id"] for n in range(3)]
    off = {"schemas": [PATCH], "Operations": [{"op": "replace", "path": "active", "value": False}]}
    assert [call(scim, "PATCH", "/Users/" + i, off).status_code for i in ids] == [200, 200, 429]
    assert call(scim, "PATCH", "/Users/" + ids[2], off).headers["retry-after"] == "3600"
    assert events(scim, "directory.scim_guard") and roster_of(scim)["u2@acme.example"]["hidden"] is False


def test_discovery_endpoints_and_unsupported_groups(scim):
    cfg = call(scim, "GET", "/ServiceProviderConfig", expected=200).json()
    assert cfg["patch"]["supported"] is True and cfg["bulk"]["supported"] is False
    assert cfg["authenticationSchemes"][0]["type"] == "oauthbearertoken"
    assert call(scim, "GET", "/ResourceTypes", expected=200).json()["Resources"][0]["endpoint"] == "/Users"
    assert call(scim, "GET", "/Schemas", expected=200).json()["totalResults"] == 2
    assert call(scim, "POST", "/Groups", {"displayName": "x"}).status_code == 501
    assert call(scim, "POST", "/Users", {"userName": "not-an-email"}).status_code == 400
    assert scim.post("/scim/v2/Users", content="{", headers=scim.scim_headers).status_code == 400
