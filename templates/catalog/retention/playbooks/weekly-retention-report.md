# Weekly retention report

Schedule: Fridays at 10:00 team time (routine `weekly-retention-report`), once a human has approved
the first report. Budget 30 minutes. The outcome is one page on why customers left or stayed this week,
the open requests with replies ready, and who may leave next.

---

## 1. Close the week's requests

For each line in `knowledge/reasons.md` from the last seven days, record the outcome from the record:
cancelled, downgraded, paused, saved, or still open. A save made 30 or more days ago is confirmed only
if the customer is still paying (billing or CRM read); otherwise mark it lost.

## 2. Count by reason

Requests, saves and losses per reason code, this week and the four-week average. Note the offer used
for each save. A reason whose count doubled is the week's finding.

## 3. Refresh the watch list

Read the signals `knowledge/save-policy.md` lists (usage, downgrades, repeated tickets, failed
payments). Add customers who crossed a signal this week with its date; remove those who recovered. For
a business account, the next step is a task to `customer-success`, not an offer.

## 4. Prepare what is open

For each open request, follow `playbooks/handle-a-cancellation.md` up to the prepared reply.

## 5. Suggest one change

One change backed by this week's counts: a policy offer that is never taken, a reason no offer answers,
a product problem behind several losses. Evidence and who decides.

## 6. Write and hand over

Write `reports/YYYY-MM-DD-retention.md` in the shape of `knowledge/examples/retention-report.md` and
`hub files publish` it. Put each prepared reply on the task as its own item. Commit, and finish the task.
