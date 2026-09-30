# Weekly reorder list

Schedule: Mondays at 07:30 team time (routine `weekly-reorder-list`), once a human has approved the
first list. Budget 30 minutes. The outcome is a reorder list and one purchase order per supplier ready
for approval. Nothing is ordered.

---

## 1. Get this week's data

The sales and stock exports on the task. If they are missing or older than 7 days, ask once with
`hub task ask <id>` and build the list from the last exports, saying so in the first line.

## 2. Update the item plan

Recompute average and maximum daily sales over the window for every item. Update observed lead times
from any deliveries recorded since last week (ordered date to arrival). Recompute safety stock and
reorder points; note any item whose reorder point moved by more than 20 percent and why.

## 3. Decide what to order

Items at or below reorder point: quantity to reach the reorder point plus the agreed cover, rounded to
minimum or case size. Items that will reach zero before an order placed today could land: at risk,
first on the page, with the days short. Skip discontinued items; flag seasonal ones whose season is
ending.

## 4. Overstock and slow movers

Items with more than the agreed months of cover, and items with no sale in 60 days, with the value tied
up where cost is in the export. A suggestion (pause reorders, a bundle, a markdown) is for a human.

## 5. Build the orders

One purchase order per supplier: lines, quantities, unit price from the price list with its date, the
total. Put each on the task with `hub approval request --kind spend`.

## 6. Write and hand over

Write `reports/YYYY-MM-DD-reorder.md` in the shape of `knowledge/examples/reorder-list.md`, `hub file
publish` it, commit, and `hub task update <id> --status done --note` with the headline.
