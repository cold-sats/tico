import hashlib

from backend.archive import import_text_archives
from backend.tests.test_api import api, get, headers  # noqa: F401  (the api fixture)


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
