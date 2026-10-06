"""Who a ticket waits on: its developers, reviewers and QA, and the role each column waits on.

A ticket on a board passes through several hands. The owner (Tico's one owner a task) is the
developer it is on; a ticket can also carry more developers, reviewers and QA people, each a row
of `task_roles` (`task_id`, `role`, `actor`). A step of a type says which role its tasks wait on
(`task_steps.waits_on`: developer, reviewer or qa; NULL means the owner). From the two, every task
answer carries `waits_on`: the role, the actors it waits on, and whether anyone holds that role.
A column that waits on a role nobody holds yet waits on the owner, so a ticket never waits on
nobody. Moving a ticket to a review column is what hands it to its reviewers: it leaves the
developer's own list and lands on theirs, and a rejection brings it back.

`set_roles` is the only writer (task update, the task page, `hub task update --reviewers`, the MCP
tool and task create come here). The rules are task update's: a party, a delegate, an ancestor's
party, a type's working bot, or a mover changes who is on a task. The owner is never stored as a
developer: being the owner already says so, and a handoff moves the ticket with it.

This module imports nothing from hubdb at load, so hubdb can import it; the writers reach hubdb
through `_H()`.
"""

ROLES = ("developer", "reviewer", "qa")
WORDS = {"developer": "developers", "reviewer": "reviewers", "qa": "qa"}   # the history field a role
FINISHED = ("done", "closed", "declined")

SCHEMA = """
CREATE TABLE IF NOT EXISTS task_roles(
  task_id TEXT NOT NULL REFERENCES tasks(id), role TEXT NOT NULL CHECK (role IN ('developer','reviewer','qa')),
  actor TEXT NOT NULL, added_by TEXT, created TEXT NOT NULL,
  PRIMARY KEY(task_id, role, actor));
CREATE INDEX IF NOT EXISTS task_roles_actor ON task_roles(actor, role);
"""


def _H():
    from . import hubdb
    return hubdb


# ----------------------------------------------------------------------------- schema
def default_role(name, status):
    """The role a board's column waits on, from its name, for a type whose steps were made before
    steps could say (a ticket board copied from Trello). A finished column waits on nobody. QA's
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
    """Create the table and the steps' `waits_on`; give every step of a numbered type (a board of
    tickets) that says nothing yet its default. Idempotent: a step a mover has set is left alone,
    and a database that has both already is left as it is."""
    _H().add_column(conn, "task_steps", "waits_on", "TEXT")
    for statement in SCHEMA.split(";"):
        if statement.strip():
            conn.execute(statement)
    rows = conn.execute("SELECT s.id, s.name, s.status FROM task_steps s JOIN task_types t ON t.id=s.type_id "
                        "WHERE t.numbered=1 AND s.waits_on IS NULL").fetchall()
    for row in rows:
        role = default_role(row[1], row[2])
        if role:
            conn.execute("UPDATE task_steps SET waits_on=? WHERE id=?", (role, row[0]))


# ----------------------------------------------------------------------------- reads
def on_task(conn, actor, task_id):
    """Whether the actor holds any role on the task: a reviewer or QA may move it on or back."""
    return bool(conn.execute("SELECT 1 FROM task_roles WHERE task_id=? AND actor=? LIMIT 1", (task_id, actor)).fetchone())


def roles_of(conn, task_id):
    """{role: [actor, ...]} for one task, each role in the order its people were added; a role
    nobody holds is an empty list."""
    out = {role: [] for role in ROLES}
    for row in conn.execute("SELECT role, actor FROM task_roles WHERE task_id=? ORDER BY created, rowid", (task_id,)):
        out[row[0]].append(row[1])
    return out


def grouped(conn, task_ids):
    """{task id: {role: [actors]}} for each of `task_ids`, in a few queries."""
    out = {tid: {role: [] for role in ROLES} for tid in task_ids}
    ids = list(task_ids)
    for i in range(0, len(ids), 400):
        part = ids[i:i + 400]
        marks = ",".join("?" * len(part))
        for row in conn.execute(f"SELECT task_id, role, actor FROM task_roles WHERE task_id IN ({marks}) "
                                "ORDER BY created, rowid", part):
            out[row[0]][row[1]].append(row[2])
    return out


def waits_on(row, step, roles):
    """Who the task waits on now: `{role, actors, assigned}`.

    `role` is the step's `waits_on` (None: the owner, as a task with no board). `actors` are the
    people it waits on: the owner and the other developers for `developer`; the role's people for
    `reviewer` and `qa`, or, when nobody holds that role yet, the owner, with `assigned` false so a
    page can say a reviewer is still needed. A finished task waits on nobody."""
    role = (step or {}).get("waits_on") or None
    owner = (row or {}).get("owner") or ""
    if (row or {}).get("status") in FINISHED:
        return {"role": role, "actors": [], "assigned": True}
    held = list((roles or {}).get(role) or []) if role else []
    if role == "developer" or not role:
        actors = [owner] + [a for a in held if a != owner]
        return {"role": role, "actors": [a for a in actors if a], "assigned": True}
    if held:
        return {"role": role, "actors": held, "assigned": True}
    return {"role": role, "actors": [owner] if owner else [], "assigned": False}


STEP_ROLE_SQL = "(SELECT waits_on FROM task_steps s WHERE s.id=tasks.step_id)"


def waits_on_sql():
    """A WHERE fragment over `tasks`: the task waits on the actor bound to each of its five `?`
    (`waits_on_args(actor)`), as `waits_on` reads it. A finished task waits on nobody."""
    held = "EXISTS (SELECT 1 FROM task_roles r WHERE r.task_id=tasks.id AND r.role={role} AND r.actor=?)"
    return ("(tasks.status NOT IN ('done','closed','declined') AND CASE COALESCE(" + STEP_ROLE_SQL + ",'') "
            "WHEN '' THEN tasks.owner=? "
            "WHEN 'developer' THEN (tasks.owner=? OR " + held.format(role="'developer'") + ") "
            "ELSE (" + held.format(role=STEP_ROLE_SQL) + " OR (tasks.owner=? AND NOT EXISTS (SELECT 1 FROM task_roles r "
            "WHERE r.task_id=tasks.id AND r.role=" + STEP_ROLE_SQL + "))) END)")


def waits_on_args(actor):
    return (actor,) * 5


# ----------------------------------------------------------------------------- writes
def clean(value):
    """`{role: [actors]}` from what a client sent: known roles only, each a list of ids."""
    H = _H()
    if value is None:
        return None
    if not isinstance(value, dict):
        raise ValueError("roles is an object: {developer: [...], reviewer: [...], qa: [...]}")
    out = {}
    for role, actors in value.items():
        role = str(role or "").strip().lower().rstrip("s") if str(role or "").strip().lower() != "qa" else "qa"
        if role not in ROLES:
            raise ValueError(f"a role is {'|'.join(ROLES)}, not {role}")
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
            if who == row["owner"] and role == "developer":
                continue                    # the owner is the first developer already
            if who not in resolved:
                resolved.append(who)
        if resolved == have[role]:
            continue
        conn.execute("DELETE FROM task_roles WHERE task_id=? AND role=?", (task_id, role))
        for who in resolved:
            conn.execute("INSERT INTO task_roles(task_id,role,actor,added_by,created) VALUES(?,?,?,?,?)",
                         (task_id, role, who, actor, at))
        H._task_event(conn, task_id, actor, WORDS[role], ", ".join(have[role]) or None, ", ".join(resolved) or None, note or "")
        H.event(conn, actor, "task.roles", task_id, {"role": role, "actors": resolved})
        changed = True
    if changed:
        conn.execute("UPDATE tasks SET updated=? WHERE id=?", (at, task_id))
    return changed
