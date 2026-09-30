# Route a request

Triggered by a task that says a request is stuck, misrouted or has no owner, or by step 4 of the weekly
summary. Budget 10 minutes. The outcome is one proposal on the task: who should take it, and why.

---

## 1. Read the request and its history

    hub task show <id>

Note who has touched it, how long it has waited and what it is waiting on (a customer, a person, a fix).
Read `knowledge/team.md` for who owns what and who is covering today.

## 2. Pick the owner by what the work is

- Answering a customer: the triage bot (`support`) drafts, a person approves.
- A repeated question the docs do not answer: the Librarian (`librarian`), as a task naming the question and the tickets.
- A reply that already went out and may be wrong: Support QA.
- A theme or feature request: the Feedback Analyst, or a person in product.
- A refund, legal, security or outage: a named person in `knowledge/escalation.md` or `team.md`, now.
- A defect: the engineering lead or the product-issue owner, with the ticket count.

If two owners fit, say which you would choose and why. If the person in `team.md` is away, name their cover.

## 3. Write the proposal

On the task: one line naming the owner and the reason, the age and what it waits on, and the draft task
you would create. You do not create it or assign it. `hub task ask <id>` the support owner once, and stop.

## 4. After a yes

Create the task with `hub task create --owner <owner> --parent <id>`, link the ticket, and note it in
`knowledge/decisions-needed.md`. On a no, record the reason in `memory/learnings.md` so the next proposal
is better.
