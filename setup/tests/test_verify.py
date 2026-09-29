import json

from setup import verify
from setup.remote import Result
from setup.tests.fakes import FakeShell

GOOGLE = ("https://accounts.google.com/o/oauth2/v2/auth?client_id=cid&response_type=code"
          "&redirect_uri=https%3A%2F%2Ftico.example.com%2Fauth%2Fcallback&scope=openid+email")


def getter(code, location="", **_):
    return lambda url, follow=True: (code, {"Location": location}, "")


def test_signin_redirect_ok_only_with_exact_redirect_uri_and_provider_host():
    c = verify.check_signin("tico.example.com", "google", "cid", get=getter(302, GOOGLE))
    assert c.ok and "auth/callback" in c.detail


def test_signin_redirect_uri_mismatch_names_the_exact_uri_to_register():
    bad = GOOGLE.replace("tico.example.com", "other.example.com")
    c = verify.check_signin("tico.example.com", "google", "cid", get=getter(302, bad))
    assert not c.ok and "https://tico.example.com/auth/callback" in c.hint


def test_signin_wrong_host_or_no_redirect_fails_with_a_hint():
    assert not verify.check_signin("tico.example.com", "google", "cid", get=getter(200)).ok
    c = verify.check_signin("tico.example.com", "microsoft", "cid", get=getter(302, GOOGLE))
    assert not c.ok and "login.microsoftonline.com" in c.hint


def test_signin_wrong_client_id_detected():
    assert not verify.check_signin("tico.example.com", "google", "different", get=getter(302, GOOGLE)).ok


def test_health():
    assert verify.check_health("t", get=lambda u: (200, {}, "")).ok
    c = verify.check_health("t", get=lambda u: (502, {}, ""))
    assert not c.ok and "docker compose logs server" in c.hint

    def boom(u):
        raise OSError("refused")
    assert not verify.check_health("t", get=boom).ok


def test_service_check_parses_compose_json_lines_and_arrays():
    row = json.dumps({"Service": "server", "State": "running", "Health": "healthy"})
    assert verify.check_service(FakeShell({"compose ps": Result(0, row + "\n")}), "server", "Server").ok
    assert verify.check_service(FakeShell({"compose ps": Result(0, "[" + row + "]")}), "server", "Server").ok
    down = json.dumps({"State": "restarting", "Health": ""})
    c = verify.check_service(FakeShell({"compose ps": Result(0, down)}), "server", "Server")
    assert not c.ok and "logs" in c.hint
    assert not verify.check_service(FakeShell({"compose ps": Result(1, "")}), "server", "Server").ok


def test_env_permissions():
    assert verify.check_env_perms(FakeShell({"stat": Result(0, "600\n")})).ok
    c = verify.check_env_perms(FakeShell({"stat": Result(0, "644\n")}))
    assert not c.ok and "chmod 600" in c.hint


def test_tls_unreachable_and_bad_cert_have_different_hints():
    import ssl

    def refuse(addr, timeout):
        raise ConnectionRefusedError("refused")
    c = verify.check_tls("tico.example.com", connect=refuse)
    assert not c.ok and "443" in c.hint

    class BadCert:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            pass

    err = ssl.SSLCertVerificationError(1, "certificate verify failed")
    err.verify_message = "self-signed certificate"
    orig = ssl.SSLContext.wrap_socket
    ssl.SSLContext.wrap_socket = lambda self, sock, server_hostname=None: (_ for _ in ()).throw(err)
    try:
        c = verify.check_tls("tico.example.com", connect=lambda addr, timeout: BadCert())
    finally:
        ssl.SSLContext.wrap_socket = orig
    assert not c.ok and "certificate" in c.detail and "caddy" in c.hint


def test_runner_container_and_computer_checks():
    ok = FakeShell({"docker ps": Result(0, "Up 2 minutes\n")})
    assert verify.check_runner_container(ok).ok
    c = verify.check_runner_container(FakeShell({"docker ps": Result(0, ""), "docker logs": Result(0, "code expired")}))
    assert not c.ok and "15 minutes" in c.hint and "code expired" in c.hint
    assert verify.check_computer_online("https://t", "", "lbl") is None


def _run(monkeypatch, results, wait, provider="google"):
    """results: successive (tls_ok, health_ok) outcomes; the last repeats."""
    seq, slept = iter(results), []
    state = {"cur": (True, True)}

    def tls(domain):
        state["cur"] = next(seq, state["cur"])
        return verify.Check("HTTPS certificate", state["cur"][0], "x")

    monkeypatch.setattr(verify, "check_dns", lambda *a: verify.Check("DNS", True, "ok"))
    monkeypatch.setattr(verify, "check_tls", tls)
    monkeypatch.setattr(verify, "check_health", lambda d: verify.Check("/healthz", state["cur"][1], "x"))
    monkeypatch.setattr(verify, "check_signin", lambda *a: verify.Check("Sign-in redirect", state["cur"][1], "x"))
    said = []
    out = verify.run_all(domain="t.example.com", provider=provider, client_id="c", front_door="caddy", records=[], resolvers=[],
                         shell=None, wait_https=wait, sleep=slept.append, say=said.append)
    return out, slept, said


def test_https_checks_are_retried_until_the_certificate_arrives(monkeypatch):
    out, slept, said = _run(monkeypatch, [(False, False), (False, False), (True, True)], 180)
    assert all(c.ok for c in out) and len(slept) == 2
    assert len(said) == 1 and "waiting for the HTTPS certificate" in said[0]


def test_https_retry_gives_up_after_the_deadline_and_backs_off(monkeypatch):
    out, slept, _ = _run(monkeypatch, [(False, False)], 180)
    assert not all(c.ok for c in out) and 180 <= sum(slept) < 200
    assert slept[0] < slept[-1] <= 15


def test_no_wait_means_a_single_shot_like_doctor(monkeypatch):
    out, slept, said = _run(monkeypatch, [(False, False)], 0)
    assert slept == [] and said == [] and not out[1].ok


def test_tls_internal_error_hint_points_at_caddy_logs():
    import ssl

    def boom(*a, **k):
        raise ssl.SSLError(1, "[SSL: TLSV1_ALERT_INTERNAL_ERROR] tlsv1 alert internal error")
    c = verify.check_tls("t.example.com", connect=boom)
    assert not c.ok and "still being issued" in c.hint and "docker compose logs caddy" in c.hint


def test_unreachable_443_hint_names_the_private_subnet():
    def refuse(*a, **k):
        raise TimeoutError("timed out")
    c = verify.check_tls("t.example.com", connect=refuse)
    assert "private subnet" in c.hint and "NAT gateway" in c.hint and "internet gateway" in c.hint
