# Using Tico

Short answers to common questions. Sign in at your team's Tico address with the email on its Humans roster. Ask your owner for the address.
How the pieces fit is in [How Tico works](how-it-works.md). Words are defined in the [Glossary](glossary.md).

![Tasks in the demo team](images/tasks-desktop-light.png)

Every picture in these docs is a screenshot of [demo mode](demo.md), which you can run yourself.

**How do I give work to a bot or a human?**
On **Tasks**, press **New task** and pick who it is for — any human or bot. On a human's profile,
**Give a task**. On a bot, ask it in Chat. Or ask your own external agent (Grok, Muse, Claude and others) to file
it through Tico's MCP. Each task shows who added it: you, another human, or a bot.

**How do I ask a bot a question?**
Open the bot's page and use its **Chat** tab; the reply comes back into the same conversation.
For anything across the team, ask your own external agent: **Connect an external agent** (the plug button beside
your email) gives it a token and Tico's MCP ([Connect an external agent](connect-an-agent.md)).

**How do I know my bot ran?**
The conversation goes *Saved — queued* → *Starting* → *Working* → the reply. When the bot marks
a task done, the task shows under **Tasks → Done** with the bot's note.
Every run is under your email → **Runs**, and on the bot's **More** tab with its files and routines.

**What does *waiting* mean, and the other states?**
*Waiting*: the bot is parked on something — a bot, a child task, or an answer from you.
*Doing*: being worked on (*Doing · starting* until a computer picks it up). *Needs you*, or *Needs <Name>* for someone else: a
human must act — a question, an approval, a blocked or declined item. The all-owners list groups these as **Needs a human**.
A comment on a task answers that task's question, so the bot can ask its next question; it does not answer a different
task in the same room. *Done*: finished, awaiting close.

**Marked a task Done by mistake?**
Choose **Undo** in the toast, or open the finished task under **Done** and choose **Reopen**.
A task you requested for yourself closes when you mark it Done; Reopen works for it too.
The earlier completion stays in its history, while Goals and KPIs count it as active again.

A bot's final answer to a reply appears under that update automatically. An acknowledgement such as
"Thanks" needs only a short answer; it does not need a new task. `hub_update_reply` is for humans.

**My Mac is asleep. What happens?**
Your team's Tico server keeps running: everything is saved and other humans' bots keep answering. Bots on your
Mac show *offline* and new requests show *Saved — waiting for <your Mac>*; they run when it wakes.
A run cut off mid-way is settled by Tico when that is safe (its task was already done, or it
had not used any tool yet) and otherwise opens in front of you as *needs you* the next time you
look at the app, with *Review now* on it. Nothing is silently re-sent. Your Mac being offline for
a few minutes is not something you are asked about; after ten minutes it is.

![Needs you: a decision and an approval waiting](images/needs-you-desktop-light.png)

**What needs my approval, and why?**
Sending outside the team, spending, publishing, credentials or unusual production changes, and
irreversible deletion: a bot files an approval with the exact action attached and it appears in
**Needs you** with **Approve** / **Decline**. A bot may improve and merge its own repository after
checks pass. Authorized maintainers may merge tested Tico changes without a separate approval.
BotOps handles requested bot and repository deletion, adding humans outside the domain (for owners and admins), and Tico updates
directly with your rights. Its outbound sending switch still needs you to turn it on. Product and public documentation repositories
keep their stated review rules. Full rules:
`policies/approvals.md`.

![The team chart with goals](images/org-chart-desktop-light.png)

**How do I rearrange the team chart?**
Drag a human or a bot in the sidebar onto the human or bot it should report to. The owner can
move anyone; everyone else can move what reports up to them, under themselves or their own
reports. The same rule decides whose profile, goals, bot settings and routines you may edit:
your own, and anyone's below you.

**How do I add a routine?**
**Settings → Routines → New routine** (or the Routines card on the bot's page): pick the bot, a
title, a cron (five fields, America/Los_Angeles by default) or a Tico event, and the text the bot
is told each time. A bot can set up its own with `hub routine set`. Details: `docs/routines.md`.

**How do I change what a bot does?**
Edit `AGENT.md` in its `bot-<slug>` repository (playbooks and `knowledge/` for methods and facts),
commit and push; it is read at the start of the bot's next run once the Mac's checkout has it.
Model, effort, computer, owners and status are changed in **Settings → Bots**. One-off requests are tasks, not edits.

**Where do files go?**
Files you attach to a task or a chat are stored privately by your team's Tico server and the bot downloads them
for that conversation (up to ten files of 10 MB). A file a bot produces for you is attached to the
task the same way (`hub task attach`) and linked from its note; open it from the task or the link
while signed in. Other files a bot publishes are listed on its page under Files ([Files](files.md)); a bot's own
record stays in its repo's `reports/`. Meeting transcripts come from the tools that made them ([Meetings](meetings.md)).

**How do I review message bots?**
Choose a mailbox or Slack channel under **Message bots** in the sidebar. The bot's instructions and
routines are on the left, with example messages and actions to review on the right. Open an
email or Slack item for its thread. Email is a synced copy, with no per-human Google sign-in.
Ana can review all mailboxes; other humans see only mailboxes granted by the roster. Slack
channel history is owner-only in this view.

**How do I add a human or a bot?**
A human: **Settings → Humans → Add manually** (an owner or admin), or sync them from the team's
directory there; behind Cloudflare Access, also allow the address in its policy ([Humans](people.md)). A
bot: **Settings > Bots > Add from template**, or ask BotOps to build it. Open the bot and press **Set up** to finish its
first conversation. See [Creating bots](creating-bots.md) for custom Instructions and manual setup.
