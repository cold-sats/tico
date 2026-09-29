"""Docker integration: bot code cannot read the runner's registration, and still works.

Needs Docker and a built runner image; skipped otherwise:
    docker build --target runner -t tico-runner:local .
    TICO_RUNNER_TEST_IMAGE=tico-runner:local pytest runner/tests/test_isolation_docker.py

It starts the image the way docker/runner.compose.yaml does (root, five capabilities) on a volume laid
out the way an older image left it (everything owned by 10002), so the one-time migration runs too.
Inside, runner/tests/isolation/turn_side.py plays the supervisor and drops a turn to the bot user. Then
the volume is used the way an older image (no capabilities, only uid 10002) would after a rolled-back
update: it must still read its registration and state and run a harness, and `bot` must still not.
"""
import json
import os
import shutil
import subprocess
import uuid
from pathlib import Path

import pytest

IMAGE = os.environ.get("TICO_RUNNER_TEST_IMAGE", "tico-runner:local")
HERE = Path(__file__).parent / "isolation"


def docker(*args, **kwargs):
    return subprocess.run(["docker", *args], capture_output=True, text=True, timeout=300, **kwargs)


@pytest.fixture
def volume():
    if not shutil.which("docker") or docker("image", "inspect", IMAGE).returncode != 0:
        pytest.skip(f"Docker or the runner image {IMAGE} is not available")
    name = "tico-isolation-test-" + uuid.uuid4().hex[:8]
    yield name
    docker("volume", "rm", "-f", name)


CAPS = [a for cap in ("CHOWN", "DAC_OVERRIDE", "KILL", "SETGID", "SETUID") for a in ("--cap-add", cap)]


def test_a_turn_cannot_read_the_registration_but_can_run_a_harness_and_push(volume):
    # A volume from before this change: one user, 10002, owns everything.
    seeded = docker("run", "--rm", "-u", "10002", "-v", f"{volume}:/home/runner", "--entrypoint", "sh", IMAGE, "-c", """
        set -e; cd /home/runner
        echo '{"token": "REGISTRATION-SECRET"}' > runner.json; chmod 600 runner.json
        mkdir -p state-abc tools/bin .codex workspace/emp-alpha; echo secret > state-abc/runner.sqlite; chmod 700 state-abc
        echo '{"login": "chatgpt"}' > .codex/auth.json; chmod 600 .codex/auth.json
        printf '#!/bin/sh\\necho "codex logged in: $(cat "$HOME/.codex/auth.json")"\\n' > tools/bin/codex; chmod 755 tools/bin/codex
    """)
    assert seeded.returncode == 0, seeded.stderr
    ran = docker("run", "--rm", "--user", "0", "--cap-drop", "ALL", "--security-opt", "no-new-privileges:true", *CAPS,
                 "-v", f"{volume}:/home/runner",
                 "-v", f"{HERE / 'turn_side.py'}:/turn_side.py:ro", "-v", f"{HERE / 'turn.sh'}:/turn.sh:ro",
                 IMAGE, "python", "/turn_side.py")
    assert ran.returncode == 0, ran.stdout + ran.stderr
    result = json.loads(ran.stdout.strip().splitlines()[-1])
    turn = dict(line.split("=", 1) for line in result["turn"])
    assert turn["uid"] == "10003" and turn["caps"] == "CapEff:0000000000000000", result
    assert turn["read_registration"] == "no" and turn["delete_registration"] == "no", result
    assert turn["read_state"] == "no" and turn["registration_in_env"] == "no", result
    assert result["registration"] == "ticorun 600", result
    assert turn["harness"] == 'codex logged in: {"login": "chatgpt"}', result       # the model login moved with the bot
    assert turn["push"] == "ok" and result["pushed"] == "from the turn", result        # the helper got the bot's token
    assert result["auth_seen"][-1].startswith("Basic ") and len(result["auth_seen"]) == 2, result   # 401, then the token

    # The update is rolled back: the previous image runs as 10002 with no capabilities on the migrated volume.
    old = docker("run", "--rm", "-u", "10002", "-v", f"{volume}:/home/runner", "--entrypoint", "sh", IMAGE, "-c", """
        set -e; cd /home/runner
        grep -q REGISTRATION-SECRET runner.json
        echo more >> state-abc/runner.sqlite                   # its state is still its own to write
        python3 -c 'import json; c = json.load(open("runner.json")); json.dump(c, open("runner.json", "w"))'   # as the entrypoint rewrites it
        [ "$(tools/bin/codex login status)" = 'codex logged in: {"login": "chatgpt"}' ]   # the login is still readable
        cd workspace/emp-alpha && git init -q -b main . && git -c user.name=t -c user.email=t@x commit -q --allow-empty -m old
    """)
    assert old.returncode == 0, old.stdout + old.stderr
    # ...and the bot user still cannot open any of it.
    for path in ("runner.json", "state-abc/runner.sqlite"):
        blocked = docker("run", "--rm", "-u", "10003", "-v", f"{volume}:/home/runner", "--entrypoint", "sh", IMAGE, "-c",
                         f"! cat /home/runner/{path} >/dev/null 2>&1")
        assert blocked.returncode == 0, path
