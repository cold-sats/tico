"""The Tico manual: this release's docs, searchable, read-only and apart from the company's docs (docs/docs.md)."""

from pathlib import Path

from backend import manual
from backend.tests.test_api import api  # noqa: F401  (the api fixture)
from backend.tests.test_docs import ANA, call, make

ROOT = Path(__file__).resolve().parents[2]


def test_the_url_rule_is_the_release_tag_or_main():
    assert manual.manual_url("0.2.19", "backups", "restore") == "https://github.com/ticoteam/tico/blob/v0.2.19/docs/backups.md#restore"
    assert manual.manual_url("dev", "backups") == "https://github.com/ticoteam/tico/blob/main/docs/backups.md"
    assert manual.slug("How it `works` (2)") == "how-it-works-2"


def test_manual_results_are_labelled_and_cited_with_file_and_link(api, monkeypatch):
    monkeypatch.setenv("TICO_VERSION", "v0.2.19")
    found = call(api, "GET", "docs/search?q=how+do+I+add+a+watcher&collection=manual")["results"]
    assert found and all(r["collection"] == "manual" and r["label"] == "Tico manual" and r["type"] == "manual" for r in found)
    top = found[0]
    assert top["path"] == "docs/watchers.md" and top["excerpt"]
    assert top["url"].startswith("https://github.com/ticoteam/tico/blob/v0.2.19/docs/watchers.md")
    page = call(api, "GET", "docs/manual/watchers")["doc"]
    assert page["read_only"] and page["label"] == "Tico manual" and "watchers" in page["body"].lower()
    call(api, "GET", "docs/manual/nope", expected=404)


def test_the_manual_is_read_only_and_never_mixed_with_company_docs(api):
    mine = make(api, "Watchers at Acme", "Our watchers poll the warehouse every hour.")
    # The Docs page's search and the company's list know nothing of the manual.
    assert [r["path"] for r in call(api, "GET", "docs/search?q=watchers")["results"]] == [mine["path"]]
    assert not any(d["path"].startswith(("manual", "docs/")) for d in call(api, "GET", "docs")["docs"])
    # Together, the company's own doc comes first and each result says which collection it is from.
    both = call(api, "GET", "docs/search?q=watchers&collection=all")["results"]
    assert any(r["collection"] == "company" and r["id"] == mine["id"] for r in both)
    assert any(r["collection"] == "manual" for r in both)
    assert [r["score"] for r in both] == sorted((r["score"] for r in both), reverse=True)
    # Nothing writes to it.
    call(api, "PATCH", "docs/manual:watchers", {"version": 1, "body": "x"}, expected=405)
    call(api, "POST", "docs/manual:watchers/restore", {"version": 1}, expected=405)
    assert call(api, "GET", "docs/manual/watchers")["doc"]["body"] == (ROOT / "docs/watchers.md").read_text()


def test_the_manual_is_rebuilt_when_the_release_or_a_file_changes(monkeypatch, tmp_path):
    (tmp_path / "widgets.md").write_text("# Widgets\n\n## Polishing\n\nUse the polish command on a widget.\n")
    monkeypatch.setattr(manual, "DOCS_DIR", tmp_path)
    monkeypatch.setenv("TICO_VERSION", "1.0.0")
    first = manual.search("polish widget")[0]
    assert first["version"] == "1.0.0" and first["url"].endswith("/v1.0.0/docs/widgets.md#polishing") and first["path"] == "docs/widgets.md"
    monkeypatch.setenv("TICO_VERSION", "1.0.1")
    assert manual.search("polish widget")[0]["url"].startswith("https://github.com/ticoteam/tico/blob/v1.0.1/")
    (tmp_path / "widgets.md").write_text("# Widgets\n\n## Buffing\n\nBuff the widget with wax.\n")
    assert manual.search("polish") == [] and manual.search("buff wax")[0]["title"] == "Widgets > Buffing"


def test_the_image_ships_the_docs():
    assert not any(line.strip().rstrip("/") in ("docs", "docs/*.md") for line in (ROOT / ".dockerignore").read_text().splitlines())
    assert "COPY . /opt/tico" in (ROOT / "Dockerfile").read_text()
    assert len(manual.pages()) > 20 and "how-it-works" in manual.pages()


def test_search_normalizes_old_words_keeps_the_question_tail_and_ranks_sections(api):
    make(api, "Search log", "Needs setup. Trello. Linear tools. Add a computer. Join code.", path="_librarian/faq-log.md")
    for question, expected, section in [
        ("Why does my new bot say Needs setup, and what should I do next?", "onboarding", "Needs setup"),
        ("How do I connect Trello for a scheduled bot?", "connect-tools", "Trello"),
        ("Linear integration", "connect-tools", "Linear"),
        ("How do I add a new machine to run bots and how long does its join code last", "install", "Add computers"),
    ]:
        hits = call(api, "GET", "docs/search", params={"q": question, "collection": "all", "limit": 3})["results"]
        assert hits[0]["path"] == "docs/" + expected + ".md"
        assert section in hits[0]["section"] and hits[0]["excerpt"]
    assert "join" in manual.query_words("How do I add a new machine to run bots and how long does its join code last")
    assert manual.query_words("people page and onboarding") == ["humans", "setup"]
