# Weekly ops checklist and team summary

Schedule: Mondays at 08:30 company time (routine `weekly-ops-checklist`), once a person has approved the
first page. Also run by hand on request. Budget 35 minutes. The outcome is one page for the recipient:
what is overdue, what is due, what is blocked, what the Operations bots produced, and what to route. Nothing
is sent, assigned or changed.

---

## 1. Read where things stand

    hub task show <id>

Then `knowledge/rhythm.md`, `knowledge/duties.md`, `knowledge/vendors.md` and last week's page in
`reports/`. Read live sources, not memory:

    hub task list --status open --status doing --status waiting
    hub updates --kind weekly
    hub calendar upcoming

Skim the reports the Operations bots published since last Monday (`recruiting`, `people-hr`,
`legal-review`, `procurement`, `bookkeeping`, `spend-watcher`, `ar-followup`, `meeting-notes`).

## 2. Sort every duty

For each row in the register decide one of: **overdue** (past its date with no proof of completion),
**in its lead window** (notice period or lead time has opened), **due this week**, **blocked** (waiting on a
named person or vendor for more than the agreed wait), **fine**. A duty you cannot date is "needs a date",
and one with no owner is "needs an owner". Neither is ever guessed.

## 3. Choose the checklist items

Pick five to nine items that matter most: the ones costly to miss or easy to forget. Put the rest in a
linked appendix. Each item is one line: what, owner, date, proof needed, source. Say once at the top whether
the checklist is read-do (steps someone has not done before) or do-confirm (an owner who knows the job
confirming the killer items).

## 4. Draft vendor follow-ups

For each vendor thread quiet longer than the agreed wait, follow `playbooks/vendor-follow-up.md`. Attach
the drafts to the task. Never more than three in one page; the rest are listed by name.

## 5. Summarise the Operations team

One line per sibling bot: what it produced this week, with the report path, and what is waiting on a
person. Bots with nothing to report say "quiet" once, not a paragraph. Route work as proposals only:
"Ask `legal-review` to summarise the vendor renewal due 2026-10-14" is a line on the page, and becomes a task
only after a person approves it.

## 6. Write the page and hand it over

Write `reports/YYYY-MM-DD-ops-weekly.md` in the shape of `knowledge/examples/ops-weekly.md`: a headline,
what needs a person, the checklist, vendor follow-ups, the team summary, routing proposals, and what you
could not read. Then:

    hub files publish reports/YYYY-MM-DD-ops-weekly.md

Update `knowledge/duties.md` and `knowledge/vendors.md` with what you learned. Only the recipient in
`knowledge/rhythm.md` gets it, as `hub notice <person> "<one line and the link>"` after approval.

## 7. Finish

Commit, then `hub task update <id> --status done --note`: the headline first, counts (overdue, due,
blocked), and which sources you could not read. Always finish it: an open scheduled task absorbs the next.

## When a source fails

Name it in the page and say what is therefore unknown. A calendar you could not read means "no dated
obligations found in the calendar" is never written; "calendar not read" is.
