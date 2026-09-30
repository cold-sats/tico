# What is broken? ("Tell me issues to solve", "status")

Triggered by a human asking what is wrong, what to fix, how things are, or why a bot is not working.
Budget 5 minutes. You answer with a short prioritised list and you have already fixed what you may.

## 1. Look

    hub health check

It lists, most urgent first, what is wrong with the bots this human may see, each with the one
command that fixes it: a bot with no computer, a computer that is offline, failing runs, a credential a bot
needs, setup that never finished, a bot paused or stopped. For "why isn't X live?" read X's lines, then
`hub bot status list` and `hub run list <bot> --since 24h` for the last thing it did.

## 2. Fix what you may, now

Do each fix as the human, with their rights. Do not ask first.

| Issue | You do |
| --- | --- |
| Not on a computer | `hub bot place <bot>` |
| Turned on but never finished setting up | `hub bot go-live <bot>` |
| Paused | `hub bot resume <bot>` (unless they paused it on purpose: then only mention it) |
| A credential a bot needs | open the card: `playbooks/connect-a-tool.md` |
| Failing runs | `playbooks/diagnose-a-failed-run.md`; fix instructions in the bot's repository if that is the cause |
| A computer is offline | nothing you can do: say which one, and that its bots wait for it |
| Stopped after refusing something | `hub api POST /api/v2/bots/<bot>/quarantine/clear` only after you read why |

A tool with too few verbs (a mail bot that cannot send, a read-only GitHub) is changed in place with
`hub tool update <tool-id> --bot <bot> --can ...`, never removed and added again.

A fix the server refuses for their rights is not a failure: name it in the list with who can do it.

## 3. Answer once

One message. First what you fixed ("Put Jira Manager on your computer and turned it on"), then what is
left, most important first, at most five lines, each a plain sentence and what to do. End with the
single most useful next step. If nothing is wrong, say that in one line and how many bots you checked.
No internal words: "Setting up", "your computer", "the Jira credential".
