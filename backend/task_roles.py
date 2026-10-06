"""Roles on a task, and the role each step of a type waits on.

A task on a board passes through several hands. Besides its owner (Tico's one owner a task), any
number of people or bots can be on it, each under a role: a row of `task_roles` (`task_id`,
`role`, `actor`). A role is a short name the team chooses (`reviewer`, `qa`, `designer`,
`approver`); Tico keeps no list of them. A step of a type names the role its tasks wait on
(`task_steps.waits_on`; NULL means the owner), and a type can name the role its owner holds
without being listed (`task_types.owner_role`: on a ticket board the owner is the developer).
From these, every task answer carries `waits_on`: the role, the actors it waits on now, and
whether anyone holds that role. A step whose role nobody holds yet waits on the owner, so a task
never waits on nobody. Moving a task is what hands it on: to a step that waits on `reviewer`,
it leaves the owner's own list and lands on the reviewers', and a step back returns it.

`set_roles` is the only writer (task update, the task page, `hub task update --role`, the MCP
tools and task create come here). The rules are task update's: a party, a delegate, an ancestor's
party, a type's working bot, or a mover changes who is on a task. The owner is never stored under
the type's owner role: being the owner already says so, and a handoff moves the task with it.

This module imports nothing from hubdb at load, so hubdb can import it; the writers reach hubdb
through `_H()`.
"""
import re

ROLE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,39}$")   # a role name: a short lower-case slug
FINISHED = ("done", "closed", "declined")

SCHEMA = """
CREATE TABLE IF NOT EXISTS task_roles(
  task_id TEXT NOT NULL REFERENCES tasks(id), role TEXT NOT NULL,
  actor TEXT NOT NULL, added_by TEXT, created TEXT NOT NULL,
  PRIMARY KEY(task_id, role, actor));
CREATE INDEX IF NOT EXISTS task_roles_actor ON task_roles(actor, role);
"""


def _H():
    from . import hubdb
    return hubdb


def role_name(value):
    """A role as stored, or None when the value is not a role name."""
    name = str(value or "").strip().lower()
    return name if ROLE.match(name) else None


# ----------------------------------------------------------------------------- schema
def default_role(name, status):
    """The role a ticket board's column waits on, from its name, for a type whose steps were made
    before steps could say (a board copied from Trello). A finished column waits on nobody. QA's
    columns are the QA columns and the release chain through to the stores, pushes to production
    included; a rejection, a dependency and Dev Owned QA go back to the developer; review columns
    wait on the reviewer; everything else is the developer's."""
    if status in FINISHED:
        return None
    n = str(name or "").lower()
    if "rejected" in n or "dev owned" in n or "dependency" in n:
        return "developer"
    if "pr review" in n or "product review" in n or "code review" in n:
        return "reviewer"
    if any(w in n for w in ("qa", "uat", "staging", "prod", "stores", "native build", "ready for ios", "ready for android")):
        return "qa"
    return "developer"


def migrate(conn):
    """Create the table, the steps' `waits_on` and the types' `owner_role`; give every step of a
    numbered type (a board of tickets) that says nothing yet its default by column name, and such a
    type `developer` as the role its owner holds. Idempotent: what a mover has set is left alone."""
    H = _H()
    H.add_column(conn, "task_steps", "waits_on", "TEXT")
    H.add_column(conn, "task_types", "owner_role", "TEXT")
    for statement in SCHEMA.split(";"):
        if statement.strip():
            conn.execute(statement)
    rows = conn.execute("SELECT s.id, s.name, s.status, s.type_id FROM task_steps s JOIN task_types t ON t.id=s.type_id "
                        "WHERE t.numbered=1 AND s.waits_on IS NULL").fetchall()
    for row in rows:
        role = default_role(row[1], row[2])
        if role:
            conn.execute("UPDATE task_steps SET waits_on=? WHERE id=?", (role, row[0]))
    conn.execute("UPDATE task_types SET owner_role='developer' WHERE numbered=1 AND owner_role IS NULL "
                 "AND id IN (SELECT type_id FROM task_steps WHERE waits_on='developer')")


# ----------------------------------------------------------------------------- reads
def on_task(conn, actor, task_id):
    """Whether the actor holds any role on the task: someone on it may move it on or back."""
    return bool(conn.execute("SELECT 1 FROM task_roles WHERE task_id=? AND actor=? LIMIT 1", (task_id, actor)).fetchone())


def roles_of(conn, task_id):
    """{role: [actor, ...]} for one task: the roles somebody holds, each in the order its people
    were added."""
    out = {}
    for row in conn.execute("SELECT role, actor FROM task_roles WHERE task_id=? ORDER BY created, rowid", (task_id,)):
        out.setdefault(row[0], []).append(row[1])
    return out


def grouped(conn, task_ids):
    """{task id: {role: [actors]}} for each of `task_ids`, in a few queries."""
    out = {tid: {} for tid in task_ids}
    ids = list(task_ids)
    for i in range(0, len(ids), 400):
        part = ids[i:i + 400]
        marks = ",".join("?" * len(part))
        for row in conn.execute(f"SELECT task_id, role, actor FROM task_roles WHERE task_id IN ({marks}) "
                                "ORDER BY created, rowid", part):
            out[row[0]].setdefault(row[1], []).append(row[2])
    return out


def waits_on(row, step, roles, owner_role=None):
    """Who the task waits on now: `{role, actors, assigned}`.

    `role` is the step's `waits_on` (None: the owner, as a task with no board). `actors` are the
    people it waits on: the role's people; for the type's `owner_role` the owner first, then the
    others in it; and, when nobody holds the role yet, the owner, with `assigned` false so a page
    can say a reviewer is still needed. A finished task waits on nobody."""
    role = (step or {}).get("waits_on") or None
    owner = (row or {}).get("owner") or ""
    if (row or {}).get("status") in FINISHED:
        return {"role": role, "actors": [], "assigned": True}
    held = list((roles or {}).get(role) or []) if role else []
    if not role or (owner_role and role == owner_role):
        actors = [owner] + [a for a in held if a != owner]
        return {"role": role, "actors": [a for a in actors if a], "assigned": True}
    if held:
        return {"role": role, "actors": held, "assigned": True}
    return {"role": role, "actors": [owner] if owner else [], "assigned": False}


STEP_ROLE_SQL = "(SELECT waits_on FROM task_steps s WHERE s.id=tasks.step_id)"
OWNER_ROLE_SQL = "(SELECT owner_role FROM task_types y WHERE y.id=tasks.type_id)"


def waits_on_sql():
    """A WHERE fragment over `tasks`: the task waits on the actor bound to each of its four `?`
    (`waits_on_args(actor)`), as `waits_on` reads it. A finished task waits on nobody."""
    held = ("EXISTS (SELECT 1 FROM task_roles r WHERE r.task_id=tasks.id AND r.role=" + STEP_ROLE_SQL + " AND r.actor=?)")
    anyone = "EXISTS (SELECT 1 FROM task_roles r WHERE r.task_id=tasks.id AND r.role=" + STEP_ROLE_SQL + ")"
    return ("(tasks.status NOT IN ('done','closed','declined') AND ("
            "(COALESCE(" + STEP_ROLE_SQL + ",'')='' AND tasks.owner=?) OR "
            "(COALESCE(" + STEP_ROLE_SQL + ",'')<>'' AND (" + held + " OR (tasks.owner=? AND "
            "(" + STEP_ROLE_SQL + "=" + OWNER_ROLE_SQL + " OR NOT " + anyone + "))))))")


def waits_on_args(actor):
    return (actor,) * 3


# ----------------------------------------------------------------------------- writes
def clean(value):
    """`{role: [actors]}` from what a client sent: each role a short name, each a list of ids."""
    if value is None:
        return None
    if not isinstance(value, dict):
        raise ValueError("roles is an object: {role: [people]}, such as {reviewer: [\"dana\"], qa: []}")
    out = {}
    for raw, actors in value.items():
        role = role_name(raw)
        if not role:
            raise ValueError(f"a role is a short name in lower-case letters, digits, - or _, not {raw!r}")
        if actors is None:
            actors = []
        if isinstance(actors, str):
            actors = [a for a in actors.split(",")]
        if not isinstance(actors, (list, tuple)):
            raise ValueError(f"{role} is a list of people")
        out[role] = [str(a).strip() for a in actors if str(a or "").strip()]
    return out


def set_roles(conn, actor, task_id, roles, mover=None, note=""):
    """Replace the people in each role named in `roles` ({role: [actors]}); a role not named is
    left as it is, and [] clears one. Returns True when anything changed."""
    H = _H()
    from . import task_relations as TR
    wanted = clean(roles)
    if not wanted:
        return False
    H._writer(conn, actor)
    row = H.task(conn, task_id)
    if not row:
        H.refuse(conn, actor, "not-found", f"no task {task_id}")
    H._task_private_writer(conn, actor, row)
    mover = TR._mover(conn, actor, mover)
    TR._mine(conn, actor, row, mover)
    owner_role = (H.type_get(conn, row.get("type_id") or "") or {}).get("owner_role")
    have = roles_of(conn, task_id)
    changed = False
    at = H.now()
    for role, people in wanted.items():
        resolved = []
        for person in people:
            who = H.resolve_actor(conn, person)
            if not who:
                H.refuse(conn, actor, "reach", f"{person} is not a bot or a person on the roster")
            if H.task_private(conn, row) and not H.task_private_readable(conn, who, row):
                H.refuse(conn, actor, "private", f"{H.actor_id(who)} cannot read this private task")
            if who == row["owner"] and role == owner_role:
                continue                    # the owner holds that role already
            if who not in resolved:
                resolved.append(who)
        before = have.get(role, [])
        if resolved == before:
            continue
        conn.execute("DELETE FROM task_roles WHERE task_id=? AND role=?", (task_id, role))
        for who in resolved:
            conn.execute("INSERT INTO task_roles(task_id,role,actor,added_by,created) VALUES(?,?,?,?,?)",
                         (task_id, role, who, actor, at))
        H._task_event(conn, task_id, actor, "role:" + role, ", ".join(before) or None, ", ".join(resolved) or None, note or "")
        H.event(conn, actor, "task.roles", task_id, {"role": role, "actors": resolved})
        changed = True
    if changed:
        conn.execute("UPDATE tasks SET updated=? WHERE id=?", (at, task_id))
    return changed
