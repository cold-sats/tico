# First run

The first time the owner opens a new environment, the app is a wizard at `#/welcome`: name the
company, say what it does and what hurts, pick a starting team, add a computer (a Linux Docker runner or a Mac), optionally connect your own
agent, and press **Create my team**. Every company gets the assistant, BotOps, the Librarian and the Goal Manager, and none of them can be archived.
Creating defines the bots on the server and hands the rest to two places: a starter bot's repository is set up by the computer
the moment it is placed, and BotOps sets up every other template.

The wizard is the first of four pieces, all described below: the wizard, a short tour, the Getting
started checklist and a card at the top of each section. [After the wizard](#after-the-wizard) covers
the last three. To choose a first team and get the most from it, read the [onboarding guide](onboarding-guide.md).

Nobody else sees the wizard. Only the owner may write onboarding, and the sidebar entry
**Finish setup** appears only while it is unfinished.

The implementation is `backend/onboarding.py` (the record, the chooser, creating the team), `ui/first-run.js` (the
questions, the team screen and the screen after Create), `clients/catalog.py` (turning a template into a repository),
`runner/service.py` (the bots the computer sets up itself) and `templates/catalog/` (the templates). The quick start in the
[README](../README.md) is the same flow with the commands in it.

## The screens

Every **Next** saves the whole draft with `PUT /api/v2/onboarding`, so a closed tab loses nothing.

| Screen | What it asks | What it stores |
|---|---|---|
| Names | Company name, app name | `names`. From the moment they are saved they override `TICO_COMPANY_NAME` and `TICO_APP_NAME` everywhere, including in the catalog cards. The wizard does not ask for an assistant name: the tab is always called Assistant, and `names.assistant_name` keeps `TICO_ASSISTANT_NAME` unless a draft set it |
| About the company | What you do, who you sell to, whether software is your product, team size and what must never happen without a person | `answers`. Free text is never parsed; it is shown to a person and written into every bot's `knowledge/company.md` |
| What hurts, and what you use | The top one or two pains (about a dozen chips grouped by team, two each, and free text) and the tools already in use: mail, chat, CRM, GitHub, a meetings importer, docs | `answers.pains`, `pains_text`, `tools`. Nothing leaves the computer: the chooser runs in the hub |
| Your team | A starting point (a starter team, a full org chart or just the built-ins), then every bot: its name, who it reports to, remove, and add | `selected`: for each chosen slug, its template, display name, the `AGENT.md` text and `reports_to` (a person `human:<id>` or a bot slug; the owner by default). Nothing is created yet |
| Set up a computer | Nothing if a runner is already online (the server's own); otherwise download a setup file, then run three commands | Nothing. It polls `GET /api/v2/onboarding` every ten seconds and reports the enrolled machine |
| Connect your agent | Optional: **Connect an agent** makes a personal token and the MCP setup to paste into Grok Bot, Meta Muse or another agent | Nothing in onboarding; the token is the owner's own (`POST /api/v2/me/tokens`) |
| Review and create | A summary of all of it, the team with each bot's reports-to | **Create my team** calls `POST /api/v2/onboarding/complete` |
| After Create | One screen, below | Nothing in the record |

### The answers

| Field | Shape |
|---|---|
| `what_we_do` | Free text, up to 2000 characters |
| `customers` | `businesses`, `consumers`, `both`, or empty |
| `software_product` | `yes`, `no`, or empty: whether software is the product |
| `team_size` | Free text. The chooser reads the largest number in it |
| `pains` | Up to eight phrases, ticked from the starter cards' `pains` |
| `pains_text` | Free text, up to 1000 characters: what hurts, in their words |
| `tools` | Any of `mail`, `chat`, `crm`, `github`, `meetings`, `docs` |
| `never_without_person` | Any of `send`, `spend`, `publish`, `hire`. All four start ticked |
| `work_arrives`, `repetitive_work` | The earlier questions. The wizard no longer asks them, an older record keeps them, and `work_arrives` still implies a tool (`email` is mail, `slack` is chat, `crm` is CRM, `tickets` is mail) |

### The chooser

The hub chooses locally, from the answers and the catalog, with no network call. `GET` and `PUT /api/v2/onboarding` answer with two starting
points and every card's pain phrases (`pain_options`, each with its `team` and whether it is `featured`: the twelve the screen shows,
two per team, from `FEATURED_PAINS` in `backend/onboarding.py`; the rest still match what is ticked or typed). A template is only ever proposed when its **required prerequisites** are met: a
starter that needs mail is not proposed to a company that did not tick mail, and is named in `held_back` with what it needs. It can still be
added by hand.

**Starter team** (`recommendations`, about three to five bots, each with a one-line `why` and its prerequisites):

1. The best one or two pain matches. A chip that is one of a card's own `pains` is a strong match; free text matches a phrase when it shares
   all of its words, at least two of them, or its one or two keywords.
2. Then the starters a ticked tool names outright: `uses_github` (GitHub ticked) for Issue Triage, `uses_meetings` (a meetings importer) for
   Meeting Notes.
3. Then every starter that asks for `always` (Chief of Staff), which keeps its place: it is the first thing dropped from the list of
   others, not the last.

With no pain matched, the best fit for who they sell to and how work arrives is proposed instead. The `why` is the matched pain, or the tool
that named the card, and the first sentence of its summary; with neither, just the summary.

**Full org chart** (`full_chart`): every catalog template that fits, grouped into the teams of a company: Leadership, Sales, Marketing,
Support, Operations and Engineering (the card's `pack`), each with a **lead** and the rest reporting to it. The leads report to the company
owner. A template fits when it matches a pain, names a ticked tool, overlaps a tag the answers imply, or is for every company.

Both are starting points and there is no limit: the person adds, removes, renames and re-points anything before Create. The best pain
match is set up first (`setup_rank`), in either mode.

The tags the answers imply, for a card's `recommend_when`:

| Answer | Tag |
|---|---|
| Any answers at all | `always` |
| Customers: businesses or both | `sells_to_businesses` |
| Customers: consumers or both | `sells_to_consumers` |
| Software is the product | `sells_software` |
| Mail, chat or a CRM ticked (or work arriving that way) | `uses_email`, `uses_slack`, `uses_crm` |
| GitHub, a meetings importer or docs ticked | `uses_github`, `uses_meetings`, `uses_docs` |
| Work arrives as tickets | `uses_tickets` and `has_support_inbox` |
| Team size with no number above 10 | `small_team` |

### What Create does

**Create my team** (`POST /api/v2/onboarding/complete`) writes to the server only, in one request (a chart of 25 bots takes a fraction of a
second). It reaches no machine.

- BotOps, the assistant, the Librarian and the Goal Manager first, so they exist before anything is addressed to them, then everything picked, each `planned`
  with the card's summary as its description, `emp-<slug>` as its repository, the card's runtime, model and reasoning effort, the person
  it reports to, and the owner as its owner. A model a deployment does not offer falls back to the product default.
- The template and the reviewed instructions are stored in the bot's server-side config, with the **template version** (the release whose
  catalog it came from: `template_version`).
- A **starter** template (a card with a `first_routine` and an `onboarding` conversation) is created whole and parked:
  - `onboarding_state: needs_onboarding`, exposed on `/api/v2/bots`, `/api/v2/bots/{bot}` and `/api/v2/org`;
  - its first routine is seeded paused (the template declares `enabled: false`);
  - **no task is filed for BotOps**: the computer materializes its repository from the catalog as soon as the bot is placed on it
    (`materialize: true` in its config, which only onboarding writes), and the bot is activated as soon as it is placed;
  - the scheduler skips it, and only a person's chat message is claimed for it (a task notice, a Slack route, a bot's request or a routine
    waits), so nothing runs until it is onboarded;
  - it does not count toward a member's bot limit while parked.
  The built-ins and every other template are not parked.
- Any other template is created `planned` and gets one task for BotOps, as before. Title: `Set up <Display> from the <template> template`.
  Body: the slug, the template, the display name, the reviewed instructions in a fenced block, and the onboarding answers.
- Every bot from a template that no machine holds is assigned to the owner's most recently enrolled computer. If none is enrolled yet,
  enrolling the owner's computer afterwards does the same, so the order the two are done in does not matter. A bot someone placed by hand is
  never moved.
- Finishing twice is safe: it reopens no task, creates no second bot, and keeps the first completion time.

### Needs onboarding

A parked starter shows **Needs onboarding** on the org chart (a small *Setup* mark), on its page and after Create. **Start setup** sends it
the message "Let's set you up." as the person, which starts the onboarding conversation its `AGENT.md` describes; any first message from a
person does the same. The bot introduces itself, asks the template's questions in one message, writes a first draft from the company's own
data, and proposes its first routine. On the person's yes it arms the routine and calls `hub bot onboarded` (MCP `hub_bot_onboarded`,
`POST /api/v2/bots/{bot}/onboarded`). That clears the mark, lets its routines run and counts it toward a member's limit. On a no it stays
parked and answers people only.

### After Create: one screen

- **Setting up**: each bot with its progress. A starter says *Setting up its repository* until the repository exists,
  then its **Start setup** works.
- **Invite an admin**: a name and an email. The person joins the roster and the sign-in list and is made an admin (`POST /api/v2/access/people`,
  then `POST /api/v2/access/people/{id}` with `role: admin`). Tico sends no email.
- **Who owns each bot**: add a person as a co-owner of any bot (`POST /api/v2/bots/{bot}/co-owners`; [permissions](permissions.md#bot-owners)).
- **Connect your tools**: links to the places a ticked tool is connected (Settings > Cloud services, Integrations, Credentials). Secrets
  are entered in those fields, **never in a chat with a bot**; the BotOps playbook says the same, and a secret pasted into a chat is treated as
  leaked.

## After the wizard

The wizard is done once, by the owner. Everything after it is per person, so a teammate who
joins later gets the same help without the owner doing anything.

```
wizard  ->  tour (once)  ->  Getting started checklist  ->  section cards
             replay: ?        until done or hidden           until closed
```

### The tour

Six spotlight steps: Updates, Tasks, your bots (the org list), Docs, Market, Meetings. **Next** moves
on, **Skip** or **Esc** closes it, and focus stays inside it. On a phone it opens the navigation drawer
and shows the same steps. It opens by itself once, right after **Finish setup**, and can be replayed
from **?** (How Tico works) with **Take the tour**. That it was seen is kept per person.

### The checklist

**Getting started** sits at the top of the sidebar with a count such as `3/9`. It leaves the sidebar
when every step is done or the person hides it, and stays reachable at `#/getting-started` (the button
on that page, or **Getting started checklist** on the Help page, brings it back).

`GET /api/v2/getting-started` computes every step from live state on each request. Nothing is
self-reported and nothing stays ticked once the thing it names goes away.

| Step | Done when | Who sees it |
|---|---|---|
| Signed in | Always, if you can read this | Everyone |
| A computer is online | An enrolled, unrevoked runner sent a heartbeat in the last 2 minutes | Owner |
| A model is signed in on it | An online runner's readiness lists a runtime that is installed and `authenticated: ready`. The runtime is the company's default; with none, any runtime of an enabled provider | Owner |
| GitHub is connected | The GitHub App is stored and installed (`backend/github_app.py`). Optional: it can be skipped, and a skipped step counts toward the total | Owner |
| BotOps is active | The `botops` bot's state is `active` | Owner, bot administrators |
| Create your first bot | Any bot other than the assistant and BotOps exists and is not archived | Owner, bot administrators |
| Set up the next bot | Done when no starter is waiting; while one is, the label names it (the one matching the top pain first, by `setup_rank`), says why, and links to its page, where **Start setup** is | Owner, bot administrators |
| First approved output | A starter bot has said it is onboarded (`onboarding_state: onboarded`): a person approved its first routine, which is the first output reviewed. It replaces a count of set-up bots, and completes by one | Everyone |
| Your first update arrived | The `updates` table has a row | Everyone |

The model step carries a **Sign in** button when a computer has Codex or Claude Code installed but not
signed in: it opens the same dialog as Settings > Devices, which shows the CLI's link and one-time code
(and a paste field for Claude Code) so the owner can sign the runner in from the browser, no SSH. Tico
relays the CLI's prompts and never sees the credential (`backend/model_login.py`, and `runner/login.py`).

Every step that is not done carries a one-line reason and a link to the place that fixes it (Settings >
Devices, AI providers or Cloud services, the bot's page, Tasks, Updates).

**Create your first bot** opens **What should your bot do?** (a description and an optional name).
It files a task for BotOps titled `Build a bot: <name>` with the slug, the description and the
onboarding answers, via `POST /api/v2/getting-started/bot`. That needs BotOps active and the owner or
a bot administrator. The task names no template, so BotOps picks the closest one
(`playbooks/set-up-a-bot.md`). While that task is open the step points at it.

### Section cards

The first time a person opens a section, a compact card sits above it. It can be closed with the X,
and stays closed for that person. It never blocks the page.

| Section | The card | What it does |
|---|---|---|
| Docs (owner) | Where do your current docs live? Paste links (a help site, a Drive folder, a Notion page, a GitHub repository, anything), each with an optional description; "No docs yet" leads to writing a first internal doc, "Files to upload" to Import | `POST /api/v2/getting-started/docs` `{"links": [{"url", "description"}]}` makes each link a linked doc (kind detected from the address; Tico keeps no copy) and answers `{"linked": [...], "skipped": [...]}`. No task is filed and no bot is involved ([docs.md](docs.md)) |
| Market (owner) | **Research your market**: one box for a website, a description or links to anything about the market, and **Start research** (with an **Attach files** link to the Docs import). Shown on the Market page and the Getting started page while the market is empty | `POST /api/v2/getting-started/market` `{"text"}` files one task, "Set up the market map", to the Librarian and answers `{"task_id", "bot": "librarian"}`; `409 librarian` while the Librarian is not running. The Librarian's `playbooks/market-setup.md` researches the sources and writes the market pages and graph ([librarian.md](librarian.md)). The page then shows "The Librarian is researching your market. This usually takes 5–10 minutes." until the market has content (at least two minutes, at most thirty), kept in the browser, polling the market every 30 seconds |
| Bots | In the org list while there are no bots of your own: **Connect a bot you already have** (the connect-an-agent dialog) or **Build one with BotOps** (the form above) | As above |
| Tasks, Goals | One or two sentences and one action: create a task, set a first goal | Opens the real control on that page |
| Updates | What daily and Friday updates are | Nothing to do |

### What is stored, and who may do what

A person's choices are one row in `preferences` (key `onboarding.progress`, the same per-person store as
`/api/v2/preferences/{key}`): tour seen, checklist hidden, cards closed, optional steps skipped.
`POST /api/v2/getting-started/state` writes only the caller's own row, and the checklist read shows only
the caller's own choices. Runners and bots get `403`.

| Endpoint | Who |
|---|---|
| `GET /api/v2/getting-started` | Any person; the steps returned depend on their role |
| `POST /api/v2/getting-started/state` | Any person, for themselves |
| `POST /api/v2/getting-started/bot` | Owner or bot administrator |
| `POST /api/v2/getting-started/docs`, `.../market` | Owner |

The code is `backend/getting_started.py` and `ui/getting-started.js`. Tests: `backend/tests/test_getting_started.py`
and `ui/tests/getting-started.cjs`.

## What finishing creates

See [What Create does](#what-create-does). Nothing there reaches a machine or a repository: it writes definitions and tasks, and the
computer does the rest.

## What the Mac does

The runner materializes the bootstrap bots and the starters first run created during readiness, once per bot, when the
repository is missing and this machine is the one the bot is assigned to. That is a few seconds after Create, so the screen after it
shows *setting up* per bot until each repository exists (about 70 ms a bot; 25 bots take under two seconds). Everything else stays missing
until BotOps has built it.

1. Read the cards from this checkout's `templates/catalog/`.
2. Take the template from the bot's server-side config, and use it only if its card says
   `bootstrap: true` or the bot's config says `materialize: true` (only onboarding writes that). A registration made before the catalog existed carries no template, so a bot
   named `coo` falls back to the assistant template and one named `botops` to the botops template.
3. Read the names from `GET /api/v2/config` and the answers from `GET /api/v2/onboarding` with
   this machine's own credential. Both are read fresh, because onboarding is answered after the
   machine is enrolled.
4. Copy the template folder to `<workspace>/emp-<slug>`, fill the placeholders, set `name:` in
   `employee.yaml` to the slug, write `knowledge/company.md` from the answers, replace `AGENT.md`
   with the reviewed instructions when there are any, then `git init` and one commit.

An existing directory is never touched. A failure is a readiness problem on that bot rather than an
exception, so the machine keeps reporting the others.

## What BotOps does

BotOps works one setup task at a time, following `playbooks/set-up-a-bot.md` in its own repository:
read the task, `hub bot create <slug> --template <template> --name "<Display>"`, put the reviewed
instructions into `AGENT.md` (or tailor the template's to the answers), run `hub bot check <slug>`
and fix every failure, commit, then finish the task with the repository path, what it changed, the
check result and the one thing to read before activating.

It never activates a bot, never creates a credential, and never overwrites a repository that
already exists.

## The assistant, BotOps and the Librarian are built in

Every company gets all of them, and none is a choice: their cards are `required: true` in the wizard, so the wizard
builds them whatever else is ticked, and both become active once a computer is enrolled ([Activating](#activating)).
The assistant is every person's private [Assistant](assistant.md) (a tab on their own page); it also works in the
background: it routes Slack messages to the bot that owns them, takes meetings and tasks nobody was named for, reviews
BotOps' refused writes, and runs its own routines.

None can be archived or deleted by anyone, the owner included, through Settings, the API, `hub` or BotOps itself:
the archive route answers `409 system_bot`. Pausing, renaming and editing their instructions stay allowed. Settings >
Bots lists them as **Built in**, with no Archive or Delete control. Like every bot they start open to everyone; their
**Access** can be narrowed in Settings > Bots ([permissions](permissions.md)), and the owner keeps full access to them
whatever it says.

The third, the [Librarian](librarian.md#built-in), answers questions from the company's docs. A company from before it existed gets it on
update, without a click, once a model is chosen and a computer is enrolled; until then its owner gets **Turn on the Librarian** on Ask AI.

The fourth, the [Goal Manager](goals-and-kpis.md#the-goal-manager), keeps the KPIs and sets goals' automatic colours. It is
built the same way (a required, bootstrap card; a company from before it existed gets it on update once a model is chosen
and a computer is enrolled). Its routines start paused: the server arms the daily KPI pass once the first KPI exists, and the
weekly goals review stays paused until the Goal Manager arms it after the owner has read the first one.

A company that set the assistant aside before it was built in (v0.2.1 to v0.2.9 let the wizard skip it) keeps it archived
on update: nothing restores it automatically. Its owner sees "The Assistant is off" on the Assistant tab and at the top of
Settings > Bots, and one click on **Turn on Assistant** brings the same bot back with its history (or adds it from the
catalog if it is missing), places it on BotOps' computer and activates it. From then on it cannot be archived again.
While an assistant is off, or paused, what used to fall back to it goes to BotOps or to a person:

| what | with no assistant |
|---|---|
| Slack, nobody at threshold, or every chosen bot refused | BotOps gets the message with the top three candidates and asks which bot; with no BotOps running either, the message is recorded and nobody is woken |
| Slack, no decisions key | the same fallback bot (BotOps) |
| Meetings and notes sent in **Auto**, for a person with no bot of their own | BotOps, which takes work from anyone the way the assistant does |
| A person handing work to "whoever takes it" | BotOps accepts it from anyone, as the assistant does |
| Review of BotOps' refused writes (rule 8) | a task for the owner, which shows in Needs you |
| A bot whose `reports_to` names a bot that is not there | shown under the owner in the org chart, not hidden |

## Activating

Only an active bot is given work. Finishing onboarding activates the assistant and BotOps as soon
as a machine hosts them (and again when a machine is enrolled later), because BotOps cannot be
handed setup tasks while it is planned. A starter is activated the same way once placed, and is still parked: it answers a person and
nothing else until it is onboarded. Every bot BotOps builds gets its own **Activate** button
when its repository is reported present; that stays a person's decision.

## Adding a bot later

- **Settings → Bots → Add from catalog.** The same cards, minus the bots that already exist. A starter is created parked, exactly as Create
  makes it; any other template is created `planned` with the same BotOps task the wizard would have filed.
- **From a BotOps task**, inside a turn: `hub bot create <slug> --template <template> --name
  "<Display>"`, then `hub bot check <slug>`. Both need `HUB_WORKSPACE`, which the runner puts in
  every turn's environment.
- **By hand on the Mac**: `scripts/tico -e <env> bot create <slug> --template <template>`. This
  materializes from the same catalog with the environment's names but without the onboarding
  answers, so `knowledge/company.md` says nobody has answered them. Register the bot in
  **Settings → Bots** afterwards.

The pickers key a bot by its card's slug, so each template yields one bot there. A second bot from
the same template is one of the two command line routes, with a slug of your own.

## Adding a template to the catalog

The catalog ships 38 starter templates in six packs, each with a card; [Starter bots](starter-bots.md) lists them all.

`templates/catalog/<template>/` is one template. The folder name is what `--template` takes.

- `card.yaml` describes the template to whoever is choosing. It is never copied into a bot's
  repository. Fields: `template`, `slug` (the default bot slug), `name`, `required`, `bootstrap`,
  `summary`, `owns`, `never`, `runtime`, `model`, `reasoning_effort`, `recommend_when`, `pack` (its team: `basics`, `sales`,
  `marketing`, `support`, `operations` or `engineering`), `lead` (one per pack: it leads its team on the full org chart), `pains`, `prerequisites` and, for a starter, `onboarding`, `first_routine`,
  `approval_required` and `example_output`. The server serves all of them except `onboarding` and `example_output`, and the chooser reads
  `pack`, `pains`, `prerequisites` and `recommend_when` ([Starter bots](starter-bots.md)). A card with a `first_routine` and an
  `onboarding` list is a **starter**: Create parks it (`needs_onboarding`), so its `onboarding` playbook must end with `hub bot onboarded`.
- Everything else in the folder is the repository the bot starts from: `AGENT.md`,
  `employee.yaml`, `playbooks/`, `knowledge/`, `memory/`, `state.md`, `.env.example`, `.gitignore`.
- `{{company_name}}`, `{{app_name}}`, `{{assistant_name}}` and `{{bot_name}}` are filled in every
  text file before the first commit, and in the card's own words wherever a person reads it.
- `required: true` means the wizard always includes it. `bootstrap: true` means the machine
  materializes it itself and no BotOps task is filed for it. Both are true for the assistant and
  BotOps only.
- `recommend_when` matches the tags in the table above. A card may carry others, and the shipped cards do
  (`publishes_content`, `tracks_mentions`, `has_pipeline`), which the answers derive from what is gated and who they sell to. The `inbox` card
  asks for `has_personal_inbox`, which no answer derives, so it is proposed only by a matching pain and always needs a person's mailbox
  chosen alongside it.
- The release ships `templates/catalog` as `.yaml` and `.md` files only, which is all the server
  reads. The full folder is materialized from the checkout on the Mac, so a template only works
  for real once that Mac has pulled it. `TICO_CATALOG_DIR` points either side at another catalog.

## Troubleshooting

**The wizard does not appear.** It is shown when `GET /api/v2/config` says `onboarding_needed`,
which is true only for the owner and only while onboarding has no completion time. Someone who is
not the owner is sent to Tasks, and a bot administrator can read the record but not write it.
Everyone else gets `403` on `GET /api/v2/onboarding`. To see the finished record again, open
`#/welcome` directly; it opens on the progress screen.

**Bots stay "Missing bot repository or AGENT.md".** For the assistant or BotOps it means no machine
is enrolled, or the bot sits on a machine that is not running, because a machine only materializes
its own assignments. Check **Settings → Bots** for the computer column and **Settings → Machines**
for the last heartbeat. A starter bot needs the same: the computer it is placed on sets it up, and until that computer
is online its row says *setting up*. For any other bot it means BotOps has not built it yet:
check that BotOps is `active`, that its repository exists, and read its setup task. The wizard's
rows say `waiting` until the machine reports a repository, and a bot no machine has reported on at
all is also `waiting`.

**`422` on a template name.** `PUT /api/v2/onboarding` and `POST /api/v2/bots` refuse a template
the catalog does not have, with the name in the detail. Check the folder exists under
`templates/catalog/` on the server, that it has a readable `card.yaml` with a `template:` field,
and that the key is a slug: lowercase letters, digits and single hyphens.

**No cards at all.** A missing or unreadable catalog leaves onboarding running with nothing to
offer, and the bots screen says so. On a hosted server that means the release did not carry
`templates/catalog`, or `TICO_CATALOG_DIR` points somewhere empty.

**A starter does not answer, or a routine never runs.** While it is `needs_onboarding` it answers only a person's chat message: a task
notice, a Slack route, a bot's request and its routines wait. Press **Start setup**, or say anything to it in its chat, and answer its
questions. When you approve its first routine it calls `hub bot onboarded`. If it cannot (a member's bot at their limit answers
`bot_limit`), archive a bot you no longer need or ask an admin to raise the limit in Settings > People. An owner or a bot's manager can
also call `POST /api/v2/bots/{bot}/onboarded` to release a bot whose conversation went wrong.
