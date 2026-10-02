"""Git used by computer maintenance has no turn credentials or repository hooks."""
import atexit
import os
import shutil
import tempfile

_SETTINGS = {'HOME', 'PATH', 'SHELL', 'USER', 'LOGNAME', 'TMPDIR', 'TMP', 'TEMP', 'LANG', 'TZ', 'TERM', 'COLORTERM',
             'CODEX_HOME', 'XDG_CONFIG_HOME', 'XDG_CACHE_HOME'}
_hooks = tempfile.mkdtemp(prefix='tico-empty-hooks-')
os.chmod(_hooks, 0o555)
atexit.register(shutil.rmtree, _hooks, ignore_errors=True)
PREFIX = ['git', '--no-optional-locks', '-c', 'core.hooksPath=' + _hooks, '-c', 'core.fsmonitor=false']


def process_environment(source=None):
    source = os.environ if source is None else source
    return {k: v for k, v in source.items() if k in _SETTINGS or k.startswith('LC_')}


def environment(source=None):
    from . import git_credentials
    source = os.environ if source is None else source
    env = process_environment(source)
    # These are the per-repository helper settings, never vault grants or the runner token.
    keys = set(git_credentials.environment('')) | {git_credentials.credential_socket.SOCKET_ENV, 'HUB_TOKEN'}
    keys.update(k for k in source if k.startswith('TICO_GITHUB_'))
    env.update({k: v for k, v in source.items() if k in keys})
    env.update(GIT_TERMINAL_PROMPT='0', GIT_OPTIONAL_LOCKS='0')
    return env
