---
service: upfluence
title: Upfluence
kind: browser
summary: Influencer discovery in the company's Upfluence brand account, read-only, in the bot browser that an influencer bot signs into itself.
access: "The Aside browser connector (`$HUB_DIR/connectors/browser.py`) on upfluence.com / upfluence.co, after the bot's `software/upfluence-login.sh` signs in"
credentials:
  - UPFLUENCE_EMAIL and UPFLUENCE_PASSWORD — in the influencer bot's secrets file (may be `op://vault/item/field` references the runner resolves); used only by the login script, never seen by the model
declared_as: |
  - service: upfluence
    identity: "the company brand account, in the bot browser"
    can: [read]
    env: UPFLUENCE_PASSWORD
    note: "logs itself in through software/upfluence-login.sh; read-only after that: search, profiles, Community, saved lists"
  - service: aside
    can: [read]
    sites: [upfluence.com, upfluence.co]
writes: never
owner: owner
---

## What it is

Upfluence is where an influencer bot finds creators: search, profiles, the Community, and
the saved lists. It is a website, not an API: the bot reads it in the company browser through
the [Aside connector](aside.md). Upfluence is the one exception to "never ask the owner to log in"
(`policies/shared-rules.md`): the bot signs in itself with the credentials in its secrets
file, through `software/upfluence-login.sh`, and asks the owner only when the
script reports a verification code, a captcha or a rejected password.

## What data it has

Creator search with filters, creator profiles and audience data, the Community (creators who
applied), saved lists, and campaign and message history that the bot may look at but not
change.

## How a bot uses it

```bash
software/upfluence-login.sh                         # signs in; the model never sees the values
$HUB_DIR/connectors/browser.py tabs --as influencer                # what is open
$HUB_DIR/connectors/browser.py repl --as influencer --file steps.js   # Playwright-style reads on upfluence.com
```

`repl` under `can: [read]` may open pages and read them; the connector refuses clicks, typing
and submits, so a search is driven by URL and by reading the page, not by filling forms.

## Rules

- Read only: search, profiles, Community, saved lists. Never a campaign, a message to a
  creator, a list edit, an export or a settings change.
- Only the login script handles the credentials; a bot never types a password and never asks
  the owner for one. A verification code, captcha or rejected password is a task for the owner, and
  the run stops there.
- Stay on `upfluence.com` and `upfluence.co`; every other host is refused by the connector.
- Outreach to creators goes through the mail service under its own gates
  (`integrations/mail.md`); nothing is sent from Upfluence.

## Recipes

- Discovery pass: sign in, open a saved search by URL, read the result pages, write the
  shortlist to the task with creator handle, platform, audience size and why.
- Reply check: read replies in the mailbox, not in Upfluence messaging.

## Gotchas

- The session lives in Aside; when a page shows the login form again the script must run
  again, and if it reports a challenge, stop.
- Upfluence pages load results lazily; read after the list has rendered, not on navigation.

## Learnings

What bots and people learn about this integration is added with `hub learn upfluence "…"`
and shown under this page; a person folds it into the page over time. The page is the rule.
