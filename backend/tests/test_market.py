"""The shared market graph: seed, read, report, curator writes."""

import json
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch


from backend import market as M
from backend.blobs import Blobs
from backend.store import H
from backend.tests.test_api import api, get, headers, post, setup_attempt  # noqa: F401
from clients import hubtools

ROOT = Path(__file__).resolve().parents[2]
FIXTURE_REGISTRY = Path(__file__).parent / "fixtures" / "registry"


def _seed(api, tmp_path):
    store = api.app.state.store
    with store.transaction() as c:
        M.seed(c, {}, Blobs(store.settings), document=M.load_snapshot(FIXTURE_REGISTRY))
        M.ensure_analyst(c, force=True)
        if not H.bot(c, "listening"):
            c.execute("INSERT INTO bots (slug, display_name, runtime, model, effort, cwd, host, state, created) "
                      "VALUES (?,?,?,?,?,?,?,?,?)",
                      ("listening", "Listening", "grok", "grok-4.6", "high", "", "keeper", "active", H.now()))
        if not c.execute("SELECT 1 FROM bot_config WHERE bot='listening'").fetchone():
            c.execute("INSERT INTO bot_config (bot, config_json, team, operator, description, reports_to, repo) "
                      "VALUES (?,?,?,?,?,?,?)",
                      ("listening", "{}", "marketing", "ana", "Listening", "cmo", "emp-listening"))


def test_show_find_edges_delta_and_a_report_does_not_write_the_graph(api, tmp_path):
    _seed(api, tmp_path)
    shown = get(api, "market/entities/company/northwind")
    assert shown["entity"]["id"] == "company/northwind"
    assert shown["edges"]["competes_with"]["out"]
    assert shown["edges"]["competes_with"]["in"] == []
    assert shown["evidence"]
    assert len(shown["events"]) <= 10
    acme = get(api, "market/entities/company/acme")
    assert acme["edges"]["competes_with"]["in"]
    assert get(api, "market/entities?q=Brightline%20YC")["entities"][0]["id"] == "company/brightline"
    both = get(api, "market/edges?src=company/acme&rel=competes_with")["edges"]
    assert any(edge["dst"] == "company/acme" and edge["src"] == "company/northwind" for edge in both)
    assert len(both) == len({edge["id"] for edge in both})
    before = get(api, "market/entities?type=company")["entities"]
    report = post(api, "market/insights", {"kind": "edge", "about": "Northwind",
                                           "claim": "Northwind changed a fee.", "confidence": "low"},
                  token="ben-test")["insight"]
    assert report["id"] and report["status"] == "new"
    _, _, listening = setup_attempt(api, "listening")
    other = post(api, "market/insights", {"kind": "other", "about": "Brightline",
                                          "claim": "Brightline was mentioned on a host thread.", "confidence": "medium"},
                 token=listening["token"])["insight"]
    assert other["id"]
    after = get(api, "market/entities?type=company")["entities"]
    assert [(row["id"], row["summary"]) for row in after] == [(row["id"], row["summary"]) for row in before]
    with api.app.state.store.read() as c:
        assert c.execute("SELECT count(*) FROM market_edges").fetchone()[0] == 6
    # as-of keeps an edge whose span covers the date
    evidence = post(api, "market/evidence", {"source_kind": "site", "quote": "ended", "our_read": "The partnership ended."})["evidence"]
    edge = post(api, "market/edges", {"src": "company/northwind", "rel": "partners_with", "dst": "company/acme",
                                      "since": "2020-01-01", "until": "2024-01-01", "confidence": "low",
                                      "evidence_ids": [evidence["id"]]})["edge"]
    covered = get(api, f"market/edges?src=company/northwind&rel=partners_with&as_of=2022-06-01")["edges"]
    assert edge["id"] in {row["id"] for row in covered}
    assert get(api, "market/edges?src=company/northwind&rel=partners_with&as_of=2025-01-01")["edges"] == []
    post(api, f"market/entities/company/northwind", {"summary": "A national manager.", "evidence_ids": [evidence["id"]]})
    grouped = get(api, "market/delta?since=1d")["entities"]
    assert "company/northwind" in {row["id"] for row in grouped}


def test_the_server_enforces_writers_evidence_vocabulary_and_no_delete(api, tmp_path):
    _seed(api, tmp_path)
    body = {"type": "company", "name": "Newco", "summary": "A company."}
    post(api, "market/entities", body, token="ben-test", expected=403)
    post(api, "market/entities", body, expected=422)
    evidence = post(api, "market/evidence", {"source_kind": "news", "quote": "Newco launched.", "our_read": "A new company."})["evidence"]
    post(api, "market/edges", {"src": "company/northwind", "rel": "friends_with", "dst": "company/acme",
                               "evidence_ids": [evidence["id"]]}, expected=422)
    post(api, "market/edges", {"src": "company/northwind", "rel": "partners_with", "dst": "company/acme",
                               "since": "2026-05-01", "until": "2026-01-01", "evidence_ids": [evidence["id"]]}, expected=422)
    post(api, "market/entities", {"type": "company", "name": "Also Northwind", "aliases": ["Northwind"],
                                  "evidence_ids": [evidence["id"]]}, expected=422)
    forced = post(api, "market/entities", {"type": "company", "name": "Also Northwind", "aliases": ["Northwind"],
                                           "evidence_ids": [evidence["id"]], "force": True})["entity"]
    post(api, f"market/entities/{forced['id']}", {"aliases": ["Northwind", "also-northwind"]})
    post(api, f"market/entities/{forced['id']}", {"summary": "No evidence."}, expected=422)
    merged = post(api, f"market/entities/{forced['id']}/merge", {"into": "company/northwind"})["entity"]
    assert merged["status"] == "merged" and merged["merged_into"] == "company/northwind"
    assert get(api, f"market/entities/{forced['id']}")["entity"]["id"] == forced["id"]
    retired = post(api, "market/entities/company/pricewise/retire", {})["entity"]
    assert retired["status"] == "retired"
    assert get(api, "market/entities/company/pricewise")["entity"]["status"] == "retired"
    denied = api.delete("/api/v2/market/entities/company/northwind", headers=headers())
    assert denied.status_code == 405
    assert get(api, "market/entities/company/northwind")["entity"]["name"] == "Northwind"
    _, _, analyst = setup_attempt(api, "market-analyst")
    created = post(api, "market/entities", {"type": "company", "name": "Analyst Co", "evidence_ids": [evidence["id"]]},
                   token=analyst["token"])["entity"]
    assert created["created_by"] == "bot:market-analyst"


def test_the_curator_applies_an_insight_files_one_owner_task_and_only_marked_stale_entities(api, tmp_path):
    _seed(api, tmp_path)
    _, _, listening = setup_attempt(api, "listening")
    _, _, analyst = setup_attempt(api, "market-analyst")
    with api.app.state.store.read() as c:
        quiet = c.execute("SELECT count(*) FROM tasks WHERE owner='bot:market-analyst'").fetchone()[0]
    post(api, "market/insights", {"kind": "other", "about": "Northwind", "claim": "Nothing urgent.", "urgent": False},
         token=listening["token"])
    with api.app.state.store.read() as c:
        assert c.execute("SELECT count(*) FROM tasks WHERE owner='bot:market-analyst'").fetchone()[0] == quiet
    woke = post(api, "market/insights", {"kind": "edge", "about": "Brightline", "claim": "Brightline launched a flat fee.",
                                        "urgent": True, "source_url": "https://brightline.example/pricing",
                                        "quote": "Flat monthly pricing."}, token=listening["token"])["insight"]
    with api.app.state.store.read() as c:
        assert c.execute("SELECT count(*) FROM tasks WHERE owner='bot:market-analyst'").fetchone()[0] == quiet + 1
    applied = post(api, f"market/insights/{woke['id']}/apply", {
        "evidence": {"source_url": "https://brightline.example/pricing", "source_kind": "site", "quote": "Flat monthly pricing.",
                     "our_read": "Brightline is selling a flat monthly tier."},
        "entity_id": "company/brightline", "summary": "Brightline sells a flat monthly management tier."},
        token=analyst["token"])
    assert applied["insight"]["status"] == "applied"
    assert applied["events"]
    with api.app.state.store.read() as c:
        events = c.execute("SELECT subject_kind, field, insight_id FROM market_events WHERE insight_id=? ORDER BY rowid",
                           (woke["id"],)).fetchall()
    assert events[0]["subject_kind"] == "evidence"
    assert any(row["subject_kind"] == "entity" and row["field"] == "summary" for row in events)
    for status, claim in (("needs-human", "First disagreement."), ("needs-human", "Second disagreement."),
                          ("needs-human", "Third disagreement.")):
        row = post(api, "market/insights", {"kind": "question", "about": "Fees", "claim": claim},
                   token="ben-test")["insight"]
        post(api, f"market/insights/{row['id']}/resolve", {"status": status, "resolution": "Two sources disagree."},
             token=analyst["token"])
    today = date(2026, 9, 21)
    with api.app.state.store.transaction() as c:
        c.execute("UPDATE market_entities SET last_verified=? WHERE id='company/northwind'",
                  ((today - timedelta(days=31)).isoformat(),))
        c.execute("UPDATE market_entities SET last_verified=? WHERE id='company/harborly'",
                  ((today - timedelta(days=61)).isoformat(),))
        c.execute("UPDATE market_entities SET last_verified=? WHERE id='company/fernwood'",
                  ((today - timedelta(days=1)).isoformat(),))
        c.execute("UPDATE market_entities SET last_verified=? WHERE id='company/doorlark'",
                  ((today - timedelta(days=90)).isoformat(),))
    result = post(api, "market/curator/sweep", {"today": today.isoformat(), "unverified": [
        {"id": "company/northwind", "look_for": "whether Northwind still manages homes"},
        {"id": "company/harborly", "look_for": "whether Harborly still sells to landlords"},
        {"id": "company/fernwood", "look_for": "this one is fresh and must not be tasked"},
    ]}, token=analyst["token"])
    assert result["owner_task"]
    with api.app.state.store.read() as c:
        owner = c.execute("SELECT * FROM tasks WHERE id=?", (result["owner_task"],)).fetchone()
        assert owner["owner"] == "human:ana"
        assert "First disagreement." in owner["body"] and "Second disagreement." in owner["body"]
        assert "Third disagreement." in owner["body"]
        assert c.execute("SELECT count(*) FROM tasks WHERE owner='human:ana' AND requester='bot:market-analyst'").fetchone()[0] == 1
        listening_rows = c.execute("SELECT title, body FROM tasks WHERE owner='bot:listening' AND requester='bot:market-analyst'").fetchall()
    bodies = " ".join(row["body"] for row in listening_rows)
    assert "company/northwind" in bodies and "company/harborly" in bodies
    assert "company/fernwood" not in bodies and "company/doorlark" not in bodies
    assert "whether Northwind still manages homes" in bodies


def test_the_curator_rewrites_a_narrative_page_and_nobody_else_does(api, tmp_path):
    """#488: the market pages were still the seed listings; the curator had no way to write one."""
    _seed(api, tmp_path)
    page = post(api, "market/pages/overview", {"body": "# Overview\n\nThree AI property managers launched this month."})
    assert page["id"] == "market/overview" and page["title"] == "Overview" and page["owner"] == "bot:market-analyst"
    with api.app.state.store.read() as c:
        assert M.read_page(c, "market/overview")["content"].startswith("# Overview\n\nThree AI")
    post(api, "market/pages/overview", {"body": "# Mine"}, token="ben-test", expected=403)
    post(api, "market/pages/weekly-delta", {"body": "# Delta"}, expected=404)
    post(api, "market/pages/nonsense", {"body": "# X"}, expected=404)
    assert "hub_market_page" in hubtools.BY_NAME
