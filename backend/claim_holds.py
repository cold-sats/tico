"""A queued run the claim could not start is held with its reason, not retried by every claim.

The claim evaluates each candidate job and prepares the one it hands out (execution.Execution.claim). An error in
either belongs to that job alone: the claim rolls back that job's writes, logs the traceback once, and holds the job
here, so the next claim passes over it. The bot's operator gets one Needs-you item, the job's task a note, and Health a
finding. Releasing the bot (bot_stops.release, POST /api/v2/bots/{bot}/release) queues its held jobs again; one that
fails again is held again.
"""

import logging

from .store import H

log = logging.getLogger(__name__)

REASON = "Couldn't start: an error while preparing this run"


def hold(c, settings, job_id, error):
    """Hold a queued job its claim could not start: the reason, an event, its bot's Needs-you item and a note on its
    task. Quiet when the job is no longer queued and free, as another claim or a person may have moved it."""
    job = c.execute("SELECT j.bot,j.message_id,m.conversation_id FROM jobs j JOIN messages m ON m.id=j.message_id "
                    "WHERE j.id=? AND j.state='queued' AND j.held=0", (job_id,)).fetchone()
    if not job:
        return
    bot = job["bot"]
    c.execute("UPDATE jobs SET held=1,hold_until=NULL,hold_reason=? WHERE id=?", (REASON, job_id))
    H.event(c, H.KEEPER, "job.claim_failed", job_id, {"bot": bot, "error": error})
    item = _needs_you(c, settings, bot)
    c.execute("UPDATE jobs SET hold_task_id=? WHERE id=?", (item, job_id))
    task_id = H.message_task_id(H.message(c, job["message_id"]), H.conversation(c, job["conversation_id"]))
    if task_id:
        _note(c, task_id, bot, job_id)


def _needs_you(c, settings, bot):
    """The bot's one open Needs-you item for its held jobs: the open one is reused, else a new one is filed. None when
    nobody can be asked; the jobs stay held either way."""
    from . import bot_stops
    open_item = c.execute("SELECT hold_task_id FROM jobs WHERE bot=? AND held=1 AND hold_reason=? AND state='queued' "
                          "AND hold_task_id IS NOT NULL LIMIT 1", (bot, REASON)).fetchone()
    if open_item:
        task = H.task(c, open_item["hold_task_id"])
        if task and task["status"] in H.ACTIVE_STATUSES:
            return task["id"]
    name = bot_stops.name_of(c, bot)
    return bot_stops.raise_item(
        c, settings, bot, f"Couldn't start a queued run for {name}",
        f"Tico could not start a queued run for {name}: an error happened while its claim prepared it. The job is "
        "held, and no claim tries it again until the bot is released. The server log has the traceback, and Health "
        f"names the held jobs. Fix the cause, then release {name} (hub bot release {bot}): its held runs queue again, "
        "and one that fails again is held again.")


def _note(c, task_id, bot, job_id):
    from . import bot_stops
    name = bot_stops.name_of(c, bot)
    try:
        H.task_comment(c, H.KEEPER, task_id,
                       f"Tico could not start this run: an error happened while its claim prepared it, so the job is "
                       f"held. No claim tries it again until {name} is released (hub bot release {bot}). The server "
                       f"log has the traceback for job {job_id}.", wake=False)
    except H.Refused:
        log.warning("Could not note the held job %s on task %s", job_id, task_id)


def release(c, actor, bot):
    """Queue the bot's held jobs again and close their Needs-you item. A held job another path cancelled meanwhile is
    freed too, so its item closes with it. Answers how many jobs were freed."""
    from . import bot_stops
    rows = c.execute("SELECT id,hold_task_id FROM jobs WHERE bot=? AND held=1 AND hold_reason=?",
                     (bot, REASON)).fetchall()
    if not rows:
        return 0
    c.execute("UPDATE jobs SET held=0,hold_reason=NULL,hold_task_id=NULL WHERE bot=? AND held=1 AND hold_reason=?",
              (bot, REASON))
    for task_id in sorted({row["hold_task_id"] for row in rows if row["hold_task_id"]}):
        bot_stops.close_item(c, task_id, "Released.")
    H.event(c, actor, "job.claim_released", bot, {"jobs": [row["id"] for row in rows]})
    return len(rows)


def held(c):
    """The bots with jobs held for this reason, one row each: how many, and since when the oldest waits."""
    return [dict(row) for row in c.execute(
        "SELECT bot,count(*) AS jobs,min(created) AS since FROM jobs WHERE held=1 AND hold_reason=? AND state='queued' "
        "GROUP BY bot ORDER BY bot", (REASON,))]
