# Task types and steps

Every task starts on **General**, with the same statuses and behavior as before. To give work a
pipeline such as Marketing, a mover makes a type in **Settings → Types**, adds named steps, and
chooses the status each step means. Types belong to the whole team. General keeps one step for
each standard status.

Choose **Type** when creating a task, or change it in the task modal. A custom type shows a **Step**
dropdown; General shows **Status**. On the board, **Filter → Type** selects that type's steps as
columns. Clear the type to return to the usual board. Finished work appears in the selected type's
Done or Closed steps as well as under Done.

Picking a step sets the task's status. Steps can move in any order. Bots, older runners, GitHub
webhooks and existing scripts can keep setting `status`:

- If the current step has that status, it stays there.
- Otherwise Tico picks the first step with that status, in the type's step order.
- If none matches, the step clears. The task keeps its status, and the UI shows that status until
  someone picks a step.

Changing a task's type preserves its status and finds a matching step in the new type. Use an
empty step to clear just the step. Status permissions, completion notes, closing and reopening
work the same way for step changes. Moving between two steps with the same status changes only
the step, without another completion note or notice. Step changes appear in the task history.

Movers (the owner and humans on the leadership, product or engineering teams) create, rename,
reorder and delete types and steps. Move every task off a step before deleting it, including
finished tasks. Move tasks to another type before deleting the type. Changing an occupied step's
status moves its tasks to that status, using the normal completion and reopening behavior.

A task on a custom type with a linked pull request follows the existing GitHub flow: review when
the PR opens, ready when it merges, and done when the configured release includes it. Each move
uses the mapping above, including clearing the step when the type has no match. General tasks
keep their existing behavior.

## CLI and MCP

```sh
hub task types
hub task create --owner content --title "Draft the campaign" --body "Use the brief." --type Marketing
hub task update <task-id> --step "Legal review"
hub task update <task-id> --status review
hub task update <task-id> --type General
hub task update <task-id> --step ""
```

`hub_task_types` lists types and ordered steps. `hub_task_create` and `hub_task_update` accept
`type` and `step`, as ids or names. Movers manage definitions with `hub_task_type_create`,
`hub_task_type_update` and `hub_task_type_delete`, or `hub task type create|update|delete`.

For example, put this JSON array in `steps.json`:

```json
[{"name":"Draft","status":"open"},{"name":"Legal review","status":"review"}]
```

Then run `hub task type create --name Marketing --steps-file steps.json`. To edit steps, first
read `hub task types Marketing`, keep the ids of retained steps in the JSON array, and run
`hub task type update Marketing --steps-file steps.json`. Array order supplies positions unless
explicit positions are provided. Omitted steps are removed; new steps omit `id`.

## API and SQL

`GET/POST /api/v2/task-types` list and create types. `GET/POST /api/v2/task-types/{id}` read and
update one. `DELETE /api/v2/task-types/{id}`, or `POST /api/v2/task-types/{id}/delete`, deletes an
unused type. Updates accept `name` and a replacement `steps` array, retaining existing step ids.
All writes use the existing Idempotency-Key contract. Task create and update accept `type` and
`step`; task answers include `type_id`, `step_id`, a `type` object and a `step` object (null when
unmapped).

`task_types` and `task_steps` are readable through SQL. Join them to the caller's visible `tasks`
using `tasks.type_id` and `tasks.step_id`; the task visibility rules still apply.

## Subtasks and PRs

Subtasks can nest to any depth. A human-created subtask keeps a human parent's requester for
notices; under a bot-requested parent, the person filing it is its requester.
A bot-created subtask is requested by the filing bot, which receives its completion
notice and may close it. It auto-closes after three quiet days like other bot-requested tasks.
Subtasks never inherit a human's delegation anchor from a bot's request. BotOps acts with the
filing bot's rights when that bot asks it to work on a subtask.

Parent owners can track descendants they can read, without gaining Read on hidden bots.
Only the task's owner or requester, or a human mover, can re-parent it; bots must also own,
request or manage the new parent. Moving or detaching a subtask also requires its current
parent's owner or requester, or a human mover. Moving a task moves its whole subtree,
and cycles are refused.
Bots finish open subtasks before marking a parent Done. Humans can always choose Ready or Done,
or close a parent to cancel work. The keeper accepts completed routine work and old bot deliveries
even when they have open subtasks. Finishing or moving away the last open subtask wakes the
parent's owner with “All subtasks done”, unless that owner made the change.
Closing a parent cancels it; later subtask completion does not wake its owner.
Done, Closed and Declined count as finished. Open descendants under a finished subtask do not
block its parent.

```sh
hub task child <parent-id> --owner engineer --title "Build the service" --body "Use the plan."
hub task tree <task-id>
hub task parent <task-id> <new-parent-id>
hub task parent <task-id> ""
```

The corresponding MCP tools are `hub_task_child_create`, `hub_task_tree` and `hub_task_reparent`.
Task create accepts `parent_id`; task update accepts `parent_id` with the current `version`.
`GET /api/v2/tasks/{id}/tree` returns nested subtasks with `id`, `title`, `status`, `owner`,
`pr_state` and `children`. Task detail and list answers include `children_summary` with descendant
counts: `total`, `open`, `done`, `prs_total` and `prs_merged`, plus `direct_total` and
`direct_done` for direct children. Counts include only visible subtrees. Totals include all
visible descendants; `open` ignores work below finished subtasks. Closed, unmerged PRs are
excluded from the PR totals.

Attach as many PRs as the task needs with `hub task link`. `GET/POST /api/v2/tasks/{id}/links`
list or attach links; `DELETE /api/v2/tasks/{id}/links/{link_id}` removes one. The older POST
with `remove` still works. People who can read a task can add or remove its links. Bots
need task rights; worktree links keep their worktree rules.
PR URLs outside the connected GitHub org are plain links. PR links include repository,
number, branch, checks, mergeability, review state and pending review comments. The task's `pr_state` shows the worst active PR:
Failing, Conflict, Changes requested, Open, then Merged. Closed PRs are excluded; shipped PRs
count as merged. Automatic Ready requires at least one merged PR and every tracked PR
merged or closed. A repository in the connected org is tracked when it is reachable, ticked,
or has received a PR webhook on any task. Its PRs block automatic Ready even before their
first event. Unreachable, unticked repositories with no webhook history do not block it. Removing a PR link
recomputes the automatic status. Abandoning every PR returns a task in Review or Ready
to Doing. Adding a PR keeps a Ready task in Ready. Automatic PR moves retain the existing custom-type and legacy
product-lane behavior and preserve a human's status choice for one hour.

Opening a task returns its last known PR state immediately and schedules a background
refresh for repositories the App can reach. Refreshes are grouped, capped at 20 links and
cached for three minutes; failures back off from five minutes up to one hour. People
can still move tasks without webhooks or a successful refresh.

Failing checks, new conflicts, requests for changes, review comments from others and PRs
closed without merging wake the owner with the specific item, grouped into one notice within
three minutes. Conflicts wake once per head until a known clean result clears the marker.
A new push resets mergeability to Unknown while GitHub recomputes it; label and text edits
keep the last known mergeability. Pending or passing checks and the bot's own comments
do not wake it. Tico recognises the GitHub App identity, configured bot login and PR author.
A head pusher counts as the bot only when their login matches the PR author. Requests for
changes always wake the owner, including requests from those identities.
Automatic shipping waits until every merged PR is included in the configured release;
PRs in another repository remain Ready for their release or a human's completion.

## Files, versions and questions

Attach a file to the task so anyone who can read the task can open it. Uploading the same name
on the same task adds a new version, even when another teammate uploads it. Another task or an
archived file starts a separate file. Older attachments appear as v1 without rewriting existing data.
Each version records who uploaded it, when, its size and type, an optional note (up to 500 characters),
and a question with its answers. Media metadata can be null until processing finishes.

```sh
hub task attach <task-id> report.md --note "Revised introduction" --choices "Approve,Request changes"
hub task comment <task-id> "Choose a draft" --attach draft-a.md --attach draft-b.md --ask ask.json
hub task answers <task-id>
```

`--ask` reads a JSON object from a file; it and `--choices` are alternatives. The shorthand builds
one question (`id: verdict`) with the given options and an Other text answer. MCP tools
`hub_task_attach` and `hub_task_comment` accept `ask`; attach also accepts `note`. Comment's
`attachments` contains references such as `file-id@2`. `hub_task_answers` lists recorded answers.

```json
{"questions":[{"id":"verdict","header":"Review","question":"Is this ready?",
 "options":[{"label":"Approve"},{"label":"Request changes","description":"Say what to change"}],
 "multi":false,"other":true}],"who":null}
```

Questions may be on a comment or a file version. An ask has one to four questions, each with
an id (up to 40 characters), header (30), question (300), and zero to six options. Labels are up
to 60 characters and descriptions up to 200. An option can link to a version using `file: "<id>@<n>"`.
`multi` defaults to false; `other` defaults to true. Question ids and labels must be unique.
Unknown fields are rejected. `who` names a person or bot for Needs you; otherwise the requester
is highlighted. Every open ask counts in the task's `open_asks`, including older unanswered questions.

Anyone who may comment on the task can answer, except the asker. Read permission alone does
not grant comment or answer permission. Answers validate question ids and option labels; Other
text is accepted only when the question allows it. A dismissal closes the ask too. Every answer
is retained, oldest first, as an existing answer message and a readable task comment. The task's
bot wakes with the comment text and an `answer: {...}` block; older Computers still read the text.
The bot decides what to do and whether to move the step. Ask once per version and act on the
answer; attach a new version when the work changes.

The API uses the existing ask/answer protocol (`messages.kind`, `refs.questions`, `refs.target`,
and `refs.answer`); plain questions and text replies keep working. The version's metadata points
to its ask message. These routes use the usual Idempotency-Key contract:

- `POST /api/v2/tasks/{id}/files` accepts the existing `name` plus `text` or `content_base64`, and
  optional `note` and `ask`. The result includes `file_id` and `version`, alongside the existing
  `file` and `link` fields.
- `GET /api/v2/tasks/{id}/files` returns files, including archived files, with versions newest first.
- `PATCH /api/v2/files/{id}/versions/{n}` accepts `note` and `ask`, by the version's uploader.
- `POST /api/v2/tasks/{id}/comments` accepts `text`, `ask`, and version references in `attachments`.
  `GET` lists the comments, including `ask` and `answers` on questions, and `answer` on responses.
- `POST /api/v2/tasks/{id}/answers` accepts `target: {comment: id}` or
  `target: {file: id, version: n}`, `answers: {question_id: [label, ...]}`, optional `other`,
  or `dismiss: true`. Answer every question, using an empty label list for an allowed Other reply.
  `GET` lists the structured answers.
