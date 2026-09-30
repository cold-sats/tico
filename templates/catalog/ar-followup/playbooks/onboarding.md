# Onboarding

Runs once, on the first message or task you receive, while `state.md` says onboarding has not
finished. Budget 25 minutes. The outcome is six recorded answers, a real pack of reminder drafts from
the aging list, and a routine that is proposed but not armed.

---

## 1. Read before you ask

    hub task show <id>

Check what you can already reach: an aging export attached to the task, a docs folder, the sender's
mailbox. Do not ask for what these already show. If you cannot see open invoices, that is answer
one, and a task for the owner if they want a source connected. Never work around it.

## 2. Introduce yourself in three lines

What you do (a weekly aging summary and a draft reminder for each overdue invoice), that you never
send, never change a record and never state a fee or term you were not given, and that a person
sends every reminder.

## 3. Ask, in one message

Numbered, each with its one-line why. Offer a default so a person can answer "fine".

1. Where do I get the list of open invoices? Can you attach the current one?
2. What are your usual payment terms, and what may a reminder say about them?
3. How firm should each step be: before due, 1 to 7 days late, 15, 30, 45 and beyond?
4. Which customers or invoices must I never chase, and above what amount does a person write instead?
5. Who sends reminders and from which address? Ask for two they were happy with.
6. Which day and hour should the weekly pack land, and for whom? (Default: you, Mondays at 09:00.)

## 4. Record

Write each answer to `state.md` under `## Answers`, dated. Write `knowledge/ladder.md`,
`knowledge/voice.md` and `knowledge/customers.md` as present-tense rules; start `knowledge/customers.md`
with the disputes and do-not-chase names given. Never write a bank or card number.

## 5. Draft the first pack now

Follow `playbooks/weekly-receivables-reminders.md` on the aging list, at most five drafts, in the shape of
`knowledge/examples/ar-pack.md`, labelled "First draft, not yet reviewed". Attach it to the task. Nothing
is sent.

## 6. Propose the routine and wait

Say: "If this is useful, I will draft this pack every Monday at 09:00, and a person sends any reminder.
Say yes and I will switch it on." Then `hub task ask <id>` once, and stop. On a yes:

    hub routine list
    hub routine update <id> --enable

Record it in `memory/decisions.md` and set `state.md` to `Onboarding: finished`. On a no or a change,
adjust `knowledge/` and leave the routine off.

Last, once the routine is enabled and recorded, run:

    hub bot setup-done

It tells {{app_name}} that a person approved your first routine. That clears your "Needs onboarding"
mark and lets the routine run; until then nothing you have runs on its own. Never run it before a
yes. On a no, do not run it: you stay parked and answer people only, until they say yes. If setup
began in chat there is no task, so ask in your reply instead of `hub task ask` and end the turn; the
person's next message is the answer.
