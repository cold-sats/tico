"""Release isolation checks must use the runner image built from the candidate."""
from types import SimpleNamespace

from scripts import release_checks


def test_isolation_uses_the_candidate_image_only_after_successful_builds(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(release_checks, 'os', SimpleNamespace(
        environ={'TICO_RUNNER_TEST_IMAGE': 'stale-runner:local'}, getloadavg=lambda: (0, 0, 0)))
    monkeypatch.setattr(release_checks, 'subprocess', SimpleNamespace(
        run=lambda *args, **kwargs: SimpleNamespace(stdout='a' * 40)))
    monkeypatch.setattr(release_checks, 'tempfile', SimpleNamespace(mkdtemp=lambda **kwargs: str(tmp_path)))
    monkeypatch.setattr(release_checks, 'free_port', lambda: 12345)

    for builds_ok in (True, False):
        calls, completed = {}, set()

        class Check:
            def __init__(self, name, command, log_dir, env):
                calls[name] = (command, env, completed.copy())
                self.name, self.log = name, tmp_path / f'{name}.log'

            def join(self):
                completed.add(self.name)
                return int(self.name == 'build-runner' and not builds_ok)

            def tail(self):
                return 'synthetic build failure'

        monkeypatch.setattr(release_checks, 'Check', Check)
        assert release_checks.release(SimpleNamespace(previous=None)) == (0 if builds_ok else 1)
        output = capsys.readouterr().out
        python_command = calls['all-python'][0]
        isolation_file = 'runner/tests/test_isolation_docker.py'
        assert f'--ignore={isolation_file}' in python_command
        if builds_ok:
            command, env, finished = calls['isolation']
            assert command[:4] == [release_checks.sys.executable, '-m', 'pytest', '-q']
            assert isolation_file in command and command[command.index('-m', 2) + 1] == 'slow or not slow'
            assert {'build-server', 'build-runner', 'build-updater'} <= finished
            runner_build = calls['build-runner'][0]
            assert env['TICO_RUNNER_TEST_IMAGE'] == 'tico-rc-runner:local'
            assert env['TICO_RUNNER_TEST_IMAGE'] in runner_build
            assert {'smoke', 'side-jobs'} <= calls.keys()
            assert (tmp_path / 'images-ready').read_text() == 'ok'
        else:
            assert 'isolation' not in calls
            assert 'isolation: not run' in output
            assert (tmp_path / 'images-ready').read_text() == 'failed'
