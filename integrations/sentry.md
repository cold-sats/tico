---
service: sentry
title: Sentry
kind: api
summary: Read unresolved issues and their latest events across the company's product projects; nothing is ever resolved, assigned or commented from a bot.
access: "The Sentry REST API (https://sentry.io/api/0) with a Bearer token from the bot's environment; no shared connector — the bot's own script and its playbook are the guard"
credentials:
  - SENTRY_TOKEN — a read-only Sentry auth token, vault item "Sentry", copied by scripts/vault-sync.sh to each declaring bot's env file
declared_as: |
  - service: sentry
    identity: the company's Sentry organization (name its projects)
    can: [read]
    env: SENTRY_TOKEN
    note: read-only, GET only; never resolves, ignores, assigns, comments on, merges or deletes an issue
writes: never
owner: owner
---

## What it is

Error tracking for the company's products. One Sentry organization with a project per app
(for example a web app, a mobile app and a marketing site). One token reaches all of them; a
bug-triage bot and an engineering bot can each ask it a different question. There is no
connector: the bot calls the API itself with the token in its environment, and its own script is
what keeps it read-only.

The hub's own error reporting (`TICO_SENTRY_DSN`, `docs/observability.md`) is a separate
Sentry setup and not this integration.

## What data it has

Unresolved issues per project (title, short id such as `WEB-79`, count, first and last seen,
level), each issue's latest event with its stack frames, and the project list the token can
reach. No customer data beyond what an error payload carries.

## How a bot uses it

A bug-triage bot's `software/sentry-digest.py` is the model: it discovers the org and every project
each `SENTRY_TOKEN*` in the environment can reach, lists unresolved issues for a window and
prints a markdown digest. Its watermark (issues already reported, and the size each spike was
reported at) lives in the bot's data directory and is never committed.

```bash
software/sentry-digest.py                     # last 24h, only what has not been reported
software/sentry-digest.py --since 48h         # a wider window
software/sentry-digest.py --all               # ignore the watermark, report everything
software/sentry-digest.py --project web    # one project; repeatable
software/sentry-digest.py --no-mark           # read without advancing the watermark
software/sentry-digest.py --json              # machine form
software/sentry-digest.py --issue WEB-79 --events   # one issue, latest event, stack frames
```

The endpoints behind it, all `GET` with `Authorization: Bearer $SENTRY_TOKEN`:

```text
/projects/{org}/{project}/issues/         unresolved issues; paginated by the Link header
/issues/{id}/                             one issue by numeric id
/issues/{id}/events/latest/               its latest event, with stack frames
/organizations/{org}/shortids/{SHORTID}/  resolve a short id like WEB-79 to the numeric id
```

An engineering bot can read the same token for post-deploy regressions and also watch your Sentry alerts channel in
Slack (`integrations/slack.md`).

## Rules

- `GET` only. Never resolve, ignore, assign, comment on, merge, delete or bookmark an issue,
  never change an alert rule or a project setting. Sentry stays exactly as it was found.
- A bug-triage bot prepares fix PRs from a branch on the affected repository; the owner merges; never push to
  the default branch (`integrations/github.md`).
- The token is a secret: never print it, never put it in a task or a report.
- A bot that needs a project the token cannot reach files a task for `the owner` rather than
  borrowing another credential.

## Recipes

- Yesterday's new and spiking issues for one project, without moving the watermark:
  `software/sentry-digest.py --project web --since 24h --no-mark`
- One issue in detail before opening a fix PR: `software/sentry-digest.py --issue WEB-79 --events`
- A numeric id goes straight to `/issues/<id>/`; a short id is looked up per org through
  `/organizations/<org>/shortids/<SHORTID>/` first.

## Gotchas

- One token serves every project it can reach. `sentry-digest.py` reports which token reached which project.
- Issue lists are paginated; follow the `Link` header or the digest under-counts.
- A spike reported once is not reported again until it grows; use `--all` when a person asks
  for the whole picture.

## Learnings

What bots and people learn about this integration is added with `hub learn sentry "…"` and
shown under this page; a person folds it into the page over time. The page is the rule.
