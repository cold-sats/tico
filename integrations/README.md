# Integrations

One page per outside system the company uses, written for a bot about to touch it and for a
person deciding whether it may. Each page says what the system is, what data it holds, the
exact commands a bot runs, the rules (read/write gates, approvals, what never to do), useful
recipes and the gotchas people have already hit. The pages ship with every release, so
hub.example.com serves them (`GET /api/v2/integrations`, the **Integrations** page) and every bot
reads them from its checkout (`$HUB_DIR/integrations/<service>.md`, or `hub integration
<service>`).

Nothing secret goes in here: the names of environment variables and 1Password items are fine,
their values never.

## The page

Every page starts with YAML frontmatter, then six sections in this order, then `## Learnings`.

```yaml
---
service: posthog            # the file name, lower-case, matches `service:` in employee.yaml
title: PostHog
kind: api                   # api | sql | browser | mail | cli  (sql = any database read through `hub db`)
summary: One line for the list.
access: How a bot reaches it (the connector, CLI or API), one line.
credentials:                # env var names and the 1Password item they come from; never values
  - POSTHOG_API_KEY — vault item "the company Posthog Read Only", copied to secrets/_shared.env by scripts/vault-sync.sh
declared_as: |              # the `access:` entry a bot carries in employee.yaml
  - service: posthog
    can: [read]
    env: POSTHOG_API_KEY
writes: never               # never | approval | allowed
owner: owner              # who decides changes to this integration
aliases: [ph]               # optional: other names `hub integration <name>` resolves
---
```

`writes` means: `never` — no bot writes, there is no path for it; `approval` — a write needs a
Tico approval (`policies/approvals.md`) or an explicit per-bot grant from the owner named on the
page; `allowed` — a bot whose `access:` carries the verb may write within the page's rules.

Sections: **What it is** · **What data it has** · **How a bot uses it** (exact commands) ·
**Rules** · **Recipes** · **Gotchas**. Plain sentences, present tense, no history (that goes in
the decision log or the learnings).

## Your company's own pages

This folder is what ships with a release. Your own integrations (a company database, an internal
tool) and their query catalogs belong in your private config, in `<TICO_REGISTRY_DIR>/integrations/`
(or the folder `TICO_INTEGRATIONS_DIR` names): the same page format, layered over these, a page with
the same name replacing ours. `postgres.md`, `mysql.md` and `sqlite.md` here document `hub db`, which
reads a company database read-only; [docs/databases.md](../docs/databases.md) sets it up.

## Queries

`queries/<service>.yaml` is the catalog of useful queries for a `kind: sql` integration: a list
of `{id, title, description, category, tags, database, sql, params}`. `queries/hub-sql.yaml` is
written by hand from `docs/hub-sql.md`. A MongoDB entry has `mongo:` (op, collection, filter or pipeline, with
`{"$param": name}` for values) in place of `sql:`; see `templates/company-config/integrations/queries/atlas.yaml`. `hub queries <service> [term]` searches them; `hub queries <service> --id
<id>` prints one.

## Learnings

Learnings are the log; the page is the rules (`policies/writing.md`, "Rules and the log"). A bot
or a person who learns something reusable about an integration adds it with `hub learn <service>
"<text>"` (or the box on the Integrations page); it is stored in the hub database, shown under
the page, and folded into the page by a person over time. The page wins when they disagree.
