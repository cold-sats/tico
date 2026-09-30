# Weekly incident review

Schedule: Mondays at 10:00 team time (routine `weekly-incident-review`), once a human has approved the
first draft. Also run by hand. Budget 45 minutes. The outcome is one page: incidents since last week, a draft
postmortem for each that meets the trigger, open action items past due, and repeats. Nothing is posted.

---

## 1. Read where things stand

    hub task show <id>

Then `knowledge/triggers.md`, `knowledge/actions.md` and last week's review.

## 2. Find last week's incidents

Read what you were given and can reach, in this order: tasks and updates that mention an outage
(`hub task list --status open --status done`, `hub update list --kind daily`), the incident channel if connected
and any error-tracker export attached, merged changes and deploys near each incident (`gh pr list -R <repo> --state merged --search
"merged:>YYYY-MM-DD"`), and any debrief meeting (`hub meeting search "incident"`). List each incident with
start and end time, severity and status. If none, say "no incidents found" and name the sources read.

## 3. Build a timeline for each

Follow `playbooks/build-a-timeline.md`. Reuse a timeline already written during the incident.

## 4. Draft a postmortem where the trigger is met

Follow `playbooks/draft-a-postmortem.md` for each incident that meets `knowledge/triggers.md`. Below the
trigger, write two lines in the review and no postmortem.

## 5. Follow up the action items

Read `knowledge/actions.md`. List items past due, items done since last week, and items with no owner. Ask the
incident lead about an item past due by two weeks. Note repeats: a cause that appears in `knowledge/patterns.md`
again is the headline.

## 6. Write the review

`reports/YYYY-MM-DD-incident-review.md`: headline, incidents in one line each, postmortem drafts (paths),
action items past due, repeats, what you could not read. Then `hub file publish reports/YYYY-MM-DD-incident-review.md`.

## 7. Finish

Commit, then `hub task update <id> --status done --note`: incidents, drafts, past-due items, unread sources.
Always finish it. Share beyond the incident lead only after a Confirm.

## When a source fails

Name it and what is therefore unknown in each affected timeline. A timeline from one source of three that
reads like a full account is worse than a marked gap.
