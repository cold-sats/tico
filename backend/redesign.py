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


def dormant():
    """Decorator options for a redesign route: a dependency that answers 404 while the switch is off. FastAPI checks a
    body or query before the handler runs, so without it a malformed request would get a 422 that shows the route."""
    from fastapi import Depends, Request

    def switch_off_is_404(request: Request):
        with request.app.state.store.read() as c:
            if not on(c):
                raise Problem("not_found", "Not found", 404)
    return {"dependencies": [Depends(switch_off_is_404)]}


def set_on(c, enabled, actor):
    c.execute("INSERT INTO registry_metadata VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value_json=excluded.value_json",
              (KEY, json.dumps({"enabled": bool(enabled), "updated": H.now(), "updated_by": actor})))
    H.event(c, actor, "redesign.on" if enabled else "redesign.off", "")
    if enabled:   # the built-ins are there the moment it is on, not a tick later
        from .automations import ensure_builtins
        ensure_builtins(c)
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
            from . import redesign_migration
            if not body.enabled and redesign_migration.converted(c):
                # Off, the automations the convert made would stop and the rows they replaced are gone.
                raise Problem("conflict", "The install was converted to the redesign; restore the migration "
                                          "before turning it off", 409)
        def change(c):
            out = set_on(c, body.enabled, request.state.identity.actor)
            if body.enabled:   # the Automations Bot is made the moment the redesign is on, like the other built-ins
                app.state.onboarding.ensure_automations_bot(c)
            return out
        return mutate(request, body, change, check=permitted)
