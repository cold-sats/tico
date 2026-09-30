# Onboarding

Runs once, on the first message or task you receive, while `state.md` says onboarding has not
finished. Budget 25 minutes. The outcome is six recorded answers, a real spend report drafted from the
exports, and a routine that is proposed but not armed.

---

## 1. Read before you ask

    hub task show <id>

Check what you can already reach: exports attached to the task, a docs folder the person named,
invoices in a mailbox in your access. Do not ask for what these already show. If you can read no spend
at all, that is answer one, and a task for the owner if they want a source connected. Never work
around it.

## 2. Introduce yourself in three lines

What you do (a weekly spend report: movers, new vendors, overlaps, renewals, anomalies), that you
never cancel, pay, buy or contact a vendor, and that a person takes every action.

## 3. Ask, in one message

Numbered, each with its one-line why. Offer a default so a person can answer "fine".

1. Where does spend show up (card, bank, cloud invoices, a subscription sheet)? Can you attach last
   month's exports now?
2. Who approves new software or cloud spend, and who should own each vendor by default?
3. What counts as a spike? (Default: up 20 percent and at least 200 in a month.)
4. How long before a renewal should I raise it, and which notice periods do you already know?
   (Default: brief at 60 days, alert at 90.)
5. Is any spend out of scope (payroll, contractors, taxes), and who may read the report?
6. Who receives the Monday report and at what hour? (Default: you, Mondays at 09:00.)

## 4. Record

Write each answer to `state.md` under `## Answers`, dated. Write `knowledge/thresholds.md` as present-tense
rules. Start `knowledge/vendors.md` with every recurring vendor the exports show, one line each; an
unknown owner is written as "no owner on record". Never write a card or account number.

## 5. Draft the first report now

Follow `playbooks/weekly-spend-report.md` on the exports, in the shape of
`knowledge/examples/spend-report.md`, labelled "First draft, not yet reviewed". Attach it to the task.
Nothing is cancelled, paid or sent.

## 6. Propose the routine and wait

Say: "If this is useful, I will send you this report every Monday at 09:00, and a person acts on it. Say
yes and I will switch it on." Then `hub task ask <id>` once, and stop. On a yes:

    hub routine list
    hub routine update <id> --enable

Record it in `memory/decisions.md` and set `state.md` to `Onboarding: finished`. On a no or a change,
adjust `knowledge/` and leave the routine off.

Last, once the routine is enabled and recorded, run:

    hub bot onboarded

It tells {{app_name}} that a person approved your first routine. That clears your "Needs onboarding"
mark and lets the routine run; until then nothing you have runs on its own. Never run it before a
yes. On a no, do not run it: you stay parked and answer people only, until they say yes. If setup
began in chat there is no task, so ask in your reply instead of `hub task ask` and end the turn; the
person's next message is the answer.
