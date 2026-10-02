"""Base clones for this computer; independent of bot readiness and turn credentials."""

import concurrent.futures
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import shutil
import signal
import subprocess
import threading
import time
import tempfile

from . import git_credentials, isolation, safe_git

FETCH_INTERVAL = 15 * 60
REMOVE_AFTER = 30 * 86400
GB = 1024 ** 3


def valid_name(name):
    return isinstance(name, str) and re.fullmatch(r"[A-Za-z0-9-]+/[A-Za-z0-9_.-]+", name) and name.split('/')[1] not in ('.', '..')


class Repositories:
    def __init__(self, workspace, state_file, client):
        self.root = Path(workspace) / 'repos'
        self.state_file = Path(state_file)
        self.mirrors = self.state_file.parent / 'mirrors'
        self.client = client
        self.lock = threading.RLock()
        self.pool = concurrent.futures.ThreadPoolExecutor(max_workers=1)
        self.pending = None
        self.visible = False
        self.stopping = threading.Event()
        self.process = None
        try:
            saved = json.loads(self.state_file.read_text())
            self.rows = {name: row for name, row in saved.items() if valid_name(name) and isinstance(row, dict)}
        except (OSError, ValueError, AttributeError):
            self.rows = {}

    def close(self):
        self.stopping.set()
        with self.lock:
            process = self.process
        if process and process.poll() is None:
            self.kill_git(process)
        self.pool.shutdown(wait=False, cancel_futures=True)

    @staticmethod
    def kill_git(process):
        try:
            os.killpg(process.pid, signal.SIGTERM)
            try:
                process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                pass
            # The parent may have exited while a credential helper kept running.
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except (ProcessLookupError, PermissionError):
                pass
            process.wait(timeout=2)
        except (ProcessLookupError, PermissionError, subprocess.TimeoutExpired):
            pass

    def run_git(self, command, *, env, timeout, bot=False):
        with tempfile.TemporaryDirectory(prefix='tico-git-hooks-') as hooks:
            os.chmod(hooks, 0o755)
            command = [command[0], '-c', 'core.hooksPath=' + hooks, *command[1:]]
            with self.lock:
                if self.stopping.is_set():
                    raise ValueError('Repository sync interrupted by computer shutdown')
                launch = isolation.popen if bot else subprocess.Popen
                process = launch(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                           text=True, stdin=subprocess.DEVNULL, env=env, cwd=hooks, start_new_session=True)
                self.process = process
            deadline = time.monotonic() + timeout
            try:
                while True:
                    if self.stopping.is_set():
                        self.kill_git(process)
                        raise ValueError('Repository sync interrupted by computer shutdown')
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        self.kill_git(process)
                        raise subprocess.TimeoutExpired(command, timeout)
                    try:
                        out, err = process.communicate(timeout=min(.2, remaining))
                        return subprocess.CompletedProcess(command, process.returncode, out, err)
                    except subprocess.TimeoutExpired:
                        continue
            finally:
                with self.lock:
                    self.process = None

    def path(self, name):
        path = self.root / name.lower().replace('/', '__')
        if self.root.is_symlink() or path.is_symlink() or path.resolve().parent != self.root.resolve():
            raise ValueError('Repository folder points outside repos; left as it is')
        return path

    def save(self):
        self.state_file.parent.mkdir(parents=True, exist_ok=True)
        temp = self.state_file.with_suffix('.tmp')
        temp.write_text(json.dumps(self.rows))
        temp.replace(self.state_file)

    def report(self):
        with self.lock:
            return [self.report_row(row) for row in self.rows.values()] if self.visible else []

    def inspect(self):
        """Doctor reads current repositories and saved status without cloning or cleanup."""
        try:
            repos = self.client.get("runners/me/repositories")["repositories"]
            return [self.report_row(self.rows.get(repo["full_name"].lower(), {
                "full_name": repo["full_name"], "state": "cloning", "last_fetch": None, "size_mb": 0}))
                    for repo in repos if valid_name(repo.get("full_name"))]
        except Exception:
            return []

    @staticmethod
    def report_row(row):
        return {k: row.get(k) for k in ("full_name", "state", "last_fetch", "size_mb", "error") if k in row}

    def poll(self):
        if self.stopping.is_set():
            return self.report()
        # Failed requests are not an empty list: they must never start the removal clock.
        try:
            reply = self.client.get('runners/me/repositories')
            repos = reply['repositories']
            if not isinstance(repos, list) or any(not isinstance(r, dict) or not valid_name(r.get('full_name')) for r in repos):
                return None
        except Exception:
            self.visible = False
            return None
        self.visible = True
        with self.lock:
            if self.pending is not None and not self.pending.done():
                return self.report()
            now = time.time()
            wanted = {r['full_name'].lower(): r for r in repos}
            for marker in self.root.glob('*/.git/tico-managed'):
                name = marker.parent.parent.name.replace('__', '/', 1)
                if valid_name(name) and not marker.is_symlink():
                    self.rows.setdefault(name, {'full_name': name, 'state': 'cloned', 'managed': True, 'left_at': now, 'size_mb': 0})
            for name, row in list(self.rows.items()):
                if name in wanted:
                    row.pop('left_at', None)
                elif row.get('state') == 'removed':
                    del self.rows[name]
                else:
                    row.setdefault('left_at', now)
            for name, repo in wanted.items():
                self.rows.setdefault(name, {'full_name': repo['full_name'], 'state': 'cloning', 'last_fetch': None, 'size_mb': 0})
            try:
                self.save()
            except OSError:
                for row in self.rows.values():
                    row.update(state="failed", error="Could not save repository state; free disk space and check permissions")
                return self.report()
            # One job per cycle, chosen fairly so a failed clone cannot hold up the others.
            due = [name for name in wanted if now - self.rows[name].get('attempted_at', 0) >= self.rows[name].get('retry_delay', FETCH_INTERVAL)
                   and now - self.rows[name].get('fetched_at', 0) >= FETCH_INTERVAL]
            due.sort(key=lambda name: self.rows[name].get('attempted_at', 0))
            selected = due[0] if due else None
            if selected:
                self.rows[selected]['attempted_at'] = now
            self.pending = self.pool.submit(self.sync, wanted, selected, now)
            return self.report()

    def sync(self, wanted, selected, now):
        with self.lock:
            stale = [name for name, row in self.rows.items() if name not in wanted
                     and now - row.get('left_at', now) >= REMOVE_AFTER]
        for name in stale:
            try:
                path = self.path(name)
                if self.rows[name].get('managed') and path.exists():
                    kept = base_kept(path)
                    if kept:
                        self.rows[name].update(error=kept)
                        continue
                    shutil.rmtree(path)
                mirror = self.mirror_path(name)
                if mirror.exists():
                    shutil.rmtree(mirror)
                with self.lock:
                    self.rows[name].update(state='removed', size_mb=0)
                    self.rows[name].pop('error', None)
            except (OSError, ValueError):
                with self.lock:
                    self.rows[name].update(state='failed', error='Could not remove base clone safely; check repos folder permissions')
        if selected:
            self.update(selected, wanted[selected], now)
        with self.lock:
            try:
                self.save()
            except OSError:
                # Disk exhaustion must not break the next heartbeat or any bot.
                if selected:
                    self.rows[selected].update(state='failed', error='Could not save repository state; free disk space and check permissions')

    def mirror_path(self, name):
        path = self.mirrors / (name.lower().replace('/', '__') + '.git')
        if self.mirrors.is_symlink() or path.is_symlink():
            raise ValueError('Mirror contains a symlink; repair the computer mirror folder')
        if self.mirrors.exists() and isolation.enabled():
            stats = self.mirrors.stat()
            if stats.st_uid != os.geteuid() or stats.st_mode & 0o022:
                raise ValueError('Mirror folder is writable by another user; repair the computer mirror permissions')
        if path.exists():
            for root, dirs, files in os.walk(path, followlinks=False):
                for entry in (Path(root), *(Path(root) / n for n in (*dirs, *files))):
                    stats = entry.lstat()
                    if entry.is_symlink():
                        raise ValueError('Mirror contains a symlink; repair the computer mirror folder')
                    if isolation.enabled() and (stats.st_uid != os.geteuid() or stats.st_mode & 0o022):
                        raise ValueError('Mirror is writable by another user; repair the computer mirror permissions')
        return path

    @staticmethod
    def mirror_permissions(path):
        for root, dirs, files in os.walk(path, followlinks=False):
            os.chmod(root, 0o755)
            for name in files:
                os.chmod(Path(root) / name, 0o644)

    def update(self, name, repo, now):
        token = ''
        created = False
        try:
            path = self.path(name)
            exists = path.exists()
            if exists and (not (self.rows[name].get('managed') or (path / '.git' / 'tico-managed').is_file()) or not (path / '.git').is_dir() or (path / '.git').is_symlink()):
                raise ValueError('Repository folder already exists and is not a managed base clone; left as it is')
            volumes = (self.root if self.root.exists() else self.root.parent,
                       self.mirrors if self.mirrors.exists() else self.state_file.parent)
            volume, usage = min(((p, shutil.disk_usage(p)) for p in volumes), key=lambda item: item[1].free)
            size_kb = int(repo.get('size_kb') or self.rows[name].get('size_mb', 0) * 1024)
            floor = 5 * GB + 2 * size_kb * 1024
            if usage.free < floor:
                with self.lock:
                    self.rows[name].update(state='disk_low', error=f'Not enough disk to {"fetch" if exists else "clone"} {repo["full_name"]}: {usage.free / GB:.1f} GB free, needs {floor / GB:g} GB. Free space on {volume}')
                return
            from .service import Runner
            clean = Runner.credential_environment(None, None)
            clean.update(GIT_CONFIG_NOSYSTEM='1', GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_SYSTEM=os.devnull,
                         GIT_TERMINAL_PROMPT='0')
            mirror = self.mirror_path(name)
            self.mirrors.mkdir(mode=0o755, parents=True, exist_ok=True)
            os.chmod(self.mirrors, 0o755)
            granted = self.client.post('runners/me/repositories/token')
            token = granted.get('token') or ''
            if not token or name not in {n.lower() for n in granted.get('repositories', [])}:
                raise ValueError('No GitHub read token for this repository; check the GitHub connection')
            env = {**clean, **git_credentials.environment(token)}
            url = f'https://github.com/{repo["full_name"]}.git'
            prefix = ['git', '-c', 'core.fsmonitor=false', '-c', 'gc.auto=0', '-c', 'maintenance.auto=false',
                      '-c', 'http.followRedirects=false', '-c', 'http.sslVerify=true',
                      '-c', 'protocol.allow=never', '-c', 'protocol.https.allow=always', '-c', 'protocol.file.allow=never']
            timeout = max(900, min(7200, size_kb // 1024))
            branch = repo.get('default_branch')
            if not branch:
                result = self.run_git([*prefix, 'ls-remote', '--symref', url, 'HEAD'], env=env, timeout=timeout)
                match = re.search(r'^ref: refs/heads/(.+)\tHEAD$', result.stdout, re.M)
                if result.returncode or not match:
                    raise ValueError('Could not find the default branch; check GitHub access')
                branch = match.group(1)
            if not mirror.exists():
                done = self.run_git([*prefix, 'init', '--bare', '--quiet', '--initial-branch=' + branch, str(mirror)], env=clean, timeout=10)
                if done.returncode:
                    raise ValueError('Could not create mirror; check disk space and permissions')
            # Only supervisor-owned Git config is read with an installation token.
            config = self.run_git([*prefix, '-C', str(mirror), 'config', '--no-includes', '--name-only',
                                   '--get-regexp', r'^(http|include|includeif)\.'], env=clean, timeout=10)
            if config.returncode not in (0, 1):
                raise ValueError('Could not inspect mirror Git config')
            for key in config.stdout.splitlines():
                if key.lower().startswith(('include.', 'includeif.')):
                    raise ValueError('Mirror Git config includes another file; remove the include before fetching')
                setting = key.rsplit('.', 1)[-1].lower()
                value = 'true' if setting == 'sslverify' else (clean.get('GIT_SSL_CAINFO', '') if setting == 'sslcainfo' else '')
                prefix += ['-c', key + '=' + value]
            done = self.run_git([*prefix, '-C', str(mirror), 'fetch', '--quiet', '--prune', '--no-tags',
                                 '--no-write-fetch-head', '--', url, f'+refs/heads/{branch}:refs/heads/{branch}'],
                                env=env, timeout=timeout)
            if done.returncode:
                raise ValueError(f'Git mirror fetch failed (exit {done.returncode}); check GitHub access, disk space and network')
            done = self.run_git([*prefix, '-C', str(mirror), 'symbolic-ref', 'HEAD', 'refs/heads/' + branch], env=clean, timeout=10)
            if done.returncode:
                raise ValueError('Could not set mirror default branch')
            self.mirror_permissions(mirror)
            # Bot-owned directories are touched only by unprivileged Git, without a token.
            local = ['git', '-c', 'safe.directory=' + str(mirror.resolve()),
                     '-c', 'safe.directory=' + str(path.resolve()), '-c', 'core.fsmonitor=false', '-c', 'gc.auto=0', '-c', 'maintenance.auto=false',
                     '-c', 'protocol.allow=never', '-c', 'protocol.file.allow=always']
            if not exists:
                isolation.mkdir(self.root, mode=0o755)
                created = True
                with self.lock:
                    self.rows[name].update(state='cloning', managed=True)
                    self.save()
                done = self.run_git([*local, 'clone', '--quiet', '--single-branch', '--no-hardlinks',
                                     '--origin', 'tico-mirror', '--branch', branch, '--', mirror.as_uri(), str(path)],
                                    env=clean, timeout=timeout, bot=True)
                if done.returncode:
                    raise ValueError('Could not clone local mirror; check disk space and permissions')
            else:
                done = self.run_git([*local, '-C', str(path), 'rev-parse', '--git-dir'], env=clean, timeout=10, bot=True)
                if done.returncode:
                    raise ValueError('Base clone is not a working Git repository; repair it without deleting local work')
            for key, value in [('remote.tico-mirror.url', mirror.as_uri()),
                               ('remote.tico-mirror.fetch', f'+refs/heads/{branch}:refs/remotes/tico-mirror/{branch}'),
                               ('remote.origin.url', url), ('remote.origin.pushurl', url),
                               ('remote.origin.fetch', '+refs/heads/*:refs/remotes/origin/*'),
                               ('branch.' + branch + '.remote', 'origin'), ('branch.' + branch + '.merge', 'refs/heads/' + branch)]:
                done = self.run_git([*local, '-C', str(path), 'config', '--local', '--replace-all', key, value], env=clean, timeout=10, bot=True)
                if done.returncode:
                    raise ValueError('Could not configure base clone mirror; check its Git config and permissions')
            done = self.run_git([*local, '-C', str(path), 'fetch', '--quiet', '--no-tags', '--no-write-fetch-head',
                                 '--', mirror.as_uri(), f'+refs/heads/{branch}:refs/remotes/origin/{branch}',
                                 f'+refs/heads/{branch}:refs/remotes/tico-mirror/{branch}'],
                                env=clean, timeout=timeout, bot=True)
            if done.returncode:
                # Git's stderr may contain credentials or local secrets; keep them out of reports.
                raise ValueError(f'Git {"fetch" if exists else "clone"} failed (exit {done.returncode}); check GitHub access, disk space and network')
            done = self.run_git([*local, '-C', str(path), 'symbolic-ref', 'refs/remotes/origin/HEAD', 'refs/remotes/origin/' + branch], env=clean, timeout=10, bot=True)
            if done.returncode:
                raise ValueError('Could not record base default branch; check permissions')
            mark_managed(path, clean)
            size = sum(p.stat().st_size for root, dirs, files in os.walk(path, followlinks=False)
                       for p in (Path(root) / f for f in files) if not p.is_symlink()) / (1024 ** 2)
            with self.lock:
                self.rows[name].update(state='cloned', managed=True, fetched_at=now,
                                       last_fetch=datetime.fromtimestamp(now, timezone.utc).isoformat(), size_mb=round(size, 1))
                self.rows[name].pop('error', None)
                self.rows[name].update(failures=0, retry_delay=FETCH_INTERVAL)
        except Exception as exc:
            if created:
                try:
                    if path.exists() and not base_kept(path):
                        shutil.rmtree(self.path(name))
                except (OSError, ValueError):
                    pass
            if isinstance(exc, subprocess.TimeoutExpired):
                error = f'Git timed out after {exc.timeout} seconds; check the network'
            elif isinstance(exc, ValueError):
                error = str(exc).replace(token, '[redacted]') if token else str(exc)
            elif isinstance(exc, OSError) and exc.errno == 28:
                error = 'Not enough disk space; free space on the workspace volume'
            else:
                error = 'Could not sync base clone; check GitHub connection, network, disk space and folder permissions'
            with self.lock:
                failures = self.rows[name].get('failures', 0) + 1
                delay = (900, 3600, 21600)[min(failures - 1, 2)]
                self.rows[name].update(state='failed', failures=failures, retry_delay=delay, attempted_at=time.time(),
                                       error=f'{error}. Retrying in {delay // 60} minutes')


def worktree_base(workspace, repo, env):
    """Fetch a managed base using this bot's own credentials, also usable inside a turn."""
    env = safe_git.environment(env)
    name = repo['full_name']
    if not valid_name(name):
        raise ValueError('Invalid repository name')
    root = Path(workspace) / 'repos'
    path = root / name.lower().replace('/', '__')
    if root.is_symlink() or path.is_symlink() or path.resolve().parent != root.resolve():
        raise ValueError('Base clone points outside repos')
    isolation.mkdir(root, mode=0o755)
    if path.exists():
        if not (path / '.git').is_dir() or (path / '.git').is_symlink():
            raise ValueError('Base clone folder is not a Git repository')
        current = isolation.run([*safe_git.PREFIX, '-C', str(path), 'config', '--get', 'remote.origin.url'], env=env, capture_output=True, text=True, timeout=15)
        if not git_credentials._same_repository(current.stdout.strip(), name):
            raise ValueError('Base clone remote does not match this repository')
    else:
        command = [*safe_git.PREFIX, '-c', 'protocol.allow=never', '-c', 'protocol.https.allow=always', '-c', 'http.followRedirects=false', '-c', 'http.sslVerify=true', 'clone', '--quiet', '--single-branch']
        if repo.get('default_branch'):
            command += ['--branch', repo['default_branch']]
        try:
            done = isolation.run([*command, '--', f'https://github.com/{name}.git', str(path)], env=env, capture_output=True, text=True, timeout=120)
        except (OSError, subprocess.SubprocessError):
            discard_failed_clone(path)
            raise ValueError('Git clone failed; check repository access, network and disk space') from None
        if done.returncode:
            discard_failed_clone(path)
            raise ValueError('Git clone failed; check repository access, network and disk space')
        mark_managed(path, env)
    branch = repo.get('default_branch')
    if not branch:
        result = isolation.run([*safe_git.PREFIX, '-C', str(path), 'symbolic-ref', '--short', 'refs/remotes/origin/HEAD'], env=env, capture_output=True, text=True, timeout=15)
        branch = result.stdout.strip().removeprefix('origin/')
    if not branch or branch.startswith('-') or isolation.run([*safe_git.PREFIX, 'check-ref-format', '--branch', branch],
            env=env, capture_output=True, timeout=15).returncode:
        raise ValueError('Repository default branch is missing; refresh Repositories')
    mirror_url = isolation.run([*safe_git.PREFIX, '-C', str(path), 'config', '--get', 'remote.tico-mirror.url'],
                               env=env, capture_output=True, text=True, timeout=15).stdout.strip()
    source = mirror_url or 'origin'
    local_env = safe_git.process_environment(env) if mirror_url else env
    prefix = [*safe_git.PREFIX, '-c', 'protocol.allow=never', '-c', 'protocol.file.allow=always'] if mirror_url else [*safe_git.PREFIX, '-c', 'http.followRedirects=false']
    if mirror_url:
        from urllib.parse import urlparse, unquote
        prefix += ['-c', 'safe.directory=' + unquote(urlparse(mirror_url).path)]
    done = isolation.run([*prefix, '-C', str(path), 'fetch', '--quiet', '--no-tags', '--no-write-fetch-head', '--', source,
                         f'+refs/heads/{branch}:refs/remotes/origin/{branch}'], env=local_env, capture_output=True, text=True, timeout=120)
    if done.returncode:
        available = isolation.run([*safe_git.PREFIX, '-C', str(path), 'show-ref', '--verify', 'refs/remotes/origin/' + branch],
                                 env=local_env, capture_output=True, timeout=15)
        if available.returncode:
            raise ValueError('Git fetch failed; check repository access, network and disk space')
    mark_managed(path, local_env)
    # A normal git push then updates the task branch's tracking ref, rather than comparing it to main.
    done = isolation.run([*safe_git.PREFIX, '-C', str(path), 'config', 'remote.origin.fetch',
                          '+refs/heads/*:refs/remotes/origin/*'], env=env, capture_output=True, text=True, timeout=15)
    if done.returncode:
        raise ValueError('Could not configure task branch tracking')
    return path, branch


def discard_failed_clone(path):
    if not path.exists() or path.is_symlink():
        return
    if (path / '.git').exists():
        try:
            if base_kept(path):
                return
        except (ValueError, OSError):
            return
    shutil.rmtree(path)


def mark_managed(path, env):
    done = isolation.run(['/bin/sh', '-c', 'test ! -L .git/tico-managed && : > .git/tico-managed'],
                         cwd=str(path), env=safe_git.process_environment(env), capture_output=True, timeout=15)
    if done.returncode:
        raise ValueError('Could not mark managed base clone; check permissions')


def base_kept(path):
    if (path / '.git').is_symlink() or (path / '.git' / 'worktrees').is_symlink():
        raise ValueError('Base clone registrations point outside repos')
    env = safe_git.environment(safe_git.process_environment())
    prefix = [*safe_git.PREFIX, '-C', str(path)]
    done = isolation.run([*prefix, 'worktree', 'prune', '--expire', 'now'], env=env, capture_output=True, text=True, timeout=120)
    if done.returncode:
        raise ValueError('Could not prune base clone; repair without deleting local work')
    listing = isolation.run([*prefix, 'worktree', 'list', '--porcelain'], env=env, capture_output=True, text=True, timeout=15)
    if listing.returncode:
        raise ValueError('Could not inspect base clone worktrees')
    count = max(0, sum(line.startswith('worktree ') for line in listing.stdout.splitlines()) - 1)
    if count:
        return f'kept: {count} task worktrees'
    branches = isolation.run([*prefix, 'rev-list', '--count', '--branches', '--not', '--remotes'], env=env, capture_output=True, text=True, timeout=30)
    if branches.returncode:
        raise ValueError('Could not inspect local branches; repair without deleting local work')
    if int(branches.stdout.strip() or '0'):
        return 'kept: local branches with unpublished commits'
    refs = isolation.run([*prefix, 'for-each-ref', '--format=%(refname)', 'refs/heads', 'refs/remotes'], env=env, capture_output=True, text=True, timeout=15)
    if refs.returncode:
        raise ValueError('Could not inspect local branch names')
    names = refs.stdout.splitlines()
    remote_names = {name.split('/', 3)[3] for name in names if name.startswith('refs/remotes/') and len(name.split('/', 3)) == 4}
    if any(name.removeprefix('refs/heads/') not in remote_names for name in names if name.startswith('refs/heads/')):
        return 'kept: local branches absent from remotes'
    return None
