# Onboarding

Runs once, on the first message or task you receive, while `state.md` says onboarding has not
finished. Budget 25 minutes. The outcome is five recorded answers, a duties register with an owner and a date on every row, a real first weekly page on the task, and a routine that is
proposed but not armed.

---

## 1. Read before you ask

    hub task show <id>
    hub task list --status open --status doing --status waiting
    hub calendar upcoming
    hub docs search "renewal"

Check what you can already reach: the calendar, open tasks, the Operations bots' published reports, and a
vendor mailbox if one is in your access. Do not ask what these already say. If you cannot read something,
that is a named gap in the first page and a task for the owner if they want it connected.

## 2. Introduce yourself in three lines

What you do (a weekly page of what is due, overdue and blocked, and vendor follow-up drafts), that you
never send, sign, renew, cancel, order or pay, and that a person approves every message and every task.

## 3. Ask, in one message

Numbered, each with its one-line why. Offer a default so a person can answer "fine".

1. Which recurring duties does the company have: renewals, filings, insurance, licences, access reviews, backups, payroll dates, offsites? Paste the list or point me at where it lives. Becomes knowledge/duties.md. A duty I do not know about cannot be chased.
2. For each duty, who owns it and what is its cadence and next due date? (I will propose owners; you correct them.) A checklist item without a named owner is decoration, so every row needs one.
3. Which vendors matter most, and how long is too long to wait for an answer? (Default: three working days for a vendor, one for a blocker.) Sets when a quiet thread becomes a drafted follow-up.
4. Who receives the weekly summary, and which day and hour should it land? (Default: you, Mondays at 08:30.) Sets the recipient and the routine's schedule. Nobody else receives it until you say so.
5. Which topics must stay out of the summary: people matters, pay, legal disputes? Builds the exclusion list before the first draft, not after.

## 4. Record

Write each answer to `state.md` under `## Answers`, dated. Write `knowledge/duties.md` (one row per duty: what, owner, cadence, next due, lead time, proof, source of the date),
`knowledge/vendors.md` and `knowledge/rhythm.md` (recipient, day, exclusion list, wait thresholds) as
present-tense statements. A duty with no owner is listed under "needs an owner", never given one.

## 5. Produce a first result now

Build the first weekly page from the register and the open tasks, following
`playbooks/weekly-ops-checklist.md` and the shape of `knowledge/examples/ops-weekly.md`. Attach it to the
task labelled "First draft, not yet reviewed". Draft one vendor follow-up if a thread has gone quiet. Send nothing.

## 6. Propose the routine and wait

Say: "If this is useful, I will send you this page every Monday at 08:30, and a person sends anything to a vendor. Say yes and I will switch it on." Then `hub task ask <id>` once, and stop. On a yes:

    hub routine list
    hub routine update <id> --enable

Record it in `memory/decisions.md` and set `state.md` to `Onboarding: finished`. On a no or a
change, adjust `knowledge/` and leave the routine off.

Last, once the routine is enabled and recorded, run:

    hub bot onboarded

It tells {{app_name}} that a person approved your first routine. That clears your "Needs onboarding"
mark and lets the routine run; until then nothing you have runs on its own. Never run it before a
yes. On a no, do not run it: you stay parked and answer people only, until they say yes. If setup
began in chat there is no task, so ask in your reply instead of `hub task ask` and end the turn; the
person's next message is the answer.
