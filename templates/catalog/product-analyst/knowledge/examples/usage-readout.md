A sample of excellent output for a fictional company. Every name in it is a stand-in.

```markdown
# Acme product usage readout, Wed 2026-09-30

Sample output for Acme, a fictional studio-scheduling software company. Every number is invented.
Source: product database `app`, read 2026-09-30 06:10; queries in `queries/2026-09-30-usage-readout.sql`.
First draft, not yet reviewed.

**Headline: Recurring bookings v2 reached 31% of eligible studios in 3 weeks; activation fell to 38%
(4-week average 44%), with the drop at "add first class".**

## Adoption of recent launches (share of eligible studios)
| Launch | Shipped | Eligible | Used once | Used in 2+ weeks |
|---|---|---|---|---|
| Recurring bookings v2 | 2026-09-08 | 1,410 | 437 (31%) | 262 (19%) |
| Instructor app login | 2026-08-18 | 1,410 | 902 (64%) | 811 (58%) |
| Payout report | 2026-07-21 | 690 (Pro plan) | 124 (18%) | 41 (6%) |

## Activation funnel, signups 2026-09-21 to 2026-09-27 (n = 212)
Signed up 212 → created studio 181 (85%) → **added first class 96 (53%, avg 64%)** → first booking 81 (38%).
Checked: the "class_created" event fired normally; the drop coincides with the new class form released 2026-09-22.

## Retention by signup week (active studios)
Cohorts 2026-08-03 to 2026-09-21: week-4 retention 61% to 66%, within range. No cohort flagged.

## Could not read
Mobile events after 2026-09-28 18:00 are missing from `app` (ingest lag); mobile numbers stop there.

## Tracking gaps
Waitlist interest cannot be measured: no event when a member sees a full class. Proposed event
`class_full_viewed` (task for a person, not created).
```
