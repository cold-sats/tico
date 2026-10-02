"""Subscription defaults for bots and nested groups."""
import json

from fastapi import Request

from . import groups as G, hubdb as H, models as M
from .execution import readiness_document
from .store import Problem, encode


def context(c, settings=None):
    result = {'groups': G._roster(c)['org_groups'],
              'teams': {r['bot']: r['team'] for r in c.execute('SELECT bot,team FROM bot_config')},
              'assignments': {(r['scope'], r['target']): r['profile']
                              for r in c.execute('SELECT * FROM subscription_assignments')}}
    if settings is not None:
        from . import providers
        result['providers'] = providers.load(c, settings)
    return result


def effective(c, bot, ctx=None):
    ctx = ctx if ctx is not None else context(c)
    assignments = ctx['assignments']
    if ('bot', bot) in assignments:
        return assignments['bot', bot], 'bot'
    gid = ctx['teams'].get(bot)
    seen = set()
    while gid and gid not in seen:
        seen.add(gid)
        group = ctx['groups'].get(gid)
        if not group:
            break
        if ('group', gid) in assignments:
            return assignments['group', gid], 'group:' + group['name']
        gid = group.get('parent')
    return None, 'computer'


def record(c, runner_id, profiles):
    # Omitted by an older computer: retain its last report until it can report again.
    from .repositories import save_metadata
    from .repositories import metadata
    reported = {'reported': profiles is not None}
    if metadata(c, 'computer-profiles:' + runner_id) != reported:
        save_metadata(c, 'computer-profiles:' + runner_id, reported)
    if profiles is None:
        return
    valid = {}
    for row in profiles[:100]:
        try:
            profile = M.ComputerProfile.model_validate(row)
        except ValueError:
            continue
        valid[profile.name] = encode({k: v.model_dump() for k, v in profile.runtimes.items()})
    stored = {r['profile']: r['runtimes_json'] for r in c.execute(
        'SELECT profile,runtimes_json FROM computer_profiles WHERE runner_id=?', (runner_id,))}
    if stored == valid:
        return
    c.execute('DELETE FROM computer_profiles WHERE runner_id=?', (runner_id,))
    c.executemany('INSERT INTO computer_profiles VALUES(?,?,?,?)',
                  [(runner_id, name, runtimes, H.now()) for name, runtimes in valid.items()])


def listing(c, auth, who, computer_rows):
    computers = []
    for runner in computer_rows(c, who):
        computers.append({'runner_id': runner['id'], 'label': runner['label'], 'profiles': [
            {'name': row['profile'], 'runtimes': json.loads(row['runtimes_json'] or '{}')}
            for row in c.execute('SELECT * FROM computer_profiles WHERE runner_id=? ORDER BY profile', (runner['id'],))]})
    access = auth.bot_accesses(c, who)
    assignments = [dict(row) for row in c.execute('SELECT * FROM subscription_assignments ORDER BY scope,target')
                   if row['scope'] == 'group' or (access.get(row['target']) or {}).get('see')]
    return {'profiles_by_computer': computers, 'assignments': assignments}


def assign(c, auth, who, body):
    if body.scope == 'group':
        G._may_change(auth, who)
        if body.target not in G._roster(c)['org_groups']:
            raise Problem('not_found', 'Group not found', 404)
    else:
        if not H.bot(c, body.target):
            raise Problem('not_found', 'Bot not found', 404)
        if not (auth.bot_admin(who) or (who.role == 'human' and c.execute(
                'SELECT 1 FROM assignments a JOIN runners r ON r.id=a.runner_id '
                'WHERE a.bot=? AND r.operator=? AND r.revoked_at IS NULL',
                (body.target, H.actor_id(who.actor))).fetchone())):
            raise Problem('forbidden', 'You cannot change this bot', 403)
    if body.profile is None:
        c.execute('DELETE FROM subscription_assignments WHERE scope=? AND target=?', (body.scope, body.target))
    else:
        c.execute('INSERT INTO subscription_assignments VALUES(?,?,?,?,?) ON CONFLICT(scope,target) DO UPDATE SET '
                  'profile=excluded.profile,updated=excluded.updated,updated_by=excluded.updated_by',
                  (body.scope, body.target, body.profile, H.now(), who.actor))
    H.event(c, who.actor, 'subscription.assigned', body.target, body.model_dump())
    return body.model_dump()


def bot_subscription(c, bot, settings, ctx=None):
    ctx = ctx if ctx is not None else context(c, settings)
    profile, source = effective(c, bot, ctx)
    runner = c.execute('SELECT r.* FROM assignments a JOIN runners r ON r.id=a.runner_id WHERE a.bot=? '
                       'AND r.revoked_at IS NULL', (bot,)).fetchone()
    signed_in, problem = None, ''
    computer = {'runner_id': runner['id'], 'label': runner['label']} if runner else None
    if runner:
        report = readiness_document(runner['readiness_json'])
        bot_report = report.get('bots', {}).get(bot, {})
        from . import providers
        from .shared_bots import follow
        row = c.execute('SELECT config_json FROM bot_config WHERE bot=?', (bot,)).fetchone()
        config = providers.fill(ctx['providers'], follow(c, bot, json.loads(row[0] or '{}') if row else {}))
        runtime = config.get('runtime')
        if source == 'computer':
            profile = bot_report.get('profile') or None
            state = bot_report.get('sign_in') or report.get('runtimes', {}).get(runtime, {}).get('authenticated')
            signed_in = True if state == 'ready' else False if state in ('missing', 'failed', 'rejected') else None
        else:
            from .repositories import metadata
            if not metadata(c, 'computer-profiles:' + runner['id']).get('reported'):
                return {'profile': profile, 'source': source, 'computer': computer, 'signed_in': None,
                        'problem': f'Update {runner["label"]} to use subscriptions'}
            row = c.execute('SELECT runtimes_json FROM computer_profiles WHERE runner_id=? AND profile=?',
                            (runner['id'], profile)).fetchone()
            if row:
                signed_in = json.loads(row[0] or '{}').get(runtime, {}).get('signed_in')
                if signed_in is False:
                    problem = f'{profile} is not signed in on {runner["label"]}'
            else:
                signed_in = False
                problem = f'profile {profile} not on {runner["label"]}'
    return {'profile': profile, 'source': source, 'computer': computer, 'signed_in': signed_in, 'problem': problem}


def install(app, store, auth, mutate, settings, computer_rows):
    @app.get('/api/v2/subscriptions')
    def subscriptions(request: Request):
        who = request.state.identity
        auth.domain(who)
        with store.read() as c:
            return listing(c, auth, who, computer_rows)

    @app.put('/api/v2/subscriptions')
    def subscription_assignment(request: Request, body: M.SubscriptionAssignment):
        who = request.state.identity
        def work(c):
            auth.domain(who)
            return assign(c, auth, who, body)
        return mutate(request, body, work)

    @app.get('/api/v2/bots/{bot}/subscription')
    def subscription(request: Request, bot: str):
        who = request.state.identity
        auth.domain(who)
        with store.read() as c:
            if not H.bot(c, bot):
                raise Problem('not_found', 'Bot not found', 404)
            auth.require_see(c, who, bot)
            return bot_subscription(c, bot, settings)
