"""Base clones for this computer; independent of bot readiness and turn credentials."""

import concurrent.futures
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import threading
import time

from . import git_credentials, isolation

FETCH_INTERVAL = 15 * 60
REMOVE_AFTER = 30 * 86400
GB = 1024 ** 3


def valid_name(name):
    return isinstance(name, str) and re.fullmatch(r"[A-Za-z0-9-]+/[A-Za-z0-9_.-]+", name) and name.split('/')[1] not in ('.', '..')


class Repositories:
    def __init__(self, workspace, state_file, client):
        self.root = Path(workspace) / 'repos'
        self.state_file = Path(state_file)
        self.client = client
        self.lock = threading.RLock()
        self.pool = concurrent.futures.ThreadPoolExecutor(max_workers=1)
        self.pending = None
        self.visible = False
        try:
            saved = json.loads(self.state_file.read_text())
            self.rows = {name: row for name, row in saved.items() if valid_name(name) and isinstance(row, dict)}
        except (OSError, ValueError, AttributeError):
            self.rows = {}

    def close(self):
        self.pool.shutdown(wait=True)

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
            due = [name for name in wanted if now - self.rows[name].get('attempted_at', 0) >= FETCH_INTERVAL
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
                    linked = path / '.git' / 'worktrees'
                    if linked.is_symlink() or linked.exists() and any(linked.iterdir()):
                        continue
                    shutil.rmtree(path)
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

    def update(self, name, repo, now):
        token = ''
        created = False
        try:
            path = self.path(name)
            exists = path.exists()
            if exists and (not (self.rows[name].get('managed') or (path / '.git' / 'tico-managed').is_file()) or not (path / '.git').is_dir() or (path / '.git').is_symlink()):
                raise ValueError('Repository folder already exists and is not a managed base clone; left as it is')
            if not exists:
                usage = shutil.disk_usage(self.root if self.root.exists() else self.root.parent)
                floor = max(5 * GB, usage.total * .1)
                if usage.free < floor:
                    with self.lock:
                        self.rows[name].update(state='disk_low', error=f'Not enough disk to clone {repo["full_name"]}: {usage.free / GB:.1f} GB free, needs {floor / GB:g} GB. Free space on this volume')
                    return
            granted = self.client.post('runners/me/repositories/token')
            token = granted.get('token') or ''
            if not token or name not in {n.lower() for n in granted.get('repositories', [])}:
                raise ValueError('No GitHub read token for this repository; check the GitHub connection')
            env = {**os.environ, **git_credentials.environment(token)}
            url = f'https://github.com/{repo["full_name"]}.git'
            prefix = ['git', '-c', 'http.followRedirects=false']
            if exists:
                branch = repo.get('default_branch') or '*'
                command = [*prefix, '-C', str(path), 'fetch', '--quiet', '--prune', '--no-tags', '--', url,
                           f'+refs/heads/{branch}:refs/remotes/origin/{branch}']
            else:
                isolation.mkdir(self.root, mode=0o755)
                created = True
                with self.lock:
                    self.rows[name].update(state="cloning", managed=True)
                    self.save()
                command = [*prefix, 'clone', '--quiet', '--single-branch']
                if repo.get('default_branch'):
                    command += ['--branch', repo['default_branch']]
                command += ['--', url, str(path)]
            done = isolation.run(command, capture_output=True, text=True, stdin=subprocess.DEVNULL, env=env, timeout=120)
            if done.returncode:
                # Git's stderr may contain credentials or local secrets; keep them out of reports.
                raise ValueError(f'Git {"fetch" if exists else "clone"} failed (exit {done.returncode}); check GitHub access, disk space and network')
            (path / '.git' / 'tico-managed').touch()
            isolation.chown(path / '.git' / 'tico-managed')
            size = sum(p.stat().st_size for root, dirs, files in os.walk(path, followlinks=False)
                       for p in (Path(root) / f for f in files) if not p.is_symlink()) / (1024 ** 2)
            with self.lock:
                self.rows[name].update(state='cloned', managed=True, fetched_at=now,
                                       last_fetch=datetime.fromtimestamp(now, timezone.utc).isoformat(), size_mb=round(size, 1))
                self.rows[name].pop('error', None)
        except Exception as exc:
            if created:
                try:
                    if path.exists():
                        shutil.rmtree(self.path(name))
                except (OSError, ValueError):
                    pass
            if isinstance(exc, subprocess.TimeoutExpired):
                error = 'Git timed out after 120 seconds; check the network and retry'
            elif isinstance(exc, ValueError):
                error = str(exc).replace(token, '[redacted]') if token else str(exc)
            elif isinstance(exc, OSError) and exc.errno == 28:
                error = 'Not enough disk space; free space on the workspace volume'
            else:
                error = 'Could not sync base clone; check GitHub connection, network, disk space and folder permissions'
            with self.lock:
                self.rows[name].update(state='failed', error=error)


def worktree_base(workspace, repo, env):
    """Fetch a managed base using this bot's own credentials, also usable inside a turn."""
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
        current = isolation.run(['git', '-C', str(path), 'config', '--get', 'remote.origin.url'], capture_output=True, text=True, timeout=15)
        if not git_credentials._same_repository(current.stdout.strip(), name):
            raise ValueError('Base clone remote does not match this repository')
    else:
        command = ['git', 'clone', '--quiet', '--single-branch']
        if repo.get('default_branch'):
            command += ['--branch', repo['default_branch']]
        done = isolation.run([*command, '--', f'https://github.com/{name}.git', str(path)], env=env, capture_output=True, text=True, timeout=120)
        if done.returncode:
            if path.exists():
                shutil.rmtree(path)
            raise ValueError('Git clone failed; check repository access, network and disk space')
        (path / '.git' / 'tico-managed').touch()
        isolation.chown(path / '.git' / 'tico-managed')
    branch = repo.get('default_branch')
    if not branch:
        result = isolation.run(['git', '-C', str(path), 'symbolic-ref', '--short', 'refs/remotes/origin/HEAD'], capture_output=True, text=True, timeout=15)
        branch = result.stdout.strip().removeprefix('origin/')
    if not branch or branch.startswith('-'):
        raise ValueError('Repository default branch is missing; refresh Repositories')
    done = isolation.run(['git', '-C', str(path), 'fetch', '--quiet', '--no-tags', 'origin',
                         f'+refs/heads/{branch}:refs/remotes/origin/{branch}'], env=env, capture_output=True, text=True, timeout=120)
    if done.returncode:
        raise ValueError('Git fetch failed; check repository access, network and disk space')
    path.touch()
    return path, branch
