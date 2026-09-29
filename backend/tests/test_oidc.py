"""Built-in OIDC sign-in, end to end against a provider running in the test process."""

import base64
import hashlib
import json
import os
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from types import SimpleNamespace
from urllib.parse import parse_qs, urlparse

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa

from backend import identity_proxy, oidc
from backend.config import Settings
from backend.tests.test_api import api, post  # noqa: F401  (the api fixture)

CLIENT = "tico-client"
SECRET = "client-secret-value"
TENANT = "11111111-2222-3333-4444-555555555555"


def _b64(raw):
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


_POOL = []


def pool_key(index):
    """Key generation dominates the run time, so keys are made once and shared."""
    while len(_POOL) <= index:
        _POOL.append(rsa.generate_private_key(65537, 2048))
    return _POOL[index]


class Provider:
    """Discovery, JWKS, authorization bookkeeping and a token endpoint, on 127.0.0.1."""

    def __init__(self, prefix=""):
        self.prefix, self.codes, self.jwks_fetches, self.token_calls = prefix, {}, 0, []
        self.keys = []
        self.rotate()
        provider = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def reply(self, body, status=200):
                raw = json.dumps(body).encode()
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)

            def do_GET(self):
                path = urlparse(self.path).path
                if path.endswith("/.well-known/openid-configuration"):
                    self.reply({"issuer": provider.issuer, "authorization_endpoint": provider.issuer + "/authorize",
                                "token_endpoint": provider.issuer + "/token", "jwks_uri": provider.issuer + "/keys",
                                "id_token_signing_alg_values_supported": ["RS256"]})
                elif path.endswith("/keys"):
                    provider.jwks_fetches += 1
                    self.reply({"keys": [provider.jwk(kid, key) for kid, key in provider.keys]})
                else:
                    self.reply({}, 404)

            def do_POST(self):
                form = parse_qs(self.rfile.read(int(self.headers["Content-Length"])).decode())
                one = {k: v[0] for k, v in form.items()}
                provider.token_calls.append(one)
                self.reply(*provider.token(one))

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.issuer = "http://127.0.0.1:%d%s" % (self.server.server_port, prefix)
        threading.Thread(target=lambda: self.server.serve_forever(0.02), daemon=True).start()

    def rotate(self):
        self.generation = getattr(self, "generation", -1) + 1
        self.keys = [("key-%d" % self.generation, pool_key(self.generation))]      # the old key is retired

    @staticmethod
    def jwk(kid, key):
        numbers = key.public_key().public_numbers()
        size = lambda n: n.to_bytes((n.bit_length() + 7) // 8, "big")
        return {"kty": "RSA", "kid": kid, "use": "sig", "alg": "RS256",
                "n": _b64(size(numbers.n)), "e": _b64(size(numbers.e))}

    def approve(self, authorize_url, **claims):
        """The person consents: a code that will exchange for an ID token with these claims."""
        query = {k: v[0] for k, v in parse_qs(urlparse(authorize_url).query).items()}
        code = "code-%d" % len(self.codes)
        self.codes[code] = {"query": query, "claims": claims}
        return code, query["state"]

    def token(self, form):
        entry = self.codes.pop(form.get("code"), None)
        if (not entry or form.get("client_id") != CLIENT or form.get("client_secret") != SECRET
                or form.get("redirect_uri") != entry["query"]["redirect_uri"]
                or _b64(hashlib.sha256(form.get("code_verifier", "").encode()).digest())
                != entry["query"]["code_challenge"]):
            return {"error": "invalid_grant"}, 400
        now = int(time.time())
        claims = {"iss": self.issuer, "aud": CLIENT, "sub": "subject-1", "iat": now, "exp": now + 300,
                  "nonce": entry["query"]["nonce"], "email": "ben@acme.example", "email_verified": True}
        claims.update(entry["claims"])
        claims = {k: v for k, v in claims.items() if v is not None}
        kid, key = self.keys[0]
        return {"id_token": jwt.encode(claims, key, algorithm="RS256", headers={"kid": kid}),
                "access_token": "opaque", "token_type": "Bearer"}, 200


@pytest.fixture
def provider():
    made = []

    def make(prefix=""):
        made.append(Provider(prefix))
        return made[-1]
    yield make
    for item in made:
        item.server.shutdown()
        item.server.server_close()


@pytest.fixture
def signin(api, provider):
    fake = provider()
    auth = api.app.state.auth
    settings = auth.settings

    def start(issuer=None, **changes):
        settings.auth_proxy, settings.oidc_issuer = "oidc", issuer or fake.issuer
        settings.oidc_client_id, settings.oidc_client_secret = CLIENT, SECRET
        settings.session_secret = "s" * 40
        for key, value in changes.items():
            setattr(settings, key, value)
        auth.proxy = identity_proxy.build(settings, auth.store)
        return auth.proxy
    proxy = start()

    def login(target="/", follow=False, claims=None, client=None, **query):
        client = client or api
        began = client.get("/auth/login", params={"next": target, **query}, follow_redirects=False)
        assert began.status_code == 302, began.text
        code, state = ns.fake.approve(began.headers["location"], **(claims or {}))
        return client.get("/auth/callback", params={"code": code, "state": state}, follow_redirects=False)

    def sessions():
        with auth.store.read() as c:
            return c.execute("SELECT * FROM oidc_sessions").fetchall()
    ns = SimpleNamespace(api=api, fake=fake, auth=auth, settings=settings, proxy=proxy, start=start,
                         login=login, sessions=sessions, provider=provider)
    return ns


def me(client, **kw):
    return client.get("/api/v2/me", **kw)


def test_full_flow_signs_in_the_roster_person(signin):
    began = signin.api.get("/auth/login", params={"next": "/tasks?x=1"}, follow_redirects=False)
    location = urlparse(began.headers["location"])
    assert began.status_code == 302 and location.path.endswith("/authorize")
    query = {k: v[0] for k, v in parse_qs(location.query).items()}
    assert query["response_type"] == "code" and query["client_id"] == CLIENT
    assert query["code_challenge_method"] == "S256" and query["scope"] == "openid email profile"
    assert query["redirect_uri"] == signin.settings.public_url + "/auth/callback"
    assert SECRET not in began.headers["location"]
    login_cookie = began.headers["set-cookie"]
    assert "HttpOnly" in login_cookie and "samesite=lax" in login_cookie.lower()

    code, state = signin.fake.approve(began.headers["location"])
    done = signin.api.get("/auth/callback", params={"code": code, "state": state}, follow_redirects=False)
    assert done.status_code == 302 and done.headers["location"] == "/tasks?x=1"
    assert signin.fake.token_calls[0]["client_secret"] == SECRET
    cookie = next(v for v in done.headers.get_list("set-cookie") if v.startswith("tico_session="))
    assert "HttpOnly" in cookie and "samesite=lax" in cookie.lower()
    who = me(signin.api)
    assert who.status_code == 200 and who.json()["actor"] == "human:ben"
    assert signin.api.get("/api/me").json()["proxy_session"] is True
    value = signin.api.cookies.get("tico_session")
    assert value not in json.dumps([dict(r) for r in signin.sessions()])      # only a hash is stored


def test_cookie_is_host_prefixed_and_secure_on_https(signin):
    signin.start()
    signin.settings.public_url = "https://tico.example"
    proxy = signin.start()
    assert proxy.cookie == "__Host-tico_session"
    began = signin.api.get("/auth/login", follow_redirects=False)
    assert "__Host-tico_login=" in began.headers["set-cookie"] and "Secure" in began.headers["set-cookie"]
    assert "Domain" not in began.headers["set-cookie"]
    code, state = signin.fake.approve(began.headers["location"])
    pair = began.headers["set-cookie"].split(";")[0]
    done = signin.api.get("/auth/callback", params={"code": code, "state": state},
                          headers={"cookie": pair}, follow_redirects=False)
    session = next(v for v in done.headers.get_list("set-cookie") if v.startswith("__Host-tico_session="))
    assert "Secure" in session and "Path=/" in session and "Domain" not in session


@pytest.mark.parametrize("claims", [
    {"aud": "someone-else"}, {"aud": ["someone-else", CLIENT], "azp": "someone-else"},
    {"iss": "https://evil.example"}, {"exp": int(time.time()) - 3600},
    {"iat": int(time.time()) + 3600}, {"nonce": "not-the-nonce"}, {"nonce": None},
    {"email_verified": False}, {"email_verified": "false"}, {"email_verified": None},
    {"email": None}, {"sub": None}], ids=lambda claims: ",".join(claims))
def test_bad_id_tokens_never_start_a_session(signin, claims):
    result = signin.login(claims=claims)
    assert result.status_code in (400, 502) and result.headers["content-type"].startswith("text/html")
    assert "session" not in result.headers.get("set-cookie", "")
    assert signin.sessions() == [] and me(signin.api).status_code == 401


def test_wrong_signature_is_refused(signin):
    signin.login()                                           # the provider's real key is now cached
    signin.api.cookies.clear()
    began = signin.api.get("/auth/login", follow_redirects=False)
    code, state = signin.fake.approve(began.headers["location"])
    other = pool_key(5)
    signin.fake.keys[0] = (signin.fake.keys[0][0], other)          # same kid, another key
    result = signin.api.get("/auth/callback", params={"code": code, "state": state}, follow_redirects=False)
    assert result.status_code == 400 and len(signin.sessions()) == 1 and me(signin.api).status_code == 401


def test_state_and_login_cookie_are_enforced(signin):
    began = signin.api.get("/auth/login", follow_redirects=False)
    code, state = signin.fake.approve(began.headers["location"])
    assert signin.api.get("/auth/callback", params={"code": code, "state": state + "x"},
                          follow_redirects=False).status_code == 400
    # The provider's code is spent by a good state only, so a fresh attempt is needed.
    began = signin.api.get("/auth/login", follow_redirects=False)
    code, state = signin.fake.approve(began.headers["location"])
    signin.api.cookies.clear()
    assert signin.api.get("/auth/callback", params={"code": code, "state": state},
                          follow_redirects=False).status_code == 400          # no cookie at all
    forged = began.headers["set-cookie"].split(";")[0]
    name, _, value = forged.partition("=")
    payload = json.loads(base64.urlsafe_b64decode(value.split(".")[0] + "=="))
    body = _b64(json.dumps({**payload, "s": "chosen"}).encode())
    assert signin.api.get("/auth/callback", params={"code": code, "state": "chosen"},
                          headers={"cookie": name + "=" + body + "." + value.split(".")[1]},
                          follow_redirects=False).status_code == 400          # signature no longer fits
    assert signin.sessions() == []
    assert signin.api.get("/auth/callback", params={"error": "access_denied"},
                          follow_redirects=False).status_code == 400


def test_disallowed_domain_and_hosted_domain(signin):
    signin.start(oidc_allowed_domains=("acme.example",))
    assert signin.login(claims={"email": "ben@other.example"}).status_code == 400
    assert signin.sessions() == []
    assert signin.login().status_code == 302
    signin.api.cookies.clear()
    # A Google issuer also needs the hd claim to be an allowed domain.
    original = oidc._google
    oidc._google = lambda issuer: True
    try:
        assert signin.login(claims={"hd": "other.example"}).status_code == 400
        assert signin.login(claims={"hd": "acme.example"}).status_code == 302
        assert signin.login(claims={"hd": None}).status_code == 400
    finally:
        oidc._google = original


def test_unknown_roster_email_gets_a_friendly_page(signin):
    result = signin.login(claims={"email": "<b>x</b>@acme.example"})
    assert result.status_code == 403 and result.headers["content-type"].startswith("text/html")
    assert "not on" in result.text and "&lt;b&gt;x&lt;/b&gt;@acme.example" in result.text
    assert "<b>x</b>" not in result.text and not result.text.lstrip().startswith("{")
    assert signin.sessions() == []
    assert signin.login(claims={"email": "stranger@acme.example"}).status_code == 403


def test_email_match_ignores_case(signin):
    assert signin.login(claims={"email": "Ben@ACME.example"}).status_code == 302
    assert me(signin.api).json()["actor"] == "human:ben"


def test_jwks_refetches_on_a_new_key_but_not_more_often_than_the_limit(signin):
    assert signin.login().status_code == 302
    assert signin.fake.jwks_fetches == 1
    signin.fake.rotate()
    assert signin.login().status_code == 400                 # unknown kid, refreshed less than a minute ago
    assert signin.fake.jwks_fetches == 1
    signin.proxy.jwks_min_interval = 0
    assert signin.login().status_code == 302
    assert signin.fake.jwks_fetches == 2
    assert signin.login().status_code == 302                 # the cached key serves it
    assert signin.fake.jwks_fetches == 2


def test_idle_and_absolute_lifetimes(signin):
    signin.login()
    assert me(signin.api).status_code == 200
    with signin.auth.store.transaction() as c:
        c.execute("UPDATE oidc_sessions SET last_seen=?", ("2000-01-01T00:00:00.000000Z",))
    assert me(signin.api).status_code == 401
    signin.login()
    assert me(signin.api).status_code == 200
    with signin.auth.store.transaction() as c:
        c.execute("UPDATE oidc_sessions SET expires_at=?", ("2000-01-01T00:00:00.000000Z",))
    assert me(signin.api).status_code == 401


def test_activity_moves_the_idle_clock(signin):
    signin.login()
    with signin.auth.store.transaction() as c:
        c.execute("UPDATE oidc_sessions SET last_seen=?", (H_ago(hours=1),))
    assert me(signin.api).status_code == 200
    assert signin.sessions()[0]["last_seen"] > H_ago(hours=1)


def H_ago(**kw):
    from backend.store import H
    return H.shift(H.now(), seconds=-kw.get("hours", 0) * 3600)


def test_sign_in_is_rotated_and_the_old_session_dropped(signin):
    signin.login()
    first = signin.api.cookies.get("tico_session")
    signin.login()
    second = signin.api.cookies.get("tico_session")
    assert first != second and len(signin.sessions()) == 1
    assert me(signin.api).status_code == 200


def test_unauthenticated_page_redirects_and_api_answers_401(signin):
    page = signin.api.get("/", headers={"accept": "text/html,application/xhtml+xml"}, follow_redirects=False)
    assert page.status_code == 302 and page.headers["location"] == "/auth/login?next=%2F"
    deep = signin.api.get("/tico/ui/index.html?a=b", headers={"accept": "text/html"}, follow_redirects=False)
    assert deep.headers["location"].startswith("/auth/login?next=")
    api_call = me(signin.api, headers={"accept": "text/html"})
    assert api_call.status_code == 401 and api_call.json()["error"]["sign_in"] == "/auth/login"
    assert signin.api.get("/", follow_redirects=False).status_code == 401           # not a browser navigation
    assert signin.api.post("/api/v2/me", follow_redirects=False,
                           headers={"accept": "text/html"}).status_code == 401
    assert me(signin.api, headers={"authorization": "Bearer nonsense"}).status_code == 401


@pytest.mark.parametrize("target,expected", [
    ("//evil.example/x", "/"), ("https://evil.example", "/"), ("/\\evil.example", "/"),
    ("/%0d%0a", "/%0d%0a"), ("javascript:alert(1)", "/"), ("/auth/login", "/"),
    ("/tasks#/x", "/tasks#/x"), ("/a b", "/")])
def test_next_only_returns_to_same_origin_paths(signin, target, expected):
    done = signin.login(target)
    assert done.status_code == 302 and done.headers["location"] == expected


def test_logout_ends_the_session_and_lands_on_a_sign_in_page(signin):
    signin.login()
    value = signin.api.cookies.get("tico_session")
    out = signin.api.get("/api/v2/logout", follow_redirects=False)
    assert out.status_code == 302 and out.headers["location"] == "/auth/signed-out"
    assert signin.sessions() == [] and me(signin.api).status_code == 401
    replay = me(signin.api, headers={"cookie": "tico_session=" + value})
    assert replay.status_code == 401                        # the id itself is dead, not only the cookie
    page = signin.api.get("/auth/signed-out")
    assert page.status_code == 200 and "/auth/login" in page.text


def test_a_person_marked_left_loses_the_session_and_cannot_return(signin):
    signin.login(claims={"email": "cara@acme.example"})
    assert me(signin.api).json()["actor"] == "human:cara"
    cookie = signin.api.cookies.get("tico_session")
    post(signin.api, "people/cara", {"left": True})
    assert signin.sessions() == []
    assert me(signin.api, headers={"cookie": "tico_session=" + cookie}).status_code == 401
    again = signin.login(claims={"email": "cara@acme.example"})
    assert again.status_code == 403 and "not on" in again.text


def test_bearer_credentials_do_not_depend_on_the_browser_session(signin):
    # With no session at all a bearer still works, and a bad one is refused, session or not.
    assert me(signin.api, headers={"authorization": "Bearer ben-test"}).json()["actor"] == "human:ben"
    signin.login()
    assert me(signin.api, headers={"authorization": "Bearer ana-test"}).json()["actor"] == "human:ana"
    assert me(signin.api, headers={"authorization": "Bearer wrong"}).status_code == 401
    signin.api.get("/api/v2/logout", follow_redirects=False)
    assert me(signin.api, headers={"authorization": "Bearer ben-test"}).status_code == 200


def test_writes_from_another_origin_are_refused(signin):
    signin.login()
    url = signin.settings.public_url
    bad = signin.api.post("/api/v2/me", headers={"origin": "https://evil.example"})
    assert bad.status_code == 403 and bad.json()["error"]["code"] == "origin"
    ok = signin.api.post("/api/v2/me", headers={"origin": url})
    assert ok.json().get("error", {}).get("code") != "origin"


def test_login_routes_are_absent_without_the_oidc_proxy(api):
    assert api.get("/auth/login", follow_redirects=False).status_code == 404
    assert api.get("/auth/callback", follow_redirects=False).status_code == 404


def test_unreachable_provider_says_so_plainly(signin):
    signin.start(issuer="http://127.0.0.1:9")
    result = signin.api.get("/auth/login", follow_redirects=False)
    assert result.status_code == 502 and "unavailable" in result.text


def test_microsoft_tenant_is_pinned_and_the_email_may_be_the_username(signin, monkeypatch):
    fake = signin.provider(prefix="/" + TENANT + "/v2.0")
    monkeypatch.setattr(oidc, "_microsoft", lambda issuer: True)
    signin.start(issuer=fake.issuer)
    signin.fake = fake
    good = {"tid": TENANT, "email": None, "email_verified": None, "preferred_username": "ben@acme.example"}
    assert signin.login(claims=good).status_code == 302
    assert me(signin.api).json()["actor"] == "human:ben"
    signin.api.cookies.clear()
    assert signin.login(claims={**good, "tid": "99999999-2222-3333-4444-555555555555"}).status_code == 400
    assert signin.login(claims={**good, "tid": None}).status_code == 400
    assert signin.login(claims={**good, "email_verified": False}).status_code == 400
    assert signin.login(claims={**good, "preferred_username": "not-an-email"}).status_code == 400


def test_client_secret_can_come_from_a_file(signin, tmp_path):
    path = tmp_path / "secret"
    path.write_text(SECRET + "\n")
    signin.settings.oidc_client_secret = ""
    signin.settings.oidc_client_secret_file = path
    oidc.check(signin.settings)
    assert signin.settings.oidc_client_secret == SECRET


def base(tmp_path, **kw):
    return dict(db_path=tmp_path / "hub.db", registry_dir=tmp_path, auth_proxy="oidc",
                oidc_issuer="https://accounts.google.com", oidc_client_id="id", oidc_client_secret="s",
                public_url="https://tico.example", **kw)


@pytest.mark.parametrize("changes,message", [
    ({"oidc_issuer": ""}, "TICO_OIDC_ISSUER and TICO_OIDC_CLIENT_ID"),
    ({"oidc_client_id": ""}, "TICO_OIDC_ISSUER and TICO_OIDC_CLIENT_ID"),
    ({"oidc_client_secret": ""}, "TICO_OIDC_CLIENT_SECRET"),
    ({"oidc_issuer": "http://idp.example.com"}, "https"),
    ({"oidc_issuer": "https://login.microsoftonline.com/common/v2.0"}, "own tenant"),
    ({"oidc_issuer": "https://login.microsoftonline.com/organizations/v2.0"}, "own tenant"),
    ({"public_url": "http://tico.example"}, "https TICO_PUBLIC_URL"),
    ({"session_secret": "short"}, "at least 32"),
    ({"oidc_allowed_domains": ("me@acme.com",)}, "ALLOWED_DOMAINS"),
    ({"oidc_client_secret": "", "oidc_client_secret_file": "/nonexistent/secret"}, "cannot be read")])
def test_startup_validation_names_the_problem(tmp_path, changes, message):
    with pytest.raises(RuntimeError, match=message):
        Settings(**{**base(tmp_path), **changes})


def test_valid_configurations_start(tmp_path):
    Settings(**base(tmp_path))
    Settings(**base(tmp_path, oidc_allowed_domains=("acme.com",)))
    Settings(**{**base(tmp_path), "oidc_issuer": "https://login.microsoftonline.com/" + TENANT + "/v2.0"})
    Settings(**{**base(tmp_path), "public_url": "http://127.0.0.1:8765"})


def test_session_secret_is_generated_once_and_kept_private(tmp_path):
    settings = Settings(**base(tmp_path))
    first = oidc._session_secret(settings)
    path = tmp_path / oidc.SECRET_FILE
    assert oct(path.stat().st_mode & 0o777) == "0o600" and len(first) >= 64
    assert oidc._session_secret(settings) == first
    os.chmod(path, 0o644)
    with pytest.raises(RuntimeError, match="chmod 600"):
        oidc._session_secret(settings)
