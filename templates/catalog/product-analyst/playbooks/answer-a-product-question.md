# Answer a product question

Triggered by a task that asks a question of the data ("how many studios use recurring bookings?",
"do teams that invite an instructor retain better?"). Budget 30 minutes. The outcome is one short answer
with its query and caveats.

---

## 1. Pin the question down

    hub task show <id>

Rewrite it as a measurable question: which users, which action, which period, compared with what. If two
readings are possible, pick the likelier, say so, and ask once with `hub task ask <id>` only if the
answer would differ a lot.

## 2. Check the definitions and the data

Use `knowledge/definitions.md`. If the question needs a new definition, write it there with the date. If
the event does not exist, stop: the answer is a tracking gap, added to `knowledge/tracking-gaps.md`, with
the closest proxy you can measure and how far to trust it.

## 3. Query

`hub db <name> "<select>" --csv --max-rows 5000`, aggregated in the query, never per person. Sanity-check
totals against a known number (signups last week, active studios) before trusting the result.

## 4. Answer

`reports/YYYY-MM-DD-<question>.md`: the answer in one line, a small table, the query in `queries/`, the
period, the definitions, and what would change the answer. Say "correlated with", never "causes", unless
it was an experiment. `hub file publish`, commit, `hub task update <id> --status done --note`.
