# How Tico works

The current system, in one page. For a teammate's questions read [Using Tico](using-tico.md).

## The six nouns

- **Bot** — an AI employee with its own `emp-<slug>` repository, run on one registered Mac,
  or run by an external agent such as a Hermes profile that reaches the hub with its own
  credential and is never dispatched to ([Hermes agents](hermes-agents.md)).
  Record states: `active`, `paused`, `planned`, `quarantined`. Live status while it works:
  `idle`, `running`, `waiting_human`, `waiting_bot`, `blocked`, `limited`, `crashed`, `paused`,
  `quarantined`.
- **Task** — a unit of work with a requester, an owner (bot or person), a title, a body and a
  note; a `lane` (company or product), a `rank` in its owner's queue, labels, links (a pull
  request first), an optional parent and an optional `blocked_by`. States: `open`, `doing`,
  `waiting`, `review`, `ready`, `done`, `closed`, `declined` (`review` and `ready` belong to the
  product lane). The owner marks it `done`; only the requester (or any person) closes it. Every
  task has a comment thread, on the record with the author.
- **Message** — one line in a conversation. Kinds: `say`, `ask`, `answer`, `notice`, `steer`.
  A bot's `ask` to a person is what lands in **Needs you**.
- **Approval** — a person's yes or no to one exact action. Kinds: `send`, `spend`, `publish`,
  `merge`. Only a person decides; an approval is spent once. Rules: `policies/approvals.md`.
- **Routine** — a cron schedule owned by a bot: `id`, `title`, `cron`, `timezone`, `template`
  (a playbook file) or inline `instructions`, `labels`. Each occurrence becomes a task.
- **Goal** — what a person or a bot is for: a title, an owner, the goal it serves (`parent_id`;
  none for a company goal), a colour the owner sets with one sentence (`red`, `yellow`, `green`;
  `done` or `dropped` when it ends; none while proposed) and KPIs whose readings anyone logs at
  any time. A task may name the goal it serves. Bots read theirs with `hub goals`; nothing is
  pushed into a run.

The rules for all six live in the backend's write layer, not in prompts: a bot acts only as
itself; it may message only active bots and people; at most 20 bot-to-bot messages per
conversation per hour and 3 unsolicited messages per person per bot per day; one clarifying
question per task; the requester closes; an approval is decided by a person and consumed once;
anything addressed to a person is linted (first line is the ask, under 120 words); repeated
refusals open a review task and, at 10 a day, quarantine the bot until a person clears it.

## The three places

**hub.acme.example** — the record, the interface and the clock. A FastAPI backend (`backend/`) on one
EC2 instance with SQLite on an encrypted EBS volume, attachments in a private S3 bucket, backed up
to S3 twice over (Litestream replicates every ten seconds; a verified bundle of the database and
every attachment is taken daily and restore-tested), behind Cloudflare Access. It holds every task, message, approval, routine, run and
bot setting, serves the web interface (`ui/`), and runs the scheduler that turns due routines into
tasks. It never runs a bot turn. It runs from the Docker image ([install.md](install.md)). Beside it
on the same host, the Slack gateway (`backend/slack_gateway.py`, its own unit) turns a DM to
Tico or an `@Tico` in a channel into a message for the employee the decision model routes it to, posts the
reply back under that employee's name, and stores everything else said in the channels Tico is
in so that each channel's readers see it within the hour (`docs/slack-gateway.md`).
Pages: **Tasks** (where the app opens), **Meetings** (imported transcripts, source sync status, Import, and each meeting's
action items), **Docs**,
**Integrations**, **Changelog**, the **Org** tree, and under your email **Runs**, **Settings**, **Credentials**
and, for the owner, **SQL**. Tasks has List, Board, Recurring and Done. A bot's page has **Chat**,
**Tasks**, **Docs** and **More**. The assistant (Tico, `coo`) and BotOps are built in to every company and cannot be archived or deleted (`409 system_bot`); the assistant
and the Librarian work in the background and are not listed for people. Each person has one private **Assistant** chat, the first tab on their own page
and "Ask the Assistant…" in search: it looks things up at once, does low-risk things as that person, and
proposes anything with a side effect for their own click ([The Assistant](assistant.md)). There is no shared
Tico chat page and no Tico Live; people can also act across the company through their own agent over the hub's
MCP (**Connect an agent**).
The database itself is readable with plain SQL (`hub sql`, the SQL page, `POST /api/v2/sql`):
one `SELECT` at a time, each caller seeing only what the JSON API would show it, secrets never
([Querying the hub with SQL](hub-sql.md)).

**Your Mac's runner** — `runner/`, started as `python -m runner`, registered once with
**Add computer** in **Settings → Bots** (`scripts/setup-runner.sh`, credential in
`~/.config/tico/runner.json`). Four launchd jobs, installed and managed with `scripts/tico`:

| Job | Command | What it does |
|---|---|---|
| `team.tico.tico-bot` | `python -m runner run` | Heartbeats every 15 s with readiness, claims work for the bots assigned to this Mac, runs each turn in the bot's local repository with the local model CLI, streams output back |
| `team.tico.tico-connectors` | `python -m runner connectors` | Publishes calendar snapshots, executes Hub-queued calendar appointments, and pushes persisted mail from local Google access (Ana's Mac, or a Linux runner that holds the Google key) |
| `team.tico.tico-close-calls` | `python -m runner close-calls` | Every five minutes, imports available Close call and Notetaker meeting transcripts without fetching audio, using the local Close key (Ana's Mac only; `scripts/tico install close-calls`) |
| `team.tico.tico-importers` | `python -m runner importers` | Runs the meeting importers the owner turned on for this computer (Fireflies, Zoom, Google Meet, Granola), using credentials kept in `secrets/` here; see [Meetings](meetings.md#meeting-importers) (`scripts/tico install importers`) |

A Linux runner (the Docker image) has no launchd: with `TICO_SIDE_JOBS=1` (set by the image) `python -m runner run` supervises `importers` (while the hub assigns importers to this computer) and
`close-calls` (while the Close key is in `secrets/`) and `connectors` (while `secrets/google-sa.json` is there, or the
hub names this computer's operator in `TICO_PROCESSING_OPERATORS`) as child processes with restart and backoff
(`runner/sidejobs.py`). A Mac keeps its checkout-sibling layout; a Linux runner names the same places with
`TICO_PROJECTS_DIR` and `TICO_MAIL_VENV` (see [Mail](mail.md#works-on-linux-runners)).

Logs are `~/.config/tico/logs/tico-{bot,connectors,close-calls,importers}.log`. The runner makes outbound
HTTPS calls only; nothing listens on the Mac. Model subscriptions (Codex, Claude, Gemini, Grok
Build) are signed in on the Mac and never leave it. Bot secrets come from
`<projects>/secrets/_shared.env` and `<projects>/secrets/<slug>.env` on the Mac, or from the
shared vault (**Credentials**) for a bot explicitly granted them, delivered only for that run.
Each turn gets a scoped credential in `HUB_API_URL`/`HUB_TOKEN`; the bot talks to hub.acme.example
through the `hub` CLI (`scripts/hub`) or the hub's MCP tools (`hub_*`, the same names with
underscores: `hub task create` is `hub_task_create`), and downloads attachments with
`clients/files.py`. The tool schema is `clients/hubtools.py` and is the contract; the two are
one implementation behind two transports. Codex and Claude turns get the MCP server for free
(the runner spawns `clients/hubmcp.py` with the turn's credential); anything that speaks MCP
over HTTP can also `POST /api/v2/mcp` with a bearer token. Either way every call goes through
the same routes and `backend/hubdb.py` rules; there is no privileged path.

Calendar appointments are three shared Hub tools available to every bot:
`hub_calendar_upcoming`, `hub_calendar_schedule`, and `hub_calendar_status`. Reads come from the
bounded connector snapshot. A schedule call writes an idempotent Hub action; the private connector
claims it once, creates the Google event and invitations locally, and reports the result. Bots must
see `succeeded` before saying the appointment exists. This path grants no generic Gmail authority.

One of those tools is a second model, the decision model. `hub_decisions` (`hub decisions`) sends a JSON state and typed
questions to the decision model, and gets a calibrated answer per question back:
a choice with a confidence, a score on ordered levels, or the probability a statement is true (yes/no, choice and score: the question format of OpenRouter's Decisions API).
It writes no prose, so a bot uses it to decide (sort a listing, dedupe, route, gate a draft) and
its own model to write. The hub holds the one key and audits every call by label, never the
state (`backend/judge.py`); the decisions themselves are versioned files in `questions/`
(`questions/README.md`), which the meeting brain and the mail CLI read the same way a bot does.
`skills/decisions/SKILL.md` says when to reach for it.

**The bot's repository** — `acme/emp-<slug>`, checked out at `<projects>/emp-<slug>` on the
Mac that runs it (`~/tico-work` on Ana's Mac). The contract (`templates/employee-repo/`):

| File | What |
|---|---|
| `AGENT.md` (with `AGENTS.md`/`CLAUDE.md` pointing at it) | role, what it owns, how it starts and ends a turn; read every turn |
| `employee.yaml` | `name`, `runtime`, `model`, `reasoning_effort`, `max_run_minutes`, `access:`, `outbound_send` (`schedules:` only in a catalog template, as the seed) |
| `state.md` | current focus, open threads, next step |
| `memory/learnings.md`, `memory/decisions.md` | how to do the job; dated decisions |
| `knowledge/` | what is true in its domain, one topic per file, dated sources |
| `playbooks/` | recurring methods; a routine's text is usually one of these |
| `reports/`, `software/`, `skills/` | dated deliverables, its own tools, runtime skills |
| `<slug>.data/` (sibling, never committed) | large or regenerable data |

Bots commit directly to `main`; the runner pushes after each completed turn and once at start-up
for every assigned bot, and leaves a diverged checkout for a person (one log line an hour). Files
bots produce for the company are published to Tico's private store and listed on the bot's page
([Files](files.md)).

## What happens when

**You send a message or file a task.** hub.acme.example saves it and queues a job for the bot. The bot's
runner claims it on its next poll, runs one turn (prompt = `AGENT.md`, the conversation, the task,
your message and attachments), and streams the reply back. The conversation shows *Saved — queued*,
*Starting*, *Working*, then the reply. Closing the browser changes nothing.

**A routine fires.** The server (America/Los_Angeles unless the routine says otherwise) creates one
task for the bot with the saved instructions and version. Missed occurrences coalesce; a task still
open from the last occurrence absorbs the next one. The runner claims it like any task. The wake,
the note, and the bot's answer land in that bot's Chat room (the operator's room for a personal bot,
the shared room otherwise), so the next turn can read them.

**The Mac is asleep.** Everything on hub.acme.example stays available and accepts work. After 60 s
without a heartbeat the bot shows *offline* and new messages show *Saved — waiting for <machine>*.
A sleeping Mac is not reliably absent: macOS wakes it for a few seconds at a time to check the
network, and the runner asks for work in those seconds. So a machine that has been silent for
more than 60 s must then report in without a break for two minutes before it is given anything.
Contact means a heartbeat or a claim, whichever arrives: a wake of a few seconds never reaches
the runner's fifteen-second heartbeat timer, so counting only heartbeats let each brief wake
stand on the record of the one before it and take work anyway,
and until it has, its queued work reads *Saved — waiting for <machine> to stay awake*. A brief
wake cannot take a 90 s lease it has no chance of finishing, and a machine that never went away
is unaffected — including every machine already enrolled when this rule arrived.
A turn that was mid-flight loses its 90 s lease: not-yet-started work is re-queued; started work
becomes *Interrupted*. Fifteen minutes later (after the runner's own chance to reclaim it) the
scheduler settles what needs no eyes: a delivery whose task is already done or closed is dismissed,
and a run that recorded no tool call and consumed no approval is resumed, each with a keeper note
in the job's recovery record (`job.auto_reconcile` in the event log). A run that used tools stays
*operator review needed*, because the hub cannot see what a tool did on the Mac; the bot's operator
resumes or dismisses it after checking what already happened. Nothing is lost or re-sent.
While such a review is owed the bot's tasks, notices and routines wait, but a person's own chat
messages still run: nothing about them is uncertain.

**Needs you.** Every issue the hub derives says whether a person has to act. Those that do (a
review owed, a machine gone for more than ten minutes, a missing agent credential, a stale backup,
a usage limit hit three times) open in a dialog in front of the person the first time they appear,
wherever they are in the app, with the action inline: *Review now* opens the interrupted work,
*Open bot* goes to the bot. Closing it is remembered per issue and *Snooze* quiets it for an hour;
the alert under the sidebar reopens it any time. Issues the hub resolves itself (a machine that
just dropped off, a usage limit that is retrying) stay out of the way as *resolves on its own* in
**Settings → Needs attention**, one row per machine rather than one per bot. A cloud deploy is different: hub.acme.example is
unreachable for a few minutes, the runner keeps the turn going and the server extends every
running lease when it comes back, so the finished reply still lands. The same forgiveness covers
a server that stalls without restarting (the daily backup runs at the lowest CPU and I/O
priority for this reason): a lease lapsing while the server has answered no runner for more
than half a lease period gets one more period instead of expiring, and an attempt that did
expire is handed back to its runner when the runner reports in within 15 minutes, as long as no
one has reviewed the job meanwhile (`attempt.lease-restored` in the event log). The runner's log
(`scripts/tico logs bot`) writes one timestamped line when the cloud becomes unreachable, a
progress line at most once a minute while it stays so, and one when it is back; `scripts/tico
status` says when the running bot job predates the checkout's current commit. On a bot's Chat
page, one line above the composer says when the bot is paused and why (a usage limit, a
quarantine, or a Mac offline for more than ten minutes) and that messages are saved, or that a
review is owed while chat still answers.

**A subscription usage limit.** A turn that hits one fails with `limited` set; it did nothing, so
the job stays queued however often this happens (it is never *Interrupted*), the bot shows
*limited* and the cloud claims it again after 30 minutes. A third limit in a row waits two hours
and says so in **Settings → Needs attention**, with the retry time. If the bot has a fallback
harness in **Settings → Bots**, the runner reruns that turn at once on the fallback (fresh
session) and reports `fallback` as that harness, which **Runs** shows in the Session column.
Tico is seeded with Gemini CLI as its fallback from Antigravity, so a usage limit uses
`GEMINI_API_KEY` in `secrets/coo.env` the same way as before. **None (fail)** means no hop:
the cloud cooldown applies.

**A bot's session is its own.** Each bot has one provider thread: chat, tasks and scheduled
routines resume it in the same local `emp-<slug>` checkout, and only that Mac knows which thread
it is. Tico never ends a thread, never asks the bot for a checkpoint before a model or machine
change, and never rebuilds history into a prompt: when the conversation fills the model's window
the runtime compacts it, and a turn carries only what the room said since the bot last answered.
A bot that wants what was said before reads it with `hub history <conversation id>` (the prompt
names the conversation). The runner fast-forwards the checkout from origin before the turn, and
pulls or clones any `reads:` sibling repos beside it.

**A bot needs you.** It asks with `hub task ask` (the task goes `waiting`), requests an approval,
or files a task for you. All of these appear in **Needs you** at the top of **Tasks** with
**Reply**, **Approve** / **Decline**, **Done** / **Close**. Needs you is your queue: approvals and
questions first (each blocks a bot), then your own tasks in rank order. There is no priority;
a mover (anyone on the leadership, product or engineering team) drags a task up or down, into
another column, or between lanes; everyone else sees the board and comments.

**A bot finishes.** It commits its repository, marks the task `done` with a note, and the reply is
saved in the conversation. The task shows under **Tasks → Done** with the bot's note; a bot that
requested it gets a *Finished: <title>* notice (`/api/v2/inbox`) and closes the task (a
bot-requested task closes itself after three days). Every run is listed under **Runs** and on
the bot's **More** tab.

**You change a bot's instructions.** Edit `AGENT.md` (or a playbook, `memory/`, `knowledge/`) in
`emp-<slug>` and commit. The runner reads the checkout on its Mac at the start of every turn, so
the change is live on the next turn once that checkout has it: push, and pull on the runner Mac
if you edited elsewhere. Do not edit while the bot is running there.

**You change a routine.** Routines are rows in the hub (`docs/routines.md`): edit one on the
site under Tasks → Recurring, or a bot changes its own with `hub routine set`. The change is in
the table at once; a sleeping Mac does not block it. **You change a bot's switches.** Connectors
read `outbound_send` and `access:` from the Mac checkout each time a bot sends or posts. Model, effort, computer, people, name,
status and reporting line are changed in **Settings → Bots**, not in the file.

## Calling the API from a script

A person is normally the browser sign-in (Cloudflare Access). A **personal API token** is the
same person from a script, a cron job or another machine, with no browser: the owner or a bot
administrator (`registry/hub-access.yaml`) opens **Settings, Devices, API tokens**, gives the
token a label and a life (90 days unless changed, a year at most), and copies it once; it is
not shown again and only its hash is kept. Then:

```
export HUB_API_URL=https://hub.acme.example HUB_TOKEN=tico_pt_...
hub whoami            # human:<you>
hub sql "SELECT slug FROM bots"
curl -H "Authorization: Bearer $HUB_TOKEN" https://hub.acme.example/api/v2/bots
```

No `HUB_EMPLOYEE`: the token is you, not a bot. It is you for every purpose, with the rights you
have in the browser (a bot administrator adds bots for their own operator account, the owner does
what the owner does), and it leaves the same audit trail. The one thing a token cannot do is make
or revoke tokens; that takes a signed-in browser, so a leaked token cannot extend its own life.
Revoke one on the same page, and it stops at once; the owner may revoke anyone's. Every token
made or revoked is an `events` row (`token.create`, `token.revoke`).

## Where things are

| Directory | What |
|---|---|
| `backend/` | the cloud API, authorization, write layer, scheduler, backups (FastAPI, SQLite) |
| `runner/` | the local runner: enrolment, readiness, leases, turns, connectors, Close call import |
| `clients/` | what bots and the runner call: the `hub` CLI, the HTTP client, attachment download, routine validation, preflight, the docs read and write commands |
| `connectors/` | shared Slack, mail/calendar and browser adapters bots use instead of vendor APIs |
| `integrations/` | one page per outside system (what it is, how a bot uses it, rules, recipes) and the query catalogs; served as **Integrations** and `hub integration <service>`, with the learnings bots add |
| `questions/` | the question sets the decision model answers (`hub_decisions`, `hub decisions`, `mail inbox --decisions`, the meeting brain): one versioned JSON file per decision, with its thresholds |
| `ui/` | the web interface (`index.html` and its scripts, browser tests) |
| `app/` | the native macOS shell around hub.acme.example |
| `infra/` | the EC2 stack, release packaging, deploy and restore scripts |
| `scripts/` | `tico` (operate the runner), `hub` (the bots' CLI), setup, publishing and maintenance |
| `docs/` | company knowledge |
| `policies/` | rules every bot follows: approvals, access, handoffs, writing, shared rules |
| `registry/` | bootstrap data: people, sign-in access, mail rules, Slack channels; `employees.yaml` seeds a new database only |
| `templates/` | the employee repository contract and prompt templates |
| `skills/` | shared runtime skills for bots |
