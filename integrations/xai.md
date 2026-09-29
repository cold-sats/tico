---
service: xai
title: xAI API
kind: api
summary: A metered xAI (Grok) API key declared by the Video Producer for generation; not in the vault sync today.
access: "The xAI API with XAI_API_KEY from video-producer.env; no shared connector"
credentials:
  - XAI_API_KEY — declared by the Video Producer's access; not in scripts/vault-sync.sh's MAP, so it lives only in secrets/video-producer.env if the owner has put it there
declared_as: |
  - service: xai
    can: [use]
    env: XAI_API_KEY
    note: generation API
writes: never
owner: owner
---

## What it is

A metered key for xAI's models, declared by the Video Producer as a generation API. This is
separate from the Grok Build subscription every Grok worker runs on (`grok`, signed in on the
Mac), which needs no key.

## What data it has

None of the company's. A model endpoint.

## How a bot uses it

The Video Producer declares `service: xai` with `can: [use]` and reads `XAI_API_KEY` from its
environment. The variable is not in `scripts/vault-sync.sh`'s MAP: if the key is absent from
`secrets/video-producer.env`, the bot marks that section "needs access" and files a task for
`the owner` rather than improvising. Adding the vault item and a MAP line is what unlocks it.

## Rules

- Generation only; the public result is publish-gated (`policies/approvals.md`, the read-only
  period). Credits are spend and need a `spend` approval.
- Do not use a metered key to route around a Grok Build usage limit for ordinary bot work;
  subscriptions first.
- Never print the key.

## Recipes

- None recorded yet. Add one with `hub learn xai "…"` when the first generation ships.

## Gotchas

- Grok as the mail service's second reviewer is the subscription, not this key.

## Learnings

What bots and people learn about this integration is added with `hub learn xai "…"` and
shown under this page; a person folds it into the page over time. The page is the rule.
