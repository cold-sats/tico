"""Task worktree authorization and computer lifecycle reports (task_links v2 schema)."""
import json
import re
import uuid
from datetime import datetime, timezone
from pathlib import PurePosixPath
from typing import Literal

from fastapi import Request
from pydantic import Field

from . import hubdb as H, repositories as R
from .auth import validate_identity
from .models import Contract
from .store import Problem, readiness_document

CLOSED = ('done', 'closed', 'declined')


class Create(Contract):
    repo: str = Field(max_length=200)


class Attach(Contract):
    path: str = Field(max_length=1000)
    repo: str | None = Field(default=None, max_length=200)
    branch: str | None = Field(default=None, max_length=200)


class Update(Contract):
    state: Literal['pending', 'present', 'missing', 'removed', 'unknown'] | None = None
    path: str | None = Field(default=None, max_length=1000)
    computer_id: str | None = None
    branch: str | None = Field(default=None, max_length=200)


def relative(path):
    p = PurePosixPath(path)
    if not path or p.is_absolute() or '..' in p.parts or '\\' in path or '\x00' in path or str(p) in ('.', 'repos') or p.parts[0] == 'repos':
        raise Problem('worktree_path', 'Use a worktree path inside the team workspace, outside repos', 422)
    return str(p)


def supported(c):
    # No runtime schema changes: the tasks migration owns these columns.
    return 'computer_id' in {r[1] for r in c.execute('PRAGMA table_info(task_links)')}


def inventory(c, computer):
    if not supported(c):
        return []
    return [dict(r) for r in c.execute("SELECT l.*,t.owner,t.status AS task_status,b.state AS bot_state FROM task_links l "
            "JOIN tasks t ON t.id=l.task_id JOIN bots b ON ('bot:' || b.slug)=t.owner "
            "WHERE l.kind='worktree' AND l.computer_id=? AND (coalesce(l.state,'unknown')<>'removed' "
            "OR (t.status NOT IN ('done','closed','declined') AND b.state='active'))", (computer,))]


def heartbeat(c, who, reports, capable):
    if not supported(c):
        return []
    rows = {r['id']: r for r in inventory(c, who.runner_id)}
    for report in reports or []:
        row = rows.get(report.link_id)
        if not row:
            continue
        if report.repo and row['repo'] is None:
            connection = c.execute("SELECT org FROM github_app WHERE id='app'").fetchone()
            grants = R.access(c, H.actor_id(row['owner']), connection['org'] if connection else '')['effective']
            grant = next((r for r in grants if r['full_name'].lower() == report.repo.lower() and r['access'] == 'write'), None)
            if not grant:
                c.execute("UPDATE task_links SET state='unknown',detail_json=?,updated=? WHERE id=?",
                          (json.dumps({'error': 'This bot needs write access to the attached repository'}), H.now(), row['id']))
                continue
            row['repo'] = grant['full_name']
            c.execute('UPDATE task_links SET repo=? WHERE id=?', (row['repo'], row['id']))
        detail = json.loads(row['detail_json'] or '{}')
        now = H.now()
        changed = (detail.get('last_commit') != report.last_commit or detail.get('dirty_files') != report.dirty_files
                   or detail.get('last_activity') != report.last_activity)
        if changed or 'activity_at' not in detail:
            detail['activity_at'] = now
            detail.pop('stalled_woke', None)
        if report.state == 'missing':
            detail.setdefault('missing_since', now)
        else:
            detail.pop('missing_since', None)
            detail.pop('missing_woke', None)
        task = H.task(c, row['task_id'])
        if task['status'] not in CLOSED and row['bot_state'] == 'active':
            for key, since, days, message in (
                ('missing_woke', detail.get('missing_since'), 1, 'Worktree missing for a day'),
                ('stalled_woke', detail.get('activity_at') if report.ahead else None, 3, 'Worktree has unpushed commits and no activity for three days')):
                if since and not detail.get(key) and (datetime.now(timezone.utc) - datetime.fromisoformat(since.replace('Z', '+00:00'))).total_seconds() >= days * 86400:
                    H._wake(c, task, task['owner'], message + ': ' + row['path'])
                    detail[key] = True
        detail.update(report.model_dump(exclude={'link_id', 'state', 'branch'}))
        state = 'pending' if row['state'] == 'pending' and row['repo'] and report.state == 'missing' else report.state
        branch = report.branch if report.state == 'present' else None
        c.execute('UPDATE task_links SET state=?,branch=coalesce(?,branch),detail_json=?,updated=? WHERE id=?',
                  (state, branch, json.dumps(detail), H.now(), row['id']))
        row['state'] = state
        if branch:
            row['branch'] = branch
    if not capable:
        c.execute("UPDATE task_links SET state='unknown' WHERE kind='worktree' AND computer_id=? AND state<>'removed'", (who.runner_id,))
        return []
    actions = []
    for row in rows.values():
        prs_open = c.execute("SELECT 1 FROM task_links WHERE task_id=? AND kind='pr' AND coalesce(state,'open') NOT IN ('merged','closed') LIMIT 1", (row['task_id'],)).fetchone()
        closed = row['task_status'] in CLOSED or row['bot_state'] == 'archived'
        action = 'remove' if closed and not prs_open and row['state'] != 'removed' else 'restore' if not closed and row['state'] in ('removed', 'pending') else None
        if action and (row['repo'] or row['state'] == 'missing'):
            actions.append({'link_id': row['id'], 'action': action, 'branch': row['branch'], 'path': row['path'],
                            'task_id': row['task_id'], 'repo': row['repo'], 'owner': H.actor_id(row['owner'])})
    return actions


def install(app, store, auth, mutate):
    def check(c, who, tid):
        validate_identity(c, who)
        task_id = auth.resolve_task(c, who, tid)
        row = auth.task(c, who, task_id)
        human = who.role == 'owner' or who.role == 'human' and H.can_move(c, who.actor)
        if not H.is_bot(row['owner']) or not (human or who.role == 'bot' and who.actor == row['owner']):
            raise Problem('forbidden', "Only the task's owner bot or a human mover manages its worktrees", 403)
        return row

    def provision(c, who, task, repo, path=None, branch=None):
        if not supported(c):
            raise Problem('worktrees_unavailable', 'The server is too old for task worktrees', 409)
        bot = H.actor_id(task['owner'])
        connection = app.state.github_app.row(c)
        org = connection['org'] if connection else store.settings.github_owner
        grants = R.access(c, bot, org)['effective']
        grant = next((r for r in grants if repo and r['full_name'].lower() == repo.lower() and r['access'] == 'write'), None)
        if repo and not grant:
            raise Problem('forbidden', 'This bot needs write access to this repository', 403)
        assigned = c.execute('SELECT r.id,r.readiness_json FROM assignments a JOIN runners r ON r.id=a.runner_id WHERE a.bot=? AND r.revoked_at IS NULL', (bot,)).fetchone()
        if not assigned or not readiness_document(assigned['readiness_json']).get('worktrees'):
            raise Problem('computer_update', 'Update this computer to use task worktrees', 409)
        if who.role == 'bot' and who.runner_id != assigned['id']:
            raise Problem('forbidden', 'Worktree belongs on the bot\'s computer', 403)
        short = task['id'][:8]
        repo = grant['full_name'] if grant else None
        path = relative(path or f'tasks/{short}/{repo.replace("/", "__")}')
        existing = c.execute("SELECT * FROM task_links WHERE kind='worktree' AND computer_id=? AND path=? AND state<>'removed'", (assigned['id'], path)).fetchone()
        if existing:
            if existing['task_id'] != task['id']:
                raise Problem('worktree_path', 'This worktree belongs to another task', 409)
            return {'link_id': existing['id'], 'branch': existing['branch'], 'path': existing['path']}
        count = c.execute("SELECT count(*) FROM task_links l JOIN tasks t ON t.id=l.task_id WHERE l.kind='worktree' AND t.owner=? AND coalesce(l.state,'unknown')<>'removed'", (task['owner'],)).fetchone()[0]
        if count >= 10:
            raise Problem('worktree_limit', 'Finish or close older tasks before adding more than 10 worktrees', 409)
        slug = re.sub('[^a-z0-9]+', '-', task['title'].lower()).strip('-')[:50] or 'task'
        branch = branch or f'tico/{short}-{slug}'
        if not re.fullmatch(r'[A-Za-z0-9_./-]+', branch) or branch.startswith('-'):
            raise Problem('worktree_branch', 'Invalid worktree branch', 422)
        link = uuid.uuid4().hex
        c.execute("INSERT INTO task_links(id,task_id,kind,url,title,state,added_by,created,repo,branch,computer_id,path,updated) VALUES(?,?,'worktree',?,?,'pending',?,?,?,?,?,?,?)",
                  (link, task['id'], 'worktree:' + link, repo or 'Worktree', who.actor, H.now(), repo, branch, assigned['id'], path, H.now()))
        return {'link_id': link, 'branch': branch, 'path': path}

    @app.post('/api/v2/tasks/{tid}/worktrees')
    def create(request: Request, tid: str, body: Create):
        who = request.state.identity
        return mutate(request, body, lambda c: provision(c, who, check(c, who, tid), body.repo))

    @app.post('/api/v2/tasks/{tid}/worktrees/attach')
    def attach(request: Request, tid: str, body: Attach):
        who = request.state.identity
        def work(c):
            task = check(c, who, tid)
            path = relative(body.path)
            repo = body.repo
            return provision(c, who, task, repo, path, body.branch)
        return mutate(request, body, work)

    @app.patch('/api/v2/tasks/{tid}/links/{link_id}')
    def update(request: Request, tid: str, link_id: str, body: Update):
        who = request.state.identity
        def work(c):
            validate_identity(c, who)
            task_id = auth.resolve_task(c, who, tid) if who.role != 'runner' else tid
            link = c.execute("SELECT * FROM task_links WHERE id=? AND task_id=? AND kind='worktree'", (link_id, task_id)).fetchone()
            if not link:
                raise Problem('not_found', 'No such task worktree', 404)
            if who.role == 'runner':
                if link['computer_id'] != who.runner_id:
                    raise Problem('forbidden', 'Worktree belongs to another computer', 403)
            else:
                check(c, who, tid)
                if who.role != 'bot' or link['computer_id'] != who.runner_id:
                    raise Problem('forbidden', 'The computer or owner bot confirms its worktree', 403)
            if body.computer_id and body.computer_id != who.runner_id:
                raise Problem('forbidden', 'Cannot attach on another computer', 403)
            fields = body.model_dump(exclude_none=True)
            if 'path' in fields:
                fields['path'] = relative(fields['path'])
                if fields['path'] != link['path']:
                    raise Problem('worktree_path', 'Attach a new worktree to change its path', 409)
            if 'branch' in fields and fields['branch'] != link['branch']:
                raise Problem('worktree_branch', 'Attach a new worktree to change its branch', 409)
            fields['updated'] = H.now()
            c.execute('UPDATE task_links SET ' + ','.join(k + '=?' for k in fields) + ' WHERE id=?', (*fields.values(), link_id))
            return dict(c.execute('SELECT * FROM task_links WHERE id=?', (link_id,)).fetchone())
        return mutate(request, body, work)

    @app.post('/api/v2/runners/me/worktrees/{link_id}/token')
    def token(request: Request, link_id: str):
        who = request.state.identity
        with store.read() as c:
            validate_identity(c, who)
            if who.role != 'runner':
                raise Problem('forbidden', 'A registered computer is required', 403)
            link = next((r for r in inventory(c, who.runner_id) if r['id'] == link_id), None)
            if not link:
                raise Problem('not_found', 'No worktree on this computer', 404)
            service = app.state.github_app
            connection = service.row(c)
            if not connection:
                raise Problem('github_connection', 'Connect GitHub to save task work before cleanup', 409)
            grants = R.access(c, H.actor_id(link['owner']), connection['org'])['effective']
            if not any(r['full_name'].lower() == link['repo'].lower() and r['access'] == 'write' for r in grants):
                raise Problem('forbidden', 'This bot needs write access to save its worktree', 403)
        value, expires = service.mint([link['repo']], {'contents': 'write', 'metadata': 'read'})
        return {'token': value, 'expires_at': expires}

    @app.get('/api/v2/runners/me/worktrees')
    def listing(request: Request):
        who = request.state.identity
        with store.read() as c:
            validate_identity(c, who)
            if who.role != 'runner':
                raise Problem('forbidden', 'A registered computer is required', 403)
            return {'worktrees': inventory(c, who.runner_id)}
