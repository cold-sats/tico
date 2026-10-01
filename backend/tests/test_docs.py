"""Docs: internal docs (versions, locks, import, search) and linked docs (docs/docs.md)."""

import io
import zipfile


from backend import docs as D
from backend.tests.test_api import api, assign, claim, headers, ready, runner  # noqa: F401  (the api fixture)

ANA, BEN, CARA = "ana-test", "ben-test", "cara-test"      # owner, bot administrator, everyone else


def call(api, method, path, body=None, who=ANA, expected=200, **kw):
    r = api.request(method, "/api/v2/" + path, json=body, headers=headers(who), **kw)
    assert r.status_code == expected, (path, r.status_code, r.text)
    return r.json()


def make(api, title="Refund policy", body="Refund within 30 days.", who=ANA, **fields):
    return call(api, "POST", "docs", {"title": title, "body": body, **fields}, who)["doc"]


def edit(api, doc, who=ANA, expected=200, **fields):
    return call(api, "PATCH", "docs/" + doc["id"], {"version": doc["version"], **fields}, who, expected)


def test_create_edit_conflict_history_and_restore(api):
    doc = make(api)
    assert doc["path"] == "refund-policy.md" and doc["version"] == 1 and doc["updated_by_name"]
    assert make(api, "Refund policy", "again")["path"] == "refund-policy-2.md"          # a default path never collides
    call(api, "POST", "docs", {"title": "x", "path": "Refund-Policy.md"}, expected=409)  # a chosen one does
    second = edit(api, doc, body="Refund within 14 days.", note="Shorter window")["doc"]
    assert second["version"] == 2
    stale = edit(api, doc, who=BEN, body="mine", expected=409)              # ben still holds version 1
    assert stale["error"]["code"] == "version_conflict" and stale["error"]["version"] == 2
    assert call(api, "GET", "docs/" + doc["id"])["doc"]["body"] == "Refund within 14 days."
    versions = call(api, "GET", "docs/%s/versions" % doc["id"])["versions"]
    assert [v["version"] for v in versions] == [2, 1] and versions[0]["note"] == "Shorter window"
    assert versions[0]["current"] and versions[0]["actor_name"] and "body" not in versions[0]
    assert call(api, "GET", "docs/%s/versions/1" % doc["id"])["version"]["body"] == "Refund within 30 days."
    restored = call(api, "POST", "docs/%s/restore" % doc["id"], {"version": 1})["doc"]
    assert restored["version"] == 3 and restored["body"] == "Refund within 30 days."
    assert call(api, "GET", "docs/%s/versions" % doc["id"])["versions"][0]["note"] == "Restored version 1"
    call(api, "POST", "docs/%s/restore" % doc["id"], {"version": 9}, expected=404)
    moved = edit(api, restored, path="policies/refunds")["doc"]                     # .md is added
    assert moved["path"] == "policies/refunds.md"
    listed = call(api, "GET", "docs", params={"path_prefix": "policies/"})
    assert [d["id"] for d in listed["docs"]] == [doc["id"]] and listed["next_cursor"] is None
    assert edit(api, moved, archived=True)["doc"]["archived"] is True
    assert doc["id"] not in [d["id"] for d in call(api, "GET", "docs")["docs"]]
    archived = call(api, "GET", "docs", params={"archived": True, "path_prefix": "policies/"})
    assert [d["id"] for d in archived["docs"]] == [doc["id"]]
    assert call(api, "GET", "docs/search", params={"q": "refund"})["results"][0]["id"] != doc["id"]
    make(api, "Other", path="policies/refunds.md")                           # its path is taken while it is archived
    back = call(api, "POST", "docs/%s/restore" % doc["id"], {"version": 4})["doc"]
    assert back["archived"] is False and back["path"] == "policies/refunds-2.md"
    for bad in ("../x.md", "a/../b.md", "a/./b.md"):
        call(api, "POST", "docs", {"title": "x", "path": bad}, expected=422)


def test_a_locked_doc_belongs_to_owners_and_bot_administrators(api):
    doc = make(api, who=CARA)                                                # anyone may write
    call(api, "PATCH", "docs/" + doc["id"], {"version": 1, "locked": True}, CARA, 403)
    locked = edit(api, doc, who=BEN, locked=True)["doc"]                     # a bot administrator may lock
    assert locked["locked"] is True and locked["version"] == 1               # locking is not a content change
    assert edit(api, locked, who=CARA, expected=403, body="edit")["error"]["code"] == "locked"
    call(api, "POST", "docs/%s/restore" % doc["id"], {"version": 1}, CARA, 403)
    assert call(api, "GET", "docs/" + doc["id"], who=CARA)["doc"]["locked"] is True   # everyone still reads it
    assert edit(api, locked, who=ANA, body="owner edit")["doc"]["body"] == "owner edit"
    assert edit(api, call(api, "GET", "docs/" + doc["id"])["doc"], who=BEN, locked=False)["doc"]["locked"] is False


def fixture_docx():
    document = ('<?xml version="1.0"?><w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main" '
                'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><w:body>'
                '<w:p><w:pPr><w:pStyle w:val="Heading1"/></w:pPr><w:r><w:t>Onboarding guide</w:t></w:r></w:p>'
                '<w:p><w:r><w:t xml:space="preserve">Welcome to </w:t></w:r><w:r><w:rPr><w:b/></w:rPr><w:t>Acme</w:t></w:r>'
                '<w:hyperlink r:id="rId1"><w:r><w:t> handbook</w:t></w:r></w:hyperlink></w:p>'
                '<w:p><w:pPr><w:numPr><w:ilvl w:val="0"/><w:numId w:val="1"/></w:numPr></w:pPr><w:r><w:t>Get a laptop</w:t></w:r></w:p>'
                '<w:tbl><w:tr><w:tc><w:p><w:r><w:t>Plan</w:t></w:r></w:p></w:tc><w:tc><w:p><w:r><w:t>Price</w:t></w:r></w:p></w:tc></w:tr>'
                '<w:tr><w:tc><w:p><w:r><w:t>Starter</w:t></w:r></w:p></w:tc><w:tc><w:p><w:r><w:t>$35</w:t></w:r></w:p></w:tc></w:tr></w:tbl>'
                '</w:body></w:document>')
    rels = ('<?xml version="1.0"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" Type="x" Target="https://handbook.acme.example" TargetMode="External"/></Relationships>')
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w") as z:
        z.writestr("word/document.xml", document)
        z.writestr("word/_rels/document.xml.rels", rels)
    return out.getvalue()


def fixture_pdf(text):
    stream = ("BT /F1 12 Tf 20 100 Td (%s) Tj ET" % text).encode()
    objects = [b"<< /Type /Catalog /Pages 2 0 R >>", b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
               b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 400 144] /Contents 4 0 R "
               b"/Resources << /Font << /F1 5 0 R >> >> >>",
               b"<< /Length %d >>\nstream\n" % len(stream) + stream + b"\nendstream",
               b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"]
    out, offsets = b"%PDF-1.4\n", []
    for number, body in enumerate(objects, 1):
        offsets.append(len(out))
        out += b"%d 0 obj\n" % number + body + b"\nendobj\n"
    start = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objects) + 1)
    out += b"".join(b"%010d 00000 n \n" % o for o in offsets)
    return out + b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (len(objects) + 1, start)


def upload(api, name, data, who=ANA, expected=200, **fields):
    r = api.post("/api/v2/docs/import", files={"file": (name, data)}, data=fields, headers=headers(who))
    assert r.status_code == expected, r.text
    return r.json()


def test_search_ranks_internal_docs_and_lists_linked_docs_beside_them(api):
    make(api, "Pricing and plans", "Starter is $35 a month. Growth is $79.", path="sales/pricing.md")
    make(api, "Refund policy", "Refunds happen within 30 days. Pricing questions go to sales.")
    call(api, "POST", "linked-docs", {"url": "https://help.acme.example/pricing", "title": "Public pricing page",
                                       "description": "What customers see"})
    hits = call(api, "GET", "docs/search", params={"q": "pricing"})["results"]
    assert {h["type"] for h in hits} == {"internal", "linked"}
    assert hits[0]["type"] == "internal" and hits[0]["title"] == "Pricing and plans"      # title match outranks a body mention
    internal = next(h for h in hits if h["type"] == "internal")
    assert set(internal) == {"type", "id", "path", "title", "section", "anchor", "excerpt", "score"}
    linked = next(h for h in hits if h["type"] == "linked")
    assert set(linked) == {"type", "id", "title", "url", "kind", "description", "score"} and linked["kind"] == "website"
    assert [h["title"] for h in hits if h["type"] == "internal"] == ["Pricing and plans", "Refund policy"]
    assert call(api, "GET", "docs/search", params={"q": "pric"})["results"]                # a word being typed
    # A question in a sentence still finds what answers it (any meaningful word, best first).
    sentence = call(api, "GET", "docs/search", params={"q": "how do we handle a refund request"})["results"]
    assert sentence[0]["title"] == "Refund policy"
    assert call(api, "GET", "docs/search", params={"q": "zebra"})["results"] == []
    # The assistant's fast path sees the same docs.
    fast = call(api, "GET", "context/search", params={"q": "pricing", "source": "docs"})["results"]
    assert {r["kind"] for r in fast} == {"document", "linked_doc"}
    assert call(api, "GET", "context/document", params={"id": "sales/pricing.md"})["content"].startswith("Starter")
    # A pasted heading does not erase the document's searchable title.
    make(api, "Export guide", "# Steps\n\nChoose CSV.", path="notes/a.md")
    export = call(api, "GET", "docs/search", params={"q": "export"})["results"][0]
    assert export["title"] == "Export guide" and export["section"] == "Steps" and "CSV" in export["excerpt"]


def test_linked_docs_are_links_anyone_adds_and_their_adder_or_an_admin_edits(api):
    link = call(api, "POST", "linked-docs", {"url": "help.acme.example/faq", "description": "FAQ"}, CARA)["linked"]
    assert link["url"] == "https://help.acme.example/faq" and link["title"] == "help.acme.example/faq"
    dupe = call(api, "POST", "linked-docs", {"url": "https://help.acme.example/faq"}, BEN, 409)
    assert dupe["error"]["code"] == "already_linked"
    for bad in ("javascript:alert(1)", "https://user:pw@acme.example/", "ftp://acme.example", "not a url"):
        call(api, "POST", "linked-docs", {"url": bad}, expected=422)
    call(api, "PATCH", "linked-docs/" + link["id"], {"title": "Renamed"}, BEN)          # a bot administrator may
    other = call(api, "POST", "linked-docs", {"url": "https://github.com/acme/handbook"}, BEN)["linked"]
    call(api, "PATCH", "linked-docs/" + other["id"], {"title": "Mine now"}, CARA, 403)
    call(api, "PATCH", "linked-docs/" + link["id"], {"description": "Edited"}, CARA)
    call(api, "PATCH", "linked-docs/" + link["id"], {"url": "https://notion.so/faq"}, CARA)
    assert call(api, "GET", "linked-docs")["linked"][0]["kind"] == "notion"
    call(api, "PATCH", "linked-docs/" + other["id"], {"archived": True}, ANA)
    assert [row["id"] for row in call(api, "GET", "linked-docs")["linked"]] == [link["id"]]


def test_a_bots_docs_tools_read_write_and_survive_a_concurrent_edit(api):
    from backend.tests.test_mcp import call as tool
    machine = runner(api)
    assign(api, machine, "ops")
    ready(api, machine, ["ops"])
    call(api, "POST", "chat/ops", {"text": "go"}, BEN)
    token = claim(api, machine, "ops")["token"]
    err, made = tool(api, "hub_doc_write", {"path": "ops/runbook", "body": "# On-call runbook\n\nPage Ben."}, token=token)
    assert not err and made["doc"]["path"] == "ops/runbook.md" and made["doc"]["title"] == "On-call runbook"
    err, read = tool(api, "hub_doc_read", {"ref": "ops/runbook"}, token=token)
    assert not err and read["doc"]["body"].endswith("Page Ben.")
    # Someone edits between the bot's read and its write: the tool re-reads and retries once.
    real = api.app.state.docs.edit
    state = {"raced": False}

    def racing(request, doc_id, body):
        if not state["raced"]:
            state["raced"] = True
            edit(api, call(api, "GET", "docs/" + doc_id)["doc"], who=CARA, body="Cara changed it first")
        return real(request, doc_id, body)
    api.app.state.docs.edit = racing
    err, again = tool(api, "hub_doc_write", {"path": "ops/runbook.md", "body": "Bot rewrite", "note": "cleanup"}, token=token)
    api.app.state.docs.edit = real
    assert not err and again["doc"]["version"] == 3 and again["doc"]["body"] == "Bot rewrite"
    err, history = tool(api, "hub_doc_history", {"ref": made["doc"]["id"]}, token=token)
    assert [(v["actor"], v["note"]) for v in history["versions"]] == [("bot:ops", "cleanup"), ("human:cara", ""), ("bot:ops", "Created")]
    err, listing = tool(api, "hub_doc_list", {"prefix": "ops/"}, token=token)
    assert [d["path"] for d in listing["docs"]] == ["ops/runbook.md"]
    err, missing = tool(api, "hub_doc_read", {"ref": "nope"}, token=token)
    assert missing["refused"] == "docs"
    edit(api, call(api, "GET", "docs/" + made["doc"]["id"])["doc"], who=ANA, locked=True)
    err, refused = tool(api, "hub_doc_write", {"path": "ops/runbook.md", "body": "no"}, token=token)
    assert err and refused["error"] == "locked"


def test_named_map_docs_and_linked_topics_survive_whole_questions(api):
    glossary = make(api, "Team glossary", "Setup means preparing a bot. Computer means where it runs.",
                    path="_librarian/glossary.md")
    idx = make(api, "Docs index", "Source docs and their versions.", path="_librarian/index.md")
    for question, expected in [("According to the Team glossary, what does Setup mean?", glossary),
                               ("What is in _librarian/index.md?", idx)]:
        hits = call(api, "GET", "docs/search", params={"q": question, "collection": "all"})["results"]
        assert hits[0]["id"] == expected["id"]
    for collection in ("team", "company"):
        hits = call(api, "GET", "docs/search", params={"q": "glossary", "collection": collection})["results"]
        assert hits[0]["id"] == glossary["id"] and all(r["type"] != "manual" for r in hits)
    link = call(api, "POST", "linked-docs", {"url": "https://help.example.com/refunds", "title": "Refund policy",
                                           "description": "Refunds and cancellation terms"})["linked"]
    for q in ("refund policy", "Where can I read our refund policy?", "refunds cancellation"):
        hits = call(api, "GET", "docs/search", params={"q": q})["results"]
        assert any(r["id"] == link["id"] for r in hits)


def test_archive_removes_cached_index_source_and_preserves_history(api):
    source = make(api, "Refund policy", path="finance/refunds.md")
    body = "# Docs index\n- `finance/refunds.md` (v1): Refunds.\n- `finance/refunds.md.backup`: Separate doc.\n- `sales/pricing.md`: Prices.\n"
    idx = make(api, "Docs index", body, path="_librarian/index.md")
    edit(api, source, archived=True)
    fresh = call(api, "GET", "docs/" + idx["id"])["doc"]
    assert fresh["version"] == 2 and "`finance/refunds.md`" not in fresh["body"]
    assert "refunds.md.backup" in fresh["body"] and "sales/pricing.md" in fresh["body"]
    assert call(api, "GET", "docs/%s/versions/1" % idx["id"])["version"]["body"] == idx["body"]


def test_add_a_human_or_bot_question_prioritizes_the_procedure(api):
    for question in ("add a human or bot", "How do I add a human or bot to the team?"):
        hits = call(api, "GET", "docs/search", params={"q": question, "collection": "all", "limit": 3})["results"]
        assert hits[0]["id"] in ("manual:org-chart", "manual:creating-bots", "manual:people")
    hits = call(api, "GET", "docs/search", params={
        "q": "How do I add a human teammate and let them sign in when our Tico team is behind Cloudflare Access?",
        "collection": "all", "limit": 3})["results"]
    assert hits[0]["id"] == "manual:people"


def test_upgrade_repairs_generated_docs_once_and_queues_next_run_refresh(api):
    from backend.store import H
    source = make(api, "Refund policy", path="finance/refunds.md")
    old = make(api, "Old prices", path="sales/pricing.md")
    edit(api, old, archived=True)
    make(api, "Prices", path="sales/pricing.md")
    idx = make(api, "Document index", "- `finance/refunds.md` (v1): Refunds.\n- `sales/pricing.md`: Prices.\n",
               path="_librarian/index.md")
    gap = make(api, "Missing and outdated company information", "Sources I could not read: None",
               path="_librarian/missing.md")
    faq = make(api, "FAQ", "Internal company docs for coworkers. Read `knowledge/company.md`.", path="FAQ.md")
    custom = make(api, "Our terms", "Company policy.", path="_librarian/glossary.md")
    with api.app.state.store.transaction() as c:
        c.execute("DELETE FROM registry_metadata WHERE key='librarian_fix33'")
        c.execute("INSERT INTO bots(slug,display_name,runtime,model,effort,cwd,host,state,created) "
                  "VALUES('librarian','Librarian','fake','','','','keeper','active',?)", (H.now(),))
        c.execute("INSERT INTO bot_config(bot,config_json,operator) VALUES('librarian','{}','ana')")
        c.execute("UPDATE docs SET archived=1 WHERE id=?", (source["id"],))  # Older archive, stale cache.
        c.execute("UPDATE docs SET updated_by='bot:librarian' WHERE id=?", (faq["id"],))
    api.app.state.store.initialize(seed_market=False)
    fresh = call(api, "GET", "docs/" + idx["id"])["doc"]
    assert fresh["title"] == "Docs index" and "refunds.md`" not in fresh["body"]
    assert "sales/pricing.md" in fresh["body"]
    assert call(api, "GET", "docs/" + gap["id"])["doc"]["title"] == "Docs gaps"
    assert call(api, "GET", "docs/" + faq["id"])["doc"]["body"] == "Internal team docs for teammates. Read `knowledge/company.md`."
    assert call(api, "GET", "docs/" + custom["id"])["doc"]["body"] == custom["body"]
    assert call(api, "GET", "docs/%s/versions/1" % idx["id"])["version"]["body"] == idx["body"]
    api.app.state.store.initialize(seed_market=False)
    assert call(api, "GET", "docs/" + idx["id"])["doc"]["version"] == fresh["version"]
    with api.app.state.store.read() as c:
        tasks = c.execute("SELECT * FROM tasks WHERE owner='bot:librarian' AND title='Refresh the map'").fetchall()
        assert len(tasks) == 1 and tasks[0]["next_run"] == 1
        assert "unreadable" in tasks[0]["body"] and "archived" in tasks[0]["body"]


def test_wording_upgrade_repairs_previously_migrated_faq_once_and_preserves_human_docs(api):
    from backend import docs
    faq = make(api, "FAQ", "Change standing instructions. The runner pulls the update.", path="FAQ.md")
    human = make(api, "Our terms", "Our runner manages standing instructions.", path="_librarian/glossary.md")
    modified = make(api, "Edited by a human", "My standing instructions.", path="_librarian/edited.md")
    with api.app.state.store.transaction() as c:
        c.execute("UPDATE docs SET created_by='bot:librarian' WHERE id=?", (modified["id"],))
        c.execute("DELETE FROM registry_metadata WHERE key='librarian_wording35'")
        c.execute("UPDATE docs SET updated_by='keeper' WHERE id=?", (faq["id"],))
        c.execute("UPDATE doc_versions SET note='Updated generated Tico wording' WHERE doc_id=?", (faq["id"],))
        docs.refresh_generated_wording(c)
    fresh = call(api, "GET", "docs/" + faq["id"])["doc"]
    assert fresh["body"] == "Change Instructions. The Computer pulls the update."
    assert fresh["version"] == faq["version"] + 1
    assert call(api, "GET", "docs/" + modified["id"])["doc"]["body"] == modified["body"]
    assert call(api, "GET", "docs/" + human["id"])["doc"]["body"] == human["body"]
    assert call(api, "GET", "docs/%s/versions/1" % faq["id"])["version"]["body"] == faq["body"]
    with api.app.state.store.transaction() as c:
        docs.refresh_generated_wording(c)
    assert call(api, "GET", "docs/" + faq["id"])["doc"]["version"] == fresh["version"]
