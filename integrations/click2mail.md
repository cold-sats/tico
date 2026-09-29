---
service: click2mail
title: Click2Mail
kind: api
summary: Postcard mailing for a paid-marketing bot; the bot reads projects, job history and cost, and never submits a job on its own.
access: "The Click2Mail REST API with HTTP Basic auth (CLICK2MAIL_USERNAME and CLICK2MAIL_PASSWORD) from the bot's secrets file, through the bot's own software/adreport.py; no shared connector"
credentials:
  - CLICK2MAIL_USERNAME — vault item "Click2Mail", field username, copied by scripts/vault-sync.sh to the bot's secrets file
  - CLICK2MAIL_PASSWORD — vault item "Click2Mail", field password, same file
declared_as: |
  - service: click2mail
    identity: the company's Click2Mail account
    can: [read]
    env: CLICK2MAIL_USERNAME
    note: HTTP Basic with the paired CLICK2MAIL_PASSWORD; reads only; no document, address-list or job creation, never /submit while the read-only period runs
writes: approval
owner: owner
---

## What it is

The print-and-mail service behind the company's postcards. Postcards stay with the paid-marketing
bot (`policies/shared-rules.md`); Click2Mail is where a mailing becomes a job with a cost.
There is no connector: the bot's `software/adreport.py click2mail` reads with the credentials
in its environment and has no code path that creates anything.

## What data it has

Projects, jobs and their history and status, and the cost of each job. The address lists
behind a mailing are the company's lead data; the tool prints PII-safe history only.

## How a bot uses it

```bash
software/adreport.py --check                 # what is connected, and what it unlocks
software/adreport.py click2mail [--json]     # PII-safe project and job history with cost
```

Both credentials must be in the bot's secrets file (`scripts/vault-sync.sh
CLICK2MAIL_USERNAME`, then `CLICK2MAIL_PASSWORD`). Without them the tool prints labelled
SAMPLE numbers so the report shape can be checked, and never a real number.

## Rules

- Read projects, job history, known-job status and cost only. No document upload, no address
  list, no job creation, and never `/submit` while the read-only period runs.
- A mailing is spend: it needs a `spend` approval with the exact list size and amount
  (`policies/approvals.md`), and then the owner's yes on the read-only period.
- Recipient PII never leaves the lead data; counts go in the report.
- `appSignature` is an optional caller-chosen job label, not a credential; Click2Mail issues no
  separate API key.

## Recipes

- Weekly state of paid: the click2mail section of `adreport.py` beside Google and Meta, with
  postcard cost per known job and outcomes read from Close (`integrations/close-crm.md`,
  counts only).

## Gotchas

- A job in "known" status is not the same as delivered; say which status a count is.
- Sample numbers are obviously fake by design; if a report shows them, the credentials are
  missing — say so, do not clean them up.

## Learnings

What bots and people learn about this integration is added with `hub learn click2mail "…"`
and shown under this page; a person folds it into the page over time. The page is the rule.
