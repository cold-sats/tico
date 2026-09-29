---
service: reddit
title: Reddit and Reddit Ads
kind: browser
summary: Reading Reddit on the owner's account through the company browser (listening, a saved-posts review) and reading the Reddit Ads dashboard; no API credential today.
access: "The Aside browser connector (`$HUB_DIR/connectors/browser.py`) with sites reddit.com and, for a paid-marketing bot, ads.reddit.com; read-only"
credentials:
  - none for the browser path — the owner's session lives in Aside
  - REDDIT_CLIENT_ID — only if a bot uses the Reddit API; Reddit Ads has no API key
declared_as: |
  - service: aside
    can: [read]                         # listening only
    sites: [reddit.com]                 # a paid-marketing bot: [ads.reddit.com]
  - service: reddit
    identity: "the owner's account, signed-in browser"
    can: [read]
    note: "read-only search in the browser; never post or vote; stop on any challenge"
  - service: reddit-ads
    identity: "the company's Reddit Ads account, signed-in browser"
    can: [read]
    note: "read-only at ads.reddit.com; never create, enable, or edit; never turn on audience expansion"
writes: never
owner: owner
---

## What it is

Two things behind one login. **Reddit** itself, read on the owner's signed-in account in the
company browser, by the listening bot only: it sweeps subreddits for topics your company cares about and
mentions of the company, and captures the owner's saved posts as one more source.
**Reddit Ads** (`ads.reddit.com`) is read by a paid-marketing bot for the weekly numbers.
Public Reddit search needs no key, and Reddit Ads has no API key.

## What data it has

Posts, comments, subreddit search results and profiles the account can see; the owner's saved
posts. In Reddit Ads: campaigns, ad groups, ads, spend and results.

## How a bot uses it

```bash
$HUB_DIR/connectors/browser.py repl --as listening "const p = await openTab('https://www.reddit.com/r/<subreddit>/search/?q=<company name>&sort=new'); ..."
$HUB_DIR/connectors/browser.py repl --as paid-marketing "const p = await openTab('https://ads.reddit.com/'); ..."
```

Reads only under `can: [read]`.

## Rules

- Never post, comment, vote, message, follow or join. Public comments are outbound sends and
  the read-only period forbids them (`policies/shared-rules.md`).
- Stop on any login page, challenge or captcha; never log in.
- Reddit Ads: read only. Never create, enable, pause or edit a campaign, ad group or ad; never
  turn on audience expansion. Budget changes are human actions, not bot actions; report the
  weekly numbers and change nothing.

## Recipes

- Listening: one search URL per subreddit and topic, `sort=new`, read the newest posts since
  the last sweep, each search saved with `hub listen save`; findings reach their owners through
  the hub inboxes.
- Weekly paid state: read the Reddit Ads campaign table for this week and last, spend and
  results per campaign, into the same report as Google and Meta.

## Gotchas

- Reddit's new layout loads comments lazily; read after the thread has rendered.
- Old-style URLs (`old.reddit.com`) are outside the declared sites unless listed; stay on
  `reddit.com`.
- Reddit Ads shows spend in the account's timezone; say which day boundary you used.

## Learnings

What bots and people learn about this integration is added with `hub learn reddit "…"` and
shown under this page; a person folds it into the page over time. The page is the rule.
