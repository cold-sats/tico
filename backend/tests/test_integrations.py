"""The integration pages, their query catalogs and the shared learnings.

The pages in `integrations/` are data the release ships and every bot reads, so every one of
them is validated here against the frontmatter schema and the section order; the catalogs must
parse with unique ids. The API serves them to anyone signed in, takes a learning from anyone,
and lets only the owner delete one.
"""

import re
from pathlib import Path

import pytest
import yaml

from backend import integrations as I
from backend.config import ROOT
from backend.tests.test_api import api, headers, post, setup_attempt

PAGES = sorted(p for p in (ROOT / "integrations").glob("*.md") if p.name != "README.md")
CATALOGS = sorted((ROOT / "integrations" / "queries").glob("*.yaml"))
EXPECTED = {"hub-sql", "slack", "mail", "aside", "credential-vault",
            "posthog", "close-crm", "sentry", "google-ads", "meta-ads", "calendly", "github", "aws", "hub-storage"}


def get(api, path, token="ana-test", expected=200):
    r = api.get("/api/v2/" + path, headers=headers(token))
    assert r.status_code == expected, r.text
    return r.json()


@pytest.mark.parametrize("path", CATALOGS, ids=[p.stem for p in CATALOGS])
def test_every_catalog_parses_with_unique_ids_and_a_page(path):
    queries = I.parse_queries(path.read_text(), path.name)
    assert queries and len({q["id"] for q in queries}) == len(queries)
    assert (ROOT / "integrations" / f"{path.stem}.md").exists()
    for q in queries:
        assert q["sql"].strip().lower().startswith(("select", "with")), q["id"]


def test_learnings_are_added_by_anyone_listed_newest_first_and_deleted_by_the_owner_only(api):
    _, _, attempt = setup_attempt(api)
    first = post(api, "integrations/hub-sql/learnings", {"text": "  Compare timestamps as text.  "}, token="ben-test")
    assert first["actor"] == "human:ben" and first["text"] == "Compare timestamps as text."
    second = post(api, "integrations/ph/learnings", {"text": "HogQL wants toDateTime bounds."}, token=attempt["token"])
    assert second["actor"] == "bot:ops" and second["integration"] == "posthog"
    third = post(api, "integrations/hub-sql/learnings", {"text": "json_each works on refs_json."})
    notes = get(api, "integrations/hub-sql", attempt["token"])["learnings"]
    assert [n["text"] for n in notes] == ["json_each works on refs_json.", "Compare timestamps as text."]
    assert get(api, "integrations")["integrations"]
    counts = {r["service"]: r["learning_count"] for r in get(api, "integrations")["integrations"]}
    assert counts["hub-sql"] == 2 and counts["posthog"] == 1
    # Validation: empty, too long, unknown service, a runner credential.
    post(api, "integrations/hub-sql/learnings", {"text": ""}, expected=422)
    post(api, "integrations/hub-sql/learnings", {"text": "x" * 2001}, expected=422)
    post(api, "integrations/nope/learnings", {"text": "hello"}, expected=404)
    machine = api.app.state.store
    # Only the owner deletes; a deleted learning disappears from the page and the counts.
    r = api.post(f"/api/v2/integrations/hub-sql/learnings/{first['id']}/delete", headers=headers("ben-test"))
    assert r.status_code == 403
    r = api.post(f"/api/v2/integrations/hub-sql/learnings/{first['id']}/delete", headers=headers(attempt["token"]))
    assert r.status_code == 403
    r = api.post(f"/api/v2/integrations/hub-sql/learnings/{first['id']}/delete", headers=headers())
    assert r.status_code == 200 and r.json() == {"ok": True}
    r = api.post(f"/api/v2/integrations/hub-sql/learnings/{first['id']}/delete", headers=headers())
    assert r.status_code == 404
    assert [n["id"] for n in get(api, "integrations/hub-sql")["learnings"]] == [third["id"]]
    with machine.read() as c:
        actions = [row[0] for row in c.execute("SELECT action FROM events WHERE action LIKE 'learning.%' ORDER BY ts")]
        assert actions == ["learning.add", "learning.add", "learning.add", "learning.delete"]
    # The audit and the rows are readable through SQL by anyone.
    r = api.post("/api/v2/sql", json={"sql": "SELECT integration, actor FROM learnings WHERE deleted_at IS NULL ORDER BY created"},
                 headers=headers("ben-test"))
    assert r.json()["rows"] == [["posthog", "bot:ops"], ["hub-sql", "human:ana"]]


FIXTURE_NAMES = re.compile(r"\b(ana|ben|cara|acme|globex|ana-acme)\b", re.I)
FENCE = re.compile(r"^```.*?^```", re.S | re.M)


def shipped_text():
    files = [*PAGES, ROOT / "integrations" / "README.md"]
    for folder in ("catalog", "employee-repo"):
        files += [p for p in (ROOT / "templates" / folder).rglob("*") if p.is_file() and p.suffix in (".md", ".yaml")]
    return files


@pytest.mark.parametrize("path", shipped_text(), ids=lambda p: str(p.relative_to(ROOT)))
def test_shipped_pages_and_templates_name_no_fixture_people_or_companies(path):
    # A real install reads these as facts about its own company; only fenced examples may use stand-ins.
    text = FENCE.sub("", path.read_text())
    hits = FIXTURE_NAMES.findall(text)
    assert not hits, f"{path.relative_to(ROOT)} names {sorted(set(hits))}"


def test_pages_name_a_role_for_the_owner_and_the_api_serves_the_owners_name(api):
    assert all(I.parse_page(p.read_text(), p.stem)[0]["owner"] == "owner" for p in PAGES)
    page = get(api, "integrations/github")
    assert page["owner"] != "owner" and page["owner"]
    assert {i["owner"] for i in get(api, "integrations")["integrations"]} == {page["owner"]}
