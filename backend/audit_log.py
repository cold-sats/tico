"""One audit trail for the redesign's settings: task caps, spend limits, groups and automations.

Every change writes one row with who made it, the object it changed (`<kind>:<id>`, e.g. `task_cap:<id>`,
`automation:<id>`) and the whole object before and after (null when created or deleted), in the same transaction as
the change, so a change without its row cannot exist. Rows are never edited or pruned.
"""
import json

from .store import H, Problem, encode

SCHEMA = """
CREATE TABLE IF NOT EXISTS audit_log(
 id TEXT PRIMARY KEY, at TEXT NOT NULL, actor TEXT NOT NULL, object TEXT NOT NULL,
 before_json TEXT, after_json TEXT, via TEXT);
CREATE INDEX IF NOT EXISTS audit_log_object ON audit_log(object, at);
CREATE INDEX IF NOT EXISTS audit_log_at ON audit_log(at);
"""
LIMIT = 50


def write(c, actor, obj, before, after, via=None):
    """Record one change. `via` names who acted for the actor (BotOps for a person, an approval id)."""
    row_id = H.new_id()
    c.execute("INSERT INTO audit_log VALUES(?,?,?,?,?,?,?)",
              (row_id, H.now(), actor, obj,
               None if before is None else encode(before), None if after is None else encode(after), via))
    return row_id


def _row(r):
    return {"id": r["id"], "at": r["at"], "actor": r["actor"], "object": r["object"], "via": r["via"],
            "before": None if r["before_json"] is None else json.loads(r["before_json"]),
            "after": None if r["after_json"] is None else json.loads(r["after_json"])}


def rows(c, obj=None, actor=None, limit=LIMIT, before=None):
    """Newest first, paged by `before` (a row's `at`)."""
    sql, args = "SELECT * FROM audit_log WHERE 1=1", []
    for column, value in (("object", obj), ("actor", actor)):
        if value:
            sql += f" AND {column}=?"
            args.append(value)
    if before:
        sql += " AND at<?"
        args.append(before)
    limit = max(1, min(int(limit or LIMIT), 200))
    found = [_row(r) for r in c.execute(sql + " ORDER BY at DESC LIMIT ?", (*args, limit + 1))]
    return {"rows": found[:limit], "next": found[limit - 1]["at"] if len(found) > limit else None}


def install(app, store, auth):
    from fastapi import Request

    @app.get("/api/v2/audit")
    def audit_view(request: Request, object: str | None = None, limit: int = LIMIT, before: str | None = None):
        """Who changed what. The owner reads every row; anyone else reads only their own changes."""
        from . import redesign
        who = request.state.identity
        auth.domain(who)
        with store.read() as c:
            if not redesign.on(c):
                raise Problem("not_found", "Not found", 404)
            mine = None if who.role == "owner" else who.actor
            return rows(c, obj=object, actor=mine, limit=limit, before=before)
