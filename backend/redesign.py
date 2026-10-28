"""The `redesign` team setting and the audit log the redesign's writes share.

Everything the redesign adds (automations, caps, budgets) is dormant while the setting is off: its routes answer 404
and its hooks return at once, so an install that never turns it on behaves exactly as before. The owner turns it on
with PUT /api/v2/settings/redesign {"enabled": true}.

`audit_log` keeps one row per change the redesign's routes make: who, what, and the value before and after (CONTRACT
§2 "every change writes an audit row").
"""
import json

from pydantic import Field

from .models import Contract
from .store import H, Problem

KEY = "redesign"

SCHEMA = (
    "CREATE TABLE IF NOT EXISTS audit_log(id INTEGER PRIMARY KEY AUTOINCREMENT, at TEXT NOT NULL, actor TEXT NOT NULL, "
    "kind TEXT NOT NULL, target TEXT NOT NULL, action TEXT NOT NULL, before TEXT, after TEXT)",
    "CREATE INDEX IF NOT EXISTS audit_log_target ON audit_log(kind, target, id)",
)


def ensure(c):
    for statement in SCHEMA:
        c.execute(statement)


def redesign_on(c):
    """Whether the team turned the redesign on. Read through the metadata cache, so a hook pays nothing."""
    from .repositories import metadata
    return metadata(c, KEY).get("enabled") is True


def require_on(c):
    """A redesign route while the setting is off: not found, as if it were not built."""
    if not redesign_on(c):
        raise Problem("not_found", "Not found", 404)


def audit(c, actor, kind, target, action, before, after):
    """One audit row: `before` and `after` are the value as JSON (None when there was none)."""
    dump = (lambda value: None if value is None else json.dumps(value, sort_keys=True, default=str))
    c.execute("INSERT INTO audit_log(at,actor,kind,target,action,before,after) VALUES(?,?,?,?,?,?,?)",
              (H.now(), actor, kind, str(target), action, dump(before), dump(after)))


class Setting(Contract):
    enabled: bool = Field()


def install(app, store, auth, mutate):
    from fastapi import Request

    @app.get("/api/v2/settings/redesign")
    def redesign_setting(request: Request):
        """Whether the redesign is on for the team."""
        auth.domain(request.state.identity)
        with store.read() as c:
            return {"enabled": redesign_on(c)}

    @app.put("/api/v2/settings/redesign")
    def redesign_set(request: Request, body: Setting):
        """Turn the redesign on or off. The top of the org only: it changes how the whole team works."""
        who = request.state.identity
        auth.domain(who)
        if who.role != "owner":
            raise Problem("forbidden", "Only the owner turns the redesign on or off", 403)

        def work(c):
            from .repositories import save_metadata
            before = redesign_on(c)
            save_metadata(c, KEY, {"enabled": body.enabled})
            audit(c, who.actor, "setting", KEY, "update", {"enabled": before}, {"enabled": body.enabled})
            return {"enabled": body.enabled}
        return mutate(request, body, work)
