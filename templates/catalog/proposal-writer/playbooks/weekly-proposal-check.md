# Weekly proposal pipeline check

Schedule: Fridays at 14:00 company time (routine `weekly-proposal-check`), once a person has approved
the first check. Also run by hand. Budget 25 minutes. The outcome is one page saying which proposals
are stuck and on whom. Nothing is sent or changed.

---

## 1. List the open work

    hub task list --status open --status doing --status waiting

Find every proposal or questionnaire task and the drafts in `reports/`. For each: the deal, the date
requested, the date drafted, the deadline, and the open gaps.

## 2. Flag what is stuck

- Requested more than one working day ago with no draft: why (a missing input is a question to the seller).
- Drafts with open gaps for more than five days, by owner.
- Deadlines inside the next five working days.
- Drafts a seller edited: what changed compared with your draft (learn from it).

## 3. Look for library additions

Answers written new this week that a named owner has approved belong in `knowledge/library/`. List those
still waiting for approval, with the owner.

## 4. Write and hand over

Write `reports/YYYY-MM-DD-proposal-check.md`: headline, deals at risk, gaps by owner, library candidates,
what you could not read. `hub files publish` it, commit, and `hub task update <id> --status done --note`.
Always finish the task: an open scheduled task absorbs the next.
