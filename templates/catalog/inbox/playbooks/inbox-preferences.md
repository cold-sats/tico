# Inbox preferences

Standing preferences for the mailbox this bot is assigned. A run that learns a preference that should
hold next month writes it here, one bullet, present tense, no dates. The dated note goes in
`memory/decisions.md`.

## Filing
Off. Change to `labels` only after the human says "file for me", and to `labels and archive` only after
they have read a week of what you would have archived. Every change is logged in `memory/decisions.md`.

## Sending
Off. Until the human turns it on, every reply or forward is a draft on the task for their approval. When they
ask BotOps to turn it on, BotOps changes `Off` to `On`, sets `outbound_send: true` and `forward_to:` in
`bot.yaml`, and writes their rules here, one bullet each, in their words. With it On you follow those rules with no
approval for each message, to the team's own domain, the sender of the message you are answering, and the
`forward_to:` addresses only. Anyone else is a draft and an approval request.

## Always reaches the human
None yet. Setup fills this: people, topics and senders that are flagged first and never filed.

## Fine to file
None yet. Setup fills this: senders and kinds of mail that can be filed without asking.

## Never commit the human to
Money, a meeting time, a contract, an introduction, until they say otherwise here.

## Routed to someone else
None yet. Setup fills this: kinds of mail that belong to another bot or human, and who.
