# Manage a company's billing (staff)

**Unreleased Hosting update:** billing remains off. The Hosting rules below do not confirm deployment or activation.

Only Tico staff see this page. Open **Customers** on the admin page, pick the company, then open **Billing**.
The page sits behind Cloudflare Access, so customers never reach it, and HQ only takes these changes with
the staff billing key. Customers cannot change their own minimum balance, grace period, or enforcement.

The **Account** panel shows the balance, the status, enforcement, the minimum balance and the Hosting grace
period. The company is **Active** only while its balance is above its minimum. At or below the minimum it is
**Paused**: a balance of $0.00 with a $0 minimum is paused. Below the panel are the settings history, credits,
the month's debits, usage by day and the month's statement, the same figures the company sees.

**Balance** is the billed balance. The **Account** panel also separates these Gateway readings:

- **Unbilled usage** is usage since the last hourly bill.
- **Live balance** is the billed balance less unbilled usage.
- **Gateway** reports **Running**, **Stopped**, or an unknown status. In **Enforce** mode, it stops on the live balance and follows within five minutes.

A credit can clear the billed pause while the Gateway still refuses calls because unbilled usage uses up that credit.
If HQ supplies no live reading, **Gateway** says **HQ doesn't report the live balance**.
The staff account response carries this reading in `live`. The direct live route uses the billing account ID.

The Gateway stop time comes from a recorded stop event.
A stopped Gateway without that event has an unknown stop time (`stopped_since: null`).
Repeated reads do not invent a time. Once the event is recorded, its timestamp stays the stop time.
Where stop times appear in credit notices, an unknown time reads **Not reported yet**.

## Add credit

In the **Add credit** form:

1. Enter the **Amount (dollars)**, like 10, 25.50 or 0.01. It must be more than $0.
2. Pick the **Type**: **Grant**, or **Credit by arrangement** for credit the company pays for
   by arrangement (no card payment runs).
3. Optionally set **Ends**. The credit counts to the end of that day (UTC).
4. Enter the **Reason**. It is required.
5. Select **Add credit**.

The balance goes up by the amount. Sending the same form twice by accident still makes one credit.

## Reverse a debit

Each debit in **Debits in** the month that isn't reversed yet has its own Reverse form:

1. Enter the **Reason** next to the debit. It is required.
2. Select **Reverse**.

The original stays listed, marked **Reversed**, and the balance goes back up by that amount.
Nothing on this page is ever edited or deleted: every fix is a new row.

## Change settings

The **Change settings** form holds all three settings, filled in with the current values. Change the
ones you need, enter the **Reason** (required), and select **Change settings**. Each change is saved as a
new settings row.

### Minimum balance

Enter dollars. It may be negative: a −$50 minimum lets the company keep working until the balance
reaches −$50.

Raising the minimum to the balance or above pauses the company. In **Enforce** mode its Tico models
stop within 5 minutes. Lowering the minimum below the balance, or adding credit so the balance ends
above the minimum, lets them start again within 5 minutes.

For Hosting in **Enforce** mode, raising the minimum to the balance or above starts grace when you save the change.
Lowering it below the balance ends grace. Credit ends grace only when the balance is above the minimum.

### Hosting grace period (hours)

A whole number of hours. The default is 72. Zero means no grace; waitlist servers stop within five minutes of reaching the minimum.

The stop time counts from when the balance first reached the minimum. Changing the grace period
recomputes that stop time from the same starting point.
If the new deadline has already passed, servers stop at the next daily run at 00:05 UTC, rather than when you save.
For example, shortening a 72-hour grace to 48 hours after 50 hours schedules the stop for that next daily run.

Stops retain the servers’ data. With positive grace in **Enforce** mode, the current owner gets the grace-start email,
a 24-hour reminder where applicable, and the stopped/data-kept email.
The owner’s account page shows one **Needs you: add credit** card with the UTC stop time and **Ask for more credit** direction.
Changing the grace period updates that card. Recovery above the minimum or a completed stop removes it.
See [Hosting grace and retained data](account.md#hosting-grace-and-retained-data) for the email timing and exclusions.

The recipient comes from the current company owner’s membership and profile, not the original sign-up email.
A failed or partial delivery is recorded as `unsent`, even if one channel succeeded.
There is no automatic retry or outbox for grace notices. An unsent result does not prove that no email was accepted.
Zero-hour companies, including waitlist companies, use their separate credit-notice run-out email instead.
**Record only** companies receive no grace notices. Delivered notices and the live card remain unverified.

For the daily charge and restart rules, see [Hosting grace and retained data](account.md#hosting-grace-and-retained-data)
and [More credit and restarting](account.md#more-credit-and-restarting).
Positive-grace accounts require manual owner restart; the guarded owner-start path is unfinished.
Zero-grace waitlist recovery instead checks both servers together before automatically restarting either.

### Enforcement

Pick **Record only** or **Enforce**.

**Record only** is the default for every company: usage and balance are recorded and shown, and
nothing stops. Tico Team's own install always stays **Record only**. With **Enforce**, the company's
Tico models stop at the minimum balance and its Hosting servers stop once the grace period ends.

## Settings history

Every change needs a reason, and every change is listed under **Settings history** with the old
value, the new value, who made it, and when.

## If HQ does not answer

If HQ does not answer, the page shows **Send again** at the top with the same change. It is safe to
select it: HQ makes the credit or change at most once.
This form retry does not resend an unsent grace notice.

A company with no billing account yet shows only the Add credit and Change settings forms. Adding a
credit or changing a setting opens the account with HQ's defaults: minimum $0.00, Hosting grace
period 72 hours, Record only.

*Hosting changes checked 2026-10-23: ticoteam/tico-services#138; Billing system spec v1.1, boundary rule and tests 7–8 and 19–23; waitlist spec v3.4, Answers 15–16. Owner-start safeguard (Dev 430) remains separate; grace notices are covered below from services#147. Billing remains off.*

*Grace notices and Gateway status checked 2026-10-23: [ticoteam/tico-services#147](https://github.com/ticoteam/tico-services/pull/147), billing/staff.py (staff_billing_account), billing/gateway_usage.py (live), billing/grace_notices.py, billing/hosting.py, and portal/views.py; Billing system spec v1.1, tests 7 and 19. Gateway labels checked in ticoteam/tico-internal admin/tico_admin/billing.py (standing), reviewed source 58bb5077. Fresh internal-repository access, separate admin installation, HQ deployment, daily billing activation, live email, and power actions not verified.*
