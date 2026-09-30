# Invoice run check

Schedule: the 25th of each month at 09:00 company time (routine `invoice-run-check`), once a person
has approved the first run; run again on a billing day if inputs arrive late. Budget 40 minutes. The
outcome is a run the approver can approve as a batch. Nothing is issued.

---

## 1. Who is due

From `knowledge/billing-register.md`: every customer with an invoice date in this cycle. Add new
contracts signed since the last run (tasks from sales, closed-won deals where readable).

## 2. Build each invoice

From its source only: the contract's fixed fee and period; the usage export's final figures for the
period times the contract rate; approved hours times the rate; a signed-off milestone. Prorate a
partial period the way the contract says. No final input means held.

## 3. Check each invoice

1. Amount agrees with the source, and the rate with the contract (not only with the billing system).
2. Customer legal name, billing contact and address as the register gives them.
3. PO number present and unexpired where required.
4. Tax as the register gives it for that customer; a new place of supply is a question for the Tax Specialist.
5. Terms and payment route match the contract; the invoice number continues the sequence.
6. No duplicate: the same customer and period is not already invoiced.

## 4. Find unbilled work

Compare delivered work (usage above plan, extra hours, completed milestones, add-ons in tasks) with
invoices. Add each finding to `knowledge/unbilled.md` and to the run as a proposal.

## 5. Write and hand over

`reports/YYYY-MM-DD-invoice-run.md` in the shape of `knowledge/examples/invoice-run.md`, `hub files
publish` it, and ask the approver on the task. On a yes, a person issues the batch from the billing
system (or it goes as `hub approval request --kind send`). Commit, and `hub task update <id> --status
done --note` with ready, held, unbilled and the path.
