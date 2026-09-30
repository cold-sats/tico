# Decide a return

Triggered by a task or message asking to return, exchange or refund an order. Budget 10 minutes. The
outcome is a decision with its rule, a reply ready for approval and, when allowed, a refund or label
request for a human.

---

## 1. Find the order

Match the request to one order: number, delivery date, items and variants, price paid, discounts, and
this customer's returns in the last 90 days. No order found is a question to the customer in the reply,
not a refusal.

## 2. Run the checks

Each check in `knowledge/policy-checks.md` in order: within the window counted from delivery, item
eligible (not final sale), condition as the customer describes it or as photos show, who pays shipping.
Write pass, fail or unknown for each, with the fact behind it.

## 3. Decide which of three

- **Allowed**: every check passes and it is under the "human decides" line. Recommend approval.
- **Not allowed**: a check clearly fails. Recommend a refusal with the rule, and whether an exception
  (store credit, a partial refund) is worth a human's thought.
- **A human's call**: anything unknown, over the value line, a damage claim, or an abuse signal.

## 4. Prepare the pieces

The reply: under 120 words, the decision, what happens next (label, where to send, when the refund
lands), and the policy line in plain words. For an allowed return, the label request and the refund
amount (price paid less anything the policy deducts), as a `hub approval request --kind spend` naming
the order.

## 5. Record

Add the line to `knowledge/ledger.md` with the reason in the customer's words and the product variant.
When a human confirms the refund is issued, record the date so the refund clock stops. Commit and
finish the task.
