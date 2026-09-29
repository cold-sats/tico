---
service: brightdata
title: Bright Data
kind: api
summary: Web data collection for lead research; metered, research and image matching only.
access: "The Bright Data API with BRIGHTDATA_API_KEY and BRIGHTDATA_TOKEN from the bot's secrets file; no shared connector — the bot's own code and these rules are the guard"
credentials:
  - BRIGHTDATA_API_KEY — vault item "Bright Data" (an item name containing `@` must be referenced by its item id in scripts/vault-sync.sh), copied to the bot's secrets file
  - BRIGHTDATA_TOKEN — a second vault item, same file
declared_as: |
  - service: brightdata
    can: [read]
    env: BRIGHTDATA_API_KEY
writes: never
owner: owner
---

## What it is

A web-data platform (proxies and data collectors) a research bot uses to fetch public pages,
for research and image matching. Metered.

## What data it has

Whatever public pages it is pointed at; nothing of the company's own.

## How a bot uses it

A bot with both variables in its environment calls the API from its own code. Official
bulk sources come first; Bright Data is for what they do not cover.

## Rules

- Research and image matching only. Never message, book, create an account, submit a form, or
  infer a hidden address as fact.
- Metered by bandwidth and request: budget every run, cache fetched pages, never loop
  unbounded over a list.
- Collected pages stay in the bot's own data; nothing is republished.

## Recipes

- Fetch each listing page once, keep the parsed fields and image hashes beside the record, and
  match against the cache on later runs.

## Gotchas

- Two credentials, two vault items; `scripts/vault-sync.sh` can name the first by item id. If one
  is missing, `--check`-style output should say which before any collection starts.

## Learnings

What bots and people learn about this integration is added with `hub learn brightdata "…"`
and shown under this page; a person folds it into the page over time. The page is the rule.
