---
service: close-crm
title: Close CRM
kind: api
summary: The sales CRM — leads, contacts, opportunities, statuses, smart views — read by the marketing and sales bots, written only by the sales-operations and SDR bots within their grants.
access: "The Close REST API at https://api.close.com/api/v1/ with CLOSE_API_KEY (HTTP Basic, the key as username, empty password); no shared connector — the bot's own script and its access note are the guard"
credentials:
  - CLOSE_API_KEY — vault item "Close API", copied by scripts/vault-sync.sh into each declaring bot's secrets file; also in secrets/close-calls.env, read only by the hub runner's transcript sync
declared_as: |
  - service: close-crm
    identity: "the company's Close account"
    can: [read]                 # a sales-ops bot may carry [read, write]; an SDR bot [read, write] for lead imports
    env: CLOSE_API_KEY
    note: "GET /lead/ and /opportunity/ only; ids and labels, no contact PII."
writes: allowed
owner: owner
aliases: [close]
---

## What it is

Close is where the humans on sales work and send from. Bots read it for pipeline numbers and,
for two roles, keep the lead data in order. There is no shared connector: a bot calls the API
itself with the key in its environment. A sales-ops bot's `software/close_api.py` is the
helper to reuse.

## What data it has

Leads (`/lead/`) with custom fields, statuses (`/status/lead/`), owners and notes; contacts on a
lead; opportunities (`/opportunity/`) and their stage changes
(`/activity/status_change/opportunity/`); smart views (saved searches); custom field
definitions (`/custom_field/lead/`). A weekly review can watch one opportunity stage (for example a demo-scheduled stage) and what moves out of it.

## How a bot uses it

```bash
software/close_api.py fields                       # lead custom fields: id, name, type, choices
software/close_api.py statuses                     # lead statuses and pipelines
software/close_api.py views                        # smart views
software/close_api.py get lead/ _limit=5 query='status:Potential'   # any GET, k=v query params
software/close_api.py count 'status:Potential'     # leads matching a Close search query
software/close_api.py window 2026-09-01 2026-09-08 # explicit YYYY-MM-DD bounds; count + timestamp check
```

Plain HTTP, when the helper is not in your repo:

```bash
curl -s -u "$CLOSE_API_KEY:" "https://api.close.com/api/v1/opportunity/?_limit=100&_skip=0"
```

Paging is `_limit` and `_skip`; `query=` takes Close's own search syntax. An analytics bot's
`software/close_pull.py --since --until` counts leads and opportunities created plus stage
transitions for the digest, and `--dry-run` shows what it would fetch.

## Rules

- Read-only for everyone except the two grants below. Never delete, never send, never call.
- A **sales-operations** bot may write lead custom fields, lead status (into DNC is fine; out of
  DNC, Customer or Canceled never), lead owner, notes, smart views and the custom fields it
  creates. Never enrol a lead in a sequence without that rep's yes on the task.
- An **SDR** bot may create eligible leads and contacts from approved lead imports,
  deduplicate and read back. No campaigns, sequence subscriptions, sends, calls, deletes, or
  changes to existing customer or DNC status.
- Analytics and scorecard bots read ids and labels, no contact PII. A paid-marketing bot reads counts
  for mailed leads; recipient PII never leaves Close.
- Cold email stays with the humans on sales, who send from Close. Bots do
  the lists, the copy, the replies and the scorecard, and do not send
  (`policies/shared-rules.md`).
- The hub's `close-calls` job (`runner/close_calls.py`) reads Close call and Notetaker meeting
  activity transcripts and imports their text into **Meetings**. It reads only and never
  downloads Close audio. Calls without an existing Close transcript are revisited but do not
  appear as transcript records. Call Assistant remains an account-level choice; the worker does
  not enable it. See [Meetings](../docs/meetings.md#close).

## Recipes

- Leads created in a local-time window: `close_api.py window 2026-09-01 2026-09-08` (it echoes the UTC
  bounds it sent).
- Pipeline movement for the weekly review: `GET /activity/status_change/opportunity/` with
  `date_created__gte` / `date_created__lt` in UTC, then group by `new_status_label`.
- A rep's working list: `views`, then `get lead/ query='in:"<smart view name>"' _limit=100`.
- A write, from the helper: `from close_api import Close; Close().put(f"lead/{lead_id}/", {"custom.cf_xxx": "A"})`
  — only within the grants above.

## Gotchas

- Close filters in UTC. Convert local-time windows before you send them and echo the bounds you used.
- Rate limits answer 429; back off, do not hammer.
- A status change into DNC is a write with consequences; the reverse is never yours to make.
- Every bot with `read` shares one key; the audit trail in Close shows the key, not the bot,
  so say which bot did what in the task note.

## Learnings

What bots and people learn about this integration is added with `hub learn close-crm "…"` and
shown under this page; a person folds it into the page over time. The page is the rule.
