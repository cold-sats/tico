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

## Editing and deleting comments

Whoever wrote a comment, a person or a bot, can change its text or delete it, signed in as
themselves. Nobody else can, the owner included, and neither can the Assistant or BotOps on the
author's behalf. Only comments can be changed. A question, an answer, a notice, an approval or a chat
line in a bot's room that mentions the task cannot.

An edit gets the checks a new comment gets, and the comment is marked as edited; Tico's task view
shows "edited" beside its time. A delete takes the comment off the task. Neither wakes anyone or
sends anything. Both move the task's updated time and add a line to its history, and the audit log
(`events`) keeps the old text.

A deleted comment stays in the database, where the owner can still read it through SQL, but it is
never listed again or handed to a bot. If it started a bot run that has not begun yet, the run is
cancelled. The questions it answered are open again, and the bot it woke loses the delegation that
came with it. An edit is not sent again: a bot that has not read the comment yet reads the new text,
and one that has is not told. A copy already posted to Slack stays there.

```sh
hub task comment-edit <task-id> <comment-id> "Use the August numbers."
hub task comment-delete <task-id> <comment-id>
```

The comment id is the `id` in the task's `comments` (`hub task show`). MCP: `hub_task_comment_edit`
(`id`, `comment_id`, `text`) and `hub_task_comment_delete` (`id`, `comment_id`). The API routes are
in [Task comments](api.md#task-comments).
