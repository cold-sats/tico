"""Real Git worktree lifecycle, using only temporary repositories and synthetic credentials."""
import os
from pathlib import Path
import shutil
import subprocess
from unittest import mock

import pytest

from clients.tico import APIError
from runner import worktrees as W
from runner.repositories import GB
from runner.service import Runner


def git(path, *args):
    return subprocess.run(['git', '-C', str(path), *args], check=True, capture_output=True, text=True).stdout.strip()


@pytest.fixture
def trees(tmp_path, monkeypatch):
    remote = tmp_path / 'remote.git'
    subprocess.run(['git', 'init', '--bare', '--initial-branch=main', str(remote)], check=True, capture_output=True)
    source = tmp_path / 'source'
    subprocess.run(['git', 'init', '--initial-branch=main', str(source)], check=True, capture_output=True)
    git(source, 'config', 'user.name', 'Sam')
    git(source, 'config', 'user.email', 'sam@example.com')
    (source / 'file').write_text('initial')
    git(source, 'add', '.')
    git(source, 'commit', '-m', 'Initial')
    git(source, 'remote', 'add', 'origin', str(remote))
    git(source, 'push', 'origin', 'main')
    workspace = tmp_path / 'workspace'
    base = workspace / 'repos' / 'org__product'
    base.parent.mkdir(parents=True)
    subprocess.run(['git', 'clone', str(remote), str(base)], check=True, capture_output=True)
    git(base, 'config', 'remote.origin.url', 'https://github.com/org/product.git')
    git(base, 'config', f'url.{remote}.insteadOf', 'https://github.com/org/product.git')
    monkeypatch.setattr(W.shutil, 'disk_usage', lambda p: shutil._ntuple_diskusage(100 * GB, 0, 100 * GB))
    monkeypatch.setenv('HUB_WORKSPACE', str(workspace))
    monkeypatch.setenv('HUB_BOT', 'engineer')
    monkeypatch.setenv('HUB_TASK_ID', '12345678abcdef')
    row = {'id': 'link1', 'link_id': 'link1', 'task_id': '12345678abcdef', 'path': 'tasks/12345678/org__product',
           'branch': 'tico/12345678-build', 'repo': 'org/product', 'full_name': 'org/product', 'default_branch': 'main',
           'state': 'present', 'owner': 'bot:engineer', 'setup_command': 'touch setup-ran'}
    client = mock.Mock()
    client.get.return_value = {'repositories': [{**row, 'access': 'write'}]}
    client.post.return_value = {'link_id': row['id'], 'branch': row['branch'], 'path': row['path']}
    return workspace, base, remote, row, client


def test_add_setup_report_attach_dirty_push_remove_restore(trees):
    workspace, base, remote, row, client = trees
    result = W.command(client, 'add', 'org/product')
    path = Path(result['workspace_path'])
    assert (path / 'setup-ran').exists()
    assert git(path, 'rev-parse', 'HEAD') == git(remote, 'rev-parse', 'main')
    (path / 'file').write_text('changed')
    report = W.inspect(workspace, row)
    assert report['state'] == 'present' and report['dirty_files'] == 2 and report['last_commit']
    attached = W.command(client, 'attach', str(path))
    assert attached['path'] == row['path']
    assert client.post.call_args.args[0].endswith('/worktrees/attach')
    assert W.act(workspace, row, 'remove', os.environ.copy()) == 'removed'
    assert not path.exists()
    saved = git(remote, 'show', 'wip/12345678:file')
    assert saved == 'changed'
    assert W.inspect(workspace, {**row, 'state': 'removed'})['state'] == 'removed'
    assert W.act(workspace, row, 'restore', os.environ.copy()) == 'present'
    assert git(path, 'symbolic-ref', '--short', 'HEAD') == row['branch']
    assert (path / 'file').read_text() == 'changed'
    assert (path / 'setup-ran').exists()


def test_failed_push_keeps_tree_and_retry_preserves_saved_branch(trees):
    workspace, base, remote, row, client = trees
    path = Path(W.command(client, 'add', 'org/product')['workspace_path'])
    (path / 'file').write_text('keep this')
    hook = remote / 'hooks' / 'pre-receive'
    hook.write_text('#!/bin/sh\nexit 1\n')
    hook.chmod(0o755)
    with pytest.raises(ValueError, match='push failed'):
        W.act(workspace, row, 'remove', os.environ.copy())
    assert path.exists() and (path / 'file').read_text() == 'keep this'
    hook.unlink()
    W.act(workspace, row, 'remove', os.environ.copy())
    W.act(workspace, row, 'restore', os.environ.copy())
    assert (path / 'file').read_text() == 'keep this'


def test_restore_remote_branch_then_default(trees):
    workspace, base, remote, row, client = trees
    path = Path(W.command(client, 'add', 'org/product')['workspace_path'])
    git(path, 'push', 'origin', row['branch'])
    git(base, 'worktree', 'remove', '--force', str(path))
    git(base, 'branch', '-D', row['branch'])
    W.act(workspace, row, 'restore', os.environ.copy())
    assert git(path, 'symbolic-ref', '--short', 'HEAD') == row['branch']
    git(base, 'worktree', 'remove', '--force', str(path))
    git(base, 'branch', '-D', row['branch'])
    git(base, 'push', 'origin', '--delete', row['branch'])
    W.act(workspace, row, 'restore', os.environ.copy())
    assert git(path, 'rev-parse', 'HEAD') == git(base, 'rev-parse', 'origin/main')


def test_disk_floor_paths_old_server_and_setup_failure(trees, monkeypatch):
    workspace, base, remote, row, client = trees
    monkeypatch.setattr(W.shutil, 'disk_usage', lambda p: shutil._ntuple_diskusage(100 * GB, 99 * GB, GB))
    with pytest.raises(ValueError, match='Not enough disk'):
        W.command(client, 'add', 'org/product')
    assert not client.post.called
    monkeypatch.setattr(W.shutil, 'disk_usage', lambda p: shutil._ntuple_diskusage(100 * GB, 0, 100 * GB))
    client.post.side_effect = APIError('not_found', 'Missing', 404)
    with pytest.raises(ValueError, match='server is too old'):
        W.command(client, 'add', 'org/product')
    client.post.side_effect = None
    client.get.return_value['repositories'][0]['setup_command'] = 'exit 7'
    with pytest.raises(ValueError, match='setup failed'):
        W.command(client, 'add', 'org/product')
    assert client.patch.called
    outside = workspace.parent / 'outside'
    outside.mkdir()
    (workspace / 'escape').symlink_to(outside, target_is_directory=True)
    for path in ('../outside', 'escape/child', 'repos/org__product', str(outside)):
        with pytest.raises(ValueError):
            W.safe_path(workspace, path)


def test_mixed_version_heartbeat_drops_worktree_fields():
    runner = Runner.__new__(Runner)
    runner.client = mock.Mock()
    runner.client.post.side_effect = [APIError('validation', 'worktrees: Extra inputs', 422),
                                    APIError('validation', 'readiness.worktrees: Extra inputs', 422), {'ok': True}]
    body = {'worktrees': [], 'readiness': {'schema_version': 1, 'worktrees': True}}
    assert runner.report_heartbeat(body) == {'ok': True}
    assert 'worktrees' not in body and 'worktrees' not in body['readiness']


def test_unselected_base_with_linked_worktree_is_not_deleted(trees):
    from runner.repositories import Repositories, REMOVE_AFTER
    workspace, base, remote, row, client = trees
    W.command(client, 'add', 'org/product')
    manager = Repositories(workspace, workspace / 'state.json', client)
    manager.rows = {'org/product': {'full_name': 'org/product', 'managed': True, 'left_at': 0}}
    try:
        manager.sync({}, None, REMOVE_AFTER + 1)
        assert base.exists()
        git(base, 'worktree', 'remove', '--force', str(workspace / row['path']))
        manager.sync({}, None, REMOVE_AFTER + 1)
        assert not base.exists()
    finally:
        manager.close()


def test_computer_heartbeat_actions_use_scoped_token_and_wait_for_idle(trees):
    workspace, base, remote, row, client = trees
    W.command(client, 'add', 'org/product')
    saved = {**row, 'task_status': 'closed', 'bot_state': 'active'}
    repo = {**row, 'access': 'write'}
    client.get.side_effect = lambda route: {'worktrees': [saved]} if route.endswith('/worktrees') else {'repositories': [repo]}
    client.post.return_value = {'token': 'synthetic-worktree-token'}
    client.patch.side_effect = lambda route, body: saved.update(body)
    idle = [False]
    manager = W.Worktrees(workspace, client, idle=lambda: idle[0])
    action = {**row, 'action': 'remove'}
    try:
        manager.sync([action])
        assert (workspace / row['path']).exists()
        idle[0] = True
        manager.sync([action])
        assert not (workspace / row['path']).exists()
        assert manager.reports[0]['state'] == 'removed'
        assert client.post.call_args.args[0] == 'runners/me/worktrees/link1/token'
        assert 'synthetic-worktree-token' not in str(manager.reports)
        saved['task_status'] = 'open'
        manager.sync([{**action, 'action': 'restore'}])
        assert manager.reports[0]['state'] == 'present'
        saved['task_status'] = 'closed'
        client.post.side_effect = APIError('forbidden', 'This bot needs write access', 403)
        manager.sync([action])
        manager.sync([])
        assert 'write access' in manager.reports[0]['error']
        assert (workspace / row['path']).exists()
    finally:
        manager.close()


def test_actions_arriving_during_poll_are_queued(trees):
    import threading
    workspace, base, remote, row, client = trees
    manager = W.Worktrees(workspace, client)
    entered, finish = threading.Event(), threading.Event()
    batches = []
    def sync(actions):
        batches.append(actions)
        entered.set()
        assert finish.wait(2)
    manager.sync = sync
    try:
        manager.poll()
        assert entered.wait(2)
        action = {**row, 'action': 'remove'}
        manager.poll([action])
        finish.set()
        manager.pending.result(timeout=2)
        manager.poll()
        manager.pending.result(timeout=2)
        assert batches == [[], [action]]
    finally:
        finish.set()
        manager.close()
