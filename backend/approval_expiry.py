"""Approvals and asks nobody will act on leave a person's Needs you.

Run hourly (backend/scheduler.py). New ones leave as it happens (a task's end, a replacing request:
hubdb._set_status and hubdb.approval_request); this sweep catches the rest:

1. An undecided approval older than APPROVAL_STALE_DAYS is withdrawn. The bot is told quietly and may ask again.
2. An undecided approval whose task already ended is withdrawn.
3. An unanswered ask to a person about a task that ended is superseded, wherever it was asked. A done task keeps its
   structured questions: that is how it asks for acceptance of what it delivered (hubdb.supersede_asks).
"""

from . import hubdb as H
from .batch_work import isolated

ENDED = ("done", "closed", "declined")


def sweep(conn, at=None):
    at = at or H.now()
    cutoff = H.shift(at, days=-H.APPROVAL_STALE_DAYS)
    stale, ended = [], []
    marks = ",".join("?" * len(ENDED))
    for row in H._rows(conn.execute(
            "SELECT a.id, a.created, t.status FROM approvals a LEFT JOIN tasks t ON t.id=a.task_id "
            f"WHERE a.decision IS NULL AND (a.created<? OR t.status IN ({marks})) ORDER BY a.created",
            (cutoff, *ENDED))):
        with isolated(conn, "approval_expiry", row["id"]):
            if row["status"] in ENDED:
                if H.approval_withdraw(conn, row["id"], f"Its task was {H.TASK_ENDED[row['status']]}."):
                    ended.append(row["id"])
            elif H.approval_withdraw(conn, row["id"], f"No decision in {H.APPROVAL_STALE_DAYS} days. "
                                                       "Ask again if it is still needed."):
                stale.append(row["id"])
    rows = H._rows(conn.execute(
        f"SELECT m.id, t.status, json_type(m.refs_json,'$.questions') AS questions FROM messages m "
        f"JOIN conversations cv ON cv.id=m.conversation_id JOIN tasks t ON t.id={H.MESSAGE_TASK_SQL} "
        f"WHERE m.kind='ask' AND m.to_actor LIKE 'human:%' AND m.deleted_at IS NULL AND {H.OPEN_ASK_SQL} "
        f"AND t.status IN ({marks})", ENDED))
    asks = [r["id"] for r in rows if not (r["status"] == "done" and r["questions"])]
    if asks:
        conn.executemany("UPDATE messages SET superseded_at=? WHERE id=? AND superseded_at IS NULL",
                         [(at, mid) for mid in asks])
    return {"stale": stale, "ended": ended, "asks": asks}
