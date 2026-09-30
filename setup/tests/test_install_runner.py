"""scripts/install.sh --runner, run for real against a local release with docker and the host checks stubbed.

Unlike test_install_sh.py this needs no container: everything the script touches is under tmp_path."""
import shutil
import stat
import subprocess
from pathlib import Path

import pytest

from setup.tests.test_install_sh import SCRIPTS, build, docker_ready  # noqa: F401

ROOT = SCRIPTS.parent
DOCKER = """#!/bin/sh
echo "docker $*" >> "$STUB_LOG"
case "$*" in
  "compose version --short") echo 2.29.7 ;;
  "version --format"*) echo 27.0.0 ;;
  "volume inspect tico-runner") [ -n "${STUB_VOLUME:-}" ] || exit 1 ;;
  "container inspect"*) [ -n "${STUB_BARE:-}" ] || exit 1 ;;
esac
exit 0
"""


@pytest.fixture
def box(tmp_path):
    """A fake Linux server: stub tools first on PATH, a local release to download, a directory to install into."""
    stubs = tmp_path / "stubs"
    stubs.mkdir()
    (stubs / "docker").write_text(DOCKER)
    (stubs / "uname").write_text('#!/bin/sh\ncase "$1" in -s) echo Linux;; -m) echo x86_64;; *) exec /usr/bin/uname "$@";; esac\n')
    (stubs / "id").write_text('#!/bin/sh\nif [ "$1" = -u ]; then echo 0; else exec /usr/bin/id "$@"; fi\n')
    (stubs / "df").write_text("#!/bin/sh\nprintf 'Filesystem 1024-blocks Used Available Capacity Mounted on\\nfake 1 1 50000000 1%% /\\n'\n")
    (stubs / "ss").write_text("#!/bin/sh\nexit 0\n")
    (stubs / "hostname").write_text("#!/bin/sh\necho build-host\n")
    for tool in stubs.iterdir():
        tool.chmod(tool.stat().st_mode | stat.S_IXUSR)
    (tmp_path / "meminfo").write_text("MemTotal:        2000000 kB\n")
    rel = tmp_path / "rel"
    version = "v0.2.0"
    assert build.main(["--version", version, "--output", str(rel / "download" / version), "--source", str(ROOT)]) == 0
    return {"stubs": stubs, "rel": rel, "dir": tmp_path / "runner", "log": tmp_path / "docker.log", "tmp": tmp_path}


def install(box, *args, **env):
    variables = {"PATH": f"{box['stubs']}:/usr/bin:/bin:/usr/sbin:/sbin:/usr/local/bin:/opt/homebrew/bin",
                 "HOME": str(box["tmp"]), "STUB_LOG": str(box["log"]),
                 "TICO_INSTALL_RELEASES_URL": "file://" + str(box["rel"]),
                 "TICO_INSTALL_MEMINFO": str(box["tmp"] / "meminfo"), **env}
    script = box["rel"] / "download" / "v0.2.0" / "install.sh"
    return subprocess.run(["sh", str(script), "--dir", str(box["dir"]), *args], env=variables,
                          capture_output=True, text=True, timeout=120)


JOIN = ("--runner", "--url", "https://tico.example.com", "--code", "code_123-abc", "--label", "Ana's build box")


def test_runner_mode_writes_the_compose_file_and_a_pinned_env_and_starts_it(box):
    result = install(box, *JOIN)
    assert result.returncode == 0, result.stdout + result.stderr
    compose = (box["dir"] / "runner.compose.yaml").read_text()
    assert "tico-updater" in compose and "updater:" in compose        # the sidecar is what follows the release
    assert not (box["dir"] / "compose.yaml").exists()                 # the server's file stays out
    env = (box["dir"] / ".env").read_text().splitlines()
    assert env == ["TICO_URL=https://tico.example.com", "TICO_CODE=code_123-abc",
                   'TICO_RUNNER_LABEL="Ana\'s build box"', "TICO_TAG=v0.2.0", "TICO_UPDATER_TAG=v0.2.0"]
    assert stat.S_IMODE((box["dir"] / ".env").stat().st_mode) == 0o600
    calls = box["log"].read_text()
    assert "docker compose -f runner.compose.yaml up -d" in calls
    assert "docker run" not in calls


def test_running_it_again_keeps_the_env_and_a_bare_docker_run_switches_over_with_its_volume(box):
    assert install(box, *JOIN).returncode == 0
    (box["dir"] / ".env").write_text((box["dir"] / ".env").read_text() + "TICO_RUNNER_PINNED=1\n")
    before = (box["dir"] / ".env").read_text()
    again = install(box, "--runner")                                    # no join flags: the update path
    assert again.returncode == 0 and "Keeping the settings" in again.stdout
    assert (box["dir"] / ".env").read_text() == before
    shutil.rmtree(box["dir"])
    box["log"].write_text("")
    switched = install(box, *JOIN, STUB_VOLUME="1", STUB_BARE="1")
    assert switched.returncode == 0, switched.stderr
    assert "TICO_RUNNER_HOME_VOLUME=tico-runner" in (box["dir"] / ".env").read_text()
    calls = box["log"].read_text()
    assert "docker rm -f tico-runner" in calls
    assert calls.index("docker rm -f tico-runner") < calls.index("up -d")



def test_a_new_code_url_or_label_replaces_only_those_keys_of_an_existing_env(box):
    assert install(box, *JOIN).returncode == 0
    env = box["dir"] / ".env"
    env.write_text(env.read_text() + "TICO_RUNNER_PINNED=1\n")
    again = install(box, "--runner", "--code", "fresh-code_9", "--url", "https://new.example.com")
    assert again.returncode == 0, again.stdout + again.stderr
    assert "Updating TICO_URL TICO_CODE in" in again.stdout and "other settings are kept" in again.stdout
    assert env.read_text().splitlines() == [
        "TICO_URL=https://new.example.com", "TICO_CODE=fresh-code_9", 'TICO_RUNNER_LABEL="Ana\'s build box"',
        "TICO_TAG=v0.2.0", "TICO_UPDATER_TAG=v0.2.0", "TICO_RUNNER_PINNED=1"]
    assert stat.S_IMODE(env.stat().st_mode) == 0o600
    assert "up -d" in box["log"].read_text()
    # A key the file lacks is added, and a label alone leaves the join code as it was.
    env.write_text("TICO_TAG=v0.2.0\n")
    assert install(box, "--runner", "--label", "Box 2").returncode == 0
    assert env.read_text().splitlines() == ["TICO_TAG=v0.2.0", 'TICO_RUNNER_LABEL="Box 2"']
