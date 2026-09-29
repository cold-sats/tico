A sample of excellent output for a fictional company. Every name in it is a stand-in.

```markdown
# Acme support triage, Tue 2026-09-29, 09:00

Sample output for Acme, a fictional company. Every ticket, name and address below is invented.

**Headline: 11 arrived since yesterday, 8 drafted, 2 need a person today, 1 repeat became a product issue.**

## Needs a person today
- **T-2041, refund request over the studio plan** (customer says they were charged twice). Task created
  for Ben Okafor: "Decide on a refund for a double charge". Draft has a marked gap where the refund would
  go. Not promised.
- **T-2046, possible outage**: three studios cannot open the booking page since 08:10. Task created for
  Ana Rivera. Draft holds a holding reply with no time promised.

## Drafts ready for approval (8)
| Ticket | Bucket | Draft says | Source |
|---|---|---|---|
| T-2038 | Answered before | How to reset a studio's calendar link | answers.md, "Reset calendar link", confirmed 2026-09-12 |
| T-2039 | Answered before | Invoices are emailed on the first of the month | answers.md, "Invoice timing", confirmed 2026-09-05 |
| T-2040 | Known issue | Calendar sync can lag up to 10 minutes; a fix is being worked on | known-issues.md, "Sync lag", count now 4 |
| T-2042 | New | Asks which plan includes SMS reminders. Draft says we are checking and will confirm; needs an answer | not in answers.md |

The other four are the same shape and are on the task.

Draft for T-2038, for the person to approve (nothing has been sent):

> Hi Priya, thanks for asking about resetting the calendar link. Open Settings, then Calendar, and choose
> "Reset link". Your old link stops working straight away, so share the new one with your studio. If the
> option is missing, tell us your plan and we will take a look.

## Patterns
- **Calendar sync lag** reached 4 tickets in 10 days. Promoted to a product issue: one task for Dana
  Okoye with the ticket references and the count. Not escalated again.
- "SMS reminders" asked twice, no standing answer yet. Proposed answer for a person to confirm: unknown, ask
  Cara Mendes which plan includes it.

## Could not read
The Slack support channel refused access (not connected). Only the support mailbox was read.

## Sources
- Support mailbox, 11 messages 2026-09-28 09:00 to 2026-09-29 08:55
- `knowledge/answers.md`, `knowledge/known-issues.md`, read 2026-09-29
```
