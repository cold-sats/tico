# Daily escalation digest

Schedule: weekdays at 08:30 team time (routine `daily-escalation-digest`), once a human has
approved the first digest. Budget 25 minutes. The outcome is one page for the people who own
escalations, plus every customer update due today ready for approval.

---

## 1. Refresh the register

Read `knowledge/register.md`. Add new escalations from `hub task list` (anything matching a trigger in
`knowledge/escalation-rules.md`) by following `playbooks/open-an-escalation.md`.

## 2. Read each open case

For each case: the ticket thread (mail read or the task), the engineering issue (read only), calls
(`hub meeting search "<customer>"`) and the case owner's notes. Append new facts to the case timeline
with time and source.

## 3. Work out what is due

- The next customer update: last update time plus the severity's cadence. Due today or overdue goes to
  the top.
- Engineering: acknowledged or not, last movement, the next step they named.
- Cases where the customer confirmed the fix: ready to close.

## 4. Prepare the updates

For each update due, write the exact text: what happened since the last update, what is happening next,
when they will hear again. No fix date unless engineering gave one in writing, and then with the source.
Name the recipient and the case owner who approves it.

## 5. Write and hand over

Write `reports/YYYY-MM-DD-escalations.md` in the shape of `knowledge/examples/escalation-digest.md` and
`hub file publish` it. Put each update on the task as its own item for approval. Tell an owner whose
update is overdue with `hub message send`. For closed cases, add the lesson to `knowledge/lessons.md`. Commit,
and finish the task with the counts and the path.
