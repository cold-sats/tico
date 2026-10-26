"""Descriptive task trigger metadata. This catalog never participates in rule evaluation.

Hard-coded checks and event effects live alongside wake rules in their existing listing;
job metadata is attached to the live routine rows, retaining their schedule and permissions.
"""

# Entries describe the existing hubdb/task creation paths, not independently switchable rules.
BUILTINS = (
    ("dedupe", "created", "Refuse it if an unfinished task (of any type) with the same title already exists between the same people (same parent)."),
    ("ceo_limit", "created", "Limit the CEO Bot to five ordinary items a day (UTC) in one person's Needs you; urgent asks go through."),
    ("review_pr", "created", "Refuse a Review 1 or Review 2 subtask that names no pull request."),
    ("review_duplicate", "created", "Refuse a second open Review 1, Review 2 or QA subtask of the same kind for the same pull request head. Security subtasks are not checked."),
    ("private_default", "created", 'Make it private if the requester\'s or owner\'s "private tasks" default is on.'),
    ("public_text", "created", "Refuse public roadmap text from a bot that no person approved; the bot files it privately and asks for publication."),
    ("ask_check", "created", "Check the title and text for asks a person must answer first; note any problem on the task."),
    ("qa_tag", "created", 'Add the "qa" tag when its changed files need QA (Dev and Engineering types).'),
    ("conversation", "created", 'Open its own conversation for a bot owner, and say "Started task" in the chat it came from.'),
    ("queue", "created", 'Put it at the bottom of its owner\'s queue and of its step (top, if filed with "top").'),
    ("created_wake", "created", 'Wake its owner: "New task from …". A bot\'s own task waits until the turn that filed it ends.'),
    ("human_wait", "created", "If it waits on a person, say so once in the bot's main chat."),
    ("roadmap", "step", "Move the linked Product roadmap item: Building, Ready to ship, Shipped (and back); only Engineering and Dev types linked to a roadmap item."),
    ("questions", "finished", 'Drop its open questions to people (and its subtasks\'), except the requester\'s "is this done?" question.'),
    ("approvals", "finished", "Drop any yes/no approval it was waiting on."),
    ("completion", "finished", "Tell the bot that asked for it: at once if it is waiting on this result (Wakes); otherwise in its next batch of finished tasks (Quiet). Closes it accepted itself, and its own tasks, send nothing."),
)

JOBS = {
    "assigned_tasks": ("open", 'Start assigned tasks on a free computer, up to each bot\'s "Keep N going".'),
    "stall_checks": ("open", "Wake the owner when nothing moves on a task (at most 3 a day); drop queued work the bot can no longer read."),
    "waiting_checks": ("open", "Send a bot task waiting on nothing back to work after 2 hours; turn a bot's plain ask to a person into a small task."),
    "due_reminders": ("open", "Tell a bot its task is due. People get no reminder."),
    "snooze_ends": ("open", "Bring snoozed tasks back on their date."),
    "still_wanted": ("open", "Ask the task's person once whether a task idle for a week is still wanted."),
    "ask_deadlines": ("open", "When a bot question passes its deadline, go ahead on its default answer, or let it expire."),
    "approval_expiry": ("open", "Remove approvals and asks nobody will act on from Needs you."),
    "still_needed": ("open", "Weekday mornings, send questions unanswered for 2 business days back to their bots."),
    "github_sync": ("open", "Catch missed pull request, merge and release notices."),
    "repository_waits": ("open", "Finish tasks waiting on a repository or worktree."),
    "task_manager_report": ("open", "Task Manager: per department, list quiet tasks, overdue asks, review tickets without a PR and merged work whose step did not move."),
    "stall_triage": ("open", "Ask Decide what to do with a quiet task: set a wait, close it, or wake once."),
    "propose_demotions": ("open", "Suggest turning noisy wake rules into notes; changes nothing itself."),
    "routine_timer": ("open", "Start each bot routine (these file tasks). Edit them in Tasks → Routines."),
    "stale_review": ("after", "Suggest what to do with open tasks that look finished or forgotten."),
}

NON_TASK = frozenset(("routine", "schedule", "next_run", "background_done", "*", "digest", "feed", "backlog", "release_now"))


def trigger(event):
    if event in NON_TASK or "." in event:
        return None
    if event in ("task_done", "task_declined", "batch_completion"):
        return "finished"
    if event == "step_entered":
        return "step"
    return "open"


def describe_rule(row):
    return {**row, "task_trigger": trigger(row["event"])}


def builtins():
    return [{"id": "task-setting-" + key, "task_trigger": section, "task_action": words,
             "scope_kind": "builtin", "built_in": True, "enabled": True, "can_change": False,
             "then": "wake" if key == "created_wake" else "note",
             "usage_available": False}
            for key, section, words in BUILTINS]


def describe_job(row):
    if row.get("kind") == "task_rule":
        hours = " or ".join(str(t["hours"]) for t in row.get("triggers", []))
        return {**row, "task_trigger": "after", "task_action":
                f"Close a done task after {hours} hours untouched; skips tasks waiting on a person, snoozed, pinned, "
                "or with an open question or approval; at most 50 a pass."}
    metadata = JOBS.get(row["key"])
    return {**row, "task_trigger": metadata[0] if metadata else None,
            "task_action": metadata[1] if metadata else None}
