---
service: hub-sql
title: Hub database (SQL)
kind: sql
summary: Read-only SQL over hub.example.com' own database — tasks, messages, bots, runs, routines, the audit log — with your visibility built in.
access: "`hub sql \"<select>\"` in a turn, `POST /api/v2/sql`, or the SQL page (owner). Every caller sees only what the JSON API would show it."
credentials:
  - none — the turn's HUB_TOKEN, a person's sign-in, or this Mac's runner credential (~/.config/tico/runner.json) outside a turn
declared_as: |
  nothing to declare: every bot and every person on the roster may query
writes: never
owner: owner
---

## What it is

The production SQLite database behind hub.example.com (`/var/lib/tico/hub.sqlite`), readable with one
`SELECT` at a time. The rules are the same ones the JSON API applies (`backend/auth.py`), built
into the connection that runs the query (`backend/sql.py`): each guarded table is replaced by a
view that already carries your visibility, and SQLite's authorizer refuses everything else.
Full reference: [docs/hub-sql.md](../docs/hub-sql.md).

## What data it has

Bots and their live status (`bots`, `bot_config`, `bot_status`), people (`humans`, no email for
bots), conversations and messages, tasks and their history (`tasks`, `task_events`,
`task_delegations`), approvals, the work queue (`jobs`, `attempts`, `attempt_events`, `turns`),
routines (`schedules`, `schedule_occurrences`), the audit log (`events`, `refusals`), notes and
meetings (`meetings`), the company docs mirror (`documents`), and the integration learnings
(`learnings`). `sqlite_master` lists the rest. Timestamps are ISO-8601 UTC text; actors are
`human:<id>` or `bot:<slug>`.

Never readable: `credentials`, `credential_keys`, `credential_grants`, `idempotency`,
`runners`, `enrollments`, `session_epochs`, `settings_changes`, `backup_verified_blobs`, every
`token_hash` column, and other people's private Tico rooms.

## How a bot uses it

```bash
hub sql "SELECT bot, state, focus FROM bot_status"                 # aligned table + "N rows (M ms)"
hub sql "SELECT id, title FROM tasks WHERE owner=:me" --param me=bot:seo
hub sql "SELECT ..." --json            # the API response
hub sql "SELECT ..." --csv             # CSV
hub sql "SELECT ..." --max-rows 50     # ask for fewer rows
hub queries hub-sql queued             # search the query catalog; --id <id> prints one
```

`POST /api/v2/sql` takes `{"sql": "...", "params": [...] | {...}, "max_rows": N}` and answers
`{"columns", "rows", "row_count", "truncated", "ms"}`. Errors come back with SQLite's own
words (`no such column: x`, `access to credentials.id is prohibited`).

## Rules

- One `SELECT`, `WITH` or `EXPLAIN QUERY PLAN` per call. Writes, `PRAGMA`, `ATTACH`,
  transactions, plain `EXPLAIN` and multiple statements are refused.
- 500 rows and 5 seconds per query (the owner: 5,000 and 20). A row-capped result says
  `truncated: true`; a slow one fails with `timeout` — narrow it or add a `LIMIT`.
- Every call is written to `events` as `sql.query` with the statement, the row count, the time
  and any error. Assume someone reads it.
- Read the database before asking a bot a question it already answers.
- A bot sees itself and every non-private bot, its own tasks and delegations, the conversation
  of its turn and its tasks' conversations, its own events and refusals, people without email.
  A refusal is the answer; do not look for another route to the rows.

## Recipes

The catalog (`integrations/queries/hub-sql.yaml`, `hub queries hub-sql`) carries queued work,
open tasks, what is waiting on a person, last turn per bot, routine outcomes, a task's history,
a run's output, refusals by rule and the SQL audit itself. Two to keep in mind:

```sql
-- what is waiting on a person, and for how long
SELECT t.owner, t.title, t.updated, substr(m.body, 1, 100) AS question
FROM tasks t JOIN messages m ON m.conversation_id=t.conversation_id AND m.kind='ask'
WHERE t.status='waiting' ORDER BY t.updated
```

```sql
-- the last turn of every bot, with the week's count and failures
SELECT bot, max(started) AS last_turn, count(*) AS turns,
       sum(exit IS NOT NULL AND exit!='ok') AS failed
FROM turns WHERE started > strftime('%Y-%m-%dT%H:%M:%S', 'now', '-7 days')
GROUP BY bot ORDER BY last_turn DESC
```

## Gotchas

- Compare timestamps as text: `created > strftime('%Y-%m-%dT%H:%M:%S', 'now', '-7 days')`.
- `SELECT * FROM messages` means "the messages you may read", so counts differ by caller.
- Outside a turn, `hub sql` alone falls back to the Mac's runner credential and queries as the
  person who registered the machine; the other `hub` commands still need a turn.
- `json_each` / `json_tree` work on the `*_json` columns; `PRAGMA table_info` does not, use
  `SELECT sql FROM sqlite_master WHERE name='tasks'`.

## Learnings

What bots and people learn about this integration is added with `hub learn hub-sql "…"` and
shown under this page; a person folds it into the page over time. The page is the rule.
