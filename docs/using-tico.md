# Using Tico

Ten questions, short answers. Sign in at [hub.acme.example](https://hub.acme.example) with your Acme email.
How the pieces fit is in [How Tico works](how-it-works.md).

![Tasks in the demo company](images/tasks-desktop-light.png)

Every picture in these docs is a screenshot of [demo mode](demo.md), which you can run yourself.

**How do I give work to a bot or a person?**
On **Tasks**, press **New task** and pick who it is for — any person or bot. On a person's profile,
**Give a task**. On a bot, ask it in Chat. Or ask your own agent (Grok, Muse, Claude and others) to file
it through the hub's MCP. Each task shows who added it: you, another person, or a bot.

**How do I ask a bot a question?**
Open the bot's page and use its **Chat** tab; the reply comes back into the same conversation.
For anything across the company, ask your own agent: **Connect an agent** (the plug button beside
your email) gives it a token and the hub's MCP ([Connect an agent](connect-an-agent.md)).

**How do I know my bot ran?**
The conversation goes *Saved — queued* → *Starting* → *Working* → the reply. When the bot marks
a task done, the task shows under **Tasks → Done** with the bot's note.
Every run is under your email → **Runs**, and on the bot's **More** tab with its files and routines.

**What does *waiting* mean, and the other states?**
*Waiting*: the bot is parked on something — a bot, a child task, or an answer from you.
*Doing*: being worked on (*Doing · starting* until the runner picks it up). *Needs you*: a
person must act — a question, an approval, a blocked or declined item. *Done*: finished, awaiting close.

**My Mac is asleep. What happens?**
hub.acme.example keeps running: everything is saved and other people's bots keep answering. Bots on your
Mac show *offline* and new requests show *Saved — waiting for <your Mac>*; they run when it wakes.
A turn cut off mid-way is settled by the hub when that is safe (its task was already done, or it
had not used any tool yet) and otherwise opens in front of you as *needs you* the next time you
look at the app, with *Review now* on it. Nothing is silently re-sent. Your Mac being offline for
a few minutes is not something you are asked about; after ten minutes it is.

![Needs you: a decision and an approval waiting](images/needs-you-desktop-light.png)

**What needs my approval, and why?**
Sending outside the company, spending, publishing, credentials or unusual production changes, and
irreversible deletion: a bot files an approval with the exact action attached and it appears in
**Needs you** with **Approve** / **Decline**. A bot may improve and merge its own repository after
checks pass. Authorized maintainers may merge tested Tico changes without a separate approval.
Product and public documentation repositories keep their stated review rules. Full rules:
`policies/approvals.md`.

![The org chart with goals](images/org-chart-desktop-light.png)

**How do I rearrange the org chart?**
Drag a person or a bot in the sidebar onto the person or bot it should report to. The owner can
move anyone; everyone else can move what reports up to them, under themselves or their own
reports. The same rule decides whose profile, goals, bot settings and routines you may edit:
your own, and anyone's below you.

**How do I add a routine?**
**Tasks → Recurring → New routine** (or the Routines card on the bot's page): pick the bot, a
title, a cron (five fields, America/Los_Angeles by default) or a hub event, and the text the bot
is told each time. A bot can set up its own with `hub routine set`. Details: `docs/routines.md`.

**How do I change what a bot does?**
Edit `AGENT.md` in its `emp-<slug>` repository (playbooks and `knowledge/` for methods and facts),
commit and push; it is read at the start of the bot's next turn once the runner Mac's checkout has it.
Model, effort, computer, people and status are changed in **Settings → Bots**. One-off requests are tasks, not edits.

**Where do files go?**
Files you attach to a task or a chat are stored privately by hub.acme.example and the bot downloads them
for that conversation (up to ten files of 10 MB). A file a bot produces for you is attached to the
task the same way (`hub task attach`) and linked from its note; open it from the task or the link
while signed in. Other files a bot publishes are listed on its page under Files ([Files](files.md)); a bot's own
record stays in its repo's `reports/`. Meeting transcripts come from the tools that made them ([Meetings](meetings.md)).

**How do I review messaging bots?**
Choose an inbox or Slack channel under **Message bots** in the sidebar. The bot's instructions and
scheduled work are on the left, with example messages and actions to review on the right. Open an
email or Slack item for its thread. Email is a synced copy, with no per-person Google sign-in.
Ana can review all mailboxes; other people see only mailboxes granted by the roster. Slack
channel history is owner-only in this view.

**How do I add a person or a bot?**
A person needs the Cloudflare Access policy, `registry/hub-access.yaml` and the roster
(`registry/people.yaml`) to allow the address — ask Ana; there is no form yet. A bot: **Settings →
Bots → Add bot**, then create its repository from `templates/employee-repo/` on the Mac that will run it.
