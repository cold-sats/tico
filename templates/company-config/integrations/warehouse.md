---
service: warehouse
title: Acme warehouse database
kind: sql
summary: Acme's reporting PostgreSQL replica (customers, orders, products), read through `hub db warehouse`.
access: "`hub db warehouse \"<select>\"` or `hub db warehouse --query <id>`; read-only, audited."
credentials:
  - DB_WAREHOUSE_URL — read-only connection string, in secrets/_shared.env on the runner computer (or a vault credential granted to the bot)
declared_as: |
  - service: postgres
    identity: read-only role on the reporting replica
    database: warehouse
    can: [read]
    env: DB_WAREHOUSE_URL
writes: never
owner: ana
aliases: [acme-db]
---

## What it is

Acme's reporting replica: PostgreSQL 16, read-only role `tico_readonly`, refreshed continuously from
production. It is the only database a bot may read. The generic rules are in `hub tool show postgres`.

## What data it has

| Table | Columns worth knowing | Notes |
|---|---|---|
| `customers` | `id, name, plan, region, created_at` | `email` and `phone` are personal data: count them, never list them |
| `orders` | `id, customer_id, status, total_cents, placed_at` | `status`: pending, paid, shipped, refunded |
| `order_items` | `order_id, product_id, quantity, unit_cents` | one row per line |
| `products` | `id, sku, name, category, active` | |

## How a bot uses it

```bash
hub tool query-search warehouse revenue                       # find a named query
hub db warehouse --query revenue-by-month --param start=2026-01-01 --param end=2026-07-01
hub db warehouse "SELECT status, count(*) FROM orders WHERE placed_at >= :since GROUP BY 1" --param since=2026-09-01
```

## Rules

- Read-only, always; the replica user cannot write and no bot asks for a writer URL.
- Reports carry counts, ids and labels. Never paste a customer's name, email or phone into a task,
  Slack or a repository.
- Bound every query with a date window and a `LIMIT`.

## Recipes

`revenue-by-month`, `orders-by-status`, `top-products`, `new-customers-by-region` (see
`hub tool query-search warehouse`).

## Gotchas

- Timestamps are UTC; Acme reports in Pacific.
- `orders.total_cents` is cents; divide by 100.0 for dollars.
- `customers.plan` is null for free accounts, not the text `free`.

## Learnings

What bots and people learn about this database is added with `hub tool learn warehouse "..."` and shown
under this page; a person folds it into the page over time. The page is the rule.
