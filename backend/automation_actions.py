"""What an automation's steps do in the hub: its actions, the turns it starts and the items `find` reads.

Each runs inside one short write transaction (backend/automations.py opens it) and reuses what the hub already has:
the rules' task and event runners (backend/rules.py), outgoing webhooks, updates, and tasks. An action never raises
for an ordinary refusal; it answers {"ok": False, "detail": ...} and the run records it.

Mail is changed on the computer that reads the mailbox, not here: archive, label, leave for you, draft, send and
forward on a message from mail are queued in `automation_mail_actions` for its runner to claim
(GET .../mail-actions/claim, POST .../mail-actions/{id}/result). On a Slack message, send_reply posts in the thread
(the `slack_posts` outbox) and draft_reply leaves the draft with the owner as a task.

`send_reply` honors the inbox's send switch, `trigger.send` (on unless set false): off saves a draft and logs
`automation.send_off`.
"""
import json

from . import rules as R
from .store import H, Problem

MAIL_ACTIONS = {"archive": "archive", "label": "label", "leave_for_you": "leave", "draft_reply": "draft",
                "send_reply": "send", "forward": "forward"}
MAX_TEXT = 8000
MAX_ITEM = 4000


def actor_of(owner):
    """Who an automation acts as: its owner (a person as human:<id>, a bot), or Tico for a group."""
    kind, _, ident = str(owner).partition(":")
    return {"person": "human:" + ident, "bot": "bot:" + ident}.get(kind, H.KEEPER)


def _text(args, *keys):
    for key in keys:
        if args.get(key):
            return str(args[key])[:MAX_TEXT]
    return ""


def _fail(detail):
    return {"ok": False, "detail": str(detail)[:300]}


def run(c, auto, run_id, do, args, values):
    """Carry out one action for the automation `auto` ({id, flow}). Wrapped in a savepoint: a refused action writes
    nothing but its refusal."""
    c.execute("SAVEPOINT automation_action")
    try:
        result = ACTIONS[do](c, auto, run_id, args or {}, values or {})
        c.execute("RELEASE automation_action")
        return result
    except (H.Refused, Problem, ValueError, KeyError) as exc:
        c.execute("ROLLBACK TO automation_action")
        c.execute("RELEASE automation_action")
        return _fail(getattr(exc, "detail", None) or getattr(exc, "message", None) or exc or type(exc).__name__)


# ---------------------------------------------------------------------------------------------------- messages
def _message(values):
    message = values.get("message")
    return message if isinstance(message, dict) else None


def _queue_mail(c, auto, run_id, action, message, args):
    aid = H.new_id()
    c.execute("INSERT INTO automation_mail_actions(id,automation_id,run_id,mailbox,msg_id,action,args_json,state,created) "
              "VALUES(?,?,?,?,?,?,?,'queued',?)",
              (aid, auto["id"], run_id, str(message.get("mailbox") or ""), str(message.get("id") or ""), action,
               json.dumps(args, default=str), H.now()))
    return {"ok": True, "detail": f"{action} queued", "mail_action": aid}


def _send_on(auto):
    return (auto["flow"].get("trigger") or {}).get("send", True) is not False


def _mail_or_slack(do):
    def act(c, auto, run_id, args, values):
        message = _message(values)
        if not message:
            return _fail(f"{do} needs a message")
        if message.get("source") == "slack":
            return _slack(c, auto, run_id, do, args, message)
        action = MAIL_ACTIONS[do]
        if do == "send_reply" and not _send_on(auto):
            H.event(c, actor_of(auto["flow"]["owner"]), "automation.send_off", auto["id"],
                    {"run": run_id, "mailbox": message.get("mailbox"), "msg_id": message.get("id")})
            return {**_queue_mail(c, auto, run_id, "draft", message, args), "detail": "send_off"}
        if do == "forward" and args.get("webhook"):
            return _webhook(c, auto, "custom.forward.automation", args["webhook"], message)
        return _queue_mail(c, auto, run_id, action, message, args)
    return act


def _slack(c, auto, run_id, do, args, message):
    text = _text(args, "body", "text")
    if do == "send_reply" and _send_on(auto):
        if not text:
            return _fail("send_reply needs a body")
        bot = R._slug(args.get("bot")) or _owner_bot(c, auto)
        if not bot:
            return _fail("send_reply in Slack needs a bot to post as")
        conv = R._bot_room(c, bot)
        msg = H._write_message(c, H.bot_actor(bot), conv.get("owner_actor") or H.KEEPER, text, conv, "say",
                               {"automation": auto["id"], "automation_run": run_id}, None, None)
        now = H.now()
        c.execute("INSERT INTO slack_posts(message_id,channel,thread_ts,bot,text,state,created,updated) "
                  "VALUES(?,?,?,?,?,'ready',?,?)",
                  (msg["id"], message.get("channel"), message.get("thread_ts") or message.get("ts"), bot, text, now, now))
        return {"ok": True, "detail": "posted", "message": msg["id"]}
    if do in ("send_reply", "draft_reply"):
        if do == "send_reply":
            H.event(c, actor_of(auto["flow"]["owner"]), "automation.send_off", auto["id"], {"run": run_id})
        title = f"Draft reply: {str(message.get('text') or '')[:80]}".strip()
        return _create_task(c, auto, run_id, {"title": title, "body": text}, {})
    return {"ok": True, "detail": "nothing to do in Slack"}


def _owner_bot(c, auto):
    kind, _, ident = auto["flow"]["owner"].partition(":")
    return ident if kind == "bot" else auto.get("assistant_bot") or ""


# ---------------------------------------------------------------------------------------------------- tasks
def _task(c, values):
    task = values.get("task")
    tid = task.get("id") if isinstance(task, dict) else None
    return H.task(c, tid) if tid else None


def _create_task(c, auto, run_id, args, values):
    title = " ".join(_text(args, "title").split())[:300]
    if not title:
        return _fail("create_task needs a title")
    owner = str(args.get("owner") or "")
    owner = owner if ":" in owner else (("bot:" + owner) if owner and H.bot(c, owner) else
                                        ("human:" + owner) if owner else actor_of(auto["flow"]["owner"]))
    if owner.startswith("person:"):
        owner = "human:" + owner[7:]
    if owner == H.KEEPER:
        return _fail("create_task needs an owner")
    row = H.task_create(c, actor_of(auto["flow"]["owner"]), title, _text(args, "body") or title, owner, lint=False,
                        deduplicate=False)
    return {"ok": True, "detail": f"task {row['id']}", "task": row["id"]}


def _on_task(name):
    def act(c, auto, run_id, args, values):
        task = _task(c, values)
        if not task:
            return _fail(f"{name} needs a task")
        said = _text(args, "text", "note") or f"Automation {auto['flow'].get('name') or auto['id']}"
        if name == "note":
            H.task_update(c, H.KEEPER, task["id"], note=said)
            return {"ok": True, "detail": "noted"}
        if name == "assign":
            owner = str(args.get("owner") or "")
            if not owner:
                return _fail("assign needs an owner")
            done = R._assign(c, task["id"], {"owner": owner.replace("person:", "human:")}, said) or {}
            return {"ok": True, "detail": f"assigned to {done.get('owner')}"}
        tags = args.get("tag") or args.get("name")
        done = R.TASK_RUNNERS["add_tag"](c, task["id"], {"tag": tags if isinstance(tags, list) else [tags]}, said)
        return {"ok": True, "detail": "labelled" if done["changed"] else "already labelled"}
    return act


def _label(c, auto, run_id, args, values):
    if _message(values) and not values.get("task"):
        return _mail_or_slack("label")(c, auto, run_id, args, values)
    if not (args.get("tag") or args.get("name")):
        return _fail("label needs a tag")
    return _on_task("label")(c, auto, run_id, args, values)


def _note(c, auto, run_id, args, values):
    if values.get("task"):
        return _on_task("note")(c, auto, run_id, args, values)
    bot = R._slug(args.get("bot"))
    if not bot:
        return _fail("note needs a task or a bot")
    ok, detail = R._tell_bot(c, "automation:" + auto["id"], bot, _text(args, "text", "note") or "A note.",
                             {"automation": auto["id"], "automation_run": run_id}, wake=False)
    return {"ok": ok, "detail": detail}


def _wake_bot(c, auto, run_id, args, values):
    bot = R._slug(args.get("bot")) or _owner_bot(c, auto)
    text = _text(args, "text", "prompt") or f"Automation {auto['flow'].get('name')}: take a look."
    ok, detail = R._tell_bot(c, "automation:" + auto["id"], bot, text,
                             {"automation": auto["id"], "automation_run": run_id}, wake=True, task=_task(c, values))
    return {"ok": ok, "detail": detail}


def _post_update(c, auto, run_id, args, values):
    text = _text(args, "text", "body")
    if not text:
        return _fail("post_update needs text")
    from . import updates
    author = actor_of(auto["flow"]["owner"])
    if author == H.KEEPER:
        return _fail("a group's automation has no one to post an update as")
    posted = updates.post(c, H.actor_id(author) if author.startswith("bot:") else author, text)
    return {"ok": True, "detail": "posted", "update": (posted or {}).get("id")}


def _webhook(c, auto, kind, hook, data):
    done = R._send_out(c, "call_webhook", actor_of(auto["flow"]["owner"]), str(hook or ""), kind, auto["id"],
                       data if isinstance(data, dict) else {"data": data}, None)
    return {"ok": done["ok"], "detail": done["detail"]}


def _call_webhook(c, auto, run_id, args, values):
    return _webhook(c, auto, str(args.get("type") or "custom.automation"), args.get("webhook"),
                    args.get("data") if args.get("data") is not None else {"automation": auto["id"], "run": run_id})


ACTIONS = {"archive": _mail_or_slack("archive"), "leave_for_you": _mail_or_slack("leave_for_you"),
           "draft_reply": _mail_or_slack("draft_reply"), "send_reply": _mail_or_slack("send_reply"),
           "forward": _mail_or_slack("forward"), "create_task": _create_task, "label": _label, "wake_bot": _wake_bot,
           "note": _note, "post_update": _post_update, "call_webhook": _call_webhook, "assign": _on_task("assign")}


# ---------------------------------------------------------------------------------------------------- turns
def start_turn(c, auto, run_id, step_id, who, prompt, assistant_bot):
    """Wake the named bot with the prompt in its own room (an Assistant in the person's Assistant room, made on first
    use), never in the sender's conversation. The notice carries the run, so its turn's end resumes it."""
    kind, _, ident = who.partition(":")
    refs = {"automation": auto["id"], "automation_run": run_id, "automation_step": step_id}
    if kind == "assistant":
        from . import assistant
        person = H.human(c, ident)
        if not person:
            raise ValueError(f"No person {ident}")
        bot, conv = assistant_bot, assistant.ensure_room(c, "human:" + ident, assistant_bot)
    else:
        bot = ident
        found = H.bot(c, bot)
        if not found or found["state"] not in R.BOT_STATES_OK:
            raise ValueError(f"No bot {bot}" if not found else f"{bot} is {found['state']}")
        conv = R._bot_room(c, bot)
    msg = H._write_message(c, H.KEEPER, H.bot_actor(bot), prompt, conv, "notice", refs, None, None,
                           decided=R.Decision(R.WAKE, "automation:" + auto["id"]))
    return {"ref": msg["id"]}


# ---------------------------------------------------------------------------------------------------- find
FIND = {
    "mail": ("SELECT mailbox, msg_id AS id, thread_id AS thread, from_addr AS 'from', subject, snippet, date, "
             "updated AS at FROM mail_messages WHERE deleted_at IS NULL AND updated > ? {mine} "
             "AND (subject LIKE ? OR from_addr LIKE ? OR snippet LIKE ?) ORDER BY updated LIMIT ?", 3),
    "tasks": ("SELECT id, title, status, owner, requester, created AS at FROM tasks WHERE created > ? "
              "AND coalesce(private,0)=0 AND title LIKE ? ORDER BY created LIMIT ?", 1),
    "prs": ("SELECT task_id AS task, url, title, state, repo, number, created AS at FROM task_links "
            "WHERE kind='pr' AND created > ? AND (coalesce(title,'') LIKE ? OR url LIKE ?) ORDER BY created LIMIT ?", 2),
    "listening": ("SELECT i.id, i.destination, l.url, l.author, l.content, i.created_at AS at FROM intake_items i "
                  "JOIN listen_items l ON l.id=i.item_id WHERE i.created_at > ? AND l.content LIKE ? "
                  "ORDER BY i.created_at LIMIT ?", 1),
    "docs": ("SELECT id, path, title, updated AS at FROM docs WHERE archived=0 AND updated > ? "
             "AND (title LIKE ? OR path LIKE ?) ORDER BY updated LIMIT ?", 2),
}


def find(c, auto, source, query, limit, since):
    """Items from `source` newer than `since` whose text has `query` (plain words), oldest first. Mail is the
    automation's own inbox when its trigger names one."""
    sql, likes = FIND[source]
    like = "%" + str(query or "").strip().replace("%", "").replace("_", "") + "%"
    args = [since]
    mine = ""
    inbox = (auto["flow"].get("trigger") or {}).get("inbox")
    if source == "mail" and inbox and "@" in str(inbox):
        mine, args = "AND mailbox=?", [since, inbox]
    rows = [dict(r) for r in c.execute(sql.format(mine=mine), (*args, *[like] * likes, int(limit)))]
    for row in rows:
        for key in ("content", "snippet"):
            if isinstance(row.get(key), str):
                row[key] = row[key][:MAX_ITEM]
    return rows
