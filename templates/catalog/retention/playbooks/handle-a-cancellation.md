# Handle a cancellation

Triggered by a task or message where a customer asks to cancel, downgrade or stop renewing. Budget 10
minutes. The outcome is a coded reason, one matched offer or none, and a reply ready for approval.

---

## 1. Read the request and the account

The customer's own words, their plan, tenure and value (CRM or billing read), recent tickets and usage
if readable. If a request for this customer is already open, add to it.

## 2. Code the reason

Pick one code from `knowledge/save-policy.md`, from what they said, not what you suspect. If they gave
no reason, code it "not given"; the reply may ask once, never as a condition of cancelling.

## 3. Match one offer, or none

Look up the offer for that code and check its limits (tenure, how often this customer has had one).
No offer when the policy has none for the reason, when the customer has had one within the limit, or
when they said plainly they have decided. Never invent an offer.

## 4. Prepare the reply

Under 120 words: thank them, acknowledge the reason in their terms, make the one offer if there is one,
and say plainly how to complete the cancellation and when billing stops if they still want to go. For a
missing feature, say honestly whether it is planned only if a human or the docs confirm it.

## 5. Put it forward

Attach the reply to the task for the approver. If the customer accepts an offer or confirms cancelling,
the billing change is a `hub approval request --kind spend` (for a discount or refund) or a task for the
human who changes billing. Log the line in `knowledge/reasons.md` and commit.
