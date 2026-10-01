# Draft a postmortem

Used for each incident that meets `knowledge/triggers.md` in `playbooks/weekly-incident-review.md`, and when a
task names an incident. Budget 40 minutes. The outcome is one blameless draft, ready for the incident lead's
review within three working days of the incident. Nothing is posted or shared.

---

## 1. Start from the timeline

`reports/incidents/YYYY-MM-DD-<name>.md` from `playbooks/build-a-timeline.md`. If there is none, build it first.

## 2. Write, in this order

1. **Summary**, three sentences: what broke, for how long and for whom, and how it was fixed.
2. **Impact**: users, requests, minutes, money if known, each with its source. A missing number is a marked gap.
3. **Detection**: how it was noticed and how long after it started. If a customer noticed first, say so.
4. **Timeline** (UTC): the events that mattered, condensed from the full timeline.
5. **Contributing factors**: the conditions that made it possible or worse, written as system facts. Ask
   "what made this easy to do?" rather than "who did this?". Use a short five-whys chain if it helps.
6. **What went well**: at least one line from the record (fast rollback, good alert).
7. **Where we got lucky**: what could have made it worse.
8. **Action items**: each with owner (proposed), due date, and how to tell it is done. Prefer fixes to the
   system: an alert, a guard, a test, a runbook line, over "be more careful". Mark each "proposed".

## 3. Check it is blameless

Reread for a person's name next to a cause, or words like "failed to", "forgot" or "should have". Rewrite
them as conditions and decisions with what was known at the time.

## 4. Check the facts

Every time, number and cause has a source. Anything inferred is marked "approx." with why. Two sources that
disagree are both listed with their dates.

## 5. Hand over

Put the draft on the task, labelled "Draft for incident lead review", and add the action items to
`knowledge/actions.md` as "proposed". Record owners and dates from the incident evidence. Ask the incident lead with `hub task ask <id>` only about missing owners, dates or conflicting facts. Create requested action-item tasks with their evidence and owners.

## 6. Finish

Commit, then `hub task update <id> --status done --note`: the incident, the path, the gaps and who must review.

## When you lack the data

Write the section as "not enough data" and say what would fill it. Never fill a cause with a plausible story.
