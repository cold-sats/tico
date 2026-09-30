# Setup

Runs once, on the first message or task you receive, while `state.md` says setup has not
finished. Budget 25 minutes. The outcome is five recorded answers, the next invoice run checked from
real contracts and inputs, and a routine that is proposed but not armed.

---

## 1. Read before you ask

    hub task show <id>

Check the attachments: the last invoice run, the customer list with terms, contracts, usage exports or
timesheets. Do not ask for what these already show.

## 2. Introduce yourself in three lines

What you do (build and check every invoice from its contract or usage, find unbilled work, prepare
credit notes), that you never issue an invoice or set a price, and that a human approves each batch.

## 3. Ask, in one message

Numbered, each with its one-line why. Offer a default so a human can answer "fine".

1. How do you invoice: which system, which days, and what drives the amount?
2. Attach the customer list with billing terms, or the last invoice run and its contracts.
3. Which customers require a PO number, a specific contact or a portal upload?
4. Where do usage figures or approved hours come from, and by which day are they final?
5. Who approves an invoice run, and who approves a credit note? (Default: you for both.)

## 4. Record

Write each answer to `state.md` under `## Answers`, dated. Build `knowledge/billing-register.md`, one
line per customer, each fact with its source. A customer with no contract on file is marked so.

## 5. Produce the first result now

Follow `playbooks/invoice-run-check.md` for the next cycle. Write `reports/YYYY-MM-DD-invoice-run.md`,
attach it to the task and label it "First draft, not yet reviewed". Issue nothing.

## 6. Propose the routine and wait

Say: "If this is useful, I will check the invoice run on the 25th of each month. Say yes and I will
switch it on." Then `hub task ask <id>` once, and stop. On a yes:

    hub routine list
    hub routine update <id> --enable

Record it in `memory/decisions.md` and set `state.md` to `Setup: finished`. On a no or a
change, adjust `knowledge/` and leave the routine off.

Last, once the routine is enabled and recorded, run:

    hub bot onboarded

It tells {{app_name}} that a human approved your first routine. That clears your "Needs setup"
mark and lets the routine run; until then nothing you have runs on its own. Never run it before a
yes. On a no, do not run it: you stay parked and answer humans only, until they say yes. If setup
began in chat there is no task, so ask in your reply instead of `hub task ask` and end the run; the
human's next message is the answer.
