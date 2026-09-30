# Weekly training tracker

Schedule: Thursdays at 09:00 team time (routine `weekly-training-tracker`), once a human has approved
the first tracker. Budget 25 minutes. The outcome is one page for the HR owner: what is overdue, what is
due, what new starters need, what expires, and what is waiting for budget. Nothing is enrolled or sent.

---

## 1. Read where things stand

    hub task show <id>
    hub team show

Then `knowledge/mandatory.md`, last week's tracker and the newest completion export on the tasks.

## 2. Who needs what

From the roster: for each mandatory course in `knowledge/mandatory.md`, everyone whose role requires it,
with the due date (start date plus the allowed days for new starters; last completion plus the frequency
for everyone else).

## 3. Match to records

Mark each person-course pair: complete (with the record and date), due within 30 days, overdue, or no
record. "No record" is not "overdue": say which it is.

## 4. New starters and expiring certifications

People who started or start in the last or next 30 days and the courses they must finish, added to
`people-hr`'s checklist as one line each. Certifications a role or a customer contract requires that
expire in 60 days.

## 5. Budget requests

Requests on tasks waiting for a decision, with cost and the skill they serve.

## 6. Write and hand over

Write `reports/YYYY-MM-DD-training-tracker.md` in the shape of `knowledge/examples/training-tracker.md`
(counts by team), then `hub file publish reports/YYYY-MM-DD-training-tracker.md --scope task --task <id>`.
Put the per-manager lists on the task for approval. Delete the export, commit, and
`hub task update <id> --status done --note`.

## When a source fails

No export this week means no completion status: say so, and do not carry last week's status forward as current.
