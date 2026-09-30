# Review an expense report

Triggered by a task with one expense report to check before an approver signs it. Budget 10 minutes.
The outcome is a review note: pass, or the lines to question, each with its rule. Nothing is approved.

---

## 1. Read the report

    hub task show <id>

Who submitted it, who approves it (`knowledge/approvers.md`), the period, each line and each receipt.

## 2. Check

Run the seven checks from `playbooks/monthly-expense-audit.md` on each line, plus: the total on the
report equals the sum of its lines; currency conversions use the rate on the card statement or the
receipt date.

## 3. Write the note

Three parts, under 150 words: **Pass** or **Question N lines**; one line per question (date, merchant,
amount, the rule, what would resolve it: "an itemised receipt", "the client's name"); and what was not
checkable. Neutral words only.

## 4. Hand over

Put the note on the task for the approver and `hub task update <id> --status done --note` with pass or
the count. If the approver grants an exception, record it in `knowledge/exceptions.md` with who and when.
