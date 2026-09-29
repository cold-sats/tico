---
service: google-search-console
title: Google Search Console
kind: api
summary: Search performance and URL inspection for the company's sites, read-only, through a dedicated SEO service account.
access: "The Search Console API (webmasters v3 and searchconsole v1) with a service-account file, through the SEO bot's software/search-console.py; no shared connector"
credentials:
  - GSC_SERVICE_ACCOUNT — vault item "Google Search Console GSC", field "username", copied by scripts/vault-sync.sh into the SEO bot's env file
  - GSC_SERVICE_ACCOUNT_FILE — the path to the service-account JSON as the SEO bot declares it
declared_as: |
  - service: google-search-console
    identity: "the company's properties explicitly granted to the SEO service account"
    can: [read]
    env: GSC_SERVICE_ACCOUNT_FILE
    note: "Read-only search performance and URL inspection. Do not claim access until sites and query checks pass."
writes: never
owner: owner
aliases: [gsc, search-console]
---

## What it is

Google's report on how the company's sites appear in search: queries, clicks,
impressions, position, and whether a URL is indexed. A dedicated service account for the SEO
bot reads it once each property has been granted to that account. There is no shared
connector; the SEO bot's `software/search-console.py` is the tool, with the read-only scope
`https://www.googleapis.com/auth/webmasters.readonly`.

**Status:** until `sites` lists the properties and a query check returns rows, the bot has no access and
must not claim it. What unlocks it: the owner grants each property to the service account in
Search Console and confirms the credential resolves (`scripts/preflight.sh`).

## What data it has

Per property: search analytics (query, page, country, device, date; clicks, impressions, CTR,
position), the sitemaps submitted, and per-URL index inspection. Properties: each one the owner has granted.

## How a bot uses it

```bash
software/search-console.py sites                              # which properties the account can see
software/search-console.py query --site https://example.com/ --start 2026-08-01 --end 2026-08-31 --dimensions query
software/search-console.py inspect --site https://example.com/ --url https://example.com/pricing
```

Under the hood: `POST https://www.googleapis.com/webmasters/v3/sites/{site}/searchAnalytics/query`
and `GET .../sites`, plus `POST https://searchconsole.googleapis.com/v1/urlInspection/index:inspect`.

## Rules

- Read only: `webmasters.readonly` is the scope, and there is nothing to write anyway. Never
  submit or delete a sitemap, never request indexing.
- Do not infer search volumes or actual traffic beyond what the report says; do not claim a
  property is connected until `sites` shows it and a query returns data.
- The service-account file is a credential: never commit it, never print it, never copy it into
  a task.

## Recipes

- Monthly organic note: top 50 queries by clicks with position, month over month, per property.
- New page: `inspect` the URL after publishing to confirm it is indexed; if not,
  say so and wait, do not request indexing.
- Cannibalisation check: `--dimension page` filtered to one query across properties.

## Gotchas

- Search Console data lags two to three days; the last days of a window are incomplete.
- A property must be granted to the service account's email exactly; a domain property and a
  URL-prefix property are different grants.
- Rows are capped at 25,000 per request; page with `startRow`.

## Learnings

What bots and people learn about this integration is added with `hub learn google-search-console "…"`
and shown under this page; a person folds it into the page over time. The page is the rule.
