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

Subtasks can nest to any depth. They inherit the parent's requester, so work delegated by a bot
keeps the original requester's rights. A parent owner can read and move its descendants,
including through the task tools and SQL, without gaining access to unrelated tasks. Moving a task to a new parent moves its whole subtree;
a task cannot become its own ancestor. A parent with unfinished descendants cannot become Done.
A human can still close it to cancel the work. Finishing the last subtask wakes the parent's
owner with “All subtasks done”. Done, Closed and Declined count as finished.

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
counts: `total`, `open`, `done`, `prs_total` and `prs_merged`.

Attach as many PRs as the task needs with `hub task link`. `GET/POST /api/v2/tasks/{id}/links`
list or attach links; `DELETE /api/v2/tasks/{id}/links/{link_id}` removes one. The older POST
with `remove` still works. PR links include repository, number, branch, checks, mergeability,
review state and pending review comments. The task's `pr_state` shows the worst active PR:
Failing, Conflict, Changes requested, Open, then Merged. Closed PRs are excluded; shipped PRs
count as merged. A task becomes Ready only after every attached PR is merged or closed.
Automatic PR moves retain the existing custom-type and legacy product-lane behavior.

GitHub events wake the owner with specific PR items, grouped into one notice within three
minutes. Automatic shipping waits until every merged PR is included in the configured release;
PRs in another repository remain Ready for their release or a human's completion.
