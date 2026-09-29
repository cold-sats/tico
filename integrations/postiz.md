---
service: postiz
title: Postiz
kind: api
summary: Social post scheduling for Content & Social; drafts only until the owner opens publishing.
access: "The Postiz API with POSTIZ_API_KEY from content-social.env; no shared connector — the bot's playbook is the guard"
credentials:
  - POSTIZ_API_KEY — vault item "Postiz", copied by scripts/vault-sync.sh to secrets/content-social.env
declared_as: |
  - service: postiz
    identity: the company account
    can: [draft]
    env: POSTIZ_API_KEY
    note: drafts and scheduled drafts only; publishing needs a publish approval and outbound_send
writes: approval
owner: owner
---

## What it is

The tool that schedules and publishes social posts for the company's accounts. Content & Social
prepares posts in it. There is no connector: the bot calls the API itself with the key in its
environment, and its playbook keeps everything a draft.

## What data it has

The connected social accounts, the posts drafted and scheduled under them, and what has been
published. Nothing customer-related.

## How a bot uses it

Content & Social declares `service: postiz` and creates or updates posts through the API as
drafts, attaching the draft to the Tico task for review. Nothing is set to publish.

## Rules

- Drafting and scheduling as drafts only. Nothing publishes while the read-only period and
  `outbound_send: false` hold (`policies/shared-rules.md`); publishing needs a `publish`
  approval naming the exact post (`policies/approvals.md`).
- Every draft passes AI-text detection first (`integrations/pangram.md`) and follows the copy
  the company writing rules.
- The standing HOLDs stay: Show HN is drafted with the owner and never posted.

## Recipes

- Draft a week of posts, one per task, with the copy in the task body and the Postiz draft id
  in the completion note, so the owner reviews once.

## Gotchas

- Postiz's digest emails to the inbox are archived by the mail rules; they are not a signal.
- A scheduled post is a publish the moment its time comes: leave the schedule unset on drafts.

## Learnings

What bots and people learn about this integration is added with `hub learn postiz "…"` and
shown under this page; a person folds it into the page over time. The page is the rule.
