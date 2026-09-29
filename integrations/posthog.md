---
service: posthog
title: PostHog
kind: api
summary: Product analytics for the company's product (funnels, pageviews, attribution and reliability events), read with HogQL.
access: "The PostHog REST API at https://us.posthog.com (or the EU host) with POSTHOG_API_KEY; no shared connector — the bot's own read-only script and playbook are the guard"
credentials:
  - POSTHOG_API_KEY — a read-only personal API key from vault item "PostHog Read Only", copied to secrets/_shared.env by scripts/vault-sync.sh (every bot inherits it)
  - POSTHOG_API_KEY — optionally a write key, copied only to one bot's env file; that bot's employee.yaml must say `write` before it may use it
  - POSTHOG_HOST and POSTHOG_PROJECT_ID come with the key
declared_as: |
  - service: posthog
    identity: "the company's PostHog project"
    can: [read]
    env: POSTHOG_API_KEY
    note: "HogQL SELECT and GET only; never edits a flag, experiment, insight or dashboard."
writes: approval
owner: owner
aliases: [ph]
---

## What it is

The company's product analytics: one PostHog project for the product. There is no shared
connector: a bot calls the API itself with the key in its environment, and its own `software/`
script plus the rules below are what keep it read-only. An analytics bot's
`software/posthog_pull.py` is the model to copy.

The hub's own usage analytics (`docs/observability.md`) can also use PostHog, in a
different project. That one is not this page.

## What data it has

Events with person properties, UTC timestamps. Typical events for a product with a demo or
sign-up funnel:

- A funnel: `demo_page_viewed` -> `demo_scheduler_loaded` -> `demo_slot_selected` -> `demo_booked`,
  plus `created_account`.
- Reliability around a scheduling handoff: timeouts, retries and fallbacks.
- `$pageview` on the marketing and sign-up paths.
- Attribution: `$initial_utm_source`, `$initial_utm_medium`, `$initial_referring_domain`.

Insights, funnels, dashboards, cohorts, feature flags and experiments are readable as they are.

## How a bot uses it

HogQL, one `SELECT` per call, `Authorization: Bearer $POSTHOG_API_KEY`:

```bash
curl -s -X POST "$POSTHOG_HOST/api/projects/$POSTHOG_PROJECT_ID/query/" \
  -H "Authorization: Bearer $POSTHOG_API_KEY" -H 'Content-Type: application/json' \
  -d '{"query": {"kind": "HogQLQuery", "query": "select event, count() from events where timestamp > now() - interval 1 day group by event order by count() desc limit 20"}}'
```

`GET /api/projects/$POSTHOG_PROJECT_ID/insights/`, `/feature_flags/`, `/experiments/` read what exists.

The analytics bot's pull, which other bots should reuse rather than rewrite:

```bash
software/posthog_pull.py --days 1                          # yesterday to now, local-time days
software/posthog_pull.py --since 2026-08-25 --until 2026-09-07
software/posthog_pull.py --dry-run                         # the exact HogQL, no network, fake sample
```

## Rules

- `GET` and HogQL `SELECT` only. Never create or edit a flag, experiment, insight, dashboard,
  cohort or survey (`policies/shared-rules.md`, read-only period). The read-only key cannot;
  a write key may only be used when the owner says so, with a Tico approval for the change.
- If you also read bookings from a scheduling tool (`integrations/calendly.md`), that is the
  source of truth; PostHog is diagnostics. A number that disagrees is a question, not a correction.
- Never invent numbers. A missing key exits with the key name and a task for the owner, not a
  guess. A `--dry-run` sample never reaches a report.
- Never print, log or write the key.

## Recipes

Window bounds are UTC; convert a local-time window before querying and bound every query with
`timestamp >= toDateTime(...)` — an unbounded scan 504s.

Funnel volume per local-time day:

```sql
select toString(toDate(toTimeZone(timestamp, 'America/Los_Angeles'))) as day, event, count() as c
from events
where timestamp >= toDateTime('2026-09-01 07:00:00') and timestamp < toDateTime('2026-09-08 07:00:00')
  and event in ('demo_page_viewed', 'demo_scheduler_loaded', 'demo_slot_selected',
                'demo_booked', 'created_account')
group by day, event order by day, event
```

Where booked demos came from, at person level:

```sql
select event,
       person.properties.$initial_utm_source as utm_source,
       person.properties.$initial_utm_medium as utm_medium,
       person.properties.$initial_referring_domain as referrer,
       count() as c
from events
where timestamp >= toDateTime('2026-09-01 07:00:00') and timestamp < toDateTime('2026-09-08 07:00:00')
  and event in ('demo_booked')
group by event, utm_source, utm_medium, referrer order by c desc limit 100
```

Pageviews on the funnel paths:

```sql
select replaceRegexpOne(properties.$pathname, '/$', '') as path,
       count() as views, uniq(person_id) as people
from events
where timestamp >= toDateTime('2026-09-01 07:00:00') and timestamp < toDateTime('2026-09-08 07:00:00')
  and event = '$pageview'
  and (path like '/demo%' or path like '/get-started%')
group by path order by views desc limit 40
```

## Gotchas

- A null `$initial_utm_*` means PostHog never saw a UTM for that person, not that the demo
  was organic.
- Stored timestamps are UTC; report local-time days with `toTimeZone(timestamp, 'America/Los_Angeles')`.
- A bot with no API key reads PostHog in the signed-in browser; if that needs a login, mark the
  section "needs access" rather than signing in.
- `POSTHOG_API_KEY` names two different keys depending on the bot's env file; only the one bot's env file
  that is allowed to write carries the write key.

## Learnings

What bots and people learn about this integration is added with `hub learn posthog "…"` and
shown under this page; a person folds it into the page over time. The page is the rule.
