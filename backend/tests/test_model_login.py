"""Signing a model in from the browser: owner-only, a small state machine, and no secrets kept."""

import json

from backend.store import H
from backend.tests.test_api import api, get, headers, post, ready, runner  # noqa: F401


def online(api):
    r = runner(api)
    ready(api, r, [])
    return r


def start(api, r, runtime="codex", **kw):
    return post(api, f"runners/{r['runner_id']}/logins", {"runtime": runtime}, **kw)


def report(api, r, lid, **body):
    return post(api, f"runner-logins/{lid}/report", body, token=r["token"])


def stored(api):
    with api.app.state.store.read() as c:
        return [dict(row) for row in c.execute("SELECT * FROM model_logins")]


def test_only_the_owner_starts_reads_or_cancels_a_login(api):
    r = online(api)
    base = f"runners/{r['runner_id']}/logins"
    post(api, base, {"runtime": "codex"}, token="ben-test", expected=403)
    lid = start(api, r)["id"]
    get(api, f"{base}/{lid}", token="ben-test", expected=403)
    post(api, f"{base}/{lid}/cancel", {}, token="ben-test", expected=403)
    post(api, f"{base}/{lid}/code", {"code": "abcdef#ghijkl"}, token="ben-test", expected=403)
    # A runner cannot drive the owner's endpoints, nor another runner's login.
    post(api, base, {"runtime": "codex"}, token=r["token"], expected=403)
    other = online(api)
    post(api, f"runner-logins/{lid}/report", {"state": "failed"}, token=other["token"], expected=404)
    assert api.get("/api/v2/runner-logins", headers=headers("ana-test")).status_code == 403


def test_a_login_needs_a_supported_runtime_and_a_computer_that_is_online(api):
    r = online(api)
    post(api, f"runners/{r['runner_id']}/logins", {"runtime": "gemini"}, expected=422)
    post(api, "runners/nope/logins", {"runtime": "codex"}, expected=404)
    with api.app.state.store.transaction() as c:
        c.execute("UPDATE runners SET last_seen=? WHERE id=?", (H.shift(H.now(), seconds=-600), r["runner_id"]))
    post(api, f"runners/{r['runner_id']}/logins", {"runtime": "codex"}, expected=409)


def test_the_state_machine_relays_what_the_cli_printed_and_ends_once(api):
    r = online(api)
    login = start(api, r)
    assert login["state"] == "requested" and login["expires_at"] > login["created"]
    assert start(api, r)["id"] == login["id"]                     # one at a time per runtime
    assert start(api, r, "claude")["id"] != login["id"]
    assert [row["id"] for row in get(api, "runner-logins", token=r["token"])["logins"]
            if row["runtime"] == "codex"] == [login["id"]]
    report(api, r, login["id"], state="waiting", url="https://auth.example/device", code="AB12-CD345",
           lines=["Open this link", "Enter this one-time code"])
    shown = get(api, f"runners/{r['runner_id']}/logins/{login['id']}")
    assert (shown["state"], shown["url"], shown["code"]) == ("waiting", "https://auth.example/device", "AB12-CD345")
    assert shown["lines"] == ["Open this link", "Enter this one-time code"] and not shown["accepts_code"]
    # A late "starting" cannot move it backwards.
    assert report(api, r, login["id"], state="starting")["state"] == "waiting"
    assert report(api, r, login["id"], state="signed_in")["state"] == "signed_in"
    done = get(api, f"runners/{r['runner_id']}/logins/{login['id']}")
    assert done["state"] == "signed_in" and done["url"] == "" and done["code"] == ""
    assert report(api, r, login["id"], state="failed")["state"] == "signed_in"   # final
    assert all(row["runtime"] != "codex" or row["id"] != login["id"]
               for row in get(api, "runner-logins", token=r["token"])["logins"])
    assert start(api, r)["id"] != login["id"]                     # a new one may begin


def test_cancel_and_expiry_end_a_login_and_tell_the_runner_to_stop(api):
    r = online(api)
    base = f"runners/{r['runner_id']}/logins"
    first = start(api, r)
    assert post(api, f"{base}/{first['id']}/cancel", {})["state"] == "cancelled"
    assert get(api, "runner-logins", token=r["token"])["logins"] == []
    assert report(api, r, first["id"], state="waiting", url="https://x.example/a")["state"] == "cancelled"
    second = start(api, r)
    with api.app.state.store.transaction() as c:
        c.execute("UPDATE model_logins SET expires_at=? WHERE id=?", (H.shift(H.now(), seconds=-1), second["id"]))
    assert get(api, f"{base}/{second['id']}")["state"] == "expired"
    assert get(api, "runner-logins", token=r["token"])["logins"] == []
    assert report(api, r, second["id"], state="signed_in")["state"] == "expired"


def test_a_pasted_code_reaches_the_runner_once_and_is_then_dropped(api):
    r = online(api)
    base = f"runners/{r['runner_id']}/logins"
    codex = start(api, r)
    post(api, f"{base}/{codex['id']}/code", {"code": "abcdef#ghijkl"}, expected=422)
    login = start(api, r, "claude")
    post(api, f"{base}/{login['id']}/code", {"code": "abcdef#ghijkl"}, expected=409)   # not waiting yet
    report(api, r, login["id"], state="waiting", url="https://claude.example/authorize")
    assert get(api, f"{base}/{login['id']}")["accepts_code"] is True
    post(api, f"{base}/{login['id']}/code", {"code": "has spaces"}, expected=422)
    sent = post(api, f"{base}/{login['id']}/code", {"code": "abcdef#ghijkl"})
    assert sent["code_sent"] is True and "abcdef" not in json.dumps(sent)
    post(api, f"{base}/{login['id']}/code", {"code": "zzzzzz#yyyyyy"}, expected=409)
    work = [w for w in get(api, "runner-logins", token=r["token"])["logins"] if w["id"] == login["id"]][0]
    assert work["code"] == "abcdef#ghijkl"
    report(api, r, login["id"], state="waiting", code_taken=True)
    assert "code" not in [w for w in get(api, "runner-logins", token=r["token"])["logins"]
                          if w["id"] == login["id"]][0]
    assert [row["pending_code"] for row in stored(api) if row["id"] == login["id"]] == [None]


def test_nothing_token_like_is_stored_or_shown(api):
    r = online(api)
    login = start(api, r)
    jwt = "eyJhbGciOiJSUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.c2lnbmF0dXJlc2lnbmF0dXJl"
    secret = "sk-ant-oat01-" + "A1b2C3d4" * 6
    blob = "QUJDREVGR0hJSktMTU5PUFFSU1RVVldYWVowMTIzNDU2Nzg5"
    report(api, r, login["id"], state="waiting", url="http://insecure.example/x", code="not a code!!",
           lines=[f"token: {jwt}", f"Your key {secret} is here", f"blob {blob}", "Enter code AB12-CD345",
                  "line\x1b[31m with control"], message=f"failed {jwt}")
    dump = json.dumps(stored(api)) + json.dumps(get(api, f"runners/{r['runner_id']}/logins/{login['id']}"))
    for leaked in (jwt, secret, blob, "eyJ", "sk-ant"):
        assert leaked not in dump
    shown = get(api, f"runners/{r['runner_id']}/logins/{login['id']}")
    assert shown["url"] == "" and shown["code"] == ""            # http and free text are refused
    assert "Enter code AB12-CD345" in shown["lines"]
    assert "\x1b" not in dump
