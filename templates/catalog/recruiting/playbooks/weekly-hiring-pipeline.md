# Weekly hiring pipeline summary

Schedule: Fridays at 10:00 company time (routine `weekly-hiring-pipeline`), once a person has approved the
first summary. Also run by hand on request. Budget 30 minutes. The outcome is one page for the hiring
managers: where each open role stands, who is waiting on a person, and what to schedule. Nothing is sent.

---

## 1. Read where things stand

    hub task show <id>
    hub task list --status open --status doing --status waiting

Then `knowledge/pipeline.md`, every `knowledge/roles/<role>.md` for open roles, and last week's page.

## 2. Count by stage

For each role: applications received, summarised, with the manager, in interviews, offer stage, closed.
Use the stages a person set; never move a candidate yourself. A number with no source is left out.

## 3. Find who is waiting

List every candidate waiting on a person longer than the agreed wait (default two working days), with the
person and the days. This is the line managers read first.

## 4. Draft the scheduling

For candidates a manager moved to interview, draft a scheduling message in `hub calendar upcoming` terms:
three real free slots, the interviewers, the length, no video links you cannot see. Invitations to the
roster go through `hub calendar schedule` only after approval; anyone outside the roster is invited by a
person. Attach the drafts to the task.

## 5. Check the kits

Each role in interviews has a kit. A role without one, or with an interviewer who scored differently
against no guide, is a flag on the page.

## 6. Write the page and hand it over

Write `reports/YYYY-MM-DD-hiring-pipeline.md` in the shape of `knowledge/examples/hiring-pipeline.md`.

    hub files publish reports/YYYY-MM-DD-hiring-pipeline.md

Then `hub task update <id> --status done --note`: the headline, counts, and what you could not read.

## When a source fails

Name the role or mailbox you could not read; a role with no data is "not read", never "quiet".
