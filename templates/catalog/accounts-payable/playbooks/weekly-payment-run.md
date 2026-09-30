# Weekly payment run proposal

Schedule: Tuesdays at 09:00 team time (routine `weekly-payment-run`), once a human has approved
the first proposal. Budget 35 minutes. The outcome is one proposal a human approves as a whole or line
by line, and a spend approval request for exactly what is approved. Nothing is paid.

---

## 1. Bring the register up to date

Log every new bill (see `playbooks/process-a-bill.md`). Mark bills paid since last week from the bank
or payables export attached to the task; a bill you cannot confirm as paid stays open and is named.

## 2. Choose what is due

Due this run: bills whose due date falls before the next run, plus bills with an early-payment discount
the team takes. Everything else waits, and its due date is shown in the "coming up" line.

## 3. Hold what is not ready

Hold, with the reason in one clause: no approver sign-off; no match where a purchase order or contract
is required, or a price or quantity difference; a duplicate candidate; a vendor whose bank details
changed and are not yet verified by a callback on a number already on file; a disputed bill.

## 4. Check the total

Total by paying account (by name). Compare with the Head of Finance's latest cash figure and minimum
line where they are readable; if the run would breach it, say so in the first line and propose which
bills could move to the next run without a fee.

## 5. Write and request

Write `reports/YYYY-MM-DD-payment-run.md` in the shape of `knowledge/examples/payment-run.md` and
`hub file publish` it. Ask the requester on the task to approve. On their yes, request exactly the
approved lines: `hub approval request --kind spend --payload-file run.json --task <id>`. Commit, and
`hub task update <id> --status done --note` with the total, the held count and the path.
