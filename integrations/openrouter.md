---
service: openrouter
title: OpenRouter
kind: api
summary: The runner Mac's own metered model key for the Pi harness; stripped from every other bot turn.
access: "The runner injects OPENROUTER_API_KEY into a Pi harness process. Other runtimes still strip it."
credentials:
  - OPENROUTER_API_KEY — in secrets/_shared.env on the owner's Mac; runner/op.py strips it from every turn
declared_as: |
  nothing: a bot never declares or receives this key
writes: never
owner: owner
---

## What it is

A metered model gateway. It is the machine's key, not a bot's: the runner hands it only to a
Pi-harness process (below).

## What data it has

Nothing of the company's beyond the prompts a Pi-harness bot sends; nothing is stored on
OpenRouter's side that a bot would read.

## How a bot uses it

A Pi-harness bot (for example an inbox bot on a low-cost model) uses it: the Pi host copies the machine
key into the `pi` process so OpenRouter can be swapped later by changing `runner/hosts/pi.py`.
`OPENROUTER_API_KEY` remains in `runner/op.py` `SECRET_KEYS` and is stripped from every other
runtime. A bot on Codex, Claude, Gemini, or Grok still uses that subscription.

## Rules

- Do not ask for this key, do not look for it, do not put another metered key in its place.
  Subscriptions first; metered keys are the exception the owner decides.
- The mail service's second reviewer (Grok, a different vendor from the drafting model) runs on
  the Mac's subscription sign-in, not on OpenRouter.

## Recipes

None for bots.

## Gotchas

- None recorded yet.

## Learnings

What bots and people learn about this integration is added with `hub learn openrouter "…"`
and shown under this page; a person folds it into the page over time. The page is the rule.
