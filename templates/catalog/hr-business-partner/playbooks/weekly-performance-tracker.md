# Weekly performance cycle tracker

Schedule: Wednesdays at 09:00 team time (routine `weekly-performance-tracker`), once a human has
approved the first tracker. Budget 25 minutes. The outcome is one page for the HR owner: where the cycle
stands, who is behind, which probation reviews are coming, and what calibration should look at. It
carries counts and references, never a rating.

---

## 1. Read where things stand

    hub task show <id>
    hub org
    hub task list --status open --status doing --status waiting

Then `knowledge/review-cycle.md`, `knowledge/probation.md` and last week's tracker.

## 2. The phase

Which phase the cycle is in (or how many days until the next one starts), its deadline, and what must
happen this week. Out of cycle, the page is short: next cycle date and probation only.

## 3. Submitted and missing

Per manager: reviews due, submitted, missing, from the review tasks or what the HR owner recorded. A
manager with half or more missing three days before the deadline is flagged with a proposed reminder.

## 4. Probation

Every probation end in the next 30 days: reference, role, end date, reviewer, whether a review meeting
is booked (`hub calendar upcoming`). A date in the next 7 days with nothing booked is bold.

## 5. Calibration flags (when ratings are in)

Follow `playbooks/prepare-calibration.md` step 3 at team level only: spread by team and level, teams with
everyone at one point of the scale, ratings with no evidence cited. Individual detail stays in the
calibration file on its task.

## 6. Write and hand over

Write `reports/YYYY-MM-DD-performance-tracker.md` in the shape of `knowledge/examples/performance-tracker.md`,
then `hub files publish reports/YYYY-MM-DD-performance-tracker.md --scope task --task <id>`. Reminders for
managers go on the task as one-line texts for approval. Commit, and `hub task update <id> --status done --note`.

## When a source fails

A team whose review status you cannot read is "not read", never "on track".
