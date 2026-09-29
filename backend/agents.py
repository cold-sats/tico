"""External agents: a bot run by a harness Tico does not operate, such as a Hermes profile.

Such a bot is a full bot record (org tree, chat, tasks, routines) with no computer. Nothing
dispatches to it: a message addressed to it lands in its inbox and stays there until the agent
reads it through the hub's MCP endpoint or the `hub` CLI, with the one bot credential minted
here. Presence is a plain heartbeat the agent's box posts on a timer; that is all Tico knows
about whether the agent is alive, and the pages say exactly that (docs/hermes-agents.md).

One row per bot in `agents`: the credential's hash and the last heartbeat. Rotating the
credential replaces the hash; revoking keeps the row so the page can say who revoked it.
"""

import secrets

from .harnesses import is_external, resolve_harness
from .store import H, Problem, digest, encode

# The agent's timer posts every minute; three misses is offline. A Mac runner is offline after
# 60 s because its heartbeat is every 15 s and a lease depends on it; nothing here does.
PRESENCE_GAP = 180


def external_harness(c, bot):
    """The bot's harness id when it is external, else None."""
    row = c.execute("SELECT config_json FROM bot_config WHERE bot=?", (bot,)).fetchone()
    if not row:
        return None
    config = H._json(row["config_json"], {}) or {}
    return resolve_harness(config) if is_external(config) else None


def row(c, bot):
    return c.execute("SELECT * FROM agents WHERE bot=?", (bot,)).fetchone()


def presence(c, bot, harness=None, now=None):
    """What the pages show for an external bot, in the shape `views.machine` gives a runner:
    online/awake/ready are one fact here, whether the agent has reported in lately."""
    harness = harness or external_harness(c, bot)
    if not harness:
        return None
    if harness == "grokbot":
        from . import grokbot
        config = c.execute("SELECT config_json FROM bot_config WHERE bot=?", (bot,)).fetchone()
        return grokbot.presence(c, bot, H._json(config["config_json"], {}) or {}, now)
    now = now or H.now()
    record = row(c, bot)
    credential = bool(record and not record["revoked_at"])
    last_seen = record["last_seen"] if record else None
    online = bool(credential and last_seen and last_seen > H.shift(now, seconds=-PRESENCE_GAP))
    agent = {"harness": harness, "credential": credential, "last_seen": last_seen,
             "revoked_at": record["revoked_at"] if record else None,
             "version": (record["version"] if record else "") or "",
             "platform": (record["platform"] if record else "") or "",
             "model": (record["model"] if record else "") or "",
             "provider": (record["provider"] if record else "") or "",
             "profile": (record["profile"] if record else "") or "",
             "detail": (record["detail"] if record else "") or ""}
    return {"online": online, "awake": online, "ready": online, "machine": None, "agent": agent}


def issue_credential(c, who, bot):
    """Mint (or rotate) the one credential this bot's agent uses. The token is returned once
    and stored only as a hash; the previous token stops working at once."""
    harness = external_harness(c, bot)
    if not harness:
        raise Problem("harness", "Only a bot run by an external agent gets an agent credential; "
                      "this bot runs on a registered computer", 422)
    token = "tico-agent-" + secrets.token_urlsafe(32)
    now = H.now()
    c.execute("INSERT INTO agents(bot,harness,token_hash,created,created_by) VALUES(?,?,?,?,?) "
              "ON CONFLICT(bot) DO UPDATE SET harness=excluded.harness,token_hash=excluded.token_hash,"
              "created=excluded.created,created_by=excluded.created_by,revoked_at=NULL,revoked_by=NULL",
              (bot, harness, digest(token), now, who.actor))
    H.event(c, who.actor, "agent.credential_issued", bot, {"harness": harness})
    return {"bot": bot, "harness": harness, "token": token, "created": now}


def revoke_credential(c, who, bot):
    record = row(c, bot)
    if not record or record["revoked_at"]:
        raise Problem("not_found", "This bot has no active agent credential", 404)
    c.execute("UPDATE agents SET revoked_at=?,revoked_by=? WHERE bot=?", (H.now(), who.actor, bot))
    H.event(c, who.actor, "agent.credential_revoked", bot)
    return {"bot": bot, "revoked": True}


def heartbeat(c, who, body):
    """The agent reporting in. Identity is the credential; the body is only what the page shows."""
    if who.role != "bot" or not who.agent:
        raise Problem("identity", "An agent credential is required", 403)
    bot = H.actor_id(who.actor)
    now = H.now()
    c.execute("UPDATE agents SET last_seen=?,version=?,platform=?,model=?,provider=?,profile=?,detail=? "
              "WHERE bot=?", (now, body.version, body.platform, body.model, body.provider,
                              body.profile, body.detail, bot))
    inbox = H.inbox(c, who.actor, at=now)
    return {"server_time": now, "bot": bot, "presence_gap_s": PRESENCE_GAP,
            "waiting": {"messages": len(inbox["messages"]), "tasks": len(inbox["tasks"])}}


def listing(c, who, auth):
    """Every external agent this person may see, for Settings."""
    out = []
    for record in c.execute("SELECT a.*,b.display_name FROM agents a JOIN bots b ON b.slug=a.bot ORDER BY a.bot"):
        if not auth.bot_access(c, who, record["bot"])["read"]:
            continue
        config = c.execute("SELECT operator FROM bot_config WHERE bot=?", (record["bot"],)).fetchone()
        if who.role != "owner" and not (config and who.actor == "human:" + config["operator"]):
            continue
        value = {k: record[k] for k in ("bot", "display_name", "harness", "created", "created_by",
                                        "last_seen", "version", "platform", "model", "provider",
                                        "profile", "detail", "revoked_at", "revoked_by")}
        value["online"] = bool(not record["revoked_at"] and record["last_seen"]
                               and record["last_seen"] > H.shift(H.now(), seconds=-PRESENCE_GAP))
        out.append(value)
    return out


def setup_snippet(url, bot, token, harness="hermes"):
    """What the person pastes on the agent's box. Kept here so the API and the docs agree."""
    return {"url": url, "bot": bot, "harness": harness, "token": token,
            "mcp_servers": {"tico": {"url": url + "/api/v2/mcp",
                                     "headers": {"Authorization": "Bearer " + token}}},
            "heartbeat": {"method": "POST", "path": "/api/v2/agents/heartbeat",
                          "every_seconds": 60, "offline_after_seconds": PRESENCE_GAP}}


__all__ = ["PRESENCE_GAP", "external_harness", "presence", "issue_credential", "revoke_credential",
           "heartbeat", "listing", "setup_snippet", "encode"]
