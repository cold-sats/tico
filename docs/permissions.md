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
| **Admin** | people the owner makes admins (the old "bot administrators": the list is read under either name for one release) | manage every bot but the built-in ones (below), people and computers (enrol, revoke, open to members' bots); set what members may do and the bot limit. They cannot make or remove admins or owners, and they are not credential administrators |
| **Member** | everyone else | create and manage their own bots, add coworkers, and use the bots they are allowed to |

Settings > People (owners and admins) shows each person on one row: their role (the owner switches Admin and Member there), a
**Can sign in** switch, and a ⋯ menu with two capabilities per member:

- **Can add bots** (`create_bots`): on for everyone unless switched off.
- **Can add people** (`add_people`): on by default for coworkers, that is people whose email is in the company domain. A
  member with it on may add a person whose email is in the company domain. Adding anyone outside it needs an owner or an admin,
  whatever the capability says.

The **company domain** is the domain(s) the owner allows to sign in (Settings > People, **Anyone at <domain> can sign in**); when
none is set it is the owner's own email domain, unless that is a public mail service such as gmail.com, in which case there is none
and members add nobody until the owner sets one. A newly added person goes on the roster and on the sign-in list, so they can
actually sign in.

**Can sign in** off keeps a person on the roster and the org chart but refuses their sign-in, sessions and API tokens until it is
on again. Owners and admins switch it for members; only the owner switches it for an admin; nobody switches it for themselves or
for the owner.

**Credential administrators** are the owner and whoever `TICO_CREDENTIAL_ADMINS` names, nobody else: being an Admin does not
let someone write shared credentials, whatever an earlier version did. Add a person to that list to give them the vault.

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

- **Off** for every computer that existed before this release and for every new one, whoever enrols it: only an owner or an admin
  turns it on. A computer a member enrols is theirs, and hosts their own bots because they are its operator; it is not open to other
  members' bots.
- A bot created by a member can only be placed on **its own operator's computer, or a computer an admin has opened to members' bots**.
  Otherwise it stays planned, and the answer says to ask an admin to place it or to open a computer. Admins may place a member's
  bot on any computer. Placing a member's bot never hands it to the computer's operator: it stays theirs.
- Setup that places bots for you (a computer enrolling, the wizard) leaves a member's bot alone unless the computer is its operator's
  or open to members' bots.
- Settings > Health warns when bots members created run on a computer whose `secrets/_shared.env` holds keys, since the bot
  instructions could ask a run for them. Give members a computer with no shared keys and open only that one.

A computer still hosts its operator's bots and the owner's; opening it to members' bots adds members' bots, it does not move anyone else's.

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
| `hub bot onboarded [slug]` | a starter bot's own call, once a person approved its first routine: it stops being `needs_onboarding` (its manager may call it for it) |
| `hub people add <email> [--name] [--title] [--reports-to]`, `hub people list` | the roster |

Everyday edits to a bot the person owns happen at once, and each is undoable from Settings > Bots history.

### What always needs their click

These are proposed instead: the command answers `needs_confirm: true` and a **Confirm card** appears in the person's chat with BotOps
(the same card the Assistant uses: "Runs as you, only when you confirm"). Nothing changes until they click, and only they can:
BotOps, the owner and the admins cannot confirm for them.

- adding a person (any), including anyone outside the company domain (owners and admins only);
- making someone an Admin, granting `add_people`, changing roles, or changing a person's email (it decides who is an Admin) or team
  (it is an access audience);
- giving a bot a stored credential (a tool registration that uses a shared credential or another bot's);
- placing a member's bot on a computer that is neither its operator's nor open to members' bots (admins only).

The card shows every field the request carries, and its description, written by the server and never by the bot, names each field it
changes and, for a placement, the computer and whether it takes members' bots.

BotOps reports "there is a card waiting in this chat" instead of asking the person to go to Settings.

### Why it is built this way

A bot's instructions and everything it reads (mail, web pages, documents, a colleague's task) can try to steer it. If BotOps could
act with the company's full authority, or for whoever a piece of text names, one injected sentence would be a privilege escalation.
So it borrows one person's rights at a time, only from the message that person typed to it in chat, never more than they have, and
the few changes that widen who can get in or what a bot can hold need that person's own click. For the same reason a member's bot goes
only on computers set aside for members' bots: bots on one computer are not isolated from each other.

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
