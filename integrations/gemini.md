---
service: gemini
title: Gemini API
kind: api
summary: A paid Gemini key for generation (Video Producer), Tico's usage-limit fallback, and the docs-qa profile; a tool, not a system of record.
access: "Google's Gemini API with GEMINI_API_KEY from the bot's environment; no shared connector"
credentials:
  - GEMINI_API_KEY — vault item "Gemini API Key", copied by scripts/vault-sync.sh to video-producer.env and coo.env; the botops bot loads it from the docs-qa credential profile (secrets/docs-qa.env)
declared_as: |
  - service: gemini
    identity: the company's Gemini API key
    can: [use]
    env: GEMINI_API_KEY
    credential_profile: docs-qa        # optional: load only this key from another bot's profile
writes: never
owner: owner
---

## What it is

A metered Google API key with three jobs. A video-producer bot generates with it. Tico (the operations bot)
carries it as the runner's usage-limit fallback: when an Antigravity turn hits
a subscription limit, the runner reruns the same turn on the Gemini CLI with this key, same
model, effort and repository, and reports it as `fallback: gemini-api` (`docs/how-it-works.md`,
"A subscription usage limit"). The BotOps bot loads only this key from the `docs-qa` credential
profile.

The hub itself holds no Gemini key.

## What data it has

None of the company's. It is a model endpoint; what a bot sends it is what it sees.

## How a bot uses it

A bot whose `access:` declares `service: gemini` with `can: [use]` finds `GEMINI_API_KEY` in
its environment and calls the API from its own `software/`. A bot that names
`credential_profile: docs-qa` gets the key from `secrets/docs-qa.env` and nothing else from
that file. The fallback needs no action from the bot: the runner does it and the Runs page
shows it in the Session column.

## Rules

- Generation and the fallback only. Do not use the key to route around a subscription limit for
  other work, and do not copy it into another bot's file; the owner decides which bots carry it.
- Subscriptions first; metered keys are the exception. Report unusual usage on the task.
- Never print the key; never put it in a prompt, a task or a commit.

## Recipes

- Check the fallback is ready as the running job sees it: `scripts/tico status` on the Mac.
- See how often the fallback ran: the Session column under **Runs** says `fallback: gemini-api`,
  and the bot's More tab counts it in *Voice, last 7 days*.

## Gotchas

- The launchd job does not see a shell export; the key has to be in `secrets/coo.env` (from
  `scripts/vault-sync.sh GEMINI_API_KEY`) for the fallback to exist.
- Only when the fallback is missing or also limited does the cloud's 30-minute cooldown apply.

## Learnings

What bots and people learn about this integration is added with `hub learn gemini "…"` and
shown under this page; a person folds it into the page over time. The page is the rule.
