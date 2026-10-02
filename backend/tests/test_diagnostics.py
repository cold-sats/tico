"""Support diagnostics (PRIVACY.md, "Support diagnostics"): the redactor, the allowlist, and that a preview is what is sent."""

import json
import logging

import pytest

from backend import diagnostics as D
from backend import support
from backend.store import H, encode
from backend.tests.test_onboarding import as_person, environment, signed_in, machine  # noqa: F401
from backend.tests.test_support import hq, file  # noqa: F401  (the fake HQ, autouse)


def redactor():
    return D.Redactor(["acme.example"], [("coo", ["Morgan the assistant"]), ("botops", ["BotOps"])],
                      [("morgan", ["Morgan Reed", "morgan@acme.example"]), ("riley", ["Riley Quinn", "riley@acme.example"])])


# ------------------------------------------------------------------ the redactor
@pytest.mark.parametrize("raw, gone, shown", [
    ("key sk-abcdEFGH1234567890xyz here", "sk-abcdEFGH1234567890xyz", "[key]"),
    ("token ghp_abcdefgh12345678ABCD", "ghp_abcdefgh12345678ABCD", "[token]"),
    ("token gho_abcdefgh12345678ABCD", "gho_abcdefgh12345678ABCD", "[token]"),
    ("slack xoxb-1234567890-abcdefghij", "xoxb-1234567890-abcdefghij", "[token]"),
    ("slack xoxp-1234567890-abcdefghij", "xoxp-1234567890-abcdefghij", "[token]"),
    ("aws AKIAABCDEFGHIJKLMNOP", "AKIAABCDEFGHIJKLMNOP", "[key]"),
    ("Authorization: Bearer abc123.def-456_ghi", "abc123.def-456_ghi", "[token]"),
    ("jwt eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0In0.SflKxwRJSMeKKF2QT4fw", "eyJhbGciOiJIUzI1NiJ9", "[jwt]"),
    ("hex " + "a1b2c3d4" * 8, "a1b2c3d4a1b2c3d4", "[secret]"),
    ("b64 QWxhZGRpbjpvcGVuIHNlc2FtZSBhbmQgbW9yZSBzdHVmZg==", "QWxhZGRpbjpvcGVuIHNlc2FtZSBhbmQgbW9yZSBzdHVmZg", "[secret]"),
    ("OPENAI_API_KEY=abcd1234efgh", "abcd1234efgh", "[redacted]"),
    ("password: hunter22", "hunter22", "[redacted]"),
    ("mail stranger@elsewhere.org sent", "stranger@elsewhere.org", "[email]"),
    ("from 10.0.0.12 and 192.168.1.1", "10.0.0.12", "[ip]"),
    ("v6 2001:db8:85a3::8a2e:370:7334 and ::1", "2001:db8:85a3", "[ip]"),
    ("GET https://api.tico.team/v1/latest?install_id=abc&x=1 failed", "install_id=abc", "?[query]"),
    ("see https://other.io/path?a=1#frag", "a=1", "?[query]#frag"),
    ("db.acme.example refused", "db.acme.example", "[company-domain]"),
    ("acme.example unreachable", "acme.example", "[company-domain]"),
    ("connect to internal.corp and files.somewhere.io", "somewhere.io", "[host]"),
])
def test_the_redactor_removes_each_kind_of_secret(raw, gone, shown):
    out = redactor().text(raw)
    assert gone not in out and shown in out


@pytest.mark.parametrize("raw", [
    "Tico 0.2.18 on Python 3.12.4", "updates.tico.team answered", "https://api.github.com/repos/x", "ghcr.io/ticoteam/tico:v0.2.18",
    "service.py line 12, hub.db and backend.app", "at 12:34:56 and 2026-09-29T10:00:00Z", "6f1c2a9e-3b7d-4c58-9a10-2d4e8b7f5a63",
    "the /usr/local/lib/python3.12/site-packages/pkg path", "codex-cli 0.130.0", "bootstrap coordinate"])
def test_the_redactor_leaves_what_is_not_a_secret(raw):
    assert redactor().text(raw) == raw


def test_names_become_labels_that_are_the_same_all_through_a_bundle():
    r = redactor()
    out = r.text("Morgan Reed (morgan@acme.example, morgan) asked bot:coo; BotOps and botops; Riley Quinn later; morgan again")
    assert out == "person-1 (person-1, person-1) asked bot-2; bot-1 and bot-1; person-2 later; person-1 again"
    assert r.label("BOTOPS") == "bot-1" and r.label("Zed") is None
    # Whole words only, and every string, however nested, goes through it.
    assert r.text("coordinator") == "coordinator"
    assert r.clean({"a": ["riley failed", {"b": "Morgan Reed"}], "n": 3, "ok": True, "x": None}) == \
        {"a": ["person-2 failed", {"b": "person-1"}], "n": 3, "ok": True, "x": None}
    # Another bundle with the same people in a different order gets its own labels: they mean nothing outside one bundle.
    other = D.Redactor([], [], [("riley", []), ("morgan", [])])
    assert other.text("riley") == "person-2" and other.text("morgan") == "person-1"


def test_a_short_name_is_not_a_word_but_an_exact_actor_reference_or_an_email_is_always_relabeled():
    r = D.Redactor([], [("coo", ["COO"]), ("pm", []), ("sage", ["Sage"])],
                   [("ana", ["Ana", "ana@acme.example"]), ("bo", ["Bo Li", "bo@acme.example"]), ("riley", ["Riley Quinn"])])
    # Ordinary words that happen to be a short slug, name or id stay as they are.
    for plain in ("the coo signed off", "COO and PM sat with Ana and Bo", "a bo staff, a pm", "Li joined"):
        assert r.text(plain) == plain
    # Four letters or more is a word, a full name too.
    assert r.text("ask sage or Sage, then riley and Riley Quinn, Bo Li wrote") == "ask bot-3 or bot-3, then person-3 and person-3, person-2 wrote"
    # An exact actor reference is relabeled whatever its length, by kind, and only when the slug or id is known.
    assert r.text("bot:coo asked bot:pm; human:ana and human:bo, bot:coo.") == "bot-1 asked bot-2; person-1 and person-2, bot-1."
    assert r.text("bot:sage and human:riley; bot:zed and human:coo and xbot:coo") == "bot-3 and person-3; bot:zed and human:coo and xbot:coo"
    # An email is always relabeled when it is a person's, and redacted when it is anyone else's, short local part or not.
    assert r.text("ana@acme.example, bo@acme.example and coo@acme.example") == "person-1, person-2 and [email]"
    assert r.text("bo.li@else.org") == "[email]"
    # The exact lookup still knows a short slug.
    assert r.label("coo") == "bot-1" and r.label("BO") == "person-2"
    assert r.clean({"actor": "bot:coo", "note": "the coo"}) == {"actor": "bot-1", "note": "the coo"}


def test_control_characters_are_dropped():
    assert redactor().text("a\x1b[31mred\x00b‮dc") == "a[31mredbdc"


def test_a_bundle_over_the_cap_shrinks_its_logs_first():
    bundle = {"format": 1, "counts": {"bots": 1}, "containers": [],
              "logs": {"server": ["x" * 300] * 2000, "updater": []}, "runners": [{"log": ["y" * 300] * 2000, "problems": []}]}
    out = D.fit(bundle)
    assert len(json.dumps(out).encode()) <= D.MAX_BYTES and out["counts"] == {"bots": 1}


# ------------------------------------------------------------------ the allowlist
def walk(value, shape, where="$"):
    """Every key of `value` must be in `shape`, at every depth."""
    if isinstance(shape, list):
        for item in value:
            walk(item, shape[0], where + "[]")
    elif isinstance(shape, dict) and shape:
        assert isinstance(value, dict), where
        for key, inner in value.items():
            assert key in shape, f"{where}.{key} is not allowlisted"
            walk(inner, shape[key], where + "." + key)
    elif isinstance(shape, dict):
        assert set(value) <= set(D.FEATURES) and all(isinstance(v, bool) for v in value.values())


def seed(api):
    """A company with content in it: a task, a message, a doc, and a log line that carries an address and a key."""
    owner = signed_in()
    api.post("/api/v2/tasks", json={"title": "CONTENT-task-title", "body": "CONTENT-task-body", "owner": "coo"}, headers=owner)
    api.post("/api/v2/chat/coo", json={"body": "CONTENT-chat-message"}, headers=owner)
    api.post("/api/v2/docs", json={"title": "CONTENT-doc-title", "body": "CONTENT-doc-body"}, headers=owner)
    logging.getLogger("tico.test").warning("Sync for riley@acme.example failed from 203.0.113.9 with sk-abcdEFGH1234567890xyz")
    logging.getLogger("tico.test").info("not kept: below WARNING")


def bundle_of(api, headers=None):
    got = api.get("/api/v2/support/diagnostics", headers=headers or signed_in())
    assert got.status_code == 200, got.text
    return got.json(), json.loads(got.json()["text"])


def test_the_bundle_holds_only_allowlisted_facts_and_never_content(environment, hq):
    api = environment()
    seed(api)
    answer, bundle = bundle_of(api)
    walk(bundle, D.ALLOWED)
    text = answer["text"]
    for content in ("CONTENT-task-title", "CONTENT-task-body", "CONTENT-chat-message", "CONTENT-doc-title", "CONTENT-doc-body"):
        assert content not in text
    # Every string was redacted: the log line kept its shape, not its address, key or names.
    lines = [line for line in bundle["logs"]["server"] if "Sync for" in line]
    assert len(lines) == 1 and "person-" in lines[0] and "[ip]" in lines[0] and "[key]" in lines[0]
    assert "riley@acme.example" not in text and "203.0.113.9" not in text and "sk-abcd" not in text
    assert "not kept: below WARNING" not in text
    # The company, its people and its bots by name: none of it appears.
    for name in ("Morgan Reed", "Riley Quinn", "acme.example", "AcmeCorp", "Acme", "Atlas", "morgan", "riley", "coo", "botops"):
        assert name not in text.replace("[company-domain]", ""), name
    assert bundle["versions"]["tico"] and bundle["counts"]["people"] == 3 and bundle["counts"]["bots"] >= 2
    assert bundle["database"]["migration"] >= 11 and set(bundle["features"]) <= set(D.FEATURES)
    assert all(set(x) == {"name", "status"} for x in bundle["health"]) and bundle["health"]
    assert D.digest(bundle) == answer["id"] and answer["bytes"] == len(text.encode()) <= D.MAX_BYTES


def test_a_computers_readiness_is_summarised_with_labels_and_redacted_problems(environment, hq):
    api = environment()
    enrolled = machine(api, label="Morgan's Mac")
    runner_id = enrolled["runner_id"] if "runner_id" in enrolled else enrolled["id"]
    readiness = {"schema_version": 1, "runtimes": {"codex": {"installed": True, "authenticated": "ready", "version": "codex-cli 0.130.0",
                                                            "detail": "Signed in with ChatGPT"},
                                                   "gemini": {"installed": False, "authenticated": "missing"}},
                 "bots": {"coo": {"ready": False, "problems": ["coo: repository missing at /Users/morgan/work"]}},
                 "recent_errors": ["2026-09-29T10:00:00Z Tico runner: coo failed for morgan@acme.example"]}
    with api.app.state.store.transaction() as c:
        c.execute("UPDATE runners SET readiness_json=?, last_seen=? WHERE id=?", (encode(readiness), H.now(), runner_id))
    _, bundle = bundle_of(api)
    (runner,) = bundle["runners"]
    text = json.dumps(bundle)
    assert runner["label"] == "runner-1" and runner["online"] and "Mac" not in text
    assert runner["runtimes"] == [{"name": "codex", "installed": True, "version": "codex-cli 0.130.0", "ready": True,
                                   "state": "ready", "detail": "Signed in with ChatGPT"}]
    assert runner["bots"] == 1 and runner["bots_ready"] == 0
    assert runner["problems"] == ["bot-2: repository missing at /Users/person-1/work"]
    assert runner["log"] == ["2026-09-29T10:00:00Z Tico runner: coo failed for person-1"]     # `coo` alone is a word, not a name


def test_a_member_may_preview_and_only_a_person_may(environment, hq):
    api = environment()
    riley = as_person(api, "riley")
    assert api.get("/api/v2/support/diagnostics", headers=riley).status_code == 200
    assert api.get("/api/v2/support/diagnostics").status_code in (401, 403)
    assert hq.seen == []                                          # a preview sends nothing


# ------------------------------------------------------------------ the preview is what is sent
def test_what_the_preview_showed_is_exactly_what_hq_gets(environment, hq):
    api = environment()
    seed(api)
    answer, shown = bundle_of(api)
    r = file(api, diagnostics=answer["id"])
    assert r.status_code == 200 and r.json()["sent"]["diagnostics"] == answer["bytes"]
    (request,) = hq.seen
    sent = json.loads(request.content)
    assert sent["diagnostics"] == shown                           # the same bundle, key for key
    assert D.canonical(sent["diagnostics"]) == answer["text"]     # and the same text
    # A second send needs a bundle of its own: the digest is looked up per person and lives a few minutes.
    assert file(api, diagnostics=answer["id"]).status_code == 200
    riley = as_person(api, "riley")
    assert file(api, headers=riley, diagnostics=answer["id"]).status_code == 409
    assert file(api, diagnostics="0" * 64).status_code == 409
    assert len(hq.tickets) == 2                                   # the two refusals reached nobody


def test_a_preview_expires_and_nothing_is_sent_without_one(environment, hq, monkeypatch):
    api = environment()
    answer, _ = bundle_of(api)
    file(api)
    assert "diagnostics" not in json.loads(hq.seen[-1].content)   # unticked: no key at all
    assert file(api).json()["sent"] == {"version": "0.2.17", "install_id": api.get("/api/v2/support/compose", headers=signed_in()).json()["install_id"]}
    monkeypatch.setattr(D, "KEEP_S", -1)
    assert file(api, diagnostics=answer["id"]).status_code == 409


def test_an_hq_from_before_diagnostics_gets_the_ticket_without_them(environment, hq, monkeypatch):
    import httpx
    api = environment()
    answer, _ = bundle_of(api)
    calls = []

    def older(request):
        body = json.loads(request.content or b"{}")
        if request.method == "POST":
            calls.append(sorted(body))
        if request.method == "POST" and "diagnostics" in body:
            return httpx.Response(422, json={"error": "invalid", "field": "fields"})
        return hq(request)
    monkeypatch.setattr(support, "TRANSPORT", httpx.MockTransport(older))
    r = file(api, diagnostics=answer["id"])
    assert r.status_code == 200 and "diagnostics" not in r.json()["sent"]
    assert calls == [["diagnostics", "install_id", "message", "version"], ["install_id", "message", "version"]]


def test_the_heartbeat_contract_takes_a_runners_recent_errors_and_keeps_them_bounded():
    from pydantic import ValidationError
    from backend import models as M
    ok = M.StructuredReadiness(recent_errors=["2026-09-29T10:00:00Z Tico runner: failed"])
    assert ok.model_dump()["recent_errors"] == ["2026-09-29T10:00:00Z Tico runner: failed"]
    assert M.StructuredReadiness().recent_errors == [] and "recent_errors" not in M.StructuredReadiness().model_dump()
    with pytest.raises(ValidationError):
        M.StructuredReadiness(recent_errors=["x"] * 51)
    # A long line is cut to 300, never refused: refusing hid a whole computer in 0.3.2.
    assert M.StructuredReadiness(recent_errors=["x" * 301]).recent_errors == ["x" * 300]


def test_the_runner_never_sends_an_error_line_over_300_characters():
    from runner import outage
    outage.RECENT.clear()
    outage.log("Tico runner: failed " + "y" * 400)
    assert outage.RECENT and all(len(line) <= 300 for line in outage.RECENT)
    outage.RECENT.clear()
