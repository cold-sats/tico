"""Actual NDJSON subprocesses, token rotation and private-session boundaries."""
import json
import os
import sys
import time

import pytest

from runner.service import Runner
from runner.warm import WarmSessions
from runner.hosts.antigravity import AntigravityHost
from clients.tico import Client, APIError


FAKE = '''import json,sys,uuid
cid = sys.argv[sys.argv.index('--conversation')+1] if '--conversation' in sys.argv else str(uuid.uuid4())
print(json.dumps({'event':'init','conversation_id':cid}),flush=True)
for n,line in enumerate(sys.stdin,1):
 prompt=json.loads(line)['message']['content']
 if prompt=='crash': sys.exit(1)
 print(json.dumps({'event':'step_update','step_update':{'conversation_id':cid,'step_type':'agent_response','text_delta':'Hello'}}),flush=True)
 print(json.dumps({'event':'result','result':{'conversation_id':cid,'status':'SUCCESS','response':'Hello','usage':{'input_tokens':n*10,'output_tokens':n*2}}}),flush=True)
'''


def result(host):
    events = []
    until = time.monotonic() + 3
    while time.monotonic() < until:
        events += host.drain()
        if any(e['kind'] in ('turn_completed', 'turn_failed') for e in events):
            return events
        time.sleep(.01)
    pytest.fail('No terminal event')


def test_warm_scope_rotation_revocation_and_config_change(tmp_path, monkeypatch):
    class Host:
        running = True
        def alive(self): return self.running
        def stop(self): self.running = False
    pool = WarmSessions(tmp_path)
    a = {'bot':'coo','conversation':{'id':'private-ana'},'principal':'human:ana',
         'config':{'runtime':'gemini','harness':'antigravity','model':'gemini-3.8-flash'}}
    env = {'HUB_TOKEN':'first-token','HUB_API_URL':'http://localhost'}
    host, child = pool.acquire(a,env,lambda a,e:Host())
    path = next(iter(pool.entries.values()))['token_file']
    assert path.stat().st_mode & 0o777 == 0o600
    assert path.read_text()=='first-token' and child['HUB_TOKEN'].startswith('tico-file:')
    with pytest.raises(RuntimeError): pool.acquire(a,env,lambda a,e:Host())
    client = Client('http://localhost',child['HUB_TOKEN'])
    pool.release(host,True)
    with pytest.raises(APIError,match='No active Hub turn'):client.get('me')
    same,child2 = pool.acquire(a,{**env,'HUB_TOKEN':'second-token'},lambda a,e:Host())
    assert same is host and child2==child and path.read_text()=='second-token'
    pool.release(host,True)
    other = {**a,'principal':'human:ben','conversation':{'id':'private-ben'}}
    second,_ = pool.acquire(other,{**env,'HUB_TOKEN':'ben-token'},lambda a,e:Host())
    assert second is not host and path.read_text()==''
    pool.release(second,True)
    changed,_ = pool.acquire(a,{**env,'GEMINI_API_KEY':'changed-key'},lambda a,e:Host())
    assert changed is not host and not host.alive()
    pool.release(changed,False);pool.prune(close=True)
    assert not pool.entries
