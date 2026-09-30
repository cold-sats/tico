# Weekly product summary

Schedule: Mondays at 09:00 company time (routine `weekly-product-summary`), once a person has approved
the first summary. Also run by hand. Budget 40 minutes. The outcome is one page for the owner: where the
committed roadmap stands, which decisions wait on a person, and what to build or route next. Nothing is
changed in any tool.

---

## 1. Read where things stand

    hub task show <id>
    hub goal list --all

Then `knowledge/roadmap.md`, `knowledge/decision-log.md`, `knowledge/team.md` and last week's summary.
If last week proposed a decision, check whether it was made; carry it forward or log it.

## 2. Check each committed item

For every item in `knowledge/roadmap.md`: read its source (the doc, the milestone, the linked issues,
read only) and the owner's latest update. Mark it on track, at risk (a dependency open, a spec missing,
more than a week behind) or slipped (target passed). One line each, with the evidence and its date.

## 3. Read what the team produced

For each product bot in `knowledge/team.md`: `hub update list --bot <slug>` and its newest file in
`reports/`. Pull out only what changes a decision: a theme that rose, a finding with three or more
sources, a usage number that moved, a request with many accounts behind it, a price change by a
competitor. List tasks waiting more than five days on a person.

## 4. Score what is asking for room

For new candidates since last week, follow `playbooks/score-a-request.md`. Keep the top three with
their scores and the one thing that would raise confidence most.

## 5. Decide what needs the owner

At most three decisions, each: the question, the options, the evidence, your recommendation and what
happens if nobody decides this week. Add routing proposals (one line each) and, if the pattern in
`playbooks/propose-a-hire.md` holds, one hiring proposal.

## 6. Write and hand over

Write `reports/YYYY-MM-DD-product-summary.md` in the shape of `knowledge/examples/product-summary.md`,
then `hub file publish reports/YYYY-MM-DD-product-summary.md`. Commit, and `hub task update <id>
--status done --note`: the headline, the path, the decisions waiting, and any source you could not read.
Always finish the task.
