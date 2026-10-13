"""Which provider thread a turn continues, and which lane it runs in.

Pure functions shared by the server (backend/execution.py, which hands out work per lane) and the
runner (runner/state.py, which keys its sessions), so the two never disagree about a turn.
"""

# The default provider thread. BotOps isolates jobs by default; other bots can
# opt into the same isolation with session: task.
BOT_THREAD = "bot"

# Every turn that is not keyed on a task: the bot thread and conversation-keyed chat, which share
# the bot's main checkout and so run one at a time.
MAIN_LANE = "main"


def session_key(config, bot, task_id, conversation_id):
    """The provider thread this turn continues. BotOps and bots set to `session: task` get one
    per task, so a review never carries every earlier review into each call; a wake about the
    same task (a stalled nudge, a reconcile, a reply) resumes it. A wake with no task keys on
    its conversation, so a person's follow-up still lands where the first answer was."""
    mode = (config or {}).get("session") or ("task" if bot == "botops" else "bot")
    if mode != "task":
        return BOT_THREAD
    if task_id:
        return "task:" + task_id
    return "conversation:" + conversation_id if conversation_id else BOT_THREAD


def lane(config, bot, task_id, conversation_id):
    """A task-keyed turn has its own session, so it runs in its own lane beside the bot's other
    tasks; everything else shares the main lane."""
    key = session_key(config, bot, task_id, conversation_id)
    return key if key.startswith("task:") else MAIN_LANE
