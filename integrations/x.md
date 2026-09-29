---
service: x
title: X (Twitter)
kind: browser
summary: Reading X on the owner's signed-in account through the company browser — listening sweeps and a bookmark review; no API access today.
access: "The Aside browser connector (`$HUB_DIR/connectors/browser.py`) with sites x.com, twitter.com, t.co; read-only"
credentials:
  - none for the browser path — the owner's session lives in Aside
  - X_BEARER_TOKEN — only if a bot uses the recent-search API, which needs a paid X developer tier
declared_as: |
  - service: aside
    can: [read]                         # listening only
    sites: [x.com, twitter.com, t.co]
  - service: x
    identity: "the owner's account, signed-in browser"
    can: [read]
    note: "read-only search in the browser; never post, like, or reply; stop on any challenge"
writes: never
owner: owner
aliases: [twitter]
---

## What it is

X, read on the owner's signed-in account in the company browser (Aside). The listening bot uses it for
sweeps and mentions, and captures the owner's bookmarks daily as one more source (it is the
only bot with this session). There is no API path by default: the recent-search endpoint needs a
paid X developer tier; until the owner adds `X_BEARER_TOKEN` to the vault the browser is the
only door.

## What data it has

Search results, timelines, profiles and threads the owner's account can see; the owner's bookmarks.

## How a bot uses it

```bash
$HUB_DIR/connectors/browser.py repl --as listening "const p = await openTab('https://x.com/search?q=%22<company%20name>%22%20<topic>&f=live'); ..."
$HUB_DIR/connectors/browser.py tabs --as listening
```

Reads only under `can: [read]`; the connector refuses clicks, typing and submits.

## Rules

- Never post, like, reply, follow, DM, quote or repost. Public replies are outbound sends and
  the read-only period forbids them (`policies/shared-rules.md`).
- Stop on any challenge, login page or captcha and say so; never log in.
- Everything read is saved with `hub listen save`; market facts, content ideas and creators reach
  their owners through the hub inboxes (`registry/listening.yaml`).

## Recipes

- Listening sweep: a saved search URL per topic with `f=live`, read the newest posts, keep the
  ones that are new since the last watermark in the bot's `<slug>.data/`.
- Bookmark capture (the listening bot, `playbooks/saved-queue-capture.md`): open `x.com/i/bookmarks` and
  save every item in full with `hub listen save`. Bookmarks are left in place.

## Gotchas

- X renders in an infinite scroll; read what is on screen and scroll in small steps rather
  than expecting a full list.
- Rate limits show as a "something went wrong" page; back off and continue later, do not
  retry in a loop.
- `t.co` links resolve to the real destination; follow them in the read, not by clicking.

## Learnings

What bots and people learn about this integration is added with `hub learn x "…"` and shown
under this page; a person folds it into the page over time. The page is the rule.
