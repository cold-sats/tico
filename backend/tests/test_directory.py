"""Directory sync: Google and Graph fixtures, the safety rules, the audit trail and the routes."""
import json
import urllib.parse

import httpx
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from backend import directory as D
from backend import directory_sources as S
from backend import people as P
from backend.tests.test_onboarding import OWNER_EMAIL, PEOPLE, environment, signed_in  # noqa: F401
from backend.tests.test_people_access import person_headers

KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048).private_bytes(
    serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()).decode()
SERVICE_ACCOUNT = {"client_email": "tico@proj.iam.gserviceaccount.com", "private_key": KEY,
                   "token_uri": "https://oauth2.googleapis.com/token", "type": "service_account"}


def guser(email, name, **more):
    return {"id": "g-" + email.split("@")[0], "primaryEmail": email, "name": {"fullName": name},
            "orgUnitPath": "/", **more}


GOOGLE_PAGES = {
    "": {"users": [
        guser("ana@acme.example", "Ana Rivera", organizations=[{"title": "CEO", "primary": True}]),
        guser("dev@acme.example", "Dev Patel", orgUnitPath="/Eng", organizations=[{"title": "Engineer"}],
              relations=[{"type": "manager", "value": "Ana@acme.example"}])], "nextPageToken": "p2"},
    "p2": {"users": [
        guser("gone@acme.example", "Gail Gone", suspended=True, orgUnitPath="/Eng"),
        guser("old@acme.example", "Ola Old", archived=True),
        guser("sales@acme.example", "Sam Sales", orgUnitPath="/Sales/West")]},
}


def google_transport(seen):
    def handler(request):
        url = request.url
        seen.append((request.method, str(url), dict(request.headers)))
        if url.host == "oauth2.googleapis.com":
            seen[-1] += (urllib.parse.parse_qs(request.content.decode()),)
            return httpx.Response(200, json={"access_token": "g-token"})
        assert request.headers["authorization"] == "Bearer g-token"
        if url.path.endswith("/users"):
            return httpx.Response(200, json=GOOGLE_PAGES[url.params.get("pageToken", "")])
        if url.path.endswith("/groups/eng@acme.example/members"):
            return httpx.Response(200, json={"members": [{"email": "sales@acme.example", "type": "USER"},
                                                         {"email": "sub@acme.example", "type": "GROUP"}]})
        return httpx.Response(404, json={})
    return httpx.MockTransport(handler)


GOOGLE = {"service_account": SERVICE_ACCOUNT, "admin_email": "admin@acme.example"}


def test_google_maps_users_across_pages_and_reads_suspended_as_inactive(monkeypatch):
    seen = []
    monkeypatch.setattr(S, "TRANSPORT", google_transport(seen))
    records = {r["email"]: r for r in S.google_fetch(GOOGLE, {})}
    assert list(records) == ["ana@acme.example", "dev@acme.example", "gone@acme.example", "old@acme.example",
                             "sales@acme.example"]
    assert records["ana@acme.example"]["title"] == "CEO"
    assert records["dev@acme.example"]["manager"] == "ana@acme.example"        # lower-cased
    assert not records["gone@acme.example"]["active"] and not records["old@acme.example"]["active"]
    assert records["dev@acme.example"]["active"]
    token = seen[0][3]
    assert token["grant_type"] == ["urn:ietf:params:oauth:grant-type:jwt-bearer"]
    import jwt
    claims = jwt.decode(token["assertion"][0], options={"verify_signature": False})
    assert claims["sub"] == "admin@acme.example"
    assert claims["scope"] == S.GOOGLE_USER_SCOPE                                # read-only, users only
    assert "pageToken=p2" in seen[2][1] and "customer=my_customer" in seen[1][1]


def test_google_scope_filters_by_ou_group_and_domain(monkeypatch):
    monkeypatch.setattr(S, "TRANSPORT", google_transport([]))
    emails = lambda flt: [r["email"] for r in S.google_fetch(GOOGLE, flt)]      # noqa: E731
    assert emails({"org_units": ["Eng"]}) == ["dev@acme.example", "gone@acme.example"]
    assert emails({"org_units": ["/Sales"]}) == ["sales@acme.example"]           # sub-OUs are inside
    assert emails({"groups": ["eng@acme.example"]}) == ["sales@acme.example"]    # nested GROUP members ignored
    assert emails({"groups": ["eng@acme.example"], "org_units": ["/Eng"]}) == [
        "dev@acme.example", "gone@acme.example", "sales@acme.example"]
    assert emails({"domains": ["other.example"]}) == []


def gd(oid, name, mail, **more):
    return {"id": oid, "displayName": name, "mail": mail, "userPrincipalName": mail or name + "@acme.onmicrosoft.com",
            "userType": "Member", "accountEnabled": True, **more}


def graph_transport(seen):
    def handler(request):
        url = request.url
        seen.append((str(url), dict(request.headers)))
        if url.host == "login.microsoftonline.com":
            assert url.path == "/tenant-1/oauth2/v2.0/token"
            form = urllib.parse.parse_qs(request.content.decode())
            assert form["scope"] == ["https://graph.microsoft.com/.default"]
            assert form["grant_type"] == ["client_credentials"]
            return httpx.Response(200, json={"access_token": "m-token"})
        assert request.headers["authorization"] == "Bearer m-token"
        if url.path == "/v1.0/users" and not url.params.get("$skiptoken"):
            return httpx.Response(200, json={"value": [
                gd("1", "Ana", "Ana@acme.example", jobTitle="CEO"),
                gd("2", "Dev", "dev@acme.example", manager={"id": "1", "mail": "ana@acme.example"}),
                gd("3", "Off", "off@acme.example", accountEnabled=False)],
                "@odata.nextLink": "https://graph.microsoft.com/v1.0/users?$skiptoken=abc"})
        if url.path == "/v1.0/users":
            return httpx.Response(200, json={"value": [
                gd("4", "Guest", "guest@other.example", userType="Guest"),
                gd("5", "Nomail", None, userPrincipalName="not-an-email"),
                gd("6", "Upn", None, userPrincipalName="upn@acme.example")]})
        if url.path == "/v1.0/groups/g-1/members/microsoft.graph.user":
            return httpx.Response(200, json={"value": [{"id": "2"}, {"id": "6"}]})
        return httpx.Response(404, json={"error": {"message": "nope"}})
    return httpx.MockTransport(handler)


ENTRA = {"tenant": "tenant-1", "client_id": "app-1", "client_secret": "s3cret"}


def test_graph_maps_users_across_pages_and_drops_guests(monkeypatch):
    seen = []
    monkeypatch.setattr(S, "TRANSPORT", graph_transport(seen))
    records = {r["email"]: r for r in S.entra_fetch(ENTRA, {})}
    assert list(records) == ["ana@acme.example", "dev@acme.example", "off@acme.example", "upn@acme.example"]
    assert records["dev@acme.example"]["manager"] == "ana@acme.example"
    assert not records["off@acme.example"]["active"] and records["dev@acme.example"]["active"]
    assert records["ana@acme.example"]["title"] == "CEO" and records["ana@acme.example"]["external_id"] == "1"
    first = next(u for u, _ in seen if "/v1.0/users" in u)
    assert "%24top=999" in first or "$top=999" in first


def test_graph_group_filter_uses_the_user_cast_with_consistency_header(monkeypatch):
    seen = []
    monkeypatch.setattr(S, "TRANSPORT", graph_transport(seen))
    assert [r["email"] for r in S.entra_fetch(ENTRA, {"groups": ["g-1"]})] == ["dev@acme.example", "upn@acme.example"]
    group = next(h for u, h in seen if "/groups/" in u)
    assert group["consistencylevel"] == "eventual"


def test_graph_never_follows_a_next_link_off_graph(monkeypatch):
    def handler(request):
        if request.url.host == "login.microsoftonline.com":
            return httpx.Response(200, json={"access_token": "t"})
        return httpx.Response(200, json={"value": [], "@odata.nextLink": "https://evil.example/steal"})
    monkeypatch.setattr(S, "TRANSPORT", httpx.MockTransport(handler))
    with pytest.raises(Exception, match="unexpected page link"):
        S.entra_fetch(ENTRA, {})


def test_a_failed_listing_raises_instead_of_looking_like_an_empty_directory(monkeypatch):
    monkeypatch.setattr(S, "TRANSPORT", httpx.MockTransport(lambda r: httpx.Response(
        403, json={"error": {"message": "Insufficient privileges"}}) if r.url.host != "login.microsoftonline.com"
        else httpx.Response(200, json={"access_token": "t"})))
    with pytest.raises(Exception, match="Insufficient privileges"):
        S.entra_fetch(ENTRA, {})


# ------------------------------------------------------------------------------------ the engine
def person(pid, email, **more):
    return P._person({"id": pid, "name": pid.title(), "email": email, **more})


def rec(email, active=True, **more):
    return {"email": email, "name": more.pop("name", email.split("@")[0].title()), "title": "", "manager": "",
            "active": active, "external_id": "", **more}


def test_engine_only_leaves_people_its_feed_created_and_never_the_owner():
    roster = {"people": [person("owner", "owner@x.io"), person("hand", "hand@x.io"),
                         person("g", "g@x.io", directory="google"), person("e", "e@x.io", directory="entra"),
                         person("g2", "g2@x.io", directory="google")]}
    found = D.plan(roster, [rec("owner@x.io", active=False), rec("hand@x.io", active=False),
                            rec("e@x.io", active=False)], "google", "owner@x.io", True)
    # g and g2 are absent from the directory; owner, hand and the entra person are not ours to remove.
    assert sorted(x["email"] for x in found["leaves"]) == ["g2@x.io", "g@x.io"]
    assert found["protected"] == []
    roster["people"][0]["directory"] = "google"
    found = D.plan(roster, [rec("owner@x.io", active=False)], "google", "owner@x.io", True)
    assert "owner@x.io" not in [x["email"] for x in found["leaves"]]
    assert [x["email"] for x in found["protected"]] == ["owner@x.io"]


def test_engine_fills_blanks_on_hand_added_people_but_never_overwrites():
    roster = {"people": [person("hand", "hand@x.io", name="Hand Made", title="Founder"), person("blank", "blank@x.io"),
                         person("mine", "mine@x.io", title="Old", directory="google")]}
    found = D.plan(roster, [rec("hand@x.io", name="Someone Else", title="Intern"),
                            rec("blank@x.io", name="Blake Lane", title="Analyst"),
                            rec("mine@x.io", title="New")], "google", "", True)
    changes = {u["email"]: u["changes"] for u in found["updates"]}
    assert "hand@x.io" not in changes
    assert changes["blank@x.io"] == {"name": ["Blank", "Blake Lane"], "title": ["", "Analyst"]}
    assert changes["mine@x.io"]["title"] == ["Old", "New"]


def test_engine_restores_only_people_the_directory_removed():
    roster = {"people": [person("a", "a@x.io", directory="google", hidden=True, directory_left=True),
                         person("b", "b@x.io", directory="google", hidden=True)]}
    found = D.plan(roster, [rec("a@x.io"), rec("b@x.io")], "google", "", True)
    assert [x["email"] for x in found["restores"]] == ["a@x.io"]
    assert found["skipped"] == [{"email": "b@x.io", "reason": "was marked left here; not restored"}]


# ------------------------------------------------------------------------------------- the routes
def events(api, action):
    with api.app.state.store.read() as c:
        return [dict(r) for r in c.execute("SELECT * FROM events WHERE action=? ORDER BY ts, id", (action,))]


def put_config(api, revision=0, **more):
    body = {"source": "google", "filter": {}, "expected_revision": revision,
            "credentials": {"service_account_json": json.dumps(SERVICE_ACCOUNT), "admin_email": "admin@acme.example"},
            **more}
    r = api.put("/api/v2/directory", json=body, headers=signed_in())
    assert r.status_code == 200, r.text
    return r.json()["revision"]


def sync(api, **body):
    r = api.post("/api/v2/directory/sync", json=body, headers=signed_in())
    assert r.status_code == 200, r.text
    return r.json()


def roster_of(api):
    with api.app.state.store.read() as c:
        from backend.views import roster
        return {p["email"]: p for p in roster(c)["people"]}


@pytest.fixture
def google_api(environment, monkeypatch):
    users = {"users": [
        guser("ana@acme.example", "Ana Rivera"),
        guser("dev@acme.example", "Dev Patel", organizations=[{"title": "Engineer"}],
              relations=[{"type": "manager", "value": "ana@acme.example"}]),
        guser(OWNER_EMAIL, "Morgan Reed")]}
    state = {"users": users}

    def handler(request):
        if request.url.host == "oauth2.googleapis.com":
            return httpx.Response(200, json={"access_token": "g-token"})
        if request.url.path.endswith("/users"):
            return httpx.Response(200, json=state["users"])
        if "/photos/thumbnail" in request.url.path:
            return httpx.Response(200, json={"photoData": "_-8", "mimeType": "image/png"})
        return httpx.Response(404, json={})
    monkeypatch.setattr(S, "TRANSPORT", httpx.MockTransport(handler))
    api = environment()
    state["api"] = api
    return api, state


def test_first_sync_previews_then_needs_the_owner_to_confirm_that_exact_plan(google_api):
    api, _ = google_api
    put_config(api)
    r = api.post("/api/v2/directory/preview", json={}, headers=signed_in())
    preview = r.json()
    assert preview["counts"]["adds"] == 2 and preview["needs_confirmation"]["first"] is True
    assert "ana@acme.example" not in roster_of(api)                          # a preview writes nothing
    held = sync(api)
    assert held["applied"] is False and "ana@acme.example" not in roster_of(api)
    wrong = sync(api, confirm=True, plan_hash="0" * 24)
    assert wrong["applied"] is False and wrong["stale"] is True
    done = sync(api, confirm=True, plan_hash=preview["plan"]["hash"])
    assert done["applied"] is True and done["done"]["adds"] == 2
    people = roster_of(api)
    assert people["dev@acme.example"]["title"] == "Engineer"
    assert people["dev@acme.example"]["reports_to"] == people["ana@acme.example"]["id"]
    assert people["dev@acme.example"]["directory"] == "google"
    assert len(events(api, "directory.person_added")) == 2
    synced = events(api, "directory.synced")
    assert len(synced) == 1 and json.loads(synced[0]["detail_json"])["applied"]["adds"] == 2
    assert sync(api)["applied"] is True                                       # confirmed once, then routine
    assert api.get("/api/v2/directory", headers=signed_in()).json()["confirmed"] is True


def confirmed_sync(api):
    preview = api.post("/api/v2/directory/preview", json={}, headers=signed_in()).json()
    return sync(api, confirm=True, plan_hash=preview["plan"]["hash"])


def test_suspended_people_are_marked_left_and_their_tokens_revoked_not_deleted(google_api):
    api, state = google_api
    put_config(api)
    confirmed_sync(api)
    dev = roster_of(api)["dev@acme.example"]
    headers = person_headers(api, dev["id"])
    assert api.get("/api/me", headers=headers).status_code == 200
    state["users"]["users"][1]["suspended"] = True
    out = sync(api)
    assert out["applied"] is True and out["done"]["leaves"] == 1
    after = roster_of(api)["dev@acme.example"]
    assert after["hidden"] is True and after["directory_left"] is True
    with api.app.state.store.read() as c:
        assert c.execute("SELECT COUNT(*) FROM human_tokens WHERE human=? AND revoked_at IS NULL", (dev["id"],)).fetchone()[0] == 0
    assert api.get("/api/me", headers=headers).status_code in (401, 403)
    left = events(api, "directory.person_left")
    assert json.loads(left[0]["detail_json"])["reason"] == "disabled in the directory"
    state["users"]["users"][1]["suspended"] = False
    assert sync(api)["done"]["restores"] == 1
    assert roster_of(api)["dev@acme.example"]["hidden"] is False


def test_hand_added_people_and_the_owner_survive_a_directory_that_omits_them(google_api):
    api, state = google_api
    put_config(api)
    confirmed_sync(api)
    r = api.post("/api/v2/access/people", json={"name": "Hand Added", "email": "hand@acme.example"}, headers=signed_in())
    assert r.status_code == 200
    state["users"]["users"] = [state["users"]["users"][0]]                   # only Ana remains; owner not listed
    out = sync(api)
    left = {x["email"] for x in out["plan"]["leaves"]}
    assert left == {"dev@acme.example"}
    people = roster_of(api)
    assert not people["hand@acme.example"]["hidden"] and not people[OWNER_EMAIL]["hidden"]


def test_the_owner_is_protected_when_the_directory_disables_them(google_api):
    api, state = google_api
    put_config(api)
    confirmed_sync(api)
    state["users"]["users"][2]["suspended"] = True
    # Morgan was hand-added, so the feed does not own her; make the feed own her to prove the guard.
    with api.app.state.store.transaction() as c:
        row = json.loads(c.execute("SELECT value_json FROM registry_metadata WHERE key='people'").fetchone()[0])
        for p in row["people"]:
            if p["email"] == OWNER_EMAIL:
                p["directory"] = "google"
        c.execute("UPDATE registry_metadata SET value_json=? WHERE key='people'", (json.dumps(row),))
    out = sync(api)
    assert [x["email"] for x in out["plan"]["protected"]] == [OWNER_EMAIL]
    assert roster_of(api)[OWNER_EMAIL]["hidden"] is False


def test_a_sync_that_would_mark_too_many_people_left_is_held_until_confirmed(google_api):
    api, state = google_api
    put_config(api, mass_leave_limit=1)
    confirmed_sync(api)
    state["users"]["users"] = [state["users"]["users"][2]]                   # both Ana and Dev vanish
    held = sync(api)
    assert held["applied"] is False and held["needs_confirmation"] == {"first": False, "mass_leave": True}
    assert roster_of(api)["ana@acme.example"]["hidden"] is False
    done = sync(api, confirm=True, plan_hash=held["plan"]["hash"])
    assert done["applied"] is True and done["done"]["leaves"] == 2


def test_the_interval_sync_holds_instead_of_applying_a_risky_plan(google_api):
    api, state = google_api
    service = api.app.state.directory
    put_config(api, interval_minutes=5)
    with api.app.state.store.read() as c:
        assert service.due(c) is False                                        # never before the first confirmation
    confirmed_sync(api)
    state["users"]["users"] = [state["users"]["users"][2]]
    put_config(api, revision=1, mass_leave_limit=1, interval_minutes=5, credentials=None)
    with api.app.state.store.transaction() as c:
        cfg = D.load(c)
        cfg["confirmed"], cfg["last"] = True, {"at": "2020-01-01T00:00:00+00:00"}
        D.save(c, cfg)
    with api.app.state.store.read() as c:
        assert service.due(c) is True
    service.tick()
    assert roster_of(api)["ana@acme.example"]["hidden"] is False
    assert len(events(api, "directory.sync_held")) == 1
    service.tick()                                                            # same plan: no second event
    with api.app.state.store.transaction() as c:
        cfg = D.load(c)
        cfg["last"]["at"] = "2020-01-01T00:00:00+00:00"
        D.save(c, cfg)
    service.tick()
    assert len(events(api, "directory.sync_held")) == 1


def test_credentials_are_encrypted_and_never_returned(google_api):
    api, _ = google_api
    put_config(api)
    with api.app.state.store.read() as c:
        row = c.execute("SELECT * FROM directory_credentials WHERE source='google'").fetchone()
    assert b"PRIVATE KEY" not in row["ciphertext"] and b"tico@proj" not in row["ciphertext"]
    view = api.get("/api/v2/directory", headers=signed_in())
    assert "PRIVATE KEY" not in view.text
    assert view.json()["credentials"]["google"] == {"configured": True, "hint": "tico@proj.iam.gserviceaccount.com as admin@acme.example"}
    config = events(api, "directory.configured")
    assert config and "PRIVATE KEY" not in config[0]["detail_json"]


def test_only_the_owner_manages_directory_sync_and_stale_revisions_are_refused(google_api):
    api, _ = google_api
    riley = person_headers(api, "riley")
    assert api.get("/api/v2/directory", headers=riley).status_code == 403
    assert api.post("/api/v2/directory/sync", json={}, headers=riley).status_code == 403
    put_config(api)
    r = api.put("/api/v2/directory", json={"source": "", "expected_revision": 0}, headers=signed_in())
    assert r.status_code == 409


def test_a_directory_error_is_reported_and_changes_nothing(google_api, monkeypatch):
    api, _ = google_api
    put_config(api)
    monkeypatch.setattr(S, "TRANSPORT", httpx.MockTransport(lambda r: httpx.Response(401, json={"error": "unauthorized_client",
                        "error_description": "Client is unauthorized to retrieve access tokens"})))
    r = api.post("/api/v2/directory/sync", json={}, headers=signed_in())
    assert r.status_code == 502 and "unauthorized" in r.text
    last = api.get("/api/v2/directory", headers=signed_in()).json()["last"]
    assert last["ok"] is False


def test_photos_fetched_for_new_people_land_in_the_photo_cache(google_api):
    api, _ = google_api
    put_config(api)
    confirmed_sync(api)
    from backend import people_photos
    assert people_photos.cached(api.app.state.store.settings, "ana@acme.example") == (b"\xff\xef", "image/png")
