---
service: google-ads
title: Google Ads
kind: api
summary: Reporting on the company's Google Ads account with GAQL through searchStream; never a mutate.
access: "The Google Ads API v22 searchStream endpoint with the six GOOGLE_ADS_* values; no shared connector — a paid-marketing bot's adreport.py is the read-only tool"
credentials:
  - GOOGLE_ADS_DEVELOPER_TOKEN — vault item "Google Ads", field "Developer Token"
  - GOOGLE_ADS_CLIENT_ID — vault item "Google Ads", field "OAuth Client ID"
  - GOOGLE_ADS_CLIENT_SECRET — vault item "Google Ads", field "OAuth Client Secret"
  - GOOGLE_ADS_REFRESH_TOKEN — vault item "Google Ads", field "Refresh Token"
  - GOOGLE_ADS_LOGIN_CUSTOMER_ID — vault item "Google Ads", field "MCC Login Customer ID"
  - GOOGLE_ADS_CUSTOMER_ID — vault item "Google Ads", field "the company Customer ID"
  - all six copied by scripts/vault-sync.sh into each declaring bot's secrets file
declared_as: |
  - service: google-ads
    identity: "the company's Google Ads customer account (under its manager account), API"
    can: [read]
    env: GOOGLE_ADS_DEVELOPER_TOKEN
    note: "read-only GAQL; also uses GOOGLE_ADS_CLIENT_ID/_CLIENT_SECRET/_REFRESH_TOKEN/_CUSTOMER_ID/_LOGIN_CUSTOMER_ID. Never a mutate call."
writes: approval
owner: owner
---

## What it is

The company's Google Ads account (a customer id, usually under a manager account, MCC). Bots read
it for the weekly state of paid and creative audits. There is no shared
connector: the bot calls the API itself, and a paid-marketing bot's `software/adreport.py`
is the tool, which has no code path to a mutate.

## What data it has

Campaigns, ad groups, ads, keywords and their metrics (cost, clicks, impressions,
conversions) by date segment. What GAQL cannot
show is read in the signed-in browser at `ads.google.com` through Aside, read-only.

## How a bot uses it

```bash
software/adreport.py --check                      # what is connected, and what it unlocks
software/adreport.py google --days 7              # this week
software/adreport.py google --days 7 --offset 7   # the prior week, for week-over-week
software/adreport.py google --ads --json          # per-ad rows, machine form
```

Plain HTTP: `POST https://googleads.googleapis.com/v22/customers/<customer-id>/googleAds:searchStream`
with headers `Authorization: Bearer <oauth access token from the refresh token>`,
`developer-token: $GOOGLE_ADS_DEVELOPER_TOKEN`, `login-customer-id: $GOOGLE_ADS_LOGIN_CUSTOMER_ID`,
and a body `{"query": "SELECT ..."}`. That is the only read endpoint; the tool refuses anything
else.

## Rules

- Reporting only. Never a mutate call: no change to ads, bids, budgets, campaigns, audiences,
  status or creative (`policies/shared-rules.md`).
- Spending or changing a budget needs a Tico `spend` approval naming the exact vendor and
  amount, and the owner makes the change.
- In the browser (Aside, `ads.google.com`, `can: [read]`): never Edit, Save, Apply, Enable,
  Pause or Create; never log in — a login page means stop and say so.
- Never print a credential; `--check` reports names, never values.

## Recipes

Cost, clicks and conversions per campaign, last seven days:

```sql
SELECT campaign.name, campaign.status, metrics.cost_micros, metrics.clicks,
       metrics.impressions, metrics.conversions
FROM campaign
WHERE segments.date DURING LAST_7_DAYS AND campaign.status != 'REMOVED'
ORDER BY metrics.cost_micros DESC
```

Per-ad performance for a creative audit:

```sql
SELECT ad_group.name, ad_group_ad.ad.id, ad_group_ad.ad.type, ad_group_ad.status,
       metrics.impressions, metrics.clicks, metrics.ctr, metrics.cost_micros
FROM ad_group_ad
WHERE segments.date DURING LAST_30_DAYS
ORDER BY metrics.impressions DESC
```

## Gotchas

- Cost comes back in micros; divide by 1,000,000 for dollars.
- `--offset 7 --days 7` is the prior week; windows are whole PT days, end-exclusive.
- Reporting calls need `login-customer-id` set to the MCC even though the query names the
  child customer.
- The credentials were injected at run time before they were in the local env files; if
  `--check` says something is missing, say "needs access" in the report rather than borrowing
  a key.

## Learnings

What bots and people learn about this integration is added with `hub learn google-ads "…"`
and shown under this page; a person folds it into the page over time. The page is the rule.
