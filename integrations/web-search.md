---
service: web-search
title: Web search and public sources
kind: cli
summary: The model's own web search and the public web — firm sites, filings, news, RSS, public APIs — for research, reading only.
access: "Codex's native web search (the runner passes `--search` for a bot that declares `web-search`), plus plain HTTP reads of public pages and feeds; no key"
credentials:
  - none
declared_as: |
  - service: web-search
    can: [use]
    note: "Codex's native web search: the runner passes --search; no key"
  - service: public-web
    identity: "Unauthenticated public sources"
    can: [read]
    note: "Official bulk sources first; no forms, messages, or account creation."
writes: never
owner: owner
aliases: [web, public-web]
---

## What it is

Two ways to read the public web. A bot that declares `service: web-search` with
`can: [use]` runs with Codex's native search switched on (`--search`), so the model can look
things up as it works. Any bot may also read public pages and feeds over plain HTTP:
company sites, regulatory filings, press releases, Google News RSS, the Hacker News API,
competitor sitemaps and pages. Neither needs a credential.

## What data it has

Whatever is public. Research bots use it; a listening or competitor-monitoring bot reads Google News RSS, the
Hacker News API and competitor sitemaps weekly; a business-development bot reads firm sites and
filings.

## How a bot uses it

```bash
curl -s 'https://news.google.com/rss/search?q=%22<topic>%22+AI&hl=en-US&gl=US&ceid=US:en'
curl -s 'https://hn.algolia.com/api/v1/search_by_date?query=<topic>&tags=story'
curl -s https://example-competitor.com/sitemap.xml
```

With `--search` on, the model searches as part of its turn; cite the URL you read in the
report.

## Rules

- Reading only: no forms, no sign-ups, no account creation, no messages, no comments.
- Official bulk sources first (a government dataset before a scraped table); never infer a
  hidden address, a search volume or actual traffic as fact.
- Public listing pages are for research and image matching only; never message, book or
  contact anyone through them.
- Cite sources with dates in `knowledge/`; never invent a number.
- Anything behind a login is a different integration (Aside) with its own page and grant.

## Recipes

- Weekly competitor snapshot: fetch each sitemap, diff URLs against last week's, read the new
  pages.
- Press check: Google News RSS per company name, newest first, keep items since the last run.

## Gotchas

- RSS and public APIs rate-limit; cache what you fetched in `<slug>.data/`, not in the repo.
- A page that renders only with JavaScript is not readable with curl; that is an Aside job
  if the site is on the bot's `sites:` list, otherwise it is out of reach.
- Search results are not evidence; the page they point at is.

## Learnings

What bots and people learn about this integration is added with `hub learn web-search "…"`
and shown under this page; a person folds it into the page over time. The page is the rule.
