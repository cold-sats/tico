---
service: meta-ads
title: Meta Ads
kind: api
summary: Reporting on the company's Meta ad account through the Graph API insights endpoint; never a change.
access: "GET on the Graph API v21.0 insights endpoint with META_ACCESS_TOKEN (scope ads_read); no shared connector — a paid-marketing bot's adreport.py is the read-only tool"
credentials:
  - META_ACCESS_TOKEN — vault item "Facebook Meta API Token", copied by scripts/vault-sync.sh into each declaring bot's secrets file (scope ads_read only)
  - META_AD_ACCOUNT_ID — the account id (`act_<number>`), set alongside the token in the same env file
declared_as: |
  - service: meta-ads
    identity: "the company's Meta ad account (act_<number>)"
    can: [read]
    env: META_ACCESS_TOKEN
    note: "ads_read only; also uses META_AD_ACCOUNT_ID. Reporting only, never spend."
writes: approval
owner: owner
aliases: [facebook-ads, meta]
---

## What it is

The Meta (Facebook and Instagram) ad account for the company's campaigns (`act_<number>`). Personal accounts are out of scope. There is no shared connector: the
bot calls the Graph API itself with a token scoped to `ads_read`, and a paid-marketing
bot's `software/adreport.py meta` is the tool, which only issues `GET`.

## What data it has

Campaign, ad set and ad insights: spend, impressions, reach, clicks, CTR, CPM, results, by
date range. Ads Manager (`business.facebook.com`,
`adsmanager.facebook.com`) shows the same in the signed-in browser through Aside, read-only.

## How a bot uses it

```bash
software/adreport.py --check                    # what is connected, and what it unlocks
software/adreport.py meta --days 7              # this week
software/adreport.py meta --days 7 --offset 7   # the prior week
software/adreport.py meta --ads --json          # per-ad rows
```

Plain HTTP:

```bash
curl -s "https://graph.facebook.com/v21.0/$META_AD_ACCOUNT_ID/insights?level=campaign&date_preset=last_7d&fields=campaign_name,spend,impressions,clicks,ctr,actions&access_token=$META_ACCESS_TOKEN"
```

## Rules

- Reporting only. Never change status, budget, audience, bid or creative; never create a
  campaign (`policies/shared-rules.md`, read-only period).
- Meta "Property Managers - Combined" runs at its current $30/day cap; that is accepted.
  Report the weekly numbers and do not escalate them as a HOLD breach.
- A budget change needs a Tico `spend` approval with the exact amount, and the owner makes it.
- In Ads Manager through Aside (`can: [read]`): look, never Edit, Save, Apply, Enable, Pause
  or Create; never log in.
- Never print the token.

## Recipes

- Weekly state of paid: `adreport.py meta --days 7` and `--days 7 --offset 7`, side by side,
  spend and results per campaign.
- Creative audit: `--ads` for the per-ad rows, sorted by impressions, with CTR and frequency.
- A custom pull: `level=adset&time_range={"since":"2026-09-01","until":"2026-09-07"}&fields=adset_name,spend,reach,frequency,actions`.

## Gotchas

- `META_PIXEL_ID`, if set, additionally allows pixel-event checks.
- The bot's secrets file may not carry the token; `adreport.py --check` says
  what is connected before you promise a section.
- `actions` is a list of `{action_type, value}` pairs; pick the conversion you mean
  (`lead`, `schedule`, …) rather than summing them.
- Graph tokens expire; an OAuthException 190 means the token needs replacing in the vault, a
  task for the owner.

## Learnings

What bots and people learn about this integration is added with `hub learn meta-ads "…"` and
shown under this page; a person folds it into the page over time. The page is the rule.
