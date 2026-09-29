"""The Librarian eval's own bookkeeping (docs-eval/run.py): the questions point at real fixture docs and the
scoring counts a citation, a fact and a plain "Not in the docs." the way docs/librarian.md says. The eval
itself needs a live Tico and runs on demand (scripts/docs-eval.sh)."""

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("docs_eval", ROOT / "docs-eval/run.py")
E = importlib.util.module_from_spec(spec)
spec.loader.exec_module(E)

IDS = {E.PREFIX + "finance/refunds.md": "r1", E.PREFIX + "company/about.md": "a1"}


def test_every_question_cites_a_fixture_doc_that_exists_and_two_are_unanswerable():
    questions = E.load_questions()
    assert len(questions) >= 12 and sum(bool(q.get("unknown")) for q in questions) == 2
    files = {p.relative_to(E.HERE / "fixture").as_posix() for p in E.fixture_files()}
    assert {path for q in questions for path in q.get("cite") or []} <= files
    assert len({q["id"] for q in questions}) == len(questions)


def test_a_citation_needs_every_expected_doc_and_a_real_answer():
    q = {"id": "x", "question": "Who approves?", "cite": ["finance/refunds.md", "company/about.md"], "contains": ["Ana"]}
    both = "Ana Rivera. [Internal doc · Refunds](doc:r1) [Internal doc · About](doc:a1)"
    assert E.score(q, both, IDS)["cited"] and E.score(q, both, IDS)["facts"]
    assert not E.score(q, "Ana. [Internal doc · Refunds](doc:r1)", IDS)["cited"]
    assert not E.score(q, "Not in the docs. [Internal doc · Refunds](doc:r1) [Internal doc · About](doc:a1)", IDS)["cited"]
    assert not E.score(q, "Ben. [Internal doc · Refunds](doc:r1) [Internal doc · About](doc:a1)", IDS)["facts"]
    assert E.score(q, None, IDS) == {"answered": False, "cited": False, "unknown_ok": False, "facts": False}


def test_an_unanswerable_question_is_right_only_when_it_says_not_in_the_docs():
    q = {"id": "y", "question": "Gift cards?", "unknown": True}
    assert E.score(q, "Not in the docs. Nothing mentions them.", IDS)["unknown_ok"]
    assert not E.score(q, "Yes, we sell them.", IDS)["unknown_ok"]
    results = [{"score": E.score(q, "Not in the docs.", IDS), "seconds": 4},
               {"score": E.score(q, "Yes.", IDS), "seconds": 8}]
    assert E.summary(results)["unknown_rate"] == 0.5 and E.summary(results)["median_seconds"] == 6
