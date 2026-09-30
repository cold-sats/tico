# Weekly returns report

Schedule: Mondays at 09:00 company time (routine `weekly-returns-report`), once a person has approved
the first report. Budget 30 minutes. The outcome is one page: what came back, what is waiting on a
decision or a refund, and which products keep returning.

---

## 1. Work the open requests

Run `playbooks/decide-a-return.md` for every request without a decision. List them with the
recommended decision and the reply waiting for approval.

## 2. Age the refunds

Every return received (warehouse or customer's tracking shows delivered back) without a refund issued,
with the days since receipt. Anything past the promised refund time goes first, with who issues it.

## 3. Count the week

Requests, approved, refused, exchanged; refund total; median days from receipt to refund. Compare with
the four-week average from `knowledge/ledger.md`.

## 4. Find the product patterns

Return rate and reasons by product and variant from `knowledge/products.md`. A variant returned for the
same reason three times in a month ("runs small", "arrived damaged") is a finding with its orders.

## 5. List the flags

Abuse signals, stated as facts, for the owner only.

## 6. Write and hand over

Write `reports/YYYY-MM-DD-returns.md` in the shape of `knowledge/examples/returns-report.md` and
`hub files publish` it. Commit, and finish the task with the counts and the path.
