"""Trusted Computer config survives maintenance without repository programs."""
import os
import subprocess
from runner import safe_git


def test_system_and_global_settings_are_kept_without_includes(tmp_path, monkeypatch):
    system = tmp_path / 'system.gitconfig'
    global_config = tmp_path / 'global.gitconfig'
    included = tmp_path / 'included.gitconfig'
    included.write_text('[credential]\nhelper = forbidden-include\n')
    system.write_text('[credential]\nhelper = system-helper\n'
                      '[url "ssh://git@example.com/"]\ninsteadOf = https://example.com/\n'
                      '[http]\nproxy = http://proxy.example.com\nsslCAInfo = /example/ca.pem\n'
                      '[user]\nname = Sam\nemail = sam@example.com\n'
                      '[include]\npath = ' + str(included) + '\n')
    global_config.write_text('[credential]\nhelper = global-helper\n'
                             '[core]\nsshCommand = ssh -i /example/key\n'
                             '[user]\nname = Ana\n')
    env = safe_git.machine_environment({**os.environ, 'GIT_CONFIG_SYSTEM': str(system),
                                        'GIT_CONFIG_GLOBAL': str(global_config)})
    entries = [(env['GIT_CONFIG_KEY_' + str(i)], env['GIT_CONFIG_VALUE_' + str(i)])
               for i in range(int(env['GIT_CONFIG_COUNT']))]
    assert ('credential.helper', 'system-helper') in entries
    assert ('credential.helper', 'global-helper') in entries
    assert not any(value == 'forbidden-include' for key, value in entries)
    assert env['GIT_SSH_COMMAND'] == 'ssh -i /example/key'
    for key, value in [('http.proxy', 'http://proxy.example.com'), ('http.sslcainfo', '/example/ca.pem'),
                       ('user.name', 'Ana'), ('user.email', 'sam@example.com'),
                       ('url.ssh://git@example.com/.insteadof', 'https://example.com/')]:
        assert (key, value) in entries
    repo = tmp_path / 'repo'
    subprocess.run(['git', 'init', str(repo)], check=True, capture_output=True)
    subprocess.run(['git', '-C', str(repo), 'config', 'core.sshCommand', 'forbidden-repo'], check=True)
    result = subprocess.run([*safe_git.prefix(repo), '-C', str(repo), 'config', '--get', 'core.sshCommand'],
                            env=env, check=True, capture_output=True, text=True)
    assert result.stdout.strip() == 'ssh -i /example/key'
