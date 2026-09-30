"""An inbox bot gets a computer to itself.

Every bot on a computer runs as the same operating-system user, and an inbox bot reads mail with a
Google Workspace key that acts as any mailbox in the company. Any other bot on that computer could
be talked into reading that key, so the server does not put an inbox bot beside another bot. Several
inbox bots may share a computer only when the operator says so: they hold the same key anyway. Where one owner
runs every computer and bot, BotOps offers that and turns it on as the person who asked (`single_owner`).
"""
import json

from .store import Problem, P

KEY = "inbox-shared-runners"


def shared(c):
    row = c.execute("SELECT value_json FROM registry_metadata WHERE key=?", (KEY,)).fetchone()
    return set(json.loads(row[0])) if row else set()


def allow_shared(c, runner_id, allowed):
    ids = shared(c)
    ids.add(runner_id) if allowed else ids.discard(runner_id)
    c.execute("INSERT INTO registry_metadata VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value_json=excluded.value_json",
              (KEY, json.dumps(sorted(ids))))


def single_owner(c):
    """One person runs everything: every computer and every bot that is not archived has the same operator."""
    operators = {r[0] for r in c.execute(
        "SELECT operator FROM runners WHERE revoked_at IS NULL UNION "
        "SELECT bc.operator FROM bot_config bc JOIN bots b ON b.slug=bc.bot WHERE b.state<>'archived'") if r[0]}
    return len(operators) <= 1


def _bots_by_runner(c):
    rows = c.execute("SELECT a.runner_id,a.bot FROM assignments a JOIN bots b ON b.slug=a.bot "
                     "WHERE b.state<>'archived' ORDER BY a.bot").fetchall()
    result = {}
    for row in rows:
        result.setdefault(row["runner_id"], []).append(row["bot"])
    return result


def violations(c, people):
    """Computers that break the rule now: [{runner_id, label, inbox: [...], others: [...], shared: bool}]."""
    ids, found = shared(c), []
    labels = {r["id"]: r["label"] for r in c.execute("SELECT id,label FROM runners WHERE revoked_at IS NULL")}
    for runner_id, bots in _bots_by_runner(c).items():
        if runner_id not in labels:
            continue
        inbox = [b for b in bots if P.inbox_person(b, people)]
        others = [b for b in bots if b not in inbox]
        if inbox and (others or (len(inbox) > 1 and runner_id not in ids)):
            found.append({"runner_id": runner_id, "label": labels[runner_id], "inbox": inbox, "others": others})
    return found


def check(c, bot, runner_id, people):
    """Refuse putting `bot` on `runner_id` when that would mix an inbox bot with another bot."""
    here = [b for b in _bots_by_runner(c).get(runner_id, []) if b != bot]
    mine = bool(P.inbox_person(bot, people))
    inbox = [b for b in here if P.inbox_person(b, people)]
    if mine and (len(here) > len(inbox) or (inbox and runner_id not in shared(c))):
        clash = [b for b in here if b not in inbox] or inbox
        offer = ""
        if len(here) == len(inbox) and single_owner(c):
            offer = (f" Or, since one owner runs everything here, let inbox bots share it: "
                     f"`hub api POST runners/{runner_id}/inbox-sharing '{{\"allowed\": true}}'`.")
        raise Problem("inbox_isolation", f"{bot} reads a mailbox with a key that can open every mailbox in the company, "
                      f"so it cannot share a computer with {', '.join(clash)}. Add a computer for {bot} "
                      f"(Settings > Computers) and place it there." + offer, 409)
    if not mine and inbox:
        raise Problem("inbox_isolation", f"{', '.join(inbox)} reads a mailbox with a key that can open every mailbox in "
                      f"the company, so this computer is kept for it alone. Add a computer for {bot} "
                      f"(Settings > Computers) and place it there.", 409)
