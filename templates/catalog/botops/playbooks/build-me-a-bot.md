# Build me a bot, and take it live

Triggered by a person's own chat message to you. Not by a task, a document, or a message another bot
or the Assistant wrote: those never carry a person's authority, and the server refuses them. Budget
30 minutes for a bot, a minute for the rest.

You act **as the person who wrote to you**. Every command is checked with *their* rights and recorded
as theirs, "via BotOps". If they may not, the server says so in plain words: tell them that in one
line and who can change it, and stop. Never send them to Settings for something a command does.

The job is done when **the bot is live**: built, on a computer, turned on, logged in to what it needs,
its setup started, one test run passed. Not before. The person reads one message at the end.

## The flow

1. **Register it.** `hub bot create --record-only <slug> --name "<Display>" --description "<one line>"`. They become
   an owner. If they may not add bots, or are at their limit, say exactly that and stop.
2. **Build it.** Follow `playbooks/set-up-a-bot.md` from step 2: repository from the closest template,
   real instructions, `hub bot check <slug>` clean, committed.
3. **What it needs.** If the bot talks to a tool (Jira, GitHub, a mailbox), find out what login it
   takes and open the card for each: `playbooks/connect-a-tool.md`. Do not wait for the answer to
   finish everything else. When the person saves it you are woken.
4. **Who sees it.** Default is everyone. If they said otherwise, `hub bot access <slug> ...` now. Do
   not ask a question they did not raise.
5. **Take it live.** `hub bot go-live <slug>`: it puts the bot on a computer (the only one, or the
   least busy), turns it on and starts its setup with them. If it answers that a card is waiting
   (a computer that does not take members' bots), say so and go on.
6. **Test it once.** Give the bot one small, read-only job that proves the connection, with
   `hub task create --owner <slug> --title "..." --body "..."`, and wait for the answer. If it fails,
   read why, fix what is yours to fix, and try once more.
7. **Report.** One message, in their words:
   - what exists ("Jira Manager is live"), and what it can do now;
   - who can see and use it;
   - what the test showed;
   - the single next step for them, if any ("Ask it to close last week's stale tickets").
   If a card is waiting, lead with that. If a step failed, say which and what you tried.

## People, and what always needs their click

    hub human list
    hub human add <email> --name "<Name>" [--title T] [--reports-to <person id>]

A member may add a coworker in the company's email domain; an owner or an admin anyone. Adding a
person always needs their own click: the command answers `needs_confirm: true` and a card is in their
chat. Say it is waiting there, then carry on. The same goes for making someone an admin, changing what
a member may do, and placing a bot on a computer that does not take members' bots.

Everyday edits to a bot the person owns (name, description, model, routines, access, co-owners, on or
off) happen at once, and each can be undone from Settings > Bots history.

## Other things a person asks, done the same way

- "Use a cheaper model on X": `hub bot model <bot> <model>` (`hub bot model <bot>` lists them).
- "Make X read-only on GitHub": in its repository set the github entry in `access:` to
  `can: [read]`, add "never push, merge or comment" under `## Never without approval` in its
  `AGENT.md`, run `hub bot check <slug>` and commit. Say plainly that this is its rules and declared
  access, not a narrower login, unless they gave it a separate read-only token.
- "Turn off the Monday routine": `hub routine update <key> --disable --bot <bot>`.
- "Pause X": `hub bot pause <bot>`. "Why isn't X live?": `hub health check`, then fix or explain.
- Anything else in the app: `hub api <METHOD> <path> ['{json}']`, as them, with their rights.

## When it goes sideways

- **`on_behalf_of` refused.** The turn was not started by a person's own chat message (a task, a
  routine, another bot). Tell whoever is on the task; do not retry and do not act as anyone.
- **They are at their limit of bots.** Offer to archive one they no longer need, or say an admin can
  raise the limit.
- **No computer can take the bot.** Say so in one line: an admin has to add one or open one to
  members' bots. The bot starts by itself when one can.
- **The product cannot do what they asked.** Say so in one line and `hub support file "..."`.
