"""Tico file hosting (Gateway): a company's files in a bucket Tico runs, served from its ticofiles.com address.

It is the company-bucket option (backend/company_storage.py) pointed at Tico's bucket and the company's own folder
in it, with the keys and the address handed over by Tico HQ instead of typed by the owner. Whether the company uses it
is HQ's word (the owner buys and stops it on the Gateway page, tico-services); the app asks with its gateway key at
start, hourly and when the owner presses Check now, and applies the answer without a restart.

The handoff, agreed with HQ on Dev 315/316: `POST <gateway>/file-hosting`, `Authorization: Bearer <gateway key>`,
body `{"files": <distinct files>, "bytes": <their total size>}` (HQ's estimate on the Gateway page). HQ answers
`{"state", "bucket", "prefix", "region", "access_key_id", "secret_access_key", "session_token"?, "address",
"price_gb_month"?}`, where `state` is:
- `off`: not bought. Nothing changes; a company that never had it has nothing saved.
- `on`: new files go to Tico's bucket. Files already stored keep opening where they are; Move existing files
  copies them over (`Move`).
- `credits_out`: Gateway credits ran out. Files in Tico's bucket keep opening; new files go to the company's own
  storage (its bucket, else the server's storage). If that storage can't take a file, the upload is refused with a
  plain reason (`PAUSED`).
- `stopped`: the owner stopped it. Like `credits_out` for reads and writes; the export and Move files back are
  offered. HQ keeps the files 30 days, emails the owner and deletes them (Dev 316); the app deletes nothing.
Keys for `on` are checked by writing and reading back a small object first (company_storage.check), and are sealed
with the credential vault like the company's own; no read returns them. `address` (https://<name>.ticofiles.com)
becomes the visual address when the server has none of its own (TICO_VISUAL_ORIGIN), so visuals show in full there:
every request on it still carries a signed, expiring token and is checked again (backend/visuals.py).

A 404 or `not_found` from HQ means it does not offer file hosting yet: nothing changes.
"""

import hashlib
import json
import logging
import re
import sqlite3
import tempfile
import threading
import zipfile

from fastapi import Request
from fastapi.responses import StreamingResponse
from pydantic import Field

from clients import gateway as G

from . import models as M
from .store import H, Problem

SCHEMA = """
CREATE TABLE IF NOT EXISTS tico_storage(
 id INTEGER PRIMARY KEY CHECK(id=1), state TEXT NOT NULL CHECK(state IN ('off','on','credits_out','stopped')),
 bucket TEXT NOT NULL DEFAULT '', prefix TEXT NOT NULL DEFAULT '', region TEXT NOT NULL DEFAULT '',
 access_key_id TEXT NOT NULL DEFAULT '', secret TEXT NOT NULL DEFAULT '', address TEXT NOT NULL DEFAULT '',
 price_gb_month REAL, changed TEXT, checked TEXT, error TEXT NOT NULL DEFAULT '');
CREATE TABLE IF NOT EXISTS storage_moves(
 id TEXT PRIMARY KEY, target TEXT NOT NULL, state TEXT NOT NULL CHECK(state IN ('running','done','failed','stopped')),
 started TEXT NOT NULL, started_by TEXT NOT NULL, finished TEXT,
 estimate_files INTEGER NOT NULL, estimate_bytes INTEGER NOT NULL,
 moved_files INTEGER NOT NULL DEFAULT 0, moved_bytes INTEGER NOT NULL DEFAULT 0, failed INTEGER NOT NULL DEFAULT 0,
 error TEXT NOT NULL DEFAULT '');
CREATE UNIQUE INDEX IF NOT EXISTS storage_moves_one_running ON storage_moves(state) WHERE state='running';
"""
PATH = "/file-hosting"
CONTEXT = "tico_storage:keys"
STATES = ("off", "on", "credits_out", "stopped")
ADDRESS = re.compile(r"^https://[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.ticofiles\.com$")
LABEL = "Tico file hosting"
PAUSED = ("Gateway credits have run out, so new files go to the company's own storage, and it can't take this one "
          "right now ({reason}). Add Gateway credits, or fix the company's storage in Settings › General, and try again.")
LOG = logging.getLogger("tico.storage")
# Each live server's file store, for the hourly check (backend/scheduler.py), which has only the store.
_live = {}
_lock = threading.Lock()


class Move(M.Contract):
    """Copy every file not yet in the place new files go to. `expect_bytes` is the estimate the owner was shown."""
    expect_bytes: int = Field(ge=0)


# ---------------------------------------------------------------------------------------------- saved state
def row(c):
    try:
        found = c.execute("SELECT * FROM tico_storage WHERE id=1").fetchone()
    except sqlite3.OperationalError:          # a database from before file hosting, read by a backup
        return None
    return dict(found) if found else None


def _keys(c, vault, saved):
    """(access key id, secret, session token) from the sealed record."""
    secret, token = json.loads(vault.cipher.unseal(c, CONTEXT, saved["secret"]))
    return (saved["access_key_id"], secret, token)


def place(c, vault):
    """(the Tico place {bucket, prefix, region, keys} or None, its state). The place is None until HQ has handed over
    a bucket; it stays once handed over, whatever the state, so files written there keep opening."""
    saved = row(c)
    if not saved or not saved["bucket"] or not saved["secret"]:
        return None, saved["state"] if saved else "off"
    return ({"bucket": saved["bucket"], "prefix": saved["prefix"], "region": saved["region"],
             "keys": _keys(c, vault, saved)}, saved["state"])


def active_location(c):
    """{bucket, prefix, region} of Tico's place while new files go there, or None: for Health."""
    saved = row(c)
    if not saved or saved["state"] != "on" or not saved["bucket"]:
        return None
    return {"bucket": saved["bucket"], "prefix": saved["prefix"], "region": saved["region"]}


def arrange(active, earlier, hosting):
    """Where files are written and read, given the company's own places (company_storage.places) and Tico's.
    (write place or None for the server's own storage, earlier places newest first, copy this disk's files, paused)."""
    tico, state = hosting
    if tico and state == "on":
        # The company's own bucket becomes a place files are still read from; this disk's files stay where they are
        # until the owner moves them (each one moved is billed storage).
        return tico, ([active] if active else []) + list(earlier), False, False
    if tico:
        # Credits out or stopped: the company's own storage takes new files; Tico's still serves what it holds.
        return active, [tico] + list(earlier), True, state == "credits_out"
    return active, list(earlier), True, False


def totals(c):
    """{files, bytes}: every distinct file Tico stores, every version, picture still and recording included."""
    usage = c.execute("SELECT COUNT(*) AS files, COALESCE(SUM(size),0) AS bytes FROM "
                      "(SELECT digest, MAX(size) AS size FROM blobs GROUP BY digest)").fetchone()
    return {"files": usage["files"], "bytes": usage["bytes"]}


def visual_address(settings, saved):
    """HQ's address is the visual address while Tico file hosting is in use and the server has none of its own
    (TICO_VISUAL_ORIGIN, or Dev 314's hosted address), which always wins."""
    from .visuals import hostname
    ours = getattr(settings, "_tico_visual_origin", "")
    if settings.visual_origin and settings.visual_origin != ours:
        return
    address = saved["address"] if saved and saved["state"] != "off" else ""
    if not ADDRESS.match(address or "") or hostname(address) == hostname(settings.public_url):
        address = ""
    if address or ours:
        settings.visual_origin = settings._tico_visual_origin = address


def view(c, settings):
    saved = row(c)
    if not saved:
        return {"state": "off", "label": LABEL}
    location = saved["bucket"] + ("/" + saved["prefix"] if saved["prefix"] else "")
    out = {"state": saved["state"], "label": LABEL, "address": saved["address"], "location": location,
           "checked": saved["checked"], "changed": saved["changed"], "error": saved["error"]}
    if saved["price_gb_month"] is not None:
        out["price_gb_month"] = saved["price_gb_month"]
    return out


# ---------------------------------------------------------------------------------------------- HQ's word
def parse(answer):
    """The checked fields of HQ's answer, or ValueError naming the field. Never echoes a secret."""
    state = answer.get("state")
    if state not in STATES:
        raise ValueError("state")
    out = {"state": state, "address": "", "price_gb_month": None}
    address = str(answer.get("address") or "").strip().rstrip("/").lower()
    if address and not ADDRESS.match(address):
        raise ValueError("address")
    out["address"] = address
    price = answer.get("price_gb_month")
    if price is not None:
        if not isinstance(price, (int, float)) or isinstance(price, bool) or not 0 <= price < 100:
            raise ValueError("price_gb_month")
        out["price_gb_month"] = float(price)
    if not answer.get("bucket"):
        if state == "on":
            raise ValueError("bucket")
        return out
    from .company_storage import ACCESS_KEY, BUCKET, PREFIX, REGION
    bucket = str(answer["bucket"]).strip()
    region, prefix = str(answer.get("region") or "").strip().lower(), str(answer.get("prefix") or "").strip().strip("/")
    key, secret = str(answer.get("access_key_id") or ""), str(answer.get("secret_access_key") or "")
    token = str(answer.get("session_token") or "")
    if not BUCKET.match(bucket) or ".." in bucket:
        raise ValueError("bucket")
    if not REGION.match(region):
        raise ValueError("region")
    # A company's own folder: Tico's bucket is shared, so a place at its root would read other companies' files.
    if not prefix or not PREFIX.match(prefix) or any(part in ("", ".", "..") for part in prefix.split("/")):
        raise ValueError("prefix")
    if not ACCESS_KEY.match(key) or not secret or len(secret) > 128 or len(token) > 4096:
        raise ValueError("access_key_id")
    out.update(bucket=bucket, region=region, prefix=prefix, keys=(key, secret, token))
    return out


def ask(key, base, body, opener=None):
    """(status, answer, code) from HQ's file-hosting endpoint."""
    return G._post(G.safe_base(base) + PATH, body, {"Authorization": "Bearer " + key}, G.TIMEOUT, opener)


def sync(store, vault, blobs, settings=None, opener=None):
    """Ask HQ and apply its answer. Returns the view, or None when this server has no gateway key."""
    from . import gateway_connection
    settings = settings or store.settings
    with store.read() as c:
        key, base, usage = gateway_connection.key(c, vault, settings), gateway_connection.url(c, settings), totals(c)
    if not key or settings.rehearsal or settings.demo:
        return None
    try:
        status, answer, code = ask(key, base, usage, opener)
    except ValueError:
        status, answer, code = 0, {}, "bad_url"
    if status == 404 or code == G.NOT_FOUND:
        with store.read() as c:
            return view(c, settings)
    error = "" if status == 200 else f"{LABEL}: Tico HQ didn't answer ({code or status}); files stay where they are"
    parsed = None
    if not error:
        try:
            parsed = parse(answer)
        except ValueError as exc:
            error = f"{LABEL}: Tico HQ's answer has an unusable {exc}; files stay where they are"
    same = True
    if parsed and parsed.get("keys"):
        with store.read() as c:
            saved = row(c)
            same = bool(saved and saved["secret"] and saved["bucket"] == parsed["bucket"]
                        and saved["prefix"] == parsed["prefix"] and saved["region"] == parsed["region"]
                        and _keys(c, vault, saved) == parsed["keys"])
        if parsed["state"] == "on" and not same:
            from .company_storage import check
            try:
                check(settings, parsed["bucket"], parsed["prefix"], parsed["region"], parsed["keys"])
            except Problem as exc:
                error, parsed = f"{LABEL}: {exc.detail}; new files stay where they go now", None
    now, moved = H.now(), False
    with store.transaction() as c:
        saved = row(c)
        if parsed is None:
            if saved:
                c.execute("UPDATE tico_storage SET checked=?, error=? WHERE id=1", (now, error))
            elif error:
                LOG.warning("%s", error)
        elif parsed["state"] == "off" and not saved:
            pass
        else:
            fields = {"state": parsed["state"], "address": parsed["address"], "price_gb_month": parsed["price_gb_month"],
                      "checked": now, "error": ""}
            if parsed.get("keys"):
                fields.update(bucket=parsed["bucket"], prefix=parsed["prefix"], region=parsed["region"],
                              access_key_id=parsed["keys"][0],
                              secret=vault.cipher.seal(c, CONTEXT, json.dumps(list(parsed["keys"][1:]))))
            if not saved:
                c.execute("INSERT INTO tico_storage(id,state) VALUES(1,'off')")
            # Where files go changes only with the state or the place: an hourly answer saying the same again leaves
            # the file store alone (reapplying it would make uploads wait for a fresh write check).
            moved = not saved or saved["state"] != parsed["state"] or not same
            if moved:
                fields["changed"] = now
                H.event(c, "system:gateway", "storage.tico", parsed["state"],
                        {"from": saved["state"] if saved else "off", "address": parsed["address"]})
            c.execute("UPDATE tico_storage SET " + ",".join(k + "=?" for k in fields) + " WHERE id=1", tuple(fields.values()))
        saved = row(c)
    if moved:
        from . import company_storage
        company_storage.apply(store, vault, blobs, checked=bool(parsed.get("keys") and parsed["state"] == "on"))
    else:
        visual_address(settings, saved)
    with store.read() as c:
        return view(c, settings)


def sync_later(store):
    """`sync` on a thread, for the hourly check. Nothing when this store has no live file store."""
    with _lock:
        live = _live.get(id(store))
    if not live or live[0] is not store:
        return None
    _, vault, blobs = live
    def run():
        try:
            sync(store, vault, blobs)
        except Exception:
            LOG.exception("Tico file hosting check failed")
    thread = threading.Thread(target=run, name="tico-file-hosting", daemon=True)
    thread.start()
    return thread


# ---------------------------------------------------------------------------------------------- move
def _target(blobs):
    """(label of the place new files go to, its bucket location or '' for this computer's disk)."""
    return (blobs.location, blobs.location) if blobs.bucket else ("this server's disk", "")


def pending(c, blobs):
    """[(digest, size, content type)] of every file not yet verified in the place new files go to."""
    _, location = _target(blobs)
    rows = c.execute("SELECT digest, MAX(size) AS size, MAX(content_type) AS content_type FROM blobs GROUP BY digest "
                     "ORDER BY digest").fetchall()
    if location:
        known = {r[0] for r in c.execute("SELECT digest FROM blob_locations WHERE bucket=?", (location,))}
        return [(r["digest"], r["size"], r["content_type"]) for r in rows if r["digest"] not in known]
    return [(r["digest"], r["size"], r["content_type"]) for r in rows
            if not (blobs.directory / blobs.key(r["digest"])).is_file()]


def estimate(c, blobs, price=None):
    items = pending(c, blobs)
    label, _ = _target(blobs)
    size = sum(item[1] for item in items)
    out = {"to": label, "files": len(items), "bytes": size, "gb": round(size / 1e9, 3)}
    if price is not None:
        out["monthly"] = round(size / 1e9 * price, 2)
    return out


def _move_view(found):
    if not found:
        return None
    out = {k: found[k] for k in ("id", "target", "state", "started", "finished", "estimate_files", "estimate_bytes",
                                 "moved_files", "moved_bytes", "failed", "error")}
    out["matches"] = found["state"] == "done" and found["moved_bytes"] == found["estimate_bytes"] and not found["failed"]
    return out


def latest_move(c):
    return _move_view(c.execute("SELECT * FROM storage_moves ORDER BY started DESC LIMIT 1").fetchone())


def interrupted(store):
    """At start: a move that was running when the server stopped is stopped (the next one picks up where it left)."""
    with store.transaction() as c:
        c.execute("UPDATE storage_moves SET state='stopped', finished=?, error=? WHERE state='running'",
                  (H.now(), "The server restarted during the move; start it again to finish"))


def start_move(store, blobs, who, expect_bytes, stop=None, wait=False):
    with store.transaction() as c:
        if c.execute("SELECT 1 FROM storage_moves WHERE state='running'").fetchone():
            raise Problem("move_running", "Files are already being moved", 409)
        items = pending(c, blobs)
        total = sum(item[1] for item in items)
        if total != expect_bytes:
            raise Problem("estimate_changed", "The files to move changed since the estimate; check the new one", 409,
                          extra={"estimate": estimate(c, blobs)})
        move_id = H.new_id()
        label, location = _target(blobs)
        c.execute("INSERT INTO storage_moves(id,target,state,started,started_by,estimate_files,estimate_bytes) "
                  "VALUES(?,?,'running',?,?,?,?)", (move_id, label, H.now(), who.actor, len(items), total))
        H.event(c, who.actor, "storage.move", label, {"files": len(items), "bytes": total})
    thread = threading.Thread(target=_move, args=(store, blobs, move_id, items, location, stop or threading.Event()),
                              name="tico-storage-move", daemon=True)
    thread.start()
    if wait:
        thread.join()
    return move_id


def _move(store, blobs, move_id, items, location, stop):
    """Copy each file from where it is now into the place new files go to, verify the copy by reading it back whole
    and hashing it, and only then record it there. Nothing is ever deleted: the source stays where it was."""
    generation, moved, size, failed, error = blobs._generation, 0, 0, 0, ""
    for digest, length, content_type in items:
        if stop.is_set() or generation != blobs._generation:
            break
        try:
            copy_one(blobs, digest, length, content_type or "application/octet-stream", location)
            if location:
                with store.transaction() as c:
                    c.execute("INSERT OR REPLACE INTO blob_locations VALUES(?,?,?)", (digest, location, H.now()))
            moved, size = moved + 1, size + length
        except Exception as exc:
            failed += 1
            error = exc.detail if isinstance(exc, Problem) else "A file could not be copied: " + type(exc).__name__
        with store.transaction() as c:
            c.execute("UPDATE storage_moves SET moved_files=?, moved_bytes=?, failed=?, error=? WHERE id=?",
                      (moved, size, failed, error, move_id))
    state = ("stopped" if stop.is_set() or generation != blobs._generation else "failed" if failed else "done")
    if state == "stopped" and not error:
        error = "Where new files go changed during the move; start it again to finish"
    with store.transaction() as c:
        c.execute("UPDATE storage_moves SET state=?, finished=?, error=? WHERE id=?", (state, H.now(), error, move_id))
        H.event(c, "system:storage", "storage.moved", move_id, {"state": state, "files": moved, "bytes": size,
                                                               "failed": failed})


def copy_one(blobs, digest, length, content_type, location):
    key = blobs.key(digest)
    with tempfile.TemporaryFile(dir=_staging(blobs)) as staged:
        source = blobs._open_elsewhere(key, digest, 0, {})
        sha, got = hashlib.sha256(), 0
        try:
            while chunk := source.read(1024 * 1024):
                sha.update(chunk)
                got += len(chunk)
                staged.write(chunk)
        finally:
            source.close()
        if sha.hexdigest() != digest or got != length:
            raise Problem("blob_integrity", "A stored file failed its integrity check where it is now; it was not moved",
                          503)
        staged.seek(0)
        if location:
            blobs._upload(staged, digest, length, content_type)
            blobs.verify_s3(digest)
        else:
            blobs._local(staged, digest)
            with (blobs.directory / key).open("rb") as written:
                if hashlib.file_digest(written, "sha256").hexdigest() != digest:
                    raise Problem("blob_integrity", "A moved file failed its integrity check", 503)


def _staging(blobs):
    blobs.directory.mkdir(parents=True, mode=0o700, exist_ok=True)
    return blobs.directory


# ---------------------------------------------------------------------------------------------- export
class _Sink:
    """What zipfile writes to: chunks taken by the response as they are made, never the whole archive."""
    def __init__(self):
        self.parts = []

    def write(self, data):
        self.parts.append(bytes(data))
        return len(data)

    def flush(self):
        pass

    def take(self):
        out, self.parts = b"".join(self.parts), []
        return out


def _clean(name):
    name = re.sub(r"[\x00-\x1f\x7f/\\]", "_", str(name or "")).strip(". ") or "file"
    return name[:150]


def export_entries(c, who, auth, files):
    """[(path in the archive, digest)] of every file version and attachment `who` may open, and how many were left
    out because they are private to someone else."""
    from .media import blob_for
    entries, seen, left_out = [], set(), 0
    cache = {}
    for found in c.execute("SELECT * FROM bot_files WHERE locator='tico_blob' ORDER BY first_activity_at, id"):
        versions = c.execute("SELECT version, blob_id, digest, name FROM bot_file_versions WHERE file_id=? "
                             "ORDER BY version", (found["id"],)).fetchall()
        if not files.visible(c, who, found, cache):
            left_out += len(versions)
            seen.update(v["blob_id"] for v in versions)
            continue
        for v in versions:
            seen.add(v["blob_id"])
            entries.append((f"files/{found['id']}/v{v['version']}/{_clean(v['name'])}", v["digest"]))
    # A video's poster and a page's preview are made from a version, not files of their own.
    for still in c.execute("SELECT poster_blob_id, thumb_blob_id FROM bot_file_versions UNION ALL "
                           "SELECT poster_blob_id, thumb_blob_id FROM blob_media"):
        seen.update(still)
    for blob in c.execute("SELECT id, digest, name FROM blobs ORDER BY created, id"):
        if blob["id"] in seen:
            continue
        try:
            blob_for(c, auth, who, blob["id"])
        except Problem:
            left_out += 1
            continue
        entries.append((f"attachments/{blob['id']}/{_clean(blob['name'])}", blob["digest"]))
    return entries, left_out


def export(store, blobs, auth, files, who):
    with store.read() as c:
        entries, left_out = export_entries(c, who, auth, files)

    def chunks():
        sink = _Sink()
        with zipfile.ZipFile(sink, "w", zipfile.ZIP_STORED, allowZip64=True) as archive:
            for path, digest in entries:
                with archive.open(path, "w", force_zip64=True) as out:
                    for chunk in blobs.open_range(digest):
                        out.write(chunk)
                        if sink.parts:
                            yield sink.take()
                yield sink.take()
            note = {"files": len(entries), "left_out": left_out,
                    "note": "Files private to someone else are left out; Move files back keeps every file."}
            archive.writestr("manifest.json", json.dumps(note, indent=1))
        yield sink.take()

    headers = {"Content-Disposition": "attachment; filename=\"tico-files.zip\"", "Cache-Control": "private, no-store",
               "X-Content-Type-Options": "nosniff", "X-Tico-Left-Out": str(left_out)}
    return StreamingResponse(chunks(), media_type="application/zip", headers=headers)


# ---------------------------------------------------------------------------------------------- routes
def startup(store, vault, blobs):
    interrupted(store)
    with store.read() as c:
        saved = row(c)
    visual_address(store.settings, saved)


def install(app, store, auth):
    from .company_storage import apply, require_owner
    vault, blobs, settings = app.state.vault, app.state.blobs, store.settings
    with _lock:
        _live[id(store)] = (store, vault, blobs)

    def owner(request):
        who = request.state.identity
        auth.domain(who)
        require_owner(who)
        return who

    @app.post("/api/v2/system/storage/tico/check")
    def storage_tico_check(request: Request):
        """Ask Tico HQ now whether this company uses Tico file hosting, and apply its answer."""
        owner(request)
        result = sync(store, vault, blobs)
        if result is None:
            raise Problem("no_gateway", "Connect the Tico AI Gateway first (Settings › Computers)", 409)
        return result

    @app.get("/api/v2/system/storage/move")
    def storage_move_read(request: Request):
        """What Move existing files would copy into the place new files go to, and the latest move."""
        owner(request)
        with store.read() as c:
            saved = row(c)
            price = saved["price_gb_month"] if saved and saved["state"] == "on" else None
            return {"estimate": estimate(c, blobs, price), "move": latest_move(c)}

    @app.post("/api/v2/system/storage/move")
    def storage_move(request: Request, body: Move):
        """Copy every file and every version into the place new files go to; each copy is read back and checked
        before it counts, and nothing is deleted where it was."""
        who = owner(request)
        if settings.rehearsal or settings.demo:
            raise Problem("rehearsal", "Files can't be moved in a rehearsal or the demo", 409)
        start_move(store, blobs, who, body.expect_bytes)
        with store.read() as c:
            return {"move": latest_move(c)}

    @app.get("/api/v2/system/storage/export")
    def storage_export(request: Request):
        """A zip of every file and version the owner may open, streamed (files private to others are left out)."""
        who = owner(request)
        return export(store, blobs, auth, app.state.files, who)
