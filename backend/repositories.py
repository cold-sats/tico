"""Team repository selection, bot grants and computer base-clone access."""
import base64
import json
import time
import uuid
from typing import Literal

from fastapi import Request
from pydantic import BaseModel, ConfigDict

from . import hubdb as H
from .auth import validate_identity
from .store import Problem

SETTINGS = 'repos_new_bot_default'


def metadata(c, key):
    row = c.execute('SELECT value_json FROM registry_metadata WHERE key=?', (key,)).fetchone()
    try:
        value = json.loads(row[0]) if row else {}
        return value if isinstance(value, dict) else {}
    except ValueError:
        return {}


def save_metadata(c, key, value):
    c.execute('INSERT INTO registry_metadata VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value_json=excluded.value_json',
              (key, json.dumps(value)))


def migrate(c):
    if metadata(c, 'repositories-access-migrated').get('done'):
        return
    for bot, repos in metadata(c, 'github-extra-repos').items():
        if not repos:
            continue
        row = c.execute('SELECT config_json FROM bot_config WHERE bot=?', (bot,)).fetchone()
        if row:
            config = json.loads(row[0] or '{}')
            config['repo_access_mode'] = 'chosen'
            c.execute('UPDATE bot_config SET config_json=? WHERE bot=?', (json.dumps(config), bot))
        for repo in repos:
            c.execute('INSERT INTO repositories(id,full_name,enabled,updated) VALUES(?,?,1,?) '
                      'ON CONFLICT(full_name) DO UPDATE SET enabled=1', (uuid.uuid4().hex, repo, H.now()))
            c.execute("INSERT INTO bot_repo_access VALUES(?,?,'write') ON CONFLICT(bot,full_name) DO UPDATE SET access='write'",
                      (bot, repo))

    save_metadata(c, 'repositories-access-migrated', {'done': True})


def access(c, bot, org):
    from .github_app import repo_of
    from .shared_bots import declared, source_of
    row = c.execute('SELECT config_json FROM bot_config WHERE bot=?', (bot,)).fetchone()
    if not row:
        raise Problem('not_found', 'No such bot', 404)
    config = json.loads(row[0] or '{}')
    mode, all_access = config.get('repo_access_mode', 'own'), config.get('repo_all_access', 'write')
    source = source_of(declared(c, bot)) or bot
    own_row = c.execute('SELECT repo FROM bot_config WHERE bot=?', (source,)).fetchone()
    own = repo_of(own_row[0] if own_row else '', org)
    chosen = [dict(r) for r in c.execute('SELECT full_name,access FROM bot_repo_access WHERE bot=? ORDER BY full_name', (bot,))]
    grants = {}
    if mode == 'all':
        grants = {r[0].lower(): {'full_name': r[0], 'access': all_access}
                  for r in c.execute('SELECT full_name FROM repositories WHERE enabled=1')}
    elif mode == 'chosen':
        grants = {r['full_name'].lower(): r for r in chosen if c.execute(
            'SELECT 1 FROM repositories WHERE full_name=? AND enabled=1', (r['full_name'],)).fetchone()}
    if own:
        grants[own.lower()] = {'full_name': own, 'access': 'write'}
    effective = [r for _, r in sorted(grants.items()) if org and r['full_name'].split('/')[0].lower() == org.lower()]
    return {'mode': mode, 'all_access': all_access, 'chosen': chosen, 'effective': effective}


def set_access(c, bot, body, org, actor, legacy=False):
    from .github_app import repo_of, save_extra_repos
    before = access(c, bot, org)
    wanted = {}
    for grant in body.chosen or []:
        name = repo_of(grant.full_name, org)
        if not name or name.split('/')[0].lower() != org.lower():
            raise Problem('github_repo', 'Choose a repository in the connected organization', 422)
        if legacy:
            c.execute('INSERT INTO repositories(id,full_name,enabled,updated) VALUES(?,?,1,?) '
                      'ON CONFLICT(full_name) DO UPDATE SET enabled=1', (uuid.uuid4().hex, name, H.now()))
        elif not c.execute('SELECT 1 FROM repositories WHERE full_name=?', (name,)).fetchone():
            raise Problem('github_repo', 'Choose a repository from the team list', 422)
        wanted[name.lower()] = (name, grant.access)
    config = json.loads(c.execute('SELECT config_json FROM bot_config WHERE bot=?', (bot,)).fetchone()[0] or '{}')
    config.update(repo_access_mode=body.mode, repo_all_access=body.all_access or before['all_access'])
    c.execute('UPDATE bot_config SET config_json=? WHERE bot=?', (json.dumps(config), bot))
    if body.chosen is not None:
        c.execute('DELETE FROM bot_repo_access WHERE bot=?', (bot,))
        c.executemany('INSERT INTO bot_repo_access VALUES(?,?,?)', [(bot, name, level) for name, level in wanted.values()])
    after = access(c, bot, org)
    save_extra_repos(c, bot, [r['full_name'] for r in after['chosen'] if r['access'] == 'write'] if body.mode == 'chosen' else [])
    H.event(c, actor, 'bot.repos_changed', bot, {'before': before, 'after': after})
    return after


def sync(service):
    row = service.row()
    if not row or not service.installation():
        with service.store.transaction() as c:
            c.execute('UPDATE repositories SET reachable=0 WHERE reachable<>0')
        return
    token, _ = service.mint(None, {'contents': 'read', 'metadata': 'read'})
    headers = {'Authorization': 'Bearer ' + token}
    repos, page = [], 1
    while True:
        response = service._call('GET', '/installation/repositories', params={'per_page': 100, 'page': page}, headers=headers)
        if response.status_code >= 300:
            raise Problem('github_repositories', 'GitHub could not list repositories; retry Refresh', 502)
        batch = response.json()['repositories']
        repos.extend(r for r in batch if r['full_name'].split('/')[0].lower() == row['org'].lower())
        if len(batch) < 100:
            break
        page += 1
    with service.store.read() as c:
        from .github_app import repo_of
        own = {str(repo_of(r[0], row['org']) or '').lower() for r in c.execute('SELECT repo FROM bot_config')}
        overrides = {r[0].lower() for r in c.execute("SELECT full_name FROM repositories WHERE setup_source='settings'")}
    for repo in repos:
        repo['setup_command'], repo['setup_source'] = None, None
        if repo['full_name'].lower() in overrides:
            continue
        for filename in ('tico.json', 'conductor.json'):
            response = service._call('GET', f"/repos/{repo['full_name']}/contents/{filename}", headers=headers,
                                     params={'ref': repo['default_branch']} if repo.get('default_branch') else {})
            if response.status_code == 404:
                continue
            if response.status_code >= 300:
                raise Problem('github_setup', f"Could not read {repo['full_name']}/{filename}; retry Refresh", 502)
            try:
                data = response.json()
                if data.get('size', 0) > 1024 * 1024:
                    continue
                config = json.loads(base64.b64decode(data['content']))
                command = config.get('setup') if filename == 'tico.json' else (config.get('scripts') or {}).get('setup')
                if isinstance(command, str):
                    repo['setup_command'], repo['setup_source'] = command, filename
                    break
            except (ValueError, KeyError, TypeError, AttributeError):
                continue
    with service.store.transaction() as c:
        c.execute('UPDATE repositories SET reachable=0')
        for repo in repos:
            name = repo['full_name']
            c.execute('INSERT INTO repositories(id,full_name,bot_repo,default_branch,setup_command,setup_source,reachable,last_seen,updated) '
                      'VALUES(?,?,?,?,?,?,1,?,?) ON CONFLICT(full_name) DO UPDATE SET bot_repo=excluded.bot_repo,'
                      'default_branch=excluded.default_branch,reachable=1,last_seen=excluded.last_seen,updated=excluded.updated,'
                      "setup_command=CASE WHEN repositories.setup_source='settings' THEN repositories.setup_command ELSE excluded.setup_command END,"
                      "setup_source=CASE WHEN repositories.setup_source='settings' THEN 'settings' ELSE excluded.setup_source END",
                      (uuid.uuid4().hex, name, int(name.split('/')[1].lower().startswith('bot-') or name.lower() in own),
                       repo.get('default_branch'), repo['setup_command'], repo['setup_source'], H.now(), H.now()))
        save_metadata(c, 'repositories-synced', {'day': H.now()[:10]})


def daily(service):
    with service.store.read() as c:
        if metadata(c, 'repositories-synced').get('day') == H.now()[:10]:
            return
    if time.time() - service.repository_sync_attempt < 3600:
        return
    service.repository_sync_attempt = time.time()
    sync(service)


def runner_repos(c, runner_id, org):
    result = {}
    for row in c.execute("SELECT a.bot FROM assignments a JOIN bots b ON b.slug=a.bot WHERE a.runner_id=? AND b.state='active'", (runner_id,)).fetchall():
        for grant in access(c, row[0], org)['effective']:
            repo = c.execute('SELECT full_name,default_branch,setup_command FROM repositories WHERE full_name=? AND enabled=1',
                             (grant['full_name'],)).fetchone()
            if not repo:
                continue
            key = repo['full_name'].lower()
            entry = result.setdefault(key, {**dict(repo), 'bots': [], 'access': 'read'})
            entry['bots'].append(row[0])
            if grant['access'] == 'write':
                entry['access'] = 'write'
    return {'repositories': [result[k] for k in sorted(result)]}


class Contract(BaseModel):
    model_config = ConfigDict(extra='forbid')


class Grant(Contract):
    full_name: str
    access: Literal['read', 'write'] = 'write'


class RepoAccessUpdate(Contract):
    mode: Literal['own', 'all', 'chosen']
    all_access: Literal['read', 'write'] | None = None
    chosen: list[Grant] | None = None


class RepoUpdate(Contract):
    enabled: bool | None = None
    setup_command: str | None = None


class RepoSettings(Contract):
    new_bot_default: Literal['own', 'all']


def install(app, store, service):
    def human(request, change=False):
        who = request.state.identity
        with store.read() as c:
            validate_identity(c, who)
        if who.role not in ('human', 'owner') or (change and who.role != 'owner' and not app.state.auth.bot_admin(who)):
            raise Problem('forbidden', 'Only an owner or admin changes repository access' if change else 'A teammate may read repositories', 403)
        return who

    def listing():
        with store.read() as c:
            repos = [dict(r) for r in c.execute('SELECT full_name,enabled,bot_repo,default_branch,setup_command,setup_source,reachable,last_seen FROM repositories ORDER BY full_name')]
            for r in repos:
                for key in ('enabled', 'bot_repo', 'reachable'):
                    r[key] = bool(r[key])
            return {'repositories': repos, 'new_bot_default': metadata(c, SETTINGS).get('new_bot_default', 'own'),
                    'github_connected': bool(service.row(c))}

    @app.get('/api/v2/repositories')
    def repo_list(request: Request):
        human(request)
        return listing()

    @app.post('/api/v2/repositories/refresh')
    def refresh(request: Request):
        human(request, True)
        sync(service)
        return listing()

    @app.put('/api/v2/repositories/settings')
    def settings(request: Request, body: RepoSettings):
        who = human(request, True)
        with store.transaction() as c:
            before = metadata(c, SETTINGS)
            save_metadata(c, SETTINGS, body.model_dump())
            H.event(c, who.actor, 'repositories.changed', 'settings', {'before': before, 'after': body.model_dump()})
        return body.model_dump()

    @app.put('/api/v2/repositories/{owner}/{repo}')
    def update(request: Request, owner: str, repo: str, body: RepoUpdate):
        who = human(request, True)
        name = owner + '/' + repo
        with store.transaction() as c:
            before = c.execute('SELECT * FROM repositories WHERE full_name=?', (name,)).fetchone()
            if not before:
                raise Problem('not_found', 'No such repository; refresh the list', 404)
            if body.enabled is not None:
                c.execute('UPDATE repositories SET enabled=? WHERE full_name=?', (int(body.enabled), name))
            if 'setup_command' in body.model_fields_set:
                c.execute("UPDATE repositories SET setup_command=?,setup_source='settings' WHERE full_name=?", (body.setup_command, name))
            c.execute('UPDATE repositories SET updated=? WHERE full_name=?', (H.now(), name))
            after = dict(c.execute('SELECT * FROM repositories WHERE full_name=?', (name,)).fetchone())
            H.event(c, who.actor, 'repositories.changed', name, {'before': dict(before), 'after': after})
        return after

    @app.get('/api/v2/bots/{bot}/repositories')
    def bot_get(request: Request, bot: str):
        human(request)
        with store.read() as c:
            row = service.row(c)
            return access(c, bot, row['org'] if row else store.settings.github_owner)

    @app.put('/api/v2/bots/{bot}/repositories')
    def bot_set(request: Request, bot: str, body: RepoAccessUpdate):
        who = human(request, True)
        with store.transaction() as c:
            row = service.row(c)
            return set_access(c, bot, body, row['org'] if row else store.settings.github_owner, who.actor)

    def computer(request):
        who = request.state.identity
        with store.read() as c:
            validate_identity(c, who)
            if not app.state.execution.runner(c, who):
                raise Problem("forbidden", "This computer is no longer registered", 403)
            row = service.row(c)
            return runner_repos(c, who.runner_id, row['org'] if row else '')

    @app.get('/api/v2/runners/me/repositories')
    def computer_get(request: Request):
        who = request.state.identity
        if who.role != 'bot':
            return computer(request)
        with store.read() as c:
            validate_identity(c, who)
            row = service.row(c)
            bot = H.actor_id(who.actor)
            grants = access(c, bot, row['org'] if row else store.settings.github_owner)['effective']
            result = []
            for grant in grants:
                repo = c.execute('SELECT full_name,default_branch,setup_command FROM repositories WHERE full_name=?',
                                 (grant['full_name'],)).fetchone()
                result.append({**(dict(repo) if repo else {'full_name': grant['full_name'], 'default_branch': None,
                                                          'setup_command': None}), 'access': grant['access']})
            return {'repositories': result}

    @app.post('/api/v2/runners/me/repositories/token')
    def computer_token(request: Request):
        names = [r['full_name'] for r in computer(request)['repositories']]
        if not names:
            return {'token': None, 'expires_at': None, 'repositories': []}
        token, expires = service.mint(names, {'contents': 'read', 'metadata': 'read'})
        return {'token': token, 'expires_at': expires, 'repositories': names}
