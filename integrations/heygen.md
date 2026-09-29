---
service: heygen
title: HeyGen
kind: api
summary: Avatar video generation for the Video Producer; a metered key, generation only.
access: "The HeyGen API with HEYGEN_API_KEY from video-producer.env; no shared connector"
credentials:
  - HEYGEN_API_KEY — vault item "Heygen", copied by scripts/vault-sync.sh to secrets/video-producer.env
declared_as: |
  - service: heygen
    can: [use]
    env: HEYGEN_API_KEY
    note: generation API
writes: never
owner: owner
---

## What it is

Avatar and video generation used by the Video Producer. A tool with a metered key; not a
system of record.

## What data it has

The avatars, templates and generated videos under the company's account. Nothing else of the
company's.

## How a bot uses it

The Video Producer declares `service: heygen` with `can: [use]` and calls the API from its own
`software/` with the key in its environment. No other bot carries the key.

## Rules

- Generation only. Every public video is publish-gated: the read-only period and
  `outbound_send: false` hold, and publishing needs a `publish` approval
  (`policies/approvals.md`).
- Buying credits or changing the plan is spend and needs a `spend` approval.
- Never print the key.

## Recipes

- Render from an approved script and an approved voice track; keep the output in the bot's
  working prefix in the bucket and link it from the task for review.

## Gotchas

- Renders are asynchronous and metered per minute of output; poll for completion, do not
  re-submit the same job.

## Learnings

What bots and people learn about this integration is added with `hub learn heygen "…"` and
shown under this page; a person folds it into the page over time. The page is the rule.
