"""One contract, two engines: `python -m runner run` and the Rust `tico-runner run` (runner-rs/), each run as a
real process against a real listening API, with fake `claude` and `codex` executables first on PATH
(runner/tests/conformance/). Every scenario runs on both engines and both harnesses, and checks the result
through the server: the claim, the streamed events, the completion and its Idempotency-Keys, granted
credentials and their redaction, session resume, and recovery after the runner is killed mid-turn.

Slow: it builds the release binary once per session (cargo) and starts runner processes."""

import json
import os
import shutil
import signal
import subprocess
import sys
import time
from pathlib import Path

import pytest

from backend.store import encode
from backend.tests.test_api import api, assign, get, post, runner, settled  # noqa: F401
from backend.tests.test_runner import live  # noqa: F401
from clients.tico import Client

pytestmark = pytest.mark.slow

ROOT = Path(__file__).resolve().parents[2]
FAKES = Path(__file__).resolve().parent / "conformance"
MODELS = {"claude": "claude-sonnet-5", "codex": "gpt-5.5"}
SECRET = "acme-synthetic-fixture-4821"


@pytest.fixture(scope="session")
def rust_binary():
    if not shutil.which("cargo"):
        pytest.skip("cargo is not installed")
    subprocess.run(["cargo", "build", "--release", "-q"], cwd=ROOT / "runner-rs", check=True, timeout=900)
    return ROOT / "runner-rs" / "target" / "release" / "tico-runner"


def until(check, what, timeout=30.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        value = check()
        if value:
            return value
        time.sleep(0.05)
    raise AssertionError(f"timed out waiting for {what}")


class Computer:
    """One registration, its workspace, and the engine process running it."""

    def __init__(self, api, live, tmp_path, engine, harness, binary, bot=None, registration=None, git=False, env=None):
        self.api, self.engine, self.harness, self.binary = api, engine, harness, binary
        self.registration = runner(api)
        assign(api, self.registration, "ops")
        with api.app.state.store.transaction() as c:
            c.execute("UPDATE bot_config SET config_json=? WHERE bot='ops'",
                      (encode({"name": "ops", "runtime": harness, "model": MODELS[harness], "status": "active",
                               **(bot or {})}),))
        repo = tmp_path / "projects" / "bot-ops"
        repo.mkdir(parents=True)
        (repo / "AGENT.md").write_text("# Ops\n\nAnswer the Acme team.\n")
        (repo / "bot.yaml").write_text(f"name: ops\nruntime: {harness}\nmodel: {MODELS[harness]}\n")
        if git:
            # A checkout with an upstream, so a task can have a worktree of its own (runner/task_sessions.py).
            origin = tmp_path / "origin.git"
            git_env = {**os.environ, "GIT_AUTHOR_NAME": "Acme", "GIT_AUTHOR_EMAIL": "ops@acme.invalid",
                       "GIT_COMMITTER_NAME": "Acme", "GIT_COMMITTER_EMAIL": "ops@acme.invalid"}
            for args in (["init", "-q", "--bare", "-b", "main", str(origin)], ["-C", str(repo), "init", "-q", "-b", "main"],
                         ["-C", str(repo), "add", "-A"], ["-C", str(repo), "commit", "-q", "-m", "Start"],
                         ["-C", str(repo), "remote", "add", "origin", str(origin)],
                         ["-C", str(repo), "push", "-q", "-u", "origin", "main"]):
                subprocess.run(["git", *args], check=True, env=git_env, capture_output=True)
        home, bin_dir = tmp_path / "home", tmp_path / "bin"
        (home / ".codex").mkdir(parents=True)
        bin_dir.mkdir()
        self.log_path = tmp_path / "harness.jsonl"
        for name in ("claude", "codex"):
            wrapper = bin_dir / name
            # A turn's environment keeps only process settings, so the fakes' own settings ride in the wrapper.
            fake = "".join(f"{k}='{v}' " for k, v in (env or {}).items() if k.startswith("FAKE_"))
            wrapper.write_text(f"#!/bin/sh\n{fake}FAKE_LOG='{self.log_path}' exec '{sys.executable}' '{FAKES / f'fake_{name}.py'}' \"$@\"\n")
            wrapper.chmod(0o755)
        self.config = tmp_path / "config" / "runner.json"
        self.config.parent.mkdir()
        self.config.write_text(json.dumps({"url": live, "token": self.registration["token"],
                                           "runner_id": self.registration["runner_id"],
                                           "projects_dir": str(tmp_path / "projects"), **(registration or {})}))
        keep = {k: v for k, v in os.environ.items() if k in ("LANG", "LC_ALL", "TMPDIR", "USER", "LOGNAME")}
        self.env = {**keep, "HOME": str(home), "CODEX_HOME": str(home / ".codex"), "TICO_UPDATE_CHECK": "off",
                    "PATH": os.pathsep.join([str(bin_dir), str(Path(sys.executable).parent), "/usr/bin", "/bin",
                                             "/usr/sbin", "/sbin"]), **(env or {})}
        self.output = tmp_path / "runner.log"
        self.process = None

    def start(self):
        command = ([str(self.binary)] if self.engine == "rust" else [sys.executable, "-m", "runner"])
        with self.output.open("a") as out:
            self.process = subprocess.Popen(command + ["--config", str(self.config), "run"], cwd=ROOT, env=self.env,
                                            stdout=out, stderr=subprocess.STDOUT, start_new_session=True)
        until(lambda: self.readiness().get("ops", {}).get("ready") or self.died(), "the runner's first heartbeat")
        assert not self.died(), self.output.read_text()[-3000:]
        assert self.readiness()["ops"]["ready"], self.readiness()["ops"]
        settled(self.api, self.registration)        # past the server's wake-up settle, so it is given work

    def died(self):
        return self.process.poll() is not None

    def kill(self):
        os.killpg(self.process.pid, signal.SIGKILL)
        self.process.wait(timeout=10)

    def stop(self):
        if self.process and self.process.poll() is None:
            os.killpg(self.process.pid, signal.SIGTERM)
            try:
                self.process.wait(timeout=20)
            except subprocess.TimeoutExpired:
                self.kill()

    def readiness(self):
        with self.api.app.state.store.read() as c:
            row = c.execute("SELECT readiness_json FROM runners WHERE id=?", (self.registration["runner_id"],)).fetchone()
        return (json.loads(row[0] or "{}") if row else {}).get("bots", {})

    def calls(self):
        if not self.log_path.exists():
            return []
        return [json.loads(line) for line in self.log_path.read_text().splitlines() if line.strip()]

    def prompts(self):
        return [call for call in self.calls() if "prompt" in call]

    def attempts(self):
        with self.api.app.state.store.read() as c:
            rows = c.execute("SELECT id, state, result_json, final_text FROM attempts WHERE runner_id=? ORDER BY created",
                             (self.registration["runner_id"],)).fetchall()
        return [{"id": r[0], "state": r[1], "result": json.loads(r[2] or "null"), "text": r[3]} for r in rows]

    def events(self, aid):
        with self.api.app.state.store.read() as c:
            return [{"seq": r[0], "kind": r[1], "payload": json.loads(r[2])}
                    for r in c.execute("SELECT seq, kind, payload_json FROM attempt_events WHERE attempt_id=? ORDER BY seq", (aid,))]

    def keys(self):
        with self.api.app.state.store.read() as c:
            return {r[0] for r in c.execute("SELECT key FROM idempotency")}


@pytest.fixture(params=["python", "rust"])
def engine(request):
    return request.param


@pytest.fixture(params=["claude", "codex"])
def harness(request):
    return request.param


@pytest.fixture
def setup():
    """What a scenario changes about its computer (Computer's keyword arguments); override with parametrize."""
    return {}


@pytest.fixture
def computer(api, live, tmp_path, engine, harness, setup, request):
    binary = request.getfixturevalue("rust_binary") if engine == "rust" else None
    machine = Computer(api, live, tmp_path, engine, harness, binary, **setup)
    yield machine
    machine.stop()


def reply_to(api, conversation, token="ana-test"):
    messages = get(api, f"conversations/{conversation}/messages", token)
    return next((m for m in reversed(messages) if m["from_actor"] == "bot:ops"), None)


def test_a_chat_turn_streams_completes_and_resumes_the_bot_thread(api, computer):
    computer.start()
    first = post(api, "chat/ops", {"text": "Please answer locally"})
    answer = until(lambda: reply_to(api, first["conversation_id"]), "the bot's reply")
    assert answer["body"] == "Acme reply."
    attempt = computer.attempts()[-1]
    assert attempt["state"] == "completed" and attempt["result"]["outcome"] == "completed"
    kinds = [e["kind"] for e in computer.events(attempt["id"])]
    assert "delta" in kinds and "message" in kinds
    assert {f"started:{attempt['id']}", f"complete:{attempt['id']}"} <= computer.keys()
    usage = attempt["result"].get("usage") or {}
    assert usage.get("output_tokens") == 2 and usage.get("runtime") == computer.harness

    # Another person's conversation continues the bot's one thread, told only what is new.
    second = post(api, "chat/ops", {"text": "A separate question from Ben"}, token="ben-test")
    until(lambda: reply_to(api, second["conversation_id"], "ben-test"), "the second reply")
    calls = computer.prompts() if computer.harness == "claude" else computer.calls()
    if computer.harness == "claude":
        session = calls[0]["argv"][calls[0]["argv"].index("--session-id") + 1]
        assert calls[-1]["argv"][calls[-1]["argv"].index("--resume") + 1] == session
    else:
        starts = [c for c in calls if c.get("method") in ("thread/start", "thread/resume")]
        assert starts[-1] == {"harness": "codex", "method": "thread/resume", "thread": starts[0]["thread"]}
    assert "Please answer locally" not in computer.prompts()[-1]["prompt"]


def test_a_granted_credential_reaches_the_turn_and_never_the_transcript(api, computer):
    from backend.tests.test_credentials import create, setup
    setup(api)
    secret = create(api, name="Acme API", env="ACME_API_KEY", secret=SECRET)
    post(api, f"credentials/{secret['id']}/grants", {"subject": "bot:ops"})
    computer.start()
    msg = post(api, "chat/ops", {"text": "Use the Acme key"})
    answer = until(lambda: reply_to(api, msg["conversation_id"]), "the bot's reply")
    assert computer.prompts()[-1]["env"]["ACME_API_KEY"] == SECRET
    assert SECRET not in json.dumps(get(api, f"conversations/{msg['conversation_id']}/messages"))
    assert "••••" in answer["body"]
    aid = computer.attempts()[-1]["id"]
    assert SECRET not in json.dumps(computer.events(aid))


def test_a_runner_killed_mid_turn_files_the_turn_as_interrupted_when_it_restarts(api, computer):
    computer.start()
    msg = post(api, "chat/ops", {"text": "Please HANG for a while"})
    # The first text reaches the server while the turn is still running.
    attempt = until(lambda: next((a for a in computer.attempts() if a["state"] == "running"
                                  and any(e["kind"] == "delta" for e in computer.events(a["id"]))), None),
                    "the streamed first text")
    computer.kill()
    computer.start()
    done = until(lambda: next((a for a in computer.attempts() if a["id"] == attempt["id"] and a["result"]), None),
                 "the recovered result")
    assert done["result"]["outcome"] == "interrupted"
    assert done["result"]["text"] == "Runner restarted during execution"
    assert msg["conversation_id"]


def running_with_text(computer):
    return next((a for a in computer.attempts() if a["state"] == "running"
                 and any(e["kind"] == "delta" for e in computer.events(a["id"]))), None)


@pytest.mark.parametrize("harness", ["codex"])
def test_a_native_goal_is_set_runs_its_turn_and_a_persons_clear_reaches_codex(api, computer):
    computer.start()
    until(lambda: computer.readiness()["ops"].get("goals") is True, "native goals in readiness")
    conversation = post(api, "conversations", {"participants": ["bot:ops"]})["id"]
    post(api, f"conversations/{conversation}/goal", {"action": "set", "objective": "Keep the Acme summary current"})
    until(lambda: any(c.get("method") == "turn/completed" for c in computer.calls()), "the goal's first turn")
    post(api, f"conversations/{conversation}/goal", {"action": "clear"})
    until(lambda: any(c.get("method") == "thread/goal/clear" for c in computer.calls()), "the native clear")
    calls = computer.calls()
    goal_set = next(c for c in calls if c.get("method") == "thread/goal/set")
    assert goal_set["goal"]["status"] == "active" and goal_set["goal"]["objective"].startswith("Keep the Acme summary current")
    assert next(c for c in calls if c.get("method") == "thread/goal/clear")["thread"] == goal_set["thread"]
    assert get(api, f"conversations/{conversation}/goal")["goal"]["status"] == "cleared"
    done = until(lambda: (lambda rows: rows if len(rows) == 2 and all(a["result"] for a in rows) else None)(computer.attempts()),
                 "both attempts settled")
    assert [a["result"]["outcome"] for a in done] == ["completed", "completed"]
    assert sum(c.get("method") == "turn/start" for c in calls) == 1     # the clear is a control, not a turn


@pytest.mark.parametrize("harness", ["codex"])
@pytest.mark.parametrize("setup", [{"bot": {"fallback": {"harness": "claude", "model": "claude-sonnet-5"}}}])
def test_a_usage_limit_hops_the_turn_to_the_fallback_harness(api, computer):
    computer.start()
    msg = post(api, "chat/ops", {"text": "Please LIMIT yourself"})
    answer = until(lambda: reply_to(api, msg["conversation_id"]), "the fallback's reply")
    assert answer["body"] == "Acme reply."
    result = until(lambda: computer.attempts()[-1]["result"], "the completion")
    assert result["outcome"] == "completed" and result["fallback"] == "claude" and not result.get("limited")
    assert [p["harness"] for p in computer.prompts()] == ["codex", "claude"]
    # A segment per harness that used tokens: the refused Codex turn used none.
    assert [part["runtime"] for part in result["usage"]["segments"]][-1:] == ["claude"]
    diagnostics = [e["payload"].get("text", "") for e in computer.events(computer.attempts()[-1]["id"]) if e["kind"] == "diagnostic"]
    assert "codex unavailable; running this turn on claude" in diagnostics


@pytest.mark.parametrize("setup", [{"env": {"FAKE_SLOW": "8"}}])
def test_a_message_sent_mid_turn_is_steered_into_it_once(api, computer):
    computer.start()
    first = post(api, "chat/ops", {"text": "Please go SLOW"})
    attempt = until(lambda: running_with_text(computer), "the streamed first text")
    post(api, "chat/ops", {"text": "Also count the Acme invoices"})
    until(lambda: (computer.attempts()[-1]["result"] or {}).get("outcome"), "the steered turn's completion", timeout=40)
    delivered = [c for c in computer.calls() if "Acme invoices" in (c.get("steer") or c.get("prompt") or "")]
    assert len(delivered) == 1
    assert [a["id"] for a in computer.attempts()] == [attempt["id"]]      # no turn of its own
    with api.app.state.store.read() as c:
        assert c.execute("SELECT count(*) FROM attempt_inputs WHERE attempt_id=? AND acked_at IS NOT NULL",
                         (attempt["id"],)).fetchone()[0] == 1
    assert reply_to(api, first["conversation_id"])


@pytest.fixture
def profiled(tmp_path):
    directory = tmp_path / "profiles" / "acme"
    for runtime in ("claude", "codex"):
        (directory / runtime).mkdir(parents=True)
    return directory


def test_a_bot_on_a_subscription_profile_runs_in_that_profiles_home(api, live, tmp_path, engine, harness, profiled, request):
    binary = request.getfixturevalue("rust_binary") if engine == "rust" else None
    machine = Computer(api, live, tmp_path, engine, harness, binary,
                       registration={"profiles": {"acme": {"dir": str(profiled)}}, "bot_profiles": {"ops": "acme"}})
    try:
        machine.start()
        assert machine.readiness()["ops"]["profile"] == "acme"
        msg = post(api, "chat/ops", {"text": "Please answer on the Acme subscription"})
        until(lambda: reply_to(api, msg["conversation_id"]), "the bot's reply")
        env = machine.prompts()[-1]["env"]
        assert env["HOME" if harness == "claude" else "CODEX_HOME"] == str(profiled / harness)
        result = until(lambda: machine.attempts()[-1]["result"], "the completion")
        assert result["profile_used"] == "acme"
    finally:
        machine.stop()


@pytest.mark.parametrize("harness", ["codex"])
@pytest.mark.parametrize("setup", [{"bot": {"session": "task"}, "git": True, "registration": {"capacity": 4},
                                    "env": {"FAKE_SLOW": "4"}}])
def test_two_tasks_of_one_bot_run_side_by_side_in_their_own_lanes(api, computer, request):
    if computer.engine == "rust":
        # Task worktrees are the rr-worktrees step; without them a task turn waits for the bot's checkout.
        request.applymarker(pytest.mark.xfail(reason="the Rust runner has no task worktrees yet", strict=False))
    computer.start()
    for title in ("SLOW first", "SLOW second"):
        post(api, "tasks", {"owner": "ops", "title": title, "body": "Please do " + title + "."})
    until(lambda: len([c for c in computer.calls() if c.get("method") == "turn/completed"]) == 2, "both task turns", timeout=60)
    starts = sorted(c["at"] for c in computer.calls() if c.get("method") == "turn/start")
    ends = sorted(c["at"] for c in computer.calls() if c.get("method") == "turn/completed")
    assert len(starts) == 2 and starts[1] < ends[0], (starts, ends)
