# Review a design doc

Triggered by a task naming a design doc, an RFC or a large structural pull request, and used for each new
design in the weekly review. Budget 40 minutes. The outcome is review notes the author can act on and the
decision-maker can decide from. Nothing is posted on the document.

---

## 1. Read it twice

    hub task show <id>

First for the problem, then for the solution. Read the parts of `knowledge/system-map.md` it touches and any
ADR it contradicts or supersedes.

## 2. Restate

In three sentences: the problem, the proposal, and what success looks like. If you cannot restate the
problem, that is the first finding.

## 3. Check

- **Options:** were at least two considered, including doing nothing? If not, name the obvious alternative.
- **Boundaries:** which services, data stores and teams change; new coupling or a new single point of failure.
- **Data:** ownership, migration and backfill, what happens to existing records, rollback.
- **Failure:** what happens when a dependency is slow or down; limits and retries.
- **Operations:** how it is deployed, observed and turned off; who is paged.
- **Security and privacy:** new data collected, new external calls, new secrets (flag to the Security Engineer).
- **Cost and reversibility:** is this a one-way door? If so, it needs the most scrutiny.

## 4. Write the notes

`reports/reviews/<doc>.md`: the restatement, the top three questions (blocking first), the risks each with a
mitigation, and the ADR the decision will need. Label each point blocking or non-blocking. Attach, commit,
and `hub task update <id> --status done --note` with the one blocking question in the first line.
