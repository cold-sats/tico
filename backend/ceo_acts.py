"""What the CEO Bot does alone at level 3, and what it never does (docs/goals-and-kpis.md, "Your CEO Bot"; spec: Head
of Product, CEO Bot, tests 9, 12 and 15).

At level 3 ("Acts on its own") the CEO Bot makes a decision alone: one reason and a few changes to bot tasks, made
together under one action id (`decide`). The changes it may make are `create` (a new task for a bot), `reorder` (a
bot's task to the top of its queue), `reassign` (a bot's task to another bot) and `close` (a bot's task). Every change
is written with the action id on its task events, and the decision is a row in `ceo_actions`, the CEO Bot log on its
page, newest first. Below level 3 it decides nothing alone: a recovery is a proposal (backend/ceo_suggest.py).

The owner undoes a decision (`undo`): each task it changed goes back to what it was, field by field, and the bot that
owns it is told. A field someone changed since is kept as they left it and the result says so in plain words: Undo
never overwrites a later edit silently. A task the decision made is closed, unless someone has changed it since. What
one task can't take back (a refusal) is said too, and the rest of the decision is still undone.

"Always the person's" (`PERSON_ONLY`) is checked on the server at every level (`gate`): anything that raises cost (wake
schedules, routines, models), publishing, sending outside the company, adding or removing bots, changing a goal or KPI
target, changing the vision, changing a bot's instructions, and any task for a person. The CEO Bot never does these;
each try becomes a proposal in the owner's Needs you that says what it wanted and why it can't do it itself
(`Proposed`). A change in a decision that can't be made now (a person's task, a bot that is offline, a refusal) is never
dropped either: it becomes a proposal the same way, and the log keeps it.
"""

import contextvars

from . import ceo_bot
from . import hubdb as H

CEO = "bot:" + ceo_bot.SLUG
ACTIONS = ("create", "reorder", "reassign", "close")
MAX_CHANGES = 10
LOG_PAGE = 50
# What Undo says it put back or kept, in the owner's words.
PLAIN = {"owner": "its owner", "status": "its status", "rank": "its place in the queue", "note": "its note"}
# The fields Undo puts back, with the task events that mean someone changed one since: a step move is a status change.
EVENTS = {"owner": ("owner",), "status": ("status", "step", "type"), "rank": ("rank",), "note": ("note",)}

# What stays the person's at every level: the kind, and the words the owner reads in Needs you.
PERSON_ONLY = {
    "cost": "anything that raises cost (wake schedules, routines, models)",
    "publish": "publishing",
    "send": "sending anything outside the company",
    "bots": "adding or removing bots",
    "target": "changing a goal or KPI target",
    "vision": "changing the company's vision or description",
    "instructions": "changing a bot's instructions",
    "person_task": "a task for a person",
}

# The action a write belongs to while a decision or its Undo is being made: hubdb._task_event stamps it on every task
# event, so the log can show (and Undo can find) every change of one decision.
ACTION = contextvars.ContextVar("ceo_action", default=None)


class Proposed(H.Refused):
    """The CEO Bot tried something that stays the person's. The write is undone like any refusal, but it is not one
    of the bot's mistakes (it does not count toward quarantine): `settle` files the proposal after the rollback."""

    def __init__(self, kind, what, why=""):
        self.kind, self.what, self.why = kind, what, why
        super().__init__("proposed", f"{PERSON_ONLY[kind][0].upper()}{PERSON_ONLY[kind][1:]} stays the owner's at every "
                                     f"level: the CEO Bot does not do it. It is now a proposal in the owner's Needs you: "
                                     f"{what}")


def acts(c):
    """Whether this install's CEO Bot acts on its own: level 3."""
    return ceo_bot.level(c) >= 3


def is_ceo(actor):
    """Whether this write is the CEO Bot's, itself or acting for the owner."""
    return actor == CEO or H.VIA.get() == CEO


def gate(c, actor, kind, what, why=""):
    """Refuse the CEO Bot something on the "always the person's" list (`PERSON_ONLY`), at every level. Anyone else
    passes. The caller says what was tried, in plain words (`what`); `settle` makes it a proposal."""
    if kind not in PERSON_ONLY:
        raise ValueError(kind)
    if is_ceo(actor):
        raise Proposed(kind, " ".join(str(what or "").split())[:500], " ".join(str(why or "").split())[:1000])


def settle(c, exc):
    """After a `Proposed` write is rolled back (backend/store.py `refused`): the proposal in the owner's Needs you and
    the line in the CEO Bot log. Returns the log row."""
    return _log(c, kind=exc.kind, reason=exc.why, state="proposed",
                left=[{"change": {"do": exc.kind}, "text": exc.what, "why": PERSON_ONLY[exc.kind] + " stays the owner's"}])


# ----------------------------------------------------------------------------- deciding alone
def _name(c, actor):
    if H.is_bot(actor):
        return (H.bot(c, H.actor_id(actor)) or {}).get("display_name") or H.actor_id(actor)
    return (H.human(c, H.actor_id(actor)) or {}).get("name") or H.actor_id(actor or "")


def _title(row):
    return f'"{row["title"]}"' if row else "a task"


def _bot_task(c, task_id):
    """A task the CEO Bot may change alone: live, owned by a bot, and one it may read. None otherwise."""
    row = H.task(c, str(task_id or ""))
    if not row or row["status"] not in H.ACTIVE_STATUSES or not H.is_bot(row["owner"]):
        return None
    return row if H.task_private_readable(c, CEO, row) else None


def _offline(c, actor):
    state = (H.bot(c, H.actor_id(actor)) or {}).get("state")
    return None if state == "active" else f"{_name(c, actor)} is {state or 'gone'} right now"


def describe(c, change):
    """One change in plain words."""
    do = change.get("do")
    row = H.task(c, change.get("task_id") or "") if change.get("task_id") else None
    if do == "create":
        return f'New task for {_name(c, change.get("owner", ""))}: "{change.get("title", "")}"'
    if do == "reorder":
        return f"Move {_title(row)} to the top of {_name(c, (row or {}).get('owner', ''))}'s queue"
    if do == "reassign":
        return f"Give {_title(row)} to {_name(c, change.get('owner', ''))}"
    if do == "close":
        return f"Close {_title(row)}"
    return PERSON_ONLY.get(do, str(do))


def _check(c, change):
    """Why this change can't be made alone, in plain words, with whether it is a person's (`PERSON_ONLY`) — or None.
    Cleans `change` in place: owners become actors and text is trimmed."""
    do = change.get("do")
    if do not in ACTIONS:
        return f"a change is {'|'.join(ACTIONS)}", None
    if do in ("create", "reassign"):
        owner = H.resolve_actor(c, str(change.get("owner") or "").strip()) or str(change.get("owner") or "")
        if H.is_human(owner):
            change["owner"] = owner
            return "a task for a person stays the person's to give", "person_task"
        if not H.is_bot(owner) or not H.bot(c, H.actor_id(owner)):
            return f"no bot {change.get('owner') or '(none named)'} to give the task to", None
        change["owner"] = owner
    if do == "create":
        change["title"] = " ".join(str(change.get("title") or "").split())[:300]
        change["body"] = str(change.get("body") or "").strip()[:8000]
        if not change["title"]:
            return "a new task needs a title", None
        return _offline(c, change["owner"]), None
    row = H.task(c, str(change.get("task_id") or ""))
    if row and H.is_human(row["owner"]):
        return f"{_title(row)} is a person's task, so it stays theirs", "person_task"
    if not _bot_task(c, change.get("task_id")):
        return "name a live bot task (a finished or private one can't be changed)", None
    if do == "reassign" and change["owner"] == row["owner"]:
        return f"{_title(row)} is already {_name(c, row['owner'])}'s", None
    if do == "close":
        change["note"] = " ".join(str(change.get("note") or "").split())[:1000]
    return _offline(c, row["owner"]) or (_offline(c, change["owner"]) if do == "reassign" else None), None


FIELDS = ("status", "step_id", "step_rank", "owner", "rank", "note", "closed_at", "closed_by")


def _snapshot(row):
    return {k: row.get(k) for k in FIELDS}


def _apply(c, change, goal_id, reason):
    """Make one change as the CEO Bot; returns what Undo needs: the task, and its fields before and after."""
    do = change["do"]
    if do == "create":
        made = H.task_create(c, CEO, change["title"],
                             (change["body"] + "\n\n" if change["body"] else "") +
                             f"Made by the {ceo_bot.name(c)} on its own: {reason}",
                             change["owner"], goal_id=goal_id or None, lane="company")
        return {"task_id": made["id"], "made": True, "before": None, "after": _snapshot(H.task(c, made["id"]))}
    row = H.task(c, change["task_id"])
    before = _snapshot(row)
    if do == "reorder":
        H.task_update(c, CEO, row["id"], rank=H._queue_end(c, row["owner"], top=True), mover=True, quiet=True)
    elif do == "reassign":
        H.task_update(c, CEO, row["id"], owner=change["owner"], mover=True)
    else:
        H.task_close(c, H.KEEPER, row["id"], change["note"] or f"Closed by the {ceo_bot.name(c)}: {reason}")
        c.execute("UPDATE tasks SET closed_by=? WHERE id=?", (CEO, row["id"]))
    _bump(c, row["id"])
    return {"task_id": row["id"], "made": False, "before": before, "after": _snapshot(H.task(c, row["id"]))}


def _bump(c, task_id):
    """A form or bot holding the task from before this write gets a version conflict, as after any task update."""
    c.execute("UPDATE tasks SET version=version+1 WHERE id=?", (task_id,))


def decide(c, actor, reason, changes, goal_id=None):
    """A decision the CEO Bot makes alone, at level 3: each change made on its own under one action id, the rest (a
    person's task, a bot offline, a refusal) one proposal in the owner's Needs you with the reason. Returns the log
    row."""
    H._writer(c, actor)
    if not is_ceo(actor) or H.VIA.get():
        H.refuse(c, actor, "identity", f"Only the {ceo_bot.name(c)} decides alone, and only for itself")
    if not acts(c):
        H.refuse(c, actor, "state", f"The {ceo_bot.name(c)} acts on its own only at level 3, which the owner chooses "
                                    "in Settings; propose a recovery instead (POST /api/v2/goal-proposals)")
    reason = " ".join(str(reason or "").split())[:1000]
    if not reason:
        H.refuse(c, actor, "lint", "say why, in a sentence the owner reads in the log")
    if not isinstance(changes, list) or not 1 <= len(changes) <= MAX_CHANGES:
        H.refuse(c, actor, "lint", f"a decision makes 1 to {MAX_CHANGES} changes")
    if goal_id and not c.execute("SELECT 1 FROM goals WHERE id=?", (goal_id,)).fetchone():
        H.refuse(c, actor, "not-found", f"no goal {goal_id}")
    action_id = H.new_id()
    done, left = [], []
    token = ACTION.set(action_id)
    try:
        for change in changes:
            change = dict(change) if isinstance(change, dict) else {}
            why, kind = _check(c, change)
            if why:
                left.append({"change": change, "text": describe(c, change), "why": why, "kind": kind})
                continue
            c.execute("SAVEPOINT ceo_change")
            try:
                out = _apply(c, change, goal_id, reason)
            except H.Refused as exc:
                c.execute("ROLLBACK TO ceo_change")
                c.execute("RELEASE ceo_change")
                left.append({"change": change, "text": describe(c, change), "why": exc.detail or str(exc.rule)})
                continue
            c.execute("RELEASE ceo_change")
            done.append({"change": change, "text": describe(c, change), **out})
    finally:
        ACTION.reset(token)
    return _log(c, kind="decision", reason=reason, goal_id=goal_id, done=done, left=left, action_id=action_id,
                state="done" if done else "proposed")


# ----------------------------------------------------------------------------- the log and its proposals
def _owner(c):
    from . import people as P, views
    roster = views.roster(c) or {}
    person = P.person(roster.get("default_user"), roster) or {}
    return H.human_actor(person["id"]) if person.get("id") else None


def _propose(c, reason, left):
    """What the CEO Bot couldn't do alone, as one item in the owner's Needs you, or why it isn't there (the 5 a day
    are used, or no owner yet). Returns (task id or None, note)."""
    owner = _owner(c)
    if not owner:
        return None, "No owner to propose it to yet"
    if ceo_bot.room_today(c, owner) == 0:
        return None, (f"Not in Needs you: the {ceo_bot.name(c)} has put {ceo_bot.DAILY_CAP} items there today; "
                      "it stays here in the log")
    lines = "\n".join(f"- {x['text']}: {x['why']}" for x in left)
    # One item per thing proposed: the same thing tried again finds the item already waiting (a duplicate).
    title = (f"Decide on the {ceo_bot.name(c)}'s proposal: {left[0]['text']}" if len(left) == 1 else
             f"Decide on {len(left)} changes the {ceo_bot.name(c)} proposed: {reason}")[:200]
    body = (f"Please decide whether to make these changes yourself; the {ceo_bot.name(c)} may not make them.\n"
            + (f"Why it wanted them: {reason}\n" if reason else "") + lines +
            f"\nNothing changed. Make the change yourself if you agree, or close this to leave it.")
    c.execute("SAVEPOINT ceo_propose")
    try:
        made = H.task_create(c, CEO, title, body, owner, lint=False)
    except H.Refused as exc:
        c.execute("ROLLBACK TO ceo_propose")
        c.execute("RELEASE ceo_propose")
        return None, f"Not in Needs you: {exc.detail or exc.rule}; it stays here in the log"
    c.execute("RELEASE ceo_propose")
    return made["id"], ""


def _log(c, *, kind, reason, state, done=(), left=(), goal_id=None, action_id=None):
    proposal, note = _propose(c, reason, list(left)) if left else (None, "")
    row = {"id": action_id or H.new_id(), "created": H.now(), "actor": CEO, "kind": kind, "reason": reason or "",
           "goal_id": goal_id or None, "state": state, "proposal_task": proposal, "note": note,
           "changes_json": H._dump({"done": list(done), "left": list(left)})}
    c.execute("INSERT INTO ceo_actions (id, created, actor, kind, reason, goal_id, state, proposal_task, note, "
              "changes_json) VALUES (:id, :created, :actor, :kind, :reason, :goal_id, :state, :proposal_task, :note, "
              ":changes_json)", row)
    H.event(c, CEO, "ceo_bot." + ("decided" if kind == "decision" else "proposed"), row["id"],
            {"kind": kind, "done": len(done), "left": len(left)})
    return entry(c, row["id"])


def entry(c, action_id):
    row = H._one(c, "SELECT * FROM ceo_actions WHERE id=?", (action_id,))
    if not row:
        return None
    changes = H._json(row.pop("changes_json"), None) or {}
    row["done"], row["left"] = changes.get("done") or [], changes.get("left") or []
    row["undo"] = H._json(row.pop("undo_json", None), None) or None
    row["undoable"] = row["state"] == "done"
    return row


def log(c, before=None, limit=LOG_PAGE):
    """The CEO Bot log, newest first: {items, next_before}. Paged by `created`."""
    limit = max(1, min(int(limit or LOG_PAGE), LOG_PAGE))
    rows = c.execute("SELECT id, created FROM ceo_actions WHERE (? IS NULL OR created<?) ORDER BY created DESC LIMIT ?",
                     (before, before, limit + 1)).fetchall()
    items = [entry(c, r[0]) for r in rows[:limit]]
    return {"items": items, "next_before": rows[limit - 1][1] if len(rows) > limit else None}


# ----------------------------------------------------------------------------- undo
def undo(c, actor, action_id):
    """The owner undoes a decision. Each task it changed goes back field by field where nobody changed the field
    since; a field changed since keeps its later value, and the result says which and by whom. A task it made is
    closed unless someone changed it since. A task Tico won't put back (a refusal) is said, and the others still are.
    Each bot whose task changed is told. Done once."""
    H._writer(c, actor)
    row = entry(c, action_id)
    if not row:
        H.refuse(c, actor, "not-found", f"no CEO Bot decision {action_id}")
    if row["state"] != "done":
        H.refuse(c, actor, "duplicate", "this decision was " + ("undone already" if row["state"] == "undone" else
                                                                "a proposal; nothing was changed to undo"))
    restored, kept = [], []
    token = ACTION.set(action_id)
    try:
        for item in _per_task(row["done"]):
            task = H.task(c, item["task_id"])
            if not task:
                kept.append(f"{item['text']}: the task is gone")
                continue
            c.execute("SAVEPOINT ceo_undo")
            try:
                did = (_unmake if item.get("made") else _restore)(c, actor, task, item, row["created"], kept)
            except H.Refused as exc:
                c.execute("ROLLBACK TO ceo_undo")
                c.execute("RELEASE ceo_undo")
                kept.append(f"{_title(task)} could not be put back: {exc.detail or exc.rule}")
                continue
            c.execute("RELEASE ceo_undo")
            if did:
                restored.append(did)
                _bump(c, task["id"])
                _tell(c, actor, H.task(c, task["id"]), item["after"]["owner"])
    finally:
        ACTION.reset(token)
    result = {"restored": restored, "kept": kept, "text": _undo_text(restored, kept)}
    c.execute("UPDATE ceo_actions SET state='undone', undone_at=?, undone_by=?, undo_json=? WHERE id=?",
              (H.now(), actor, H._dump(result), action_id))
    H.event(c, actor, "ceo_bot.undone", action_id, {"restored": len(restored), "kept": len(kept)})
    return entry(c, action_id)


def _per_task(done):
    """One item per task, in the order the decision first changed it: its fields before the decision's first change
    to it and after its last, so two changes to one task are undone together."""
    tasks = {}
    for item in done:
        if item["task_id"] in tasks:
            tasks[item["task_id"]]["after"] = item["after"]
        else:
            tasks[item["task_id"]] = dict(item)
    return list(tasks.values())


def _later(c, task_id, fields, since, action_id):
    """Who last changed any of these task event fields after the decision, or None."""
    marks = ",".join("?" * len(fields))
    found = c.execute(f"SELECT actor FROM task_events WHERE task_id=? AND field IN ({marks}) AND ts>? "
                      "AND coalesce(action_id,'')!=? ORDER BY ts DESC, rowid DESC LIMIT 1",
                      (task_id, *fields, since, action_id)).fetchone()
    return found[0] if found else None


def _value(task, field):
    return (task.get("status"), task.get("step_id")) if field == "status" else task.get(field)


def _changed_since(c, task, after, field, since):
    """Who changed this field after the decision (or "someone", when its value moved with no event), or None."""
    action_id = ACTION.get()
    who = _later(c, task["id"], EVENTS[field], since, action_id)
    if who:
        return who
    return "someone" if _value(task, field) != _value(after, field) else None


def _unmake(c, actor, task, item, since, kept):
    """Close a task the decision made, unless someone changed it since: then it stays as they left it."""
    if task["status"] == "closed":
        kept.append(f"{_title(task)}, which it made, was closed since")
        return None
    for field in ("owner", "status", "note"):
        who = _changed_since(c, task, item["after"], field, since)
        if who:
            kept.append(f"{_title(task)}, which it made, was changed since by {_name(c, who)}, so it stays open")
            return None
    H.task_close(c, H.KEEPER, task["id"], f"Undone by {_name(c, actor)}: the {ceo_bot.name(c)} made this task on its "
                                          "own")
    return f"Closed {_title(task)}, which it made"


def _restore(c, actor, task, item, since, kept):
    """Put back each field the decision changed that nobody changed since, in one write; returns what was put back."""
    before, after = item["before"], item["after"]
    back = []
    for field in ("owner", "status", "rank", "note"):
        if _value(before, field) == _value(after, field):
            continue
        who = _changed_since(c, task, after, field, since)
        if who:
            kept.append(f"{_title(task)}: {PLAIN[field]} was changed since by {_name(c, who)}, so their change stays")
        else:
            back.append(field)
    if not back:
        return None
    put = {}
    if "owner" in back:
        put["owner"] = before["owner"]
        # A new owner otherwise puts it at the bottom of their queue: the place goes back too, or stays as it is now.
        put["rank"] = before["rank"] if "rank" in back else task["rank"]
    elif "rank" in back:
        put["rank"] = before["rank"]
    if "status" in back:
        put["status"] = before["status"]
        if before.get("step_id"):
            put["step"], put["step_rank"] = before["step_id"], before.get("step_rank")
    if "note" in back:
        put["note"] = before.get("note") or ""
    H.task_update(c, actor, task["id"], mover=True, **put)
    if "status" in back:
        c.execute("UPDATE tasks SET closed_at=?, closed_by=? WHERE id=?",
                  (before.get("closed_at"), before.get("closed_by"), task["id"]))
    return f"{_title(task)}: {', '.join(PLAIN[f] for f in back)} put back"


def _tell(c, actor, task, held_by):
    """Tell each bot the Undo changed things for: the task's owner now, and the bot the decision gave it to."""
    said = (f"{_name(c, actor)} undid a decision the {ceo_bot.name(c)} made on its own; this task is back as it was "
            "before it")
    for bot in dict.fromkeys((task["owner"], held_by)):
        if bot and H.is_bot(bot):
            H._wake(c, task, bot, said + ("." if bot == task["owner"] else
                                          f", with {_name(c, task['owner'])}. It is no longer yours."))


def _undo_text(restored, kept):
    text = ("Undone: " + "; ".join(restored) + ".") if restored else "Nothing needed restoring."
    if kept:
        text += " Not restored: " + "; ".join(kept) + "."
    return text
