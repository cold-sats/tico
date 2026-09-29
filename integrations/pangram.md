---
service: pangram
title: Pangram
kind: api
summary: AI-written-text detection run on drafts before they are handed over; a signal, not the gate.
access: "The Pangram API with PANGRAM_API_KEY from the bot's own secrets file; no shared connector"
credentials:
  - PANGRAM_API_KEY — in the secrets file of each bot that declares it; add its vault item to your scripts/vault-sync.sh map
declared_as: |
  - service: pangram
    can: [use]
    env: PANGRAM_API_KEY
    note: "AI-text detection on every draft before it is handed over. Key never written down."
writes: never
owner: owner
---

## What it is

A detector that scores text for AI authorship. Bots that produce public or customer-facing
words (content, email-marketing, SEO and paid-marketing bots) run their drafts
through it before handing them over. There is no shared connector; each bot calls the API
with the key in its environment, usually through a small script of its own such as
an email-marketing bot's `software/pangram-check.mjs`.

## What data it has

Nothing of the company's. It answers with a prediction for the text you send (a short label
such as `Human` or `AI` in `prediction_short`, with a score); it keeps no shared state a bot
should read back.

## How a bot uses it

```bash
node software/pangram-check.mjs out/draft.txt        # a bot's checker; prints the verdict
```

A plain call sends the draft text as JSON with the key in the `x-api-key` header and reads
`prediction_short` from the answer. Keep the wrapper in your own `software/`.

## Rules

- It is a signal, not the gate. Human review is the gate for email copy; the writing rules in
  `policies/writing.md` and `docs/mail.md` still apply whatever the score says.
- A bot's copy QA can require `prediction_short === Human`; a draft that
  fails is rewritten, not sent anyway.
- Never write the key down, never print it, never paste a draft plus the key into a task.
- `use` only: the account has no settings a bot touches.

## Recipes

- Check every draft once, at the end, before attaching it to the task; record the verdict in
  one line of the completion note.
- For a long page, check the sections that will be read as prose, not the tables or lists.

## Gotchas

- Short texts score unreliably; a verdict on under a paragraph means little.
- The score is not a reason to add filler or odd phrasing; rewrite for a reader, then check
  again.

## Learnings

What bots and people learn about this integration is added with `hub learn pangram "…"` and
shown under this page; a person folds it into the page over time. The page is the rule.
