"""Request timing (backend/timing.py): every answer says where its time went, and the owner and
BotOps can read the per-route numbers; nobody else can."""
from backend.tests.test_api import api, get, headers  # noqa: F401


def test_answers_carry_server_timing_and_the_owner_reads_the_numbers(api):
    r = api.get("/api/v2/status", headers=headers())
    assert r.status_code == 200 and "auth;dur=" in r.headers["server-timing"] and "app;dur=" in r.headers["server-timing"]
    summary = get(api, "ops/timing")
    route = next(x for x in summary["routes"] if x["route"] == "GET /api/v2/status")
    assert route["n"] >= 1 and route["p95"] >= route["auth_p95"] >= 0
    assert "loop_lag_p95" in summary and summary["inflight"] >= 1
    assert all("{" in x["route"] or "/" in x["route"] or x["route"].endswith(("static", "unmatched")) for x in summary["routes"])
    get(api, "ops/timing", "ben-test", expected=403)


def test_cloudflare_signing_keys_are_kept_for_a_day_not_five_minutes(api):
    # 2026-09-27: every person's request after a pause waited ~400 ms re-downloading them.
    from backend.identity_proxy import CloudflareAccess
    import jwt
    client = jwt.PyJWKClient("https://example.test/cdn-cgi/access/certs", cache_keys=True, lifespan=86400, timeout=10)
    assert client.jwk_set_cache.lifespan == 86400
    src = open(CloudflareAccess.__init__.__code__.co_filename).read()
    assert "lifespan=86400" in src and "cache_keys=True" in src
