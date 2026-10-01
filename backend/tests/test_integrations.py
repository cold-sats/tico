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
from backend.tests.test_api import api, headers

PAGES = sorted(p for p in (ROOT / "integrations").glob("*.md") if p.name != "README.md")
CATALOGS = sorted((ROOT / "integrations" / "queries").glob("*.yaml"))
# Only outside services Tico has built-in support for ship; a company adds its own pages in its
# config (<registry>/integrations or TICO_INTEGRATIONS_DIR), layered over these.
SHIPPED = {"github", "slack", "mail", "aside", "close-crm", "postgres", "mysql", "mongodb", "sqlite"}


def get(api, path, token="ana-test", expected=200):
    r = api.get("/api/v2/" + path, headers=headers(token))
    assert r.status_code == expected, r.text
    return r.json()


def test_the_release_ships_only_built_in_services_and_every_page_parses():
    pages, _ = I.load(ROOT / "integrations")
    assert set(pages) == SHIPPED
    assert {name: pages[name]['title'] for name in ('aside', 'postgres', 'mysql', 'mongodb', 'sqlite')} == {
        'aside': 'Aside', 'postgres': 'PostgreSQL', 'mysql': 'MySQL and MariaDB', 'mongodb': 'MongoDB', 'sqlite': 'SQLite'}
    with pytest.raises(I.Problem, match='No tool named missing'):
        I.Catalog(ROOT / "integrations").resolve('missing')


def test_a_company_page_adds_a_service_and_replaces_a_shipped_one(tmp_path):
    github = (ROOT / "integrations" / "github.md").read_text()
    (tmp_path / "github.md").write_text(github.replace("title: GitHub", "title: GitHub (our org)"))
    (tmp_path / "stripe.md").write_text(github.replace("service: github", "service: stripe"))
    pages, _ = I.load(ROOT / "integrations", tmp_path)
    assert pages["github"]["title"] == "GitHub (our org)"
    assert set(pages) == SHIPPED | {"stripe"}


@pytest.mark.parametrize("path", CATALOGS, ids=[p.stem for p in CATALOGS])
def test_every_catalog_parses_with_unique_ids_and_a_page(path):
    queries = I.parse_queries(path.read_text(), path.name)
    assert queries and len({q["id"] for q in queries}) == len(queries)
    assert (ROOT / "integrations" / f"{path.stem}.md").exists()
    for q in queries:
        assert q["sql"].strip().lower().startswith(("select", "with")), q["id"]


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
