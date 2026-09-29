"""docker/updater.py: the database snapshot around an update, and the updater replacing itself."""
import json

import pytest

from backend.tests.test_updater_runner import load


class Fake:
    """`docker`: records argv, and answers inspect/ps from tables. `fail` names a compose verb that exits 1."""

    def __init__(self, module, monkeypatch, healthy=(True,), fail=(), container=None):
        self.calls, self.answers, self.fail, self.container = [], list(healthy), set(fail), container
        monkeypatch.setattr(module.subprocess, "run", self.run)
        monkeypatch.setattr(module, "healthy", lambda seconds: self.answers.pop(0))
        monkeypatch.setattr(module, "running_image", lambda: ("sha256:old", "v0.1.0"))

    def verbs(self):
        return [next(x for x in a[a.index("--project-directory") + 2:] if not x.startswith("-")) for a, _ in self.calls
                if a[:2] == ["docker", "compose"]]

    def run(self, argv, env=None, **kw):
        self.calls.append((argv, env))
        out, code = "", 0
        if argv[:2] == ["docker", "compose"]:
            verb = next(x for x in argv[argv.index("--project-directory") + 2:] if not x.startswith("-"))
            code = 1 if verb in self.fail else 0
            out = "updater-1\n" if "ps" in argv else ""
        elif argv[:2] == ["docker", "inspect"]:
            out = json.dumps([self.container(argv[2])])
        return type("R", (), {"returncode": code, "stdout": out, "stderr": "boom" if code else ""})()


def test_a_snapshot_is_taken_before_the_switch_and_left_alone_when_the_update_works(monkeypatch, tmp_path):
    updater = load(monkeypatch, "", tmp_path)
    docker = Fake(updater, monkeypatch, [True])
    updater.update("v0.2.0")
    assert updater.status["state"] == "healthy" and updater.status["snapshot"].startswith("pre-update-v0.1.0-")
    verbs = docker.verbs()
    assert verbs.index("exec") < verbs.index("up") and "run" not in verbs and updater.status["restored"] is False
    exec_call = next(a for a, _ in docker.calls if "exec" in a)
    assert "/data/snapshots" in exec_call and "hub.sqlite" in updater.SNAPSHOT_SCRIPT and "backup(" in updater.SNAPSHOT_SCRIPT


def test_a_failed_health_check_restores_the_snapshot_because_migrations_may_have_run(monkeypatch, tmp_path):
    updater = load(monkeypatch, "", tmp_path)
    docker = Fake(updater, monkeypatch, [False, True])
    updater.update("v0.2.0")
    status = updater.status
    assert status["state"] == "rolled_back" and status["restored"] is True and status["snapshot"] in status["message"]
    assert "Went back to v0.1.0" in status["message"] and "Restored the database" in status["message"]
    verbs = docker.verbs()
    assert verbs[-3:] == ["stop", "run", "up"]                       # server stopped, snapshot back, old image up
    run_call, env = next((a, e) for a, e in docker.calls if "run" in a and a[:2] == ["docker", "compose"])
    assert env["TICO_TAG"] == "v0.1.0" and "--entrypoint" in run_call     # the OLD image puts it back
    assert json.loads((tmp_path / ".updater-status.json").read_text())["restored"] is True


def test_the_restore_script_swaps_the_database_and_clears_litestreams_tracking(monkeypatch, tmp_path):
    import sqlite3, subprocess, sys
    updater = load(monkeypatch, "", tmp_path)
    for name, value in (("snap.sqlite", "before"), ("hub.sqlite", "migrated")):
        db = sqlite3.connect(tmp_path / name)
        db.execute("CREATE TABLE t(v)"); db.execute("INSERT INTO t VALUES(?)", (value,)); db.commit(); db.close()
    (tmp_path / ".hub.sqlite-litestream").mkdir()
    (tmp_path / ".hub.sqlite-litestream" / "ltx").write_text("x")
    (tmp_path / "hub.sqlite-wal").write_text("stale")
    subprocess.run([sys.executable, "-c", updater.RESTORE_SCRIPT, str(tmp_path / "snap.sqlite"), str(tmp_path / "hub.sqlite")], check=True)
    value = lambda name: sqlite3.connect(tmp_path / name).execute("SELECT v FROM t").fetchone()[0]
    assert value("hub.sqlite") == "before" and value("hub.sqlite.failed-update") == "migrated"
    assert not (tmp_path / ".hub.sqlite-litestream").exists() and not (tmp_path / "hub.sqlite-wal").exists()
    assert not (tmp_path / "hub.sqlite.restoring").exists()


def test_a_pull_failure_or_snapshot_failure_does_not_touch_the_database(monkeypatch, tmp_path):
    updater = load(monkeypatch, "", tmp_path)
    docker = Fake(updater, monkeypatch, [True], fail=["exec"])
    updater.update("v0.2.0")
    assert updater.status["state"] == "rolled_back" and "could not snapshot" in updater.status["message"]
    assert "stop" not in docker.verbs() and updater.status["restored"] is False


def container(updater, mode_dir, tag="v0.1.0"):
    def inspect(ref):
        return {"Image": "sha256:oldupdater", "Name": "/tico-updater-1", "Config": {"Image": "ghcr.io/ticoteam/tico-updater:" + tag},
                "Mounts": [{"Destination": updater.PROJECT, "Source": str(mode_dir)}], "State": {"Running": True}}
    return inspect


@pytest.mark.parametrize("mode", ["server", "runner"])
def test_after_an_update_a_helper_from_the_new_image_replaces_the_updater(monkeypatch, tmp_path, mode):
    updater = load(monkeypatch, mode, tmp_path)
    monkeypatch.setenv("TICO_UPDATER_SELF", "always")
    monkeypatch.setenv("TICO_UPDATER_PULL", "always")
    monkeypatch.setenv("HOSTNAME", "abc")
    monkeypatch.setattr(updater, "SELF_UPDATE", "always")
    docker = Fake(updater, monkeypatch, container=container(updater, "/srv/tico"))
    note = updater.replace_updater("v0.2.0")
    assert "replacing itself with v0.2.0" in note
    pulled = [a for a, _ in docker.calls if a[:2] == ["docker", "pull"]]
    assert pulled == [["docker", "pull", "ghcr.io/ticoteam/tico-updater:v0.2.0"]]
    run = next(a for a, _ in docker.calls if a[:3] == ["docker", "run", "-d"])
    joined = " ".join(run)
    assert "ghcr.io/ticoteam/tico-updater:v0.2.0 python /usr/local/bin/tico-updater replace-self" in joined
    assert "/srv/tico:/srv/tico" in joined and "TICO_PROJECT_DIR=/srv/tico" in joined and "TICO_SWAP_OLD_ID=sha256:oldupdater" in joined
    assert "TICO_UPDATER_MODE=" + mode in joined
    assert ("TICO_COMPOSE_FILE=runner.compose.yaml" in joined) == (mode == "runner")


def helper(monkeypatch, tmp_path, image_after):
    updater = load(monkeypatch, "server", tmp_path)
    monkeypatch.setenv("TICO_SWAP_TAG", "v0.2.0")
    monkeypatch.setenv("TICO_SWAP_OLD_ID", "sha256:oldupdater")
    monkeypatch.setenv("TICO_SWAP_OLD_REF", "ghcr.io/ticoteam/tico-updater:v0.1.0")
    (tmp_path / ".env").write_text("TICO_TAG=v0.2.0\nTICO_UPDATER_TAG=v0.1.0\n")
    monkeypatch.setattr(updater.time, "sleep", lambda s: None)
    clock = iter(range(0, 10000, 5))
    monkeypatch.setattr(updater.time, "time", lambda: next(clock))
    docker = Fake(updater, monkeypatch, container=lambda ref: {"Image": image_after, "State": {"Running": True}})
    return updater, docker


def test_the_helper_puts_the_old_updater_back_when_the_new_one_does_not_stay_up(monkeypatch, tmp_path):
    updater, docker = helper(monkeypatch, tmp_path, "sha256:oldupdater")    # still the old image: it never got replaced
    assert updater.replace_self() == 1
    assert ["docker", "tag", "sha256:oldupdater", "ghcr.io/ticoteam/tico-updater:v0.1.0"] in [a for a, _ in docker.calls]
    assert [e["TICO_UPDATER_TAG"] for a, e in docker.calls if "up" in a] == ["v0.2.0", "v0.1.0"]
    assert "TICO_UPDATER_TAG=v0.1.0" in (tmp_path / ".env").read_text()      # the pin never moved


def test_the_new_updater_does_not_inherit_the_helpers_pull_and_bundle_settings(monkeypatch, tmp_path):
    updater, docker = helper(monkeypatch, tmp_path, "sha256:newupdater")
    monkeypatch.setenv("TICO_UPDATER_PULL", "never")     # how replace_updater starts the helper
    monkeypatch.setenv("TICO_UPDATER_BUNDLE", "never")
    assert updater.replace_self() == 0
    up = next(e for a, e in docker.calls if "up" in a)
    assert "TICO_UPDATER_PULL" not in up and "TICO_UPDATER_BUNDLE" not in up
