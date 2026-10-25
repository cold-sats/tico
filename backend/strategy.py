"""The team's strategy (docs/strategy.md): how it means to win, written down, versioned, and read by every bot.

- The page is one row at a time in `strategy_versions`: a short summary (400 characters, what every bot reads on every
  run), the vision (the same 400-character field the Goals page has shown), a handful of markdown sections whose keys
  come from the chosen framework, and a snapshot of the choices. Exactly one row is the `draft`; publishing stamps it
  `n` (1, 2, 3...), marks it `published`, and opens a fresh draft copied from it. `n` of the draft is NULL.
- Frameworks are lenses, not forks (`strategy_frameworks/*.yaml`): the stored shape is the same, only the section keys,
  the label of the choices and the interview questions change. Switching keeps the summary, the vision, the choices
  and any section whose key the new framework also has; the rest stays readable in the version history.
- Choices (`strategy_choices`, "bets" under the default framework) are the spine: a statement, a why, what it rules
  out, and a status (proposed, active, retired). Goals link to a choice (`goals.choice_id`), so each choice shows the
  goals that serve it and their colours. A retired choice keeps its goals.
- Every change is a `strategy_events` row, like `market_events`. Publishing tells every bot: a `strategy.published`
  routine event, one quiet note per active bot, and the text of `/strategy/summary` in every run's context from the
  next run (backend/learned.py `for_turn`, runner-rs/src/prompt.rs).

Who may: everyone signed in reads. The owner writes the draft and the choices, and so does the CEO Bot at level 3
(Acts on its own); below that it gets the refusal the goals routes give it. Only the owner publishes, on their own
click: never a bot, the CEO Bot included, and never someone acting for the owner.

Unversioned and idempotent (`ensure`), like the company profile: an older release never reads the tables or the column.
The first `ensure` on an install that has a vision or a description in `company_profile` makes the draft from them.
"""
import functools
import json
from pathlib import Path

import yaml
from fastapi import Request
from fastapi.responses import PlainTextResponse

from . import ceo_bot
from . import hubdb as H
from . import models as M
from .store import Problem

SUMMARY_MAX = 400          # one paragraph: what every bot reads on every run
VISION_MAX = 400           # one or two sentences, the same limit the Goals page has had
SECTION_MAX = 20_000       # one markdown section
NOTE_MAX = 500             # what a version was for
STATEMENT_MAX = 300        # a choice, in one sentence
CHOICE_TEXT_MAX = 2_000    # a choice's why and what it rules out
CHOICES_MAX = 20           # a strategy with more choices than this has none
VERSIONS_PAGE = 100
DEFAULT_FRAMEWORK = "plain"
CHOICE_STATUSES = ("proposed", "active", "retired")
FIELDS = ("framework", "summary", "vision", "sections")
CEO = "bot:" + ceo_bot.SLUG
EVENT = "strategy.published"
FRAMEWORKS_DIR = Path(__file__).resolve().parent / "strategy_frameworks"
# The order the page offers them in: the default first.
FRAMEWORK_ORDER = ("plain", "rumelt", "playing-to-win", "ogsm", "v2mom", "positioning")
# Sections every framework has, after its own: a strategy with no trade-offs is a description. The vision is a field
# of its own, not a section, so it is not here.
IMPLICIT = ({"key": "not", "title": "What we won't do",
             "prompt": "The customers, products, channels and deals you say no to, even when they would bring money "
                       "this quarter."},)

SCHEMA = (
    "CREATE TABLE IF NOT EXISTS strategy_versions (id TEXT PRIMARY KEY, n INTEGER UNIQUE, "
    "status TEXT NOT NULL CHECK (status IN ('draft','published')), framework TEXT NOT NULL DEFAULT 'plain', "
    "summary TEXT NOT NULL DEFAULT '', vision TEXT NOT NULL DEFAULT '', sections TEXT NOT NULL DEFAULT '{}', "
    "choices TEXT NOT NULL DEFAULT '[]', note TEXT NOT NULL DEFAULT '', updated TEXT, updated_by TEXT, "
    "published TEXT, published_by TEXT)",
    # Exactly one draft at a time.
    "CREATE UNIQUE INDEX IF NOT EXISTS strategy_versions_draft ON strategy_versions(status) WHERE status='draft'",
    "CREATE TABLE IF NOT EXISTS strategy_choices (id TEXT PRIMARY KEY, statement TEXT NOT NULL, "
    "why TEXT NOT NULL DEFAULT '', rules_out TEXT NOT NULL DEFAULT '', "
    "status TEXT NOT NULL CHECK (status IN ('proposed','active','retired')), since_n INTEGER, until_n INTEGER, "
    "rank INTEGER NOT NULL DEFAULT 0, created TEXT NOT NULL, updated TEXT NOT NULL, updated_by TEXT NOT NULL)",
    "CREATE TABLE IF NOT EXISTS strategy_events (id TEXT PRIMARY KEY, kind TEXT NOT NULL, actor TEXT NOT NULL, "
    "at TEXT NOT NULL, payload TEXT NOT NULL DEFAULT '{}')",
    "CREATE INDEX IF NOT EXISTS strategy_events_at ON strategy_events(at)",
)


def ensure(c):
    """The tables, the goals column, and once the draft: from the company profile's vision and description where an
    install has them, empty otherwise."""
    for statement in SCHEMA:
        c.execute(statement)
    H.add_column(c, "goals", "choice_id", "TEXT")
    if c.execute("SELECT 1 FROM strategy_versions LIMIT 1").fetchone():
        return False
    profile = H._one(c, "SELECT vision, description FROM company_profile WHERE id='company'") or {}
    vision = " ".join(str(profile.get("vision") or "").split())[:VISION_MAX]
    description = str(profile.get("description") or "").strip()
    now = H.now()
    c.execute("INSERT INTO strategy_versions (id, n, status, framework, summary, vision, sections, choices, note, "
              "updated, updated_by) VALUES (?,NULL,'draft',?,?,?,?,'[]','',?,?)",
              (H.new_id(), DEFAULT_FRAMEWORK, "", vision, dumps({"sell": description} if description else {}),
               now, H.KEEPER))
    if vision or description:
        _event(c, H.KEEPER, "migrated", {"fields": [f for f, v in (("vision", vision), ("sell", description)) if v]})
    return True


# ----------------------------------------------------------------------------- small helpers
def dumps(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False)


def loads(value, default):
    try:
        found = json.loads(value or "")
    except (TypeError, ValueError):
        return default
    return found if isinstance(found, type(default)) else default


def _event(c, actor, kind, payload):
    c.execute("INSERT INTO strategy_events (id, kind, actor, at, payload) VALUES (?,?,?,?,?)",
              (H.new_id(), kind, actor, H.now(), dumps(payload or {})))


def _clean(c, actor, value, limit, what, one_line=False):
    text = " ".join(str(value or "").split()) if one_line else str(value or "").strip()
    if len(text) > limit:
        H.refuse(c, actor, "lint", f"keep the {what} under {limit} characters")
    return text


# ----------------------------------------------------------------------------- frameworks
@functools.lru_cache(maxsize=1)
def frameworks():
    """Every framework, as its YAML says, the default first. Loaded once: the files ship with the release."""
    found = {}
    for path in FRAMEWORKS_DIR.glob("*.yaml"):
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        found[data["id"]] = {"id": data["id"], "name": data["name"], "choices_label": data["choices_label"],
                             "choice_label": data["choice_label"],
                             "sections": [dict(s) for s in data.get("sections") or []],
                             "implicit_sections": [s["key"] for s in IMPLICIT],
                             "interview": list(data.get("interview") or [])}
    order = {fid: i for i, fid in enumerate(FRAMEWORK_ORDER)}
    return [found[fid] for fid in sorted(found, key=lambda f: (order.get(f, len(order)), f))]


def framework(fid):
    return next((f for f in frameworks() if f["id"] == fid), None) or framework(DEFAULT_FRAMEWORK)


def section_keys(fid):
    """The framework's own sections, then the implicit ones, in the order the page renders them."""
    return [s["key"] for s in framework(fid)["sections"]] + [s["key"] for s in IMPLICIT]


def label(fid):
    return framework(fid)["choices_label"]


def label_one(fid):
    return framework(fid)["choice_label"]


# ----------------------------------------------------------------------------- reads
def _version(row):
    if not row:
        return None
    row = dict(row)
    row["sections"] = loads(row.get("sections"), {})
    row["choices"] = loads(row.get("choices"), [])
    return row


def draft(c):
    return _version(H._one(c, "SELECT * FROM strategy_versions WHERE status='draft'"))


def current(c):
    """The latest published version, or None before the first publish."""
    return _version(H._one(c, "SELECT * FROM strategy_versions WHERE status='published' ORDER BY n DESC LIMIT 1"))


def version(c, n):
    return _version(H._one(c, "SELECT * FROM strategy_versions WHERE status='published' AND n=?", (n,)))


def versions(c, limit=VERSIONS_PAGE):
    """The published versions, newest first: what the history list shows, without the sections."""
    return H._rows(c.execute("SELECT n, note, published, published_by, framework, summary FROM strategy_versions "
                             "WHERE status='published' ORDER BY n DESC LIMIT ?", (max(1, min(limit, VERSIONS_PAGE)),)))


def choice(c, choice_id):
    return H._one(c, "SELECT * FROM strategy_choices WHERE id=?", (choice_id,))


def choices(c, status=None):
    """Every choice in rank order; `status` narrows it to one status."""
    if status:
        return H._rows(c.execute("SELECT * FROM strategy_choices WHERE status=? ORDER BY rank, created", (status,)))
    return H._rows(c.execute("SELECT * FROM strategy_choices ORDER BY rank, created"))


def goals_by_choice(c):
    """{choice id: [{id, title, colour}]} over every goal that names a choice. The colour is the goal's status: red,
    yellow, green, done, dropped, or null while proposed or unscored."""
    out = {}
    for row in c.execute("SELECT id, title, status, choice_id FROM goals WHERE choice_id IS NOT NULL "
                         "ORDER BY owner, rank, created"):
        out.setdefault(row["choice_id"], []).append({"id": row["id"], "title": row["title"], "colour": row["status"]})
    return out


def view(c, who=None):
    """GET /strategy: the draft, the latest published version, the choices, the labels the draft's framework gives
    them (plural and singular), every framework, the implicit sections, each choice's goals, and whether the caller
    may edit."""
    row = draft(c)
    fid = row["framework"] if row else DEFAULT_FRAMEWORK
    return {"draft": row, "current": current(c), "choices": choices(c), "label": label(fid), "label_one": label_one(fid),
            "frameworks": frameworks(), "implicit": [dict(s) for s in IMPLICIT], "goals_by_choice": goals_by_choice(c),
            "may_edit": bool(who) and may_write(c, who)}


def may_write(c, who):
    """The owner, or the CEO Bot once the owner has raised it to level 3 (Acts on its own)."""
    if who.role == "owner":
        return True
    return who.role == "bot" and who.actor == CEO and ceo_bot.level(c) >= 3


def summary_text(c, published=None):
    """What goes into every run's context: the summary, one line per active choice, then the version. Empty before
    the first publish."""
    published = published or current(c)
    if not published:
        return ""
    lines = [published["summary"]] if published["summary"] else []
    active = [ch for ch in published["choices"] if ch.get("status") == "active"]
    if active:
        lines.append(label(published["framework"]) + ":\n" + "\n".join("- " + ch["statement"] for ch in active))
    lines.append(f"version {published['n']}")
    return "\n\n".join(lines)


def diff(c, a, b):
    """Two published versions, field by field: what changed in `from` to become `to`, and the choices added, retired
    or changed between them."""
    one, two = version(c, a), version(c, b)
    if not one or not two:
        raise Problem("not_found", f"There is no strategy version {a if not one else b}", 404)
    fields = [{"key": k, "from": one[k], "to": two[k]} for k in ("summary", "vision", "framework") if one[k] != two[k]]
    keys = section_keys(two["framework"])
    for key in sorted(set(one["sections"]) | set(two["sections"]), key=lambda k: (keys.index(k) if k in keys else len(keys), k)):
        if one["sections"].get(key) != two["sections"].get(key):
            fields.append({"key": "section:" + key, "from": one["sections"].get(key), "to": two["sections"].get(key)})
    before = {ch["id"]: ch for ch in one["choices"]}
    after = {ch["id"]: ch for ch in two["choices"]}
    changed = [{"id": cid, "from": before[cid], "to": after[cid]} for cid in after
               if cid in before and any(before[cid].get(k) != after[cid].get(k) for k in ("statement", "why", "rules_out"))]
    return {"from": a, "to": b, "fields": fields,
            "choices": {"added": [after[cid] for cid in after if cid not in before],
                        "retired": [before[cid] for cid in before if cid not in after],
                        "changed": changed}}


# ----------------------------------------------------------------------------- the draft
def framework_ids():
    return [f["id"] for f in frameworks()]


def update_draft(c, actor, framework_id=None, summary=None, vision=None, sections=None):
    """Save what changed on the draft; only the fields sent. `sections` merges: a key sent is set, a key sent as ""
    is cleared, a key not sent is kept. Section keys are checked against the framework (the new one when it changes).
    Switching frameworks keeps the sections whose key the new one has. The vision is also the company profile's
    (backend/company.py): the vision ask in Needs you and the CEO Bot's company layer read it there."""
    H._writer(c, actor)
    row = draft(c)
    changes = {}
    if framework_id is not None and framework_id != row["framework"]:
        if framework_id not in framework_ids():
            H.refuse(c, actor, "kind", f"a framework is {'|'.join(framework_ids())}, not {framework_id}")
        changes["framework"] = framework_id
    keys = section_keys(changes.get("framework", row["framework"]))
    if summary is not None:
        text = _clean(c, actor, summary, SUMMARY_MAX, "summary")
        if text != row["summary"]:
            changes["summary"] = text
    if vision is not None:
        text = _clean(c, actor, vision, VISION_MAX, "vision", one_line=True)
        if text != row["vision"]:
            changes["vision"] = text
    kept = {k: v for k, v in row["sections"].items() if k in keys}
    if sections is not None:
        if not isinstance(sections, dict):
            H.refuse(c, actor, "kind", "sections is an object of {key: markdown}")
        for key, text in sections.items():
            if key not in keys:
                H.refuse(c, actor, "kind", f"{key} is not a section of this framework; one of {', '.join(keys)}")
            text = _clean(c, actor, text, SECTION_MAX, f"{key} section")
            if text:
                kept[key] = text
            else:
                kept.pop(key, None)
    if kept != row["sections"]:
        changes["sections"] = kept
    if not changes:
        return row
    now = H.now()
    sets = ", ".join(f"{k}=:{k}" for k in changes)
    args = {**changes, "sections": dumps(changes["sections"]) if "sections" in changes else None,
            "updated": now, "updated_by": actor, "id": row["id"]}
    c.execute(f"UPDATE strategy_versions SET {sets}, updated=:updated, updated_by=:updated_by WHERE id=:id", args)
    if "vision" in changes:
        from . import company
        company.update(c, actor, vision=changes["vision"])
    _event(c, actor, "draft", {"fields": sorted(changes)})
    H.event(c, actor, "strategy.draft", "", {"fields": sorted(changes)})
    return draft(c)


# ----------------------------------------------------------------------------- the CEO Bot's proposal
def proposal_error(c, payload):
    """What is wrong with a `strategy_draft` goal proposal (backend/goals.py), in a sentence, or None. The payload is
    partial: framework, summary, vision, sections {key: markdown}, choices [{id?, statement, why, rules_out, status}]."""
    if not isinstance(payload, dict) or not any(payload.get(k) for k in (*FIELDS, "choices")):
        return "propose a framework, a summary, a vision, sections or choices"
    fid = payload.get("framework") or (draft(c) or {}).get("framework") or DEFAULT_FRAMEWORK
    if fid not in framework_ids():
        return f"a framework is {'|'.join(framework_ids())}, not {fid}"
    if len(" ".join(str(payload.get("summary") or "").split())) > SUMMARY_MAX:
        return f"keep the summary under {SUMMARY_MAX} characters"
    if len(" ".join(str(payload.get("vision") or "").split())) > VISION_MAX:
        return f"keep the vision under {VISION_MAX} characters"
    sections = payload.get("sections")
    if sections is not None:
        if not isinstance(sections, dict):
            return "sections is an object of {key: markdown}"
        for key in sections:
            if key not in section_keys(fid):
                return f"{key} is not a section of this framework; one of {', '.join(section_keys(fid))}"
    for item in payload.get("choices") or []:
        if not isinstance(item, dict):
            return "each choice is an object with a statement"
        if item.get("id") and not choice(c, item["id"]):
            return f"no choice {item['id']}"
        if not item.get("id") and not " ".join(str(item.get("statement") or "").split()):
            return "say each new choice in one sentence"
        if item.get("status") and item["status"] not in CHOICE_STATUSES:
            return f"a status is {'|'.join(CHOICE_STATUSES)}, not {item['status']}"
    return None


def apply_proposal(c, actor, payload):
    """A confirmed `strategy_draft` proposal, written as the owner: the draft (merge semantics), then each choice,
    new or changed. Nothing is published."""
    update_draft(c, actor, payload.get("framework"), payload.get("summary"), payload.get("vision"),
                 payload.get("sections"))
    ids = []
    for item in payload.get("choices") or []:
        if item.get("id"):
            row = update_choice(c, actor, item["id"], item.get("statement"), item.get("why"), item.get("rules_out"),
                                item.get("status"))
        else:
            row = add_choice(c, actor, item.get("statement"), item.get("why") or "", item.get("rules_out") or "",
                             item.get("status") or "proposed")
        ids.append(row["id"])
    return {"draft": True, "choices": ids}


# ----------------------------------------------------------------------------- choices
def add_choice(c, actor, statement, why="", rules_out="", status="proposed"):
    H._writer(c, actor)
    statement = _clean(c, actor, statement, STATEMENT_MAX, "statement", one_line=True)
    if not statement:
        H.refuse(c, actor, "lint", "say the choice in one sentence")
    if status not in CHOICE_STATUSES:
        H.refuse(c, actor, "kind", f"a status is {'|'.join(CHOICE_STATUSES)}, not {status}")
    if c.execute("SELECT count(*) FROM strategy_choices WHERE status<>'retired'").fetchone()[0] >= CHOICES_MAX:
        H.refuse(c, actor, "lint", f"a strategy holds at most {CHOICES_MAX} live choices; retire one first")
    now = H.now()
    rank = c.execute("SELECT coalesce(max(rank), -1) + 1 FROM strategy_choices").fetchone()[0]
    row = {"id": H.new_id(), "statement": statement, "why": _clean(c, actor, why, CHOICE_TEXT_MAX, "why"),
           "rules_out": _clean(c, actor, rules_out, CHOICE_TEXT_MAX, "rules_out"), "status": status,
           "rank": rank, "created": now, "updated": now, "updated_by": actor}
    c.execute("INSERT INTO strategy_choices (id, statement, why, rules_out, status, since_n, until_n, rank, created, "
              "updated, updated_by) VALUES (:id, :statement, :why, :rules_out, :status, NULL, NULL, :rank, :created, "
              ":updated, :updated_by)", row)
    _event(c, actor, "choice.add", {"id": row["id"], "status": status})
    H.event(c, actor, "strategy.choice", row["id"], {"status": status})
    return choice(c, row["id"])


def update_choice(c, actor, choice_id, statement=None, why=None, rules_out=None, status=None, rank=None):
    H._writer(c, actor)
    row = choice(c, choice_id)
    if not row:
        H.refuse(c, actor, "not-found", f"no choice {choice_id}")
    changes = {}
    if statement is not None:
        text = _clean(c, actor, statement, STATEMENT_MAX, "statement", one_line=True)
        if not text:
            H.refuse(c, actor, "lint", "say the choice in one sentence")
        changes["statement"] = text
    if why is not None:
        changes["why"] = _clean(c, actor, why, CHOICE_TEXT_MAX, "why")
    if rules_out is not None:
        changes["rules_out"] = _clean(c, actor, rules_out, CHOICE_TEXT_MAX, "rules_out")
    if status is not None:
        if status not in CHOICE_STATUSES:
            H.refuse(c, actor, "kind", f"a status is {'|'.join(CHOICE_STATUSES)}, not {status}")
        changes["status"] = status
    if rank is not None:
        changes["rank"] = int(rank)
    changes = {k: v for k, v in changes.items() if v != row[k]}
    if not changes:
        return row
    args = {**changes, "updated": H.now(), "updated_by": actor, "id": choice_id}
    c.execute(f"UPDATE strategy_choices SET {', '.join(f'{k}=:{k}' for k in changes)}, updated=:updated, "
              "updated_by=:updated_by WHERE id=:id", args)
    _event(c, actor, "choice.update", {"id": choice_id, "fields": sorted(changes)})
    H.event(c, actor, "strategy.choice", choice_id, {"fields": sorted(changes)})
    return choice(c, choice_id)


# ----------------------------------------------------------------------------- publishing
def _snapshot(row):
    return {k: row[k] for k in ("id", "statement", "why", "rules_out", "status", "rank")}


def publish(c, actor, note=""):
    """Stamp the draft as version n, snapshot the active choices into it, open a fresh draft, and tell every bot: the
    `strategy.published` routine event and one quiet note each. The owner's own call (the route checks). A draft that
    says nothing new since the last version is refused: every bot would be told for nothing."""
    H._writer(c, actor)
    note = _clean(c, actor, note, NOTE_MAX, "note", one_line=True)
    row = draft(c)
    active = [_snapshot(ch) for ch in choices(c, "active")]
    last = current(c)
    if last and all(last[k] == row[k] for k in FIELDS) and last["choices"] == active:
        H.refuse(c, actor, "lint", f"nothing has changed since version {last['n']}; edit the draft or a choice first")
    n = (last["n"] if last else 0) + 1
    now = H.now()
    c.execute("UPDATE strategy_versions SET status='published', n=?, choices=?, note=?, published=?, published_by=? "
              "WHERE id=?", (n, dumps(active), note, now, actor, row["id"]))
    c.execute("INSERT INTO strategy_versions (id, n, status, framework, summary, vision, sections, choices, note, "
              "updated, updated_by) VALUES (?,NULL,'draft',?,?,?,?,'[]','',?,?)",
              (H.new_id(), row["framework"], row["summary"], row["vision"], dumps(row["sections"]), now, actor))
    # A choice's span in versions: first published active here, or retired as of here.
    c.execute("UPDATE strategy_choices SET since_n=? WHERE status='active' AND since_n IS NULL", (n,))
    c.execute("UPDATE strategy_choices SET until_n=? WHERE status='retired' AND until_n IS NULL", (n,))
    _event(c, actor, "published", {"n": n, "note": note})
    H.event(c, actor, "strategy.publish", f"v{n}", {"n": n})
    published = version(c, n)
    text = summary_text(c, published)
    from . import routines
    routines.emit(c, EVENT, f"v{n}", {"n": n, "note": note, "published_by": actor}, title=f"Strategy v{n}",
                  content=text)
    told = []
    line = f"Strategy v{n} published" + (f": {note}." if note else ".") + " Run `hub strategy show`."
    for bot in H.bots(c, state="active"):
        try:
            H.note_create(c, actor, "bot:" + bot["slug"], line)
            told.append(bot["slug"])
        except H.Refused:          # a bot a note cannot reach (one synced from elsewhere) is not the publish's problem
            continue
    return {**published, "told": told}


# ----------------------------------------------------------------------------- HTTP
def install(app, store, auth, mutate):
    def reader(who):
        auth.domain(who)

    def writer(c, who):
        """The owner, or the CEO Bot once the owner has raised it to level 3. The CEO Bot below that gets the refusal
        the goals routes give it: it proposes, the owner confirms."""
        auth.domain(who)
        if may_write(c, who):
            return
        if who.role == "bot" and who.actor == CEO:
            raise Problem("forbidden", f"The {ceo_bot.name(c)} proposes changes to the strategy; the owner confirms "
                          "it (POST /api/v2/goal-proposals, kind strategy_draft)", 403)
        raise Problem("forbidden", "Only the owner writes the strategy draft and its choices", 403)

    def publisher(who):
        """The owner on their own click: never a bot, the CEO Bot included, never someone acting for the owner."""
        auth.domain(who)
        if who.role != "owner" or who.via:
            raise Problem("forbidden", "Only the owner publishes a strategy version, on their own click; a bot never "
                          "does", 403)

    @app.get("/api/v2/strategy")
    def strategy_show(request: Request):
        """The draft, the latest published version, the choices and the goals that serve each one."""
        who = request.state.identity
        reader(who)
        with store.read() as c:
            return view(c, who)

    @app.put("/api/v2/strategy/draft")
    def strategy_draft(request: Request, body: M.StrategyDraft):
        """Change the draft: only the fields sent. `sections` merges: a key sent is set, "" clears it, a key not sent
        is kept. Section keys must belong to the framework."""
        who = request.state.identity

        def work(c):
            writer(c, who)
            return {"draft": update_draft(c, who.actor, body.framework, body.summary, body.vision, body.sections)}
        return mutate(request, body, work)

    @app.post("/api/v2/strategy/publish")
    def strategy_publish(request: Request, body: M.StrategyPublish):
        """Owner only: the draft becomes the next numbered version and every bot is told."""
        who = request.state.identity

        def work(c):
            publisher(who)
            return publish(c, who.actor, body.note)
        return mutate(request, body, work)

    @app.get("/api/v2/strategy/versions")
    def strategy_versions(request: Request, limit: int = VERSIONS_PAGE):
        """The published versions, newest first, as a list: n, note, published, published_by, framework, summary."""
        reader(request.state.identity)
        with store.read() as c:
            return versions(c, limit)

    @app.get("/api/v2/strategy/versions/{n}")
    def strategy_version(request: Request, n: int):
        """One published version, whole: its sections and the choices as they were."""
        reader(request.state.identity)
        with store.read() as c:
            row = version(c, n)
        if not row:
            raise Problem("not_found", f"There is no strategy version {n}", 404)
        return row

    @app.get("/api/v2/strategy/diff")
    def strategy_diff(request: Request):
        """`?from=&to=`: what changed between two published versions, field by field, and the choices added,
        retired or changed."""
        reader(request.state.identity)
        try:
            a, b = int(request.query_params.get("from", "")), int(request.query_params.get("to", ""))
        except ValueError:
            raise Problem("validation", "Say which versions to compare: ?from=1&to=2", 422) from None
        with store.read() as c:
            return diff(c, a, b)

    @app.post("/api/v2/strategy/choices")
    def strategy_choice_add(request: Request, body: M.StrategyChoiceCreate):
        who = request.state.identity

        def work(c):
            writer(c, who)
            return {"choice": add_choice(c, who.actor, body.statement, body.why, body.rules_out, body.status)}
        return mutate(request, body, work)

    @app.post("/api/v2/strategy/choices/{choice_id}")
    def strategy_choice_update(request: Request, choice_id: str, body: M.StrategyChoiceUpdate):
        who = request.state.identity

        def work(c):
            writer(c, who)
            return {"choice": update_choice(c, who.actor, choice_id, body.statement, body.why, body.rules_out,
                                            body.status, body.rank)}
        return mutate(request, body, work)

    @app.get("/api/v2/strategy/summary")
    def strategy_summary(request: Request):
        """Plain text: the summary, one line per active choice, then "version N"; what every run's context carries.
        A caller that asks for JSON (the hub client does) gets it as `text`."""
        reader(request.state.identity)
        with store.read() as c:
            published = current(c)
            text = summary_text(c, published)
        if not published:
            raise Problem("not_found", "No strategy version has been published yet", 404)
        if "application/json" in request.headers.get("accept", "") and "text/plain" not in request.headers.get("accept", ""):
            return {"text": text, "n": published["n"]}
        return PlainTextResponse(text)

    @app.get("/api/v2/strategy/frameworks")
    def strategy_frameworks(request: Request):
        """Every framework: its sections, the labels for its choices, and the interview questions the CEO Bot asks;
        and the implicit sections every framework ends with."""
        reader(request.state.identity)
        return {"frameworks": frameworks(), "implicit": [dict(s) for s in IMPLICIT]}
