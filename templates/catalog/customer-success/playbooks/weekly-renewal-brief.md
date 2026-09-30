# Weekly renewal and health brief

Schedule: Tuesdays at 09:00 company time (routine `weekly-renewal-brief`), once a person has approved
the first brief. Also run by hand. Budget 40 minutes. The outcome is one page: what renews when, who is
at risk and why, and a draft next touch. Nothing is sent and no record changes.

---

## 1. Read where things stand

    hub task show <id>

Then `knowledge/renewals.md`, `knowledge/health-rules.md` and last week's brief. Check whether last
week's flagged actions happened.

## 2. Refresh the calendar

Read the renewal source (a CRM read, or the list the owner keeps up to date). List every renewal in the
next 120 days: account, date, notice deadline, owner, value. Sort by date. Mark the playbook stage:
120, 90, 60 or 30 days out. A missing notice deadline is flagged.

## 3. Read the signals for each account in the window

Usage trend where readable (last 30 days against the prior 90), open and recent tickets, the last call
(`hub meetings search "<account>"`), payment status if given, and whether the champion changed. Name every
signal you could not read.

## 4. Give each account a status

Apply `knowledge/health-rules.md`: green, yellow or red with the two facts behind it. Update
`knowledge/accounts/<account>.md`. A change since last week is marked "moved from yellow to red".

## 5. Draft the next touch for each yellow or red account

One action for one person: who, what and by when; a message under 100 words in the account owner's voice,
with `[price: Account Manager]` or `[date: account owner]` gaps wherever it would need them. Never send.

## 6. Write and hand over

Write `reports/YYYY-MM-DD-renewal-brief.md` in the shape of `knowledge/examples/renewal-brief.md`, then
`hub files publish reports/YYYY-MM-DD-renewal-brief.md`. Commit and `hub task update <id> --status
done --note`: the headline, the path, what you could not read. Always finish the task.
