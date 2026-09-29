"""One Gemini request, for the market librarian's answers (backend/market.py)."""
import json
import os
from functools import lru_cache
from pathlib import Path
from urllib.request import Request, urlopen

# The projects folder holds secrets/ beside the hub checkout; TICO_PROJECTS names it when this
# checkout is somewhere else (a worktree), the way the runner's --projects does.
PROJECTS = Path(os.environ.get('TICO_PROJECTS') or Path(__file__).resolve().parents[1].parent).expanduser()


def read_env(path):
    out = {}
    for line in path.read_text(errors='replace').splitlines():
        if '=' in line and not line.lstrip().startswith('#'):
            k, v = line.split('=', 1); out[k.strip()] = v.strip()
    return out


@lru_cache(maxsize=1)
def key():
    shared = {}
    for path in (PROJECTS / 'secrets/_shared.env', PROJECTS / 'secrets/docs-qa.env'):
        if path.exists():
            shared.update(read_env(path))
    env = {k: os.environ.get(k) or shared.get(k, '') for k in ('GEMINI_API_KEY', 'OP_SERVICE_ACCOUNT_TOKEN')}
    if env['GEMINI_API_KEY'].startswith('op://'):
        from runner.op import resolve_op_refs
        resolve_op_refs(env)
    if not env['GEMINI_API_KEY']:
        raise ValueError('Docs answers need a configured Gemini API key.')
    return env['GEMINI_API_KEY']


def request(path, body):
    return urlopen(Request('https://generativelanguage.googleapis.com/v1beta/' + path,
        data=json.dumps(body).encode(), headers={'Content-Type':'application/json', 'x-goog-api-key':key()}), timeout=30)
