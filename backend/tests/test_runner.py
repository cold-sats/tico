"""A real listening API, stdlib HTTP client, bot CLI subprocess, and local runtime adapter."""

import json
import os
import socket
import sys
import subprocess
import threading
import time
from pathlib import Path

import pytest
import uvicorn

from backend.tests.test_api import api, assign, claim, get, post, ready, runner  # noqa: F401
from clients.tico import Client
from runner.service import ROOT, Runner, declared_reads, pull_repo, sibling_repo
from runner.state import BOT_THREAD, State
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
    assert "run `hub fleet`" in prompt
    # The assistant's private-room lines and house style are its own, not every bot's.
    assert "privately assisting" not in prompt and "House chat style" not in prompt
    ben = Client(live, "ben-test")
    other = ben.post("chat/ops", {"text": "A separate person's conversation"})["message"]
    service.execute(claim(api, r))
    assert other["conversation_id"] != msg["conversation_id"]
    assert hosts[1].resumes == [hosts[0].prompts[0][0]]
    assert "Please answer locally" not in hosts[1].prompts[0][1]
    service.pool.shutdown()


def test_failed_turn_forgets_the_provider_session(api, live, tmp_path):
    r = runner(api)
    assign(api, r, "ops")
    ready(api, r, ["ops"])
    post(api, "chat/ops", {"text": "Fail after starting the provider session"})

    def factory(attempt, env):
        host = FakeHost()
        host.fail_next_turn("provider turn failed")
        return host

    service = Runner({"url": live, "token": r["token"], "projects_dir": str(tmp_path)},
                     tmp_path / "runner", host_factory=factory)
    attempt = claim(api, r)
    service.execute(attempt)

    assert service.state.session("ops", BOT_THREAD, "codex") is None
    with service.state.connect() as c:
        error = c.execute("SELECT payload FROM events WHERE attempt_id=? AND kind='error'", (attempt["id"],)).fetchone()
    assert json.loads(error[0])["error"] == "provider turn failed"
    assert service.state.unfinished() == []
    service.pool.shutdown()


def test_existing_hub_cli_uses_http_and_never_opens_local_db(api, live, tmp_path):
    r = runner(api)
    assign(api, r, "ops")
    ready(api, r, ["ops"])
    post(api, "chat/ops", {"text": "Create a delegated task"})
    attempt = claim(api, r)
    trap = tmp_path / "must-not-exist.sqlite"
    result = subprocess.run(
        [sys.executable, str(ROOT / "scripts/hub"),
         "task", "create", "--owner", "cpo", "--title", "Review proposed launch", "--body", "Provide a recommendation"],
        env={**os.environ, "HUB_API_URL": live, "HUB_TOKEN": attempt["token"],
             "HUB_EMPLOYEE": "ops", "HUB_DB": str(trap)}, capture_output=True, text=True, timeout=20)
    assert result.returncode == 0, result.stdout + result.stderr
    task = json.loads(result.stdout)
    assert task["requester"] == "bot:ops"
    assert task["owner"] == "bot:cpo"
    assert not trap.exists()


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
        assert '[redacted]' in messages[-1]['body']
    finally:
        service.pool.shutdown()


def test_reads_names_and_a_clean_checkout_fast_forwards(tmp_path):
    assert sibling_repo("emp-product-manager") == "emp-product-manager"
    assert sibling_repo("product-manager") == "emp-product-manager"
    assert sibling_repo("acme/emp-product-manager") == "emp-product-manager"
    path = tmp_path / "emp-ops"
    path.mkdir()
    (path / "employee.yaml").write_text("name: ops\nreads:\n  - emp-product-manager\n  - tickets\n")
    assert declared_reads(path) == ["emp-product-manager", "tickets"]
    remote = tmp_path / "remote.git"
    subprocess.check_call(["git", "init", "--bare", str(remote)])
    work = tmp_path / "work"
    subprocess.check_call(["git", "clone", str(remote), str(work)])
    def git(*args, cwd=work):
        return subprocess.check_call(["git", "-C", str(cwd), *args])
    git("config", "user.email", "test@example.com")
    git("config", "user.name", "Test")
    (work / "file").write_text("one")
    git("add", "file")
    git("commit", "-m", "one")
    git("push", "origin", "HEAD")
    clone = tmp_path / "clone"
    subprocess.check_call(["git", "clone", str(remote), str(clone)])
    (work / "file").write_text("two")
    git("add", "file")
    git("commit", "-m", "two")
    git("push", "origin", "HEAD")
    assert pull_repo(clone) == ""
    assert (clone / "file").read_text() == "two"
    (clone / "file").write_text("dirty")
    assert pull_repo(clone) == ""
    assert (clone / "file").read_text() == "dirty"


REFUSED = "unexpected status 401 Unauthorized: Incorrect API key provided: sk-proj-abcdef1234567890"


def test_a_refused_key_stops_the_computer_taking_that_runtime_until_it_changes(api, live, tmp_path):
    r = runner(api)
    assign(api, r, "ops")
    row = {"installed": True, "authenticated": "ready"}
    bot = {"ready": True, "runtime": "fake", "model": "m", "repository_present": True,
           "repository_revision": "", "configuration_valid": True, "problems": []}
    beat = {"version": "test", "platform": "test",
            "readiness": {"schema_version": 1, "runtimes": {"fake": row}, "bots": {"ops": bot}}}
    post(api, "runners/heartbeat", beat, token=r["token"])
    post(api, "chat/ops", {"text": "Build me a bot"})

    def factory(attempt, env):
        host = FakeHost()
        host.fail_next_turn(REFUSED)
        return host

    service = Runner({"url": live, "token": r["token"], "projects_dir": str(tmp_path)},
                     tmp_path / "runner", host_factory=factory)
    service.environment = lambda attempt: {"HUB_API_URL": live, "HUB_TOKEN": attempt["token"]}
    service.execute(claim(api, r))

    assert claim(api, r) is None, "the job waits instead of starting a new attempt every 15 seconds"
    with api.app.state.store.read() as c:
        assert c.execute("SELECT state FROM jobs").fetchone()[0] == "queued"
        seen = json.loads(c.execute("SELECT readiness_json FROM runners").fetchone()[0])["runtimes"]["fake"]
        assert c.execute("SELECT count(*) FROM attempts").fetchone()[0] == 1
    assert seen["authenticated"] == "rejected" and seen["rejected_at"]
    assert "Incorrect API key" in seen["rejected_reason"] and "sk-proj" not in json.dumps(seen)

    assert service.rejection("fake")
    service.clear_rejection("fake")            # a sign-in succeeded
    assert service.rejection("fake") is None
    service.pool.shutdown()
