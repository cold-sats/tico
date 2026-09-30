# Weekly renewal and expansion review

Schedule: Tuesdays at 09:00 company time (routine `weekly-account-review`), once a person has approved the
first review. Also run by hand. Budget 40 minutes. The outcome is one page: every renewal in the next 120
days at its stage, the packs ready or waiting, and expansion with evidence. Nothing is sent or changed.

---

## 1. Read where things stand

    hub task show <id>

Then `knowledge/renewal-rules.md`, `knowledge/renewals.md` and last week's review. Check each action it
proposed: done, slipped or dropped.

## 2. Refresh the calendar

Read renewal dates, notice periods and values from the contract or a CRM read; note the source and date.
Place each renewal in its stage: **120 days** (account plan refreshed, usage against contract checked),
**90 days** (business review held or booked with the Customer Success Manager, options shaped), **60 days**
(renewal pack with a person for pricing), **30 days** (order form out for signature). A renewal behind its
stage is flagged with the step it missed.

## 3. Check health before terms

For each renewal in the next 90 days, read the Customer Success Manager's status. A red account gets no
commercial proposal this week; list it under "Held for health" with their note.

## 4. Find expansion

Compare usage with the contract: seats, locations, modules, usage tiers. Read recent calls for goals the
customer stated (`hub meeting search "<account>"`). Each opportunity is one line: the account, the evidence
with its number and date, the option to propose. No evidence, no opportunity.

## 5. Prepare the packs due

For renewals reaching 60 days, follow `playbooks/renewal-pack.md`.

## 6. Write and hand over

Write `reports/YYYY-MM-DD-account-review.md` in the shape of `knowledge/examples/account-review.md`, update
`knowledge/renewals.md`, then `hub file publish` it. Commit and `hub task update <id> --status done --note`:
notice deadlines in 30 days, packs waiting on a price, sources not read. Always finish the task.
