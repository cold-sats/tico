"""Shared bots: one definition and one repository, a copy for each human who adds it.

A bot that starts every task fresh from its repository (a reviewer, an architect) is everything
its AGENT.md, knowledge and memory say. Marking one `shared` lets anyone who may read it add their
own copy: a bot `<bot>-<human>` the human operates, on their own computer and model subscription,
pointed at the same repository. Every copy reads and writes that one repository, so a lesson any
copy learns is every copy's next turn.

A copy has nothing of its own to drift. Model, effort, harness, session and fallback are read
from the original whenever a turn is claimed (`follow`), a copy's own definition cannot be
changed (`refuse_copy`), and routines stay with the original so a weekly learning run happens
once. A task anyone files on a shared bot goes to their own copy when they have one
(`hubdb.shared_copy_for`), so a human's work runs on their own subscription.
"""

import json
import re
from types import SimpleNamespace

from .store import H, Problem, encode

# What a copy takes from its original at every claim. Everything else (its name, its human,
# its computer) is the copy's own.
FOLLOWED = ("model", "runtime", "harness", "reasoning_effort", "session", "fallback",
            "max_run_minutes", "bot_contact")


def _json(value):
    try:
        return json.loads(value) if isinstance(value, str) else (value or {})
    except (TypeError, ValueError):
        return {}


def declared(c, bot):
    row = c.execute("SELECT config_json FROM bot_config WHERE bot=?", (bot,)).fetchone()
    return _json(row[0]) if row else {}


def source_of(config):
    """The shared bot this one is a copy of, or ""."""
    return str((config or {}).get("shared_from") or "")


def follow(c, bot, config):
    """A copy's config with the original's behaviour in it; any other bot's config as it is."""
    source = source_of(config)
    if not source:
        return config
    original = declared(c, source)
    if not original:
        return config
    merged = dict(config)
    for key in FOLLOWED:
        if key in original:
            merged[key] = original[key]
        else:
            merged.pop(key, None)
    return merged


def refuse_copy(c, bot):
    """A copy's behaviour is its original's; changing it means changing the original."""
    source = source_of(declared(c, bot))
    if source:
        raise Problem("shared_copy", f"{bot} is a copy of the shared bot {source} and follows it; "
                      f"change {source} instead", 409)


def copy_slug(source, person):
    slug = re.sub(r"[^a-z0-9]+", "-", f"{source}-{person}".lower()).strip("-")
    if len(slug) > 80:
        raise Problem("slug", "That bot and human make a name longer than 80 characters", 422)
    return slug


def add_copy(c, who, source, runner_id, settings_admin, execution):
    """The caller's own copy of `source`, created if they have none, on `runner_id` if given.
    The caller must be allowed to read `source` (the route checks) and to add bots of their own."""
    if who.role not in ("human", "owner"):
        raise Problem("forbidden", "Only a human may add a shared bot", 403)
    person = H.actor_id(who.actor)
    if not H.human(c, person):
        raise Problem("not_found", "You are not on the roster", 404)
    original_row = c.execute("SELECT * FROM bot_config WHERE bot=?", (source,)).fetchone()
    original_bot = H.bot(c, source)
    if not original_row or not original_bot or original_bot["state"] == "archived":
        raise Problem("not_found", "Bot not found", 404)
    original = _json(original_row["config_json"])
    if source_of(original):
        raise Problem("shared_copy", f"{source} is itself a copy; add {source_of(original)}", 422)
    if not original.get("shared"):
        raise Problem("not_shared", f"{source} is not a shared bot", 409)
    if original_row["operator"] == person:
        raise Problem("own_bot", f"{source} is already yours", 409)
    runner = None
    if runner_id:
        runner = c.execute("SELECT * FROM runners WHERE id=? AND revoked_at IS NULL", (runner_id,)).fetchone()
        if not runner:
            raise Problem("not_found", "Computer is not registered", 404)
        if runner["operator"] != person:
            raise Problem("operator", "That computer belongs to someone else", 403)

    slug = copy_slug(source, person)
    existing = c.execute("SELECT * FROM bot_config WHERE bot=?", (slug,)).fetchone()
    if existing and (existing["operator"] != person or source_of(_json(existing["config_json"])) != source):
        raise Problem("duplicate", f"The name {slug} is taken by another bot", 409)
    created = not existing
    if created:
        # A copy is a bot of the caller's own: the company's rules for adding one apply.
        settings_admin._creator(c, who)
        # The same fallback the bot's own definition uses when no repository is recorded.
        repo = original_row["repo"] or ("emp-" + source)
        status = "active" if runner else "planned"
        config = {"name": slug, "display_name": original_bot["display_name"],
                  "description": original_row["description"] or "", "reports_to": "human:" + person,
                  "status": status, "repo": repo, "host": "keeper", "tasks": "hub", "thread_mode": "personal",
                  "shared_from": source, "model_managed_by": "cloud"}
        config.update({key: original[key] for key in FOLLOWED if key in original})
        team = settings_admin._team(c, slug, config)
        now = H.now()
        c.execute("INSERT INTO bots(slug,display_name,runtime,model,effort,cwd,host,state,created) "
                  "VALUES(?,?,?,?,?,'','keeper',?,?)",
                  (slug, original_bot["display_name"], original_bot["runtime"], original_bot["model"],
                   original_bot["effort"], status, now))
        c.execute(
            "INSERT INTO bot_config(bot,config_json,team,operator,owner_ids_json,description,reports_to,"
            "repo,thread_mode,definition_updated,definition_updated_by,bot_owners_json,created_by) "
            "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (slug, encode(config), team, person, encode([person]), config["description"],
             config["reports_to"], repo, "personal", now, who.actor, encode([person]), who.actor))
        H.event(c, who.actor, "bot.shared_copy_added", slug, {"source": source, "runner": runner_id})
    assignment = c.execute("SELECT * FROM assignments WHERE bot=?", (slug,)).fetchone()
    if runner and (not assignment or assignment["runner_id"] != runner["id"]):
        execution.assign(c, who, slug, SimpleNamespace(
            runner_id=runner["id"], expected_generation=assignment["generation"] if assignment else 0))
        if H.bot(c, slug)["state"] == "planned":
            c.execute("UPDATE bots SET state='active' WHERE slug=?", (slug,))
    return {**settings_admin.definition(c, slug), "created": created,
            "assignment": dict(c.execute("SELECT * FROM assignments WHERE bot=?", (slug,)).fetchone() or {})
            or None}
