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

Eleven groups of operations, each a tag in the spec:

| Tag | What a frontend builds with it |
|---|---|
| Session | who is signed in, sign-in for a separate frontend, personal API tokens |
| Company | names, version, setup state |
| Org chart | people, bots, who reports to whom |
| Bots | the bots you can see and their live status, models |
| Conversations | chat with a bot: send, list, snapshot, live stream |
| Tasks | list, create, update, comment |
| Updates | the daily and weekly updates bots post |
| Needs you | what waits on the signed-in person: questions, tasks, approvals |
| Meetings | search and read recorded meetings |
| Docs | internal docs with history and locks, linked docs, import, and search across both ([docs.md](docs.md)) |
| Health | liveness and the health checks |

## Stable and internal

Tico's own app uses more of the API than the spec lists. The line:

- **Stable.** Operations in `openapi/v2.json`. Within v2 they only grow: a field may be added to an answer, an optional
  field to a request, a new route to the spec. Nothing is removed or renamed, and a request that worked keeps working.
  A breaking change would be a new version (`/api/v3`) with `/api/v2` kept alongside for a release cycle.
- **Internal.** Everything else: the `/api/...` routes without `v2` (the web app's own: `/api/me`, `/api/employees`,
  `/api/meetings`, `/api/status` and others), runner and bot endpoints (`/api/v2/runners`,
  `/jobs`, `/attempts`, `/agents`), settings, access, credentials, integrations, market, routines, goals, `/mcp` and
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
| A browser app on another address | A bearer session from `/auth/token` after the person signs in with your company account | [custom-frontend.md](custom-frontend.md#sign-in-option-b) |
| A browser app served from the same address as Tico | Tico's own session cookie | [custom-frontend.md](custom-frontend.md#same-origin-option-a) |
| A server or script | A personal API token, `Authorization: Bearer tico_pt_...` | [custom-frontend.md](custom-frontend.md#servers-and-scripts-option-c) |

Whatever the credential, the caller is a person on your roster and sees what that person sees.

## Rate limits and size limits

Tico does not rate-limit ordinary calls. What it does enforce: writes are limited to 2 MB (uploads and meeting
imports 20 MB, `413 too_large`), a few actions have a daily budget (`429`), and each open live stream costs the
server a small read every second. [custom-frontend.md](custom-frontend.md#rate-limits) has the guidance.
