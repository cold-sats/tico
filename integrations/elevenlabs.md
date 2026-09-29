---
service: elevenlabs
title: ElevenLabs
kind: api
summary: Voice generation for the Video Producer; a metered key, generation only.
access: "The ElevenLabs API with ELEVENLABS_API_KEY from video-producer.env; no shared connector"
credentials:
  - ELEVENLABS_API_KEY — vault item "ElevenLabs API Key", copied by scripts/vault-sync.sh to secrets/video-producer.env
declared_as: |
  - service: elevenlabs
    can: [use]
    env: ELEVENLABS_API_KEY
    note: generation API
writes: never
owner: owner
---

## What it is

Text-to-speech and voice generation used by the Video Producer to make voice tracks for
videos. A tool with a metered key; not a system of record.

## What data it has

The voices and generations made under the company's account. Nothing else of the company's.

## How a bot uses it

The Video Producer declares `service: elevenlabs` with `can: [use]` and calls the API from its
own `software/` with the key in its environment. No other bot carries the key.

## Rules

- Generation only. Every public video is publish-gated: the read-only period and
  `outbound_send: false` hold, and publishing needs a `publish` approval
  (`policies/approvals.md`).
- Buying credits or changing the plan is spend and needs a `spend` approval.
- Never print the key.

## Recipes

- Generate one voice track per script draft, keep the audio in the bot's working prefix in the
  bucket (`integrations/hub-storage.md`) and link it from the task.

## Gotchas

- Credits are metered per character; long scripts cost more — draft first, generate once.

## Learnings

What bots and people learn about this integration is added with `hub learn elevenlabs "…"`
and shown under this page; a person folds it into the page over time. The page is the rule.
