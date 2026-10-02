"""Computer-owned task worktrees. Never removes a tree before preserving its history."""
import concurrent.futures
from contextlib import contextmanager
import fcntl
import fnmatch
import hashlib
import json
import signal
import time
import os
import re
from pathlib import Path
import shutil
import subprocess
import threading

from clients.tico import APIError
from . import git_credentials, isolation, repositories, safe_git


def safe_path(workspace, relative):
    root = Path(workspace).resolve()
    if not isinstance(relative, str) or len(relative) > 1000 or any(ord(ch) < 32 for ch in relative):
        raise ValueError('Invalid worktree path')
    raw = Path(relative)
    path = root / raw
    if raw.is_absolute() or '..' in raw.parts or not raw.parts or path.is_symlink():
        raise ValueError('Use a worktree inside the team workspace')
    resolved = path.resolve()
    if resolved != path:
        raise ValueError("Worktree path must not contain symlinks")
    try:
        insensitive = root.samefile(Path(str(root).swapcase()))
    except OSError:
        insensitive = False
    repo_path = str(root / 'repos')
    candidate = str(resolved)
    if insensitive:
        repo_path, candidate = repo_path.casefold(), candidate.casefold()
    if candidate == repo_path or candidate.startswith(repo_path + os.sep):
        raise ValueError('Worktree must stay outside repos')
    if resolved == root or root not in resolved.parents or (root / 'repos') == resolved or (root / 'repos') in resolved.parents:
        raise ValueError('Worktree must stay inside the team workspace, outside repos')
    return resolved


def disk_floor(workspace):
    usage = shutil.disk_usage(workspace)
    floor = max(5 * repositories.GB, usage.total * .1)
    if usage.free < floor:
        raise ValueError(f'Not enough disk to create worktree: {usage.free / repositories.GB:.1f} GB free, needs {floor / repositories.GB:g} GB. Free space on this volume')


def git(path, *args, env=None, check=True):
    if args[:2] == ('worktree', 'prune') and (Path(path) / '.git' / 'worktrees').is_symlink():
        raise ValueError('Worktree registrations point outside the base clone; left as they are')
    done = isolation.run([*safe_git.PREFIX, '-C', str(path), *args], env=safe_git.environment(env), capture_output=True, text=True,
                         stdin=subprocess.DEVNULL, timeout=120)
    if check and done.returncode:
        raise ValueError(f'Git {args[0]} failed (exit {done.returncode}); check access, network, disk space and repository state')
    return done


@contextmanager
def locked(workspace, task):
    folder = isolation.mkdir(Path(workspace) / 'tasks' / '.locks', mode=0o755)
    path = folder / hashlib.sha256(str(task).encode()).hexdigest()[:2]
    with path.open('a') as handle:
        isolation.chown(path)
        fcntl.flock(handle, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)


def setup(path, command, env):
    if command:
        with isolation.popen(['/bin/sh', '-c', command], cwd=path, env=safe_git.environment(env),
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, stdin=subprocess.DEVNULL,
                             start_new_session=True) as process:
            try:
                code = process.wait(timeout=600)
            except subprocess.TimeoutExpired:
                os.killpg(process.pid, signal.SIGKILL)
                process.wait()
                raise ValueError('Worktree setup timed out; run setup again') from None
        if code:
            raise ValueError(f'Worktree created but setup failed (exit {code}); run the repository setup command again')


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
    env = safe_git.environment()
    try:
        if operation == 'setup':
            repo = metadata(client, value)
            rows = client.get(f'tasks/{task}/links')
            rows = rows.get('links', []) if isinstance(rows, dict) else rows
            candidates = [r for r in rows if r['kind'] == 'worktree' and (r.get('repo') or '').lower() == value.lower() and r.get('state') == 'present']
            candidates.sort(key=lambda r: not json.loads(r.get('detail_json') or '{}').get('setup_pending'))
            row = candidates[0] if candidates else None
            if not row:
                raise ValueError('No present worktree for this repository on the task')
            path = safe_path(workspace, row['path'])
            with locked(workspace, row['id']):
                setup(path, repo.get('setup_command'), env)
                return client.patch(f'tasks/{task}/links/{row["id"]}', {'setup_pending': False})
        if operation == 'add':
            disk_floor(workspace)
            repo = metadata(client, value)
            link = client.post(f'tasks/{task}/worktrees', {'repo': repo['full_name']})
            with locked(workspace, link['link_id']):
                checked_branch(link['branch'])
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
                    git(base, 'worktree', 'prune', '--expire', 'now', env=env)
                    isolation.mkdir(path.parent, mode=0o755)
                    if git(base, 'show-ref', '--verify', 'refs/heads/' + link['branch'], check=False).returncode == 0:
                        git(base, 'worktree', 'add', str(path), link['branch'], env=env)
                    else:
                        git(base, 'worktree', 'add', '--no-track', '-b', link['branch'], str(path), 'origin/' + default, env=env)
                    # Confirm before setup: a failed setup still leaves a tracked tree.
                    client.patch(f'tasks/{task}/links/{link["link_id"]}', {'state': 'present', 'path': link['path']})
                    client.patch(f'tasks/{task}/links/{link["link_id"]}', {'setup_pending': True})
                    setup(path, repo.get('setup_command'), env)
                    client.patch(f'tasks/{task}/links/{link["link_id"]}', {'setup_pending': False})
        else:
            raw = Path(value)
            relative = str(raw.relative_to(Path(workspace).resolve())) if raw.is_absolute() else value
            path = safe_path(workspace, relative)
            relative = str(path.relative_to(Path(workspace).resolve()))
            if not (path / '.git').is_file():
                raise ValueError('Attach needs a Git worktree, not a base clone')
            common = Path(git(path, 'rev-parse', '--path-format=absolute', '--git-common-dir').stdout.strip()).resolve()
            if Path(workspace).resolve() not in common.parents:
                raise ValueError('Worktree base must be inside the team workspace')
            repo_name = git_credentials.repository_name(git(path, 'config', '--get', 'remote.origin.url').stdout.strip())
            repo = metadata(client, repo_name or '')
            branch = checked_branch(git(path, 'symbolic-ref', '--short', 'HEAD', env=env).stdout.strip())
            link = client.post(f'tasks/{task}/worktrees/attach', {'path': relative, 'repo': repo['full_name'], 'branch': branch})
        client.patch(f'tasks/{task}/links/{link["link_id"]}', {'state': 'present', 'path': link['path']})
        return {**link, 'workspace_path': str(path)}
    except (ValueError, OSError, subprocess.SubprocessError):
        if operation == 'add' and 'link' in locals() and ('path' not in locals() or not (path / '.git').is_file()):
            client.patch(f'tasks/{task}/links/{link["link_id"]}', {'state': 'missing'})
        raise
    except APIError as exc:
        if exc.status in (404, 405):
            raise ValueError('The server is too old for task worktrees; update Tico') from exc
        raise


def checked_branch(branch):
    if not isinstance(branch, str) or not branch or len(branch) > 200 or branch.startswith('-'):
        raise ValueError('Invalid or oversized worktree branch')
    if git(Path.cwd(), 'check-ref-format', '--branch', branch, env=safe_git.process_environment(), check=False).returncode:
        raise ValueError('Invalid worktree branch')
    return branch


def wip_branch(row):
    return 'wip/' + row['task_id'][:8] + '-' + (row.get('id') or row['link_id'])[:6]


def remote_branch(base, branch, env):
    checked_branch(branch)
    listed = git(base, 'ls-remote', '--exit-code', 'origin', 'refs/heads/' + branch, env=env, check=False)
    if listed.returncode == 2:
        return None
    if listed.returncode:
        raise ValueError('Git fetch failed; cannot determine remote branch, retry later')
    git(base, 'fetch', '--no-tags', 'origin', f'+refs/heads/{branch}:refs/remotes/origin/{branch}', env=env)
    return 'refs/remotes/origin/' + branch


def fast_forward(path, branch, target, env):
    ref = 'refs/heads/' + checked_branch(branch)
    old = git(path, 'rev-parse', '--verify', ref, env=env, check=False)
    head = git(path, 'rev-parse', target, env=env).stdout.strip()
    if old.returncode == 0:
        previous = old.stdout.strip()
        if git(path, 'merge-base', '--is-ancestor', previous, head, env=env, check=False).returncode:
            raise ValueError('Task branch has separate history; kept worktree')
        if 'branch ' + ref in git(path, 'worktree', 'list', '--porcelain', env=env).stdout.splitlines():
            raise ValueError('Task branch is checked out elsewhere; kept worktree')
    else:
        previous = '0' * len(head)
    # A concurrent branch update must fail rather than discard its new commits.
    git(path, 'update-ref', ref, head, previous, env=env)


def inspect(workspace, row, env=None, cache=None):
    result = {'link_id': str(row['id'])[:100], 'state': 'unknown', 'branch': None}
    env = safe_git.environment(env)
    try:
        path = safe_path(workspace, row['path'])
        if not path.exists():
            result['state'] = 'removed' if row['state'] == 'removed' else 'missing'
            return result
        if not (path / '.git').is_file():
            raise ValueError('Tracked path is not a Git worktree; left as it is')
        result['repo'] = git_credentials.repository_name(git(path, 'config', '--get', 'remote.origin.url', env=env).stdout.strip())
        if result['repo'] and (len(result['repo']) > 200 or not repositories.valid_name(result['repo'])):
            result['repo'] = None
            result['error'] = 'Invalid or oversized repository name'
        branch = git(path, 'symbolic-ref', '--short', 'HEAD', env=env).stdout.strip()
        result.update(state='present', dirty_files=len(git(path, 'status', '--porcelain', env=env).stdout.splitlines()),
                      last_commit=git(path, 'rev-parse', 'HEAD', env=env).stdout.strip()[:100])
        try:
            result['branch'] = checked_branch(branch)
        except ValueError:
            result['error'] = 'Invalid or oversized worktree branch'
        task_branch = row.get('branch')
        remote = 'refs/remotes/origin/' + task_branch if task_branch else ''
        if remote and git(path, 'show-ref', '--verify', remote, env=env, check=False).returncode == 0:
            counts = git(path, 'rev-list', '--left-right', '--count', 'HEAD...' + remote, env=env).stdout
            result['ahead'], result['behind'] = map(int, counts.split())
        else:
            result['ahead'] = int(git(path, 'rev-list', '--count', 'HEAD', '--not', '--remotes=origin', env=env).stdout)
            result['behind'] = 0
        # File statistics are expensive on dependency folders; refresh at most every ten minutes.
        cached = (cache or {}).get(row['id'])
        if not cached or time.monotonic() - cached[0] >= 600:
            size, activity = 0, 0
            for root, dirs, files in os.walk(path, followlinks=False):
                dirs[:] = [d for d in dirs if not (Path(root) / d).is_symlink()]
                for filename in files:
                    file = Path(root) / filename
                    if not file.is_symlink():
                        stat = file.stat()
                        size += stat.st_size
                        activity = max(activity, stat.st_mtime)
            cached = (time.monotonic(), round(size / 1024 ** 2, 1), activity)
            if cache is not None:
                cache[row['id']] = cached
        result['size_mb'], result['last_activity'] = cached[1:]
    except (ValueError, OSError, subprocess.SubprocessError):
        result['error'] = 'Could not inspect worktree; check disk space, Git state and workspace permissions'
    return result


_BUILD = {'node_modules', '.venv', 'venv', 'dist', 'build', 'target', '.next', '__pycache__', '.cache', 'coverage'}
_SECRET = ('.env*', '*.pem', '*.key', 'id_rsa*', 'credentials*', '*.p12')


def _act(workspace, row, action, env):
    env = safe_git.environment(env)
    path = safe_path(workspace, row['path'])
    if action == 'remove':
        if not path.exists():
            # Prune even when the folder was removed outside Tico.
            base = Path(workspace) / 'repos' / row['repo'].lower().replace('/', '__')
            if (base.parent.is_symlink() or base.is_symlink() or (base / '.git').is_symlink()
                    or base.resolve().parent != base.parent.resolve()):
                raise ValueError('Worktree base points outside repos')
            if base.exists():
                git(base, 'worktree', 'prune', '--expire', 'now', env=env)
            return 'removed'
        branch = checked_branch(row['branch'])
        if not (path / '.git').is_file():
            raise ValueError('Tracked path is not a worktree; left as it is')
        common = Path(git(path, 'rev-parse', '--path-format=absolute', '--git-common-dir', env=env).stdout.strip()).resolve()
        if Path(workspace).resolve() not in common.parents:
            raise ValueError('Worktree base is outside the team workspace')
        base = common.parent
        default = row.get('default_branch')
        origin_head = git(base, 'symbolic-ref', '--short', 'refs/remotes/origin/HEAD', env=env, check=False).stdout.strip().removeprefix('origin/')
        defaults = {name for name in (default, origin_head) if name}
        if not defaults:
            raise ValueError('Repository default branch is unknown; refresh Repositories before cleanup')
        git(base, 'worktree', 'prune', '--expire', 'now', env=env)
        ignored = git(path, 'ls-files', '--others', '--ignored', '--exclude-standard', '-z', env=env).stdout.split('\0')
        if any(name and not any(part in _BUILD for part in Path(name).parts) for name in ignored):
            raise ValueError('kept: ignored files')
        dirty = git(path, 'status', '--porcelain', env=env).stdout.strip()
        wip = wip_branch(row)
        if wip in defaults:
            raise ValueError('Snapshot branch matches the default branch; kept worktree')
        current = git(path, 'symbolic-ref', '--short', 'HEAD', env=env).stdout.strip()
        if dirty:
            names = (git(path, 'diff', 'HEAD', '--name-only', '-z', env=env).stdout
                     + git(path, 'ls-files', '--others', '--exclude-standard', '-z', env=env).stdout).split('\0')
            skipped = [name for name in names if name and (any(fnmatch.fnmatch(Path(name).name.lower(), pat) for pat in _SECRET)
                       or (path / name).is_symlink() or ((path / name).exists() and (path / name).stat().st_size > 20 * 1024 ** 2))]
            if skipped:
                row['skipped_files'] = [name[:1000] for name in skipped[:100]]
                raise ValueError('kept: skipped unsafe or oversized files: ' + ', '.join(skipped)[:150])
            # Divergent HEAD must never replace the task branch, even after a successful snapshot push.
            exists = git(path, 'show-ref', '--verify', 'refs/heads/' + branch, env=env, check=False).returncode == 0
            if exists and git(path, 'merge-base', '--is-ancestor', branch, 'HEAD', env=env, check=False).returncode:
                raise ValueError('Task branch has separate history; kept worktree to preserve unpushed commits')
            if current != wip:
                if git(path, 'show-ref', '--verify', 'refs/heads/' + wip, env=env, check=False).returncode == 0:
                    if git(path, 'merge-base', '--is-ancestor', wip, 'HEAD', env=env, check=False).returncode:
                        raise ValueError('Saved work has separate history; kept worktree')
                git(path, 'switch', '-C', wip, env=env)
            git(path, 'add', '--all', env=env)
            from . import redact
            patch = git(path, 'diff', '--cached', env=env).stdout
            known = redact.for_turn(env)
            possible_secret = re.search(r'-----BEGIN (?:[A-Z ]+ )?PRIVATE KEY-----|(?:gh[pousr]_|github_pat_)[A-Za-z0-9_]{20,}|AKIA[0-9A-Z]{16}|sk-(?:proj-|ant-)?[A-Za-z0-9_-]{24,}', patch)
            if redact.scrub_log(patch) != patch or known and known.holds(patch.encode()) or possible_secret:
                raise ValueError('Possible secret in unsaved changes; kept worktree')
            git(path, '-c', 'user.name=Tico', '-c', 'user.email=bot@example.com', 'commit', '-m', 'Save task work before cleanup', env=env)
            git(path, 'push', 'origin', 'HEAD:refs/heads/' + wip, env=env)
            if branch not in defaults:
                fast_forward(path, branch, 'HEAD', env)
        else:
            # Retrying a failed snapshot push must still save its history.
            if current == wip:
                git(path, 'push', 'origin', 'HEAD:refs/heads/' + wip, env=env)
                if branch not in defaults:
                    if git(path, 'merge-base', '--is-ancestor', branch, 'HEAD', env=env, check=False).returncode:
                        raise ValueError('Task branch has separate history; kept worktree')
                    fast_forward(path, branch, 'HEAD', env)
            elif not row.get('prs_finished'):
                if int(git(path, 'rev-list', '--count', 'HEAD', '--not', '--remotes=origin', env=env).stdout):
                    if current != branch or branch in defaults:
                        raise ValueError('Unpushed history on another or default branch; kept worktree')
                    git(path, 'push', 'origin', branch + ':refs/heads/' + branch, env=env)
        git(base, 'worktree', 'remove', str(path), env=env)
        return 'removed'
    branch = checked_branch(row['branch'])
    disk_floor(workspace)
    if path.exists():
        if inspect(workspace, {**row, 'id': row.get('id') or row['link_id']}, env).get('state') != 'present':
            raise ValueError('Restore path already exists and is not a worktree')
        return 'present'
    base, default = repositories.worktree_base(workspace, row, env)
    git(base, 'worktree', 'prune', '--expire', 'now', env=env)
    isolation.mkdir(path.parent, mode=0o755)
    local = git(base, 'show-ref', '--verify', 'refs/heads/' + branch, env=env, check=False).returncode == 0
    task_remote = remote_branch(base, branch, env)
    saved = remote_branch(base, wip_branch(row), env)
    # Read the legacy snapshot too when upgrading an existing install.
    legacy = remote_branch(base, 'wip/' + row['task_id'][:8], env) if not saved else None
    saved = saved or legacy
    start = branch if local else task_remote or 'origin/' + default
    if saved and (not (local or task_remote) or git(base, 'merge-base', '--is-ancestor', start, saved, env=env, check=False).returncode == 0):
        start = saved
    if local:
        if start != branch:
            fast_forward(base, branch, start, env)
        git(base, 'worktree', 'add', str(path), branch, env=env)
    else:
        git(base, 'worktree', 'add', '--no-track', '-b', branch, str(path), start, env=env)
    return 'present'


def act(workspace, row, action, env):
    with locked(workspace, row.get('id') or row['link_id']):
        return _act(workspace, row, action, env)


class Worktrees:
    def __init__(self, workspace, client, idle=lambda: True, environment=lambda bot: safe_git.process_environment()):
        self.workspace, self.client, self.idle = workspace, client, idle
        self.environment = environment
        self.retry = {}
        self.stats = {}
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
        failed = set()
        errors = {key: error for key, error in self.errors.items() if any(r["id"] == key for r in rows)}
        for action in actions:
            if not self.idle():
                break
            row = next((r for r in rows if r['id'] == action['link_id']), None)
            if not row or not row.get('repo') or time.monotonic() < self.retry.get(row['id'], (0, 0))[0]:
                continue
            closed = row['task_status'] in ('done', 'closed', 'declined') or row['bot_state'] == 'archived' or json.loads(row.get('detail_json') or '{}').get('delete_requested')
            if action['action'] == 'remove' and not closed or action['action'] == 'restore' and closed:
                continue
            env = safe_git.environment(self.environment(row['owner']))
            action_row = {}
            try:
                granted = self.client.post(f'runners/me/worktrees/{row["id"]}/token')
                if not granted.get('token'):
                    raise ValueError('No repository credential for this worktree')
                env.update(git_credentials.environment(granted['token']))
                repo = next((r for r in self.client.get('runners/me/repositories')['repositories'] if r['full_name'].lower() == row['repo'].lower()), {})
                action_row = {**row, **repo, **action, 'full_name': row['repo']}
                state = act(self.workspace, action_row, action['action'], env)
                self.client.patch(f'tasks/{row["task_id"]}/links/{row["id"]}', {'state': state, 'cleanup': action['action'] == 'remove', 'setup_pending': action['action'] == 'restore'})
                row['state'] = state
                errors.pop(row['id'], None)
                self.retry.pop(row['id'], None)
            except (ValueError, APIError) as exc:
                failed.add(row['id'])
                if action_row.get('skipped_files'):
                    try:
                        self.client.patch(f'tasks/{row["task_id"]}/links/{row["id"]}', {'skipped_files': action_row['skipped_files']})
                    except Exception:
                        pass
                errors[row['id']] = ('Worktree action failed; history kept. ' + str(exc))[:300]
            except Exception:
                failed.add(row['id'])
                errors[row['id']] = 'Worktree action failed; history kept. Check repository access, network, disk space and permissions'
        for key in failed:
            failures = self.retry.get(key, (0, 0))[1] + 1
            self.retry[key] = (time.monotonic() + min(300 * 2 ** min(failures - 1, 7), 21600), failures)
        self.stats = {key: value for key, value in self.stats.items() if any(r['id'] == key for r in rows)}
        self.retry = {key: value for key, value in self.retry.items() if any(r['id'] == key for r in rows)}
        reports = [inspect(self.workspace, r, self.environment(r['owner']), self.stats) for r in rows]
        for report in reports:
            if report['link_id'] in errors:
                report['error'] = errors[report['link_id']]
        with self.lock:
            self.errors = errors
            self.reports = reports

    def close(self):
        self.pool.shutdown(wait=False, cancel_futures=True)
