# Inbox pass

Schedule: weekdays `0 7,12,16 * * 1-5` (routine `weekday-inbox-pass`) and weekends `0 9 * * 0,6`
(routine `weekend-inbox-pass`) in the company's timezone. Take the run's label from the task title.

Budget 20 minutes. The outcome is an empty untriaged list, or a short note of what still needs a
person. Quiet is a normal result. Nothing is sent.

---

## 1. Read the task

    hub task show <id>

Then `playbooks/inbox-preferences.md` and `memory/learnings.md`. The mailbox is the one named
`Mailbox:` in `AGENT.md`. You already hold it; do not pass `--mailbox` unless whoami shows more
than one.

## 2. Run the rules first

    $HUB_DIR/scripts/mail.sh rules run --all-mailboxes

Rules file marketing, notifications, and the mailbox's own list before a model reads anything.
`--all-mailboxes` walks the assigned mailbox plus everyone who reports to that person. What the
rules settle is done. Do not reopen it.

A dry run is only for a pass you are about to change. This pass applies the rules.

## 3. Read what is left

    $HUB_DIR/scripts/mail.sh inbox --untriaged --all-mailboxes --format brief

That is `in:inbox` minus every `hub/*` label. Brief is id, date, from, subject, labels and a
snippet. Open a body only for a thread you are about to draft or decide:

    $HUB_DIR/scripts/mail.sh thread <id> --format md

## 4. Sort what came back

| Outcome | What it is |
|---|---|
| File it | Noise, a notification, a receipt already settled, a copy another bot owns. Label and archive. |
| Draft a reply | A straightforward ask in this person's voice. Draft on the task; never send. |
| Needs the person | A deadline, money, legal risk, a commitment, or a question only they can answer. Label `hub/needs-owner`. Never archive it. |
| Another bot's work | A support ticket, a sales lead, a legal matter. Child task on that bot; do not label needs-owner. |

`hub/needs-owner` is scarce. Other teams' mail is not a need for this person.

## 5. Hand over what needs someone

    $HUB_DIR/scripts/mail.sh label add <msg-id> hub/needs-owner
    hub task create --owner <slug> --parent <id>

One child task per real item, never one to show the pass happened. The mailbox owner sees
needs-owner in Gmail and on this task's note. You never send the draft.

## 6. Finish the task

Prove the pass with another untriaged read. Then commit and
`hub task update <id> --status done --note`. With work: counts (rules filed, you triaged,
needs-owner ids with one line each). Without work: one line that the untriaged list was empty.
Always finish it. A scheduled task left open absorbs the next occurrence and quietly stops the
pass.

## When a mailbox fails

A refusal or a blocked mailbox is a blocked mailbox, not "nothing found". Name it on the task
and finish. Two consecutive failures of the same mailbox is one line on the owner's task, not a
repeated complaint in every note.
