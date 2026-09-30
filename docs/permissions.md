# Who can see, read and write to a bot

Every bot has three permissions. Each one has its own audience, so a bot can be visible to the whole
company, readable by one team and open to requests from everyone.

| Permission | What it covers |
| --- | --- |
| **See** | The bot in the org chart and in every bot list: its name, role, who runs it and who it reports to. |
| **Read** | Its activity: its tasks, updates, files, status and run log, routines, the shared rooms and chats it is in, and the activity sections of its page. |
| **Write** | Sending it messages, chatting with it, asking it; creating or reassigning tasks to it; leaving it notes; comments that wake it. Its approvals work as they always did. |

An audience is **Everyone**, or a list of **people**, **teams** (a team name, or a department on the org
chart) and **bots**. Anyone who may read or write a bot can also see it, whatever its See list says.

New bots, and every bot after an upgrade, start **Open**: Everyone for all three.

## Setting it

Settings > Bots has an **Access** column. **Edit** opens the editor, with three presets and a custom mode:

| Preset | See | Read | Write |
| --- | --- | --- | --- |
| **Open** | Everyone | Everyone | Everyone |
| **Visible, requests only** | Everyone | the people, teams and bots you choose | Everyone |
| **Private** | the ones you choose | the ones you choose | the ones you choose |
| **Custom** | each level chosen on its own | | |

The column summarises it, for example `See: Everyone · Read: Legal · Write: Everyone`. A person who
may only use the bot sees what they can do (`You: See · Write`) instead. Changes are revisioned and
appear in the settings history, where the owner can undo them, like the people a bot works for.

Who may edit a bot's access: its owners (see [Bot owners](#bot-owners)): the company owner, the admins, the bot's creator
and co-owners, and the people it reports up to on the org chart (the same people who may change the bot's other settings).
The Assistant, BotOps, the Librarian and the Goal Manager can have their access edited too.

## Always full access

Whatever the audiences say, these callers can see, read and write to a bot:

- the company **owner**;
- the **bot itself**, for its own data;
- the people **above the bot on the org chart** (whoever it reports up to), and a bot above it in the
  `reports_to` chain when the caller is a bot;
- an **admin**, and the bot's **owners** (its creator, co-owners and operator). This is the same rule that lets
  them change the bot's settings, so being able to edit who has access and having access always go together.

## Roles, and what a member may do

Everyone on the roster has one company role:

| Role | Who | Can |
| --- | --- | --- |
| **Owner** | whoever the company was set up for (one at a time) | everything: sign-in domains, ownership, providers, roles |
| **Admin** | people the owner makes admins (the old "bot administrators": the list is read under either name for one release) | manage every bot but the built-in ones (below), people and computers (enrol, revoke, open to members' bots); set what members may do and the bot limit. They cannot make or remove admins or owners. They are credential administrators and see the SQL page, unless the owner turns that off ([Team rules](#team-rules)) |
| **Member** | everyone else | create and manage their own bots, add coworkers, and use the bots they are allowed to |

Settings > People (owners and admins) shows each person on one row: their role (the owner switches Admin and Member there), a
**Can sign in** switch, and a ⋯ menu with two capabilities per member:

- **Can add bots** (`create_bots`): on for everyone unless switched off.
- **Can add people** (`add_people`): on by default for coworkers, that is people whose email is in the company domain. A
  member with it on may add a person whose email is in the company domain. Adding anyone outside it needs an owner or an admin,
  whatever the capability says.

The **company domain** is the domain(s) the owner allows to sign in (Settings > People, **Anyone at <domain> can sign in**); when
none is set it is the owner's own email domain. When that is a public mail service such as gmail.com, it is the team email domain the
owner gave at first run (**Names**, optional), then the company domains of the people already on the roster; with none of those,
members add nobody until the owner adds a person or sets a domain. A newly added person goes on the roster and on the sign-in list, so they can
actually sign in.

**Can sign in** off keeps a person on the roster and the org chart but refuses their sign-in, sessions and API tokens until it is
on again. Owners and admins switch it for members; only the owner switches it for an admin; nobody switches it for themselves or
for the owner.

**Credential administrators** are the owner and the Admins, so a team gets going without the owner storing every key. When the
server names its own list with `TICO_CREDENTIAL_ADMINS` it is that list (the owner and whoever it names), nobody else: the Admins
are then not credential administrators. The owner may turn **Admins store credentials** off ([Team rules](#team-rules)); a member is
never one.

## Team rules

The product favours getting going fast, and the owner tightens it later. Settings > People (owner only, saved as they change;
`GET` and `PUT /api/v2/access/rules`) has five switches, all **on** by default:

| Rule | On (default) | Off |
| --- | --- | --- |
| **Assistant acts without asking** | the Assistant makes tasks for bots, comments on tasks no other person is on, and messages bots directly; a card is for anything else ([Assistant](assistant.md)) | the Assistant acts directly only on the person's own tasks; a task, message or comment involving a bot is a card |
| **BotOps changes providers and limits without asking** | BotOps sets the company's AI providers and raises spending limits at once (lowering a limit is always direct) | both are a Confirm card |
| **Admins store credentials** | Admins are credential administrators | only the owner (and `TICO_CREDENTIAL_ADMINS`) stores credentials |
| **Admins see SQL** | Admins open the SQL page | the SQL page is the owner's |
| **Members make personal tokens** | any person makes a personal API token, which sees what they see | the owner and the Admins do |

Only the owner changes them, and BotOps cannot: the route is not delegable.

**The built-in bots** (the Assistant, BotOps, the Librarian and the Goal Manager) act for the whole company, so only the owner changes their settings,
routines, access or place, and only the owner may add them. A member cannot register a bot with the name `assistant`, `botops`,
`librarian`, `goal-manager` or `coo`; an Admin can, and manages every other bot.

A member may have at most **25 active bots** by default; owners and admins have no limit. An admin changes the number in
Settings > People (**Bot limit per member**). Past it, adding a bot answers `409 bot_limit` with what to do. A starter bot that is still `needs_onboarding`
([First run](onboarding.md#what-create-does)) is parked, does nothing on its own and costs nothing, so it does not count; it counts once
it says it is onboarded, and that call answers `bot_limit` when the member is already at their limit.

## Bot owners

Each bot has owners: its **creator** (added automatically), any **co-owners**, and its operator. Whoever the bot reports up to on
the org chart, and every admin, are owners without being listed. One rule, `Auth.bot_manager`, says who may manage a bot, and it
is the same people who always have full access to it. A bot owner can:

- edit its configuration: instructions, model, routines, name and description, repository;
- set its See, Read and Write access;
- pause it, rename it, archive it (never the built-in Assistant, BotOps, Librarian or Goal Manager);
- add or remove co-owners (`POST /api/v2/bots/{bot}/co-owners`, Settings > Bots, **Owned by**);
- give it a stored credential they hold themselves, and no one else's.

A member cannot change a bot that is not theirs, through Settings, the API or BotOps.

## Computers for members' bots

Every bot on a computer shares that computer's trust: the same OS user, workspace, model logins and `secrets/_shared.env`. A bot
created by a member has instructions the company has not reviewed, so it does not go on just any computer. Each computer has
**Accepts members' bots** (Settings > Devices, owners and admins):

- **On** for every new computer, whoever enrols it, so members' bots go on any computer without asking; an owner or an admin turns
  it off per computer. A computer that existed before this default keeps what it had: turn it on where you want it.
- A bot created by a member can only be placed on **its own operator's computer, or a computer that takes members' bots**.
  With none, it stays planned, and the answer says to ask an admin to place it or to open a computer. Admins may place a member's
  bot on any computer. Placing a member's bot never hands it to the computer's operator: it stays theirs.
- Setup that places bots for you (a computer enrolling, the wizard) leaves a member's bot alone unless the computer is its operator's
  or takes members' bots.
- Settings > Health warns when bots members created run on a computer whose `secrets/_shared.env` holds keys, since the bot
  instructions could ask a run for them. Give members a computer with no shared keys and close the others.

A computer still hosts its operator's bots and the owner's; taking members' bots adds members' bots, it does not move anyone else's.

## BotOps acts as the person who asked

An owner should be able to say "build me a Jira bot, and add Sean" in chat with BotOps and have it done. BotOps therefore acts **as the
person whose own chat message started its current turn**, checked with that person's rights and recorded as theirs, "via BotOps"
(events, settings history). Not more than they may do: a member cannot edit another person's bot through BotOps any more than by hand.

BotOps never acts for a message a **bot** wrote, one the **Assistant** wrote for a person (`refs.via`), a person's words
**inside a task** or a document, a message **routed from Slack** (anyone in the thread can shape it), or a message more than a week old.
A message cited by id (`on_behalf_of`) must be the requester's own, in their own chat with BotOps rather than a room another person
spoke in, and under a day old, and it must be the same person whose message started the turn. Someone who has left lends nothing.
A refused request answers `on_behalf_of`; BotOps reports it and stops.

The same goes for routines and quarantine: BotOps sets a bot's routines only as the person who asked, who must manage that bot (a
turn no person started, such as setup, may seed routines on a bot still being built from its template and nothing else), and clears
a quarantine only citing that person's message and their management of the bot. BotOps has no authority of its own over other bots.

The commands (with MCP tools of the same names):

| Command | Does |
| --- | --- |
| `hub bot register <slug> [--name] [--description] [--reports-to] [--template]` | creates the planned server record as the requester, who becomes its owner; safe to repeat. `hub bot create` registers automatically in such a turn |
| `hub bot access <slug> [--see V] [--read V] [--write V]` | show or set who sees, reads, writes (`everyone`, or `ben,team:legal,bot:analyst`) |
| `hub bot owners <slug> [--add P ...] [--remove P ...]` | co-owners |
| `hub bot set <slug> ...` | name, description, reports-to, status, repository |
| `hub bot onboarded [slug]` | a starter bot's own call, once its setup is done: it stops being `needs_onboarding` (its manager may call it for it) |
| `hub people add <email> [--name] [--title] [--reports-to]`, `hub people list` | the roster |

| `hub bot place <bot> [--computer C]` | puts a bot on a computer: the one named, or the only one, or the least busy that takes it |
| `hub bot go-live <bot>` | places it if it has no computer, turns it on, and for a starter bot starts its setup chat as the requester |
| `hub bot model <bot> [<model>] [--effort E]`, `hub bot pause\|resume <bot>` | the model (none: list the choices), stop and restart |
| `hub routine on\|off <key> --bot <bot>` | a routine on or off |
| `hub computers`, `hub fleet-check` | the computers a bot may go on and what runs on each; what is wrong with the bots, most urgent first, each with its fix |
| `hub credential request\|set\|list` | a card for a secret in the chat, storing one a person pasted, the credentials with their bots (never a value); see [credential-vault.md](credential-vault.md) |
| `hub support file "<message>"` | tells the Tico team about a gap or a fault: a Confirm card shows the exact message, and nothing is sent until they confirm |
| `hub api <METHOD> <path> ['{json}']` | any other v2 route, as the requester |

`hub api` (and every friendly command above) sends `X-Tico-On-Behalf-Of: turn`. The server answers the request **as the requester**, so its own
checks are the only gate: a member is refused what only an owner may do, an owner is not. A route is one of three kinds
(`backend/botops_act.py`): it **runs at once** (bots, routines, goals, tasks, docs, access, models, placement, credential grants and revoking them, a computer's restart
and model sign-in, providers and spending limits, messages and chat to bots, coworkers in the team's domain), it comes
back as a **Confirm card** (below), or it is **not delegable** at all: tokens and enrollment codes, approvals, transferring ownership, a
stored secret's own routes, agent credentials. Reads are the requester's reads. A secret never travels in a `hub api` body (a key named
`secret`, `password`, `token`, `api_key` and the like is refused).

Everyday edits to a bot the person owns happen at once, and each is undoable from Settings > Bots history.

### What still needs their click

These are proposed instead: the command answers `needs_confirm: true` and a **Confirm card** appears in the person's chat with BotOps
(the same card the Assistant uses: "Runs as you, only when you confirm"). Nothing changes until they click, and only they can:
BotOps, the owner and the admins cannot confirm for them.

- adding a person from outside the company domain (owners and admins only); a coworker in the domain is added at once;
- making someone an Admin, granting `add_people`, changing roles, or changing a person's email (it decides who is an Admin) or team
  (it is an access audience);
- giving a bot a stored credential (a tool registration that uses a shared credential or another bot's);
- placing a member's bot on a computer that is neither its operator's nor open to members' bots (admins only);
- deleting (archiving) a bot, removing a computer, and changing whether a computer takes members' bots;
- who may sign in, and what members may do (the bot limit);
- updating Tico, the directory sync, disconnecting Slack or GitHub;
- a message in their name to a person (a message or chat to a bot goes at once), a decision on a goal proposal, and a support message to the Tico team.

The company's AI providers and raising a spending limit go at once too, unless the owner turns **BotOps changes providers and limits
without asking** off ([Team rules](#team-rules)); then they are cards, and lowering a limit still is not. BotOps can start a model
sign-in on a computer (`POST /api/v2/runners/<id>/logins`, and read its link and code): the code a person pastes back is theirs to
give in the app. It can turn inbox sharing on for a computer (`POST /api/v2/runners/<id>/inbox-sharing`, [Mail](mail.md)) only where
one owner runs every computer and bot; anywhere else an owner or an admin does it. It still never turns on a bot's sending outside the
company, and never deletes a bot or a repository; it may delete a branch that is already merged.

What only an owner or an admin may ask for (sign-in and member limits, a computer taking members' bots, providers and the company
spending limit when they are cards, updates, directory, disconnecting) is refused at once for a member, not handed over as a card that would fail.

The card shows every field the request carries, and its description, written by the server and never by the bot, names each field it
changes and, for a placement, the computer and whether it takes members' bots.

BotOps reports "there is a card waiting in this chat" instead of asking the person to go to Settings.

### Why it is built this way

A bot's instructions and everything it reads (mail, web pages, documents, a colleague's task) can try to steer it. If BotOps could
act with the company's full authority, or for whoever a piece of text names, one injected sentence would be a privilege escalation.
So it borrows one person's rights at a time, only from the message that person typed to it in chat, never more than they have, and
the few changes that widen who can get in or what a bot can hold need that person's own click. For the same reason a member's bot goes
only on computers set aside for members' bots: bots on one computer are not isolated from each other.

### A computer for every active bot

A bot that becomes active without a computer (added active, turned on, resumed, or built by BotOps) is placed by the server: on the company's
only computer, else the least busy online one that takes it (a bot BotOps builds prefers BotOps's own computer, where its repository is). A member's bot goes on that member's own computer or one opened to members' bots,
and never on a closed one. With none that takes it the bot stays as it is and the answer says so; the scheduler places it as soon as one can
(`backend/placement.py`). People see a bot that is only set up, not yet turned on, as "Setting up".

## Write without Read

Someone who may write to a bot but not read it can talk to it, and only sees what is theirs: their
own conversations with it and the tasks they requested, created or own. They do not see its status,
run log, files, updates, routines, other people's tasks or shared rooms, and the step-by-step "what it
did" under its replies is hidden. The bot's page for them holds its name, role, who runs it, the
people it works for, a **Send a request** box, and their own threads and tasks. A bot they may only
see shows the same About card and no request box.

When a bot uses a shared room, the room belongs to the people it works for who may read it. Anyone else
who writes to it talks to it in a room of their own.

## Bots and people are checked alike

A bot's rights to another bot come from the same audiences: put a bot in another's Write list to let it
send that bot requests. A bot may always answer one that wrote to it, or that holds a task it asked for,
so a private bot can still be replied to. `bot_contact` (Other bots: may chat and assign, replies only,
tasks only) stays as a further limit between bots and now also applies to notes and to comments that
wake a bot.

Personal API tokens, the MCP tools and the Assistant act as the person, with the person's access.

## What each answer looks like

- A bot the caller cannot **see** does not exist for them: lists leave it out, counts and pages do not
  include its work, and asking for it by name answers `404`.
- A bot they can see but not read or write answers `403 forbidden` with what is missing, for example
  `You can see counsel but not send it requests. Ask the person who runs it for Write access.`

`GET /api/v2/bots` and `GET /api/v2/org` return only the bots the caller can see, each with
`access: {see, read, write}` for that caller, and take `?can=read` or `?can=write`. A bot the caller may only
see comes back without its status, machine, queue or configuration. The org chart is one piece: the bots
under a hidden bot hang from the nearest thing above it that is still shown.

## The Legal example

The Legal bot reviews contracts. Everyone should be able to send it a request, but its work is
Legal's business.

1. Settings > Bots, **Edit** in Legal's Access column.
2. Choose **Visible, requests only**.
3. Under *Who can read its work* tick the **Legal** team. Save.

Now everyone sees the bot and can chat with it or give it a task. Cara, on the Legal team, also reads its
tasks, updates and files. Dee, in Sales, sees a **Send a request** box and her own threads and
tasks with it; the bot's status, files and other people's requests are not shown to her. To let the
Sales lead read it too, add them to the Read list.

The same through the API, as the owner or the bot's manager:

```
GET /api/v2/bots/legal/access
PUT /api/v2/bots/legal/access
{"see": {"everyone": true},
 "read": {"teams": ["legal"]},
 "write": {"everyone": true},
 "revision": 3}
```

`revision` is the one the GET returned; a stale one answers `409 version_conflict`. Each level takes
`everyone: true` or lists of `people` (roster ids), `teams` and `bots` (slugs); unknown ones answer `404`.
An unchanged save answers `409 unchanged`.

## Moving off `hub-access.yaml`

`private_owners` and `routing_permissions` in `registry/hub-access.yaml` no longer decide anything, and
neither does a bot's "Can use" list (`owner_ids`), which now only says who a bot works for and who is in
its shared room. The first start after upgrading resets every bot to **Open**. If either list was in the
file, the server logs one warning and the owner finds a note on Settings > Health, "hub-access.yaml
private/routing lists are no longer used; bots are now Open; set access in Settings > Bots". Set the
access you meant there; saving any bot's access, or dismissing the note, clears it.

## In SQL

`POST /api/v2/sql` is the one place a bot the caller may only see or write to does not appear: the
`bots`, `bot_status`, `schedules`, `bot_config`, `turns`, `jobs` and related tables hold the bots the caller can read,
and tasks follow the rule above ([Hub SQL](hub-sql.md)).
