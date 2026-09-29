"""The hub's tool schema: one table of tools, the same names and arguments as the `hub` CLI.

This is the contract bots follow (the standard is the schema, not the
transport). Two clients read it:

  * the MCP server at `/api/v2/mcp` (`backend/mcp.py`) and the stdio adapter a runtime
    spawns on the Mac (`clients/hubmcp.py`); both hand each tool an `api` object;
  * the `hub` CLI, whose commands map onto these names one for one (`hub task create`
    is `hub_task_create`).

Every tool is written against a two-method `api`: `api.get(path, **query)` and
`api.post(path, body, key=None)`, paths relative to `/api/v2/`. On the Mac that is
`clients.tico.Client`; on the server it is an in-process caller that replays the caller's
own bearer token through the ordinary routes, so a tool can do nothing the HTTP API refuses.
No rule lives here; the rules live in `backend/hubdb.py`.

Pure stdlib on purpose: this module is imported by the runner venv, the cloud venv and the
CLI alike.
"""
import json
import sys
import time
from datetime import datetime
from pathlib import Path

from clients.agent_skill import WHO_NEEDS_ME

PROTOCOL_VERSIONS = ("2025-11-25", "2025-06-18", "2025-03-26")
SERVER_INFO = {"name": "tico-hub", "title": "Tico hub", "version": "0.1"}
ASK_WAIT_MAX = 300
TASK_STATUSES = ("open", "doing", "waiting", "review", "ready", "done", "closed", "declined")
APPROVAL_KINDS = ("send", "spend", "publish", "merge")
GOAL_STATUSES = ("red", "yellow", "green", "done", "dropped")

# What an agent reads on connect: the hub in one line, then the skill a person's own agent
# follows to work their bots (clients/agent_skill.py). Bots ignore the skill; it is for people.
INSTRUCTIONS = ("The company hub: tasks, messages, approvals, status. "
                "Every rule is enforced server-side; a refusal says which.\n\n" + WHO_NEEDS_ME)

TOOLS = []


def _s(description, **extra):
    return {"type": "string", "description": description, **extra}


def tool(name, description, properties, required=(), *, writes=False):
    """Register one tool; the decorated function is `fn(api, args) -> result`."""
    schema = {"type": "object", "properties": dict(properties), "additionalProperties": False}
    if required:
        schema["required"] = list(required)
    if writes:
        schema["properties"]["operation_id"] = _s(
            "A stable id for this write so a retried call lands once. Omit for a fresh id.")

    def register(fn):
        TOOLS.append({"name": name, "description": description, "inputSchema": schema,
                      "writes": writes, "fn": fn})
        return fn
    return register


def alias(name, of):
    """Register `name` as another name for the tool `of`: the same schema and handler, so an old bot
    that still says `hub_judge` keeps working after the rename to `hub_decisions`."""
    original = next(t for t in TOOLS if t["name"] == of)
    TOOLS.append({**original, "name": name, "description": f"Deprecated name of {of}. {original['description']}"})


def _refs(values):
    out = {}
    for value in values or []:
        kind, _, ident = str(value).partition(":")
        out.setdefault(kind, []).append(ident)
    return out


def _target(api, value):
    if value in ("me", "self"):
        return api.get("me")["actor"]
    return value


def _key(args, suffix=""):
    op = args.get("operation_id")
    return (op + suffix) if op else None


# ----------------------------------------------------------------------------- identity, messages
@tool("hub_whoami", "Who you are to the hub: actor, role, runner and attempt, or the external "
      "agent harness (a Hermes profile) when that is what runs you.", {})
def whoami(api, args):
    return api.get("me")


@tool("hub_say", "Send a message to a bot or a person. Bot-to-person messages are linted "
      "(first line is the ask, under 120 words) and capped at 3 unsolicited a day.",
      {"to": _s("Recipient: a bot slug, `bot:<slug>`, or a person id"),
       "text": _s("The message"),
       "conversation_id": _s("Continue this conversation instead of opening a pair conversation"),
       "refs": {"type": "array", "items": {"type": "string"},
                "description": "References like `task:<id>` or `approval:<id>`"}},
      required=("to", "text"), writes=True)
def say(api, args):
    return api.post("messages", {"to": args["to"], "text": args["text"], "kind": "say",
                                 "conversation_id": args.get("conversation_id"),
                                 "refs": _refs(args.get("refs"))}, key=_key(args))


@tool("hub_note", "Leave a bot a quiet note: it wakes nobody, asks nothing, and the bot's next run "
      "reads it in the same prompt as whatever woke it.",
      {"to": _s("The bot: a slug or `bot:<slug>`"), "text": _s("What it should know")},
      required=("to", "text"), writes=True)
def note(api, args):
    return api.post("notes", {"to": args["to"], "text": args["text"]}, key=_key(args))["note"]


@tool("hub_notes", "Quiet notes, newest first: the ones left for you and the ones you left.",
      {"to": _s("Only notes to this bot (`me` for you)"), "from": _s("Only notes from this bot"),
       "since": _s("ISO time"), "waiting": {"type": "boolean", "default": False}})
def notes(api, args):
    return api.get("notes", to=args.get("to"), sender=args.get("from"), since=args.get("since"),
                   waiting="true" if args.get("waiting") else None)


@tool("hub_unnote", "Take back a quiet note you left, before any run has carried it.",
      {"id": _s("The note id")}, required=("id",), writes=True)
def unnote(api, args):
    return api.post(f"notes/{args['id']}/cancel", {}, key=_key(args))["note"]


@tool("hub_notice", "An fyi to a bot or a person that expects no reply.",
      {"to": _s("Recipient: a bot slug or a person id"), "text": _s("The notice")},
      required=("to", "text"), writes=True)
def notice(api, args):
    return api.post("messages", {"to": args["to"], "text": args["text"], "kind": "notice",
                                 "conversation_id": None, "refs": {}}, key=_key(args))


@tool("hub_ask", "Ask one or more bots a question and wait for their answers. Returns one entry "
      "per bot: `answer`, `unknown`, or `timeout`. Asks nest at most three deep.",
      {"bots": {"type": "array", "items": {"type": "string"}, "minItems": 1,
                "description": "Bot slugs to ask"},
       "text": _s("The question"),
       "wait_s": {"type": "integer", "minimum": 0, "maximum": ASK_WAIT_MAX, "default": 60,
                  "description": "How long to wait for answers, in seconds"}},
      required=("bots", "text"), writes=True)
def ask(api, args):
    wait = max(0, min(int(args.get("wait_s", 60) or 0), ASK_WAIT_MAX))
    pending, result = {}, {}
    for i, bot in enumerate(args["bots"]):
        msg = api.post("messages", {"to": bot, "text": args["text"], "kind": "ask", "wait_s": wait},
                       key=_key(args, f":ask:{i}"))
        pending[msg["id"]] = bot
    deadline = time.monotonic() + wait
    while pending:
        answers = api.get("answers", ids=",".join(pending))
        for mid, answer in answers.items():
            bot = pending.pop(mid)
            result[bot] = {"unknown" if (answer.get("refs") or {}).get("unknown") else "answer": answer["body"]}
            api.post(f"messages/{answer['id']}/ack", {}, key=_key(args, ":ack:" + answer["id"]))
        if not pending or time.monotonic() >= deadline:
            break
        time.sleep(1)
    result.update({bot: {"timeout": True} for bot in pending.values()})
    return result


@tool("hub_answer", "Answer a question another bot asked you.",
      {"message_id": _s("The ask's message id"),
       "text": _s("Your answer"),
       "unknown": {"type": "boolean", "default": False,
                   "description": "True when you cannot answer; `text` then says what you would need"}},
      required=("message_id", "text"), writes=True)
def answer(api, args):
    return api.post(f"messages/{args['message_id']}/answer",
                    {"text": args["text"], "unknown": bool(args.get("unknown"))}, key=_key(args))


# ----------------------------------------------------------------------------- company context
@tool("hub_context_search", "Search company documents and market knowledge. Returns keyword matches with source links and excerpts; visibility follows your identity.",
      {"q": _s("Words to search for"), "source": {"type": "string", "enum": ["all", "docs", "market"]},
       "limit": {"type": "integer", "minimum": 1, "maximum": 50}}, required=("q",))
def context_search(api, args):
    return api.get("context/search", **args)


@tool("hub_context_show", "Read a complete document found by context search. For market entities use hub_market_show.",
      {"id": _s("Document id from context search")}, required=("id",))
def context_show(api, args):
    return api.get("context/document", id=args["id"])


@tool("hub_meetings_search", "Search meeting history and transcripts, with excerpts and available speaker timestamps. Bots see explicitly shared company meetings, never personal notes or private meetings. Empty q lists recent accessible meetings.",
      {"q": _s("Words to search for; omit for recent history"), "person": _s("Owner, participant, or speaker"),
       "since": _s("Inclusive meeting date, YYYY-MM-DD; creation date when no start is recorded"), "until": _s("Inclusive meeting date, YYYY-MM-DD"),
       "limit": {"type": "integer", "minimum": 1, "maximum": 50},
       "offset": {"type": "integer", "minimum": 0}})
def meetings_search(api, args):
    return api.get("meetings/search", **args)


@tool("hub_meetings_transcript", "Read a meeting transcript. Follow next_offset to read the complete text; access matches meetings search.",
      {"id": _s("Meeting id"), "offset": {"type": "integer", "minimum": 0},
       "limit": {"type": "integer", "minimum": 1, "maximum": 50000}}, required=("id",))
def meetings_transcript(api, args):
    return api.get("meetings/transcript", **args)


@tool("hub_meetings_import", "File a meeting transcript or notes from another tool (Zoom, Google Meet, Granola, Otter, "
      "Fireflies, a file...) as a finished meeting of yours. The transcript is plain text (one line per turn: an optional "
      "[mm:ss] and 'Name: text'), WebVTT, SRT, or JSON segments [{speaker, start, end, text}] with times in seconds; the "
      "format is detected. Send the same source and external_id again to update it instead of adding another.",
      {"title": _s("What the meeting was"), "transcript": {"description": "The transcript: text, WebVTT, SRT, or JSON "
                                                                          "segments as a string or a list of objects",
                                                            "type": ["string", "array"]},
       "format": _s("auto (default), text, vtt, srt or json"),
       "notes": _s("Notes or a summary, in Markdown"), "started_at": _s("When it started, ISO-8601 with a timezone"),
       "duration_seconds": {"type": "number", "minimum": 0},
       "participants": {"type": "array", "items": {"type": "string"}, "description": "Emails or names"},
       "source": _s("Where it came from: zoom, granola, otter, fireflies, upload... (default api)"),
       "external_id": _s("That system's id for it, to update it later"), "media_url": _s("An https link to the recording"),
       "private": {"type": "boolean"}, "send_to": _s("A bot to hand the meeting to, as Send does")})
def meetings_import(api, args):
    return api.post("meetings/import", args)


def meetings_import_file(api, args):
    """`hub meetings import <file>`: the CLI reads the files, so nothing here needs a path on the server."""
    args = dict(args)
    path = args.pop("file")
    text = sys.stdin.read() if path == "-" else Path(path).read_text(encoding="utf-8-sig")
    notes = args.pop("notes_file", None)
    when = args.pop("date", None)
    fields = {"transcript": text, "title": args.pop("title", None) or ("" if path == "-" else Path(path).stem),
              "participants": args.pop("participants", None) or []}
    if notes:
        fields["notes"] = Path(notes).read_text(encoding="utf-8")
    if when:
        try:
            fields["started_at"] = datetime.fromisoformat(when).astimezone().isoformat()
        except ValueError:
            raise ValueError(f"--date {when!r} is not a date: use 2026-09-28 or 2026-09-28T16:00") from None
    return api.post("meetings/import", {**{k: v for k, v in args.items() if v is not None}, **fields})


# ----------------------------------------------------------------------------- tasks
@tool("hub_task_create", "File a task for a bot or a person. A task for a person is a decision "
      "or a review: title says what you are asking, body under 120 words. `dry_run` reports the "
      "checks a create would fail and writes nothing.",
      {"owner": _s("Who does it: a bot slug, a person id, or `me`"),
       "title": _s("What you are asking for, in plain words: no reference numbers, no all-caps"),
       "body": _s("The details", default=""),
       "due": _s("ISO-8601 date-time with timezone"),
       "parent_id": _s("Parent task id, when this is one part of a bigger task"),
       "labels": {"type": "array", "items": {"type": "string"},
                  "description": "Labels: a project name, a kind (bug, front-end). Lower-case words."},
       "top": {"type": "boolean", "default": False,
               "description": "Put it at the top of the owner's queue instead of the bottom"},
       "links": {"type": "array", "items": {"type": "string"},
                 "description": "URLs to attach: a pull request, an issue, a document"},
       "goal_id": _s("The goal this task serves (hub_goals); optional"),
       "next_run": {"type": "boolean", "default": False,
                    "description": "For a bot owner: do not wake it; its next run carries this task"},
       "dry_run": {"type": "boolean", "default": False}},
      required=("owner", "title"), writes=True)
def task_create(api, args):
    body = {"owner": _target(api, args["owner"]), "title": args["title"], "body": args.get("body") or "",
            "due": args.get("due"), "parent_id": args.get("parent_id"),
            "goal_id": args.get("goal_id") or None}
    for field in ("labels", "top", "links", "next_run"):
        if args.get(field) not in (None, "", [], False):
            body[field] = args[field]
    if args.get("dry_run"):
        return api.post("tasks/dry-run", body)
    return api.post("tasks", body, key=_key(args))


@tool("hub_task_show", "One task with its history and conversation.", {"id": _s("Task id")}, required=("id",))
def task_show(api, args):
    return api.get("tasks/" + args["id"])


@tool("hub_task_stuck", "BotOps's sweep: every bot's open work that has not moved in a day and waits "
      "on nobody (no person owes an answer, no open blocker, no run queued).",
      {"hours": {"type": "integer", "description": "Untouched for at least this many hours (default 24)"}})
def task_stuck(api, args):
    return api.get("tasks/stuck", hours=args.get("hours") or 24)["tasks"]


@tool("hub_task_run", "Start a bot's task now, as the task (its text in the prompt, not a chat). "
      "For a person, the task's requester, or BotOps's sweep.", {"id": _s("Task id")}, required=("id",))
def task_run(api, args):
    return api.post(f"tasks/{args['id']}/run-now", {}, key=_key(args))


@tool("hub_task_list", "Tasks you may see, filtered. Your own come back in queue order: the "
      "first is what to do next.",
      {"owner": _s("Owner: a bot slug, a person id, or `me`"),
       "requester": _s("Requester: a bot slug, a person id, or `me`"),
       "status": {"type": "array", "items": {"type": "string", "enum": list(TASK_STATUSES)},
                  "description": "Only these statuses"},
       "lane": {"type": "string", "enum": ["company", "product"]},
       "label": _s("Only tasks carrying this label")})
def task_list(api, args):
    return api.get("tasks", owner=_target(api, args.get("owner")) if args.get("owner") else None,
                   requester=_target(api, args.get("requester")) if args.get("requester") else None,
                   status=",".join(args["status"]) if args.get("status") else None,
                   lane=args.get("lane") or None, label=args.get("label") or None)["tasks"]


@tool("hub_task_ask", "Ask the task's requester one question that unblocks you. One per task.",
      {"id": _s("Task id"), "text": _s("The question, and only the question")},
      required=("id", "text"), writes=True)
def task_ask(api, args):
    return api.post(f"tasks/{args['id']}/ask", {"text": args["text"]}, key=_key(args))


@tool("hub_task_update", "Move a task you own: status, note, owner, due, labels, or what blocks it. "
      "Finish with `status: done` and a concise result note; the requester closes.",
      {"id": _s("Task id"),
       "status": {"type": "string", "enum": ["open", "doing", "waiting", "review", "done", "declined"]},
       "note": _s("What changed, or the result"),
       "owner": _s("Hand the task to this bot or person"),
       "due": _s("ISO-8601 date-time with timezone"),
       "labels": {"type": "array", "items": {"type": "string"}, "description": "Replace the labels"},
       "blocked_by": _s("The id of the task this one waits on; an empty string clears it"),
       "goal_id": _s("The goal this task serves; an empty string takes it off")},
      required=("id",), writes=True)
def task_update(api, args):
    current = api.get("tasks/" + args["id"])["task"]
    body = {"version": current["version"], "note": args.get("note"), "status": args.get("status"),
            "owner": args.get("owner"), "due": args.get("due"), "goal_id": args.get("goal_id")}
    if args.get("labels") is not None:
        body["labels"] = args["labels"]
    if args.get("blocked_by") is not None:
        body["blocked_by"] = args["blocked_by"]
    return api.post("tasks/" + args["id"], body, key=_key(args))


@tool("hub_task_comment", "Leave a comment on a task: progress, a question for the people on it, "
      "a link to what you found. It is on the record with your name; it is not a chat.",
      {"id": _s("Task id"), "text": _s("The comment")}, required=("id", "text"), writes=True)
def task_comment(api, args):
    return api.post(f"tasks/{args['id']}/comments", {"text": args["text"]}, key=_key(args))


@tool("hub_task_label", "Add or remove labels on a task. A project is a label; so is a kind (bug, front-end).",
      {"id": _s("Task id"),
       "add": {"type": "array", "items": {"type": "string"}, "description": "Labels to add"},
       "remove": {"type": "array", "items": {"type": "string"}, "description": "Labels to remove"}},
      required=("id",), writes=True)
def task_label(api, args):
    current = api.get("tasks/" + args["id"])["task"]
    labels = [x for x in current.get("labels") or []]
    drop = {str(x).strip().lower() for x in args.get("remove") or []}
    labels = [x for x in labels if x not in drop]
    for x in args.get("add") or []:
        x = str(x).strip().lower()
        if x and x not in labels:
            labels.append(x)
    return api.post("tasks/" + args["id"], {"version": current["version"], "labels": labels}, key=_key(args))


@tool("hub_task_link", "Attach a link to a task: the pull request you opened (this is what moves a "
      "product task to In review and on to Shipped), an issue, a document, a page.",
      {"id": _s("Task id"), "url": _s("The URL"), "title": _s("A short name; a pull request needs none")},
      required=("id", "url"), writes=True)
def task_link(api, args):
    return api.post(f"tasks/{args['id']}/links", {"url": args["url"], "title": args.get("title")}, key=_key(args))


# ----------------------------------------------------------------------------- goals
@tool("hub_goals", "What you are for: your goals in order, the chain of goals above them up to the "
      "company goal, and your reports' goals. Read this before you read a task. `all` is every "
      "live goal in the company.",
      {"owner": _s("Someone else's: a bot slug or a person id; default is yourself"),
       "all": {"type": "boolean", "default": False},
       "status": _s("With `all`: only these, comma-separated (red,yellow,green,done,dropped)")})
def goals(api, args):
    if args.get("all"):
        return api.get("goals", all="1", status=args.get("status") or None)["goals"]
    return api.get("goals", owner=_target(api, args["owner"]) if args.get("owner") else None)


@tool("hub_goal_show", "One goal: its body, KPIs with their latest readings, the goals it serves and "
      "the goals under it, the tasks naming it, and its history.", {"id": _s("Goal id")}, required=("id",))
def goal_show(api, args):
    return api.get("goals/" + args["id"])["goal"]


@tool("hub_goal_create", "Propose a goal for yourself, under a goal you own, or for someone below "
      "you on the org chart. It has no colour until whoever owns the parent gives it one; that is "
      "the acceptance. Only the company owner creates a goal with no parent.",
      {"owner": _s("`me`, a bot slug, or a person id"),
       "title": _s("Plain English: what you are going for"),
       "parent_id": _s("The goal this one serves"),
       "body": _s("What it means, what counts, what does not", default=""),
       "top": {"type": "boolean", "default": False, "description": "Put it first in the owner's order"}},
      required=("owner", "title"), writes=True)
def goal_create(api, args):
    return api.post("goals", {"owner": _target(api, args["owner"]), "title": args["title"],
                              "parent_id": args.get("parent_id"), "body": args.get("body") or "",
                              "top": bool(args.get("top"))}, key=_key(args))["goal"]


@tool("hub_goal_status", "Say how a goal is going: red, yellow or green with one honest sentence; "
      "done when reached, dropped when it stops mattering. The goal's owner, the owner of the goal "
      "it serves, or someone above them.",
      {"id": _s("Goal id"),
       "status": {"type": "string", "enum": list(GOAL_STATUSES)},
       "note": _s("One sentence: why it is this colour")},
      required=("id", "status"), writes=True)
def goal_status(api, args):
    return api.post(f"goals/{args['id']}/status", {"status": args["status"], "note": args.get("note") or ""},
                    key=_key(args))["goal"]


@tool("hub_goal_update", "Edit a goal: title, body, the goal it serves, its owner, or its place in "
      "the owner's order. Moving it is for the parent's owner or someone above.",
      {"id": _s("Goal id"), "title": _s("New title"), "body": _s("New body"),
       "parent_id": _s("The goal it serves; an empty string makes it a company goal"),
       "owner": _s("New owner: a bot slug or a person id"),
       "rank": {"type": "integer", "description": "Position in the owner's order"},
       "top": {"type": "boolean", "default": False}},
      required=("id",), writes=True)
def goal_update(api, args):
    body = {k: args.get(k) for k in ("title", "body", "parent_id", "rank")}
    body["owner"] = _target(api, args["owner"]) if args.get("owner") else None
    body["top"] = bool(args.get("top"))
    return api.post("goals/" + args["id"], body, key=_key(args))["goal"]


@tool("hub_kpi_add", "Add a measure to a goal: what is counted, per what, in which unit, and the "
      "target if there is one. A goal may have none or many.",
      {"goal_id": _s("Goal id"), "name": _s("'booked Calendly demos per two weeks'"),
       "unit": _s("demos, $, %, days missed", default=""),
       "target": {"type": "number", "description": "Optional target"}},
      required=("goal_id", "name"), writes=True)
def kpi_add(api, args):
    return api.post(f"goals/{args['goal_id']}/kpis", {"name": args["name"], "unit": args.get("unit") or "",
                    "target": args.get("target")}, key=_key(args))["kpi"]


@tool("hub_kpi_log", "Log a reading on a KPI: a fact you measured, with when it was true. Anyone may "
      "log one. Mark a guess `estimate`; it renders grey and never counts as measured.",
      {"kpi_id": _s("KPI id"), "value": {"type": "number"},
       "note": _s("Where the number came from", default=""),
       "at": _s("When the value was true, ISO date or date-time; default now"),
       "source": _s("`measured` (default), `estimate`, or a connector name", default="measured")},
      required=("kpi_id", "value"), writes=True)
def kpi_log(api, args):
    return api.post(f"kpis/{args['kpi_id']}/readings", {"value": args["value"], "note": args.get("note") or "",
                    "source": args.get("source") or "measured", "at": args.get("at")}, key=_key(args))["reading"]


@tool("hub_kpi_readings", "Every reading on a KPI, oldest first.", {"kpi_id": _s("KPI id")}, required=("kpi_id",))
def kpi_readings(api, args):
    return api.get(f"kpis/{args['kpi_id']}/readings")


# ----------------------------------------------------------------------------- market
@tool("hub_market_show", "One market entity: its edges both ways, the evidence behind it, and the last ten events.",
      {"id": _s("Entity id, like company/globex")}, required=("id",))
def market_show(api, args):
    return api.get("market/entities/" + args["id"])


@tool("hub_market_find", "Find market entities and evidence by name, alias, summary, quote or our_read.",
      {"text": _s("What to look for")}, required=("text",))
def market_find(api, args):
    return api.get("market/entities", q=args["text"])


@tool("hub_market_edges", "Market edges as rows. Symmetric relations (competes_with, partners_with) are stored once "
      "and returned from either end. as_of keeps edges whose since/until covers that date.",
      {"src": _s("From this entity"), "dst": _s("To this entity"), "rel": _s("One of the sixteen relations"),
       "as_of": _s("YYYY-MM-DD")})
def market_edges(api, args):
    return api.get("market/edges", src=args.get("src"), dst=args.get("dst"), rel=args.get("rel"), as_of=args.get("as_of"))


@tool("hub_market_delta", "What changed in the market graph, grouped by entity.",
      {"since": _s("A date or a window like 7d", default="7d")})
def market_delta(api, args):
    return api.get("market/delta", since=args.get("since") or "7d")


@tool("hub_market_ask", "Ask a question answered from market entities, evidence and market pages. Citations are ids from the graph.",
      {"question": _s("The question")}, required=("question",))
def market_ask(api, args):
    return api.post("market/ask", {"question": args["question"]})


@tool("hub_market_report", "Report a market finding in prose. This does not change an entity or an edge. "
      "urgent wakes the market analyst now.",
      {"kind": {"type": "string", "enum": ["new-entity", "edge", "property-change", "correction", "question", "other"]},
       "about": _s("The name you used"), "claim": _s("What you found, in a sentence"),
       "source_url": _s("Where you read it", default=""), "quote": _s("What the source said", default=""),
       "confidence": {"type": "string", "enum": ["high", "medium", "low"], "default": "medium"},
       "urgent": {"type": "boolean", "default": False},
       "source_ref": _s("Where the finding came from, e.g. the intake item id; one insight per ref")},
      required=("kind", "claim"), writes=True)
def market_report(api, args):
    return api.post("market/insights", {"kind": args["kind"], "about": args.get("about") or "", "claim": args["claim"],
                    "source_url": args.get("source_url") or "", "quote": args.get("quote") or "",
                    "confidence": args.get("confidence") or "medium", "urgent": bool(args.get("urgent")),
                    "source_ref": args.get("source_ref") or None},
                    key=_key(args))


@tool("hub_market_resolve", "Close a market insight: applied, merged, rejected with one sentence, or needs-human.",
      {"id": _s("Insight id"),
       "status": {"type": "string", "enum": ["applied", "merged", "rejected", "needs-human"]},
       "resolution": _s("One sentence"), "applied_events": {"type": "array", "items": {"type": "string"}}},
      required=("id", "status"), writes=True)
def market_resolve(api, args):
    return api.post(f"market/insights/{args['id']}/resolve",
                    {"status": args["status"], "resolution": args.get("resolution") or "",
                     "applied_events": args.get("applied_events") or []}, key=_key(args))


@tool("hub_market_apply", "Curator: write the evidence first, then an entity or an edge that cites it, and mark the insight applied.",
      {"id": _s("Insight id"), "source_url": _s("Source URL", default=""),
       "source_kind": _s("reddit, x, news, site, other", default="other"),
       "quote": _s("What the source said", default=""), "our_read": _s("The curator's sentence", default=""),
       "entity_type": _s("company, person, segment, channel, ..."), "entity_name": _s("Name, when creating an entity"),
       "entity_id": _s("Existing entity to update"), "summary": _s("New summary"),
       "edge_src": _s("Edge source entity"), "edge_rel": _s("One of the sixteen relations"),
       "edge_dst": _s("Edge destination entity")},
      required=("id",), writes=True)
def market_apply(api, args):
    body = {"evidence": {"source_url": args.get("source_url") or "", "source_kind": args.get("source_kind") or "other",
                         "quote": args.get("quote") or "", "our_read": args.get("our_read") or ""}}
    if args.get("entity_type") and args.get("entity_name"):
        body["entity"] = {"type": args["entity_type"], "name": args["entity_name"], "summary": args.get("summary") or ""}
    if args.get("entity_id"):
        body["entity_id"] = args["entity_id"]
        if args.get("summary") is not None:
            body["summary"] = args["summary"]
    if args.get("edge_src") and args.get("edge_rel") and args.get("edge_dst"):
        body["edge"] = {"src": args["edge_src"], "rel": args["edge_rel"], "dst": args["edge_dst"]}
    return api.post(f"market/insights/{args['id']}/apply", body, key=_key(args))


@tool("hub_market_sweep", "Curator: one task on the company owner for every needs-human insight in this run, and a "
      "Listening task only for an entity you mark unverified that is past its verification window.",
      {"today": _s("YYYY-MM-DD; default today"),
       "unverified": {"type": "array", "items": {"type": "object"},
                      "description": "Objects {id, look_for} the curator could not verify"}},
      writes=True)
def market_sweep(api, args):
    return api.post("market/curator/sweep", {"today": args.get("today"), "unverified": args.get("unverified") or []},
                    key=_key(args))


@tool("hub_market_refresh", "Rewrite the weekly market delta from market events. A Monday updates the page; "
      "any other day leaves it as it is. The curator's sweep does this on Mondays.",
      {"today": _s("YYYY-MM-DD; default today")}, writes=True)
def market_refresh(api, args):
    return api.post("market/delta/refresh", {"today": args.get("today")}, key=_key(args))


@tool("hub_market_page", "Curator: rewrite one market page from the graph, whole, in Markdown. `name` is "
      "overview, structure-and-size, coverage-universe, people-who-matter, channels, regulation-and-catalysts, "
      "theses or open-questions; the weekly delta is hub_market_refresh's.",
      {"name": _s("The page, e.g. overview"), "body": _s("The whole page in Markdown")},
      required=("name", "body"), writes=True)
def market_page(api, args):
    return api.post("market/pages/" + args["name"], {"body": args["body"]}, key=_key(args))


# ----------------------------------------------------------------------------- listening, intake
@tool("hub_listen_save", "Listening: save one sweep of one query and every post it saw. status is ok, blocked, "
      "rate_limited or error; anything but ok says what happened in note. A post already saved is not changed.",
      {"source": _s("x, reddit, linkedin, facebook, news, x-bookmarks, reddit-saved, ..."),
       "query": _s("The query or page the sweep read"),
       "status": {"type": "string", "enum": ["ok", "blocked", "rate_limited", "error"]},
       "started_at": _s("ISO time the sweep started; default now"),
       "pages_read": {"type": "integer", "default": 0}, "items_seen": {"type": "integer"},
       "note": _s("What happened, required unless ok", default=""),
       "items": {"type": "array", "items": {"type": "object", "properties": {
           "native_id": _s("The platform's id for the post"), "url": _s("Link to the post"),
           "author": _s("Handle or name as shown"), "author_url": _s("Author profile link"),
           "content": _s("The visible text"), "published_at": _s("ISO time, if shown")},
           "required": ["native_id", "url", "content"]}}},
      required=("source", "query", "status"), writes=True)
def listen_save(api, args):
    body = {k: args[k] for k in ("source", "query", "status", "started_at", "pages_read", "items_seen", "note", "items")
            if args.get(k) is not None}
    return api.post("listening/runs", body, key=_key(args))


@tool("hub_listen_decide", "Listening: put the listening-item decision questions to saved posts that have no decision yet, one "
      "probability per category, and route each post to every inbox whose threshold it clears.",
      {"limit": {"type": "integer", "default": 20}, "item_ids": {"type": "array", "items": {"type": "string"}}},
      writes=True)
def listen_decide(api, args):
    return api.post("listening/judge", {"limit": int(args.get("limit") or 20), "item_ids": args.get("item_ids") or []},
                    key=_key(args))


alias("hub_listen_judge", "hub_listen_decide")


@tool("hub_listen_show", "One saved post: the run that first saw it, every decision, and every inbox it went to.",
      {"id": _s("Saved post id (listen_items.id)")}, required=("id",))
def listen_show(api, args):
    return api.get("listening/items/" + args["id"])


@tool("hub_listen_runs", "Listening's sweeps, newest first, with their status: tells no results from blocked.",
      {"since": _s("ISO date or time"), "source": _s("x, reddit, linkedin, ...")})
def listen_runs(api, args):
    return api.get("listening/runs", since=args.get("since"), source=args.get("source"))


@tool("hub_listen_stats", "Coverage by source and status, and accepted/rejected counts and precision by inbox.",
      {"since": _s("ISO date or time; default seven days ago")})
def listen_stats(api, args):
    return api.get("listening/stats", since=args.get("since"))


@tool("hub_intake_list", "Posts Listening routed to your inbox, oldest first, with the post, the scores and why "
      "it was routed. Resolve each one with hub_intake_resolve.",
      {"destination": _s("An inbox name from the company's registry/listening.yaml; default yours"),
       "status": {"type": "string", "enum": ["new", "accepted", "rejected", "duplicate"], "default": "new"},
       "limit": {"type": "integer", "default": 100}})
def intake_list(api, args):
    return api.get("intake", destination=args.get("destination"), status=args.get("status") or "new",
                   limit=args.get("limit") or 100)


@tool("hub_intake_resolve", "Your verdict on an inbox item: accepted with the id of the record you made, duplicate "
      "with the id it duplicates, or rejected with one sentence why.",
      {"id": _s("Intake item id"), "status": {"type": "string", "enum": ["accepted", "rejected", "duplicate"]},
       "receiver_ref": _s("The record you created or the one it duplicates", default=""),
       "reason": _s("One sentence; required when rejected", default="")},
      required=("id", "status"), writes=True)
def intake_resolve(api, args):
    return api.post(f"intake/{args['id']}/resolve", {"status": args["status"],
                    "receiver_ref": args.get("receiver_ref") or "", "reason": args.get("reason") or ""},
                    key=_key(args))


@tool("hub_task_attach", "Attach a deliverable (a report, a draft) to a task so the people on it "
      "can open it in Tico. Returns the link to put in your note; never link a path on your "
      "Mac or an s3:// URI. Send the text as-is, or content_base64 for a binary file.",
      {"id": _s("Task id"),
       "name": _s("File name with its extension, e.g. 2026-09-15-draft-review.md"),
       "text": _s("The file's text, for a text or Markdown file"),
       "content_base64": _s("The file's bytes, base64-encoded, for anything that is not text")},
      required=("id", "name"), writes=True)
def task_attach(api, args):
    body = {"name": args["name"]}
    for field in ("text", "content_base64"):
        if args.get(field) is not None:
            body[field] = args[field]
    return api.post(f"tasks/{args['id']}/files", body, key=_key(args))


# ----------------------------------------------------------------------------- files
# What a bot publishes so people find it on the bot's page (docs/files.md). The bot is the caller:
# no tool takes a bot argument for a write, and only a bot's own files can be written.
def _files_fields(args, *names):
    return {n: args[n] for n in names if args.get(n)}


@tool("hub_files_list", "The files on your page (or another bot's, if you may see it), newest activity first: "
      "id, title, kind, where each opens and when it last changed.",
      {"bot": _s("Bot slug; defaults to you"), "limit": {"type": "integer", "minimum": 1, "maximum": 100},
       "cursor": _s("next_cursor from the previous page")})
def files_list(api, args):
    slug = args.get("bot") or str(api.get("me")["actor"]).split(":", 1)[-1]
    return api.get(f"bots/{slug}/files", limit=args.get("limit"), cursor=args.get("cursor"))


@tool("hub_files_publish", "Publish a file you created or changed so people can open it from your page: "
      "a report, a draft, a spreadsheet. Send its text, or content_base64 for a binary file (up to about 1.4 MB "
      "here; `hub files publish <path>` sends up to 25 MB). Publishing the same name again adds a version. "
      "Documents, images, csv, json, md, html, pdf and office files only; never credentials.",
      {"name": _s("File name with its extension, e.g. 2026-09-15-pipeline-review.md"),
       "text": _s("The file's text"), "content_base64": _s("The bytes, base64-encoded, for anything not text"),
       "title": _s("What people see; defaults to the name"),
       "task": _s("The task this is for; defaults to the task you are working on"),
       "scope": {"enum": ["task", "bot"], "description": "bot makes it visible to everyone who sees this bot "
                 "(refused from inside a private chat)"},
       "path": _s("The file's path in your repository, so an edit later is the same file")},
      required=("name",), writes=True)
def files_publish(api, args):
    body = _files_fields(args, "name", "text", "content_base64", "title", "task", "scope", "path")
    return api.post("files/uploads", body, key=_key(args))


@tool("hub_files_add-link", "List a document you created or edited in another tool (a Google Doc, Sheet or "
      "Slides, a Notion page, a Figma file, any https link) on your page. Tico keeps the address, never the "
      "document; whoever opens it needs access there. Adding it again, or `hub_files_touch`, moves it to the top.",
      {"url": _s("An https:// link"), "title": _s("What people see"), "task": _s("The task it is for"),
       "scope": {"enum": ["task", "bot"]}}, required=("url",), writes=True)
def files_add_link(api, args):
    return api.post("files/links", _files_fields(args, "url", "title", "task", "scope"), key=_key(args))


@tool("hub_files_touch", "Say you edited a linked document again, so it moves to the top of your files. "
      "Give its file id or its https link.", {"target": _s("A file id or an https:// link")}, required=("target",),
      writes=True)
def files_touch(api, args):
    target = str(args["target"])
    return api.post("files/links", {"url": target} if target.startswith("https://") else {"file": target},
                    key=_key(args))


@tool("hub_files_import", "Copy an S3 object into Tico so people can open it. Only where the bot's own computer "
      "runs the tool (the `hub files import` command): it reads the object with the credentials that computer "
      "has, within the size and type limits.",
      {"uri": _s("s3://bucket/key"), "title": _s("What people see"), "task": _s("The task it is for")},
      required=("uri",), writes=True)
def files_import(api, args):
    from clients import bot_files as BF
    from clients.tico import Client
    if not isinstance(api, Client):
        return {"refused": "import", "detail": "Run `hub files import` on the bot's computer; the hub never "
                "reads your buckets with its own credentials."}
    try:
        name, _, data, etag = BF.fetch_s3(args["uri"], client=args.get("_s3"))
    except BF.Refused as exc:
        return {"refused": "import", "detail": str(exc)}
    query = {"source": args["uri"], "etag": etag, "name": name, **_files_fields(args, "title", "task")}
    return api.request("POST", "/api/v2/files/imports?" + BF.urlencode(query), raw=data, key=_key(args))


def files_publish_path(client, args):
    """`hub files publish <path>`: the CLI reads the file (inside this checkout only) and sends the bytes."""
    from clients import bot_files as BF
    try:
        name, _, data, relative = BF.read_local(BF.checkout_root(), args["path"])
    except BF.Refused as exc:
        return {"refused": "file", "detail": str(exc)}
    query = {"name": name, "path": relative, **_files_fields(args, "title", "task", "scope")}
    commit = BF.pushed_commit(BF.checkout_root(), relative)
    if commit:
        query["commit"] = commit
    return client.request("POST", "/api/v2/files/uploads?" + BF.urlencode(query), raw=data, key=_key(args))


@tool("hub_task_close", "Close a task you requested. Never close a task you did not request.",
      {"id": _s("Task id"), "note": _s("Why it is closed")}, required=("id",), writes=True)
def task_close(api, args):
    current = api.get("tasks/" + args["id"])["task"]
    return api.post("tasks/" + args["id"], {"version": current["version"], "note": args.get("note"),
                                            "close": True}, key=_key(args))


@tool("hub_history", "What was said in a conversation, oldest first, 200 a page: the way a bot reads "
      "back past what its own session holds. The turn prompt names the conversation.",
      {"conversation": _s("Conversation id"), "before": _s("The page before this message id"),
       "since": _s("Only messages after this message id")}, required=("conversation",))
def history(api, args):
    page = api.get(f"conversations/{args['conversation']}/messages", before=args.get("before"), since=args.get("since"))
    return {"conversation": page.get("conversation"), "messages": page.get("messages", [])}


# ----------------------------------------------------------------------------- routines
def _bot_of(api, args):
    return args.get("bot") or api.get("me")["actor"].split(":", 1)[-1]


@tool("hub_routine_list", "The routines a bot runs on a schedule: what it is told, and when. "
      "Yours unless `bot` is given.", {"bot": _s("Another bot's slug")})
def routine_list(api, args):
    return api.get(f"bots/{_bot_of(api, args)}/routines")["routines"]


@tool("hub_routine_set", "Create a routine, or update the one with this key. The hub opens a "
      "task with `text` each time it is due; a bot sets up its own, an operator sets a bot's. "
      "Give `cron` (five fields, in `timezone`) or `on` (a hub event), never both.",
      {"key": _s("A stable name: letters, digits, dots, dashes or underscores"),
       "title": _s("What the task is called"),
       "text": _s("What the bot is told each time", default=""),
       "cron": _s("Five-field cron, e.g. `0 7 * * 1-5`"),
       "on": _s("A hub event instead of a time: `recording.ready`"),
       "timezone": _s("IANA zone for the cron; America/Los_Angeles by default"),
       "enabled": {"type": "boolean", "default": True},
       "bot": _s("Set it on another bot you operate; yourself by default")},
      required=("key", "title"), writes=True)
def routine_set(api, args):
    body = {"key": args["key"], "title": args["title"], "text": args.get("text") or "",
            "cron": args.get("cron") or "", "on": args.get("on") or "", "timezone": args.get("timezone") or "",
            "enabled": args.get("enabled", True)}
    return api.post(f"bots/{_bot_of(api, args)}/routines", body, key=_key(args))["routine"]


@tool("hub_routine_update", "Change one routine by id: title, text, cron, on, timezone or enabled.",
      {"id": _s("Routine id from hub_routine_list"), "title": _s("New title"), "text": _s("New text"),
       "cron": _s("New five-field cron"), "on": _s("New event"), "timezone": _s("New zone"),
       "enabled": {"type": "boolean"}},
      required=("id",), writes=True)
def routine_update(api, args):
    body = {k: args.get(k) for k in ("title", "text", "cron", "on", "timezone", "enabled")}
    return api.post(f"routines/{args['id']}", body, key=_key(args))["routine"]


@tool("hub_routine_delete", "Delete a routine. Its history stays; an occurrence nobody has "
      "claimed yet closes.", {"id": _s("Routine id")}, required=("id",), writes=True)
def routine_delete(api, args):
    return api.post(f"routines/{args['id']}/delete", {}, key=_key(args))["routine"]


@tool("hub_bot_set", "BotOps only: apply a person's bot-settings request (reports to, name, "
      "description, status) as that person, citing the message they sent you. The server checks "
      "the change with their own permissions and refuses a message older than a week.",
      {"slug": _s("The bot to change"), "on_behalf_of": _s("Id of the person's message to BotOps asking for it"),
       "reports_to": _s("A bot slug, or human:<id>"), "display_name": _s("New display name"),
       "description": _s("New description"), "status": {"type": "string", "enum": ["active", "paused", "planned"]}},
      required=("slug", "on_behalf_of"), writes=True)
def bot_set(api, args):
    row = next((b for b in api.get("bots") if (b.get("slug") or b.get("name")) == args["slug"]), None)
    if not row:
        raise ValueError("No bot " + args["slug"])
    change = {k: args[k] for k in ("reports_to", "display_name", "description", "status") if args.get(k) is not None}
    return api.post(f"bots/{args['slug']}/definition",
                    {**change, "expected_revision": row["revision"], "on_behalf_of": args["on_behalf_of"]}, key=_key(args))


# ----------------------------------------------------------------------------- approvals
@tool("hub_approval_request", "Ask a person for a yes or no on one exact action. Only a person "
      "decides; an approval is spent once. If the owner already told you in Tico to send a "
      "specific email, do not request another approval: `mail send --approve <their-message-id>` "
      "(that message's id). A decided send approval id works as --approve too.",
      {"kind": {"type": "string", "enum": list(APPROVAL_KINDS)},
       "payload": {"type": "object", "description": "The exact action, as the approvals policy describes. "
                   "kind=send is to/cc/subject/body_sha256/mailbox. Skip this tool when the owner "
                   "already said send; use mail send --approve <their-message-id>."},
       "task_id": _s("The task this action belongs to")},
      required=("kind", "payload"), writes=True)
def approval_request(api, args):
    return api.post("approvals", {"kind": args["kind"], "payload": args["payload"],
                                  "task_id": args.get("task_id")}, key=_key(args))


@tool("hub_approval_show", "One approval and its decision.", {"id": _s("Approval id")}, required=("id",))
def approval_show(api, args):
    return api.get("approvals/" + args["id"])


# ----------------------------------------------------------------------------- status, activity
@tool("hub_status_set", "One factual line about what you are doing now.",
      {"focus": _s("What you are working on"),
       "state": _s("idle, running, waiting_human, waiting_bot, blocked"),
       "task_id": _s("The task this is about"),
       "bot": _s("Another bot you operate; default is yourself")},
      required=("focus",), writes=True)
def status_set(api, args):
    bot = args.get("bot") or api.get("me")["actor"].split(":", 1)[-1]
    return api.post(f"bots/{bot}/status", {"state": args.get("state"), "focus": args["focus"],
                                           "task_id": args.get("task_id")}, key=_key(args))


@tool("hub_org", "The company org chart: who each person is, how to reach them (email, Slack, "
      "phone), what they own, their goals, and which bots hang under them. Use this to find who "
      "handles a kind of work before you file a task or ping someone.",
      {"person": _s("Optional person id: that person and everyone under them"),
       "team": _s("Optional team name: a team name from the registry, like engineering or sales")})
def org(api, args):
    return api.get("org", person=args.get("person") or None, team=args.get("team") or None)


@tool("hub_recent", "The bots you (a person) have been working with lately, most recent first: each "
      "with its live status and what it is working on, the last thing you said and the last thing it "
      "said, the conversation id to read on with hub_history, your open tasks together, and what it "
      "needs from you. Start here to pick up where you left off.",
      {"days": {"type": "integer", "minimum": 1, "maximum": 90, "description": "How far back (default 7)"},
       "limit": {"type": "integer", "minimum": 1, "maximum": 30, "description": "At most this many bots (default 10)"}})
def recent(api, args):
    return api.get("me/recent", days=args.get("days") or 7, limit=args.get("limit") or 10)


# ----------------------------------------------------------------------------- grok bot sync
_GROK_MESSAGE = {"type": "object", "additionalProperties": False, "required": ["role", "text"], "properties": {
    "role": _s("user (the person) or bot (the Grok Bot)", enum=["user", "bot"]),
    "text": _s("The message, verbatim"),
    "at": _s("When it was sent, ISO 8601"),
    "id": _s("Grok's id for the message, if you have one"),
    "images": {"type": "array", "maxItems": 10, "description": "Images shown in this message: each a public "
               "https `url` Tico can download, or for a file on your computer `content_base64` (under 5 MB) "
               "with a `name`. Tico stores them and shows them inline.",
               "items": {"type": "object", "additionalProperties": False, "properties": {
                   "url": _s("The image's https address"), "name": _s("A file name, e.g. poster.png"),
                   "content_base64": _s("The image itself, base64")}}}}}
_GROK_BOT = {"type": "object", "additionalProperties": False, "required": ["grok_id", "name"], "properties": {
    "grok_id": _s("The Grok Bot's id (the uuid in grok.com/bot/<id>)"),
    "name": _s("Its name in Grok"),
    "description": _s("Its short description"),
    "instructions": _s("Its full instructions, verbatim"),
    "messages": {"type": "array", "maxItems": 500, "items": _GROK_MESSAGE,
                 "description": "Transcript messages newer than the synced_through the last sync returned "
                                "(all of them the first time), oldest first"}}}


@tool("hub_grokbot_sync", "Sync your (a person's) Grok Bots into Tico. A Bot Tico has not seen becomes a "
      "bot under you on the Org chart; its name, description and full instructions are kept, and its "
      "transcript is copied into your chat with it. Idempotent: resending messages adds nothing. Each "
      "bot in the reply has `synced_through`, the newest message Tico has; next time send only newer ones.",
      {"bots": {"type": "array", "minItems": 1, "maxItems": 50, "items": _GROK_BOT},
       "source": _s("Which of your Bots ran this sync")},
      required=("bots",), writes=True)
def grokbot_sync(api, args):
    return api.post("grokbot/sync", {k: v for k, v in (("bots", args["bots"]), ("source", args.get("source")))
                                     if v is not None}, key=_key(args))


# ----------------------------------------------------------------------------- updates
@tool("hub_update_post", "Post your daily update (or, on Friday, your week in review) when the hub asks "
      "for it: one to five markdown bullets in plain English and nothing else. No title, no headings or "
      "sections, no task ids. At most 25 words a bullet and 90 in all (Friday: 40 and 180); an update that "
      "breaks this is refused with how to fix it. One a day; posting again replaces it.",
      {"body": _s("One to five lines, each starting with '- '"),
       "kind": _s("daily or weekly; the hub picks from the day when omitted", enum=["daily", "weekly"])},
      required=("body",), writes=True)
def update_post(api, args):
    return api.post("updates", {k: v for k, v in (("body", args["body"]), ("kind", args.get("kind"))) if v is not None},
                    key=_key(args))["update"]


@tool("hub_updates", "The bots' updates, newest first, with your read state: what each bot did, does "
      "next and needs from you. `unread` for what you have not read; `missed` lists bots that did not report.",
      {"kind": _s("daily or weekly", enum=["daily", "weekly"]), "bot": _s("One bot's updates"),
       "unread": {"type": "boolean", "description": "Only what you have not read"},
       "before": _s("Older than this created time (paging)"),
       "limit": {"type": "integer", "minimum": 1, "maximum": 100}})
def updates_list(api, args):
    return api.get("updates", kind=args.get("kind"), bot=args.get("bot"),
                   unread=("true" if args.get("unread") else None), before=args.get("before"), limit=args.get("limit"))


@tool("hub_update_show", "One update in full with its thread: your replies and the bot's answers.",
      {"update": _s("Update id")}, required=("update",))
def update_show(api, args):
    return api.get("updates/" + args["update"])


@tool("hub_update_read", "Mark updates read (or unread again) for you.",
      {"ids": {"type": "array", "items": {"type": "string"}, "description": "Update ids"},
       "all": {"type": "boolean", "description": "Every update of the last 30 days"},
       "read": {"type": "boolean", "description": "false marks them unread again (default true)"}}, writes=True)
def update_read(api, args):
    return api.post("updates/read", {"ids": args.get("ids") or [], "all": bool(args.get("all")),
                                     "read": args.get("read", True) is not False}, key=_key(args))


@tool("hub_update_reply", "Reply to a bot's update: it shows under the update and goes to the bot's chat "
      "as a message, so the bot answers there.",
      {"update": _s("Update id"), "text": _s("Your reply")}, required=("update", "text"), writes=True)
def update_reply(api, args):
    return api.post("updates/" + args["update"] + "/reply", {"text": args["text"]}, key=_key(args))


@tool("hub_update_settings", "Turn a bot's daily or weekly update on or off (the bot, its operator, "
      "a manager or the owner).",
      {"bot": _s("Bot slug"), "daily": {"type": "boolean"}, "weekly": {"type": "boolean"}}, required=("bot",), writes=True)
def update_settings(api, args):
    flag = lambda v: v if isinstance(v, bool) else str(v).lower() in ("on", "true", "1", "yes")
    return api.post("bots/" + args["bot"] + "/updates",
                    {k: flag(args[k]) for k in ("daily", "weekly") if args.get(k) is not None}, key=_key(args))


@tool("hub_status_list", "Every bot you may see with its live status.",
      {"team": _s("Only this team")})
def status_list(api, args):
    return [b for b in api.get("bots") if not args.get("team") or b.get("team") == args["team"]]


@tool("hub_status_history", "A bot's status history.",
      {"bot": _s("Bot slug"), "since": _s("Window like `7d` or an ISO timestamp")}, required=("bot",))
def status_history(api, args):
    return api.get(f"bots/{args['bot']}/history", since=args.get("since"))


@tool("hub_turns", "A bot's recent turns.",
      {"bot": _s("Bot slug"), "since": _s("Window like `24h` or an ISO timestamp")}, required=("bot",))
def turns(api, args):
    return api.get(f"bots/{args['bot']}/turns", since=args.get("since"))


@tool("hub_inbox", "Messages and notices waiting for you.", {})
def inbox(api, args):
    return api.get("inbox")


@tool("hub_ack", "Mark a message from your inbox as read. A runner turn does this for you; an "
      "external agent (a Hermes profile) reads its inbox itself and acknowledges what it has handled.",
      {"message_id": _s("The message id from hub_inbox")}, required=("message_id",), writes=True)
def ack(api, args):
    return api.post("messages/" + args["message_id"] + "/ack", {}, key=_key(args))


@tool("hub_board", "Every task and bot you may see.", {})
def board(api, args):
    return {"tasks": api.get("tasks")["tasks"], "bots": api.get("bots")}


@tool("hub_fleet", "Tico's actor-scoped live snapshot of the fleet.", {})
def fleet(api, args):
    return api.get("tico/fleet")


# ----------------------------------------------------------------------------- the Assistant
@tool("hub_assistant_propose", "Assistant only: ask the person you are acting for to confirm something with "
      "side effects that matter: approving or declining a Needs-you item, anything that leaves the company, "
      "spending, changing people, access or settings, archiving or deleting, activating a bot. Give the exact "
      "API operation; it is shown to them as a Confirm / Cancel card and runs only when they click, as them. "
      "Never do these yourself; nothing here runs until they confirm.",
      {"summary": _s("One plain sentence saying what will happen if they confirm"),
       "method": {"enum": ["POST", "PUT", "PATCH", "DELETE"], "default": "POST"},
       "path": _s("The API path, e.g. /api/v2/approvals/<id> or /api/v2/messages/<id>/answer"),
       "body": {"type": "object", "description": "The JSON body of that request"}},
      required=("summary", "path"), writes=True)
def assistant_propose(api, args):
    return api.post("assistant/actions", {"summary": args["summary"], "method": args.get("method") or "POST",
                                          "path": args["path"], "body": args.get("body") or {}}, key=_key(args))


# ----------------------------------------------------------------------------- sql, integrations
@tool("hub_sql", "Read-only SQL over what you may see (docs/hub-sql.md). One SELECT, WITH or "
      "EXPLAIN QUERY PLAN; bind `:key` with `params`.",
      {"sql": _s("The statement"),
       "params": {"type": "object", "description": "Named bindings"},
       "max_rows": {"type": "integer", "minimum": 1, "description": "At most this many rows"}},
      required=("sql",))
def sql(api, args):
    body = {"sql": args["sql"], "params": args.get("params") or {}}
    if args.get("max_rows"):
        body["max_rows"] = int(args["max_rows"])
    return api.post("sql", body)


# ----------------------------------------------------------------------------- calendar
@tool("hub_calendar_upcoming", "Read upcoming appointments on a company calendar. Every bot may "
      "use this tool. The default is the company owner's calendar; pass `calendar` for your "
      "operator's. "
      "Results are the Hub's provider-normalized snapshot and include its freshness.",
      {"calendar": _s("Roster email whose calendar to read; default the company owner's",
                       default="")})
def calendar_upcoming(api, args):
    return api.get("calendar/appointments", calendar=args.get("calendar") or None)


@tool("hub_calendar_schedule", "Schedule an appointment on a company calendar. Every bot may use "
      "this tool without a separate permission grant. The Hub queues one idempotent provider "
      "action; attendees receive the invitation when the connector completes it. Use "
      "hub_calendar_status before claiming success.",
      {"calendar": _s("Roster email whose calendar owns the event; default the company owner's",
                       default=""),
       "title": _s("Calendar event title"),
       "start": _s("ISO-8601 start with timezone, for example 2026-09-22T09:00:00-07:00"),
       "end": _s("ISO-8601 end with timezone"),
       "attendees": {"type": "array", "items": {"type": "string"},
                     "description": "Email addresses to invite; may be empty for a private hold"},
       "description": _s("Optional attendee-visible event description", default=""),
       "add_meet": {"type": "boolean", "default": True,
                    "description": "Create a Google Meet link"}},
      required=("title", "start", "end"), writes=True)
def calendar_schedule(api, args):
    return api.post("calendar/appointments", {
        "calendar": args.get("calendar") or "", "title": args["title"],
        "start": args["start"], "end": args["end"],
        "attendees": args.get("attendees") or [], "description": args.get("description") or "",
        "add_meet": args.get("add_meet", True),
    }, key=_key(args))


@tool("hub_calendar_status", "Check a queued calendar scheduling action. `succeeded` means the "
      "event exists; `pending` or `running` is not confirmation; `unknown` requires inspection "
      "before any retry.", {"id": _s("Action id returned by hub_calendar_schedule")},
      required=("id",))
def calendar_status(api, args):
    return api.get("calendar/actions/" + args["id"])


@tool("hub_github_create-bot-repo", "Owner or the BotOps bot: create the private repository emp-<slug> in the "
      "connected GitHub organization from a template (default ticoteam/botops), or empty when the bot's "
      "repository already exists on a computer. Answers with how to create it by hand when the company's "
      "GitHub App was not given permission to.",
      {"slug": _s("The bot's name, e.g. sales for emp-sales"),
       "template": _s("Template repository as owner/name; default ticoteam/botops"),
       "empty": {"type": "boolean", "description": "Create an empty private repository (no template) to push an existing history into"}},
      required=("slug",), writes=True)
def github_create_bot_repo(api, args):
    body = {"slug": args["slug"], "empty": True} if args.get("empty") else \
        {"slug": args["slug"], "template": args.get("template") or "ticoteam/botops"}
    return api.post("github/repos", body, key=_key(args))


@tool("hub_integrations", "Every outside system, and what you need to use it: how you reach it "
      "(`access`), the credentials or env names, how it is declared, writes, and query/learning "
      "counts. Read this list before touching an outside system; `hub_integration` is the full page.", {})
def integrations(api, args):
    return api.get("integrations")


@tool("hub_integration", "One integration's page: how you reach it, what you may do, its "
      "queries and the learnings. Read it before using an outside system.",
      {"service": _s("Integration name")}, required=("service",))
def integration(api, args):
    return api.get("integrations/" + args["service"])


@tool("hub_queries", "Search an integration's ready-made query catalog, or fetch one by id.",
      {"service": _s("Integration name"),
       "term": _s("Words to match against id, title, description, tags and SQL", default=""),
       "id": _s("One query id: returns its SQL and params")},
      required=("service",))
def queries(api, args):
    return api.get(f"integrations/{args['service']}/queries", term=args.get("term") or None,
                   id=args.get("id"))


@tool("hub_learn", "Add a reusable learning about an integration: a limit, a working command, a gotcha.",
      {"service": _s("Integration name"), "text": _s("The learning")},
      required=("service", "text"), writes=True)
def learn(api, args):
    return api.post(f"integrations/{args['service']}/learnings", {"text": args["text"]}, key=_key(args))


@tool("hub_catalog", "The bot templates this company can pick from, with the instructions onboarding filled in.", {})
def catalog(api, args):
    return api.get("catalog")["cards"]


@tool("hub_decisions", "Ask the decision model (optionally TypeSafe's Jev; the question format matches OpenRouter's Decisions API) typed questions about a JSON state and get a "
      "calibrated answer per question, in one round trip, with no prose: `choice` picks one of named "
      "options (criteria: {name: description}) and answers {choice, confidence, probabilities}; `score` "
      "places the state on ordered levels (criteria: [level, ...]) and answers {score, confidence}; "
      "`noul` answers {noul: probability the statement is true}. Use it for a decision (classify, route, "
      "dedupe, gate, rank, select a value from candidates), never for writing. Ask every question the "
      "decision needs in one call (they run in parallel, up to 40) and read the answers your code needs. "
      "The shared question sets are questions/*.json in the hub checkout; send one's `questions` and its "
      "`id@version` as the label so the audit groups the calls. skills/decisions/SKILL.md says how to write "
      "a state and a question and how to act on confidence.",
      {"state": {"description": "What the decision is about: any JSON (an object of named fields reads best; "
                                "questions name the fields in backticks). Send data, not instructions; the "
                                "questions carry the instructions.",
                 "type": ["object", "array", "string"]},
       "questions": {"type": "object", "description": "id -> {type: choice|score|noul, instructions, criteria}; "
                     "instructions and criteria entries are a string or JSON structure (null for an option with "
                     "no description)",
                     "additionalProperties": {"type": "object"}},
       "label": _s("How this call is grouped in the audit: a question set's id@version, or a short name")},
      required=("state", "questions"))
def decisions(api, args):
    body = {"state": args["state"], "questions": args["questions"]}
    if args.get("label"):
        body["label"] = args["label"]
    return api.post("judge", body)


alias("hub_judge", "hub_decisions")


# ----------------------------------------------------------------------------- a person's batch
# What needs a person, frozen, walked one item at a time; responses collected and applied together
# on commit (backend/batch.py). These are a person's tools: a bot calling them is refused.
@tool("hub_live_brief", "Catch the person up in one call, for talking on the go: bots that are down "
      "(`alerts`), who is waiting on them and how many items (`lineup`), how many bots replied to "
      "something they said (`replies_waiting`), the latest things bots said to them (`said`, since "
      "`since`, default 12 hours) and how many bot tasks are stuck. Call it first in a voice "
      "session and again when they ask what's new; pass the previous reply's `now` as `since`.",
      {"since": _s("ISO date-time with timezone; only what bots said after it")})
def live_brief(api, args):
    return spoken(api.get("live/brief" + (f"?since={args['since']}" if args.get("since") else "")))


@tool("hub_live_stats", "How outside assistants' tool calls perform, per tool: calls, median and p90 "
      "server time, answer size, errors. For tuning the on-the-go setup.",
      {"days": {"type": "integer", "description": "Look back this many days (default 7)"},
       "via": _s("Only one assistant's calls, by its token label, e.g. grok-bot")})
def live_stats(api, args):
    query = "&".join(f"{k}={args[k]}" for k in ("days", "via") if args.get(k))
    return api.get("live/stats" + (f"?{query}" if query else ""))


# What a voice assistant reads aloud: every token it reads is a delay before it speaks (so answers stay small). The full text stays one hub_task_show away.
SPOKEN_CLIP = {"answer": 1200, "question": 700, "body": 500, "payload": 500, "note": 200}


def _clip(text, n):
    text = str(text or "")
    return text if len(text) <= n else text[:n - 1].rstrip() + "…"


def spoken(view):
    if not isinstance(view, dict):
        return view
    item = view.get("item")
    if isinstance(item, dict):
        item = {k: v for k, v in item.items() if k not in ("rank", "created")}
        clipped = False
        for field, n in SPOKEN_CLIP.items():
            if isinstance(item.get(field), str) and len(item[field]) > n:
                item[field], clipped = _clip(item[field], n), True
        if clipped and str(item.get("key", "")).startswith("task:"):
            item["more"] = "Clipped for speaking; hub_task_show has the full text."
        view = {**view, "item": item}
    if isinstance(view.get("lineup"), list):
        view = {**view, "lineup": [{**g, "top": _clip(g.get("top"), 90)} for g in view["lineup"]]}
    return view


@tool("hub_batch_start", "Who needs the person, one bot at a time. Call it when they ask who needs them, "
      "what is next, or to go through their list. Starts the batch of the bot that most needs them "
      "(or resumes the batch in progress) and returns `lineup` (every bot waiting on them, most "
      "important first), the count and the first item. Walk it with hub_batch_next and "
      "hub_batch_respond, read the summary back, hub_batch_commit on a clear yes, then offer "
      "the commit's `up_next`. Everything the person says about a bot's items goes to that bot.",
      {"bot": _s("Only this bot's items (a slug); omit for the bot that most needs them. The "
                 "person's own tasks are not in a batch: hub_task_list lists them"),
       "all": {"type": "boolean", "description": "Every item from every bot in one batch instead."},
       "fresh": {"type": "boolean", "description": "Drop the batch in progress and build a new list."}},
      writes=True)
def batch_start(api, args):
    if args.get("fresh"):
        open_ = (api.get("batch") or {}).get("batch")
        if open_:
            api.post("batch/" + open_["id"] + "/abandon", {}, key=_key({**args, "operation_id": None}))
    body = {} if args.get("all") else {"bot": args.get("bot") or "next"}
    return spoken(api.post("batch", body, key=_key(args)))


@tool("hub_batch_next", "The next item of the batch; at the end, the summary to read back before committing.",
      {"batch": _s("The batch id")}, required=("batch",), writes=True)
def batch_next(api, args):
    return spoken(api.post("batch/" + args["batch"] + "/next", {}, key=_key(args)))


@tool("hub_batch_respond", "Record the person's response to the current item (or another, by number). "
      "Nothing is applied until commit.",
      {"batch": _s("The batch id"),
       "kind": _s("decide | needs_info | instruct | rule | skip | later", enum=["decide", "needs_info", "instruct", "rule", "skip", "later"]),
       "text": _s("The person's own words"),
       "decision": _s("With decide: approve | decline | done | close | answer", enum=["approve", "decline", "done", "close", "answer"]),
       "item": {"type": "integer", "description": "Another item's number"},
       "until": _s("With later: an ISO date-time")},
      required=("batch", "kind"), writes=True)
def batch_respond(api, args):
    body = {k: args[k] for k in ("kind", "text", "decision", "item", "until") if args.get(k) not in (None, "")}
    return api.post("batch/" + args["batch"] + "/respond", body, key=_key(args))


@tool("hub_batch_commit", "Apply every recorded response of the batch. Only after the person confirmed the "
      "summary. Decisions apply as the person; questions, instructions and rules go to the bot each item "
      "came from, whose reply comes back on those items. Returns `up_next`: the next bot to offer.",
      {"batch": _s("The batch id")}, required=("batch",), writes=True)
def batch_commit(api, args):
    return api.post("batch/" + args["batch"] + "/commit", {}, key=_key(args))


@tool("hub_batch_abandon", "Drop the batch in progress without applying anything. Its responses are lost; "
      "the items come back in the next batch.",
      {"batch": _s("The batch id")}, required=("batch",), writes=True)
def batch_abandon(api, args):
    return api.post("batch/" + args["batch"] + "/abandon", {}, key=_key(args))


# `hub` commands with no tool: they write the Mac's own workspace (`clients/catalog.py`), which
# the hub cannot reach, so BotOps runs them in a shell. Everything else is in both doors.
# `hub_db` runs where the database credential is, on the runner; the server's MCP endpoint
# has neither the credential nor any business connecting to a company database.
SHELL_ONLY = {"hub_bot_create", "hub_bot_check", "hub_db"}
BY_NAME = {t["name"]: t for t in TOOLS}


def query_search(queries, term):
    """Every query whose id, title, description, category, tags or SQL carries every word of `term`."""
    words = str(term or "").lower().split()

    def text(q):
        return " ".join([q["id"], q["title"], q.get("description", ""), q.get("category", ""),
                         " ".join(q.get("tags") or []), q.get("sql") or json.dumps(q.get("mongo"))]).lower()
    return [q for q in queries if all(w in text(q) for w in words)]


def listing():
    """`tools/list` payload: the public fields of every tool."""
    return [{"name": t["name"], "description": t["description"], "inputSchema": t["inputSchema"]}
            for t in TOOLS]


def error_payload(exc):
    """The shape the `hub` CLI prints for an API refusal or failure, so both clients read alike."""
    return {"error": getattr(exc, "code", type(exc).__name__),
            "detail": getattr(exc, "detail", str(exc)),
            "retryable": bool(getattr(exc, "retryable", False)),
            "operation_id": getattr(exc, "operation_id", None)}


class Protocol:
    """The MCP JSON-RPC surface over the tool table, transport-agnostic.

    `handle(message) -> response | None` for one JSON-RPC message (None for a notification).
    `api_error` is the exception type the `api` raises for an HTTP-level refusal; anything else
    is a bug and surfaces as a JSON-RPC error.
    """

    def __init__(self, api, api_error=Exception):
        self.api, self.api_error = api, api_error

    def handle(self, message):
        if not isinstance(message, dict) or message.get("jsonrpc") != "2.0":
            return self._error(None, -32600, "Invalid Request")
        rid, method, params = message.get("id"), message.get("method"), message.get("params") or {}
        if method is None:
            return None                                  # a response to us; we send no requests
        if rid is None:                                  # a notification
            return None
        if method == "initialize":
            asked = params.get("protocolVersion")
            version = asked if asked in PROTOCOL_VERSIONS else PROTOCOL_VERSIONS[0]
            return self._result(rid, {"protocolVersion": version, "capabilities": {"tools": {}},
                                      "serverInfo": SERVER_INFO,
                                      "instructions": INSTRUCTIONS})
        if method == "ping":
            return self._result(rid, {})
        if method == "tools/list":
            return self._result(rid, {"tools": listing()})
        if method == "tools/call":
            return self._call(rid, params)
        return self._error(rid, -32601, f"Method not found: {method}")

    def _call(self, rid, params):
        name, args = params.get("name"), params.get("arguments") or {}
        entry = BY_NAME.get(name)
        if not entry:
            return self._error(rid, -32602, f"Unknown tool: {name}")
        if not isinstance(args, dict):
            return self._error(rid, -32602, "arguments must be an object")
        missing = [k for k in entry["inputSchema"].get("required", []) if args.get(k) in (None, "")]
        if missing:
            return self._tool_error(rid, {"error": "usage", "detail": f"{name} needs {', '.join(missing)}",
                                          "retryable": False})
        try:
            result = entry["fn"](self.api, args)
        except self.api_error as exc:
            return self._tool_error(rid, error_payload(exc))
        return self._result(rid, {"content": [{"type": "text", "text": json.dumps(result, default=str)}],
                                  "structuredContent": result if isinstance(result, dict) else {"result": result},
                                  "isError": False})

    @staticmethod
    def _result(rid, result):
        return {"jsonrpc": "2.0", "id": rid, "result": result}

    @staticmethod
    def _error(rid, code, message):
        return {"jsonrpc": "2.0", "id": rid, "error": {"code": code, "message": message}}

    @staticmethod
    def _tool_error(rid, payload):
        return {"jsonrpc": "2.0", "id": rid,
                "result": {"content": [{"type": "text", "text": json.dumps(payload)}],
                           "structuredContent": payload, "isError": True}}
