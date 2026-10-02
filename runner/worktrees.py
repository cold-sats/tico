"""Computer-owned task worktrees. Never removes a tree before preserving its history."""
import concurrent.futures
import os
from pathlib import Path
import shutil
import subprocess
import threading

from clients.tico import APIError
from . import git_credentials, isolation, repositories


def safe_path(workspace, relative):
    root = Path(workspace).resolve()
    raw = Path(relative)
    path = root / raw
    if raw.is_absolute() or '..' in raw.parts or not raw.parts or path.is_symlink():
        raise ValueError('Use a worktree inside the team workspace')
    resolved = path.resolve()
    if resolved == root or root not in resolved.parents or (root / 'repos') == resolved or (root / 'repos') in resolved.parents:
        raise ValueError('Worktree must stay inside the team workspace, outside repos')
    return path


def disk_floor(workspace):
    usage = shutil.disk_usage(workspace)
    floor = max(5 * repositories.GB, usage.total * .1)
    if usage.free < floor:
        raise ValueError(f'Not enough disk to create worktree: {usage.free / repositories.GB:.1f} GB free, needs {floor / repositories.GB:g} GB. Free space on this volume')


def git(path, *args, env=None, check=True):
    done = isolation.run(['git', '-C', str(path), *args], env=env, capture_output=True, text=True,
                         stdin=subprocess.DEVNULL, timeout=120)
    if check and done.returncode:
        raise ValueError(f'Git {args[0]} failed (exit {done.returncode}); check access, network, disk space and repository state')
    return done


def setup(path, command, env):
    if command:
        # Avoid keeping setup output (which may contain secrets or grow without bound).
        done = isolation.run(['/bin/sh', '-c', command], cwd=path, env=env, stdout=subprocess.DEVNULL,
                             stderr=subprocess.DEVNULL, stdin=subprocess.DEVNULL, timeout=600)
        if done.returncode:
            raise ValueError(f'Worktree created but setup failed (exit {done.returncode}); run the repository setup command again')


def metadata(client, name):
    repos = client.get('runners/me/repositories')['repositories']
    repo = next((r for r in repos if r['full_name'].lower() == name.lower() and r.get('access') == 'write'), None)
    if not repo:
        raise ValueError('This bot needs write access to this repository')
    return repo


def command(client, operation, value, task=None):
    workspace = os.environ.get('HUB_WORKSPACE')
    task = task or os.environ.get('HUB_TASK_ID')
    if not workspace or not os.environ.get('HUB_BOT') or not task:
        raise ValueError('Task worktrees need a bot run and a task; use --task when this run has no current task')
    env = {**os.environ, 'GIT_TERMINAL_PROMPT': '0'}
    try:
        if operation == 'add':
            disk_floor(workspace)
            repo = metadata(client, value)
            link = client.post(f'tasks/{task}/worktrees', {'repo': repo['full_name']})
            path = safe_path(workspace, link['path'])
            if path.exists():
                if not (path / '.git').is_file() or not git_credentials._same_repository(git(path, 'config', '--get', 'remote.origin.url').stdout.strip(), repo['full_name']):
                    raise ValueError('Worktree path already exists and does not match the repository')
                if git(path, 'symbolic-ref', '--short', 'HEAD').stdout.strip() != link['branch']:
                    raise ValueError('Existing worktree uses a different branch; attach it instead')
                common = Path(git(path, 'rev-parse', '--path-format=absolute', '--git-common-dir').stdout.strip()).resolve()
                if Path(workspace).resolve() not in common.parents:
                    raise ValueError('Worktree base must be inside the team workspace')
            else:
                base, default = repositories.worktree_base(workspace, repo, env)
                isolation.mkdir(path.parent, mode=0o755)
                if git(base, 'show-ref', '--verify', 'refs/heads/' + link['branch'], check=False).returncode == 0:
                    git(base, 'worktree', 'add', str(path), link['branch'], env=env)
                else:
                    git(base, 'worktree', 'add', '-b', link['branch'], str(path), 'origin/' + default, env=env)
                # Confirm before setup: a failed setup still leaves a tracked tree.
                client.patch(f'tasks/{task}/links/{link["link_id"]}', {'state': 'present', 'path': link['path']})
                setup(path, repo.get('setup_command'), env)
        else:
            raw = Path(value)
            relative = str(raw.resolve().relative_to(Path(workspace).resolve())) if raw.is_absolute() else value
            path = safe_path(workspace, relative)
            if not (path / '.git').is_file():
                raise ValueError('Attach needs a Git worktree, not a base clone')
            common = Path(git(path, 'rev-parse', '--path-format=absolute', '--git-common-dir').stdout.strip()).resolve()
            if Path(workspace).resolve() not in common.parents:
                raise ValueError('Worktree base must be inside the team workspace')
            repo_name = git_credentials.repository_name(git(path, 'config', '--get', 'remote.origin.url').stdout.strip())
            repo = metadata(client, repo_name or '')
            branch = git(path, 'symbolic-ref', '--short', 'HEAD').stdout.strip()
            link = client.post(f'tasks/{task}/worktrees/attach', {'path': relative, 'repo': repo['full_name'], 'branch': branch})
        client.patch(f'tasks/{task}/links/{link["link_id"]}', {'state': 'present', 'path': link['path']})
        return {**link, 'workspace_path': str(path)}
    except APIError as exc:
        if exc.status in (404, 405):
            raise ValueError('The server is too old for task worktrees; update Tico') from exc
        raise


def inspect(workspace, row):
    result = {'link_id': row['id'], 'state': 'unknown', 'branch': row['branch']}
    try:
        path = safe_path(workspace, row['path'])
        if not path.exists():
            result['state'] = 'removed' if row['state'] == 'removed' else 'missing'
            return result
        if not (path / '.git').is_file():
            raise ValueError('Tracked path is not a Git worktree; left as it is')
        result['repo'] = git_credentials.repository_name(git(path, 'config', '--get', 'remote.origin.url').stdout.strip())
        result.update(state='present', branch=git(path, 'symbolic-ref', '--short', 'HEAD').stdout.strip(),
                      dirty_files=len(git(path, 'status', '--porcelain').stdout.splitlines()),
                      last_commit=git(path, 'rev-parse', 'HEAD').stdout.strip())
        upstream = git(path, 'rev-list', '--left-right', '--count', 'HEAD...@{u}', check=False)
        if upstream.returncode:
            upstream = git(path, 'rev-list', '--left-right', '--count', 'HEAD...origin/HEAD', check=False)
        if upstream.returncode == 0:
            result['ahead'], result['behind'] = map(int, upstream.stdout.split())
        size, activity = 0, 0
        for root, dirs, files in os.walk(path, followlinks=False):
            for filename in files:
                file = Path(root) / filename
                if not file.is_symlink():
                    stat = file.stat()
                    size += stat.st_size
                    activity = max(activity, stat.st_mtime)
        result['size_mb'] = round(size / 1024 ** 2, 1)
        result['last_activity'] = activity
    except (ValueError, OSError, subprocess.SubprocessError):
        result['error'] = 'Could not inspect worktree; check disk space, Git state and workspace permissions'
    return result


def act(workspace, row, action, env):
    path = safe_path(workspace, row['path'])
    if action == 'remove':
        if not path.exists():
            return 'removed'
        if not (path / '.git').is_file():
            raise ValueError('Tracked path is not a worktree; left as it is')
        common = Path(git(path, 'rev-parse', '--path-format=absolute', '--git-common-dir').stdout.strip()).resolve()
        if Path(workspace).resolve() not in common.parents:
            raise ValueError('Worktree base is outside the team workspace')
        base = common.parent
        dirty = git(path, 'status', '--porcelain').stdout.strip()
        if dirty:
            wip = 'wip/' + row['task_id'][:8]
            if row['branch'] == wip:
                raise ValueError('Use a task branch separate from its wip branch before cleanup')
            current = git(path, 'symbolic-ref', '--short', 'HEAD').stdout.strip()
            if current != wip:
                git(path, 'switch', '-C', wip, env=env)
            git(path, 'add', '--all', env=env)
            git(path, '-c', 'user.name=Tico', '-c', 'user.email=bot@example.com', 'commit', '-m', 'Save task work before cleanup', env=env)
            git(path, 'push', 'origin', 'HEAD:refs/heads/' + wip, env=env)
            # Keep the saved work on the task branch for reopening, without rewriting a remote.
            git(path, 'branch', '-f', row['branch'], 'HEAD', env=env)
        else:
            branch = git(path, 'symbolic-ref', '--short', 'HEAD').stdout.strip()
            # Preserve clean, unpushed commits too. Failed pushes leave the worktree intact.
            git(path, 'push', 'origin', 'HEAD:refs/heads/' + branch, env=env)
            if branch == 'wip/' + row['task_id'][:8] and branch != row['branch']:
                git(path, 'branch', '-f', row['branch'], 'HEAD', env=env)
        git(base, 'worktree', 'remove', str(path), env=env)
        return 'removed'
    disk_floor(workspace)
    if path.exists():
        if inspect(workspace, {**row, 'id': row['link_id']}).get('state') != 'present':
            raise ValueError('Restore path already exists and is not a worktree')
        return 'present'
    base, default = repositories.worktree_base(workspace, row, env)
    isolation.mkdir(path.parent, mode=0o755)
    branch = row['branch']
    if git(base, 'show-ref', '--verify', 'refs/heads/' + branch, check=False).returncode == 0:
        git(base, 'worktree', 'add', str(path), branch, env=env)
    else:
        remote = git(base, 'fetch', 'origin', f'refs/heads/{branch}:refs/remotes/origin/{branch}', env=env, check=False)
        start = 'origin/' + branch if remote.returncode == 0 else 'origin/' + default
        git(base, 'worktree', 'add', '-b', branch, str(path), start, env=env)
    setup(path, row.get('setup_command'), env)
    return 'present'


class Worktrees:
    def __init__(self, workspace, client, idle=lambda: True):
        self.workspace, self.client, self.idle = workspace, client, idle
        self.pool = concurrent.futures.ThreadPoolExecutor(max_workers=1)
        self.pending = None
        self.reports = []
        self.actions = {}
        self.errors = {}
        self.lock = threading.Lock()

    def poll(self, actions=()):
        with self.lock:
            self.actions.update({a['link_id']: a for a in actions})
            if self.pending is None or self.pending.done():
                queued = list(self.actions.values())
                self.actions.clear()
                self.pending = self.pool.submit(self.sync, queued)
            return list(self.reports)

    def sync(self, actions):
        try:
            rows = self.client.get('runners/me/worktrees')['worktrees']
        except Exception:
            return
        errors = {key: error for key, error in self.errors.items() if any(r["id"] == key for r in rows)}
        for action in actions:
            if not self.idle():
                break
            row = next((r for r in rows if r['id'] == action['link_id']), None)
            if not row:
                continue
            closed = row['task_status'] in ('done', 'closed', 'declined') or row['bot_state'] == 'archived'
            if action['action'] == 'remove' and not closed or action['action'] == 'restore' and closed:
                continue
            env = {**os.environ, 'GIT_TERMINAL_PROMPT': '0'}
            try:
                if action['action'] == 'remove' and not safe_path(self.workspace, row['path']).exists():
                    self.client.patch(f'tasks/{row["task_id"]}/links/{row["id"]}', {'state': 'removed'})
                    row['state'] = 'removed'
                    errors.pop(row['id'], None)
                    continue
                granted = self.client.post(f'runners/me/worktrees/{row["id"]}/token')
                if not granted.get('token'):
                    raise ValueError('No repository credential for this worktree')
                env.update(git_credentials.environment(granted['token']))
                repo = next((r for r in self.client.get('runners/me/repositories')['repositories'] if r['full_name'].lower() == row['repo'].lower()), {})
                state = act(self.workspace, {**row, **action, 'full_name': row['repo'], **repo}, action['action'], env)
                self.client.patch(f'tasks/{row["task_id"]}/links/{row["id"]}', {'state': state})
                row['state'] = state
                errors.pop(row['id'], None)
            except (ValueError, APIError) as exc:
                errors[row['id']] = ('Worktree action failed; history kept. ' + str(exc))[:300]
            except Exception:
                errors[row['id']] = 'Worktree action failed; history kept. Check repository access, network, disk space and permissions'
        reports = [inspect(self.workspace, r) for r in rows]
        for report in reports:
            if report['link_id'] in errors:
                report['error'] = errors[report['link_id']]
        with self.lock:
            self.errors = errors
            self.reports = reports

    def close(self):
        self.pool.shutdown(wait=True)
