# The Tico API

Everything the Tico web app does, it does through an HTTP API, and the same API is open to your own
software: a web frontend your team builds, a script, another service. This page is the overview;
[custom-frontend.md](custom-frontend.md) is the guide for a frontend team.

## The contract

- **Spec:** [`openapi/v2.json`](openapi/v2.json) in this repository, and `GET /api/v2/openapi.json` on your
  server (OpenAPI 3.1, the same document). The server copy needs a sign-in, like the API; there is no
  public schema, and FastAPI's own `/docs` and `/openapi.json` pages are off.
- **Base:** your server's address, for example `https://tico.example.com`. Every stable route is under `/api/v2/`,
  plus `/auth/login`, `/auth/token` and `/auth/token/revoke` for signing in.
- **Format:** JSON in, JSON out, UTF-8. Timestamps are ISO 8601 in UTC (`2026-09-29T13:50:46.836453Z`).
- **Writes:** every `POST` and `PATCH` carries an `Idempotency-Key` header (1 to 200 characters, a fresh UUID per action). Sending
  the same key and body again returns the first answer instead of doing the work twice, so a retry after a dropped
  connection is safe. The same key with a different body is `409 idempotency_conflict`.
- **Errors:** `{"error": {"code", "detail", "retryable"}}`. See [errors](custom-frontend.md#errors).

## What the spec covers

The operation groups below are generated from the committed spec's tags. After regenerating the spec, run
`python scripts/build_api_docs.py`; `--check` verifies the guide matches it.

<!-- api-tags:start -->
| Tag | What it covers |
|---|---|
| Session | Who is calling, and how a frontend signs in ([guide](custom-frontend.md)). |
| Team | This installation's names and settings. |
| Team chart | Humans and bots, and who reports to whom. |
| Bots | The bots a person can see, and their live status. |
| Conversations | Chats with bots: send, list, and stream replies. |
| Tasks | Work assigned to people and bots. |
| Updates | Daily and weekly updates bots post to people. |
| Needs you | What is waiting on the signed-in person: questions, tasks, approvals. |
| Meetings | Recorded meetings. |
| Files | What a bot creates, revises or delivers, listed on its page ([guide](files.md)). |
| Docs | The team's docs ([guide](docs.md)): internal docs written or imported in Tico, with history and locks; linked docs, which are links; and search across both. |
| Assistant | The signed-in person's own private Assistant chat ([guide](assistant.md)): ask, and confirm what it proposes. |
| Goals | What every person and bot is for ([guide](goals-and-kpis.md)): goals with a colour the Goal Manager works out from their KPIs, unless a person set one; check-ins in the owner's words; proposals the owner confirms. |
| KPIs | Measures that stand on their own: a goal links to them and carries the target. Readings are facts with a period, evidence and a quality, never edited; a correction supersedes the old one. |
| Usage | Estimated model spend per bot ([guide](usage.md)): tokens counted by each run's computer, priced at list price. |
| Health | Whether the installation is working. |
| Tags | Tags, metadata, markdown checklists and reusable templates. |
<!-- api-tags:end -->

Internal developer tutorials: [Listening](listening.md#save-decide-and-resolve) and [Needs you batches](needs-you-batches.md).

## Stable and internal

Tico's own app uses more of the API than the spec lists. The line:

- **Stable.** Operations in `openapi/v2.json`. Within v2 they only grow: a field may be added to an answer, an optional
  field to a request, a new route to the spec. Nothing is removed or renamed, and a request that worked keeps working.
  A breaking change would be a new version (`/api/v3`) with `/api/v2` kept alongside for a release cycle.
- **Internal.** Everything else: the `/api/...` routes without `v2` (the web app's own: `/api/me`, `/api/employees`,
  `/api/meetings`, `/api/status` and others; a custom frontend uses `GET /api/v2/bots/{bot}` and
  `GET /api/v2/bots` where the web app uses `/api/employees`), runner and bot endpoints (`/api/v2/runners`,
  `/jobs`, `/attempts`, `/agents`), settings, access, credentials, tools, market, routines, `/mcp` and
  `/scim`. They change between releases without notice. A route you need that is not in the spec: open an issue to
  have it added to the stable set.
- **Inside answers.** Fields ending in `_json` (`refs_json`, `participants_json`, `acceptance_json`) are storage
  leftovers; read the parsed field beside them (`refs`, `participants`, `acceptance_criteria`). Unlisted fields may
  come and go; a client ignores what it does not know and never fails on an extra field.

The spec describes answers with the fields a frontend relies on (`required`) and leaves the rest open. A test in this
repository checks those against live responses, and another checks that `openapi/v2.json` is what the server
generates; after a change to the API, `python -m backend.openapi_v2` rewrites it.

## Three ways to call it

| From | Credential | Guide |
|---|---|---|
| A browser app on another address | A bearer session from `/auth/token` after the human signs in with your work account | [custom-frontend.md](custom-frontend.md#sign-in-option-b) |
| A browser app served from the same address as Tico | Tico's own session cookie | [custom-frontend.md](custom-frontend.md#same-origin-option-a) |
| A server or script | A personal API token, `Authorization: Bearer tico_pt_...` | [custom-frontend.md](custom-frontend.md#servers-and-scripts-option-c) |

Whatever the credential, the caller is a human on your roster and sees what that human sees.

## Who can see, read and write to a bot

Each bot has three permissions, See, Read and Write, each open to everyone or to chosen humans, groups and bots
([permissions.md](permissions.md)). The routes above honour them for every caller, a personal API token
included:

- `GET /api/v2/bots` and `GET /api/v2/org` return only the bots the caller can **see**, each with
  `access: {"see": true, "read": false, "write": true}` for that caller. `?can=read` or `?can=write` keeps
  only the ones the caller holds that level on. A bot they may only see has no status, computer or queue. Each bot in the
  team chart carries its `reports_to`, `department` and `template`.
- A bot the caller cannot see answers `404`. One they can see but not read, or not write to, answers
  `403 forbidden` with what is missing. A task, update, file or run of a bot they cannot read is left out of
  lists (counts and pages included) and answers `403` when asked for by id.
- `GET /api/v2/bots/{bot}` is one bot: its profile if the caller can see it, its status, queue and goals too if they can
  read it. `GET /api/v2/bots/{bot}/routines` needs Read, and so do `GET /api/v2/bots/{bot}/kpis` and a bot's goals and
  KPIs on the Goals routes ([goals-and-kpis.md](goals-and-kpis.md)); a team goal is visible to everyone.
- `GET /api/v2/bots/{bot}/access` and `PUT /api/v2/bots/{bot}/access` read and set the three audiences, for the
  bot's managers: `{"see": {"everyone": true}, "read": {"teams": ["legal"]}, "write": {"everyone": true}, "revision": 3}`.
  A stale `revision` is `409 version_conflict`.

## Rate limits and size limits

Tico does not rate-limit ordinary calls. What it does enforce: writes are limited to 2 MB (uploads and meeting
imports 20 MB, `413 too_large`), a few actions have a daily budget (`429`), and each open live stream costs the
server a small read every second. [custom-frontend.md](custom-frontend.md#rate-limits) has the guidance.

## Tags

`GET /api/v2/tags` lists tags and templates; `?is_template=true` selects templates and `false`
selects task tags. `POST /api/v2/tags` accepts `key`, optional `label`, `metadata` (an object),
`markdown`, `owner`, `is_template`, and `template_id`. Owner defaults to the caller.
`GET /api/v2/tags/{id}` accepts an id or key and returns `tag`, `editable`, visible `tasks`, and
`next_offset`; `limit` and `offset` page the tasks. `POST /api/v2/tags/{id}` accepts `version`
and optional `label`, `metadata`, `markdown` and `owner` (empty to clear). Metadata updates
replace the object. Keys and template status stay fixed after creation.

`POST /api/v2/tags/{id}/instances` copies a template's label, Markdown and metadata into a tag
with a caller-supplied key. Metadata supplied on creation overrides the template defaults.
Templates cannot be attached to tasks. Create/edit permissions are task movers or the tag owner.
Tag reads are team-wide; the task list keeps the caller's task visibility.

Task `labels` remain a list of keys. Task responses also include `tags` with their display label,
metadata and notes. `GET /api/v2/tasks/labels` preserves `labels` and adds `tags` for those keys.
`task_tags` is the source of truth; the old `labels_json` column is kept for one release but
is no longer read or written. All tag changes are audited in `events`, and task tag changes
keep the `labels` entry in `task_events`. See [Tags and release checklists](using-tico.md#tags-and-release-checklists).

## Task pipelines

`/api/v2/task-types` exposes task types and their ordered steps. Movers create and edit definitions;
unused types can be deleted, and steps with tasks cannot be removed. Task creation and updates
accept `type` and `step`. Answers add `type_id`, `step_id`, `type` and `step` while preserving the
existing status contract. See [Task types and steps](tasks.md) for mapping and update examples.

## Branches

`POST /api/v2/bots/{bot}/copies` (also `/branches`) makes the caller's branch and returns its definition,
`created` and `assignment`. Send `{ "runner_id": "your-computer-id" }`, or `{}` for a planned branch.
The caller must be a human with Read on the original, which must allow branches (`shared: true`).
A selected computer belongs to that human and cannot already run the original or a branch of it.
Repeated requests return the same `<bot>-<person>` bot. Independent copies keep using `/copy`.

`GET /api/v2/bots/{bot}/branches` returns `{original, shared, branches}`; the branch definitions include
`shared_from`, `operator` and `status`. Only branches the caller can read are returned.
Bot definitions expose `shared` and `shared_from`; updates accept `shared` and `session: "bot" | "task"`
with the existing `expected_revision`. A branch accepts only status changes to its definition.
MCP uses `hub_bot_branch(bot, runner_id?)` and `hub_bot_update(slug, shared=)`; CLI uses
`hub bot branch <bot> [--computer C]` and `hub bot update <bot> --shared|--no-shared`.
New tasks and canonical chats to an original route to the caller's active branch when branches are allowed.
Stored keys, room-mode `shared`, independent copy routes and older runner payloads keep their meanings.
