---
service: brex
title: Brex
kind: api
summary: Company cards and budgets; a read-only token lets a finance bot read transactions, cards and budgets.
access: "The Brex API (https://platform.brexapis.com) with a read-only token from the finance bot's env file; no shared connector — the finance bot's playbook is the guard"
credentials:
  - BREX_TOKEN — vault item "Brex Read Only", copied by scripts/vault-sync.sh to secrets/finance.env
declared_as: |
  - service: brex
    identity: the company account
    can: [read]
    env: BREX_TOKEN
writes: never
owner: owner
---

## What it is

The company card and spend-management account. A finance bot reads it alongside Mercury
(`integrations/mercury.md`) for the weekly spend pulse and monthly check-in. There is no
connector: the bot calls the API itself with the token in its environment.

## What data it has

Card transactions (merchant, amount, date, card, memo), the cards and their holders, and the
budgets and their limits.

## How a bot uses it

`GET` calls against `https://platform.brexapis.com` with `Authorization: Bearer $BREX_TOKEN`:
transactions for a window, the card list, the budget list. Results are paginated with a cursor;
follow it. Report totals by merchant and by budget; never print the token.

## Rules

- Read only. Never create, freeze or change a card, a limit or a budget, and never ask for a
  token that can.
- Spend is a `spend` approval with the exact vendor and amount (`policies/approvals.md`);
  reading a budget is not permission to use it.
- Cardholder names stay out of shared task bodies; the books get the detail.

## Recipes

- Weekly pulse: card transactions for the last 7 days by merchant, compared with the prior
  week; anything new or unusual is one line in the report.
- Budget check: each budget's spent-to-date against its limit at month end.

## Gotchas

- Amounts and dates are as Brex returns them; state the timezone when comparing with Mercury.
- If `scripts/vault-sync.sh BREX_TOKEN` reports missing, the vault item is empty or absent —
  the owner's fix, not the bot's.

## Learnings

What bots and people learn about this integration is added with `hub learn brex "…"` and
shown under this page; a person folds it into the page over time. The page is the rule.
