---
service: linkedin
title: LinkedIn
kind: browser
summary: Looking people and companies up on LinkedIn through the owner's signed-in profile in the company browser; read-only, no credential, no messages.
access: "The Aside browser connector (`$HUB_DIR/connectors/browser.py`) with sites linkedin.com; read-only"
credentials:
  - none — there is no LinkedIn credential; the owner's session lives in Aside and she is never asked for one
declared_as: |
  - service: aside
    can: [read]
    sites: [linkedin.com]
  - service: linkedin
    identity: "the owner's profile, signed-in browser"
    can: [read]
    note: "read-only research: no connects, messages, InMail, posts, comments, likes, or follows; stop on any captcha"
writes: never
owner: owner
---

## What it is

LinkedIn, read on the owner's signed-in profile in the company browser, by the listening bot only:
it sweeps for topic talk and buying intent, and answers other bots'
lookups (a title, a role at a target firm) by task, saving what it read with `hub listen save`. There is no connector to LinkedIn's API and no credential;
the browser is the only door, and it is read-only.

## What data it has

Profiles, company pages, posts and search results the owner's account can see.

## How a bot uses it

```bash
$HUB_DIR/connectors/browser.py repl --as listening "const p = await openTab('https://www.linkedin.com/search/results/people/?keywords=<role>%20<topic>'); ..."
$HUB_DIR/connectors/browser.py tabs --as listening
```

Reads only under `can: [read]`: open a URL, read the page. The connector refuses clicks,
typing and submits.

## Rules

- Never connect, message, InMail, post, comment, like, follow or endorse. Any of those is an
  outbound action and the read-only period forbids them (`policies/shared-rules.md`).
- Never log in and never ask the owner to; a login page or captcha means stop and say so.
- Looking up a title or a role is fine; do not scrape lists of people into a file. Contact
  details stay where they are.
- LinkedIn is not a place to reach anyone; a draft that needs sending goes through the mail
  service under its gates.

## Recipes

- Confirm a decision-maker before a business-development note: open the company page's People tab, read the
  title, cite the profile URL in the task.
- Listening: a search URL per topic sorted by date, read the newest posts since the last
  watermark.

## Gotchas

- LinkedIn throttles unfamiliar browsing patterns and then shows a challenge; pace reads and
  stop at the first challenge.
- Search result pages are partial without scrolling; read what renders rather than paging
  deep.
- Some profiles show "LinkedIn Member" without a session; that means the session is gone,
  not that the person is hidden.

## Learnings

What bots and people learn about this integration is added with `hub learn linkedin "…"` and
shown under this page; a person folds it into the page over time. The page is the rule.
