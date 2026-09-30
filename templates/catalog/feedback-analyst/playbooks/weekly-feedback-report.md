# Weekly feedback report

Schedule: Mondays at 08:00 team time (routine `weekly-feedback-report`), once a human has approved
the first report. Also run by hand on request. Budget 40 minutes. The outcome is one report for the
product owner. Nothing is sent to a customer.

---

## 1. Read where things stand

    hub task show <id>

Then `knowledge/themes.md`, `knowledge/segments.md` and `knowledge/trends.md`. Set `hub bot status set` to one
line naming the report.

## 2. Collect the week

Read the last seven days from every source in your access: tasks and attachments, Support Agent's
digests and known-issues, imported calls, the mailbox or channel if connected. Write down each source,
how many items it gave, and any that were blocked. A blocked source is a line in the report.

## 3. Tag

Follow `playbooks/tag-a-batch.md`: one primary theme and a severity for each item, sentiment, segment,
source and date, with personal details removed. Save the log to `knowledge/log/YYYY-MM-DD.md`.

## 4. Count and compare

Update `knowledge/trends.md`: the count per theme this week and last week. Rank themes by count times
severity, weighted by segment as `knowledge/segments.md` says, and show all three numbers. Flag anything
new (a theme with three or more items that did not exist), anything up by half or more, and anything that
faded. Fewer than 5 items in a theme is a note, not a trend.

## 5. Write and hand over

Write `reports/YYYY-MM-DD-feedback-report.md` in the shape of `knowledge/examples/weekly-feedback-report.md`:
headline, ranked themes with counts and change, two or three anonymised quotes for each of the top three,
what is new, three suggested actions each with evidence and an owner to ask, what was excluded, what could
not be read, sources. Then:

    hub file publish reports/YYYY-MM-DD-feedback-report.md

## 6. Finish

Commit, then `hub task update <id> --status done --note`: items read, top theme and its change, what is
new and any source you could not read. Always finish it: an open scheduled task absorbs the next.

## When a source fails

Name it and what is therefore unknown, use the rest, and say so in the headline area of the report. A
report built from one source of three that reads like all feedback is worse than none.
