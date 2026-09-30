"""A real listening API, stdlib HTTP client, bot CLI subprocess, and local runtime adapter."""

import json
import socket
import threading
import time
from pathlib import Path

import pytest
import uvicorn

from backend.tests.test_api import api, assign, claim, get, post, ready, runner  # noqa: F401
from clients.tico import Client
from runner.service import Runner
from runner.state import State
from runner.hosts.fake import FakeHost


@pytest.fixture
def live(api):
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(api.app, log_level="error"))
    thread = threading.Thread(target=server.run, kwargs={"sockets": [sock]}, daemon=True)
    thread.start()
    deadline = time.monotonic() + 5
    while not server.started and thread.is_alive() and time.monotonic() < deadline:
        time.sleep(0.01)
    assert server.started
    yield f"http://127.0.0.1:{port}"
    server.should_exit = True
    thread.join(timeout=10)
    sock.close()
    assert not thread.is_alive()


def test_full_http_runner_roundtrip_and_one_provider_session_per_bot(api, live, tmp_path):
    r = runner(api)
    assign(api, r, "ops")
    ready(api, r, ["ops"])
    hosts = []
    def factory(attempt, env):
        host = FakeHost(replies=["This answer ran on the local machine."])
        hosts.append(host)
        return host
    service = Runner({"url": live, "token": r["token"], "projects_dir": str(tmp_path)},
                     tmp_path / "runner", host_factory=factory)
    service.environment = lambda attempt: {"HUB_API_URL": live, "HUB_TOKEN": attempt["token"]}
    client = Client(live, "ana-test")
    msg = client.post("chat/ops", {"text": "Please answer locally"})["message"]
    service.execute(claim(api, r))
    messages = client.get(f"conversations/{msg['conversation_id']}/messages")["messages"]
    assert messages[-1]["body"] == "This answer ran on the local machine."
    assert service.state.unfinished() == []
    assert hosts[0].prompts
    prompt = hosts[0].prompts[0][1]
    assert "Read AGENT.md and state.md, then carry out the requested work in this turn." in prompt
    assert "Do not end the turn with only a plan or progress update" in prompt
    assert "up to three tasks at a time" in prompt.lower()
    assert "Do not impose an arbitrary answer-length or list-length cap" in prompt
    assert "do not substitute the standing backlog" in prompt
    assert "Never call work blocked until you verify" in prompt
    assert "never repeat an item that current state shows is done" in prompt
    assert "run `hub health check`" in prompt
    # The assistant's private-room lines and house style are its own, not every bot's.
    assert "privately assisting" not in prompt and "House chat style" not in prompt
    ben = Client(live, "ben-test")
    other = ben.post("chat/ops", {"text": "A separate person's conversation"})["message"]
    service.execute(claim(api, r))
    assert other["conversation_id"] != msg["conversation_id"]
    assert hosts[1].resumes == [hosts[0].prompts[0][0]]
    assert "Please answer locally" not in hosts[1].prompts[0][1]
    service.pool.shutdown()


def test_vault_injects_only_granted_secrets_and_removes_temporary_files(api, live, tmp_path):
    from backend.tests.test_credentials import setup, create
    setup(api)
    file_secret='synthetic-service-account-fixture'
    secret=create(api,name='Service account',kind='file',env='GOOGLE_SA_KEY',secret=file_secret)
    create(api,name='Unassigned',env='UNASSIGNED_API_KEY',secret='never-deliver-this-fixture')
    post(api,f"credentials/{secret['id']}/grants",{'subject':'bot:ops'})
    machine=runner(api);assign(api,machine,'ops');ready(api,machine,['ops'])
    msg=post(api,'chat/ops',{'text':'Use a synthetic granted credential'})
    files=[]
    def factory(attempt,env):
        p=Path(env['GOOGLE_SA_KEY']);files.append(p)
        assert p.read_text()==file_secret and p.stat().st_mode & 0o777 == 0o600
        assert 'UNASSIGNED_API_KEY' not in env
        return FakeHost(replies=['A diagnostic with '+file_secret])
    service=Runner({'url':live,'token':machine['token'],'projects_dir':str(tmp_path)},tmp_path/'state',host_factory=factory)
    try:
        service.execute(claim(api,machine))
        assert files and not files[0].exists()
        assert not service.vault_values and not service.vault_files
        messages=get(api,f"conversations/{msg['conversation_id']}/messages")
        assert file_secret not in json.dumps(messages)
        assert '••••' in messages[-1]['body']
    finally:
        service.pool.shutdown()


REFUSED = "unexpected status 401 Unauthorized: Incorrect API key provided: sk-proj-abcdef1234567890"

