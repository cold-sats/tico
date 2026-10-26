"""Durable observations of continuous claim refusal, without mutating jobs or execution gates."""
from . import execution as E, hubdb as H

EVENT = 'job.refusal-observed'


def state(c, job):
    row = c.execute('SELECT detail_json FROM events WHERE target=? AND action=? ORDER BY rowid DESC LIMIT 1',
                    (job, EVENT)).fetchone()
    return H._json(row[0], {}) if row else {}


def oldest(c):
    for row in c.execute("SELECT a.bot,a.runner_id,b.display_name FROM assignments a "
                         "JOIN bots b ON b.slug=a.bot AND b.state='active' WHERE EXISTS("
                         "SELECT 1 FROM jobs j WHERE j.bot=a.bot AND j.state='queued' AND j.held=0)").fetchall():
        job = c.execute("SELECT * FROM jobs WHERE bot=? AND state='queued' AND held=0 ORDER BY created,id LIMIT 1",
                        (row['bot'],)).fetchone()
        yield row, job


def observe(c, settings, at=None):
    at = at or H.now()
    for bot, job in oldest(c):
        why, _, _ = E.bot_claimable(c, settings, bot['runner_id'], bot['bot'], oldest=True)
        previous = state(c, job['id'])
        if why == previous.get('reason'):
            continue
        since = (previous.get('since') if previous.get('reason') else None) or at
        H.event(c, H.KEEPER, EVENT, job['id'], {'reason': why, 'since': since if why else None})


def aged(c, settings):
    cutoff = H.shift(H.now(), hours=-12)
    for bot, job in oldest(c):
        previous = state(c, job['id'])
        if not previous.get('reason') or not previous.get('since') or previous['since'] > cutoff:
            continue
        why, _, _ = E.bot_claimable(c, settings, bot['runner_id'], bot['bot'], oldest=True)
        if why:
            yield {'bot': bot['bot'], 'name': bot['display_name'] or bot['bot'],
                   'oldest': job['created'], 'reason': why, 'refused_since': previous['since']}
