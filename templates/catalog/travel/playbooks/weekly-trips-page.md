# Weekly trips page

Schedule: Mondays at 10:00 team time (routine `weekly-trips-page`), once a human has approved the
first page. Budget 20 minutes. The outcome is one page of every trip in the next 30 days and what each
still needs. Nothing is booked.

---

## 1. Collect the trips

`knowledge/trips.md`, open tasks that mention travel, and calendars where connected (events in another
city, "flight", "hotel"). A trip on a calendar with no request is added as "not requested".

## 2. Status per trip

**Planned** (options ready), **awaiting approval** (with approver and days waiting), **booked**
(confirmations filed), **documents** (entry requirements not confirmed by the traveller), **not
requested**. A trip inside the advance-booking window and not booked is flagged with how many days
are left and what the fare was when last checked.

## 3. Spend against policy

Booked trips this month: total, and any booked outside policy with the approved reason. Never a
judgement of a human; a pattern (hotels in one city always over the limit) becomes a policy question.

## 4. Write and hand over

Write `reports/YYYY-MM-DD-trips.md`, `hub files publish` it, commit, and `hub task update <id> --status
done --note` with the headline: trips in 30 days, unbooked inside the window, awaiting approval.
