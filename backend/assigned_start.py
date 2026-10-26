"""One recovery wake for a lost assignment; overdue starts remain visible until attempted.

The audit ledger is keyed by the assignment event, not by mutable task.updated. It survives
restarts and does not turn a Lead's profile into an idle task-pulling profile.
"""
import logging
import sqlite3

from . import auto_tasks, hubdb as H, task_privacy as privacy

EVENT = 'task.assignment-rewake'
WAKE_HOURS = 1
ESCALATE_HOURS = 2


def candidates(c, at=None, task_ids=None, recorded=None):
    if task_ids is not None and not task_ids:
        return
    at = at or H.now()
    cutoff = H.shift(at, hours=-WAKE_HOURS)
    scope = f" AND t.id IN ({','.join('?' for _ in task_ids)})" if task_ids else ''
    if recorded is True:
        scope += " AND EXISTS(SELECT 1 FROM events e WHERE e.target=t.id AND e.action='task.assignment-rewake')"
    for row in H._rows(c.execute("SELECT t.* FROM tasks t JOIN bots b ON t.owner='bot:'||b.slug "
                                 "WHERE t.status='open' AND b.state IN ('active','paused','quarantined') AND t.created<=? "
                                 + scope + " ORDER BY t.created,t.id", (cutoff, *(task_ids or ())))):
        assignment = c.execute("SELECT id,ts FROM task_events WHERE task_id=? AND field='owner' "
                               "ORDER BY ts DESC,rowid DESC LIMIT 1", (row['id'],)).fetchone()
        key, since = (assignment['id'], assignment['ts']) if assignment else (row['owner'] + ':' + row['created'], row['created'])
        if since > cutoff:
            continue
        saved = next((H._json(r['detail_json'], {}) for r in c.execute(
            "SELECT detail_json FROM events WHERE target=? AND action=? ORDER BY ts DESC",
            (row['id'], EVENT)) if H._json(r['detail_json'], {}).get('assignment') == key), None)
        # Most reads need only one side of the ledger. Skip the other before wait/provenance checks.
        if recorded is False and saved:
            continue
        if recorded is True and (not saved or saved['rewoken_at'] > H.shift(at, hours=-ESCALATE_HOURS)):
            continue
        if auto_tasks.waiting(c, row, starting=True):
            continue
        # Include folded inputs and next-run carried work, not just the job's original task.
        if any(row['id'] in privacy.attempt_tasks(c, a['id']) for a in c.execute(
                "SELECT id FROM attempts WHERE bot=? AND created>=?", (H.actor_id(row['owner']), since)).fetchall()):
            continue
        yield row, key, since, saved


def due(c, at, limit=50):
    """Read outside the scheduler write lock; each selected row is rechecked in its own transaction."""
    out = []
    for row, _, _, saved in candidates(c, at, recorded=False):
        if not saved and H.bot(c, H.actor_id(row['owner']))['state'] == 'active':
            out.append(row['id'])
            if len(out) >= limit:
                break
    return out


def sweep(c, at=None, task_ids=None):
    at = at or H.now()
    woke = []
    for row, key, since, saved in candidates(c, at, task_ids):
        if saved:
            continue
        if H.bot(c, H.actor_id(row['owner']))['state'] != 'active':
            continue
        # A delivery refusal is also one try, recorded durably; never repeat it every tick.
        c.execute('SAVEPOINT assignment_rewake')
        refusal = None
        try:
            if not c.execute('SELECT 1 FROM conversations WHERE id=?', (row['conversation_id'],)).fetchone():
                raise H.Refused('missing_conversation', 'The assignment has no task conversation.')
            message = H._wake(c, row, row['owner'], 'Assigned, not started: ' + row['title'],
                              {'assignment_rewake': True, 'needs_action': True}, trigger='other')
        except H.Refused as exc:
            c.execute('ROLLBACK TO assignment_rewake')
            message, refusal = None, exc.rule
        except Exception as exc:
            # Storage failures must reach the scheduler's fatal-error isolation. A bad task's
            # delivery gets one recorded try so it cannot starve the next bounded batch.
            code = getattr(exc, 'sqlite_errorcode', 0) & 0xff
            if not c.in_transaction or code in (sqlite3.SQLITE_FULL, sqlite3.SQLITE_IOERR,
                                                sqlite3.SQLITE_CORRUPT, sqlite3.SQLITE_NOTADB,
                                                sqlite3.SQLITE_READONLY):
                raise
            c.execute('ROLLBACK TO assignment_rewake')
            logging.getLogger(__name__).exception('Assignment recovery delivery failed')
            message, refusal = None, 'recovery_error'
        finally:
            if c.in_transaction:
                c.execute('RELEASE assignment_rewake')
        H.event(c, H.KEEPER, EVENT, row['id'], {'assignment': key, 'assigned_at': since,
                                            'rewoken_at': at, 'refusal': refusal or (None if message else 'no_queued_wake')})
        if message:
            woke.append(row['id'])
    return woke


def overdue(c, at=None):
    at = at or H.now()
    for row, _, since, saved in candidates(c, at, recorded=True):
        if saved and saved['rewoken_at'] <= H.shift(at, hours=-ESCALATE_HOURS):
            yield {**row, 'assigned_at': since, 'rewoken_at': saved['rewoken_at'], 'rewake_refusal': saved.get('refusal')}


def manager(c, row):
    config = c.execute('SELECT reports_to FROM bot_config WHERE bot=?', (H.actor_id(row['owner']),)).fetchone()
    target = config['reports_to'] if config else ''
    return target if H.actor_kind(target) else H.bot_actor(target) if target else None


def reason(c, row, settings):
    """The queued job's own fences, even beside another claimable lane; never another task's refusal."""
    from . import execution as E
    from .shared_bots import follow
    from .store import readiness_document
    bot = H.actor_id(row['owner'])
    owner = H.bot(c, bot)
    if owner and owner['state'] != 'active':
        return owner['state']
    config = c.execute(f"SELECT bc.config_json,{E.DRAINING_SQL.replace('a.bot', 'bc.bot')} draining "
                       "FROM bot_config bc WHERE bc.bot=?", (bot,)).fetchone()
    runner = c.execute('SELECT r.* FROM assignments a JOIN runners r ON r.id=a.runner_id '
                       'WHERE a.bot=? AND r.revoked_at IS NULL', (bot,)).fetchone()
    if not runner:
        return 'no_computer'
    if not config:
        return 'config'
    if not runner['last_seen'] or runner['last_seen'] < H.shift(H.now(), minutes=-10):
        return 'computer_offline'
    ready = readiness_document(runner['readiness_json'])
    held_bots, held_lanes = E.claimed_busy(runner['id'])
    why, declared = E.claim_refusal(c, settings, runner, bot, config['config_json'], config['draining'], ready, held_bots)
    if why:
        return why
    followed = follow(c, bot, declared)
    busy = {(r[0], r[1]) for r in c.execute("SELECT bot,lane FROM attempts WHERE state IN ('leased','running')")} | held_lanes
    jobs = c.execute(f"SELECT j.*,{E.unfenced_sql()} free,{E.scoped_sql()} in_scope "
                     "FROM jobs j JOIN messages m ON m.id=j.message_id JOIN conversations cv ON cv.id=m.conversation_id "
                     f"WHERE j.bot=? AND j.state='queued' AND {H.MESSAGE_TASK_SQL}=? ORDER BY j.created,j.id",
                     (bot, row['id'])).fetchall()
    if jobs:
        job = jobs[0]
        return ('scoped' if not job['in_scope'] else 'uncertain' if not job['free'] else
                E.job_refusal(c, job, followed, ready, busy, E.lanes_on(runner), E.roots_on(runner)) or
                ('cooling_off' if E.login_refusal(c, settings, runner['id'], bot, followed, job['id']) else 'not_started'))
    return auto_tasks.refusal(c, row, followed, woken=True) or row.get('rewake_refusal') or 'no_queued_wake'


def description(c, row, settings, why=None):
    why = why or reason(c, row, settings)
    return f"Assigned, not started: {row['title']}. Refusal reason: {why}."
