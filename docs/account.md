# Your Tico account page

**Unreleased:** this help describes the merged account-page update. Deployment is still being verified.

[app.tico.dev](https://app.tico.dev/) is your company’s account page, hosted by Tico on HQ.
It stays available when your Tico server or bot computer stops.
Sign in with your Tico account and select your company from the **Company** menu.
The page shows only companies you belong to.

## Before approval

While you wait, the page shows **You’re on the waitlist**.
If staff decline your sign-up, it shows **We can’t offer a spot right now**.
See [Joining the Tico waitlist](waitlist.md).

## Balance and credit

After approval, **Account** shows your balance, remaining credit, and when the credit expires.
If billing is still being set up, it shows **No credit yet**.

- **Balance** is the live balance, including Tico models usage not yet recorded in an hourly debit.
- **Credit** shows the unused amount out of the original grant. The page shows up to three current credits.
- A credit labelled **ends end of YYYY-MM-DD (UTC)** includes that whole UTC day.
  For example, credit ending on October 31 expires at 00:00 UTC on November 1.
  If an expiry includes a time, that UTC time is the expiry.

The live balance can fall before the usage tables update. Credit remaining and balance can therefore differ.
Expired unused credit no longer counts toward the balance.

## Usage

The account page and staff admin page use the same company billing records.

| Section | Shows |
|---|---|
| **Tico models today, by hour (UTC)** | Today’s recorded model charges, grouped by UTC hour. |
| **Servers this month, by day (UTC)** | This month’s recorded server charges, grouped by UTC day. |

An empty section says **No usage yet**.
The server table’s daily plan rate is separate from these recorded charges.

Hosting records one charge per running server per UTC day, at the daily run at 00:05 UTC.
Each server has its own charge. Restarting on a day already charged does not add a second charge for that day.

## Servers

**Servers** lists your **Tico server**, which runs your Tico, and your **Bot computer**, which runs your bots.
Each row shows its address or label, **State**, and **Price**.

| State | Price shown | Open your Tico |
|---|---|---|
| **Waiting**, **Creating**, or **Installing** | Advertised daily plan rate. This does not confirm a running server or a debit. | Unavailable. |
| **Ready** and running | Daily plan rate. | Available on the Tico server row only. |
| **Stopped**, **Failed**, or **Ended** | A dash, with no running price. Earlier charges remain in usage. | Unavailable. |

## Hosting grace and retained data

**Unreleased:** Hosting billing remains off. These rules describe the billing update, whose deployment and activation are not confirmed.

The default Hosting grace period is 72 hours. Tico staff can set a different period for your company.
In enforcement mode, grace starts when your balance reaches or falls below the minimum.
Exactly the minimum still counts as paused.

Adding credit ends grace only when the balance rises above the minimum.
A partial credit that leaves the balance at or below the minimum keeps the original stop time.
For example, with a $0 minimum, raising a balance from −$5 to $0 leaves grace running.
Raising it to $0.01 ends grace.

If staff raise the minimum to your balance or above it, grace starts when they save the change.
Lowering the minimum below your balance ends grace, as enough credit does.

Changing the grace period keeps its original starting point.
If staff shorten it past the time already elapsed, servers stop at the next daily run at 00:05 UTC.
For example, changing a 72-hour grace to 48 hours after 50 hours schedules that stop for the next daily run.

The grace-notice update is still pending.
It includes the stop time at grace start, a reminder 24 hours before stop, and a stop email.
Delivered grace notices and **Needs you** items are not yet confirmed.

When grace expires, Tico stops the servers and keeps their data. It does not delete them for running out of credit.
Waitlist accounts have zero grace: both servers stop within five minutes of reaching the minimum.
Your account page stays available while your Tico server and bot computer are stopped.

## More credit and restarting

[Ask for more credit](ask-for-credit.md) sends a request to Tico staff from this account page.
You can use it while your servers are stopped.

After staff add enough credit to cover model usage and bring the balance above the minimum, Tico models resume within five minutes.
Server restart follows a separate check.

Server restart requires enough credit to cover today’s uncharged server costs and keep the live balance above the minimum.
Amounts already owed must also be covered. A positive balance alone may not cover a new UTC day’s server costs.

| Account | Restart rule for the billing update |
|---|---|
| Waitlist account with zero grace | Both servers restart automatically only when the balance covers today’s uncharged costs for both and stays above the minimum. If either fails this check, neither restarts. |
| Account with a positive grace period | Stopped servers need a manual owner restart. Each server must pass the same balance and daily-cost check. This owner-start path is still being completed. |

For example, credit added on the same UTC day can reuse server charges already paid for that day.
After a new UTC day starts, the restart check includes that day’s uncharged server costs.
This check does not change the separate model-recovery rule above.

The intended manual-start safeguard refuses starts while paused or short of today’s server costs.
Its owner control is unfinished, so this help does not provide a start procedure.

**Unreleased dependencies:** the manual owner-start safeguard, grace notices, and credit-notice banners and restart-shortfall amounts remain separate work.
The billing and account-page merges do not confirm their availability or enable billing.

*Sources checked 2026-10-23: ticoteam/tico-services#127, portal/views.py (account, _ends, _usage), portal/account.py (summary), and hosting/preview.py (company_servers); spec v3.4 sections 2–3 and Answers 14–15. Banner dependency: Credit notices (Dev 346). Deployment and live sign-in not verified.*

*Hosting rules checked 2026-10-23: ticoteam/tico-services#138; Billing system spec v1.1, boundary rule, section 2, and tests 7–8 and 19–23; billing database design, Option A and Settled; waitlist spec v3.4, section 2 and Answers 15–16. Manual owner-start dependency: Dev 430. Grace notices: Dev 347. Billing remains off; deployment and live power actions not verified.*
