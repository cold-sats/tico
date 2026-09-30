# Setup guide: your first bots

A practical guide to getting real work out of your first bots. The screens themselves are in [Finish setup](onboarding.md); what each of
the 94 templates does is in [Starter bots](starter-bots.md). BotOps and the Librarian can answer questions from this page.

## Pick your first bots

Start from what your team does, not from what a bot could do.

1. **Say what you do** in "About the team": what the team does, who it sells to, whether software is its product and how big it is.
   There is no list of pains to tick and no list of tools.
2. **Build your team chart.** Pick the groups you want, then answer one short question for each ("What kind of sales do you do
   today?"). Tico recruits bots for that group: its head is checked, the usual ones are checked or shown, and the rest are under
   **More**. Check what you want and watch the chart grow. Skip a group you do not need; Product and Engineering are suggested only
   if software is your product. A big chart is safe: a bot you have not set up yet is parked, does nothing on its own and costs nothing.
   The suggestions come from Tico HQ while the toggle on the card is on (it sends that one answer, and nothing is kept:
   [PRIVACY.md](../PRIVACY.md)), otherwise from Tico itself.
3. **Edit before you create.** On the finished chart, click a bot to rename it, choose who it reports to (each group's bots report
   to its head, and the heads to you), or remove it. To have one human's mail sorted and replies drafted, switch on the message bot
   under **Built-in** and choose whose mailbox it reads. Nothing exists until **Create my team**.
4. **Connect tools when a bot asks.** Finish setup does not ask which tools you use and no bot is held back for a missing one. When you press
   **Set up** on a bot, it tells you what it needs (a mailbox, tickets, a repository, a CRM) and where to connect it.

There is no limit on how many bots to create, but set them up one at a time, in the order they are listed.

## Set one up, together

A new starter shows **Needs setup**. Press **Set up** on its page (or just say hello): it introduces itself, asks a handful of
questions in one message, and writes a real first draft from your own data so you have something to react to. Starting the setup switches
its first routine on; ask it to change or turn off the routine and it does, and it marks itself set up once its setup is done.

- Answer briefly and concretely. "Fine, the default" is a valid answer; so is pasting two examples of something done well.
- Name the human who approves its drafts, and who covers when they are away. A draft with no owner waits.
- **Never type a password, API key or token into a chat with a bot.** Connect tools in Tico's own fields (Tools, or
  Credentials). A credential pasted into a chat is treated as leaked: rotate it.

## Write good instructions

Whether it is a first message, a task or a change to what a bot does:

- **Say the outcome, then the reason.** "A digest of new tickets by 9:00, so I can reply before standup", not "look at support".
- **Say what done looks like** and what it must not touch. One line on the format is worth a paragraph of hope.
- **Point at the source.** The mailbox, the folder, the doc, the meeting series. If it is not in Tico, say where it is.
- **Give an example of good.** Two real replies, a past report you liked. Never a customer's private details.
- **Name the limits.** Who may be contacted, which topics are off limits (pay, legal, HR matters), what needs your approval.
- **One request at a time.** Ask for a second thing after the first is right.

If a bot gets it wrong twice, change its instructions, not your message: ask BotOps to tailor it, or edit its `AGENT.md` and playbooks.

## Approval gates

Every starter drafts and a human confirms anything that would send, post, pay, change a record or delete. Some of that is the platform,
not the prompt: a mail send becomes a draft until it is approved, a Slack post needs the channel to allow posting, a bot may invite only
humans on the roster to a calendar event, and the QA Engineer cannot comment or label on GitHub unless you turn that on. The list per template
is in [Starter bots](starter-bots.md#what-stops-a-starter-sending-things-outside-the-team).

When a bot asks for approval it shows the exact action. Read it as if you were sending it yourself. An approval is spent once: it covers
that action and nothing else. Loosen a gate only after a bot has been right for a few weeks, and do it in the bot's access, not in a
message.

## What good looks like

Five checks you can apply to any bot's output in ten minutes (the full version, with a worked example, is in
[Starter bots](starter-bots.md#what-a-good-bot-looks-like)):

1. **Answer first.** The first line is the result, not the process.
2. **Short and scannable.** One page, one line per item, decided in two minutes.
3. **Cited.** Every claim names its record and date.
4. **Honest about gaps.** What it could not read is named; a missing fact is a marked gap, never an invented one.
5. **Gated.** Nothing leaves the team or changes a record without a Confirm, and the draft is ready to approve with one edit.

Your first approved output is the milestone that matters: the checklist counts it, not how many bots exist.

## Review a bot's first week

Set aside fifteen minutes at the end of the week for each bot you set up.

- **Read what it produced.** Open its reports and updates. Which lines did you act on? Which did you skip? Skipped lines are the ones to
  cut or to say less about.
- **Check the sources.** Pick three claims and follow them to their records. A claim that does not check out is a bug in the playbook.
- **Look at the gaps it named.** Repeated "could not read X" means a tool to connect or access to grant.
- **Look at what it asked you.** Questions it asked twice belong in its knowledge (`knowledge/`), not in Needs you.
- **Look at the cost of attention.** If reviewing takes longer than doing the work, it is too chatty or too broad: narrow its instructions.
- **Decide.** Keep it, tighten it (edit its instructions or ask BotOps), give it one more responsibility, or pause it. Then set up the
  next bot.

A routine that has not earned your trust stays off. Turn a second routine on only after the first has been useful for a week.
