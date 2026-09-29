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

Who may edit a bot's access: the owner, a bot administrator for the bots run under their own name, and
the people the bot reports up to on the org chart (the same people who may change the bot's other
settings). The Assistant, BotOps and the librarians can have their access edited too.

## Always full access

Whatever the audiences say, these callers can see, read and write to a bot:

- the company **owner**;
- the **bot itself**, for its own data;
- the people **above the bot on the org chart** (whoever it reports up to), and a bot above it in the
  `reports_to` chain when the caller is a bot;
- a **bot administrator**, for bots whose operator is their own account. This is the same rule that lets
  them change the bot's settings, so being able to edit who has access and having access always go together.

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
