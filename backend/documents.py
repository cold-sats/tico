"""Cloud document mirror. Source fetching and inference are local worker responsibilities."""

import json
import re
from urllib.parse import urlparse

from fastapi import Request

from . import models as M
from .store import H, Problem, digest, encode

# Which files in a mirrored repository count as documentation. `proposal_repos` in the
# environment's registry/company-docs.json maps each approved repository to one of these.
DOC_PATHS = {
    "markdown": lambda path: path.endswith((".md", ".mdx")),
    "product-docs": lambda path: path.startswith("docs/") and path.endswith(".md"),
    "website": lambda path: ((path.startswith("src/app/docs/") and "/_docs/" in path and path.endswith(".tsx"))
                             or (path.startswith("src/data/docs/") and path.endswith(".ts"))),
}


def proposal_repos(settings):
    """{"owner/name": kind} for the repositories whose documentation PRs may be mirrored."""
    try:
        catalog = json.loads((settings.registry_dir / "company-docs.json").read_text())
    except (OSError, ValueError):
        return {}
    repos = catalog.get("proposal_repos")
    if not isinstance(repos, dict):
        return {}
    return {str(repo): str(kind) for repo, kind in repos.items() if str(kind) in DOC_PATHS}


def visible(who, row):
    # Preserve the existing library policy: teammates see external documentation only.
    return who.role == "owner" or row["visibility"] == "external"


def document(c, auth, who, doc_id):
    auth.domain(who)
    row = c.execute("SELECT * FROM documents WHERE id=?", (doc_id,)).fetchone()
    if not row or not visible(who, row):
        raise Problem("not_found", "Document not found or unavailable to this account", 404)
    return json.loads(row["payload_json"])


def import_catalog(c, data, repos=()):
    """Explicit trusted snapshot import. A changed source never destroys its earlier version.

    `repos` is the approved {"owner/name": kind} map from `proposal_repos`."""
    documents = data.get("documents")
    if not isinstance(documents, list) or len(documents) > 5000:
        raise Problem("documents", "Publish a catalog with at most 5,000 documents", 422)
    now = H.now()
    linked_ids = {source["id"] for source in sources(c)}
    seen = set()
    for doc in documents:
        if not isinstance(doc, dict):
            raise Problem("documents", "Every catalog entry must be an object", 422)
        if doc.get("source_id") and doc["source_id"] not in linked_ids:
            continue
        key = doc.get("id")
        if not isinstance(key, str) or not re.fullmatch(r"[A-Za-z0-9._:-]{1,200}", key):
            raise Problem("documents", "Document IDs must be stable path-safe strings", 422)
        if not isinstance(doc.get("title"), str) or not isinstance(doc.get("content", ""), str):
            raise Problem("documents", "Every document needs text title and content fields", 422)
        if len(doc["title"]) > 500 or len(doc.get("content", "")) > 5_000_000:
            raise Problem("documents", "Document title or content exceeds the catalog limit", 422)
        if not isinstance(doc.get("category", ""), str) or doc.get("collection") not in (None, "docs", "notes", "proposals", "market"):
            raise Problem("documents", "Document category and collection fields are invalid", 422)
        if doc.get("url"):
            url = urlparse(str(doc["url"]))
            if url.scheme != "https" or not url.netloc:
                raise Problem("documents", "Document source links must use HTTPS", 422)
        if key in seen:
            raise Problem("documents", "Duplicate document identifier in source catalog", 422)
        seen.add(key)
        payload = encode(doc)
        hashed = digest(payload)
        visibility = "external" if doc.get("category", "").startswith("External /") else "owner"
        collection = doc.get("collection") or ("notes" if doc.get("category", "").startswith("Notes /") else "docs")
        c.execute("INSERT OR IGNORE INTO document_versions VALUES(?,?,?,?)", (key, hashed, payload, now))
        c.execute("INSERT INTO documents VALUES(?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET "
                  "visibility=excluded.visibility,collection=excluded.collection,payload_json=excluded.payload_json,"
                  "digest=excluded.digest,updated=excluded.updated", (key, visibility, collection, payload, hashed, now))
    # The latest catalog defines visibility; preserve removed pages only as restricted history.
    for row in c.execute("SELECT id, collection FROM documents").fetchall():
        if row[0] not in seen and row[1] != "market":
            c.execute("DELETE FROM documents WHERE id=?", (row[0],))
    raw_proposals = data.get("proposals", [])
    if not isinstance(raw_proposals, list) or len(raw_proposals) > 500:
        raise Problem("documents", "Publish at most 500 documentation proposals", 422)
    proposals = []
    for proposal in raw_proposals:
        if not isinstance(proposal, dict) or proposal.get("repo") not in repos:
            raise Problem("documents", "Documentation proposal repository is not approved", 422)
        repo, number = proposal["repo"], proposal.get("number")
        if not isinstance(number, int) or number < 1:
            raise Problem("documents", "Documentation proposal number is invalid", 422)
        expected_url = "https://github.com/" + repo + "/pull/" + str(number)
        if proposal.get("url") != expected_url:
            raise Problem("documents", "Documentation proposal link does not match its repository and number", 422)
        sha = str(proposal.get("head_sha") or "")
        if not re.fullmatch(r"[0-9a-f]{40}", sha):
            raise Problem("documents", "Documentation proposal revision is invalid", 422)
        files = proposal.get("files")
        if not isinstance(files, list) or not files or len(files) > 500:
            raise Problem("documents", "Documentation proposals need a bounded file list", 422)
        clean_files = []
        for file in files:
            path = file.get("path") if isinstance(file, dict) else None
            patch = file.get("patch", "") if isinstance(file, dict) else ""
            if (not isinstance(path, str) or not 1 <= len(path) <= 500 or "\\" in path
                    or path.startswith("/") or ".." in path.split("/")
                    or not isinstance(patch, str) or len(patch) > 200_000):
                raise Problem("documents", "Documentation proposal file metadata is invalid", 422)
            clean_files.append({"path": path, "status": str(file.get("status", ""))[:40],
                                "patch": patch, "url": str(file.get("url", ""))[:2000]})
        doc_path = DOC_PATHS[repos[repo]]
        eligible = (proposal.get("state") == "open" and not proposal.get("draft")
                    and proposal.get("head_repo") == repo
                    and proposal.get("total_files") == len(clean_files) and all(doc_path(file["path"]) for file in clean_files))
        proposals.append({"repo": repo, "number": number, "title": str(proposal.get("title", ""))[:500],
                          "url": expected_url, "body": str(proposal.get("body", ""))[:100_000],
                          "draft": bool(proposal.get("draft")), "state": str(proposal.get("state", ""))[:20],
                          "merged": bool(proposal.get("merged")), "head_sha": sha,
                          "head_repo": proposal.get("head_repo"), "total_files": proposal.get("total_files"),
                          "merge_eligible": eligible, "files": clean_files,
                          "documents": proposal.get("documents", []) if isinstance(proposal.get("documents", []), list) else []})
    errors = data.get("errors", [])
    if not isinstance(errors, list) or any(not isinstance(error, str) for error in errors):
        raise Problem("documents", "Catalog source errors must be text", 422)
    metadata = {"updated": data.get("updated"), "versions": data.get("versions", {}),
                "errors": errors[:500], "proposals": proposals}
    c.execute("INSERT INTO registry_metadata VALUES('documents',?) ON CONFLICT(key) DO UPDATE SET value_json=excluded.value_json",
              (encode(metadata),))
    return {"documents": len(seen), "imported": now}


def sources(c):
    row = c.execute("SELECT value_json FROM registry_metadata WHERE key='document_sources'").fetchone()
    return json.loads(row[0]) if row else []


def install_documents(app, store, auth, mutate):
    @app.get("/api/v2/document-sources")
    def list_sources(request: Request):
        who = request.state.identity
        if who.role != "owner" and who.actor != "bot:doc-updater":
            raise Problem("forbidden", "Documentation source management requires owner access", 403)
        with store.read() as c:
            return {"sources": sources(c)}

    @app.post("/api/v2/document-sources")
    def add_source(request: Request, body: M.DocumentSource):
        def work(c):
            if request.state.identity.role != "owner":
                raise Problem("forbidden", "Documentation source management requires owner access", 403)
            from clients.doc_sources import normalize
            try:
                source = normalize(body.model_dump())
            except ValueError as exc:
                raise Problem("source", str(exc), 422)
            rows = sources(c)
            if source not in rows:
                if len(rows) >= 50:
                    raise Problem("source", "At most 50 documentation sources may be linked", 422)
                rows.append(source)
            c.execute("INSERT INTO registry_metadata VALUES('document_sources',?) "
                      "ON CONFLICT(key) DO UPDATE SET value_json=excluded.value_json", (encode(rows),))
            H.event(c, request.state.identity.actor, "documents.source_linked", source["id"], source)
            return {"source": source}
        return mutate(request, body, work)

    @app.post("/api/v2/document-sources/{source_id}/unlink")
    def unlink_source(request: Request, source_id: str, body: M.Empty):
        def work(c):
            if request.state.identity.role != "owner":
                raise Problem("forbidden", "Documentation source management requires owner access", 403)
            rows = [row for row in sources(c) if row["id"] != source_id]
            c.execute("INSERT INTO registry_metadata VALUES('document_sources',?) "
                      "ON CONFLICT(key) DO UPDATE SET value_json=excluded.value_json", (encode(rows),))
            for row in c.execute("SELECT id,payload_json FROM documents").fetchall():
                if json.loads(row["payload_json"]).get("source_id") == source_id:
                    c.execute("DELETE FROM documents WHERE id=?", (row["id"],))
            return {"unlinked": True}
        return mutate(request, body, work)

    @app.get("/api/company-docs")
    def catalog(request: Request, collection: str = "docs"):
        who = request.state.identity
        auth.domain(who)
        if collection not in ("docs", "notes", "market"):
            raise Problem("collection", "Choose current docs, notes, or market", 422)
        with store.read() as c:
            rows = c.execute("SELECT * FROM documents ORDER BY id").fetchall()
            allowed = [r for r in rows if visible(who, r)]
            metadata = c.execute("SELECT value_json FROM registry_metadata WHERE key='documents'").fetchone()
            data = json.loads(metadata[0]) if metadata else {}
            refresh = c.execute("SELECT j.state,j.created FROM jobs j JOIN messages m ON m.id=j.message_id "
                                "WHERE j.bot='doc-updater' AND json_extract(m.refs_json,'$.docs_refresh')=1 "
                                "ORDER BY m.rowid DESC LIMIT 1").fetchone()
            return {"updated": data.get("updated"), "collection": collection,
                    "collection_counts": {kind: sum(r["collection"] == kind for r in allowed)
                                          for kind in ("docs", "notes", "market")},
                    "documents": [{k: v for k, v in json.loads(r["payload_json"]).items() if k != "content"}
                                  for r in allowed if r["collection"] == collection],
                    "proposals": data.get("proposals", []) if who.role == "owner" else [],
                    "errors": data.get("errors", []) if who.role == "owner" else [],
                    "sync": {"running": bool(refresh and refresh["state"] in ("queued", "leased", "running")),
                             "state": refresh["state"] if refresh else None, "error": None}}

    @app.get("/api/company-docs/search")
    def search(request: Request, q: str = "", collection: str = "docs"):
        data = catalog(request, collection)
        terms = re.findall(r"\w+", q.lower())[:40]
        found = []
        for row in data["documents"]:
            title = row.get("title", "").lower()
            body = str(row.get("search", ""))
            haystack = title + " " + body.lower()
            if all(term in haystack for term in terms):
                found.append({"doc": row, "score": sum(10 if term in title else 1 for term in terms), "excerpt": body[:250]})
        return {"results": sorted(found, key=lambda r: -r["score"])[:50], "mode": "keyword"}

    @app.get("/api/company-docs/{doc_id:path}")
    def detail(request: Request, doc_id: str):
        with store.read() as c:
            return document(c, auth, request.state.identity, doc_id)

    @app.get("/api/v2/documents/{doc_id:path}")
    def worker_document(request: Request, doc_id: str):
        return detail(request, doc_id)

    @app.post("/api/company-docs/refresh")
    def refresh(request: Request, body: M.Empty):
        who = request.state.identity
        def work(c):
            if who.role != "owner":
                raise Problem("forbidden", "Only the " + store.settings.app_name
                              + " owner can refresh company sources", 403)
            if not H.bot(c, "doc-updater"):
                raise Problem("not_found", "Doc Updater is not registered", 409)
            conv = H.open_conversation(c, who.actor, [who.actor, "bot:doc-updater"], kind="chat",
                                       subject="Refresh the company documentation mirror")
            text = ("Refresh the company documentation catalog from its approved sources on your local machine. "
                    "Run `python3 \"$HUB_DIR/clients/company_docs.py\" --publish-cloud`. "
                    "That command publishes through this attempt's scoped credential. Report source errors honestly; "
                    "do not merge or publish documentation changes as part of a refresh.")
            message = H.say(c, who.actor, "bot:doc-updater", text, conversation_id=conv["id"],
                            refs={"docs_refresh": True})
            return {"started": True, "queued": True, "conversation": conv, "message": message}
        return mutate(request, body, work)

    @app.post("/api/v2/documents/catalog")
    def publish(request: Request, body: M.DocumentCatalog):
        who = request.state.identity
        def work(c):
            if who.role != "bot" or who.actor != "bot:doc-updater":
                raise Problem("forbidden", "Only an active Doc Updater attempt can publish this catalog", 403)
            result = import_catalog(c, body.catalog, proposal_repos(store.settings))
            H.event(c, who.actor, "documents.published", "catalog", result)
            return result
        return mutate(request, body, work)
