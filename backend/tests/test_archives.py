import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

from backend.archive import import_text_archives
from backend.config import ROOT
from backend.documents import import_catalog, proposal_repos
from backend.manage import migrate_legacy
from backend.store import H
from backend.tests.test_api import api, assign, claim, get, headers, post, ready, runner
from backend.tests.test_runner import live

FIXTURE_REGISTRY = Path(__file__).parent / "fixtures" / "registry"


def test_history_import_is_lossless_idempotent_and_person_scoped(api, tmp_path):
    runtime = tmp_path / "legacy"
    threads = runtime / "help/threads"
    threads.mkdir(parents=True)
    content = '{"role":"person","text":"A private conversation 🌎"}\n'
    path = threads / "ben.jsonl"
    path.write_text(content)
    (threads / "ana.jsonl").write_text('{"text":"Ana private"}\n')
    outside = tmp_path / "unrelated-secret.txt"
    outside.write_text("Do not import")
    (threads / "link.jsonl").symlink_to(outside)
    report = import_text_archives(api.app.state.store, runtime)
    assert report["files"] == 2 and len(report["skipped"]) == 1
    import_text_archives(api.app.state.store, runtime)
    own = get(api, "archives", "ben-test")["archives"]
    assert len(own) == 1
    assert own[0]["digest"] == hashlib.sha256(content.encode()).hexdigest()
    archived = api.get("/api/v2/archive", params={"source": own[0]["source"]}, headers=headers("ben-test")).json()
    assert archived["content"]["text"] == content
    assert get(api, "archives", "cara-test")["archives"] == []
    path.write_text(content + '{"role":"coo","text":"Follow-up"}\n')
    import_text_archives(api.app.state.store, runtime)
    assert len(get(api, "archives", "ben-test")["archives"]) == 2


def test_document_pr_review_is_snapshot_bound_private_and_never_merges_in_cloud(api):
    sha = "a" * 40
    proposal = {"repo": "acme/atlas", "number": 42, "title": "Clarify the cloud guide",
                "url": "https://github.com/acme/atlas/pull/42", "body": "Documentation only",
                "draft": False, "state": "open", "merged": False, "head_sha": sha,
                "head_repo": "acme/atlas", "total_files": 1, "merge_eligible": True,
                "files": [{"path": "docs/cloud.md", "status": "modified", "patch": "+Clearer text"}]}
    with api.app.state.store.transaction() as c:
        import_catalog(c, {"documents": [], "proposals": [proposal]},
                       proposal_repos(SimpleNamespace(registry_dir=FIXTURE_REGISTRY)))
    request = {"page": "doc-pr", "repo": proposal["repo"], "number": 42, "action": "load"}
    post(api, "page-chat", request, "ben-test", expected=403)
    loaded = post(api, "page-chat", request)
    assert loaded["pr"]["head_sha"] == sha and loaded["pr"]["merge_eligible"]
    post(api, "page-chat", {**request, "action": "feedback", "text": "Please revise this wording.",
         "head_sha": "b" * 40}, expected=409)
    feedback = post(api, "page-chat", {**request, "action": "feedback", "text": "Please revise this wording.",
                    "head_sha": sha})
    merge = post(api, "page-chat", {**request, "action": "merge",
                 "text": "Merge the reviewed revision " + sha + ".", "head_sha": sha})
    assert feedback["conversation"]["id"] == merge["conversation"]["id"] == loaded["conversation"]["id"]
    assert "Please revise this wording" in feedback["messages"][-1]["refs"]["comment"]
    assert "request a `merge` approval" in merge["messages"][-1]["body"]
    with api.app.state.store.read() as c:
        assert c.execute("SELECT count(*) FROM approvals").fetchone()[0] == 0
        assert c.execute("SELECT count(*) FROM jobs WHERE bot='doc-updater'").fetchone()[0] == 2
    get(api, f"conversations/{loaded['conversation']['id']}/messages", "ben-test", expected=403)
