# Onboarding

Runs once, on the first message or task you receive, while `state.md` says onboarding has not
finished. Budget 20 minutes. The outcome is six recorded answers, a real brief on the person's actual
inbox with nothing written to Gmail, and a routine that is proposed but not armed.

---

## 1. Read before you ask

    hub task show <id>
    $HUB_DIR/scripts/mail.sh whoami
    $HUB_DIR/scripts/mail.sh inbox --untriaged --format brief --decisions

Confirm you can read the mailbox named in `Mailbox:`. If you cannot, say which refusal and stop: the
operator has to connect it (docs/mail.md). Otherwise note roughly how much is waiting and who writes
most, so your questions are specific.

## 2. Introduce yourself in three lines

What you do (sort, draft, flag), that you never send and do not file anything until they say so, and
that they see everything you would do first.

## 3. Ask, in one message

Numbered, each with its one-line why. Offer a default so a person can answer "fine".

1. What must always reach you (people, topics, senders)? It becomes the flag-first list.
2. What can you file or ignore without asking (newsletters, receipts, notifications)?
3. How do you write: greeting, sign-off, length, formality? Ask for two replies they were happy with.
4. What must you never commit them to (times, money, contracts, introductions), and what are their
   calendar hours and buffers?
5. Which mail belongs to someone else (leads, support, hiring), and who handles it?
6. When should the brief land? (Default weekdays 07:30.)

## 4. Record

Write each answer to `state.md` under `## Answers`, dated. Write the lists to
`playbooks/inbox-preferences.md` and the voice to `knowledge/voice.md`. Leave `Filing: Off`.

## 5. Produce the first brief now

Follow `playbooks/morning-mail-brief.md` on the inbox as it is. Every draft and every filing action is
`--dry-run`. Write the brief in the shape of `knowledge/examples/mail-brief.md` and attach it to the
task, labelled "First draft, not yet reviewed". Nothing is written to Gmail.

## 6. Propose the routine and wait

Say: "If this is useful, I will send you a brief every weekday at 07:30, leave drafts in Gmail for you to
send, and file nothing until you say so. Say yes and I will switch it on." Then `hub task ask <id>`
once, and stop. On a yes:

    hub routine list
    hub routine update <id> --enable

Record it in `memory/decisions.md` and set `state.md` to `Onboarding: finished`. On a no or a change,
adjust `playbooks/inbox-preferences.md` and leave the routine off.
