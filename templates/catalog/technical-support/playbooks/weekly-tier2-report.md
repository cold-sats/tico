# Weekly tier 2 queue report

Schedule: Thursdays at 09:00 team time (routine `weekly-tier2-report`), after setup. Budget 30 minutes. The outcome is one page on the technical queue: what is open,
what engineering is holding, what was solved, and what keeps coming back.

---

## 1. List the queue

Every open tier 2 task (`hub task list --owner technical-support --status open --status waiting`) with
its age, verdict so far and what it waits on: the customer, engineering, or you.

## 2. Check engineering status

For each bug reported, the issue's state and last movement (read only). A bug with no response for five
working days is flagged with its customer count.

## 3. Count what came back

Problems seen more than once this week or this month, from `knowledge/workarounds.md` and the cases.
A problem seen three times with a workaround and no fix is the week's finding: it costs support time
every week until fixed.

## 4. Prepare replies

For tickets where the investigation finished, the customer reply is ready on the Support Agent's task
for review. List them.

## 5. Write and hand over

Write `reports/YYYY-MM-DD-tier2.md` in the shape of `knowledge/examples/tier2-report.md` and
`hub file publish` it. Commit, and finish the task with the counts and the path.
