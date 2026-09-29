"""Personal API tokens: a person's own bearer for scripts, without a browser sign-in.

Today only the browser sign-in makes a person; a bot administrator who wants to add a bot from
a script has no credential that is them. A personal token is that credential. It is stored as
a hash, shown once, expires, and is the person for every purpose but one: a token cannot make
or revoke tokens, so a leaked token cannot extend its own life (`Identity.via_token`).

Only the owner and bot administrators (`registry/hub-access.yaml`) may create one.
"""

import secrets

from .store import H, Problem, digest

PREFIX = "tico_pt_"
FIELDS = ("id", "label", "created", "last_used", "expires_at", "revoked_at")


def _person(who):
    """The token routes take a signed-in person and never a token."""
    if who.role not in ("owner", "human"):
        raise Problem("forbidden", "Personal tokens belong to people", 403)
    if who.via_token:
        raise Problem("forbidden", "Manage tokens from a signed-in browser", 403)


def listing(c, who):
    """This person's tokens, newest first; never the secret or its hash."""
    _person(who)
    rows = c.execute("SELECT " + ",".join(FIELDS) + " FROM human_tokens WHERE human=? "
                     "ORDER BY created DESC", (H.actor_id(who.actor),)).fetchall()
    return [dict(row) for row in rows]


def create(c, auth, who, body):
    """Mint a token for the caller and return its plaintext, the one time it is shown."""
    _person(who)
    if not auth.bot_admin(who):
        raise Problem("forbidden", "Personal tokens are for the owner and bot administrators", 403)
    token = PREFIX + secrets.token_urlsafe(30)          # 30 bytes: 40 url-safe characters
    now = H.now()
    expires_at = H.shift(now, days=body.expires_in_days)
    token_id = H.new_id()
    c.execute("INSERT INTO human_tokens(id,human,label,token_hash,created,created_by,expires_at) "
              "VALUES(?,?,?,?,?,?,?)",
              (token_id, H.actor_id(who.actor), body.label, digest(token), now, who.actor, expires_at))
    H.event(c, who.actor, "token.create", token_id, {"label": body.label, "expires_at": expires_at})
    return {"id": token_id, "token": token, "label": body.label, "expires_at": expires_at}


def revoke(c, who, token_id):
    """Stop a token at once. Your own; the owner may revoke anyone's."""
    _person(who)
    row = c.execute("SELECT id,human,label,revoked_at FROM human_tokens WHERE id=?", (token_id,)).fetchone()
    if not row or (who.role != "owner" and row["human"] != H.actor_id(who.actor)):
        raise Problem("not_found", "Token not found", 404)
    if row["revoked_at"]:
        raise Problem("revoked", "This token is already revoked", 409)
    c.execute("UPDATE human_tokens SET revoked_at=? WHERE id=?", (H.now(), token_id))
    H.event(c, who.actor, "token.revoke", token_id, {"label": row["label"], "human": row["human"]})
    return {"id": token_id, "revoked": True}
