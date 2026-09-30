# Weekly people records check

Schedule: Mondays at 10:00 company time (routine `weekly-records-check`), once a person has approved the
first check. Budget 30 minutes. The outcome is one page for the HR owner: leavers and what is still open,
records that disagree, letters waiting, acknowledgements outstanding. Nothing is changed or sent.

---

## 1. Read where things stand

    hub task show <id>
    hub team show
    hub task list --status open --status doing --status waiting

Then `knowledge/leavers.md`, `knowledge/systems.md` and last week's check.

## 2. Leavers

For each leaver in progress: last day, checklist items done (with the dated confirmation), open, late.
Any privileged access not confirmed removed 24 hours after the last day is the first line of the page.
New leavers from the tasks get a checklist (`playbooks/offboard-a-leaver.md`).

## 3. Records audit

If this week's tasks carry an HR export and a payroll export, compare them with each other and with
`hub team show`: name or reference, title, manager, team, start date, employment status, active on payroll.
List each mismatch with both values and dates. A person on payroll who is not on the roster, or the
reverse, goes to the top. Missing documents (a signed contract, a right-to-work check where required)
are listed by reference and type.

## 4. Letters and acknowledgements

Letters prepared and waiting for signature, with days waiting. Policy versions and how many people
have not acknowledged each.

## 5. Write and hand over

Write `reports/YYYY-MM-DD-records-check.md` in the shape of `knowledge/examples/records-check.md`, then
`hub file publish reports/YYYY-MM-DD-records-check.md --scope task --task <id>`. Delete the exports from
the working tree. Commit, and `hub task update <id> --status done --note`.

## When a source fails

No export this week means no audit this week: say so, never repeat last week's findings as current.
