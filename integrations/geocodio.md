---
service: geocodio
title: Geocodio
kind: api
summary: Geocoding and address parsing for lead research; a metered key, research only.
access: "The Geocodio API with GEOCODIO_API_KEY from the bot's secrets file; no shared connector — the bot's own code and these rules are the guard"
credentials:
  - GEOCODIO_API_KEY — vault item "Geocod.io API Key", copied by scripts/vault-sync.sh to the bot's secrets file
declared_as: |
  - service: geocodio
    can: [read]
    env: GEOCODIO_API_KEY
writes: never
owner: owner
---

## What it is

Forward and reverse geocoding (address to coordinates and back, with parsed components and
optional appends such as census data) used by research bots to normalise and place addresses.

## What data it has

Public address and location data. Nothing of the company's own.

## How a bot uses it

A bot with the key in its environment calls the API from its own code, in batches.

## Rules

- Research and matching only. Never infer a hidden address as fact from a geocode; a
  coordinate is not a confirmed location.
- Metered: batch requests, cache results beside the record, never loop unbounded.
- Address data stays in the bot's own data store.

## Recipes

- Geocode a list once with the batch endpoint, keep the parsed components, and reuse them for
  every later match.

## Gotchas

- Accuracy comes back with each result; treat low-accuracy matches as unknown, not as the
  answer.

## Learnings

What bots and people learn about this integration is added with `hub learn geocodio "…"` and
shown under this page; a person folds it into the page over time. The page is the rule.
