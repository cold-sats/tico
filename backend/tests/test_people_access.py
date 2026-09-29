"""People and access managed in the app: the owner, the allow list, and who has left."""

import uuid


from backend.auth import Identity
from backend.store import H, digest
from backend.tests.test_onboarding import (OWNER_EMAIL, PEOPLE, TOKEN, draft, environment,  # noqa: F401
                                           machine, signed_in)


def person_headers(api, pid):
    """A personal API token: its role is decided by the person's email, as a browser's is."""
    secret = "tok-" + pid + "-" + uuid.uuid4().hex
    with api.app.state.store.transaction() as c:
        c.execute("INSERT INTO human_tokens(id,human,label,token_hash,created,created_by) VALUES(?,?,?,?,?,?)",
                  (uuid.uuid4().hex, pid, "test", digest(secret), H.now(), "test"))
    return {"Authorization": "Bearer " + secret, "Idempotency-Key": str(uuid.uuid4())}


def view(api, headers=None, expected=200):
    r = api.get("/api/v2/access", headers=headers or signed_in())
    assert r.status_code == expected, r.text
    return r.json()


def call(api, method, path, body, headers=None, expected=200):
    r = api.request(method, "/api/v2/access" + path, json=body, headers=headers or signed_in())
    assert r.status_code == expected, r.text
    return r.json()


def transfer(api, person, headers=None, expected=200, **fields):
    body = {"person": person, "expected_revision": view(api)["owner"]["revision"], "confirm": True, **fields}
    return call(api, "POST", "/owner", body, headers, expected)


class HeaderProxy:
    """An identity proxy that trusts a test header instead of a signed assertion."""
    name = "cloudflare"

    def email(self, headers):
        return headers.get("x-test-email")


def test_only_owners_and_admins_read_access_and_only_the_owner_changes_who_signs_in(environment):
    api = environment()
    quinn, riley = person_headers(api, "quinn"), person_headers(api, "riley")     # a member, an admin
    view(api, quinn, expected=403)
    view(api, riley)
    # A member may add a coworker in the company's domain, but not someone outside it.
    call(api, "POST", "/people", {"name": "Zed", "email": "zed@other.example"}, quinn, expected=403)
    call(api, "POST", "/people/riley", {"title": "CTO"}, quinn, expected=403)
    call(api, "PUT", "/allow", {"allowed": [], "allowed_domains": ["acme.example"]}, riley, expected=403)
    call(api, "POST", "/owner", {"person": "riley", "confirm": True}, riley, expected=403)
    call(api, "POST", "/people/quinn", {"role": "admin"}, riley, expected=403)         # only an owner makes admins
    assert view(api)["owner"]["email"] == OWNER_EMAIL


def test_the_owner_adds_edits_and_makes_a_bot_admin(environment):
    api = environment()
    added = call(api, "POST", "/people", {"name": "Zed Park", "email": "Zed@Acme.example",
                                          "title": "Analyst", "team": "ops"})
    assert added["person"] == "zed"
    call(api, "POST", "/people", {"name": "Other", "email": "zed@acme.example"}, expected=409)
    call(api, "POST", "/people", {"name": "Bad", "email": "not-an-email"}, expected=422)
    call(api, "POST", "/people/zed", {"title": "Lead", "bot_admin": True, "email": "zed@new.example"})
    row = next(p for p in view(api)["people"] if p["id"] == "zed")
    assert (row["title"], row["team"], row["email"]) == ("Lead", "ops", "zed@new.example")
    assert row["bot_admin"] and row["can_sign_in"] and not row["owner"]
    # The bot administrator entry follows the person's address.
    assert api.app.state.auth.bot_admin(Identity("human:zed", "human", "zed@new.example"))
    call(api, "POST", "/people/zed", {"bot_admin": False})
    assert not api.app.state.auth.bot_admin(Identity("human:zed", "human", "zed@new.example"))
    call(api, "POST", "/people/morgan", {"bot_admin": True}, expected=409)          # the owner already can
    call(api, "POST", "/people/morgan", {"email": "m@acme.example"}, expected=409)  # identity is the email


def test_transfer_changes_who_is_owner_at_once_and_the_old_owner_loses_owner_routes(environment):
    api = environment()
    old, new = person_headers(api, "morgan"), person_headers(api, "riley")
    before = view(api, old)
    result = transfer(api, "riley", previous_owner_bot_admin=True, headers=old)
    assert result["owner"] == "riley@acme.example" and result["revision"] == before["owner"]["revision"] + 1
    # No restart: the very next requests already see the new owner.
    view(api, new)
    view(api, old)                          # an admin now: may look, but the owner routes are the owner's
    call(api, "POST", "/owner", {"person": "morgan", "confirm": True}, old, expected=403)
    call(api, "PUT", "/allow", {"allowed": [], "allowed_domains": ["acme.example"]}, old, expected=403)
    assert api.get("/api/v2/config", headers=signed_in()).json()["owner_email"] == "riley@acme.example"
    after = view(api, new)
    assert after["owner"]["person"] == "riley"
    morgan = next(p for p in after["people"] if p["id"] == "morgan")
    assert not morgan["owner"] and morgan["bot_admin"]
    auth = api.app.state.auth
    assert auth.bot_admin(Identity("human:morgan", "human", OWNER_EMAIL)) and auth.owner_email == "riley@acme.example"
    with api.app.state.store.read() as c:
        events = c.execute("SELECT actor,target,detail_json FROM events WHERE action='owner.transferred'").fetchall()
    assert len(events) == 1 and events[0]["actor"] == "human:morgan" and events[0]["target"] == "riley"
    assert "riley@acme.example" in events[0]["detail_json"]


def test_a_transfer_needs_confirmation_a_fresh_revision_and_an_active_other_person(environment):
    api = environment()
    revision = view(api)["owner"]["revision"]
    call(api, "POST", "/owner", {"person": "riley", "expected_revision": revision}, expected=422)
    call(api, "POST", "/owner", {"person": "riley", "expected_revision": revision, "confirm": False}, expected=422)
    call(api, "POST", "/owner", {"person": "riley", "expected_revision": revision + 5, "confirm": True}, expected=409)
    call(api, "POST", "/owner", {"person": "morgan", "expected_revision": revision, "confirm": True}, expected=409)
    call(api, "POST", "/owner", {"person": "nobody", "expected_revision": revision, "confirm": True}, expected=404)
    api.post("/api/v2/people/riley", json={"left": True}, headers=signed_in())
    call(api, "POST", "/owner", {"person": "riley", "expected_revision": revision, "confirm": True}, expected=404)
    assert view(api)["owner"]["email"] == OWNER_EMAIL


def test_a_person_who_left_loses_their_tokens_and_cannot_sign_in(environment):
    api = environment()
    riley = person_headers(api, "riley")
    assert api.get("/api/v2/tasks", headers=riley).status_code == 200
    assert api.post("/api/v2/people/riley", json={"left": True}, headers=signed_in()).status_code == 200
    assert api.get("/api/v2/tasks", headers=riley).status_code == 401
    with api.app.state.store.read() as c:
        assert c.execute("SELECT revoked_at FROM human_tokens WHERE human='riley'").fetchone()[0]
    proxy = api.app.state.auth
    proxy.proxy = HeaderProxy()
    assert api.get("/api/v2/tasks", headers={"x-test-email": "riley@acme.example"}).status_code == 403
    assert api.get("/api/v2/tasks", headers={"x-test-email": "quinn@acme.example"}).status_code == 200
    # The owner can bring them back.
    call(api, "POST", "/people/riley", {"left": False})
    assert api.get("/api/v2/tasks", headers={"x-test-email": "riley@acme.example"}).status_code == 200


def test_allow_list_changes_take_effect_without_a_restart(environment):
    api = environment()
    api.app.state.auth.proxy = HeaderProxy()
    stranger = {"x-test-email": "sam@partner.example"}
    colleague = {"x-test-email": "kim@acme.example"}
    assert api.get("/api/v2/tasks", headers=stranger).status_code == 403
    revision = view(api)["revision"]
    call(api, "PUT", "/allow", {"allowed": ["Sam@Partner.example"], "allowed_domains": ["@acme.example"],
                                "expected_revision": revision})
    # An allowed address and an allowed domain both sign in and join the roster as ordinary people.
    assert api.get("/api/v2/tasks", headers=stranger).status_code == 200
    assert api.get("/api/v2/me", headers=colleague).json()["role"] == "human"
    ids = {p["email"]: p for p in view(api)["people"]}
    assert set(ids) >= {"sam@partner.example", "kim@acme.example"} and not ids["kim@acme.example"]["owner"]
    with api.app.state.store.read() as c:
        assert c.execute("SELECT count(*) FROM events WHERE action='person.joined'").fetchone()[0] == 2
    # Narrowing the list stops new people; those already on the roster stay until marked as left.
    revision = view(api)["revision"]
    call(api, "PUT", "/allow", {"allowed": [], "allowed_domains": [], "expected_revision": revision})
    assert api.get("/api/v2/tasks", headers={"x-test-email": "lee@acme.example"}).status_code == 403
    assert api.get("/api/v2/tasks", headers=colleague).status_code == 200
    call(api, "PUT", "/allow", {"allowed": [], "allowed_domains": [], "expected_revision": revision}, expected=409)
    call(api, "PUT", "/allow", {"allowed": [], "allowed_domains": ["nodot"], "expected_revision": revision + 1},
         expected=422)



def test_who_may_join_sorts_addresses_and_domains_and_refuses_what_could_never_match(environment):
    api = environment()
    api.app.state.auth.proxy = HeaderProxy()

    def save(entries, domains=(), expected=200):
        body = {"allowed": entries, "allowed_domains": list(domains), "expected_revision": view(api)["revision"]}
        return call(api, "PUT", "/allow", body, expected=expected)

    # Either box takes either kind of entry: a domain written three ways, and an address at a public mail service.
    saved = save(["Chris@Hotmic.io", "*@hotmic.io", "@Other.example", "third.example", "sam@gmail.com"], ["  "])
    assert saved["allowed"] == ["chris@hotmic.io", "sam@gmail.com"]
    assert saved["allowed_domains"] == ["hotmic.io", "other.example", "third.example"]
    assert view(api)["allowed_domains"] == saved["allowed_domains"]
    assert api.get("/api/v2/tasks", headers={"x-test-email": "kim@hotmic.io"}).status_code == 200     # `*@` really admits
    # Anything that could never match is refused by name, and nothing is stored.
    for bad, word in (("a*@x.com", "a*@x.com"), ("not an address", "not an address"), ("*.hotmic.io", "*.hotmic.io"),
                      ("*@gmail.com", "gmail.com"), ("gmail.com", "Gmail account")):
        refused = save([bad], expected=422)
        assert word in refused["error"]["detail"], (bad, refused)
    assert view(api)["allowed_domains"] == ["hotmic.io", "other.example", "third.example"]
