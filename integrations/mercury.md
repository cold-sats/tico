---
service: mercury
title: Mercury
kind: api
summary: The company's bank; a read-only token lets a finance bot pull accounts and transactions for the spend pulse and check-in.
access: "The Mercury API (https://api.mercury.com/api/v1) with a read-only token from the finance bot's env file; no shared connector — the finance bot's playbook is the guard"
credentials:
  - MERCURY_API_TOKEN — vault item "Mercury API Token", copied by scripts/vault-sync.sh to secrets/finance.env
declared_as: |
  - service: mercury
    identity: the company account
    can: [read]
    env: MERCURY_API_TOKEN
    note: read-only token; the owner adds it to secrets/finance.env before this employee goes active
writes: never
owner: owner
---

## What it is

The company's bank account. A finance bot reads it for a weekly spend pulse and a monthly
spend check-in (its playbooks). There is no connector: the bot calls the
API itself with the token in its environment.

## What data it has

Accounts and their balances, and the transactions on them (date, counterparty, amount, status,
category). That is the whole of what a read-only token exposes.

## How a bot uses it

`GET` calls against `https://api.mercury.com/api/v1` with `Authorization: Bearer
$MERCURY_API_TOKEN`: the account list, then the transactions of an account for a date window.
Print totals and counterparties in the report; never the token.

The token must be present in the finance bot's env file (`secrets/<slug>.env`) (from the vault item "Mercury API Token",
`scripts/vault-sync.sh MERCURY_API_TOKEN`) before the finance bot can read anything. Until it is, the
playbook says "needs access" and files a task for `the owner`.

## Rules

- Read only. Never a payment, a transfer, a recipient, a card or a user change; the token
  cannot, and the bot does not ask for one that can.
- Any spend is a `spend` approval with the exact vendor and amount (`policies/approvals.md`).
- Bank data stays in the finance bot's reports and the books; it does not go into Slack or a shared task body beyond totals.

## Recipes

- Weekly spend pulse: transactions for the last 7 days grouped by counterparty, compared with
  the prior week; flag anything new or more than a set threshold above its usual amount.
- Monthly check-in: the month's outflows by category against the books.

## Gotchas

- Transaction status matters: pending and posted both appear; count what the playbook says to.
- If `vault-sync.sh` reports it missing, the vault item
  is empty or absent, which is the owner's fix, not the bot's.

## Learnings

What bots and people learn about this integration is added with `hub learn mercury "…"` and
shown under this page; a person folds it into the page over time. The page is the rule.
