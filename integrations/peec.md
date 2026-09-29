---
service: peec
title: Peec AI
kind: api
summary: AI-visibility tracking — how the company and its competitors appear in AI engines' answers — read through the Peec MCP server by an SEO bot.
access: "The Peec MCP server (streamable HTTP, https://api.peec.ai/mcp) configured in the SEO bot's runtime; read tools only; no shared connector"
credentials:
  - PEEC_API_KEY — a Peec Personal Access Token, in the SEO bot's secrets file; add it to your scripts/vault-sync.sh map so a rotation is not a hand edit
declared_as: |
  - service: peec
    identity: "the company's Peec project"
    can: [read]
    env: PEEC_API_KEY
    note: "read tools only through the Peec MCP server; never create_/update_/archive_/delete_/assign_ or set_project_profile"
writes: never
owner: owner
---

## What it is

Peec runs a fixed set of prompts through the AI engines every day and records which brands
are mentioned, which URLs are retrieved and cited, and how the brand is described. The company has
one Peec project. The SEO bot reaches it through Peec's
MCP server, which the runtime connects from `.grok/config.toml` (grok) or
`.codex/config.toml` (codex) with the token in `PEEC_API_KEY`. There is no shared connector
and no `software/` wrapper; the tool allow-list below is the guard.

## What data it has

Prompts, topics and tags; models and channels; brand, URL and domain reports (visibility,
share of voice, position, sentiment, citations); the individual chats behind them; the
recommended actions; the project profile. Other domains you own appear as citation
sources inside the one project.

## How a bot uses it

The read tools, and only these: `list_projects`, `list_prompts`, `list_models`,
`list_model_channels`, `list_topics`, `list_tags`, `get_brand_report`, `get_url_report`,
`get_domain_report`, `get_chats_report`, `get_chat`, `get_actions`, `get_project_profile`.

A typical read: `list_prompts` for the tracked questions, `get_brand_report` for the period,
`get_domain_report` for where citations come from, `get_actions` before recommending anything.

## Rules

- Read only. The server also exposes `create_`, `update_`, `archive_`, `delete_`, `assign_`
  tools and `set_project_profile`: not granted, do not call them.
- Secondary domains stay citation sources inside the one project; never a separate
  Peec project for any of them (that is spend, and spend needs an approval).
- Recommendations come from `get_actions`; do not invent SEO advice from the raw numbers.
- Changing the prompt set is not a way to improve visibility: adding or removing prompts
  changes what is measured, not what the engines say. Recommend a new prompt only for a real
  untracked question, and say it changes coverage.

## Recipes

- Monthly visibility note: `get_brand_report` for this and last period, then
  `get_domain_report` for the top cited domains and whether your own domain is among them.
- "Why did we lose a topic": `list_topics`, `get_chats_report` filtered to the topic, `get_chat`
  on a few losses to read what the engine actually cited.
- Page check: `get_url_report` on one of your pages to see whether it is retrieved or
  cited at all.

## Gotchas

- Visibility, share of voice and retrieved percentage are 0–1 ratios (×100 to display);
  sentiment is 0–100; retrieval and citation rates are averages that can exceed 1 — display
  as-is, never ×100.
- The Peec Customer REST API is a different door and rejects this token; use the MCP server.
- IDs (`pr_…`, `to_…`, `tg_…`) are opaque: copy them from a tool result, never reconstruct.

## Learnings

What bots and people learn about this integration is added with `hub learn peec "…"` and
shown under this page; a person folds it into the page over time. The page is the rule.
