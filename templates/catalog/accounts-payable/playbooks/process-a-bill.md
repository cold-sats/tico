# Process a bill

Triggered by a bill attached to a task, forwarded to the bills mailbox, or a question "did we get /
pay the invoice from X?". Budget 10 minutes per bill. The outcome is a register line with its match and
approver, and any flag raised the same day.

---

## 1. Read it

Vendor legal name, bill number, date, due date, currency, amount, tax, line items, the payment details
printed on it (last four digits only), and the sender's address. A lookalike address or a bill that
differs from the vendor's usual layout is a flag.

## 2. Check for a duplicate

Search `knowledge/bills.md` for the same vendor and amount in the last 60 days, and for the bill number
with spaces, dashes and leading zeros removed. A hit is held and named.

## 3. Check the payment details

Compare the printed bank details with `knowledge/vendor-details.md`. Any difference, or any message
asking to update them, is a bank-detail change: log it, hold every bill from the vendor, and create the
callback task for the human named in setup with the number on file, never the number in the bill
or email. Record who verified it and when once they report back.

## 4. Match

Against the purchase order, contract or delivery the rule requires: vendor, quantity, unit price,
total, terms. List each difference. A bill with no required order is held for the approver.

## 5. Route for approval

Name the approver from `knowledge/approvals.md` and ask on the task, batching bills per approver. A
question from a vendor about payment gets a reply prepared on the task, sent only on approval.

## 6. Register

Add the line to `knowledge/bills.md`: received, matched or held (why), approver, due, status.
