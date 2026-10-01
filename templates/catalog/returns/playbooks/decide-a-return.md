# Decide a return

Triggered by a task or message asking to return, exchange or refund an order. Budget 10 minutes. The
outcome is a decision with its rule, a reply ready to use and, when allowed, a refund or label issued with the available Tools.

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

- **Allowed**: every check passes. Issue the requested refund or label with your Tools.
- **Not allowed**: a check clearly fails. Explain the refusal with the rule, and whether an exception
  (store credit, a partial refund) is worth a human's thought.
- **Unclear**: anything unknown, outside the written policy, a damage claim with missing evidence, or an abuse signal. Investigate and ask only for missing facts or a policy exception the request does not cover.

## 4. Prepare the pieces

The reply: under 120 words, the decision, what happens next (label, where to send, when the refund
lands), and the policy line in plain words. For an allowed return, the label request and the refund
amount (price paid less anything the policy deducts), naming the order. Issue requested labels and refunds within the policy and your Tools.

## 5. Record

Add the line to `knowledge/ledger.md` with the reason in the customer's words and the product variant.
When the payment system confirms the refund was issued, record the date so the refund clock stops. Commit and
finish the task.
