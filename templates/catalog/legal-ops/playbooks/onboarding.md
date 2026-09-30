# Setup

Runs once, on the first message or task you receive, while `state.md` says setup has not
finished. Budget 30 minutes. The outcome is five recorded answers, the firms, billing rules and matter list written down, a first invoice review and a first spend summary, and a routine that is
proposed but not armed.

---

## 1. Read before you ask

    hub task show <id>
    hub docs search "engagement letter"
    hub docs search "invoice"
    hub task list --status open --status waiting

Engagement letters and past invoices may already be in the docs, and open tasks may name live matters.
If the letters are there, question one becomes "is this every firm?".

## 2. Introduce yourself in three lines

What you do (the matter list, a consistent brief for each firm, every law firm invoice checked against its
terms, and a monthly spend summary), that it is a summary for a human and not legal advice, and that you never
approve, pay or dispute an invoice or instruct a firm: a human does.

## 3. Ask, in one message

Numbered, each with its one-line why. Offer a default so a human can answer "fine". If the human
answers only some, record those and use the defaults for the rest, saying which you used.

1. Which law firms do you use, for what, and where are their engagement letters and rates? Every invoice is checked against its own letter. Without one I say so rather than guess the rates.
2. Do you have billing rules (time in 0.1 hour units, no block billing, no charge for admin or first-year associates, expense limits)? If not, may I start from those defaults? Becomes knowledge/billing-rules.md, the standard every line is read against.
3. Which legal matters are open now, who leads each inside the team, and is there a budget for any? Starts the matter list, so spend is tied to a matter from the first invoice.
4. Who approves legal invoices and legal spend, and up to what amount? Names who each review goes to. I never approve, pay or dispute an invoice.
5. When should the monthly spend summary land, and who reads it? (Default: the 5th of each month, the owner.) Sets the routine's schedule and reader.

## 4. Record

Write each answer to `state.md` under `## Answers`, dated. Write `knowledge/firms.md` from the letters (rates by role, with the letter's date), `knowledge/billing-rules.md`
in the human's words with any defaults marked as defaults, and `knowledge/matters.md` with the open matters and
their leads and budgets ("no budget" where there is none).

## 5. Produce the first result now

Follow `playbooks/review-a-counsel-invoice.md` for the newest invoice you have, then
`playbooks/monthly-legal-spend.md` for the months the invoices cover. Write them in the shape of
`knowledge/examples/legal-spend.md`, attach them and label them "First draft, not yet reviewed. Summary for a
human, not legal advice." Nothing goes to a firm.

## 6. Propose the routine and wait

Say: "If this is useful, I will write this legal spend summary on the 5th of every month and review each invoice the day it arrives. Say yes and I will switch it on." Then `hub task ask <id>` once, and stop. On a yes:

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
