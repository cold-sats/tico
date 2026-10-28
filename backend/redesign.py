"""The `redesign` team setting: one switch, off by default, that the redesign's code waits behind (new navigation,
Strategy tabs, Budget, task caps, automations). Off, every existing behavior stays as it is. The owner turns it on in
Settings > General; clients read it as `redesign` in GET /api/v2/config and nowhere else.
"""

import json

from .models import Contract
from .store import H, Problem

KEY = "redesign"                       # registry_metadata


class RedesignSetting(Contract):
    enabled: bool


def on(c):
    """Whether the team turned the redesign on. Code in shared paths returns early when this is false."""
    from .read_cache import metadata
    row = metadata(c, KEY)
    try:
        value = json.loads(row[0]) if row else {}
    except ValueError:
        return False
    return isinstance(value, dict) and value.get("enabled") is True


def set_on(c, enabled, actor):
    c.execute("INSERT INTO registry_metadata VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value_json=excluded.value_json",
              (KEY, json.dumps({"enabled": bool(enabled), "updated": H.now(), "updated_by": actor})))
    H.event(c, actor, "redesign.on" if enabled else "redesign.off", "")
    return {"enabled": bool(enabled)}


def install(app, store, auth, mutate):
    from fastapi import Request

    @app.get("/api/v2/settings/redesign")
    def redesign_view(request: Request):
        """Whether the redesign is on. Every signed-in person reads it; config carries the same value."""
        auth.domain(request.state.identity)
        with store.read() as c:
            return {"enabled": on(c)}

    @app.put("/api/v2/settings/redesign")
    def redesign_set(request: Request, body: RedesignSetting):
        """Turn the redesign on or off for the whole team. The owner only."""
        def permitted(c):
            who = request.state.identity
            auth.domain(who)
            if who.role != "owner":
                raise Problem("forbidden", "Only the owner turns the redesign on or off", 403)
        return mutate(request, body, lambda c: set_on(c, body.enabled, request.state.identity.actor), check=permitted)
