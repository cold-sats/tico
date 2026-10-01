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

## Numbers and the order within a step

A mover can make a custom type **numbered**: a board of tickets, worked through on the board. Its
tickets stay out of their owner's **Needs you** unless one asks that person something, and a declined
one stays out of its requester's. Each task created on a numbered type, or moved onto one, gets the
team's next number: one sequence for the whole team, like one board's ticket numbers,
the highest number yet plus one, starting at 1. A number never changes, even if the task later
moves to another type. Turning numbering on does not number the tasks already on the type. To keep
an imported ticket's number, a mover passes `number` when creating it, or gives it once to a task
that has none; a number another task has is refused (`422 duplicate`). Wherever a task id is
accepted, `#18945` names the task with that number (`%2318945` in a URL; quote it in a shell).
The digits alone are not read as a number, since a cut-short id can look the same.

A task also has a place within its step, `step_rank`, lower first, apart from `rank`, its place in
its owner's queue. A task that enters a step, when it is created or its step, type or status
changes, goes to the end of the step, or to the top when it is created with `top`. The people on
the task and movers set `step_rank` to move it within the step. On the board, a type's columns are
in that order.

## CLI and MCP

```sh
hub task types
hub task create --owner content --title "Draft the campaign" --body "Use the brief." --type Marketing
hub task update <task-id> --step "Legal review"
hub task update <task-id> --status review
hub task update <task-id> --type General
hub task update <task-id> --step ""
hub task type update "Dev ticket" --numbered
hub task create --owner ben --title "(B/F) Fix the account page" --type "Dev ticket" --number 18945
hub task show '#18945'
hub task update '#18945' --step "On deck" --step-rank 2.5
hub task list --type "Dev ticket" --sort step
```

`hub_task_types` lists types and ordered steps. `hub_task_create` and `hub_task_update` accept
`type` and `step`, as ids or names, and `number`; `hub_task_update` also takes `step_rank`, and
`hub_task_list` takes `type`, `step` and `sort`. Movers manage definitions with `hub_task_type_create`,
`hub_task_type_update` and `hub_task_type_delete` (with `numbered`), or `hub task type create|update|delete`.

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
unused type. Create and update accept `numbered`; updates accept `name` and a replacement `steps`
array, retaining existing step ids. All writes use the existing Idempotency-Key contract. Task
create and update accept `type`, `step` and `number`, and update accepts `step_rank`; task answers
include `type_id`, `step_id`, a `type` object, a `step` object (null when unmapped), `number` and
`step_rank`.

`GET /api/v2/tasks` takes `type` and `step` (ids or names; a step name without `type` means that
step in every type), `number`, and `sort=step`: by the step's position, then `step_rank`, then
when the task was created. `GET /api/v2/tasks?type=Dev%20ticket&sort=step` is a board's columns,
in order.

`task_types` and `task_steps` are readable through SQL. Join them to the caller's visible `tasks`
using `tasks.type_id` and `tasks.step_id`; the task visibility rules still apply.
