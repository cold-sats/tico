"""Pages, Library › Files, file search and hard delete (docs/pages.md, docs/files.md). Visibility first: a page or
file the reader may not read leaves no title, count or text anywhere."""

import hashlib
from datetime import datetime, timedelta, timezone

from backend import file_library, pages as P
from backend.store import encode
from backend.tests.test_api import api, headers, post  # noqa: F401  (fixtures)
from backend.tests.test_files import publish, turn

HTML = (b"<html><head><title>Weekly</title><script>alert('x')</script></head><body><h1>Acme weekly review</h1>"
        b"<p>Pipeline grew to <b>42 deals</b>.</p><img src='https://cdn.acme.example/x.png'></body></html>")


def page(api, attempt, name="weekly.html", data=HTML, **query):
    r = api.post("/api/v2/pages", params={"name": name, **query}, content=data,
                 headers={**headers(attempt["token"]), "Content-Type": "text/html"})
    return r


def read(api, fid, who):
    return api.get("/api/v2/pages/" + fid, headers=headers(who))


def test_a_published_page_is_cleaned_and_reads_with_its_status_fields_only_for_whoever_may_see_it(api):
    _, attempt = turn(api)                                    # ben's chat with ops
    made = page(api, attempt, title="Engineering weekly", cadence="weekly", as_of="2026-10-27")
    assert made.status_code == 200, made.text
    body = made.json()
    fid = body["page"]["file_id"]
    assert body["unembedded"] == ["https://cdn.acme.example/x.png"]
    stored = api.get("/api/v2/files/" + fid, headers=headers("ben-test")).content
    assert b"<script" not in stored and b"cdn.acme.example" not in stored and b"42 deals" in stored
    seen = read(api, fid, "ben-test").json()["page"]
    assert set(seen) >= {"file_id", "title", "bot", "bot_name", "version", "updated", "updated_by", "cadence",
                         "as_of", "stale_days", "replaced_by", "archived", "task_id", "src"}
    assert (seen["title"], seen["cadence"], seen["as_of"], seen["version"]) == ("Engineering weekly", "weekly",
                                                                                 "2026-10-27", 1)
    assert seen["updated_by"] == "bot:ops" and seen["stale_days"] is None
    assert seen["src"] is None                                # no visual address: an Open card
    for other in ("cara-test", "ana-test"):
        assert read(api, fid, other).status_code == 404
        many = api.get("/api/v2/pages", params={"ids": fid}, headers=headers(other)).json()
        assert many == {"pages": []}
        assert "Engineering" not in api.get("/api/v2/pages", headers=headers(other)).text
    # The same bytes again are no new version; a change is.
    assert page(api, attempt).json()["page"]["version"] == 1
    assert page(api, attempt, data=HTML.replace(b"42", b"43")).json()["page"]["version"] == 2


def test_a_page_has_an_inline_address_only_with_a_visual_address(api):
    _, attempt = turn(api)
    fid = page(api, attempt).json()["page"]["file_id"]
    api.app.state.store.settings.visual_origin = "https://visuals.acme.example"
    try:
        src = read(api, fid, "ben-test").json()["page"]["src"]
    finally:
        api.app.state.store.settings.visual_origin = ""
    assert src.startswith("https://visuals.acme.example/visuals/")


def test_publishing_refuses_what_is_not_a_page(api):
    _, attempt = turn(api)
    assert page(api, attempt, name="notes.md").status_code == 422
    assert page(api, attempt, cadence="hourly").status_code == 422
    assert page(api, attempt, as_of="last week").status_code == 422
    assert api.post("/api/v2/pages", params={"name": "x.html"}, content=HTML,
                    headers=headers("ben-test")).status_code == 403          # a person does not publish a bot's page


def test_a_page_goes_stale_after_one_and_a_half_cadences():
    now = datetime(2026, 10, 28, tzinfo=timezone.utc)
    stamp = lambda days: (now - timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
    assert P.stale_days(stamp(10), "weekly", now) is None
    assert P.stale_days(stamp(11), "weekly", now) == 11
    assert P.stale_days(stamp(2), "daily", now) == 2
    assert P.stale_days(stamp(400), "none", now) is None


def test_a_replaced_page_names_its_replacement_only_to_readers_who_may_see_it(api):
    _, attempt = turn(api)
    old = page(api, attempt).json()["page"]["file_id"]
    new = page(api, attempt, name="weekly-2.html", data=HTML + b"<p>v2</p>", replaces=old).json()["page"]
    seen = read(api, old, "ben-test").json()["page"]
    assert (seen["replaced_by"], seen["replaced_by_title"]) == (new["file_id"], "weekly-2.html")
    # Another bot's page cannot be named.
    _, other = turn(api, bot="finance")
    assert page(api, other, name="f.html", replaces=old).status_code == 404


def test_a_page_filed_on_a_task_is_pinned_to_its_top_and_says_where_it_is_pinned(api):
    _, attempt = turn(api)
    task = post(api, "tasks", {"owner": "ops", "title": "Q3 launch", "body": "x", "private": True}, token="ben-test")
    made = page(api, attempt, name="launch.html", task=task["id"])
    assert made.status_code == 200, made.text
    fid = made.json()["page"]["file_id"]
    page(api, attempt, name="launch.html", task=task["id"], data=HTML + b"<p>v2</p>")      # a new version: one pin
    place = api.get("/api/v2/places/task:" + task["id"], headers=headers("ben-test")).json()
    assert [(p["item"], p["page"]["version"]) for p in place["pins"]] == [("page:" + fid, 2)]
    assert read(api, fid, "ben-test").json()["pinned"] == [{"place": "task:" + task["id"], "label": "Q3 launch"}]
    assert read(api, fid, "cara-test").status_code == 404                                   # a private task's page


def test_latest_pages_lists_current_pages_only(api):
    _, attempt = turn(api)
    old = page(api, attempt).json()["page"]["file_id"]
    new = page(api, attempt, name="weekly-2.html", data=HTML + b"<p>v2</p>", replaces=old).json()["page"]["file_id"]
    publish(api, attempt, name="notes.html", text="<p>not a page</p>")          # an HTML file, never published as a page
    pins = api.get("/api/v2/places/dashboard", headers=headers("ben-test")).json()["pins"]
    latest = next(p["card"]["data"] for p in pins if p["card"]["template"] == "latest_pages")
    assert [p["file_id"] for p in latest["pages"]] == [new]


def test_archiving_hides_a_page_from_lists_and_search_until_its_bot_publishes_a_change(api):
    _, attempt = turn(api)
    fid = page(api, attempt).json()["page"]["file_id"]
    assert api.patch("/api/v2/pages/" + fid, json={"archived": True}, headers=headers("cara-test")).status_code == 404
    done = api.patch("/api/v2/pages/" + fid, json={"archived": True}, headers=headers(attempt["token"]))
    assert done.status_code == 200 and done.json()["page"]["archived"] is True
    assert api.get("/api/v2/pages", headers=headers("ben-test")).json()["pages"] == []
    assert [p["file_id"] for p in api.get("/api/v2/pages?archived=true", headers=headers("ben-test")).json()["pages"]] == [fid]
    assert read(api, fid, "ben-test").status_code == 200    # still opens from a link
    assert api.get("/api/v2/files/search?q=pipeline", headers=headers("ben-test")).json()["results"] == []
    page(api, attempt, data=HTML + b"<p>new</p>")
    assert [p["file_id"] for p in api.get("/api/v2/pages", headers=headers("ben-test")).json()["pages"]] == [fid]


def test_library_lists_only_what_each_person_may_see_without_totals_and_pages_on(api):
    _, attempt = turn(api)
    for i in range(5):
        assert publish(api, attempt, name=f"note-{i}.md", text=f"# Note {i}").status_code == 200
    page(api, attempt)
    first = api.get("/api/v2/files?limit=4", headers=headers("ben-test")).json()
    assert "total" not in first and len(first["files"]) == 4 and first["has_more"]
    rest = api.get("/api/v2/files", params={"limit": 4, "cursor": first["next_cursor"]}, headers=headers("ben-test")).json()
    ids = [f["id"] for f in first["files"] + rest["files"]]
    assert len(ids) == len(set(ids)) == 6 and not rest["has_more"]
    pages_only = api.get("/api/v2/files?kind=page", headers=headers("ben-test")).json()["files"]
    assert [f["library_kind"] for f in pages_only] == ["page"]
    docs = api.get("/api/v2/files?kind=document", headers=headers("ben-test")).json()["files"]
    assert len(docs) == 5
    for other in ("cara-test", "ana-test"):
        seen = api.get("/api/v2/files", headers=headers(other))
        assert seen.json() == {"files": [], "has_more": False, "next_cursor": None}
    assert api.get("/api/v2/files?kind=everything", headers=headers("ben-test")).status_code == 422


def test_search_finds_text_and_titles_ranks_titles_first_and_never_shows_another_persons_file(api):
    _, attempt = turn(api)
    publish(api, attempt, name="pricing.md", text="# Pricing\nThe enterprise plan costs more.")
    publish(api, attempt, name="notes.md", text="We talked about pricing for the launch.")
    publish(api, attempt, name="pipeline.csv", text="account,stage,amount\nAcme,won,100\n")
    page(api, attempt)
    hits = api.get("/api/v2/files/search?q=pricing", headers=headers("ben-test")).json()["results"]
    assert [h["title"] for h in hits][:2] == ["pricing.md", "notes.md"]
    assert hits[1]["excerpt"].startswith("We talked about pricing")
    assert [h["title"] for h in api.get("/api/v2/files/search?q=stage", headers=headers("ben-test")).json()["results"]] == ["pipeline.csv"]
    assert [h["page"] for h in api.get("/api/v2/files/search?q=deals", headers=headers("ben-test")).json()["results"]] == [True]
    # A page's script is not its text.
    assert api.get("/api/v2/files/search?q=alert", headers=headers("ben-test")).json()["results"] == []
    for other in ("cara-test", "ana-test"):
        assert api.get("/api/v2/files/search?q=pricing", headers=headers(other)).json() == {"results": []}


def test_the_background_pass_indexes_older_files_and_lists_task_attachments(api):
    _, attempt = turn(api)
    fid = publish(api, attempt, name="old.md", text="An archived quarterly forecast").json()["file"]["id"]
    store = api.app.state.store
    with store.transaction() as c:
        file_library.unindex(c, fid)
    assert api.get("/api/v2/files/search?q=forecast", headers=headers("ben-test")).json()["results"] == []
    task = post(api, "tasks", {"owner": "bot:ops", "title": "Review the budget", "body": "Check Q3", "private": True}, "ben-test")
    digest = api.app.state.blobs.put(b"quarter,total\nQ3,9\n", "text/csv")
    with store.transaction() as c:
        from backend.blobs import register
        from backend.auth import Identity
        item = register(c, Identity("human:ben", "human"), digest, 19, "budget.csv", "text/csv")
        c.execute("INSERT INTO task_assets VALUES(?,?)", (task["id"], item["id"]))
    assert file_library.backfill(store, api.app.state.blobs) >= 2
    assert [h["id"] for h in api.get("/api/v2/files/search?q=forecast", headers=headers("ben-test")).json()["results"]] == [fid]
    listed = api.get("/api/v2/files?task=" + task["id"], headers=headers("ben-test")).json()["files"]
    assert [f["title"] for f in listed] == ["budget.csv"]
    assert api.get("/api/v2/files?task=" + task["id"], headers=headers("cara-test")).json()["files"] == []


def test_hard_delete_is_the_owners_removes_the_bytes_and_keeps_only_that_it_happened(api):
    _, attempt = turn(api, who="ana-test")                    # ana's chat: the owner sees its files
    gone = publish(api, attempt, name="leak.md", text="secret plan v1").json()["file"]["id"]
    publish(api, attempt, name="leak.md", text="secret plan v2")
    kept = publish(api, attempt, name="copy.md", text="secret plan v2").json()["file"]["id"]   # the same bytes
    blobs = api.app.state.blobs
    with api.app.state.store.read() as c:
        digests = {r[0] for r in c.execute("SELECT digest FROM bot_file_versions WHERE file_id=?", (gone,))}
    assert len(digests) == 2
    for who in ("ben-test", attempt["token"]):
        assert api.delete("/api/v2/files/" + gone, headers=headers(who)).status_code == 403
    done = api.delete("/api/v2/files/" + gone, headers=headers("ana-test"))
    assert done.status_code == 200 and done.json() == {"deleted": gone, "versions": 2}
    still = {d for d in digests if (blobs.directory / blobs.key(d)).is_file()}
    assert still == {hashlib.sha256(b"secret plan v2").hexdigest()}       # v1's bytes are gone, the shared ones stay
    assert api.get("/api/v2/files/" + kept, headers=headers("ana-test")).content == b"secret plan v2"
    for path in ("", "/versions/1"):
        assert api.get("/api/v2/files/" + gone + path, headers=headers("ana-test")).status_code == 404
    assert api.get("/api/v2/files/" + gone + "/versions", headers=headers("ana-test")).json()["versions"] == []
    log = api.get("/api/v2/files/" + gone + "/activity", headers=headers("ana-test")).json()["activity"]
    assert log[0]["action"] == "deleted" and log[0]["digest"] is None
    listed = api.get("/api/v2/files", headers=headers("ana-test")).text
    search = api.get("/api/v2/files/search?q=secret", headers=headers("ana-test")).json()["results"]
    assert gone not in listed and [h["id"] for h in search] == [kept]
    assert api.delete("/api/v2/files/" + gone, headers=headers("ana-test")).status_code == 404
    # The same path published again is a new file, not the deleted one.
    again = publish(api, attempt, name="leak.md", text="clean").json()["file"]["id"]
    assert again != gone


def test_a_page_of_the_library_stays_under_its_byte_cap(api):
    _, attempt = turn(api)
    for i in range(100):
        publish(api, attempt, name=f"report-{i:03}-" + "x" * 150 + ".md", text=f"# Report {i}")
    r = api.get("/api/v2/files?limit=100", headers=headers("ben-test"))
    assert len(r.content) <= file_library.LIST_BYTES + 4096, len(r.content)
    assert len(encode(r.json()["files"][0]).encode()) < 2048
