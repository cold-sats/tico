# Creating bots

How to set up a bot that works, and how to write the instructions it reads every turn.

Two readers: the operator standing up the first bots in a new environment, and the person (or AI)
writing a bot's `AGENT.md`. Installation of the server, the runner and the model CLIs is in the
README; this page starts where you can open **Settings → Bots** and press **Add bot**. See also
[How it works](how-it-works.md), [Using Tico](using-tico.md), [Routines](routines.md) and
[Shared credentials](credential-vault.md).

## Start from the catalog, and let BotOps build it

Very little of this has to be done by hand. `templates/catalog/<template>/` holds the bot templates
this product ships: a card saying what the bot owns and what it never does, and the repository the
bot is created from, with the company's names filled in and the onboarding answers written into
`knowledge/company.md`. **Settings → Bots → Add from catalog** is how a bot is added after the
first run, and the first run wizard is the same catalog. Either way the bot is created `planned`
and a task goes to **BotOps**, the bot engineer every environment has (built in, like the assistant: it cannot be archived or deleted, only paused or renamed): it materializes the
repository, puts the reviewed instructions in, runs the readiness check, and finishes the task with
the one thing to read before you activate the bot. Activation stays a person's decision.

Read this page when you are writing those instructions, tailoring what BotOps produced, or standing
a bot up outside that flow. The wizard, the catalog folder format and the ways to add a bot later
are in [First run](onboarding.md).

## Inbox bots

An inbox bot is assigned to one person on the roster. **Settings → Bots → Add from catalog** (and
the first-run cards) show a person picker when the template is `inbox`. The chosen address is
appended to the instructions as `Mailbox: <email>`, and BotOps fills `{{mailbox}}` in
`employee.yaml` from that line. The bot is created `planned`, with `outbound_send: false`, two
inbox-pass routines (weekdays at 07:00 / 12:00 / 16:00 and weekends at 09:00 in the company
timezone), and gmail `read`/`draft` plus calendar `read` on that mailbox, with `org_read: true` so
it also reads everyone who reports to that person.

There is no per-user OAuth. One Google service account acts as every mailbox; the access block
names the address, never a personal login. Calendar access is broader than Gmail access: every
bot can read and create events on every address in `registry/people.yaml`, whether or not its
manifest includes that mailbox and even when Gmail is read-only. After the first inbox bot, pick
another person to create another (`<id>-inbox`).

A pass runs `mail rules run --all-mailboxes`, then `mail inbox --untriaged --all-mailboxes
--format brief`. What still needs a person is labelled `hub/needs-owner`. Nothing is sent. See
[Mail](mail.md) and [Routines](routines.md).

## 1. What a bot is here

A bot is **one durable git repository plus one row in the server**. Three parts:

- The repository is `emp-<slug>`, checked out in the environment's workspace (where that
  environment keeps its repositories, alongside the shared repository and `secrets/`). It holds
  everything the bot knows and everything it has learned.
- The runner on a registered Mac claims the bot's work, runs each turn inside that checkout with a
  model CLI signed in on that Mac, and streams the reply back. Subscriptions never leave the machine.
- The server holds the record: tasks, conversations, approvals, routines, runs and the bot's
  settings. It is also the clock: it turns a due routine into a task.

| The server owns (change it in **Settings → Bots**) | The repository owns (change it in git) |
|---|---|
| Runtime, model, reasoning effort, `max_run_minutes` | `AGENT.md`, the standing instructions |
| Which computer runs the bot | `playbooks/`, the repeatable methods |
| Record status: `planned`, `active`, `paused`, `quarantined` | `knowledge/`, what is true in the domain |
| Display name, reporting line, operator and primary user | `memory/`, dated learnings and decisions |
| The repository link recorded on the bot | `state.md`, where the bot is right now |
| Tasks, approvals, runs, routines and their history | `employee.yaml`: `access:`, `outbound_send` |

A one-off request is a **task**, not an edit. Only change the repository when the change should
hold next month too.

## 2. Repository anatomy

A catalog template produces this layout already; `templates/employee-repo/` is the generic version
of it. Copy it to `<workspace>/emp-<slug>` and fill it in. Slugs are lowercase,
hyphenated and stable: the slug appears in the repository name, in `employee.yaml` and in the bot's
own paths, so renaming later is real work.

| Path | What it is for |
|---|---|
| `AGENT.md` | The standing instructions. Read at the start of every turn. **Required.** `AGENTS.md` and `CLAUDE.md` are one-line pointers at it, so any model CLI finds it |
| `employee.yaml` | Identity and switches: `name`, optional runtime overrides, `access:`, `outbound_send`, `reads:` |
| `state.md` | Current focus, open threads, next step. Rewritten at the end of each run |
| `memory/learnings.md` | How to do the job: the flag it forgot, the tool that refused, dated |
| `memory/decisions.md` | What was decided, when, why. Dated. This is where history goes |
| `knowledge/` | The domain: one topic per file, dated sources. Other bots may read it |
| `playbooks/` | One file per recurring kind of work. Routines point at these |
| `reports/`, `software/`, `skills/` | Dated deliverables, the small scripts the bot wrote for itself, runtime skills |
| `.env.example`, `.gitignore` | The names of the secrets it expects (names only), and the ignore rules that keep `.env` out of git |

### What is enforced, not merely suggested

The runner checks these before it will run the bot, and the preflight script
(`clients/preflight.py`) checks the same things plus more before you flip a bot to `active`:

- **`AGENT.md` must exist.** A missing `AGENT.md` reads to the runner as a missing repository.
- **`AGENT.md` must not be the untouched template**, and it must contain an `## Owns` section with
  at least one non-empty bullet. Preflight fails otherwise.
- **`state.md` must exist**, and **`employee.yaml` must parse with `name:` equal to the slug**
  (`name: sales` in `emp-sales`).
- **`runtime:` and `model:` in the file must match the server, or be left out.** A mismatch reads
  as "Configuration differs from server" and the bot does not run. The simplest repository omits
  both and lets Settings decide.
- **`schedules:` in a catalog template is a seed.** `hub bot create` turns it into the new bot's
  first routines in the hub; after that the hub's rows are the routines (`docs/routines.md`).
  Preflight validates the block so a broken template is caught before a bot is made from it.
- **`.env` is never committed.** Secrets live on the Mac or in the vault. Declaring a secret in
  `access:` does not create it.
- **The working tree should be clean and have a remote.** A dirty tree or no remote is flagged:
  the bot commits and pushes after each turn, and it cannot push without a remote.

`hub bot check <slug>` runs the repository half of those preflight rules from inside a turn: the
manifest, the instructions, the schedules and stale references, reported as `{"ready": ...,
"problems": [...]}`. It is what BotOps runs before it hands a new bot over, and it needs no registry
entry, so it works on a repository the server has never seen. `clients/preflight.py` is still the
full check, including secrets, runtime and mail, and is what to run before flipping a bot to
`active`.

### The `.data/` sibling

Large or regenerable files go in `<workspace>/emp-<slug>.data/`, a sibling directory that is never
committed: raw API pulls, downloaded pages, seen-item stores, intermediate JSON. If losing it costs
nothing but a re-run, it belongs there, and the repository stays small enough to read as a diff.

## 3. Writing an `AGENT.md` that works

`AGENT.md` is read in full at the start of every turn, so every line is paid for on every run.
Aim for one to two pages. Past 150 lines it is a warning sign, and past 250 lines the bot is doing
archaeology before it starts work.

**Identity and scope come first.** The opening should answer: who am I, what am I for, what does
good look like, what is explicitly not mine. A bot with a fuzzy edge invents work.

Then, in this order:

1. `## Role`, one paragraph, including the "you do not" sentence: the thing a reader might assume
   the bot does, that it must not.
2. `## Owns`, the artifacts the bot is responsible for, by path where possible. Required. Naming
   files here is what stops a bot from creating a parallel set next to them.
3. `## Never without approval`, the role-specific additions to the shared approval rules.
4. `## Starting a run` and `## Ending a run`, short numbered lists, then `## Working style`, the
   handful of habits that make the output good.

### The task loop

Every turn is the same shape, and `AGENT.md` should say so plainly:

1. **Read `state.md`** to find out where the last run stopped.
2. **Read the task and its conversation** through the run's `hub` CLI. The task is the instruction;
   the conversation is the context.
3. **Check `memory/learnings.md` and the playbook the task names** before touching anything.
4. **Do the work**, updating `knowledge/` as it learns rather than at the end.
5. **Report in the task conversation.** The result goes in the task's completion note, first line
   first. Anything addressed to a person is linted: the first line is the ask, under 120 words.
6. **When blocked, ask through the task**, having read the record first, since most questions a bot
   wants to ask are already answered there. One clarifying question per task, phrased so the
   question is the only thing the person has to read. Internal routing, reminders, task closure,
   branches and draft pull requests are the bot's work, not questions for a person. Use an approval
   request only when the exact action is gated by the current shared or role policy.
7. **Commit, then mark the task done with a result note.** The requester closes it; the bot never
   closes a task it did not request.

### Where a line belongs

| The line is... | It goes in |
|---|---|
| A rule that is always true for this bot | `AGENT.md` |
| Steps for one recurring job | `playbooks/<job>.md` |
| A fact about the domain, with a source | `knowledge/<topic>.md` |
| A mistake this bot made and how to avoid it | `memory/learnings.md` |
| Why something changed, on what date | `memory/decisions.md` |
| Today's status | `state.md` |

The single most common failure is dated exceptions piling up at the top of `AGENT.md` until the
role is buried under three months of overrides. `AGENT.md` holds **current rules, present tense,
no dates**. When a rule changes, rewrite the rule and put the dated note in `memory/decisions.md`.

### Recording learnings

Ask one question at the end of every run: did anything go wrong or take a detour, a wrong
assumption, a refused command, a rule you had to guess? If yes, add the **smallest** scaffold that
prevents that exact mistake, in the same run: a playbook line when the fix is knowing something, a
check in `software/` when the fix is doing something, or a proposed rule on the task when the fix
belongs to everyone. Note it in `memory/learnings.md` with the date and the run it came from, so a
reviewer can see why it exists and delete it when it stops earning its place. Scope it to the
mistake actually made: no rules for imagined mistakes, no process where a sentence will do, and
when two scaffolds would work, keep the smaller one.

### Good and bad instructions

These are invented examples, in the shape that repeats in real repositories.

| Bad | Good |
|---|---|
| "Be thorough and helpful when reviewing invoices." | "Match every invoice to the purchase order for the same supplier and total. A gap over 2 percent goes on the task; you never pay." |
| "Use your judgement about what to send." | "You never send. Put the draft on the task and request a `send` approval with the exact text and recipients." |
| "On the 2nd we moved to the new sheet, then on the 11th the folder moved, so read the new one now." | "Counts come from `knowledge/counting.md`. The old spreadsheet is not a source." (The dates go in `memory/decisions.md`.) |
| "Check the chat tool, the mailbox, the CRM, the dashboard and the forum each run." | "Each pass reads the two sources named in the playbook. Anything else is a separate task." |
| "Escalate anything important." | "Escalate a deadline, a regulator, a termination, or money. Everything else you handle or archive." |

### An annotated skeleton

```markdown
# Inventory Desk                 <- display name, one line, no preamble above it

## Role
You keep the stock picture correct for the warehouse team, so a human can answer
"do we have it" in ten seconds. You read the count exports and the supplier
notices; you write `knowledge/`. **You do not order anything and you do not
contact suppliers.**                <- the "you do not" sentence is the scope edge

## Owns                          <- REQUIRED: preflight fails with no non-empty bullet
- `knowledge/suppliers.md`, `knowledge/counting.md`: the standing domain answer.
- `playbooks/daily-stock-pass.md`: the method the daily routine runs.
- `reports/YYYY-MM-DD-count.md`: a pass worth keeping. Routine passes live in
  the task note instead.
- `software/pull-counts.py`: the export reader. Keep it working.

## Never without approval        <- the shared rules, plus what is specific here
See the shared approvals policy. In addition:
- Never place, change or cancel an order. Never message a supplier.
- Never invent a number. A figure you did not read in a dated source stays out.

## Starting a run
1. Read `state.md`, then the task and its conversation.
2. Read `memory/learnings.md` and the playbook the task names.
3. Skim `knowledge/README.md` so you update the right file, not a new one.

## Ending a run
1. Add the smallest scaffold against anything that went wrong this run.
2. Update `knowledge/`; that is the work, not an afterthought.
3. Rewrite `state.md`, record durable decisions in `memory/decisions.md`, commit.
4. Mark the task done with the result in the first line. The requester closes it.

## Working style              <- three to six habits, one or two sentences each
- Quote the source. A claim you cannot quote goes in `open-questions.md`.
- Update a file, do not add a near-duplicate next to it.
- A blocked source is a blocked source, never "nothing found".
```

## 4. Knowledge and playbooks

### `knowledge/`

The bot's own documentation of its domain: not a log, not a report, but the standing answer to
"what do we actually know about this?". It is the first thing a fresh session reads, and any bot
that lists this repository under `reads:` can read it too.

- **One topic per file**, named for the topic. Prefer updating an existing file over adding one:
  forty thin files are worse than ten good ones. Keep each short enough to read in one sitting, and
  split along the topic when it outgrows that.
- **Every file ends with a dated `## Sources` section**, one line per source, and a fact that comes
  from one specific source carries its date inline too.
- **When two sources disagree, keep both with their dates.** Do not average, do not silently drop
  the older one. A contradiction is often the most useful thing on the page.
- **Never invent.** If nobody said a number, there is no number. Unanswered questions go in
  `open-questions.md`.
- **No secrets and no personal data** beyond what the source already shows.

`knowledge/` is the domain, `memory/` is the craft. If it would still be true after this bot was
replaced tomorrow, it is knowledge.

### `playbooks/`

A playbook is the checklist you would hand a new hire, with the exact commands and the exact
checks. One file per recurring kind of work. A good playbook has:

- The schedule it belongs to at the top, so a reader knows which task they are in.
- Numbered steps with the literal command to run, not a description of it.
- A time budget, and what to do when the window is bigger than the budget (most recent material
  first, say what you did not reach, finish the task anyway).
- Explicit sorting rules: what counts as a real finding, what is noise, what belongs to another pass.
- A failure branch: what to do when a source returns nothing, refuses, or rate-limits, and how to
  report that separately from "nothing found".
- What the output is and where it goes.

Keep them current the cheap way: the bot edits its own playbook at the end of a run that went
sideways, and notes it in `memory/learnings.md`. A playbook untouched for months, for a routine
that fires daily, is either perfect or unread.

**Do not hedge about permissions in prose.** Public-facing text, outbound messages, spending,
publishing and merging are gated by the server: the bot files an approval and a person decides,
and the approval is spent once. `outbound_send: false` keeps sends off entirely. So a playbook says
"draft it and request approval", never "if you are allowed to, consider perhaps sending".

## 5. Schedules (routines)

A routine is a row in the hub owned by the bot: a cron (or a hub event), a title, and the text the
bot is told. The server runs the clock and turns each occurrence into a normal task
(`docs/routines.md`). People add them on the site (Tasks → Recurring); a bot adds its own from a
turn:

```
hub routine set daily-stock-pass --title "Daily stock pass" --cron "0 7 * * 1-5" \
    --text-file playbooks/daily-stock-pass.md
```

A catalog template may declare the same thing under `schedules:` in its `employee.yaml`
(`id`, `title`, `cron`, `timezone`, `template: playbooks/<file>.md`); `hub bot create` seeds the
new bot's routines from it once, and from then on the hub's rows are the routines.

- **`key`** (the `id` in a template) is stable. Keep it when you change the title: setting the
  same key again updates the routine in place, and the server keeps its settings and history.
- **`cron`** is five fields. The default timezone is America/Los_Angeles, not the machine's.
- **The text** is the playbook: keep the method in `playbooks/` and pass it with `--text-file`,
  so the repository still says how the bot works and the hub says when.
- Deleting a routine keeps its history; setting the same key again brings it back.
- Give each occurrence its own title when two passes of the same playbook run in one day, so a run
  can never be mislabelled and one pass cannot hide behind another.

**Frequency.** Start with one routine. A second earns its place when the first has run for a week
and someone has read the output. Every routine is a recurring bill against the model subscription,
and a routine nobody reads is the most expensive kind.

**Idempotence is not optional.** Missed occurrences coalesce, and a task still open from the last
occurrence absorbs the next one, so a run must be safe to repeat: check whether the output already
exists before producing it again, keep a watermark or a seen-store for anything that scans a
stream, and never let a retry duplicate an external effect. Occurrence deduplication cannot
guarantee exactly-once effects after a crash; the playbook has to.

**Always finish the scheduled task.** One left `open` or `doing` absorbs the next occurrence, which
quietly stops the schedule. Quiet day or not, the run ends with the task marked done and a one-line
note saying what was checked and what was found.

**The read-only period pattern.** A new bot can run fully while nothing it produces leaves the
building: set `outbound_send: false`, give it `read` in `access:` and no `post` or `send`, and let
it write drafts onto tasks. Routines fire, the work is real, the output is reviewed, and nobody
wakes up to a message the bot sent. Turn sends on per bot, later, deliberately.

## 6. Access and credentials

`access:` in `employee.yaml` declares what the bot may touch. **Not listed means not allowed.** It
is shown on the bot's page, it is what the shared connectors check, and it is what preflight
resolves against the machine before a bot goes active.

```yaml
outbound_send: false           # no email, DM, post or invite leaves the company
access:
  - service: gmail
    identity: "desk@example.com"
    can: [read, draft]         # send only with outbound_send: true and an approval
    env: GOOGLE_SA_KEY
    note: "reads and drafts on its own mailbox; never files or sends"
  - service: warehouse-api
    identity: "read-only service user"
    can: [read]
    env: WAREHOUSE_TOKEN
    credential_profile: warehouse
```

- `service` and `identity` say what and as whom. `can:` is the verb list (`read`, `draft`, `post`,
  `act`, `use`, `send`): add the narrowest verb that does the job.
- `env:` names the environment variable the credential arrives in. The name, never the value.
- `credential_profile:` points at a shared profile when several bots use the same credential, so
  you store it once.
- `vault: hub` says the value is granted to this bot in Settings → Credentials rather than kept in
  a secrets file, so preflight does not look for it on disk.
- `note:` records who authorized it and what is excluded; human and bot readers rely on it. A
  browser-based access also names `sites:`, so the connector can refuse everything else.

**Where the values live.** On the Mac that runs the bot, under the environment's workspace:

| File | Holds |
|---|---|
| `<workspace>/secrets/_shared.env` | Values every bot in the environment needs |
| `<workspace>/secrets/<slug>.env` | That one bot's own credentials |
| `<workspace>/secrets/<profile>.env` | A shared `credential_profile` used by several bots |

Mode `600`, owned by the operator, never in git, never pasted into a task or a chat. A credential
kept in the shared vault instead is delivered only for the duration of one run, as an environment
variable or a mode-0600 temporary file that is removed afterwards.

Declaring access does not provision anything. The operator puts the value on the machine, or grants
the vault credential to the bot; preflight then reports whether every declared key actually
resolves. Two things need no entry: the hub itself (`hub` and the `hub_*` MCP tools come with
every turn) and the decision model behind `hub_decisions` (`skills/decisions/SKILL.md`), whose key
the hub holds. A bot that needs a service it has not declared stops and says so on the task; it never
borrows another bot's credential.

## 7. Harness, model, effort and fallback

Levers set in **Settings → Bots**, not in the repository:

- **Harness**: which CLI runs the turn (`openai` / Codex, `claude`, `gemini`, `antigravity`,
  `grok`). **Model**: the latest model in that family (Sol, Astra, Grok 4.6, Gemini Flash,
  Claude Opus 5, Claude Fable 5.1). Search the picker: `grok` shows `grok/grok 4.6` at every
  effort; `sol` shows `openai/gpt 5.6 sol`.
- **Reasoning effort**: how hard it thinks. The main cost control, and the one to reach for first.
- **Fallback**: one optional harness/model if the primary is unavailable (billing, capacity,
  the runtime refused). **None (fail)** is the default. The hop starts a fresh session. OpenRouter
  is not a bot harness.
- **`max_run_minutes`**: the ceiling on one turn. Set it from the longest real routine, not hope.
- **`hermes`** is the one harness that is not a CLI on a registered computer: the bot is
  a Hermes profile somewhere else, with its own model, reached through a credential minted in
  Settings and never dispatched to. Model, effort, fallback and computer do not apply to it.
  [Hermes agents](hermes-agents.md) has the whole picture.

Effort is where the budget goes. A useful split:

| Spend little | Spend more |
|---|---|
| Sorting, labelling, triage by keyword | Legal and contract work |
| Sweeps and watches over a stream | Anything about money or a commitment |
| Digests of things already written down | Text that will be published or sent outside |
| Filing, archiving, index maintenance | A judgement a person would otherwise have to make |

Three habits save real money. Rules before models: if a deterministic filter handles most of the
input, run the filter first and let the model see the remainder. The decision model before the bot's own model:
when what is left is a decision (which bucket, is it covered, open this or not, which branch), one
`hub decisions` call answers it in two hundred milliseconds for a fraction of a cent, and the bot's
model reads only the rows the answers say to (`skills/decisions/SKILL.md`). And audit effort, because
it ratchets up and never down: take the busiest routine, read what its last ten runs actually
decided, and drop a level if nothing needed the extra thinking.

Because these live on the server, changing them takes effect on the next turn with no commit, no
push and no wait. If `employee.yaml` also names a runtime or model, it has to agree with Settings
or the bot will not run, which is why the plainest repository names neither.

## 8. A bot's first week

1. **Create it `planned`.** **Settings → Bots → Add bot**, then copy `templates/employee-repo/` to
   `<workspace>/emp-<slug>` on the Mac that will run it, fill in `AGENT.md` and `employee.yaml`,
   commit, push, and record the repository link on the bot. Leave `outbound_send: false` and
   add no routines yet.
2. **Run preflight** and fix everything it fails on. Warnings can wait; failures cannot.
3. **Give it one narrow task**, by hand, that a person could check in two minutes. One slice of the
   job, not the job.
4. **Read the first three runs end to end**, the run and not just the completion note. You are
   looking for where it guessed, what it read that it did not need, and what it invented.
5. **Fix the instructions, not the task.** Every correction you find yourself typing into a task
   conversation twice belongs in `AGENT.md` or a playbook. This is the whole of the first week.
6. **Promote to `active`** when three runs in a row need no correction.
7. **Add one schedule**, pointing at a playbook written from those three runs, and watch the first
   two occurrences.
8. **Review `memory/` weekly** for the first month, pruning: scaffolds that fixed a one-time
   problem, rules for mistakes that never repeated, decisions superseded twice. Then reread
   `AGENT.md` and delete what is no longer true.

### Common mistakes

Drawn from real bot reviews, stated generically.

- **`AGENT.md` becomes a decision log.** Dated override sections stack above `## Role` until the
  role is unfindable. Rules in `AGENT.md`, dates in `memory/decisions.md`.
- **The scheduled task is left open.** The next occurrence is absorbed and the schedule silently
  stops. Always finish the task.
- **"Nothing found" when a source was blocked.** Unknown coverage is not evidence of absence.
  Report successful sources, blocked sources and findings as three separate things.
- **Non-idempotent routines.** A coalesced or retried occurrence repeats an external effect.
  Watermark it, check before you write, make a repeat cost nothing.
- **Undeclared access.** The bot reaches a service not in its `access:` block, or reuses a
  credential that was in the environment for another reason. Declare it or stop.
- **The completion note buries the result.** Lead with the result, under 120 words, link the rest.
- **Near-duplicate knowledge files** instead of an edit to the file that already covers the topic.
- **Asking a person what the record already answers.** Read first; one clarifying question per task.
- **Asking a person to coordinate bots.** Route the child task, reminder, completion or draft pull
  request yourself. Escalate the business decision, not the task plumbing.
- **Too much effort, too many routines, too early.** Output nobody reads, billed daily, out of a
  window every bot shares.
- **A dirty or unpushed checkout on the runner Mac.** The bot's commits and a person's edits
  collide, and what runs is not what you pushed. Keep the tree clean and do not edit it mid-run.

## 9. More than one environment

The same slug can exist in two environments, and they are different bots: separate repositories,
separate tasks, separate credentials, separate history. `emp-sales` in one environment's workspace
has nothing to do with `emp-sales` in another's. Paths in instructions should therefore be written
relative to the repository, or relative to the environment's workspace, never hard-coded to one
machine's home directory.

GitHub is optional. A plain git repository in the environment's workspace is enough for a bot to
run: the runner reads the checkout on the Mac, and the bot commits into it. A remote buys backup,
review, and editing from somewhere other than the runner Mac, which is why preflight flags a
missing remote. The bot's repository link is recorded on the bot in **Settings**, and that same
repository can be cloned into another environment's workspace as a starting point there.

Two consequences when you run more than one environment:

- **Promote instructions, not state.** `AGENT.md`, `playbooks/` and `software/` travel well.
  `state.md`, `memory/` and most of `knowledge/` do not: they are that bot's history in that
  company.
- **Credentials never travel.** Each environment's `secrets/` directory is its own, on its own
  machine, and a vault grant in one environment means nothing in another.
