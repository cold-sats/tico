"""Goals: what every person and bot on the org chart is for, and how it says it is going.

A goal has an owner (a person, a bot, or `company`; one field), the goal it serves (`parent_id`,
optional: a goal with none is simply not linked), a colour the owner sets with one sentence, and
KPIs whose readings anyone may log at any time. What level a goal is at comes from its owner: `company`
is a company goal, `human:x` a person's, `bot:x` a bot's. A company goal is optional. No number lives on a goal, no colour is derived from children, and nothing
goes stale on its own. Bots read theirs with `hub goals`;
nothing is pushed into a run.

Rows are appended, never deleted: `dropped` is a status, a reading is a fact with an author.
Every change leaves a `goal_events` row, as `task_events` does for tasks.
"""

from datetime import timezone

from . import hubdb as H
from . import people as P

COLOURS = ("red", "yellow", "green")
STATUSES = COLOURS + ("done", "dropped")
LIVE = ("red", "yellow", "green")         # statuses a goal is still worked under; None is proposed
COMPANY = "company"                       # the owner of a company goal
SOURCES = ("measured", "estimate")        # or a connector name; only these two are checked



# ----------------------------------------------------------------------------- reads
def goal(conn, goal_id):
    return H._one(conn, "SELECT * FROM goals WHERE id=?", (goal_id,))


def goals(conn, owner=None, parent_id=None, status=None, live_only=False):
    """Goals, filtered. `status` is one status or a tuple; `live_only` leaves out done and dropped."""
    where, args = [], []
    if owner:
        where.append("owner=?")
        args.append(owner)
    if parent_id is not None:
        where.append("parent_id IS NULL" if parent_id == "" else "parent_id=?")
        if parent_id != "":
            args.append(parent_id)
    if status:
        statuses = (status,) if isinstance(status, str) else tuple(status)
        where.append(f"status IN ({','.join('?' * len(statuses))})")
        args.extend(statuses)
    if live_only:
        where.append("(status IS NULL OR status NOT IN ('done','dropped'))")
    sql = "SELECT * FROM goals" + (" WHERE " + " AND ".join(where) if where else "")
    return H._rows(conn.execute(sql + " ORDER BY owner, rank, created", args))


def chain(conn, goal_id):
    """The goal's parents, nearest first, up to the top one. Cycles stop at the repeat."""
    out, seen, row = [], {goal_id}, goal(conn, goal_id)
    while row and row.get("parent_id") and row["parent_id"] not in seen:
        seen.add(row["parent_id"])
        row = goal(conn, row["parent_id"])
        if row:
            out.append(row)
    return out


def children(conn, goal_id):
    return H._rows(conn.execute("SELECT * FROM goals WHERE parent_id=? ORDER BY owner, rank, created", (goal_id,)))


def history(conn, goal_id):
    return H._rows(conn.execute("SELECT * FROM goal_events WHERE goal_id=? ORDER BY ts", (goal_id,)))


def kpis(conn, goal_id):
    """The goal's KPIs, each with its latest measured reading and its latest reading of any kind."""
    out = []
    for row in H._rows(conn.execute("SELECT * FROM kpis WHERE goal_id=? ORDER BY created", (goal_id,))):
        row["latest"] = H._one(conn, "SELECT * FROM kpi_readings WHERE kpi_id=? ORDER BY ts DESC, created DESC LIMIT 1",
                               (row["id"],))
        row["latest_measured"] = H._one(conn, "SELECT * FROM kpi_readings WHERE kpi_id=? AND source!='estimate' "
                                              "ORDER BY ts DESC, created DESC LIMIT 1", (row["id"],))
        row["readings"] = conn.execute("SELECT count(*) FROM kpi_readings WHERE kpi_id=?", (row["id"],)).fetchone()[0]
        out.append(row)
    return out


def kpi(conn, kpi_id):
    return H._one(conn, "SELECT * FROM kpis WHERE id=?", (kpi_id,))


def readings(conn, kpi_id, limit=500):
    return H._rows(conn.execute("SELECT * FROM kpi_readings WHERE kpi_id=? ORDER BY ts, created LIMIT ?",
                                (kpi_id, limit)))


def tasks_of(conn, goal_id):
    return H._rows(conn.execute("SELECT id,title,owner,requester,status,updated FROM tasks WHERE goal_id=? "
                                "ORDER BY status, updated DESC", (goal_id,)))


def view(conn, row):
    """One goal with everything the page and `hub goal show` print."""
    return {**row, "kpis": kpis(conn, row["id"]), "children": children(conn, row["id"]),
            "chain": chain(conn, row["id"]), "tasks": tasks_of(conn, row["id"]),
            "events": history(conn, row["id"])}


def for_actor(conn, actor, roster=None, entries=None, archived=()):
    """`hub goals`: the actor's own goals in rank order, the chain above each, and the goals of
    whoever reports to it. That is the whole of what a bot needs to know what it is for."""
    mine = goals(conn, owner=actor, live_only=True)
    above, seen = [], {g["id"] for g in mine}
    for g in mine:
        for parent in chain(conn, g["id"]):
            if parent["id"] not in seen:
                seen.add(parent["id"])
                above.append(parent)
    below = []
    for report in reports_of(actor, roster, entries, archived):
        below.extend(goals(conn, owner=report, live_only=True))
    company = goals(conn, owner=COMPANY, live_only=True) if not mine and not above else []
    return {"owner": actor, "goals": mine, "chain": above, "reports": below, "company": company}


# ----------------------------------------------------------------------------- the org chart
def _key(actor):
    kind = H.actor_kind(actor)
    return ("b:" if kind == "bot" else "p:") + H.actor_id(actor) if kind in ("bot", "human") else ""


def _actor(key):
    head, _, rest = str(key or "").partition(":")
    return H.bot_actor(rest) if head == "b" else H.human_actor(rest) if head == "p" else None


def above(actor, roster, entries, archived=()):
    """Actors above this one on the org chart, nearest first: the same walk as
    `people.manages`, over people and bots alike. Department groups are stepped through."""
    kind = H.actor_kind(actor)
    if kind not in ("bot", "human"):
        return []
    out, seen = [], set()
    parent = P.org_parent("bot" if kind == "bot" else "person", H.actor_id(actor), roster, entries, archived)
    while parent and parent not in seen:
        seen.add(parent)
        head, _, rest = parent.partition(":")
        if head == "g":
            group = ((roster or {}).get("org_groups") or {}).get(rest) or {}
            boss = P._clean(group.get("reports_to"))
            parent = ("p:" + boss) if boss else ""
            continue
        out.append(_actor(parent))
        parent = P.org_parent("person" if head == "p" else "bot", rest, roster, entries, archived)
    return out


def reports_of(actor, roster, entries, archived=()):
    """Direct reports on the org chart: people whose boss this is, bots whose `reports_to` this
    is, and, for a person, the bots that hang under them or their department."""
    kind = H.actor_kind(actor)
    if kind not in ("bot", "human") or roster is None:
        return []
    mine = _key(actor)
    keys = {mine}
    if kind == "human":
        for gid, group in ((roster.get("org_groups") or {})).items():
            if P._clean(group.get("reports_to")) == H.actor_id(actor):
                keys.add("g:" + gid)
    out = []
    for p in P.visible_people(roster):
        if P.org_parent("person", p["id"], roster, entries, archived) in keys:
            out.append(H.human_actor(p["id"]))
    for slug in entries or {}:
        if slug in archived:
            continue
        if P.org_parent("bot", slug, roster, entries, archived) in keys:
            out.append(H.bot_actor(slug))
    return out


# ----------------------------------------------------------------------------- writes
def _event(conn, goal_id, actor, field, old, new, note=""):
    conn.execute("INSERT INTO goal_events (id, goal_id, ts, actor, field, old, new, note) VALUES (?,?,?,?,?,?,?,?)",
                 (H.new_id(), goal_id, H.now(), actor, field,
                  None if old is None else str(old), None if new is None else str(new), note or ""))


def _next_rank(conn, owner, top=False):
    row = conn.execute("SELECT min(rank), max(rank) FROM goals WHERE owner=? AND rank IS NOT NULL", (owner,)).fetchone()
    lowest, highest = row[0], row[1]
    if top:
        return (lowest - 1) if lowest is not None else 0
    return (highest + 1) if highest is not None else 0


def create(conn, actor, title, owner, parent_id=None, body="", top=False):
    """A new goal. With a parent it is proposed: `status` is NULL until whoever owns the parent sets
    its first colour. With none it is only unlinked."""
    H._writer(conn, actor)
    title = str(title or "").strip()
    if not title:
        H.refuse(conn, actor, "lint", "give the goal a title that says what you are going for")
    if parent_id and not goal(conn, parent_id):
        H.refuse(conn, actor, "not-found", f"no goal {parent_id}")
    if parent_id and owner == COMPANY:
        H.refuse(conn, actor, "kind", "a company goal does not support another goal")
    ts = H.now()
    row = {"id": H.new_id(), "title": title, "owner": owner, "parent_id": parent_id or None,
           "body": str(body or ""), "rank": _next_rank(conn, owner, top), "created": ts,
           "created_by": actor, "updated": ts}
    conn.execute("INSERT INTO goals (id, title, owner, parent_id, body, status, status_note, rank, created, "
                 "created_by, updated) VALUES (:id, :title, :owner, :parent_id, :body, NULL, '', :rank, "
                 ":created, :created_by, :updated)", row)
    _event(conn, row["id"], actor, "created", None, title)
    H.event(conn, actor, "goal.create", row["id"], {"owner": owner, "title": title, "parent_id": parent_id})
    return goal(conn, row["id"])


def set_status(conn, actor, goal_id, status, note=""):
    H._writer(conn, actor)
    row = goal(conn, goal_id)
    if not row:
        H.refuse(conn, actor, "not-found", f"no goal {goal_id}")
    if status not in STATUSES:
        H.refuse(conn, actor, "kind", f"a status is {'|'.join(STATUSES)}, not {status}")
    note = str(note or "").strip()
    if status in COLOURS and not note:
        H.refuse(conn, actor, "lint", "say in one sentence why it is " + status)
    ts = H.now()
    conn.execute("UPDATE goals SET status=?, status_note=?, status_by=?, status_at=?, updated=?, "
                 "rank=CASE WHEN ? IN ('done','dropped') THEN NULL WHEN rank IS NULL THEN ? ELSE rank END "
                 "WHERE id=?", (status, note, actor, ts, ts, status, _next_rank(conn, row["owner"]), goal_id))
    _event(conn, goal_id, actor, "status", row["status"], status, note)
    H.event(conn, actor, "goal.status", goal_id, {"status": status})
    if status == "dropped":
        # Nothing is deleted: the children move up to the goal this one served.
        for child in children(conn, goal_id):
            conn.execute("UPDATE goals SET parent_id=?, updated=? WHERE id=?", (row["parent_id"], ts, child["id"]))
            _event(conn, child["id"], actor, "parent_id", goal_id, row["parent_id"], f"{row['title']} was dropped")
    return goal(conn, goal_id)


def update(conn, actor, goal_id, title=None, body=None, parent_id=None, owner=None, rank=None, top=False):
    """Edit the words, the parent, the owner, or the place in the owner's order."""
    H._writer(conn, actor)
    row = goal(conn, goal_id)
    if not row:
        H.refuse(conn, actor, "not-found", f"no goal {goal_id}")
    sets, args = [], {}
    if title is not None:
        title = str(title).strip()
        if not title:
            H.refuse(conn, actor, "lint", "give the goal a title that says what you are going for")
        sets.append("title=:title")
        args["title"] = title
        _event(conn, goal_id, actor, "title", row["title"], title)
    if body is not None:
        sets.append("body=:body")
        args["body"] = str(body)
        _event(conn, goal_id, actor, "body", None, None, "body changed")
    if parent_id is not None:
        new_parent = parent_id or None
        if new_parent:
            if new_parent == goal_id:
                H.refuse(conn, actor, "kind", "a goal cannot serve itself")
            if not goal(conn, new_parent):
                H.refuse(conn, actor, "not-found", f"no goal {new_parent}")
            if goal_id in {g["id"] for g in chain(conn, new_parent)}:
                H.refuse(conn, actor, "kind", "a goal cannot serve one of its own children")
        if new_parent and (owner or row["owner"]) == COMPANY:
            H.refuse(conn, actor, "kind", "a company goal does not support another goal")
        sets.append("parent_id=:parent_id")
        args["parent_id"] = new_parent
        _event(conn, goal_id, actor, "parent_id", row["parent_id"], new_parent)
    if owner is not None and owner != row["owner"]:
        sets.append("owner=:owner")
        args["owner"] = owner
        if owner == COMPANY and (row["parent_id"] or args.get("parent_id")):
            # A company goal supports nothing.
            if "parent_id=:parent_id" not in sets:
                sets.append("parent_id=:parent_id")
                _event(conn, goal_id, actor, "parent_id", row["parent_id"], None)
            args["parent_id"] = None
        sets.append("rank=:rank")
        args["rank"] = _next_rank(conn, owner)
        _event(conn, goal_id, actor, "owner", row["owner"], owner)
    if rank is not None or top:
        sets.append("rank=:rank")
        args["rank"] = _next_rank(conn, args.get("owner") or row["owner"], top=True) if top else int(rank)
        _event(conn, goal_id, actor, "rank", row["rank"], args["rank"])
    if not sets:
        return row
    args["id"], args["updated"] = goal_id, H.now()
    conn.execute(f"UPDATE goals SET {', '.join(sets)}, updated=:updated WHERE id=:id", args)
    H.event(conn, actor, "goal.update", goal_id, {k: v for k, v in args.items() if k not in ("id", "body")})
    return goal(conn, goal_id)


def mark_read(conn, actor, goal_ids):
    """`hub goals` and `hub goal show` from a bot: the signal that the mandate was read."""
    ts = H.now()
    for gid in goal_ids:
        conn.execute("UPDATE goals SET last_read_at=?, last_read_by=? WHERE id=?", (ts, actor, gid))


def kpi_add(conn, actor, goal_id, name, unit="", target=None):
    H._writer(conn, actor)
    if not goal(conn, goal_id):
        H.refuse(conn, actor, "not-found", f"no goal {goal_id}")
    name = str(name or "").strip()
    if not name:
        H.refuse(conn, actor, "lint", "name the measure, in words: what is counted, per what")
    row = {"id": H.new_id(), "goal_id": goal_id, "name": name, "unit": str(unit or "").strip(),
           "target": target, "created": H.now(), "created_by": actor}
    conn.execute("INSERT INTO kpis (id, goal_id, name, unit, target, created, created_by) VALUES "
                 "(:id, :goal_id, :name, :unit, :target, :created, :created_by)", row)
    _event(conn, goal_id, actor, "kpi", None, name, f"target {target} {row['unit']}".strip() if target is not None else "")
    H.event(conn, actor, "kpi.add", row["id"], {"goal_id": goal_id, "name": name})
    return kpi(conn, row["id"])


def kpi_update(conn, actor, kpi_id, name=None, unit=None, target=None, clear_target=False):
    H._writer(conn, actor)
    row = kpi(conn, kpi_id)
    if not row:
        H.refuse(conn, actor, "not-found", f"no kpi {kpi_id}")
    sets, args = [], {}
    if name is not None and str(name).strip():
        sets.append("name=:name")
        args["name"] = str(name).strip()
    if unit is not None:
        sets.append("unit=:unit")
        args["unit"] = str(unit).strip()
    if target is not None or clear_target:
        sets.append("target=:target")
        args["target"] = None if clear_target else target
        _event(conn, row["goal_id"], actor, "kpi_target", row["target"], args["target"], row["name"])
    if not sets:
        return row
    args["id"] = kpi_id
    conn.execute(f"UPDATE kpis SET {', '.join(sets)} WHERE id=:id", args)
    return kpi(conn, kpi_id)


def kpi_log(conn, actor, kpi_id, value, note="", source="measured", at=None):
    """A reading: a fact somebody measured, or a guess labelled as such. Appended, never edited."""
    H._writer(conn, actor)
    row = kpi(conn, kpi_id)
    if not row:
        H.refuse(conn, actor, "not-found", f"no kpi {kpi_id}")
    source = str(source or "measured").strip().lower() or "measured"
    ts = H.now()
    when = ts
    if at:
        parsed = H.parse_ts(at)
        if not parsed:
            H.refuse(conn, actor, "date", "at must be an ISO-8601 date or date-time")
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        when = parsed.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f") + "Z"
    reading = {"id": H.new_id(), "kpi_id": kpi_id, "ts": when, "value": float(value), "actor": actor,
               "source": source, "note": str(note or "").strip(), "created": ts}
    conn.execute("INSERT INTO kpi_readings (id, kpi_id, ts, value, actor, source, note, created) VALUES "
                 "(:id, :kpi_id, :ts, :value, :actor, :source, :note, :created)", reading)
    _event(conn, row["goal_id"], actor, "reading", None, f"{row['name']}: {reading['value']:g} {row['unit']}".strip(),
           (source if source != "measured" else "") + ((" " if source != "measured" and reading["note"] else "") + reading["note"]))
    H.event(conn, actor, "kpi.log", kpi_id, {"value": reading["value"], "source": source})
    return reading


# ----------------------------------------------------------------------------- seed
def seed(conn, document, resolve):
    """Import `registry/goals.yaml` once per goal: a goal whose `id` is already in the table is
    never touched, so the file is a first draft, not a source of truth. `resolve(owner)` maps a
    slug or person id to an actor string, or None when nobody by that name is on the roster;
    such a goal is skipped and tried again at the next start."""
    added = []
    for entry in (document or {}).get("goals") or []:
        gid, owner = str(entry.get("id") or "").strip(), resolve(entry.get("owner"))
        if not gid or not owner or goal(conn, gid):
            continue
        parent = str(entry.get("parent") or "").strip() or None
        if parent and not goal(conn, parent):
            continue
        ts = H.now()
        conn.execute("INSERT INTO goals (id, title, owner, parent_id, body, status, status_note, status_by, "
                     "status_at, rank, created, created_by, updated) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                     (gid, str(entry.get("title") or gid).strip(), owner, parent, str(entry.get("body") or ""),
                      entry.get("status") if entry.get("status") in STATUSES else None,
                      str(entry.get("status_note") or ""), H.KEEPER if entry.get("status") else None,
                      ts if entry.get("status") else None, _next_rank(conn, owner), ts, H.KEEPER, ts))
        _event(conn, gid, H.KEEPER, "created", None, entry.get("title"), "registry/goals.yaml")
        for measure in entry.get("kpis") or []:
            kid = str(measure.get("id") or "").strip() or H.new_id()
            if kpi(conn, kid):
                continue
            conn.execute("INSERT INTO kpis (id, goal_id, name, unit, target, created, created_by) VALUES (?,?,?,?,?,?,?)",
                         (kid, gid, str(measure.get("name") or kid), str(measure.get("unit") or ""),
                          measure.get("target"), ts, H.KEEPER))
            for reading in measure.get("readings") or []:
                conn.execute("INSERT INTO kpi_readings (id, kpi_id, ts, value, actor, source, note, created) "
                             "VALUES (?,?,?,?,?,?,?,?)",
                             (H.new_id(), kid, str(reading.get("at") or ts), float(reading.get("value")),
                              resolve(reading.get("by")) or H.KEEPER, str(reading.get("source") or "measured"),
                              str(reading.get("note") or ""), ts))
        added.append(gid)
    return added
