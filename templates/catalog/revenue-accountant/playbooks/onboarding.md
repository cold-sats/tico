# Onboarding

Runs once, on the first message or task you receive, while `state.md` says onboarding has not
finished. Budget 30 minutes. The outcome is five recorded answers, a revenue close pack for the last
closed month, and a routine that is proposed but not armed.

---

## 1. Read before you ask

    hub task show <id>

Check the attachments: billing export, ledger export, the deferred revenue schedule, contracts, a
revenue policy memo. Do not ask for what these already show.

## 2. Introduce yourself in three lines

What you do (reconcile billing to the books, roll deferred revenue, note how each contract is
recognised, bridge recurring revenue), that you never post or change billing, and that the accountant
decides anything the written policy does not cover.

## 3. Ask, in one message

Numbered, each with its one-line why. Offer a default so a person can answer "fine".

1. What do you bill, from which billing system? Attach last month's invoice and payment export.
2. Is there a written revenue recognition policy? Attach it, or say how each kind is recognised today.
3. Attach the current deferred revenue schedule and last month's ledger export.
4. How do you define MRR or ARR, and do you count at signing or at invoice?
5. By which working day of the close do you need the pack, and who posts the entries? (Default: day 2.)

## 4. Record

Write each answer to `state.md` under `## Answers`, dated. Write `knowledge/revenue-policy.md` by
revenue kind with its source, and `knowledge/deferred-schedule.md` from the schedule attached (or
rebuilt from invoices and contract dates, marked "rebuilt, to confirm").

## 5. Produce the first result now

Follow `playbooks/monthly-revenue-close.md` for the last closed month. Write
`reports/YYYY-MM-revenue-close.md`, attach it to the task and label it "First draft, not yet reviewed".

## 6. Propose the routine and wait

Say: "If this is useful, I will prepare the revenue close pack on the 2nd of each month. Say yes and I
will switch it on." Then `hub task ask <id>` once, and stop. On a yes:

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
