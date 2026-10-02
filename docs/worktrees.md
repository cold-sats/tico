# Task worktrees

A task worktree gives a bot a separate branch and folder for its code work. The computer shares one base clone per repository and records each worktree on its task.

During a bot run:

```sh
hub task worktree add org/product
hub task worktree attach tasks/12345678/org__product
```

The commands use the run's current task. Add `--task <id>` to choose another task owned by the same bot. The local MCP tools are `hub_task_worktree_add` and `hub_task_worktree_attach`.

The bot needs write access to the repository. A human who can move tasks can request a worktree through `POST /api/v2/tasks/{id}/worktrees`; the computer creates it on its next idle heartbeat. Creation returns the link, branch and path. Folders are under `<workspace>/tasks/<task-short>/<repository-owner>__<repository-name>`, with branches named `tico/<task-short>-<task-title>`. Creation fetches origin's default branch and runs the repository's setup command. A failed setup leaves the worktree tracked so the bot can fix it and run setup again.

Attach accepts an existing Git worktree inside the team workspace whose base is also there. The command checks its repository and branch. A path-only API attachment is pending until the computer identifies its repository and verifies the bot’s write access. Attached paths must stay outside the base-clone folder `repos`.

The computer reports the branch, commits ahead and behind, changed files, last commit and size with its heartbeat. Health shows disk use by bot and any worktree errors. A worktree missing for a day, or with unpushed commits and no activity for three days, wakes its task's bot once until the condition changes.

Closing or finishing a task removes its worktrees after every attached PR is merged or closed. Archiving a bot also cleans up its worktrees when its PRs are merged or closed. The computer waits until its current bot runs finish. It saves changed files in a commit on `wip/<task-short>` and pushes before removing the worktree. Clean trees also push their branch before removal, preserving unpushed commits. If saving or pushing fails, the folder stays and Health reports the failure. Ignored files that prevent Git from removing a worktree also leave the folder in place.

Reopening a task restores its worktrees on the saved local branch, otherwise the origin branch, otherwise origin's default branch. Setup runs again. Saved work remains on the task's local branch after dirty-tree cleanup. Cleanup credentials cover only the tracked repository within the bot's current write grants; they are never written to disk.

A bot can have up to ten worktrees awaiting cleanup. Adding or restoring a worktree needs at least 5 GB free and at least 10% of the workspace volume free. Finish or close older tasks to free worktrees, and free space on the workspace volume if creation reports low disk. Unselected base clones retain the existing 30-day cleanup; a base with linked worktrees stays until they are removed.

Older computers keep running bots normally. They report worktree state as unknown and creation says “Update this computer to use task worktrees”. A new computer talking to an older server omits the optional heartbeat fields, and the worktree commands say the server needs updating. Update the server first, with the task-link schema, then computers.

The runner confirms worktrees through `PATCH /api/v2/tasks/{id}/links/{link_id}`. Only the registered computer or the owner bot on that computer can confirm a tracked worktree. Heartbeat actions are retried until the computer reports completion.
