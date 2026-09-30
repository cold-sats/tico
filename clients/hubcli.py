#!/usr/bin/env python3
"""`hub`: what a bot calls inside a turn to talk to the company hub.

Thin on purpose (docs/history/hub-v2.md §5): parse the arguments, hand them to `clients/remotecli.py`,
which makes one HTTP call against the Tico API and prints JSON on stdout. Every rule lives on
the server (`backend/hubdb.py`), never here.

    hub whoami
    hub say <bot|human> "<text>" [--conversation ID] [--ref task:ID ...]
    hub ask <bot> [<bot>...] "<question>" --wait 60
    hub answer <message-id> "<text>" [--unknown "needs X"]
    hub notice <human> "<text>"
    hub note <bot> "<text>" [--text-file f]  a quiet note: wakes nobody; the bot's next run reads it
    hub notes [--to me|X] [--from me|X] [--since 24h|ISO] [--waiting]   notes, newest first
    hub unnote <id>                        take back a note no run has carried yet
    hub task create --owner <bot|human> --title "..." [--body "..."|--body-file f] [--due D] [--parent ID]
                    [--goal ID] [--dry-run] the checks a create would fail, nothing written
                    [--next-run]           for a bot: no wake; its next run carries the task
    hub task ask <id> "<question>"
    hub task update <id> --status doing|waiting|done|declined [--note "..."] [--goal ID|--goal ""]
    hub task close <id> [--note "..."]
    hub task attach <id> <file> [--name "..."]
                                           store a deliverable with the task; prints the link
    hub files publish <path> [--title T] [--task ID] [--scope task|bot]
                                           list a file from this checkout on your page (reports/x.md);
                                           publishing it again adds a version (docs/files.md)
    hub files add-link <https-url> [--title T] [--task ID]   a Google Doc, Notion page, Figma file
    hub files touch <file-id|url>          you edited a linked document again: it moves to the top
    hub files import s3://bucket/key [--title T] [--task ID]  copy an object with this computer's credentials
    hub files list [--bot X] [--limit N]   what is on the page, newest activity first
    hub docs list [--prefix sales/]        the company's internal docs by path
    hub docs read <id|path|manual:name>    one doc in full, with its version; manual:<name> is a Tico manual page
    hub docs search "<words>" [--manual]   internal and linked docs, best first, then the Tico manual (--manual: only it)
    hub docs write <path> --title T (--body-file F | stdin) [--note N]
                                           create or replace a doc; every write is a version
    hub docs history <id|path>             its versions: who changed it, when and why
    hub docs links                         where the company's other docs live (links, never copies)
    hub assistant propose --summary "..." --path /api/v2/... [--method POST] [--body '{...}']
                                           Assistant only: ask the person to confirm a side effect (an
                                           approval, anything outside the company, spend, settings,
                                           archive/delete, activating a bot); it runs only on their click
    hub task list [--owner me|X] [--requester me] [--status open|doing|waiting|done]
    hub task show <id>
    hub goals [--owner me|X] [--all]      what you are for: your goals in order, the chain above
                                           them, and your reports' goals; --all is every goal
    hub goal show <id>                     the goal, its KPIs (target, colour), tasks, check-ins, history
    hub goal create --owner me|X --title "..." [--parent ID] [--body "..."|--body-file f] [--top]
                                           set a goal; a parent is optional. With one, whoever owns the parent gives its first colour
    hub goal status <id> red|yellow|green|done|dropped "<one sentence>"
                                           set the colour by hand: it sticks (with your name) until handed back
    hub goal auto <id>                     let the Goal Manager set the colour again (ends a colour set by hand)
    hub goal refresh [--goal ID ...]       the Goal Manager's status pass: work automatic colours out again
    hub goal checkin <id> "<words>" [--signal on_track|at_risk|off_track] [--from X] [--kpi ID]
                                           how the owner says it is going, in their words (colours a goal with no KPI)
    hub goal checkins <id>                 a goal's check-ins, newest first
    hub goal needs-you                     red KPIs on your goals, stale KPIs you own, proposals to confirm
    hub goal update <id> [--title ...] [--body ...|--body-file f] [--parent ID|--parent ""] [--owner X]
                    [--rank N|--top]
    hub kpi list [--goal ID] [--owner me|X] [--unlinked] [--bot SLUG]
                                           KPIs with latest reading and colour; --bot: that bot's five automatic KPIs
    hub kpi show <id>                      definition and versions, the goals using it, every reading, check-ins
    hub kpi add "<name>" [--goal ID] [--definition "..."] [--unit %] [--direction up|down|range]
                [--cadence daily|weekly|monthly] [--owner me|X|company] [--source-note "..."] [target flags]
                                           a KPI of its own; with --goal it is linked, the target on the link
    hub kpi update <id> [--name ...] [--definition ...] [--unit ...] [--direction ...] [--cadence ...]
                    [--source-note ...] [--owner X]
                                           a change to what it measures is a new definition version
    hub kpi link <goal-id> <kpi-id> [target flags]   link a goal to a KPI, or change the target on the link
    hub kpi unlink <goal-id> <kpi-id>      take a KPI off a goal
        target flags: --baseline N --target N --deadline YYYY-MM-DD (improve; a deadline is required)
                      or --min N --max N (a range to stay in); none: just linked
    hub kpi log <kpi-id> <value> ["<note>"] [--period-start D] [--period-end D|--at D] [--collected-at T]
                [--evidence "url or note"] [--quality measured|estimate|partial|--estimate] [--source posthog]
                [--definition-version N] [--supersedes READING-ID]
                                           a reading: a fact with its period; to correct one, supersede it
    hub kpi readings <kpi-id> [--effective]   every reading, oldest first, with what superseded what
    hub proposal create --kind goal_wording|goal_kpi|kpi_definition|kpi_target|flag [--goal ID] [--kpi ID]
                        (--payload '{json}'|--payload-file f.json) [--reason "..."]
                                           a change you may not make yourself, for the owner to confirm
    hub proposal list [--status pending|confirmed|rejected|all] [--goal ID] [--kpi ID]
    hub proposal decide <id> confirm|reject [--note "..."]   a person's own decision; a bot is refused
    hub approval request --kind send|spend|publish|merge --payload-file f.json [--task ID]
                                           if the owner already said send in Tico, skip this and
                                           `mail send --approve <their-message-id>`
    hub approval show <id>
    hub listen save --file run.json        Listening: one sweep and the posts it saw (status ok|blocked|
                                           rate_limited|error; a post already saved is kept as it was)
    hub listen decide [--limit 20] [--item ID]
                                           put the listening-item decisions to new posts and route them to the inboxes
                                           (`hub listen judge` is the old name and still works)
    hub listen show <item-id>              a post, the run that saw it, its judgments, where it went
    hub listen runs [--since DATE] [--source x]
    hub listen stats [--since DATE]        coverage by source, precision by inbox
    hub intake list [--destination D] [--status new]
                                           posts Listening routed to you, oldest first
    hub intake resolve <id> --status accepted --ref <your record> | rejected --reason "..." |
                    duplicate --ref <existing>
    hub history <conversation-id> [--before MSG] [--since MSG]
                                           what was said in a conversation, oldest first, 200 a page;
                                           the turn prompt names the conversation
    hub tools list [--bot X]               what a bot uses: model, repository, each declared access entry
    hub tools add <bot> <service> --can read[,post] [--identity "..."] [--scope database=warehouse ...]
                    [--env VAR_NAME] [--note "..."]
                                           register a tool: BotOps gets a task with the entry; it shows pending
                                           until the computer reports it. A variable's name, never its value
    hub tools remove <bot> <tool-id>       ask BotOps to remove one (or withdraw a pending request)
    hub routine list [--bot X]              the routines a bot runs on a schedule (yours by default)
    hub routine set <key> --title "..." (--cron "0 7 * * 1-5" | --on meeting.ready)
                    [--text "..."|--text-file f] [--timezone Z] [--bot X] [--disabled]
                                           create or update one by its key; the hub's row is the routine
    hub routine update <id> [--title ...] [--text ...|--text-file f] [--cron ...|--on ...]
                    [--timezone Z] [--enable|--disable]
    hub routine delete <id>
    hub status set "<focus>" [--state waiting_human|blocked|...] [--task ID] [--bot X]
    hub status list [--team marketing]
    hub status history <bot> [--since 7d]
    hub turns <bot> [--since 24h]
    hub inbox
    hub board
    hub org [--person ID] [--team NAME]    people and bots: who they are, Slack, what they own
    hub fleet                              actor-scoped live snapshot (Tico)
    hub calendar upcoming [--calendar EMAIL]
                                           appointments visible on a company calendar
    hub calendar schedule --title "..." --start ISO --end ISO [--calendar EMAIL]
                    [--attendee EMAIL ...] [--description "..."] [--no-meet]
                                           queue one idempotent calendar invitation
    hub calendar status <action-id>        whether the provider confirmed the event
    hub sql "<select>" [--json|--csv] [--max-rows N] [--param key=value ...]
                                           read-only SQL, what you may see (docs/hub-sql.md)
    hub db list | doctor [name]            the company databases this bot may read, and a health check
    hub db <name> "<select>" [--param k=v ...] [--json|--csv] [--max-rows N] [--timeout S]
    hub db <mongo> find <collection> ['<filter>'] [--projection J] [--sort J] [--limit N] | aggregate <collection> '<pipeline>'
                   | count <collection> ['<filter>'] | distinct <collection> <field> | collections
    hub db <name> --query <id> [--param k=v ...]
                                           read-only SQL on a company database, run on this computer
                                           with its credential; every query is audited (docs/databases.md)
    hub github create-bot-repo <slug> [--template OWNER/REPO | --empty]
                                           owner: create <org>/emp-<slug> from a template (docs/github-app.md)
    hub integrations                       every integration: how to reach it, credentials, counts
    hub integration <service>              the page, its query index and the learnings (plain text)
    hub queries <service> [term] [--id ID] search a query catalog; --id prints the SQL and params
    hub learn <service> "<text>"           add a shared learning under an integration page
    hub decisions --set <name> --state-file s.json [--option covered=opts.json] [--label L]
                                           ask the decision model typed questions about a state (questions/README.md);
                                           --questions-file q.json instead of --set; --list shows the sets
                                           (`hub judge` is the old name and still works)
    hub docs ask "<question>" [--wait 120] ask the Librarian about the company's docs: {answer, citations, covered}
    hub docs fetch <url> [--max-chars N]   read one public link (web page, Google Doc, Drive folder, GitHub repo,
                                           sitemap) as text; runs on this computer, public addresses only
    hub catalog                            the bot templates this company can pick from
    hub bot create <slug> --template T [--name "Display"]
                                           set a chosen bot up in the workspace (BotOps only)
    hub bot check <slug>                   what preflight would still refuse about that repository
    hub bot register <slug> [--name N] [--description D] [--reports-to R] [--template T]
                                           register a new bot with the server (planned), as the requester (BotOps)
    hub bot access <slug> [--see V] [--read V] [--write V]
                                           show or set who sees, reads, writes (V: everyone, or ben,team:legal,bot:x)
    hub bot owners <slug> [--add P ...] [--remove P ...]
                                           add or remove the people who own a bot, as the requester (BotOps)
    hub bot onboarded [slug]               a starter bot marks itself onboarded once a person approved its first routine
    hub people add <email> [--name N] [--title T] [--reports-to P]
                                           add a person to the roster and sign-in list (a Confirm card first)
                                           (`hub person add` is the same)
    hub people list                        the people on the roster
    hub api GET|POST|PUT|PATCH|DELETE <path> ['{json}']
                                           BotOps: any v2 route, as the person who asked; a Confirm card for what
                                           always needs their click. Never a secret in the body
    hub bot place <bot> [--computer <label|id>]
                                           put a bot on a computer: the one named, or the best one that takes it
    hub bot go-live <bot> [--computer C] [--no-setup]
                                           place it if needed, turn it on, start its setup
    hub bot model <bot> [<model>] [--effort E]
                                           list the models, or change the bot's
    hub bot pause|resume <bot>             stop or restart a bot (resume places one that has no computer)
    hub routine on|off <key|id> --bot <bot>  turn a routine on or off
    hub computers                          the computers a bot may go on, and what runs on each
    hub fleet-check                        what is wrong with the bots, most urgent first, each with its fix
    hub credential request <ENV> [--for-bot B] [--label "your Jira login"] [--format "you@x.com:API token"]
                    [--help-url https://...] [--kind api_key|token|password]
                                           open a card in the chat for the person to type the secret into
    hub credential set <ENV> --for-bot B [--name N] [--kind K] [--username U] [--no-redact]
                                           store a secret a person gave you (read from stdin, never the command line)
    hub credential list                    names, variables and which bots have each; never a value
    hub message redact <message-id> [--label L]   take a secret (read from stdin) out of a message
    hub support file "<message>"           tell the Tico team about a gap or fault (a Confirm card first)

Exit codes: 0 fine, 2 `{"refused": <rule>, "detail": "..."}` or a non-retryable API error,
1 `{"error": "..."}` (bad arguments, no identity, or the API could not be reached).

Identity (§3): a bot is `HUB_EMPLOYEE` + `HUB_TOKEN` from the turn's environment; the runner
sets both, with `HUB_API_URL` and `HUB_WORKSPACE` (where this company's bot repositories live),
for every turn. There is no `--as`. `--human <id>` is still
parsed so an old command line is not misread, and the API refuses it: remote identity comes
from authentication. Outside a turn, `hub sql` and the integration reads (`integrations`, `integration`,
`queries`) fall back to this Mac's runner credential (`~/.config/tico/runner.json`); `sql`
queries as the person who registered it. A person's own script sets `HUB_API_URL` and a personal
API token as `HUB_TOKEN` (Settings, Devices, API tokens) and no `HUB_EMPLOYEE`: every command is
then that person (docs/how-it-works.md, "Calling the API from a script").
"""
import argparse
import json
import os
import sys
from pathlib import Path

if __package__ in (None, ""):                          # run as a script: python clients/hubcli.py
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

# Mirrors of the server's vocabulary (backend/hubdb.py), so a typo is refused by the parser
# before a request is made. The server is the authority when they disagree.
TASK_STATUSES = ("open", "doing", "waiting", "review", "ready", "done", "closed", "declined")
APPROVAL_KINDS = ("send", "spend", "publish", "merge")
GOAL_STATUSES = ("red", "yellow", "green", "done", "dropped")     # set by hand; gray is only ever automatic


class CliError(Exception):
    """Anything the arguments or the environment got wrong: exit 1."""


def out(obj):
    print(json.dumps(obj, indent=2, default=str, sort_keys=False))
    return 0


def body_of(args):
    if getattr(args, "body_file", None):
        return Path(args.body_file).read_text()
    return args.body or ""


# ----------------------------------------------------------------------------- dry run
# The rules are the server's own functions (backend/hubdb.py) run client-side, so a dry run
# reads exactly as the real create would. They are imported only here: the module is pure
# stdlib, opens no database, and the rest of the CLI never touches backend/.
def words_outside_quotes(text):
    """What rule 7 counts: hubdb's own helper, so the number a dry run prints is the number the
    lint would refuse on (quoted `>` lines and URLs do not count)."""
    from backend import hubdb as H
    return len(H._outside_quotes(text).split())


def owner_from_registry(name):
    """The owner as an actor string, read from the registry files the cloud seeds its roster
    from; None when it is in neither. The CLI has no database to resolve against (§3) and
    must not open one."""
    from backend import hubdb as H, people as P
    from clients import registry as REG
    raw = str(name or "").strip()
    if H.actor_kind(raw) in ("bot", "human"):
        return raw
    try:
        emps = {e["name"] for e in REG.load_registry()[1] if e.get("name")}
        roster = P.load(REG.load_people())
    except Exception:               # a CLI that cannot read the registry still answers
        emps, roster = set(), None
    if raw in emps:
        return H.bot_actor(raw)
    if P.person(raw, roster):
        return H.human_actor(raw)
    return None


def task_problems(actor, owner, title, body):
    """(resolved owner, the problems the server's `task_create` would refuse on), writing none.

    The owner's kind comes from the registry files; the lint (`lint_human_item`) and the reach
    rule (`classify`) are hubdb's own functions run here. Reach against live state and the
    duplicate check are the hub's to decide at the real create.
    """
    from backend import hubdb as H
    problems = []
    title, body = str(title or "").strip(), str(body or "")
    target = owner_from_registry(owner)
    if not target:
        problems.append(f"{owner} is not in registry/employees.yaml or registry/people.yaml")
    if H.is_bot(actor) and H.classify(f"{title}\n{body}", to_actor=target) == "escape":
        problems.append("the task reaches outside the hub (rule 8): a real create is refused "
                        "and quarantines you")
    if H.is_human(target):
        problems += H.lint_human_item(body, title=title)
    elif not title:
        problems.append("give it a title that says what you are asking for")
    if H.is_bot(actor):
        # plain-English titles: a warning this week, a refusal once TICO_TITLE_LINT=refuse
        problems += [f"{p} (title lint, {H.TITLE_LINT})" for p in H.lint_title(title)]
    return target, problems


def cmd_task_dry_run(args, who):
    """`hub task create --dry-run`: print what a create would be refused for; write nothing.

    No database is opened and no request is made; the owner's kind comes from the registry
    files and the same lint runs here, so a bot on the cloud API can size a human item before
    it spends a turn on a refusal. Prints lines rather
    than JSON: `- <problem>` per problem and exit 1, or one `ok:` line.
    """
    from backend import hubdb as H
    if not os.environ.get("HUB_API_URL"):
        raise CliError("HUB_API_URL is not set: `hub` talks to the Tico API and runs inside a "
                       "bot turn, where the runner sets HUB_API_URL, HUB_TOKEN and HUB_EMPLOYEE")
    if who:
        raise CliError("--human is unavailable with HUB_API_URL; remote identity is the token")
    slug = (os.environ.get("HUB_EMPLOYEE") or "").strip()
    actor = H.bot_actor(slug) if slug else None
    body = body_of(args)
    owner, problems = task_problems(actor, args.owner, args.title, body)
    if problems:
        print("\n".join(f"- {p}" for p in problems))
        return 1
    print(f'ok: would create "{args.title.strip()}" for {owner} '
          f'({words_outside_quotes(body)} words outside quoted drafts)')
    return 0


# ----------------------------------------------------------------------------- parser
def parser():
    p = argparse.ArgumentParser(prog="hub", description="the company hub: messages, tasks, status")
    sub = p.add_subparsers(dest="cmd")

    sub.add_parser("whoami").set_defaults(fn="whoami")

    context = sub.add_parser("context", help="search company documents and market knowledge").add_subparsers(dest="sub")
    s = context.add_parser("search")
    s.add_argument("q")
    s.add_argument("--source", choices=["all", "docs", "market"], default="all")
    s.add_argument("--limit", type=int, default=20)
    s.set_defaults(fn="context search")
    s = context.add_parser("show")
    s.add_argument("id")
    s.set_defaults(fn="context show")
    meetings = sub.add_parser("meetings",
                              help="search meetings, read transcripts, import a transcript from another tool").add_subparsers(dest="sub")
    s = meetings.add_parser("search")
    s.add_argument("q", nargs="?", default="")
    s.add_argument("--person", default="")
    s.add_argument("--since")
    s.add_argument("--until")
    s.add_argument("--limit", type=int, default=20)
    s.add_argument("--offset", type=int, default=0)
    s.set_defaults(fn="meetings search")
    s = meetings.add_parser("transcript")
    s.add_argument("id")
    s.add_argument("--offset", type=int, default=0)
    s.add_argument("--limit", type=int, default=20000)
    s.set_defaults(fn="meetings transcript")
    s = meetings.add_parser("import", help="file a transcript (text, WebVTT, SRT or JSON segments) as one of your meetings")
    s.add_argument("file", help="the transcript file; - reads standard input")
    s.add_argument("--title", help="default: the file's name")
    s.add_argument("--date", help="when it started: 2026-09-28 or 2026-09-28T16:00 (this Mac's time zone) or with an offset")
    s.add_argument("--participant", dest="participants", action="append", help="an email or a name; repeat for each")
    s.add_argument("--source", default="upload", help="where it came from: zoom, granola, otter, fireflies... (default upload)")
    s.add_argument("--external-id", help="that system's id for it: importing it again updates the meeting")
    s.add_argument("--format", choices=["auto", "text", "vtt", "srt", "json"], default="auto")
    s.add_argument("--notes-file", help="a Markdown file of notes or a summary")
    s.add_argument("--media-url", help="an https link to the recording, if there is one")
    s.add_argument("--send-to", help="a bot to hand the meeting to, as Send does")
    s.add_argument("--private", action="store_true", default=None)
    s.set_defaults(fn="meetings import")

    s = sub.add_parser("say")
    s.add_argument("to")
    s.add_argument("text")
    s.add_argument("--conversation")
    s.add_argument("--ref", action="append")
    s.set_defaults(fn="say")

    s = sub.add_parser("ask")
    s.add_argument("words", nargs="*")
    s.add_argument("--wait", type=float, default=60)
    s.set_defaults(fn="ask")

    s = sub.add_parser("answer")
    s.add_argument("message_id")
    s.add_argument("text", nargs="?", default="")
    s.add_argument("--unknown")
    s.set_defaults(fn="answer")

    s = sub.add_parser("notice")
    s.add_argument("to")
    s.add_argument("text")
    s.set_defaults(fn="notice")

    s = sub.add_parser("note", help="leave a bot a quiet note: no run now, its next run reads it")
    s.add_argument("to")
    s.add_argument("text", nargs="?", default="")
    s.add_argument("--text-file", dest="text_file")
    s.set_defaults(fn="note")
    s = sub.add_parser("notes", help="quiet notes, newest first: left for you and by you")
    s.add_argument("--to")
    s.add_argument("--from", dest="sender")
    s.add_argument("--since", help="an ISO time, or 24h / 3d")
    s.add_argument("--waiting", action="store_true", help="only notes no run has carried yet")
    s.add_argument("--limit", type=int, default=200)
    s.set_defaults(fn="notes")
    s = sub.add_parser("unnote", help="take back a note no run has carried yet")
    s.add_argument("id")
    s.set_defaults(fn="unnote")

    files = sub.add_parser("files", help="what you publish for people: reports, documents, imported objects").add_subparsers(dest="sub")
    s = files.add_parser("list", help="the files on your page, newest activity first")
    s.add_argument("--bot")
    s.add_argument("--limit", type=int)
    s.add_argument("--cursor")
    s.set_defaults(fn="files list")
    s = files.add_parser("publish", help="upload a file from this checkout (reports/x.md); again adds a version")
    s.add_argument("path")
    s.add_argument("--title")
    s.add_argument("--task", help="the task it is for; defaults to the one you are working on")
    s.add_argument("--scope", choices=["task", "bot"])
    s.set_defaults(fn="files publish")
    s = files.add_parser("add-link", help="list a Google Doc, Notion page, Figma file or any https link")
    s.add_argument("url")
    s.add_argument("--title")
    s.add_argument("--task")
    s.add_argument("--scope", choices=["task", "bot"])
    s.set_defaults(fn="files add-link")
    s = files.add_parser("touch", help="you edited a linked document again: move it to the top")
    s.add_argument("target", help="a file id or its https link")
    s.set_defaults(fn="files touch")
    s = files.add_parser("import", help="copy an s3:// object with this computer's credentials into Tico")
    s.add_argument("uri")
    s.add_argument("--title")
    s.add_argument("--task")
    s.set_defaults(fn="files import")
    docs = sub.add_parser("docs", help="the company's docs: read, search and write internal docs, list linked ones, ask the Librarian").add_subparsers(dest="sub")
    s = docs.add_parser("list", help="internal docs by path")
    s.add_argument("--prefix", help="only paths starting with this, e.g. sales/")
    s.add_argument("--limit", type=int)
    s.set_defaults(fn="docs list")
    s = docs.add_parser("read", help="one internal doc in full")
    s.add_argument("ref", help="a doc id or a path; manual:<name> for a page of the Tico manual")
    s.set_defaults(fn="docs read")
    s = docs.add_parser("search", help="search internal and linked docs, then the Tico manual")
    s.add_argument("q")
    s.add_argument("--limit", type=int)
    s.add_argument("--manual", dest="collection", action="store_const", const="manual",
                   help="only the read-only Tico manual (how to do something in Tico)")
    s.set_defaults(fn="docs search")
    s = docs.add_parser("write", help="create or replace an internal doc at a path")
    s.add_argument("path")
    s.add_argument("--title")
    s.add_argument("--body-file", dest="body_file", help="the Markdown file; standard input when omitted")
    s.add_argument("--note", help="one line on what changed")
    s.set_defaults(fn="docs write")
    s = docs.add_parser("history", help="the versions of a doc")
    s.add_argument("ref", help="a doc id or a path")
    s.set_defaults(fn="docs history")
    s = docs.add_parser("links", help="the linked docs: where the company's other docs live")
    s.set_defaults(fn="docs links")
    assistant = sub.add_parser("assistant", help="the Assistant's proposals for a person to confirm").add_subparsers(dest="sub")
    s = assistant.add_parser("propose", help="ask the person to confirm one side-effecting operation")
    s.add_argument("--summary", required=True)
    s.add_argument("--path", required=True)
    s.add_argument("--method", default="POST", choices=["POST", "PUT", "PATCH", "DELETE"])
    s.add_argument("--body", default="{}", help="the request's JSON body")
    s.set_defaults(fn="assistant propose")
    task = sub.add_parser("task").add_subparsers(dest="sub")
    s = task.add_parser("create")
    s.add_argument("--owner", required=True)
    s.add_argument("--title", required=True)
    s.add_argument("--body", default="")
    s.add_argument("--body-file", dest="body_file")
    s.add_argument("--due")
    s.add_argument("--parent")
    s.add_argument("--label", action="append", help="a label (repeat, or comma-separate); a project is a label")
    s.add_argument("--top", action="store_true", help="put it at the top of the owner's queue")
    s.add_argument("--link", action="append", help="a URL to attach (a pull request, an issue, a document)")
    s.add_argument("--goal", help="the goal this task serves (hub goals); optional")
    s.add_argument("--next-run", "--quiet", dest="next_run", action="store_true",
                   help="for a bot: do not wake it; its next run, whatever starts it, carries this task")
    s.add_argument("--dry-run", dest="dry_run", action="store_true",
                   help="print the checks a create would fail and write nothing")
    s.set_defaults(fn="task create")
    s = task.add_parser("ask")
    s.add_argument("id")
    s.add_argument("text")
    s.set_defaults(fn="task ask")
    s = task.add_parser("update")
    s.add_argument("id")
    s.add_argument("--status", choices=list(TASK_STATUSES))
    s.add_argument("--note")
    s.add_argument("--owner")
    s.add_argument("--due")
    s.add_argument("--blocked-by", dest="blocked_by", help="the task this one waits on; '' clears it")
    s.add_argument("--goal", help='the goal this task serves; "" takes it off')
    s.set_defaults(fn="task update")
    s = task.add_parser("comment", help="leave a comment on a task, on the record with your name")
    s.add_argument("id")
    s.add_argument("text")
    s.set_defaults(fn="task comment")
    s = task.add_parser("link", help="attach a link: the pull request you opened, an issue, a document")
    s.add_argument("id")
    s.add_argument("url")
    s.add_argument("--title")
    s.set_defaults(fn="task link")
    s = task.add_parser("label", help="add or remove labels on a task")
    s.add_argument("id")
    s.add_argument("--add", action="append")
    s.add_argument("--remove", action="append")
    s.set_defaults(fn="task label")
    s = task.add_parser("close")
    s.add_argument("id")
    s.add_argument("--note")
    s.set_defaults(fn="task close")
    s = task.add_parser("attach", help="attach a file to a task; prints the link for your note")
    s.add_argument("id")
    s.add_argument("file")
    s.add_argument("--name", help="the name people see; defaults to the file's own")
    s.set_defaults(fn="task attach")
    s = task.add_parser("list")
    s.add_argument("--owner")
    s.add_argument("--requester")
    s.add_argument("--status", action="append", choices=list(TASK_STATUSES))
    s.add_argument("--lane", choices=["company", "product"])
    s.add_argument("--label")
    s.set_defaults(fn="task list")
    s = task.add_parser("show")
    s.add_argument("id")
    s.set_defaults(fn="task show")
    s = task.add_parser("stuck", help="every bot's open work untouched for a day and waiting on nobody (BotOps's sweep)")
    s.add_argument("--hours", type=int, default=24)
    s.set_defaults(fn="task stuck")
    s = task.add_parser("run", help="start a bot's task now, as the task")
    s.add_argument("id")
    s.set_defaults(fn="task run")

    s = sub.add_parser("goals", help="what you are for: your goals, the chain above them, your reports' goals")
    s.add_argument("--owner", help="someone else's: a bot slug or a person id")
    s.add_argument("--all", action="store_true", help="every live goal in the company")
    s.add_argument("--status", help="with --all: only these, comma-separated (red,yellow,green,gray,done,dropped)")
    s.set_defaults(fn="goals")
    goal = sub.add_parser("goal", help="one goal: show it, propose one, set its colour, edit it").add_subparsers(dest="sub")
    s = goal.add_parser("show")
    s.add_argument("id")
    s.set_defaults(fn="goal show")
    s = goal.add_parser("create", help="set a goal; a parent is optional, and whoever owns it gives the first colour")
    s.add_argument("--owner", required=True, help="me, a bot slug, or a person id (company: a company goal, the owner only)")
    s.add_argument("--title", required=True)
    s.add_argument("--parent", help="the goal this one supports, if any; not needed")
    s.add_argument("--body", default="")
    s.add_argument("--body-file", dest="body_file")
    s.add_argument("--top", action="store_true", help="put it first in the owner's order")
    s.set_defaults(fn="goal create")
    s = goal.add_parser("status", help="set the colour by hand: red, yellow or green with one sentence, done or dropped "
                                     "when it ends; it sticks until a person hands it back (hub goal auto)")
    s.add_argument("id")
    s.add_argument("status", choices=list(GOAL_STATUSES))
    s.add_argument("note", nargs="?", default="")
    s.set_defaults(fn="goal status")
    s = goal.add_parser("update")
    s.add_argument("id")
    s.add_argument("--title")
    s.add_argument("--body")
    s.add_argument("--body-file", dest="body_file")
    s.add_argument("--parent", help='the goal it supports; "" unlinks it')
    s.add_argument("--owner")
    s.add_argument("--rank", type=int)
    s.add_argument("--top", action="store_true")
    s.set_defaults(fn="goal update")
    s = goal.add_parser("auto", help="let the Goal Manager set the colour again (ends a colour set by hand)")
    s.add_argument("id")
    s.set_defaults(fn="goal auto")
    s = goal.add_parser("refresh", help="the Goal Manager's status pass: work automatic colours out again")
    s.add_argument("--goal", action="append", dest="goal_ids", help="only this goal; repeatable")
    s.set_defaults(fn="goal refresh")
    s = goal.add_parser("checkin", help="how the owner says the goal is going, in their words")
    s.add_argument("id")
    s.add_argument("body")
    s.add_argument("--signal", choices=["on_track", "at_risk", "off_track"])
    s.add_argument("--from", dest="from_actor", help="whose words these are, when you record them for someone")
    s.add_argument("--kpi", dest="kpi_id", help="the KPI that prompted it")
    s.set_defaults(fn="goal checkin")
    s = goal.add_parser("checkins", help="a goal's check-ins, newest first")
    s.add_argument("id")
    s.set_defaults(fn="goal checkins")
    s = goal.add_parser("needs-you", help="red KPIs on your goals, stale KPIs you own, proposals to confirm")
    s.set_defaults(fn="goal needs-you")
    def target_flags(s):
        s.add_argument("--baseline", type=float, help="improvement: where it starts (default the latest reading)")
        s.add_argument("--target", type=float, help="improvement: the value to reach; needs --deadline")
        s.add_argument("--deadline", help="improvement: when the target is due, YYYY-MM-DD")
        s.add_argument("--min", type=float, help="range: the lowest acceptable value")
        s.add_argument("--max", type=float, help="range: the highest acceptable value")

    def kpi_flags(s):
        s.add_argument("--definition", help="what exactly is counted, in a sentence")
        s.add_argument("--unit")
        s.add_argument("--direction", choices=["up", "down", "range"], help="which way is good")
        s.add_argument("--cadence", choices=["daily", "weekly", "monthly"], help="how often it is read")
        s.add_argument("--source-note", dest="source_note", help="where the number comes from")

    kpi = sub.add_parser("kpi", help="a measure on its own that goals link to, and its readings").add_subparsers(dest="sub")
    s = kpi.add_parser("list", help="KPIs with latest reading and colour")
    s.add_argument("--goal", dest="goal_id", help="only the KPIs this goal uses")
    s.add_argument("--owner", help="only this owner's: me, a bot slug or a person id")
    s.add_argument("--unlinked", action="store_true", help="only the KPIs no goal uses")
    s.add_argument("--bot", help="a bot slug: its five automatic KPIs")
    s.set_defaults(fn="kpi list")
    s = kpi.add_parser("show", help="definition and versions, the goals using it, every reading, check-ins")
    s.add_argument("id")
    s.set_defaults(fn="kpi show")
    s = kpi.add_parser("add", help="make a KPI; with --goal it is linked, the target on the link")
    s.add_argument("name", help="what is counted, per what: 'booked demos per two weeks'")
    s.add_argument("--goal", dest="goal_id", help="link it to this goal")
    s.add_argument("--owner", help="me (default), company, a bot slug or a person id")
    kpi_flags(s)
    target_flags(s)
    s.set_defaults(fn="kpi add")
    s = kpi.add_parser("update", help="a change to what it measures is a new definition version")
    s.add_argument("id")
    s.add_argument("--name")
    s.add_argument("--owner")
    kpi_flags(s)
    s.set_defaults(fn="kpi update")
    s = kpi.add_parser("link", help="link a goal to a KPI, or change the target on the link")
    s.add_argument("goal_id")
    s.add_argument("kpi_id")
    target_flags(s)
    s.set_defaults(fn="kpi link")
    s = kpi.add_parser("unlink", help="take a KPI off a goal")
    s.add_argument("goal_id")
    s.add_argument("kpi_id")
    s.set_defaults(fn="kpi unlink")
    s = kpi.add_parser("log", help="a reading: a fact with its period; to correct one, supersede it")
    s.add_argument("kpi_id")
    s.add_argument("value", type=float)
    s.add_argument("note", nargs="?", default="")
    s.add_argument("--period-start", dest="period_start", help="start of the period it describes")
    s.add_argument("--period-end", dest="period_end", help="end of the period it describes; default now")
    s.add_argument("--at", help="the old name of --period-end")
    s.add_argument("--collected-at", dest="collected_at", help="when it was collected; default now")
    s.add_argument("--evidence", help="a link or a note that shows where the value came from")
    s.add_argument("--quality", choices=["measured", "estimate", "partial"])
    s.add_argument("--estimate", action="store_true", help="the same as --quality estimate")
    s.add_argument("--source", help="a connector or system name (posthog, close)")
    s.add_argument("--definition-version", dest="definition_version", type=int)
    s.add_argument("--supersedes", help="the id of the reading this one corrects")
    s.set_defaults(fn="kpi log")
    s = kpi.add_parser("readings", help="every reading, oldest first, with what superseded what")
    s.add_argument("kpi_id")
    s.add_argument("--effective", action="store_true", help="leave out readings a correction replaced")
    s.set_defaults(fn="kpi readings")

    proposal = sub.add_parser("proposal", help="a change you may not make yourself, for the owner to confirm").add_subparsers(dest="sub")
    s = proposal.add_parser("create")
    s.add_argument("--kind", required=True, choices=["goal_wording", "goal_kpi", "kpi_definition", "kpi_target", "flag"])
    s.add_argument("--goal", dest="goal_id")
    s.add_argument("--kpi", dest="kpi_id")
    s.add_argument("--payload", help="the proposed change, as JSON")
    s.add_argument("--payload-file", dest="payload_file")
    s.add_argument("--reason", default="")
    s.set_defaults(fn="proposal create")
    s = proposal.add_parser("list")
    s.add_argument("--status", choices=["pending", "confirmed", "rejected", "all"], default="pending")
    s.add_argument("--goal", dest="goal_id")
    s.add_argument("--kpi", dest="kpi_id")
    s.set_defaults(fn="proposal list")
    s = proposal.add_parser("decide", help="a person's own decision; a bot is refused")
    s.add_argument("id")
    s.add_argument("decision", choices=["confirm", "reject"])
    s.add_argument("--note", default="")
    s.set_defaults(fn="proposal decide")

    market = sub.add_parser("market", help="the shared market graph: read it, report into it, curate it").add_subparsers(dest="sub")
    s = market.add_parser("show", help="one entity, its edges both ways, the evidence, the last ten events")
    s.add_argument("id")
    s.set_defaults(fn="market show")
    s = market.add_parser("find", help="names, aliases, summaries, and evidence")
    s.add_argument("text")
    s.set_defaults(fn="market find")
    s = market.add_parser("edges", help="graph rows; symmetric relations are returned from either end")
    s.add_argument("--from", dest="src")
    s.add_argument("--to", dest="dst")
    s.add_argument("--rel")
    s.add_argument("--as-of", dest="as_of")
    s.set_defaults(fn="market edges")
    s = market.add_parser("delta", help="what changed, grouped by entity")
    s.add_argument("--since", default="7d")
    s.set_defaults(fn="market delta")
    s = market.add_parser("ask", help="a question answered from the graph, with citations")
    s.add_argument("question")
    s.set_defaults(fn="market ask")
    s = market.add_parser("report", help="prose only; this does not change the graph")
    s.add_argument("--kind", required=True, choices=["new-entity", "edge", "property-change", "correction", "question", "other"])
    s.add_argument("--about", default="")
    s.add_argument("--claim", required=True)
    s.add_argument("--source", default="")
    s.add_argument("--quote", default="")
    s.add_argument("--confidence", default="medium", choices=["high", "medium", "low"])
    s.add_argument("--urgent", action="store_true")
    s.add_argument("--source-ref", dest="source_ref", help="where it came from, e.g. the intake item id")
    s.set_defaults(fn="market report")
    s = market.add_parser("resolve", help="close an insight: applied, merged, rejected, or needs-human")
    s.add_argument("id")
    s.add_argument("--status", required=True, choices=["applied", "merged", "rejected", "needs-human"])
    s.add_argument("--resolution", default="")
    s.add_argument("--event", action="append", dest="events", default=[])
    s.set_defaults(fn="market resolve")
    s = market.add_parser("apply", help="write evidence first, then the entity or edge, and mark the insight applied")
    s.add_argument("id")
    s.add_argument("--source", default="")
    s.add_argument("--source-kind", dest="source_kind", default="other")
    s.add_argument("--quote", default="")
    s.add_argument("--our-read", dest="our_read", default="")
    s.add_argument("--entity-type", dest="entity_type")
    s.add_argument("--entity-name", dest="entity_name")
    s.add_argument("--entity-id", dest="entity_id")
    s.add_argument("--summary")
    s.add_argument("--tier", choices=["core", "lookalike", "phrase-stealer", "secondary"], help="for a new company")
    s.add_argument("--new-id", dest="new_id", help="the id for a new entity when the default type/name-slug is wrong, e.g. company/self")
    s.add_argument("--edge-src", dest="edge_src")
    s.add_argument("--edge-rel", dest="edge_rel")
    s.add_argument("--edge-dst", dest="edge_dst")
    s.set_defaults(fn="market apply")
    s = market.add_parser("sweep", help="one owner task for needs-human, listening tasks for unverified stale entities")
    s.add_argument("--today")
    s.add_argument("--unverified", action="append", default=[], help="entity-id=what to look for")
    s.set_defaults(fn="market sweep")
    s = market.add_parser("refresh", help="rewrite the weekly delta from market events; only a Monday changes it")
    s.add_argument("--today")
    s.set_defaults(fn="market refresh")
    s = market.add_parser("page", help="rewrite one market page (overview, coverage-universe, ...) from a Markdown file")
    s.add_argument("name", help="overview, structure-and-size, coverage-universe, people-who-matter, channels, "
                                "regulation-and-catalysts, theses or open-questions")
    s.add_argument("--body-file", dest="body_file", required=True, help="the whole page in Markdown; - reads stdin")
    s.set_defaults(fn="market page")

    listen = sub.add_parser("listen", help="Listening's saved posts: save a sweep, decide where each post goes, trace a post").add_subparsers(dest="sub")
    s = listen.add_parser("save", help="one sweep of one query and the posts it saw, from a JSON file")
    s.add_argument("--file", required=True, help="JSON: {source, query, status, note, pages_read, items: [...]}; - for stdin")
    s.set_defaults(fn="listen save")
    s = listen.add_parser("decide", aliases=["judge"], help="put the listening-item decisions to new posts and route them to the inboxes")
    s.add_argument("--limit", type=int, default=20)
    s.add_argument("--item", action="append", dest="item_ids", default=[])
    s.set_defaults(fn="listen decide")
    s = listen.add_parser("show", help="a post, its run, its decisions, and where it went")
    s.add_argument("id")
    s.set_defaults(fn="listen show")
    s = listen.add_parser("runs", help="sweeps, newest first, with ok/blocked/rate_limited/error")
    s.add_argument("--since")
    s.add_argument("--source")
    s.set_defaults(fn="listen runs")
    s = listen.add_parser("stats", help="coverage by source and precision by inbox")
    s.add_argument("--since")
    s.set_defaults(fn="listen stats")

    intake = sub.add_parser("intake", help="posts Listening routed to you: list them, then accept or reject each").add_subparsers(dest="sub")
    s = intake.add_parser("list", help="your inbox, oldest first")
    s.add_argument("--destination")
    s.add_argument("--status", default="new", choices=["new", "accepted", "rejected", "duplicate"])
    s.add_argument("--limit", type=int, default=100)
    s.set_defaults(fn="intake list")
    s = intake.add_parser("resolve", help="accepted --ref <your record>, duplicate --ref <existing>, or rejected --reason")
    s.add_argument("id")
    s.add_argument("--status", required=True, choices=["accepted", "rejected", "duplicate"])
    s.add_argument("--ref", dest="receiver_ref", default="")
    s.add_argument("--reason", default="")
    s.set_defaults(fn="intake resolve")

    s = sub.add_parser("history", help="what was said in a conversation; the turn prompt names it")
    s.add_argument("conversation")
    s.add_argument("--before", help="the page before this message id")
    s.add_argument("--since", help="only messages after this message id")
    s.set_defaults(fn="history")

    tools = sub.add_parser("tools", help="what a bot uses: its model, repository and declared access (docs/creating-bots.md)").add_subparsers(dest="sub")
    s = tools.add_parser("list", help="a bot's tools with their status; yours by default")
    s.add_argument("--bot")
    s.set_defaults(fn="tools list")
    s = tools.add_parser("add", help="register a tool: BotOps adds it to employee.yaml; never a credential value")
    s.add_argument("bot")
    s.add_argument("service", help="a short name such as posthog or google-calendar")
    s.add_argument("--can", required=True, help="read, draft, post, act, use, send or write; comma separated")
    s.add_argument("--identity", help="who it acts as, in words for a person")
    s.add_argument("--scope", action="append", metavar="KEY=VALUE", help="database=warehouse, channels=#a,#b, project=123; repeatable")
    s.add_argument("--env", help="the variable's NAME, such as POSTHOG_KEY; the operator installs the value")
    s.add_argument("--note")
    s.set_defaults(fn="tools add")
    s = tools.add_parser("remove", help="ask BotOps to remove a tool, or withdraw a pending request")
    s.add_argument("bot")
    s.add_argument("id", help="the tool id from `hub tools list`")
    s.set_defaults(fn="tools remove")

    routine = sub.add_parser("routine", help="what this bot is told on a schedule (docs/routines.md)").add_subparsers(dest="sub")
    s = routine.add_parser("list")
    s.add_argument("--bot", help="another bot's routines; yours by default")
    s.set_defaults(fn="routine list")
    s = routine.add_parser("set", help="create a routine, or update the one with this key")
    s.add_argument("key", help="a stable name, letters, digits, dots, dashes or underscores")
    s.add_argument("--title", required=True)
    s.add_argument("--cron", help="five fields, in --timezone (America/Los_Angeles by default)")
    s.add_argument("--on", help="a hub event instead of a time: meeting.ready")
    s.add_argument("--text", default="", help="what the bot is told each time")
    s.add_argument("--text-file", dest="text_file")
    s.add_argument("--timezone")
    s.add_argument("--bot", help="set it on another bot you operate; yourself by default")
    s.add_argument("--disabled", action="store_true", help="keep it, but do not run it yet")
    s.set_defaults(fn="routine set")
    s = routine.add_parser("update", help="change one routine by its id")
    s.add_argument("id", help="the routine id from `hub routine list`")
    s.add_argument("--title")
    s.add_argument("--text")
    s.add_argument("--text-file", dest="text_file")
    s.add_argument("--cron")
    s.add_argument("--on")
    s.add_argument("--timezone")
    switch = s.add_mutually_exclusive_group()
    switch.add_argument("--enable", action="store_true")
    switch.add_argument("--disable", action="store_true")
    s.set_defaults(fn="routine update")
    for name, word in (("on", "on"), ("off", "off")):
        s = routine.add_parser(name, help=f"turn a routine {word}")
        s.add_argument("routine", help="its key or id")
        s.add_argument("--bot", help="the bot it belongs to; yours by default")
        s.set_defaults(fn="routine " + name)
    s = routine.add_parser("delete")
    s.add_argument("id", help="the routine id from `hub routine list`")
    s.set_defaults(fn="routine delete")

    appr = sub.add_parser("approval").add_subparsers(dest="sub")
    s = appr.add_parser("request",
                        help="ask for a yes; if the owner already said send, mail send --approve <their message id>")
    s.add_argument("--kind", required=True, choices=list(APPROVAL_KINDS))
    s.add_argument("--payload-file", dest="payload_file")
    s.add_argument("--payload")
    s.add_argument("--task")
    s.set_defaults(fn="approval request")
    s = appr.add_parser("show")
    s.add_argument("id")
    s.set_defaults(fn="approval show")

    lv = sub.add_parser("live", help="talking to the hub on the go").add_subparsers(dest="sub")
    s = lv.add_parser("brief", help="alerts, who is waiting on you, what bots said since --since")
    s.add_argument("--since", help="an ISO date-time; default the last 12 hours")
    s.set_defaults(fn="live brief")
    s = lv.add_parser("stats", help="per-tool timing and answer size of assistants' calls")
    s.add_argument("--days", type=int)
    s.add_argument("--via", help="one assistant's token label, e.g. grok-bot")
    s.set_defaults(fn="live stats")
    bt = sub.add_parser("batch", help="a person's batch of what needs them: walk, respond, commit "
                                       "(backend/batch.py)").add_subparsers(dest="sub")
    s = bt.add_parser("start", help="start the batch of the bot that most needs you, or resume the one in progress")
    s.add_argument("--bot", help="only this bot's items (a slug)")
    s.add_argument("--all", action="store_true", help="every item from every bot in one batch")
    s.add_argument("--fresh", action="store_true", help="drop the batch in progress and build a new list")
    s.set_defaults(fn="batch start")
    s = bt.add_parser("next", help="the next item; at the end, the summary to read back")
    s.add_argument("batch")
    s.set_defaults(fn="batch next")
    s = bt.add_parser("respond", help="record a response to the current item; nothing applies until commit")
    s.add_argument("batch")
    s.add_argument("kind", choices=["decide", "needs_info", "instruct", "rule", "skip", "later"])
    s.add_argument("--text", default="")
    s.add_argument("--decision", choices=["approve", "decline", "done", "close", "answer"])
    s.add_argument("--item", type=int, help="another item's number")
    s.add_argument("--until", help="with later: an ISO date-time")
    s.set_defaults(fn="batch respond")
    s = bt.add_parser("commit", help="apply every recorded response")
    s.add_argument("batch")
    s.set_defaults(fn="batch commit")
    s = bt.add_parser("abandon", help="drop the batch without applying anything")
    s.add_argument("batch")
    s.set_defaults(fn="batch abandon")

    st = sub.add_parser("status").add_subparsers(dest="sub")
    s = st.add_parser("set")
    s.add_argument("focus")
    s.add_argument("--state")
    s.add_argument("--task")
    s.add_argument("--bot")
    s.set_defaults(fn="status set")
    s = st.add_parser("list")
    s.add_argument("--team")
    s.set_defaults(fn="status list")
    s = st.add_parser("history")
    s.add_argument("bot")
    s.add_argument("--since")
    s.set_defaults(fn="status history")

    s = sub.add_parser("turns")
    s.add_argument("bot")
    s.add_argument("--since")
    s.set_defaults(fn="turns")

    sub.add_parser("inbox").set_defaults(fn="inbox")
    s = sub.add_parser("ack", help="mark an inbox message as read (an external agent's own delivery)")
    s.add_argument("message_id")
    s.set_defaults(fn="ack")
    sub.add_parser("board").set_defaults(fn="board")
    s = sub.add_parser("org", help="the company org chart: people, Slack, what they own, bots under them")
    s.add_argument("--person", help="that person and everyone under them")
    s.add_argument("--team", help="a team name from the registry, like engineering or sales")
    s.set_defaults(fn="org")
    sub.add_parser("fleet").set_defaults(fn="fleet")
    sub.add_parser("fleet-check", help="what is wrong with the bots, most urgent first, each with its fix").set_defaults(fn="fleet-check")
    upd = sub.add_parser("update", help="post, read and reply to the bots' daily and weekly updates").add_subparsers(dest="sub")
    s = upd.add_parser("post", help="post your update when the hub asks for it: 1-5 plain-English bullets")
    s.add_argument("body", help="one to five lines, each starting with '- '")
    s.add_argument("--kind", choices=("daily", "weekly"))
    s.set_defaults(fn="update post")
    s = upd.add_parser("show")
    s.add_argument("update")
    s.set_defaults(fn="update show")
    s = upd.add_parser("read", help="mark updates read (--unread to mark them unread)")
    s.add_argument("ids", nargs="*")
    s.add_argument("--all", action="store_true")
    s.add_argument("--unread", dest="read", action="store_false")
    s.set_defaults(fn="update read")
    s = upd.add_parser("reply")
    s.add_argument("update")
    s.add_argument("text")
    s.set_defaults(fn="update reply")
    s = upd.add_parser("settings", help="turn a bot's daily or weekly update on or off")
    s.add_argument("bot")
    s.add_argument("--daily", choices=("on", "off"))
    s.add_argument("--weekly", choices=("on", "off"))
    s.set_defaults(fn="update settings")
    s = sub.add_parser("updates", help="the bots' updates, newest first")
    s.add_argument("--kind", choices=("daily", "weekly"))
    s.add_argument("--bot")
    s.add_argument("--unread", action="store_true")
    s.add_argument("--limit", type=int)
    s.set_defaults(fn="updates")
    grok = sub.add_parser("grokbot", help="your Grok Bots in Tico (docs/grok-bot-sync.md)").add_subparsers(dest="sub")
    s = grok.add_parser("sync", help="sync Grok Bots from a JSON file: {\"bots\": [...], \"source\": ...}")
    s.add_argument("--file", required=True, help="the JSON body hub_grokbot_sync takes")
    s.set_defaults(fn="grokbot sync")
    s = sub.add_parser("recent", help="the bots you have been working with lately and where each stands")
    s.add_argument("--days", type=int, help="how far back (default 7)")
    s.add_argument("--limit", type=int, help="at most this many bots (default 10)")
    s.set_defaults(fn="recent")

    calendar = sub.add_parser("calendar", help="read or schedule company appointments").add_subparsers(dest="sub")
    s = calendar.add_parser("upcoming", help="appointments on a company calendar")
    s.add_argument("--calendar", default="", help="roster email; default the company owner's")
    s.set_defaults(fn="calendar upcoming")
    s = calendar.add_parser("schedule", help="queue one calendar appointment")
    s.add_argument("--calendar", default="", help="roster email; default the company owner's")
    s.add_argument("--title", required=True)
    s.add_argument("--start", required=True, help="ISO-8601 timestamp with timezone")
    s.add_argument("--end", required=True, help="ISO-8601 timestamp with timezone")
    s.add_argument("--attendee", action="append", default=[])
    s.add_argument("--description", default="")
    s.add_argument("--description-file")
    s.add_argument("--no-meet", action="store_true")
    s.set_defaults(fn="calendar schedule")
    s = calendar.add_parser("status", help="whether a queued appointment was created")
    s.add_argument("id")
    s.set_defaults(fn="calendar status")

    s = sub.add_parser("sql", help="read-only SQL over what you may see (docs/hub-sql.md)")
    s.add_argument("sql", help="one SELECT (or WITH, EXPLAIN QUERY PLAN)")
    s.add_argument("--json", action="store_true", help="print the API response as JSON")
    s.add_argument("--csv", action="store_true", help="print CSV")
    s.add_argument("--max-rows", dest="max_rows", type=int, help="ask for at most N rows")
    s.add_argument("--param", action="append", default=[], metavar="KEY=VALUE",
                   help="bind :key in the SQL (numbers are bound as numbers)")
    s.set_defaults(fn="sql")

    s = sub.add_parser("db", help="read-only SQL on a company database (docs/databases.md)")
    s.add_argument("target", help="a database name, or `list` or `doctor`")
    s.add_argument("sql", nargs="?", help="one SELECT; with `doctor`, the database to check; on MongoDB find|aggregate|count|distinct|collections")
    s.add_argument("extra", nargs="*", help="MongoDB: the collection, then the filter or pipeline JSON (distinct: the field, then a filter)")
    s.add_argument("--projection", help="MongoDB find: fields to return, Extended JSON")
    s.add_argument("--sort", help="MongoDB find: e.g. '{\"placed_at\": -1}'")
    s.add_argument("--limit", type=int, help="MongoDB find: at most N documents")
    s.add_argument("--query", dest="query_id", help="run a named query from the company's catalog")
    s.add_argument("--param", action="append", default=[], metavar="NAME=VALUE", help="bind :name in the SQL")
    s.add_argument("--json", action="store_true", help="print the result as JSON")
    s.add_argument("--csv", action="store_true", help="print CSV")
    s.add_argument("--max-rows", dest="max_rows", type=int, help="at most N rows (never above the database's cap)")
    s.add_argument("--timeout", type=float, help="at most S seconds (never above the database's limit)")
    s.set_defaults(fn="db")

    github = sub.add_parser("github", help="the company's GitHub App").add_subparsers(dest="sub")
    s = github.add_parser("create-bot-repo", help="owner or BotOps: create <org>/emp-<slug> from a template, or empty")
    s.add_argument("slug")
    s.add_argument("--template", default="ticoteam/botops", metavar="OWNER/REPO")
    s.add_argument("--empty", action="store_true", help="an empty private repository, for a bot whose history is on a computer")
    s.set_defaults(fn="github create-bot-repo")

    s = sub.add_parser("integrations", help="every integration: access, credentials, counts")
    s.add_argument("--json", action="store_true", help="print the API response as JSON")
    s.set_defaults(fn="integrations")
    s = sub.add_parser("integration", help="one integration: the page, its queries and the learnings")
    s.add_argument("service")
    s.add_argument("--json", action="store_true", help="print the API response as JSON")
    s.set_defaults(fn="integration")
    s = sub.add_parser("queries", help="search an integration's query catalog")
    s.add_argument("service")
    s.add_argument("term", nargs="?", default="", help="matched against id, title, description, tags and SQL")
    s.add_argument("--id", dest="query_id", help="print one query's SQL and params")
    s.add_argument("--json", action="store_true", help="print the matching queries as JSON")
    s.set_defaults(fn="queries")
    s = sub.add_parser("learn", help='add a learning: hub learn <service> "<text>"')
    s.add_argument("service")
    s.add_argument("text")
    s.set_defaults(fn="learn")
    s = sub.add_parser("decisions", aliases=["judge"], help="ask the decision model typed questions about a JSON state (questions/README.md)")
    s.add_argument("--set", dest="question_set", help="a question set: questions/<name>.json in the hub checkout")
    s.add_argument("--questions-file", dest="questions_file",
                   help="instead of --set: a JSON file holding the questions map (or an object with `questions`)")
    s.add_argument("--state-file", dest="state_file", help="the JSON state the questions are about; `-` reads stdin")
    s.add_argument("--option", action="append", default=[], metavar="QUESTION=FILE",
                   help="complete a dynamic choice with a JSON map of option -> description from FILE")
    s.add_argument("--label", help="how the call is grouped in the audit; the set's id@version by default")
    s.add_argument("--list", action="store_true", help="print the question sets this checkout has")
    s.set_defaults(fn="decisions")

    # Onboarding: the person picks bots, BotOps sets each one up from the catalog in a turn.
    # The Librarian (docs/librarian.md): ask a question, and read a linked doc on this computer.
    s = docs.add_parser("ask", help="ask the Librarian about the company's docs and wait for the answer")
    s.add_argument("question")
    s.add_argument("--wait", type=float, default=120, help="seconds to wait for the answer (default 120)")
    s.set_defaults(fn="docs ask")
    s = docs.add_parser("fetch", help="read a public link as text; runs on this computer, never on the server")
    s.add_argument("url")
    s.add_argument("--max-chars", dest="max_chars", type=int, default=30000)
    s.set_defaults(fn="docs fetch")
    sub.add_parser("catalog", help="the bot templates this company can pick from").set_defaults(fn="catalog")
    bot = sub.add_parser("bot", help="set a chosen bot up from the catalog (BotOps)").add_subparsers(dest="sub")
    s = bot.add_parser("create", help="materialize <slug> from a catalog template into the workspace")
    s.add_argument("slug")
    s.add_argument("--template", required=True, help="a template from `hub catalog`")
    s.add_argument("--name", help="what people call this bot; the catalog card's name by default")
    s.set_defaults(fn="bot create")
    s = bot.add_parser("set", help="apply a person's bot-settings request as them (BotOps)")
    s.add_argument("slug")
    s.add_argument("--on-behalf-of", metavar="MESSAGE_ID",
                   help="the person's message to BotOps asking for this change; by default the one that started this turn")
    s.add_argument("--reports-to", help="a bot slug, or human:<id>")
    s.add_argument("--display-name")
    s.add_argument("--description")
    s.add_argument("--repo", help="its GitHub repository: <org>/emp-<slug>")
    s.add_argument("--status", choices=("active", "paused", "planned"))
    s.set_defaults(fn="bot set")
    s = bot.add_parser("check", help="what preflight would still refuse about that repository")
    s.add_argument("slug")
    s.set_defaults(fn="bot check")
    s = bot.add_parser("register", help="register a bot with the server, planned, as the person who asked (BotOps)")
    s.add_argument("slug")
    s.add_argument("--name", help="what people call it")
    s.add_argument("--description")
    s.add_argument("--reports-to", help="a bot slug, or human:<id>; the requester by default")
    s.add_argument("--template", help="a template from `hub catalog`")
    s.set_defaults(fn="bot register")
    s = bot.add_parser("access", help="show or set who may see, read and write to a bot")
    s.add_argument("slug")
    for level in ("see", "read", "write"):
        s.add_argument("--" + level, help="everyone, or a comma list: person ids, team:<name>, bot:<slug>")
    s.set_defaults(fn="bot access")
    s = bot.add_parser("owners", help="add or remove the people who own a bot")
    s.add_argument("slug")
    s.add_argument("--add", nargs="+", default=[], metavar="PERSON")
    s.add_argument("--remove", nargs="+", default=[], metavar="PERSON")
    s.set_defaults(fn="bot owners")
    s = bot.add_parser("onboarded", help="a starter bot marks itself onboarded, after a person approved its first routine")
    s.add_argument("slug", nargs="?", help="the bot; the one running this command by default")
    s.set_defaults(fn="bot onboarded")
    s = bot.add_parser("place", help="put a bot on a computer, as the person who asked (BotOps)")
    s.add_argument("bot")
    s.add_argument("--computer", help="a computer's label or id; the best one that takes it by default")
    s.set_defaults(fn="bot place")
    s = bot.add_parser("go-live", help="place it if needed, turn it on and start its setup (BotOps)")
    s.add_argument("bot")
    s.add_argument("--computer")
    s.add_argument("--no-setup", dest="no_setup", action="store_true", help="do not start its setup chat")
    s.set_defaults(fn="bot go-live")
    s = bot.add_parser("model", help="list the models, or change this bot's (BotOps)")
    s.add_argument("bot")
    s.add_argument("model", nargs="?", help="a model id or name; leave out to list")
    s.add_argument("--effort")
    s.set_defaults(fn="bot model")
    for verb in ("pause", "resume"):
        s = bot.add_parser(verb, help=f"{verb} a bot (BotOps)")
        s.add_argument("bot")
        s.set_defaults(fn="bot " + verb)
    people = sub.add_parser("people", aliases=["person"], help="the roster: add someone, list who is on it").add_subparsers(dest="sub")
    s = people.add_parser("add", help="add a person to the roster and the sign-in list")
    s.add_argument("email")
    s.add_argument("--name")
    s.add_argument("--title")
    s.add_argument("--reports-to")
    s.set_defaults(fn="people add")
    people.add_parser("list", help="the people on the roster").set_defaults(fn="people list")
    s = sub.add_parser("api", help="BotOps: any v2 route, as the person who asked")
    s.add_argument("method", type=str.upper, choices=["GET", "POST", "PUT", "PATCH", "DELETE"])
    s.add_argument("path", help="/api/v2/... or the part after it")
    s.add_argument("body", nargs="?", help="a JSON body for a write; - reads it from standard input")
    s.set_defaults(fn="api")
    sub.add_parser("computers", help="the computers a bot may go on").set_defaults(fn="computers")
    cred = sub.add_parser("credential", help="ask for a secret in the chat, store one, list them").add_subparsers(dest="sub")
    s = cred.add_parser("request", help="open a card in the chat for the person to type the secret into")
    s.add_argument("env", help="the variable's name, like JIRA_BASIC_AUTH")
    s.add_argument("--for-bot", dest="for_bot")
    s.add_argument("--label", help="what it is: 'your Jira login'")
    s.add_argument("--format", help="its shape: you@company.com:API token")
    s.add_argument("--help-url", dest="help_url", help="an https page where they make one")
    s.add_argument("--kind", choices=["api_key", "token", "password", "connection"])
    s.set_defaults(fn="credential request")
    s = cred.add_parser("set", help="store a secret a person gave you, for one bot; the value is read from stdin")
    s.add_argument("env")
    s.add_argument("--for-bot", dest="for_bot", required=True)
    s.add_argument("--name")
    s.add_argument("--kind", choices=["api_key", "token", "password", "connection"])
    s.add_argument("--username")
    s.add_argument("--no-redact", dest="no_redact", action="store_true", help="leave the pasted words in the chat")
    s.set_defaults(fn="credential set")
    cred.add_parser("list", help="names, variables and which bots have each; never a value").set_defaults(fn="credential list")
    msg = sub.add_parser("message", help="take a secret out of a message").add_subparsers(dest="sub")
    s = msg.add_parser("redact", help="replace a secret (read from stdin) in a message with a mark")
    s.add_argument("message_id")
    s.add_argument("--label", help="what it was saved as")
    s.set_defaults(fn="message redact")
    support = sub.add_parser("support", help="tell the Tico team about a gap or a fault").add_subparsers(dest="sub")
    s = support.add_parser("file", help="a Confirm card shows the message; nothing is sent until the person confirms")
    s.add_argument("message")
    s.set_defaults(fn="support file")
    return p


RUNNER_CONFIG = Path.home() / ".config" / "tico" / "runner.json"
# Read-only commands a person or a script on the Mac may run outside a turn with the runner credential.
READ_OUTSIDE_A_TURN = ("sql", "integrations", "integration", "queries")


def runner_credential(path=None):
    """This Mac's runner credential as (url, token), or None when it is not registered.

    `hub sql` and the integration reads use it; the API answers a runner's SQL as the person
    who registered the machine. That is how a script or an agent on the Mac reads without a
    browser session.
    """
    try:
        config = json.loads(Path(path or RUNNER_CONFIG).read_text())
        return str(config["url"]), str(config["token"])
    except (OSError, ValueError, KeyError, TypeError):
        return None


def split_human(argv):
    """Pull `--human <id>` out of anywhere in the line, so it works before or after the command."""
    argv, who = list(argv), None
    for i, a in enumerate(argv):
        if a == "--human" and i + 1 < len(argv):
            who = argv[i + 1]
            return argv[:i] + argv[i + 2:], who
        if a.startswith("--human="):
            return argv[:i] + argv[i + 1:], a.split("=", 1)[1]
    return argv, who


def main(argv):
    argv, who = split_human(argv)
    p = parser()
    try:
        args = p.parse_args(argv)
    except SystemExit as e:                 # argparse already said what was wrong, or printed help
        return 0 if not e.code else 1
    if not getattr(args, "fn", None):
        p.print_help(sys.stderr)
        return 1
    try:
        if getattr(args, "dry_run", False):     # never reaches remotecli: nothing to send
            return cmd_task_dry_run(args, who)
        if args.fn == "decisions" and args.list:    # the sets are files in this checkout, no API needed
            from clients import judge
            print(json.dumps(judge.list_sets(), indent=2))
            return 0
        if args.fn == "docs fetch":                 # runs here, beside the bot: no hub, no credential
            from clients import doc_fetch
            try:
                print(json.dumps(doc_fetch.fetch(args.url, args.max_chars), indent=2))
                return 0
            except doc_fetch.FetchError as e:
                print(json.dumps({"error": e.code, "detail": e.message}, indent=2))
                return 1
        if not os.environ.get("HUB_API_URL"):
            local = args.fn in READ_OUTSIDE_A_TURN
            credential = runner_credential(os.environ.get("HUB_RUNNER_CONFIG")) if local else None
            if not credential:
                raise CliError("HUB_API_URL is not set: `hub` talks to the Tico API and runs inside a "
                               "bot turn, where the runner sets HUB_API_URL, HUB_TOKEN and HUB_EMPLOYEE"
                               + (f"; outside a turn `hub {args.fn}` needs this Mac's runner credential "
                                  "(scripts/setup-runner.sh)" if local else ""))
            os.environ["HUB_API_URL"], os.environ["HUB_TOKEN"] = credential
        if args.fn.startswith("bot ") and not os.environ.get("HUB_WORKSPACE"):
            raise CliError("HUB_WORKSPACE is not set: bot repositories live in the workspace this "
                           "machine was enrolled with, which the runner gives every turn")
        from clients import remotecli
        return remotecli.main(args, who)
    except CliError as e:
        print(json.dumps({"error": str(e)}, indent=2))
        return 1
    except Exception as e:
        print(json.dumps({"error": f"{type(e).__name__}: {e}"}, indent=2))
        return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
