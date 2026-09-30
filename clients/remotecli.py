"""HTTP implementation of the `hub` commands (`clients/hubcli.py` parses them); never opens a database."""

import base64
import csv
import io
import json
import os
import re
import sys
import time
from pathlib import Path

if __package__ in (None, ""):                          # imported by a script run from anywhere
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from clients.tico import APIError, Client  # noqa: E402


def run(args, who=None):
    if who:
        raise APIError("identity", "Remote identity comes from authentication; --human is unavailable")
    # A query may run for 20 s on the server before it is stopped; leave room for that.
    client = Client(os.environ["HUB_API_URL"], os.environ.get("HUB_TOKEN", ""), timeout=30 if args.cmd == "sql" else 120 if args.cmd == "listen" else 15)
    if args.cmd in ("integrations", "integration", "queries"):
        # Reads a runner credential may make outside a turn; /me would refuse a runner.
        return integrations(client, args)
    if args.cmd == "github":
        return client.post("github/repos", {"slug": args.slug, **({"empty": True} if args.empty else {"template": args.template})})
    if args.cmd in ("catalog", "bot"):
        return bots(client, args)
    if args.cmd == "people":
        from clients import hubtools
        fields = {k: v for k, v in vars(args).items() if k not in ("cmd", "sub", "fn") and v is not None}
        fields["operation_id"] = os.environ.get("HUB_OPERATION_ID")
        return hubtools.BY_NAME["hub_people_" + args.sub]["fn"](client, fields)
    if args.cmd in ("decisions", "judge"):     # `judge` is the old name
        return judge(client, args)
    if args.cmd in ("context", "meetings"):
        from clients import hubtools
        fields = {k: v for k, v in vars(args).items() if k not in ("cmd", "sub", "fn") and v is not None}
        if args.fn == "meetings import":
            return hubtools.meetings_import_file(client, fields)
        return hubtools.BY_NAME["hub_" + args.fn.replace(" ", "_")]["fn"](client, fields)
    if args.fn == "docs ask":           # `docs fetch` never gets here: it runs locally (clients/hubcli.py)
        from clients import docs_ask
        return docs_ask.ask(client, args.question, args.wait, key=os.environ.get("HUB_OPERATION_ID"))
    if args.cmd == "grokbot":
        from clients import hubtools
        body = json.loads(Path(args.file).read_text())
        return hubtools.BY_NAME["hub_grokbot_sync"]["fn"](client, body)
    if args.cmd == "files":
        from clients import hubtools
        fields = {k: v for k, v in vars(args).items() if k not in ("cmd", "sub", "fn") and v is not None}
        fields["operation_id"] = os.environ.get("HUB_OPERATION_ID")
        if args.fn == "files publish":
            return hubtools.files_publish_path(client, fields)
        return hubtools.BY_NAME["hub_" + args.fn.replace(" ", "_")]["fn"](client, fields)
    if args.cmd == "docs":
        from clients import hubtools
        fields = {k: v for k, v in vars(args).items() if k not in ("cmd", "sub", "fn", "body_file") and v is not None}
        fields["operation_id"] = os.environ.get("HUB_OPERATION_ID")
        if args.fn == "docs write":
            fields["body"] = sys.stdin.read() if not args.body_file or args.body_file == "-" else Path(args.body_file).read_text(encoding="utf-8-sig")
        return hubtools.BY_NAME["hub_" + args.fn.replace(" ", "_")]["fn"](client, fields)
    if args.cmd == "assistant":
        from clients import hubtools
        try:
            body = json.loads(args.body or "{}")
        except ValueError:
            raise APIError("body", "--body must be JSON") from None
        return hubtools.BY_NAME["hub_assistant_propose"]["fn"](client, {
            "summary": args.summary, "path": args.path, "method": args.method, "body": body,
            "operation_id": os.environ.get("HUB_OPERATION_ID")})
    if args.cmd == "db":
        # Runs here, beside the credential; the hub only checks who is asking and keeps the audit.
        from clients import dbquery
        return dbquery.run(client, args)
    identity = client.get("me")
    actor = identity["actor"]
    key = os.environ.get("HUB_OPERATION_ID")

    def post(path, body, suffix=""):
        result = client.post(path, body, key=(key + suffix) if key else None)
        return result["task"] if isinstance(result, dict) and set(result) == {"task"} else result

    def target(value):
        return actor if value in ("me", "self") else value

    def refs(values):
        out = {}
        for value in values or []:
            kind, _, ident = value.partition(":")
            out.setdefault(kind, []).append(ident)
        return out

    cmd, sub = args.cmd, getattr(args, "sub", None)
    if cmd == "whoami":
        return identity
    if cmd == "ack":
        return post(f"messages/{args.message_id}/ack", {})
    if cmd in ("say", "notice"):
        return post("messages", {"to": args.to, "text": args.text, "kind": cmd,
                    "conversation_id": getattr(args, "conversation", None),
                    "refs": refs(getattr(args, "ref", None))})
    if cmd == "answer":
        return post(f"messages/{args.message_id}/answer", {"text": args.text or args.unknown,
                    "unknown": bool(args.unknown)})
    if cmd == "ask":
        if len(args.words) < 2:
            raise APIError("usage", 'hub ask <bot> [<bot>...] "question"')
        pending, result = {}, {}
        for i, bot in enumerate(args.words[:-1]):
            msg = post("messages", {"to": bot, "text": args.words[-1], "kind": "ask",
                       "wait_s": min(300, max(0, int(args.wait)))}, suffix=f":ask:{i}")
            pending[msg["id"]] = bot
        deadline = time.monotonic() + max(0, min(args.wait, 300))
        while pending:
            answers = client.get("answers", ids=",".join(pending))
            for mid, answer in answers.items():
                bot = pending.pop(mid)
                result[bot] = {"unknown" if answer.get("refs", {}).get("unknown") else "answer": answer["body"]}
                post(f"messages/{answer['id']}/ack", {}, suffix=":ack:" + answer["id"])
            if not pending or time.monotonic() >= deadline:
                break
            time.sleep(1)
        result.update({bot: {"timeout": True} for bot in pending.values()})
        return result
    if cmd == "note":
        text = Path(args.text_file).read_text() if args.text_file else args.text
        return post("notes", {"to": target(args.to), "text": text})["note"]
    if cmd == "notes":
        since = args.since
        m = re.fullmatch(r"(\d+)([hd])", since or "")
        if m:
            hours = int(m.group(1)) * (24 if m.group(2) == "d" else 1)
            since = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() - hours * 3600))
        return client.get("notes", to=target(args.to) if args.to else None,
                          sender=target(args.sender) if args.sender else None, since=since,
                          waiting="true" if args.waiting else None, limit=args.limit)
    if cmd == "unnote":
        return post(f"notes/{args.id}/cancel", {})["note"]
    if cmd == "task":
        if sub == "create":
            body = Path(args.body_file).read_text() if args.body_file else args.body
            payload = {"owner": target(args.owner), "title": args.title, "body": body,
                       "due": args.due, "parent_id": args.parent, "goal_id": getattr(args, "goal", None) or None}
            if args.label:
                payload["labels"] = [x.strip() for one in args.label for x in one.split(",") if x.strip()]
            if args.top:
                payload["top"] = True
            if args.link:
                payload["links"] = list(args.link)
            if getattr(args, "next_run", False):
                payload["next_run"] = True
            return post("tasks", payload)
        if sub == "show":
            return client.get("tasks/" + args.id)
        if sub == "stuck":
            return client.get("tasks/stuck", hours=args.hours)["tasks"]
        if sub == "run":
            return post(f"tasks/{args.id}/run-now", {})
        if sub == "list":
            return client.get("tasks", owner=target(args.owner), requester=target(args.requester),
                              status=",".join(args.status) if args.status else None,
                              lane=args.lane, label=args.label)["tasks"]
        if sub == "ask":
            return post(f"tasks/{args.id}/ask", {"text": args.text})
        if sub == "comment":
            return post(f"tasks/{args.id}/comments", {"text": args.text})
        if sub == "link":
            return post(f"tasks/{args.id}/links", {"url": args.url, "title": args.title})
        if sub == "label":
            current = client.get("tasks/" + args.id)["task"]
            labels = [x for x in current.get("labels") or []]
            for one in (args.remove or []):
                for x in one.split(","):
                    labels = [y for y in labels if y != x.strip().lower()]
            for one in (args.add or []):
                for x in one.split(","):
                    if x.strip() and x.strip().lower() not in labels:
                        labels.append(x.strip().lower())
            return post("tasks/" + args.id, {"version": current["version"], "labels": labels})
        if sub == "attach":
            path = Path(args.file)
            data = path.read_bytes()
            body = {"name": args.name or path.name}
            try:
                body["text"] = data.decode("utf-8")
            except UnicodeDecodeError:
                body["content_base64"] = base64.b64encode(data).decode("ascii")
            return post(f"tasks/{args.id}/files", body)
        if sub in ("update", "close"):
            current = client.get("tasks/" + args.id)["task"]
            body = {"version": current["version"], "note": args.note}
            if sub == "close":
                body["close"] = True
            else:
                body.update({"status": args.status, "owner": args.owner, "due": args.due,
                             "goal_id": getattr(args, "goal", None)})
                if args.blocked_by is not None:
                    body["blocked_by"] = args.blocked_by
            return post("tasks/" + args.id, body)
    if cmd == "goals":
        if args.all:
            return client.get("goals", all="1", status=args.status)["goals"]
        return client.get("goals", owner=target(args.owner) if args.owner else None)
    if cmd == "goal":
        if sub == "show":
            return client.get("goals/" + args.id)["goal"]
        if sub == "create":
            body = Path(args.body_file).read_text() if args.body_file else args.body
            return post("goals", {"owner": target(args.owner), "title": args.title, "parent_id": args.parent,
                        "body": body or "", "top": bool(args.top)})["goal"]
        if sub == "status":
            return post(f"goals/{args.id}/status", {"status": args.status, "note": args.note or ""})["goal"]
        body = {"title": args.title, "parent_id": args.parent, "owner": target(args.owner) if args.owner else None,
                "rank": args.rank, "top": bool(args.top)}
        if args.body_file or args.body is not None:
            body["body"] = Path(args.body_file).read_text() if args.body_file else args.body
        return post("goals/" + args.id, body)["goal"]
    if cmd == "kpi":
        if sub == "add":
            return post(f"goals/{args.goal_id}/kpis", {"name": args.name, "unit": args.unit or "",
                        "target": args.target})["kpi"]
        if sub == "log":
            source = "estimate" if args.estimate else (args.source or "measured")
            return post(f"kpis/{args.kpi_id}/readings", {"value": args.value, "note": args.note or "",
                        "source": source, "at": args.at})["reading"]
        return client.get(f"kpis/{args.kpi_id}/readings")
    if cmd == "market":
        if sub == "show":
            return client.get("market/entities/" + args.id)
        if sub == "find":
            return client.get("market/entities", q=args.text)
        if sub == "edges":
            return client.get("market/edges", src=args.src, dst=args.dst, rel=args.rel, as_of=args.as_of)
        if sub == "delta":
            return client.get("market/delta", since=args.since)
        if sub == "ask":
            return post("market/ask", {"question": args.question})
        if sub == "report":
            return post("market/insights", {"kind": args.kind, "about": args.about or "", "claim": args.claim,
                        "source_url": args.source or "", "quote": args.quote or "",
                        "confidence": args.confidence or "medium", "urgent": bool(args.urgent),
                        "source_ref": getattr(args, "source_ref", None) or None})
        if sub == "resolve":
            return post(f"market/insights/{args.id}/resolve", {"status": args.status,
                        "resolution": args.resolution or "", "applied_events": args.events or []})
        if sub == "apply":
            body = {"evidence": {"source_url": args.source or "", "source_kind": args.source_kind or "other",
                                 "quote": args.quote or "", "our_read": args.our_read or ""}}
            if args.entity_type and args.entity_name:
                body["entity"] = {"type": args.entity_type, "name": args.entity_name,
                                  "summary": args.summary or ""}
                if args.tier:
                    body["entity"]["tier"] = args.tier
                if args.new_id:
                    body["entity"]["id"] = args.new_id
            if args.entity_id:
                body["entity_id"] = args.entity_id
                if args.summary is not None:
                    body["summary"] = args.summary
            if args.edge_src and args.edge_rel and args.edge_dst:
                body["edge"] = {"src": args.edge_src, "rel": args.edge_rel, "dst": args.edge_dst}
            return post(f"market/insights/{args.id}/apply", body)
        if sub == "refresh":
            return post("market/delta/refresh", {"today": args.today})
        if sub == "page":
            text = sys.stdin.read() if args.body_file == "-" else open(args.body_file).read()
            return post("market/pages/" + args.name, {"body": text})
        unverified = []
        for item in args.unverified or []:
            entity_id, _, look = str(item).partition("=")
            unverified.append({"id": entity_id, "look_for": look})
        return post("market/curator/sweep", {"today": args.today, "unverified": unverified})
    if cmd == "listen":
        if sub == "save":
            text = sys.stdin.read() if args.file == "-" else Path(args.file).read_text()
            return post("listening/runs", json.loads(text))
        if sub in ("decide", "judge"):
            return post("listening/judge", {"limit": args.limit, "item_ids": args.item_ids or []})
        if sub == "show":
            return client.get("listening/items/" + args.id)
        if sub == "runs":
            return client.get("listening/runs", since=args.since, source=args.source)
        return client.get("listening/stats", since=args.since)
    if cmd == "intake":
        if sub == "list":
            return client.get("intake", destination=args.destination, status=args.status, limit=args.limit)
        return post(f"intake/{args.id}/resolve", {"status": args.status, "receiver_ref": args.receiver_ref or "",
                    "reason": args.reason or ""})
    if cmd == "history":
        page = client.get(f"conversations/{args.conversation}/messages", before=args.before, since=args.since)
        return {"conversation": page.get("conversation"), "messages": page.get("messages", [])}
    if cmd == "tools":
        from clients import hubtools
        fields = {k: v for k, v in vars(args).items() if k not in ("cmd", "sub", "fn") and v is not None}
        fields["operation_id"] = os.environ.get("HUB_OPERATION_ID")
        return hubtools.BY_NAME["hub_" + args.fn.replace(" ", "_")]["fn"](client, fields)
    if cmd == "routine":
        bot = getattr(args, "bot", None) or actor.split(":", 1)[-1]
        if sub == "list":
            return client.get(f"bots/{bot}/routines")["routines"]
        if sub == "set":
            text = Path(args.text_file).read_text() if args.text_file else args.text
            return post(f"bots/{bot}/routines", {"key": args.key, "title": args.title, "text": text,
                        "cron": args.cron or "", "on": args.on or "", "timezone": args.timezone or "",
                        "enabled": not args.disabled})["routine"]
        if sub == "delete":
            return post(f"routines/{args.id}/delete", {})["routine"]
        text = Path(args.text_file).read_text() if args.text_file else args.text
        return post(f"routines/{args.id}", {"title": args.title, "text": text, "cron": args.cron, "on": args.on,
                    "timezone": args.timezone,
                    "enabled": True if args.enable else False if args.disable else None})["routine"]
    if cmd == "approval":
        if sub == "show":
            return client.get("approvals/" + args.id)
        payload = json.loads(Path(args.payload_file).read_text() if args.payload_file else args.payload or "{}")
        return post("approvals", {"kind": args.kind, "payload": payload, "task_id": args.task})
    if cmd == "status":
        if sub == "set":
            bot = args.bot or actor.split(":", 1)[-1]
            return post(f"bots/{bot}/status", {"state": args.state, "focus": args.focus, "task_id": args.task})
        if sub == "history":
            return client.get(f"bots/{args.bot}/history", since=args.since)
        return [b for b in client.get("bots") if not args.team or b["team"] == args.team]
    if cmd == "turns":
        return client.get(f"bots/{args.bot}/turns", since=args.since)
    if cmd == "inbox":
        return client.get("inbox")
    if cmd == "board":
        return {"tasks": client.get("tasks")["tasks"], "bots": client.get("bots")}
    if cmd == "org":
        return client.get("org", person=args.person, team=args.team)
    if cmd == "fleet":
        return client.get("tico/fleet")
    if cmd == "calendar":
        from clients import hubtools
        if sub == "upcoming":
            return hubtools.BY_NAME["hub_calendar_upcoming"]["fn"](
                client, {"calendar": args.calendar})
        if sub == "status":
            return hubtools.BY_NAME["hub_calendar_status"]["fn"](client, {"id": args.id})
        description = (Path(args.description_file).read_text()
                       if args.description_file else args.description)
        return hubtools.BY_NAME["hub_calendar_schedule"]["fn"](client, {
            "calendar": args.calendar, "title": args.title, "start": args.start, "end": args.end,
            "attendees": args.attendee, "description": description,
            "add_meet": not args.no_meet, "operation_id": key,
        })
    if cmd == "sql":
        body = {"sql": args.sql, "params": sql_params(args.param)}
        if args.max_rows:
            body["max_rows"] = args.max_rows
        return post("sql", body)
    if cmd == "learn":
        return post(f"integrations/{args.service}/learnings", {"text": args.text})
    if cmd == "live":
        from clients import hubtools
        if sub == "stats":
            return hubtools.BY_NAME["hub_live_stats"]["fn"](client, {"days": args.days, "via": args.via})
        return hubtools.BY_NAME["hub_live_brief"]["fn"](client, {"since": getattr(args, "since", None)})
    if cmd == "batch":
        # The tool table is the one implementation; the command is its shell spelling.
        from clients import hubtools
        fields = {k: getattr(args, k, None) for k in ("batch", "bot", "all", "fresh", "kind", "text", "decision", "item", "until")}
        return hubtools.BY_NAME[f"hub_batch_{sub}"]["fn"](client, {**fields, "operation_id": key})
    raise APIError("unsupported", "This command is not supported by the remote API")


# ----------------------------------------------------------------------------- bots
def bots(client, args):
    """`hub catalog` and `hub bot create|check`: how BotOps sets the chosen bots up.

    The materialization is `clients/catalog.py`, which needs no network. What comes from the
    server is this company's names, the onboarding answers everybody's `knowledge/company.md` is
    written from, and the instructions the person wrote for this particular bot.
    """
    from clients import catalog
    workspace = Path(os.environ.get("HUB_WORKSPACE") or "")
    if args.cmd == "catalog":
        try:
            # The server's cards carry the instructions onboarding filled in; a server without
            # the endpoint still lets a bot read this checkout's own catalog.
            return client.get("catalog")["cards"]
        except (APIError, KeyError, TypeError):
            return catalog.cards()
    if args.sub == "set":
        # The server checks the change as the person who sent the cited message (backend/app.py).
        from clients import hubtools
        fields = {k: v for k, v in (("slug", args.slug), ("reports_to", args.reports_to), ("display_name", args.display_name),
                                    ("description", args.description), ("status", args.status), ("repo", args.repo),
                                    ("on_behalf_of", args.on_behalf_of)) if v is not None}
        try:
            return hubtools.BY_NAME["hub_bot_set"]["fn"](client, fields)
        except ValueError as exc:
            raise APIError("not_found", str(exc)) from None
    if args.sub in ("register", "access", "owners"):
        from clients import hubtools
        fields = {k: v for k, v in vars(args).items() if k not in ("cmd", "sub", "fn") and v not in (None, [])}
        fields["operation_id"] = os.environ.get("HUB_OPERATION_ID")
        return hubtools.BY_NAME["hub_bot_" + args.sub]["fn"](client, fields)
    if args.sub == "check":
        problems = catalog.check(workspace / ("emp-" + args.slug), args.slug)
        return {"ready": not problems, "problems": problems}
    record = onboarding(client)
    chosen = (record.get("selected") or {}).get(args.slug) or {}
    registered = register_for_requester(client, args, chosen)
    path = catalog.materialize(args.template, args.slug, workspace, client.get("config"),
                               record.get("answers") or {},
                               display_name=args.name or chosen.get("display_name"),
                               instructions=chosen.get("instructions"))
    return {"path": str(path), "template": args.template, "slug": args.slug,
            "committed": catalog.committed(path), "routines": seed_routines(client, args.slug, path),
            **({"registered": registered} if registered else {})}


def register_for_requester(client, args, chosen):
    """`hub bot create` in a turn a person's chat message started also registers the bot with the server as
    them (planned, they own it), so `hub bot set` and its routines have a bot to act on. A refusal for what that
    person may not do (no create_bots, the limit) stops the build; a turn no person started (onboarding, a
    routine) registers nothing here, as before."""
    try:
        return client.post("bots/register", {"slug": args.slug, "template": args.template, "on_behalf_of": "turn",
                                             "display_name": args.name or chosen.get("display_name") or ""})
    except APIError as exc:
        if exc.code == "on_behalf_of":
            return None
        raise


def seed_routines(client, slug, path):
    """The template's `schedules:` become the new bot's first routines in the hub. The manifest
    is read once, here, with its playbooks already rendered; from now on the hub's rows are the
    routines and `hub routine set` changes them (docs/routines.md)."""
    from clients.routines import validate_schedules
    import yaml
    try:
        declared = (yaml.safe_load((path / "employee.yaml").read_text()) or {}).get("schedules")
        entries = validate_schedules(declared, lambda rel: (path / rel).read_text())
    except (OSError, ValueError, TypeError, yaml.YAMLError) as exc:
        return {"error": f"employee.yaml schedules: {exc}"}
    seeded = []
    for entry in entries:
        seeded.append(client.post(f"bots/{slug}/routines", {
            "key": entry["id"], "title": entry["title"], "text": entry["instructions"],
            "cron": entry["cron"], "on": entry["on"], "timezone": entry["timezone"]})["routine"]["id"])
    return seeded


def onboarding(client):
    """What the person answered while picking their bots; {} on a server that has no onboarding."""
    try:
        record = client.get("onboarding")
    except APIError as exc:
        if exc.status in (403, 404):
            return {}
        raise
    return record if isinstance(record, dict) else {}


# ----------------------------------------------------------------------------- integrations
def integrations(client, args):
    if args.cmd == "integrations":
        return client.get("integrations")["integrations"]
    page = client.get("integrations/" + args.service)
    if args.cmd == "integration":
        return page
    if args.query_id:
        for query in page["queries"]:
            if query["id"] == args.query_id:
                return query
        raise APIError("not_found", f"No query {args.query_id} under {page['service']}", 404)
    return query_search(page["queries"], args.term)


from clients.hubtools import query_search  # noqa: E402  (one search, shared with the hub_queries tool)


# ----------------------------------------------------------------------------- decisions
def judge(client, args):
    """`hub decisions`: load the questions on this side, send them inline, print the answers.

    The hub knows nothing about question sets (questions/README.md): the set is read from this
    checkout, a dynamic choice is completed from `--option`, and the label is the set's
    `id@version` unless one is given."""
    from clients import judge as J
    if args.list:
        return J.list_sets()
    if bool(args.question_set) == bool(args.questions_file):
        raise APIError("usage", "hub decisions takes --set <name> or --questions-file <file>, and --state-file")
    if not args.state_file:
        raise APIError("usage", "hub decisions needs --state-file <json> (`-` for stdin)")
    try:
        if args.question_set:
            chosen = J.load_set(args.question_set)
            questions, label = dict(chosen["questions"]), chosen["label"]
        else:
            data = json.loads(Path(args.questions_file).read_text())
            questions = data.get("questions") if isinstance(data, dict) and "questions" in data else data
            label = data.get("label") if isinstance(data, dict) else None
        for spec in args.option or []:
            qid, _, path = spec.partition("=")
            if qid not in questions or not path:
                raise APIError("usage", f"--option names a question of the set and a file: {spec!r}")
            questions[qid] = J.with_options(questions[qid], json.loads(Path(path).read_text()))
        for qid, q in questions.items():
            if isinstance(q, dict) and q.get("dynamic"):
                raise APIError("usage", f"{qid} is a dynamic choice: complete it with --option {qid}=<file>")
        state = json.loads(sys.stdin.read() if args.state_file == "-" else Path(args.state_file).read_text())
    except J.JudgeError as exc:
        raise APIError(exc.code, exc.detail)
    except OSError as exc:
        raise APIError("usage", f"cannot read {exc.filename}: {exc.strerror}")
    except ValueError as exc:
        raise APIError("usage", f"not JSON: {exc}")
    try:
        return J.through_hub(client)(state, questions, args.label or label)
    except J.JudgeError as exc:
        raise APIError(exc.code, exc.detail, exc.status, exc.retryable)


def integrations_text(rows):
    blocks = []
    for row in rows:
        head = (f"{row['service']:<24} {row['kind']:<8} {row['writes']:<9} {row['summary']}"
                f"  [{row['query_count']} queries, {row['learning_count']} learnings]")
        extra = [f"  credentials: {c}" for c in (row.get("credentials") or [])]
        if row.get("access"):
            extra.append(f"  access: {row['access']}")
        blocks.append("\n".join([head, *extra]))
    return "\n\n".join(blocks) or "no integrations"


def integration_text(page):
    out = [f"# {page['title']} ({page['service']}, {page['kind']}, writes: {page['writes']}, owner: {page['owner']})",
           "", page["summary"], "", f"Access: {page['access']}", "Credentials:"]
    out += [f"  - {c}" for c in page["credentials"]]
    out += ["Declared in employee.yaml as:"] + ["  " + line for line in page["declared_as"].rstrip().splitlines()]
    out += ["", page["body"].rstrip()]
    if page["queries"]:
        out += ["", f"## Queries ({len(page['queries'])}; `hub queries {page['service']} <term>` searches, `--id <id>` prints one)"]
        out += [f"  {q['id']:<44} {q['title']}" for q in page["queries"]]
    notes = page.get("learnings") or []
    out += ["", f"## Learnings ({len(notes)}; add one with `hub learn {page['service']} \"...\"`)"]
    out += [f"  {n['created'][:10]}  {n['actor']}: {n['text']}" for n in notes] or ["  none yet"]
    return "\n".join(out)


def query_text(query):
    out = [f"{query['id']}: {query['title']}", query.get("description", ""),
           f"database: {query.get('database', '')}  category: {query.get('category', '')}  tags: {', '.join(query.get('tags') or [])}"]
    if query.get("params"):
        out.append("params:")
        for p in query["params"]:
            extra = (" required" if p.get("required") else "") + (f" default={p['default']}" if "default" in p else "")
            out.append(f"  {p['name']} ({p.get('type', 'text')}): {p.get('label', p['name'])}{extra}")
    out += ["", query["sql"].rstrip() if "sql" in query else json.dumps(query.get("mongo"), indent=2)]
    return "\n".join(out)


def queries_text(rows):
    return "\n".join(f"{q['id']:<44} {q['title']}  — {q.get('description', '')}" for q in rows) or "no matching queries"


def sql_params(pairs):
    """`--param key=value` pairs as the named bindings the API takes; numbers bind as numbers."""
    params = {}
    for pair in pairs or []:
        key, sep, value = pair.partition("=")
        if not sep or not key:
            raise APIError("usage", "--param takes key=value")
        if re.fullmatch(r"-?\d+", value):
            params[key] = int(value)
        elif re.fullmatch(r"-?\d+\.\d+", value):
            params[key] = float(value)
        else:
            params[key] = value
    return params


def sql_table(result, width=60):
    """A compact aligned table, one value per cell, with a trailing count line."""
    columns, rows = result["columns"], result["rows"]
    cell = lambda value: ("" if value is None else " ".join(str(value).split()))[:width]  # noqa: E731
    grid = [[cell(v) for v in row] for row in rows]
    widths = [max([len(name)] + [len(row[i]) for row in grid]) for i, name in enumerate(columns)]
    lines = []
    if columns:
        lines.append("  ".join(name.ljust(widths[i]) for i, name in enumerate(columns)).rstrip())
        lines.append("  ".join("-" * w for w in widths))
        lines += ["  ".join(row[i].ljust(widths[i]) for i in range(len(columns))).rstrip() for row in grid]
    count = f"{result['row_count']} row{'s' if result['row_count'] != 1 else ''}"
    if result.get("truncated"):
        count += " shown (more available; add a LIMIT or raise --max-rows)"
    lines.append(f"{count} ({result['ms']} ms)" + (f"; {result['note']}" if result.get("note") else ""))
    return "\n".join(lines)


def sql_csv(result):
    out = io.StringIO()
    writer = csv.writer(out, lineterminator="\n")
    writer.writerow(result["columns"])
    writer.writerows(result["rows"])
    return out.getvalue().rstrip("\n")


def main(args, who=None):
    try:
        result = run(args, who)
        if args.cmd == "sql" and not args.json:
            print(sql_csv(result) if args.csv else sql_table(result))
        elif args.cmd == "db" and not args.json:
            from clients import dbquery
            print(dbquery.render(result, args))
            return 0 if result.get("ok", True) else 2
        elif args.cmd == "integrations" and not args.json:
            print(integrations_text(result))
        elif args.cmd == "integration" and not args.json:
            print(integration_text(result))
        elif args.cmd == "queries" and not args.json:
            print(query_text(result) if args.query_id else queries_text(result))
        else:
            print(json.dumps(result, indent=2))
        return 0
    except APIError as exc:
        print(json.dumps({"error": exc.code, "detail": exc.detail, "retryable": exc.retryable,
                          "operation_id": exc.operation_id}, indent=2))
        return 1 if exc.retryable else 2
