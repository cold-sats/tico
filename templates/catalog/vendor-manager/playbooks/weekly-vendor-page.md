# Weekly vendor and renewals page

Schedule: Tuesdays at 09:00 team time (routine `weekly-vendor-page`), once a human has approved
the first page. Budget 30 minutes. The outcome is one page: which notice deadlines are coming, which
reviews are due, and what is missing from the register. Nothing is sent, renewed or cancelled.

---

## 1. Refresh the register

    hub task show <id>
    hub task list --status open --status waiting

Read new tasks tagged with a vendor name, new contracts in `hub doc search "contract"` since last week,
and, if a mailbox is connected, renewal notices and first invoices from unknown senders. A vendor paid
but not in the register is added with "found via invoice <date>" and no owner.

## 2. Compute notice dates

For each contract: notice deadline = end date minus notice period. Sort by notice deadline, not end
date. Mark each: **open now** (inside the window you agreed, default 90 days), **urgent** (inside 30
days), **passed** (the contract has renewed for another term; say so plainly with the new end date).

## 3. Reviews due

Tier 1 vendors with no review in 90 days, tier 2 with none in a year. List each with its owner and the
last issue on file (missed deliveries, outages, support tickets, invoice disputes).

## 4. Gaps

Vendors with no owner, no contract on file, no tier, or holding team data with no security review on
file (ask `security-compliance` if it exists). One line each.

## 5. Write the page

`reports/YYYY-MM-DD-vendors.md` in the shape of `knowledge/examples/vendor-page.md`: headline, urgent,
open renewals with a one-line call each (the full brief via `playbooks/renewal-brief.md` for any over
the always-show amount), reviews due, gaps, register changes. Then `hub file publish` it.

## 6. Finish

Commit, then `hub task update <id> --status done --note` with the headline and counts. A quiet week is
one line, and the task is still finished.
