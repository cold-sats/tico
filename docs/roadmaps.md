# Public roadmaps

Roadmaps use tasks, types, labels, comments and parent relations. The Product roadmap type starts
public: Suggested → Exploring → Spec → Approved → Building → Shipped (or Declined). Engineering
starts private and uses the development flow. A type default applies only when a task is created;
existing tasks and tasks moved to another type keep their visibility. Older tasks start private.

In Settings → Tasks, create a label such as `roadmap`. In Public roadmaps, select that label, add
an exact website origin such as `https://acme.example`, and save. Empty labels disables roadmaps.
A public task carrying that label appears through the API. Several labels can be enabled and a
task can appear on several roadmaps. Publication is separate from the existing two-party Private
setting: a two-party private task can never appear publicly. Child tasks are excluded; only their
completion counts are shown.

Tico provides the API and an internal ranking view, not a hosted public roadmap page. Each
installation's host scopes requests to its company, as it does for the internal API; use a different
installation host for another company. No public endpoint enumerates labels.

## Calls from your website

All calls, including reads and command-line calls, require `Origin` from the roadmap allowlist.
Use no credentials. HTTPS origins must match exactly; HTTP is allowed only for localhost. CORS
preflights accept GET, POST, DELETE and Content-Type. This browser policy is not visitor identity:
non-browser callers can supply Origin themselves.

```sh
curl https://tico.acme.example/public/roadmaps/roadmap \
  -H 'Origin: https://acme.example'

curl https://tico.acme.example/public/roadmaps/roadmap/tasks/TASK_ID/requesters \
  -H 'Origin: https://acme.example' -H 'Content-Type: application/json' \
  -d '{"email":"customer@acme.example","organization":"Acme","note":"We need larger exports"}'
```

The add response returns `requester_token` once. Save it privately for that visitor and remove their
request with `DELETE /public/roadmaps/roadmap/tasks/TASK_ID/requesters/TOKEN`. Tokens are random,
stored only as hashes, bound to one task, and unusable after removal. A token can also remove the
request while its task is private. Contact details are unverified and only for manual follow-up.

| Method | Path after `/public/roadmaps/{label}` | Body / result |
| --- | --- | --- |
| GET | (empty) | `tasks`, `next_offset` |
| GET | `/tasks/{id}` | `task`, `comments`, `next_offset` for comments |
| POST | `/suggest` | `title`, `summary`, optional requester details; returns private task `id` and `requester_token` |
| POST | `/tasks/{id}/requesters` | Optional `name`, `email`, `phone`, `other`, `organization`, `note`; returns token and count |
| DELETE | `/tasks/{id}/requesters/{token}` | Removes that requester |
| GET | `/tasks/{id}/comments` | `comments`, `next_offset` |
| POST | `/tasks/{id}/comments` | `text`; returns the public comment |

Lists accept `limit` (up to 100) and `offset`; follow `next_offset` until null. Pages are capped at
256 KB. A task contains only `id`, `title` (public title), `summary` (public summary), public step
name, requester count and `parts: {done, total}`. Public comments contain only id, text, creation
time and `author: Team|Visitor`. Nothing returns requester names, contacts, internal discussions,
attachments, assignees, bot work, labels or child identities. Render public text as text or sanitized
Markdown. Comments allow at most two links and no embedded link/script/iframe HTML.

Suggestions create private Product roadmap tasks at Suggested for the configured Product Manager,
with the label and submitter's request. They queue quietly for the PM's next run and need team
review before publication. Successful suggest, add, remove and comment actions share one limit
per IP per UTC day across every roadmap (default 10, configurable in settings); exhaustion returns
429. Failed writes roll back their charge. The server uses the connection IP, with forwarded IPs
accepted only through the deployment's trusted proxy configuration.

## Internal work

Tasks show Requested by, with external and teammate requesters separately. Contacts, organization,
quotes, source and Important stay internal. Teammate status comes from a verified actor, never from
an email claim. The roadmap ranking view sorts by total requests, external requests, important
requests, organization (alphabetically first nonempty organization), or numeric size.

Use `/api/v2/roadmaps/settings`, `/api/v2/roadmap-tasks`, and `/api/v2/tasks/{id}/requesters`
(GET/POST), `/requesters/{requester_id}` (POST replace), and `/requesters/{requester_id}/delete`
(POST). Internal writes require the usual Idempotency-Key. Requester lists are paged and do not
return tokens. Task updates accept `visibility`, `public_title`, `public_summary`, `size`, and
`approval_id`; type updates accept `default_visibility`. Public title and summary begin as copies
of the internal title/body (summary capped at 8,000 characters) and then stay independent.

A bot proposes exact public changes through `POST /api/v2/tasks/{id}/publication-preview` with
`public_title`, `public_summary`, `visibility`, or `comment`. Request a `publish` approval with its
returned `payload` and task id, wait for the human decision, then pass `approval_id` to the update
or public comment (`public: true`). Edits and replies need a new approval each time. Owners/admins
can relax this in Public roadmaps settings. Moderation uses
`POST /api/v2/tasks/{id}/comments/{comment_id}/moderate` with `action: hide|show|delete`.

These routes also have hub MCP tools; `hub api` reaches every route. `hub task update` supports
publication fields, size and approval id. `waits_on` / `waiting_on` still means blocked on someone;
requesters are independent. Nothing sends automatically; follow-ups require a person's request
and the existing outbound send switch.

The PM gathers requests and comments, researches and drafts a spec, and proposes graduation as an
existing Decide card. After approval, it moves the roadmap task to Approved and files Engineering
children through Head of Engineering. The server moves Approved/Building/Shipped between Building
and Shipped as engineering children open, finish or reopen; removing all children returns Approved.
Terminal done, closed and declined children count as finished. Requesters remain on the roadmap task.
