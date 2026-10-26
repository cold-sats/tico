"""One recovery wake for a lost assignment; overdue starts remain visible until attempted.

The audit ledger is keyed by the assignment event, not by mutable task.updated. It survives
restarts and does not turn a Lead's profile into an idle task-pulling profile.
"""
from . import auto_tasks, hubdb as H, task_privacy as privacy

EVENT = 'task.assignment-rewake'
WAKE_HOURS = 1
ESCALATE_HOURS = 2


def candidates(c, at=None):
    at = at or H.now()
    cutoff = H.shift(at, hours=-WAKE_HOURS)
    for row in H._rows(c.execute("SELECT t.* FROM tasks t JOIN bots b ON t.owner='bot:'||b.slug "
                                 "WHERE t.status='open' AND b.state IN ('active','paused','quarantined') AND t.created<=? "
                                 "ORDER BY t.created,t.id", (cutoff,))):
        if auto_tasks.waiting(c, row, starting=True):
            continue
        assignment = c.execute("SELECT id,ts FROM task_events WHERE task_id=? AND field='owner' "
                               "ORDER BY ts DESC,rowid DESC LIMIT 1", (row['id'],)).fetchone()
        key, since = (assignment['id'], assignment['ts']) if assignment else (row['owner'] + ':' + row['created'], row['created'])
        if since > cutoff:
            continue
        # Include folded inputs and next-run carried work, not just the job's original task.
        if any(row['id'] in privacy.attempt_tasks(c, a['id']) for a in c.execute(
                "SELECT id FROM attempts WHERE bot=? AND created>=?", (H.actor_id(row['owner']), since)).fetchall()):
            continue
        saved = next((H._json(r['detail_json'], {}) for r in c.execute(
            "SELECT detail_json FROM events WHERE target=? AND action=? ORDER BY ts DESC",
            (row['id'], EVENT)) if H._json(r['detail_json'], {}).get('assignment') == key), None)
        yield row, key, since, saved


def sweep(c, at=None):
    at = at or H.now()
    woke = []
    for row, key, since, saved in candidates(c, at):
        if saved:
            continue
        if H.bot(c, H.actor_id(row['owner']))['state'] != 'active':
            continue
        # A delivery refusal is also one try, recorded durably; never repeat it every tick.
        c.execute('SAVEPOINT assignment_rewake')
        refusal = None
        try:
            message = H._wake(c, row, row['owner'], 'Assigned, not started: ' + row['title'],
                              {'assignment_rewake': True, 'needs_action': True}, trigger='other')
        except H.Refused as exc:
            c.execute('ROLLBACK TO assignment_rewake')
            message, refusal = None, exc.rule
        finally:
            c.execute('RELEASE assignment_rewake')
        H.event(c, H.KEEPER, EVENT, row['id'], {'assignment': key, 'assigned_at': since,
                                            'rewoken_at': at, 'refusal': refusal or (None if message else 'no_queued_wake')})
        if message:
            woke.append(row['id'])
    return woke


def overdue(c, at=None):
    at = at or H.now()
    for row, _, since, saved in candidates(c, at):
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


def description(c, row, settings):
    why = reason(c, row, settings)
    return f"Assigned, not started: {row['title']}. Refusal reason: {why}."
