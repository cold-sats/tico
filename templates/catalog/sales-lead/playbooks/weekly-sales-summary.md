# Weekly sales team summary

Schedule: Mondays at 08:00 company time (routine `weekly-sales-summary`), once a person has approved
the first summary. Also run by hand. Budget 35 minutes. The outcome is one page for the owner: how the
pipeline moved, which deals need a person, and what to route where. Nothing is changed or sent.

---

## 1. Read where things stand

    hub task show <id>

Then `knowledge/pipeline-rules.md`, `knowledge/team.md`, `knowledge/routing.md` and last week's summary in `reports/`. If
last week flagged an action, check whether it happened; say so in the summary.

## 2. Read the pipeline

Use the source the rules name: a read of the CRM (only ever a read), `sales-ops`' latest pipeline
report, or the pipeline notes. Get each open deal's stage, amount, days since last activity and next
step. Compare with last week's summary to find what entered, moved, closed and slipped.

## 3. Read what the team produced

`hub updates --kind weekly` and `hub task list` for each sales bot in `knowledge/team.md`, plus the
newest file in its `reports/`. Count drafts made, leads researched, proposals started, renewals
flagged. List tasks waiting more than 5 days on a person or on a missing input.

## 4. Choose the priority deals

Three to five, in this order: closest to close and needing a step; stalled past the threshold (default
14 days); large deals over the "always show" size; new deals with no next step. Skip healthy ones.

## 5. Draft routing proposals

For each new lead, account or request with no owner: pick the owner from `knowledge/routing.md` and
propose it in one line with the reason. Do not create tasks. A proposal a person approves on the task
becomes `hub task create --owner <slug>` (see `playbooks/route-a-request.md`).

## 6. Write and hand over

Write `reports/YYYY-MM-DD-sales-summary.md` in the shape of `knowledge/examples/sales-summary.md`, then
`hub files publish reports/YYYY-MM-DD-sales-summary.md`. Commit, and `hub task update <id> --status done
--note`: the headline, the path, which sources you could not read. Always finish the task.

## When a source fails

Name it and what is therefore unknown, and keep going with the rest. A summary built from the notes
alone says so in its first line.
