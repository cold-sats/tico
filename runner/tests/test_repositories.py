"""Computer base-clone contracts, without a GitHub account or running server."""
import json
from pathlib import Path
import shutil
import subprocess
import time
from unittest import mock

import pytest

from clients.tico import APIError
from runner.repositories import FETCH_INTERVAL, GB, REMOVE_AFTER, Repositories
from runner.service import Runner


@pytest.fixture
def repos(tmp_path):
    client = mock.Mock()
    client.get.return_value = {'repositories': [dict(full_name='org/one', default_branch='main'), dict(full_name='org/two', default_branch='main')]}
    client.post.return_value = {'token': 'synthetic-install-token', 'repositories': ['org/one', 'org/two']}
    manager = Repositories(tmp_path, tmp_path / 'state' / 'repositories.json', client)
    yield manager
    manager.pool.shutdown(wait=True)


def fake_git(args, **kwargs):
    assert kwargs['env']['GIT_TERMINAL_PROMPT'] == '0'
    assert kwargs['timeout'] == 120
    assert 'synthetic-install-token' not in ' '.join(args)
    if 'clone' in args:
        path = Path(args[-1])
        (path / '.git').mkdir(parents=True)
        (path / '.git' / 'config').write_text('[remote "origin"]\nurl = ' + args[-2])
    return subprocess.CompletedProcess(args, 0, '', '')


def cycle(manager):
    result = manager.poll()
    if manager.pending:
        manager.pending.result(timeout=5)
    return result


def test_first_sync_is_lazy_tokens_not_saved_and_fetch_interval_survives_restart(repos):
    with mock.patch('runner.repositories.isolation.run', side_effect=fake_git) as git, mock.patch('runner.repositories.shutil.disk_usage', return_value=shutil._ntuple_diskusage(100 * GB, 0, 100 * GB)):
        cycle(repos)
        assert git.call_count == 1
        assert repos.path('org/one').exists()
        assert not repos.path('org/two').exists()
        cycle(repos)
        assert git.call_count == 2
        cycle(repos)
        assert git.call_count == 2
        saved = repos.state_file.read_text()
        assert 'synthetic-install-token' not in saved
        assert 'synthetic-install-token' not in (repos.path('org/one') / '.git/config').read_text()
        restarted = Repositories(repos.root.parent, repos.state_file, repos.client)
        try:
            with mock.patch('runner.repositories.time.time', return_value=time.time() + FETCH_INTERVAL + 1):
                cycle(restarted)
                assert git.call_count == 3
                assert 'fetch' in git.call_args.args[0]
                assert '+refs/heads/main:refs/remotes/origin/main' in git.call_args.args[0]
        finally:
            restarted.pool.shutdown(wait=True)


@pytest.mark.parametrize('total,free,needed', [(40 * GB, 3.1 * GB, '5 GB'), (100 * GB, 8 * GB, '10 GB')])
def test_disk_floor_reports_and_does_not_mint_or_clone(repos, total, free, needed):
    with mock.patch('runner.repositories.shutil.disk_usage', return_value=shutil._ntuple_diskusage(total, total-free, free)), mock.patch('runner.repositories.isolation.run') as git:
        cycle(repos)
        row = repos.report()[0]
        assert row['state'] == 'disk_low'
        assert needed in row['error']
        assert 'Not enough disk to clone org/one' in row['error']
        assert not git.called
        assert not repos.client.post.called


def test_removal_waits_30_days_and_never_follows_paths_outside_repos(repos, tmp_path):
    with mock.patch('runner.repositories.isolation.run', side_effect=fake_git), mock.patch('runner.repositories.shutil.disk_usage', return_value=shutil._ntuple_diskusage(100 * GB, 0, 100 * GB)):
        cycle(repos)
        cycle(repos)
    outside = tmp_path / 'bot-existing'
    outside.mkdir()
    (outside / 'keep').write_text('keep')
    repos.path('org/two').rename(tmp_path / 'saved-two')
    (repos.root / 'org__two').symlink_to(outside, target_is_directory=True)
    repos.client.get.return_value = {'repositories': []}
    now = time.time()
    with mock.patch('runner.repositories.time.time', return_value=now):
        cycle(repos)
    with mock.patch('runner.repositories.time.time', return_value=now + REMOVE_AFTER - 1):
        cycle(repos)
        assert repos.path('org/one').exists()
    with mock.patch('runner.repositories.time.time', return_value=now + REMOVE_AFTER + 1):
        cycle(repos)
        assert not repos.path('org/one').exists()
        assert (outside / 'keep').read_text() == 'keep'
        assert repos.rows['org/two']['state'] == 'failed'
        cycle(repos)
        assert 'org/one' not in repos.rows  # removed reports do not accumulate


def test_old_server_and_transient_error_do_nothing(repos):
    repos.rows['org/one'] = {'full_name': 'org/one', 'state': 'cloned'}
    for status in (404, 503):
        repos.client.get.side_effect = APIError('http_error', 'unavailable', status)
        assert repos.poll() is None
        assert repos.report() == []
        assert 'left_at' not in repos.rows['org/one']
        assert repos.pending is None
        assert not repos.client.post.called


def test_clone_failure_redacts_and_does_not_stall_next_repo(repos):
    with mock.patch('runner.repositories.isolation.run', return_value=subprocess.CompletedProcess([], 1, '', 'synthetic-install-token')), mock.patch('runner.repositories.shutil.disk_usage', return_value=shutil._ntuple_diskusage(100 * GB, 0, 100 * GB)):
        cycle(repos)
    assert repos.report()[0]['state'] == 'failed'
    assert 'synthetic-install-token' not in json.dumps(repos.report())
    with mock.patch('runner.repositories.isolation.run', side_effect=fake_git), mock.patch('runner.repositories.shutil.disk_usage', return_value=shutil._ntuple_diskusage(100 * GB, 0, 100 * GB)):
        cycle(repos)
    assert repos.rows['org/two']['state'] == 'cloned'


def test_root_symlink_and_unmanaged_folder_are_left_alone(repos, tmp_path):
    outside = tmp_path / 'outside'
    outside.mkdir()
    repos.root.symlink_to(outside, target_is_directory=True)
    cycle(repos)
    assert repos.rows['org/one']['state'] == 'failed'
    assert not list(outside.iterdir())
    repos.root.unlink()
    repos.root.mkdir()
    repos.path('org/two').mkdir()
    (repos.path('org/two') / 'keep').write_text('keep')
    cycle(repos)
    assert repos.rows['org/two']['state'] == 'failed'
    assert (repos.path('org/two') / 'keep').exists()


def test_old_heartbeat_schema_drops_only_repository_report():
    runner = Runner.__new__(Runner)
    runner.client = mock.Mock()
    runner.client.post.side_effect = [APIError('validation', 'repositories: Extra inputs are not permitted', 422), {}]
    body = {'repositories': [{'full_name': 'org/one', 'state': 'failed'}], 'readiness': {'bots': {'example': {'ready': True}}}}
    assert runner.report_heartbeat(body) == {}
    assert 'repositories' not in body
    assert body['readiness']['bots']['example']['ready'] is True
    assert runner.client.post.call_count == 2


def test_real_git_clone_keeps_token_out_of_config_and_fetches_default_branch(repos, tmp_path):
    source = tmp_path / 'source'
    subprocess.run(['git', 'init', '-q', '-b', 'main', str(source)], check=True)
    (source / 'README.md').write_text('first')
    subprocess.run(['git', '-C', str(source), 'add', '.'], check=True)
    subprocess.run(['git', '-C', str(source), '-c', 'user.name=Example', '-c', 'user.email=example@example.com', 'commit', '-qm', 'first'], check=True)
    repos.client.get.return_value['repositories'] = repos.client.get.return_value['repositories'][:1]
    from runner import isolation
    real_run = isolation.run

    def local_git(args, **kwargs):
        args = [str(source) if a.startswith('https://github.com/') else a for a in args]
        return real_run(args, **kwargs)

    with mock.patch('runner.repositories.isolation.run', side_effect=local_git), mock.patch('runner.repositories.shutil.disk_usage', return_value=shutil._ntuple_diskusage(100 * GB, 0, 100 * GB)):
        cycle(repos)
        assert repos.report()[0]['state'] == 'cloned'
        config = (repos.path('org/one') / '.git/config').read_text()
        assert 'synthetic-install-token' not in config
        assert 'credential' not in config
        (source / 'README.md').write_text('second')
        subprocess.run(['git', '-C', str(source), 'add', '.'], check=True)
        subprocess.run(['git', '-C', str(source), '-c', 'user.name=Example', '-c', 'user.email=example@example.com', 'commit', '-qm', 'second'], check=True)
        with mock.patch('runner.repositories.time.time', return_value=time.time() + FETCH_INTERVAL + 1):
            cycle(repos)
        head = subprocess.check_output(['git', '-C', str(source), 'rev-parse', 'HEAD'], text=True).strip()
        fetched = subprocess.check_output(['git', '-C', str(repos.path('org/one')), 'rev-parse', 'origin/main'], text=True).strip()
        assert fetched == head
        assert 'synthetic-install-token' not in (repos.path('org/one') / '.git/config').read_text()


def test_slow_git_does_not_block_heartbeat_poll(repos):
    import threading
    entered, release = threading.Event(), threading.Event()

    def slow_git(args, **kwargs):
        entered.set()
        assert release.wait(timeout=5)
        return fake_git(args, **kwargs)

    with mock.patch('runner.repositories.isolation.run', side_effect=slow_git) as git, mock.patch('runner.repositories.shutil.disk_usage', return_value=shutil._ntuple_diskusage(100 * GB, 0, 100 * GB)):
        try:
            repos.poll()
            assert entered.wait(timeout=5)
            rows = repos.poll()
            assert rows[0]['state'] == 'cloning'
            assert git.call_count == 1
            assert repos.client.get.call_count == 2
        finally:
            release.set()
            repos.pending.result(timeout=5)


def test_state_disk_failure_still_reports_without_git(repos):
    with mock.patch.object(repos, 'save', side_effect=OSError(28, 'No space left on device')):
        rows = repos.poll()
        assert rows[0]['state'] == 'failed'
        assert 'free disk space' in rows[0]['error']
        assert repos.pending is None


def test_doctor_reads_current_rows_without_cloning_and_old_server_is_silent(repos):
    rows = repos.inspect()
    assert [r['full_name'] for r in rows] == ['org/one', 'org/two']
    assert repos.pending is None
    assert not repos.client.post.called
    assert not repos.state_file.exists()
    repos.client.get.side_effect = APIError('http_error', 'not found', 404)
    assert repos.inspect() == []
