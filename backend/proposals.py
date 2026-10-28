"""Proposals for the redesign's budgets and org chart (redesign CONTRACT §5): a change to a task cap, a spend limit, a
group or a teammate's home group, filed as an approval that a person decides.

  KINDS                      task_cap, spend_limit, group, org (backend/hubdb.py APPROVAL_KINDS)
  check(c, kind, payload)    refuses, when it is filed, a proposal the hub could not apply (and every one while off)
  decider(c)                 who decides: the top of the org
  apply(c, auth, settings, who, row)
                             a person approved: the hub applies it in the same transaction as the decision, as that
                             person, audited with via `approval:<id>`; the approval is spent and BotOps gets a notice

Payloads: task_cap `{sender, receiver, per_day}`; spend_limit `{bot}` or `{pool: "company"|"group:<id>"}` with
`per_30m_usd, daily_usd, weekly_usd, monthly_usd`; group `{id, ...}` a PATCH /api/v2/groups/{id} body, or with no `id` a
POST body; org `{bot, from, to}`, `bot` any teammate ref, `from`/`to` group ids ("" = no group).

The note to BotOps is a hub notice (from `keeper`, kind `notice`, refs `{approval}`), as every hub notice reaches a bot:
BotOps reads it in its inbox, the owner in BotOps's conversations. Nothing waits in a bot's queue: only work outside
the hub becomes a BotOps task.
"""
from pydantic import ValidationError

from . import hubdb as H
from . import models as M
from . import redesign
from .store import Problem

KINDS = ("task_cap", "spend_limit", "group", "org")


class SpendLimit(M.UsageLimit):
    """A spend limit change: one bot's own, or a pool's (`company` or `group:<id>`)."""
    bot: M.ID | None = None
    pool: str | None = M.Field(default=None, max_length=200)


class GroupChange(M.GroupUpdate):
    """A group change: `id` names the group to change; with none, `name` makes a new one."""
    id: M.ID | None = None
    bet_id: None = None                       # linking a bet stays the owner's own act


class OrgMove(M.Contract):
    bot: M.ID                                 # any teammate ref: bot:<slug> or person:<id>
    from_: str = M.Field(alias="from", max_length=200)
    to: str = M.Field(max_length=200)


def _parse(kind, payload):
    try:
        if kind == "task_cap":
            from .task_caps import TaskCap
            return TaskCap(**payload)
        if kind == "spend_limit":
            found = SpendLimit(**payload)
            if bool(found.bot) == bool(found.pool):
                raise Problem("validation", "A spend_limit names a bot or a pool, not both", 422)
            if found.pool and found.pool != "company" and not found.pool.startswith("group:"):
                raise Problem("validation", "A pool is company or group:<id>", 422)
            return found
        if kind == "group":
            found = GroupChange(**payload)
            if not found.id and not found.name:
                raise Problem("validation", "A new group needs a name", 422)
            return found
        return OrgMove(**payload)
    except ValidationError as exc:
        first = exc.errors()[0]
        raise Problem("validation", f"{kind} payload: {'.'.join(map(str, first['loc']))}: {first['msg']}", 422)


def check(c, kind, payload):
    if not redesign.on(c):
        # Off, the approval model takes the kinds it always took (CONTRACT §0).
        raise Problem("validation", f"body.kind: an approval of kind {kind} needs the redesign on", 422)
    _parse(kind, payload)


def decider(c):
    """The person who decides a proposal: the top of the org (the stored owner's person)."""
    from .automations import top_person
    pid = top_person(c)
    return "human:" + pid if pid else None


def _teammate(c, value):
    from .task_caps import _teammate as teammate
    return teammate(c, value)


def _name(c, value):
    from .task_caps import _name as name
    return name(c, value)


def _home(c, who):
    """The group a teammate (an actor) is in, "" for none."""
    from . import groups as G
    from . import people as P
    roster = G._roster(c)
    kind, _, ident = who.partition(":")
    if kind == "bot":
        return P.team_of(ident, G._configs(c), roster) or ""
    return (P.person(ident, roster) or {}).get("team") or ""


def _group_name(c, gid):
    from . import groups as G
    return (G._roster(c)["org_groups"].get(gid) or {}).get("name") or gid or "no group"


def _apply_cap(c, auth, settings, who, aid, change):
    from . import task_caps
    task_caps.apply_approved(c, who.actor, aid)
    sender, receiver = _teammate(c, change.sender), _teammate(c, change.receiver)
    if change.per_day is None:
        return f"Task cap removed: {_name(c, sender)} to {_name(c, receiver)}."
    return f"Task cap set: {_name(c, sender)} sends {_name(c, receiver)} {change.per_day} a day."


def _apply_spend(c, auth, settings, who, aid, change):
    from . import usage
    # Only the fields the proposal names: one it leaves out keeps its stored value (backend/usage.py `amounts`).
    limits = M.UsageLimit(**change.model_dump(include=set(M.UsageLimit.model_fields), exclude_unset=True))
    if change.bot:
        usage.save_limit(c, auth, who, change.bot, limits, via=f"approval:{aid}")
        return f"Spend limit changed for {_name(c, 'bot:' + change.bot)}."
    usage.save_pool(c, auth, who, change.pool, limits, via=f"approval:{aid}")
    return "Spend limit changed for " + ("the whole team." if change.pool == "company" else
                                         _group_name(c, change.pool.split(":", 1)[1]) + ".")


def _apply_group(c, auth, settings, who, aid, change):
    from . import groups as G
    via = f"approval:{aid}"
    if change.id:
        body = M.GroupUpdate(**change.model_dump(exclude={"id", "bet_id"}, exclude_unset=True))
        row = G.update(c, auth, settings, who, change.id, body, via=via)
        return f"Group {row['name']} changed."
    body = M.GroupCreate(**change.model_dump(include={"name", "parent", "add", "lead"}, exclude_unset=True))
    row = G.create(c, auth, settings, who, body, via=via)
    return f"Group {row['name']} made."


def _apply_org(c, auth, settings, who, aid, move):
    from . import groups as G
    teammate = _teammate(c, move.bot)
    if _home(c, teammate) != move.from_:
        raise Problem("conflict", f"{_name(c, teammate)} is no longer in {_group_name(c, move.from_)}", 409)
    kind, _, ident = teammate.partition(":")
    members = M.GroupMembers(**{"bots" if kind == "bot" else "people": [ident]})
    if move.to:
        G.update(c, auth, settings, who, move.to, M.GroupUpdate(add=members), via=f"approval:{aid}")
    elif move.from_:
        G.update(c, auth, settings, who, move.from_, M.GroupUpdate(remove=members), via=f"approval:{aid}")
    return f"{_name(c, teammate)} moved from {_group_name(c, move.from_)} to {_group_name(c, move.to)}."


APPLY = {"task_cap": _apply_cap, "spend_limit": _apply_spend, "group": _apply_group, "org": _apply_org}


def apply(c, auth, settings, who, row):
    """`who` approved `row`: the change is applied as that person (their rights checked as if they made it), the approval
    is spent, and BotOps hears once."""
    if not redesign.on(c):
        raise Problem("not_found", "Proposals are part of the redesign, which is off", 404)
    aid = row["id"]
    words = APPLY[row["kind"]](c, auth, settings, who, aid, _parse(row["kind"], row["payload"]))
    H.approval_consume(c, who.actor, aid)
    note(c, aid, f"{words} Approved by {_name(c, who.actor)}.")


def note(c, aid, words):
    """BotOps's notice of a change the hub applied: no task, nothing for it to do unless it sees work outside the hub."""
    if H.bot(c, "botops"):
        H.say(c, H.KEEPER, H.bot_actor("botops"), words, kind="notice", refs={"approval": aid})
