---
service: calendly
title: Calendly
kind: api
summary: Booked meetings (demos, calls) read from the sales team's Calendly scheduled events and event types.
access: "The Calendly REST API at https://api.calendly.com with CALENDLY_API_TOKEN; no shared connector — the analytics bot's read-only script is the guard"
credentials:
  - CALENDLY_API_TOKEN — a personal access token for the sales team's Calendly account, in the bot's secrets file; add its vault item to scripts/vault-sync.sh's MAP before relying on a fresh sync
declared_as: |
  - service: calendly
    identity: "the sales team's Calendly account (personal access token)"
    can: [read]
    env: CALENDLY_API_TOKEN
    note: "scheduled_events and event_types only; no users:read. Never creates a webhook or edits an event type."
writes: never
owner: owner
---

## What it is

Calendly is where a prospect books a demo. A confirmed demo booked through Calendly is a
reliable conversion number; every other click or pageview is a diagnostic. There is no shared
connector: the analytics bot calls the API itself with the
token in its environment, through `software/calendly_pull.py`, which only issues `GET`.

## What data it has

Scheduled events (booked demos, with `created_at`, start time, event type, status and
cancellation) and event types for the sales team's user. Nothing else is granted: no
`users:read`, no invitee PII beyond what the events carry.

## How a bot uses it

```bash
software/calendly_pull.py --since 2026-08-25 --until 2026-09-07   # local dates, inclusive
software/calendly_pull.py --days 1                                 # yesterday to now
software/calendly_pull.py --dry-run                                # the request it would make, fake sample
```

Plain HTTP, the two calls the token is for:

```bash
curl -s -H "Authorization: Bearer $CALENDLY_API_TOKEN" \
  "https://api.calendly.com/scheduled_events?user=<user-uri>&count=100&min_start_time=2026-09-01T07:00:00Z"
curl -s -H "Authorization: Bearer $CALENDLY_API_TOKEN" "https://api.calendly.com/event_types?user=<user-uri>"
```

## Rules

- `GET /scheduled_events` and `GET /event_types` only.
- Never create a webhook, never edit an event type, never book or cancel on someone's behalf.
- The rebook URL in any copy is the company's own demo page, never a raw Calendly link.
- Never invent a demo count; the analytics bot owns the baseline. A missing token is a task for the owner,
  not a guess.

## Recipes

- "Demos booked this week": count events by `created_at` in local time, per event type, and list
  cancellations separately.
- Week-over-week: run the pull for the two windows and compare booked counts against your growth target.
- Reconcile with your product analytics booking events when the numbers disagree; Calendly wins.

## Gotchas

- "Demos booked" counts by `created_at` (when the booking happened, local time), not by the event's
  start time.
- The owner's personal booking link (for example a `calendar.app.google` link) is for people who need time with them
  directly; it is not the demo flow and its bookings are not demos.
- Paging is by `page_token` on the response; `count=100` is the maximum per page.

## Learnings

What bots and people learn about this integration is added with `hub learn calendly "…"` and
shown under this page; a person folds it into the page over time. The page is the rule.
