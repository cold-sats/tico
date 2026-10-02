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
    saved = git(remote, 'show', W.wip_branch(row) + ':file')
    assert saved == 'changed'
    assert W.inspect(workspace, {**row, 'state': 'removed'})['state'] == 'removed'
    assert W.act(workspace, row, 'restore', os.environ.copy()) == 'present'
    assert git(path, 'symbolic-ref', '--short', 'HEAD') == row['branch']
    assert (path / 'file').read_text() == 'changed'
    assert (path / 'setup-ran').exists()  # saved file, not a rerun of setup


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


def test_git_hooks_fsmonitor_and_setup_never_receive_vault_environment(trees, monkeypatch):
    workspace, base, remote, row, client = trees
    monkeypatch.setenv('VAULT_TEST_SECRET', 'synthetic-private-value')
    monkeypatch.setenv('HUB_INGEST_TOKEN', 'synthetic-runner-secret')
    marker = workspace / 'hook-ran'
    for name in ('post-checkout', 'pre-commit', 'pre-push'):
        hook = base / '.git' / 'hooks' / name
        hook.write_text('#!/bin/sh\ntouch "' + str(marker) + '"\nexit 1\n')
        hook.chmod(0o755)
    git(base, 'config', 'core.fsmonitor', 'touch ' + str(marker))
    client.get.return_value['repositories'][0]['setup_command'] = 'test -z "$VAULT_TEST_SECRET$HUB_INGEST_TOKEN" && touch setup-ran'
    path = Path(W.command(client, 'add', 'org/product')['workspace_path'])
    assert W.inspect(workspace, row)['state'] == 'present'
    (path / 'file').write_text('saved')
    W.act(workspace, row, 'remove', os.environ.copy())
    with mock.patch.object(W, 'setup') as setup:
        W.act(workspace, row, 'restore', os.environ.copy())
        setup.assert_not_called()
    assert not marker.exists()


def test_long_branch_does_not_break_heartbeat_and_4xx_retries_without_worktrees(trees):
    workspace, base, remote, row, client = trees
    path = Path(W.command(client, 'add', 'org/product')['workspace_path'])
    git(path, 'switch', '-c', 'feature/' + 'x' * 220)
    report = W.inspect(workspace, row)
    from backend.models import WorktreeStatus
    WorktreeStatus(**report)
    assert report['state'] == 'present' and report['branch'] is None and 'oversized' in report['error']
    for status in (400, 409, 422):
        runner = Runner.__new__(Runner)
        runner.client = mock.Mock()
        runner.client.post.side_effect = [APIError('validation', 'worktrees.0.branch too long', status), {'ok': True}]
        body = {'worktrees': [report], 'readiness': {'bots': {}}}
        assert runner.report_heartbeat(body) == {'ok': True}
        assert 'worktrees' not in body


def test_cleanup_never_replaces_divergent_task_history(trees):
    workspace, base, remote, row, client = trees
    path = Path(W.command(client, 'add', 'org/product')['workspace_path'])
    (path / 'file').write_text('task commit')
    git(path, 'add', 'file')
    git(path, '-c', 'user.name=Tico', '-c', 'user.email=bot@example.com', 'commit', '-m', 'Task history')
    task_head = git(path, 'rev-parse', 'HEAD')
    git(path, 'switch', '-c', 'experiment', 'origin/main')
    (path / 'file').write_text('experiment')
    with pytest.raises(ValueError, match='separate history'):
        W.act(workspace, row, 'remove', os.environ.copy())
    assert git(base, 'rev-parse', row['branch']) == task_head
    assert path.exists() and (path / 'file').read_text() == 'experiment'


def test_fetch_failure_is_not_missing_branch(trees, monkeypatch):
    workspace, base, remote, row, client = trees
    path = Path(W.command(client, 'add', 'org/product')['workspace_path'])
    git(path, 'push', 'origin', row['branch'])
    head = git(path, 'rev-parse', 'HEAD')
    git(base, 'worktree', 'remove', '--force', str(path))
    real_git = W.git
    def failed_fetch(path, *args, **kwargs):
        if args[0] == 'fetch' and any(row['branch'] in a for a in args):
            raise ValueError('Git fetch failed; synthetic network failure')
        return real_git(path, *args, **kwargs)
    monkeypatch.setattr(W, 'git', failed_fetch)
    with pytest.raises(ValueError, match='fetch failed'):
        W.act(workspace, row, 'restore', os.environ.copy())
    assert not path.exists() and git(base, 'rev-parse', row['branch']) == head


def test_missing_folder_registration_is_pruned_for_restore_and_base_cleanup(trees):
    workspace, base, remote, row, client = trees
    path = Path(W.command(client, 'add', 'org/product')['workspace_path'])
    shutil.rmtree(path)
    assert (base / '.git' / 'worktrees').exists()
    W.act(workspace, row, 'restore', os.environ.copy())
    assert path.exists()
    shutil.rmtree(path)
    from runner.repositories import Repositories, REMOVE_AFTER
    manager = Repositories(workspace, workspace / 'state.json', client)
    manager.rows = {'org/product': {'full_name': 'org/product', 'managed': True, 'left_at': 0}}
    try:
        manager.sync({}, None, REMOVE_AFTER + 1)
        assert not base.exists()
    finally:
        manager.close()


def test_new_base_clone_detects_default_and_restores_remote_snapshot(trees, monkeypatch):
    workspace, base, remote, row, client = trees
    path = Path(W.command(client, 'add', 'org/product')['workspace_path'])
    (path / 'file').write_text('saved snapshot')
    W.act(workspace, row, 'remove', os.environ.copy())
    shutil.rmtree(base)
    real_run = W.isolation.run
    cloned = []
    def local_clone(args, **kwargs):
        if 'clone' in args:
            cloned.append(args)
            result = real_run([str(remote) if a == 'https://github.com/org/product.git' else a for a in args], **kwargs)
            if result.returncode == 0:
                git(base, 'config', 'remote.origin.url', 'https://github.com/org/product.git')
                git(base, 'config', f'url.{remote}.insteadOf', 'https://github.com/org/product.git')
            return result
        return real_run(args, **kwargs)
    monkeypatch.setattr(W.isolation, 'run', local_clone)
    with mock.patch.object(W, 'setup') as setup:
        W.act(workspace, {**row, 'default_branch': None}, 'restore', os.environ.copy())
        setup.assert_not_called()
    assert len(cloned) == 1 and '--single-branch' in cloned[0]
    assert (base / '.git' / 'tico-managed').exists()
    assert (path / 'file').read_text() == 'saved snapshot'
    assert git(path, 'symbolic-ref', '--short', 'HEAD') == row['branch']


def test_unpushed_means_task_branch_and_clean_finished_cleanup_does_not_push(trees):
    workspace, base, remote, row, client = trees
    client.get.return_value['repositories'][0]['setup_command'] = None
    path = Path(W.command(client, 'add', 'org/product')['workspace_path'])
    (path / 'file').write_text('task commit')
    git(path, 'add', 'file')
    git(path, '-c', 'user.name=Tico', '-c', 'user.email=bot@example.com', 'commit', '-m', 'Work')
    assert W.inspect(workspace, row)['ahead'] == 1
    git(path, 'push', 'origin', row['branch'])
    assert W.inspect(workspace, row)['ahead'] == 0
    git(remote, 'update-ref', '-d', 'refs/heads/' + row['branch'])
    with mock.patch.object(W, 'git', wraps=W.git) as calls:
        W.act(workspace, {**row, 'prs_finished': True}, 'remove', os.environ.copy())
    assert not any(call.args[1] == 'push' for call in calls.call_args_list)
    assert git(remote, 'show-ref', '--heads') == git(remote, 'show-ref', '--heads', 'main')


@pytest.mark.parametrize('name', ['.env.local', 'private.pem', 'credentials.json', 'large.bin', 'valuable.db'])
def test_cleanup_keeps_unsafe_large_and_ignored_files(trees, name):
    workspace, base, remote, row, client = trees
    path = Path(W.command(client, 'add', 'org/product')['workspace_path'])
    file = path / name
    file.write_text('keep')
    if name == 'large.bin':
        with file.open('ab') as handle:
            handle.truncate(21 * 1024 ** 2)
    if name == 'valuable.db':
        (path / '.gitignore').write_text('valuable.db\n')
    with pytest.raises(ValueError, match='kept:'):
        W.act(workspace, row, 'remove', os.environ.copy())
    assert file.exists()
    assert git(remote, 'show-ref', '--heads') == git(remote, 'show-ref', '--heads', 'main')


def test_backoff_does_not_mint_more_tokens_and_alias_paths_are_refused(trees):
    workspace, base, remote, row, client = trees
    path = Path(W.command(client, 'add', 'org/product')['workspace_path'])
    (workspace / 'alias').symlink_to(path.parent, target_is_directory=True)
    with pytest.raises(ValueError, match='symlinks'):
        W.command(client, 'attach', 'alias/org__product')
    saved = {**row, 'task_status': 'closed', 'bot_state': 'active'}
    client.get.side_effect = lambda route: {'worktrees': [saved]} if route.endswith('/worktrees') else {'repositories': [{**row, 'access': 'write'}]}
    client.post.reset_mock()
    client.post.side_effect = APIError('forbidden', 'Synthetic refusal', 403)
    manager = W.Worktrees(workspace, client)
    try:
        action = {**row, 'action': 'remove'}
        manager.sync([action])
        until, failures = manager.retry[row['id']]
        assert failures == 1 and 299 <= until - W.time.monotonic() <= 300
        manager.sync([action])
        assert client.post.call_count == 1
        assert path.exists()
    finally:
        manager.close()


def test_readiness_advertises_worktrees_and_setup_cli_runs_in_turn(trees):
    from clients.hubcli import parser
    workspace, base, remote, row, client = trees
    runner = Runner.__new__(Runner)
    runner.config = {}
    runner.tools = None
    runner._harness_after = 0
    runner.runtime_report = lambda assignments: {'fake': {}}
    runner.preflight = lambda assignments, runtimes: [{'bot': 'engineer', 'ready': True}]
    assert runner.readiness([])['worktrees'] is True
    prompt = runner.prompt({'bot': 'engineer', 'task': {'id': row['task_id'], 'requester': 'human:ana'},
                            'message': {'id': 'm1', 'from_actor': 'human:ana', 'body': 'Work', 'refs': {}},
                            'conversation': {'id': 'room', 'scope': 'personal', 'kind': 'chat', 'owner_actor': 'human:ana'}})
    assert 'setup_pending=true' in prompt and 'hub task worktree setup <repo>' in prompt
    args = parser().parse_args(['task', 'worktree', 'setup', 'org/product'])
    assert args.fn == 'task worktree setup'
    W.command(client, 'add', 'org/product')
    repo = client.get.return_value['repositories'][0]
    client.get.side_effect = lambda route: {'links': [{**row, 'kind': 'worktree'}]} if route.endswith('/links') else {'repositories': [repo]}
    W.command(client, 'setup', 'org/product')
    assert client.patch.call_args.args[1] == {'setup_pending': False}


def test_unlisted_managed_base_is_adopted_and_clone_failure_cleans_partial_folder(trees, monkeypatch):
    from runner.repositories import Repositories
    workspace, base, remote, row, client = trees
    (base / '.git' / 'tico-managed').touch()
    client.get.return_value = {'repositories': []}
    manager = Repositories(workspace, workspace / 'state.json', client)
    try:
        manager.poll()
        manager.pending.result(timeout=2)
        assert manager.rows['org/product']['managed'] is True
        assert manager.rows['org/product']['left_at'] > 0
        from backend.models import RepositoryStatus
        RepositoryStatus(**manager.report()[0])
    finally:
        manager.close()
    shutil.rmtree(base)
    real_run = W.isolation.run
    def failed_clone(args, **kwargs):
        if 'clone' in args:
            Path(args[-1]).mkdir(parents=True)
            return subprocess.CompletedProcess(args, 128, '', 'synthetic refusal')
        return real_run(args, **kwargs)
    monkeypatch.setattr(W.isolation, 'run', failed_clone)
    with pytest.raises(ValueError, match='clone failed'):
        W.repositories.worktree_base(workspace, row, W.safe_git.process_environment())
    assert not base.exists()


def test_setup_timeout_kills_process_group(trees):
    workspace, base, remote, row, client = trees
    process = mock.MagicMock()
    process.__enter__.return_value = process
    process.pid = 12345
    process.wait.side_effect = [subprocess.TimeoutExpired('setup', 600), 0]
    with mock.patch.object(W.isolation, 'popen', return_value=process) as popen, mock.patch.object(W.os, 'killpg') as kill:
        with pytest.raises(ValueError, match='timed out'):
            W.setup(workspace, 'sleep 999', os.environ.copy())
        assert popen.call_args.kwargs['start_new_session'] is True
        kill.assert_called_once_with(12345, W.signal.SIGKILL)
        assert process.wait.call_count == 2


def test_add_using_task_prefix_waits_for_the_same_link_restore_lock(trees):
    import concurrent.futures
    import threading
    workspace, base, remote, row, client = trees
    W.command(client, 'add', 'org/product')
    posted = threading.Event()
    response = client.post.return_value
    def posted_link(*args, **kwargs):
        posted.set()
        return response
    client.post.side_effect = posted_link
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        with W.locked(workspace, row['id']):
            future = pool.submit(W.command, client, 'add', 'org/product', row['task_id'][:8])
            assert posted.wait(2)
            assert not future.done()
        assert future.result(timeout=5)['link_id'] == row['id']
