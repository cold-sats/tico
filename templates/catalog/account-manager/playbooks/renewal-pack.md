# Renewal pack

Triggered by a renewal reaching 60 days, or by a task that names an account and asks for renewal terms
or an expansion quote. Budget 30 minutes. The outcome is one pack a human can price and approve in ten
minutes. Every price is a gap; nothing is sent.

---

## 1. Read the account

    hub task show <id>

Open `knowledge/accounts/<account>.md`, the current contract (term, seats or units, price, uplift clause,
notice period, auto-renew), the usage against it, the Customer Success Manager's latest note, and what was
promised at the last renewal (the owner's thread or the call).

## 2. Write the current position

Five lines: what they have, what it costs today (from the contract), what they use, the health status and
its date, and anything promised or disputed.

## 3. Shape two or three options

For example: renew as is; renew with the seats they use; a longer term. Each with what changes and why it
fits what the customer said. Every price, discount and uplift is `[price: <approver>]` from
`knowledge/renewal-rules.md`. Never apply an uplift yourself, even a standard one.

## 4. Prepare the paperwork

The order form or renewal quote in the team's template with gaps marked, and a cover note under 120
words in the owner's voice. Put both on the task.

## 5. Hand over

Write `reports/YYYY-MM-DD-<account>-renewal.md`, `hub files publish` it, attach it. Once the approver fills
the gaps and approves, request `hub approval request --kind send` with the final file and recipient.
`hub task update <id> --status done --note`: the options, the gaps, the notice deadline.
