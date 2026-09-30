# Weekly onboarding board

Schedule: Mondays at 10:00 company time (routine `weekly-onboarding-board`), once a person has
approved the first board. Budget 30 minutes. The outcome is one page: who is on track, who is behind,
who is stuck and why, and the customer messages ready for approval.

---

## 1. Find who is in onboarding

Every plan in `knowledge/customers/` without a go-live date, plus deals closed since last week (CRM
read, or tasks naming a signed order). A new customer with no plan goes to the top of the board and
gets one today (`playbooks/plan-a-new-customer.md`).

## 2. Read the evidence of progress

For each customer: `hub meetings search "<customer>"`, `hub task list` for tasks naming them, support
tickets routed to the hub, and a usage reading if one is in your access. Log each dated fact in the
plan's progress log. A milestone is done only with evidence.

## 3. Sort

- **On track**: current milestone on or before its target date.
- **Behind**: past the target date but moving.
- **Stuck**: no progress for the stuck-rule days. Name what it waits on: the customer's data or
  decision, our fix, or a person on our side.

## 4. Prepare the next step

For each stuck or behind customer, one next step with an owner and a date. Where the step is a
message to the customer, write the exact text (under 120 words, one clear ask, their goal in the first
line) and the recipient, ready for approval. Nothing is sent.

## 5. Write and hand over

Write `reports/YYYY-MM-DD-onboarding-board.md` in the shape of
`knowledge/examples/onboarding-board.md`, then `hub files publish` it. Put the messages on the task as
separate items so each can be approved on its own. Customers who reached go-live get a handover task
to `customer-success`. Commit, and finish the task with the counts and the path.
