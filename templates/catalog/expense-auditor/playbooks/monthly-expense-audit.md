# Monthly expense audit

Schedule: the 3rd of each month at 09:00 team time (routine `monthly-expense-audit`), after setup. Budget 40 minutes. The outcome is one audit for finance with a section
per owner. Nothing is approved, rejected or sent.

---

## 1. Gather the month

    hub task show <id>

The expense report export and the card export for the month just ended, with receipts. Note each
export's date range and row count, and which cards or people have no rows (a finding, not zero).

## 2. Run every check on every line

From `knowledge/policy-rules.md`, skipping anything in `knowledge/exceptions.md`:
1. **Receipt**: over the threshold with no itemised receipt, or a receipt whose amount or date differs.
2. **Limit**: over the category limit (meal per person, hotel per night, flight class).
3. **Never reimbursed**: personal items, fines, alcohol without a client, whatever the policy lists.
4. **Source records**: travel or purchases that needed it and have no record of it.
5. **Duplicates**: same merchant, amount and date on two lines, two reports, a card and a claim, or two
   people; the same receipt file twice.
6. **Timing**: submitted after the window; weekend or holiday charges the policy asks about.
7. **Card with no claim**: card charges older than 30 days with no report or receipt.

## 3. Sort and size

Group by owner, then by rule. Small repeats become one line with the count and total. Put first
what is large, repeated or a duplicate candidate.

## 4. Write and hand over

`reports/YYYY-MM-expense-audit.md` in the shape of `knowledge/examples/expense-audit.md`:
headline, totals, per-owner sections, then "Could not read". `hub file publish` it (finance only),
commit, and `hub task update <id> --status done --note` with the headline and the path. Offer, on the
task, a prepared note per owner; send requested notes to the intended finance readers with your Tools.
