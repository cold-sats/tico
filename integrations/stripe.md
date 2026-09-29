---
service: stripe
title: Stripe
kind: api
summary: Payments; a read-only restricted key lets a finance bot read balance, charges, payouts, invoices and subscriptions.
access: "The Stripe API (https://api.stripe.com/v1) with a read-only restricted key from the finance bot's env file; no shared connector — the finance bot's playbook is the guard"
credentials:
  - STRIPE_API_KEY — vault item "Stripe Read Only", copied by scripts/vault-sync.sh to secrets/finance.env
declared_as: |
  - service: stripe
    identity: the company account
    can: [read]
    env: STRIPE_API_KEY
writes: never
owner: owner
---

## What it is

Where customers pay the company. A finance bot reads it for revenue and payout
figures; if the company's product database is connected (`hub db`), it carries the same customers
and charges from the app's side. There is no connector: the bot calls the
API itself with the restricted key in its environment.

## What data it has

Balance, charges, refunds, payouts, invoices, subscriptions, customers and connected accounts. Customer personal details live here; reports carry counts and
totals, not names or card details.

## How a bot uses it

`GET` calls against `https://api.stripe.com/v1` with the key as the Basic-auth username (or a
Bearer header), for example `GET /v1/balance`, `GET /v1/charges?created[gte]=<unix>&limit=100`,
`GET /v1/payouts`, `GET /v1/invoices`, `GET /v1/subscriptions`. Results are paginated with
`starting_after`; follow them or the totals are short.

Payment errors as they happen are not read from the API: an engineering bot can watch
your payment-error channels in Slack (`integrations/slack.md`).

## Rules

- Read only. The key is restricted to reads; never refund, charge, credit, change a
  subscription, or edit a customer, and never ask for a key that can.
- Customer PII stays in Stripe. Reports say how many and how much, not who.
- Revenue by month for the books also exists as a query on the product database
  (`hub queries <database> revenue`, if you have such a query); say which source a number came from.

## Recipes

- Month's gross and net: sum charges (minus refunds) created in the month, and payouts for the
  same window.
- Active subscriptions by plan: `GET /v1/subscriptions?status=active&limit=100`, grouped by
  `items.data[].price.id`.

## Gotchas

- Amounts are in cents; `created` filters take Unix seconds.
- `limit` caps at 100; page with `starting_after=<last id>`.

## Learnings

What bots and people learn about this integration is added with `hub learn stripe "…"` and
shown under this page; a person folds it into the page over time. The page is the rule.
