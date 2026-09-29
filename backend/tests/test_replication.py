import hashlib
import json
import os
import sqlite3
import subprocess
import textwrap
from datetime import datetime, timezone
from pathlib import Path

import pytest

from backend import replication
from backend.config import ROOT
from backend.tests.test_onboarding import environment, signed_in  # noqa: F401

ENTRYPOINT = ROOT / "docker/entrypoint.sh"


def test_status_modes(tmp_path):
    stamp = tmp_path / "status.json"
    stamp.write_text(json.dumps({"last_replicated_at": "2026-01-02T03:04:05Z"}))
    local = replication.status({"TICO_BACKUP_MODE": "local-only"}, stamp)
    assert local["mode"] == "local-only" and local["target_kind"] == "local"
    assert local["last_replicated_at"] == "2026-01-02T03:04:05Z" and "tico-backups" in local["warning"]
    r2 = replication.status({"TICO_BACKUP_MODE": "remote", "TICO_BACKUP_URL": "s3://b/p",
                             "TICO_BACKUP_ENDPOINT": "https://x.r2.cloudflarestorage.com"}, stamp)
    assert (r2["mode"], r2["target_kind"], r2["warning"]) == ("remote", "r2", "")
    assert replication.status({"TICO_BACKUP_MODE": "remote", "TICO_BACKUP_URL": "s3://b"}, stamp)["target_kind"] == "s3"
    minio = replication.status({"TICO_BACKUP_MODE": "remote", "TICO_BACKUP_URL": "s3://b", "TICO_BACKUP_ENDPOINT": "http://minio:9000"}, stamp)
    assert minio["target_kind"] == "s3-compatible"
    off = replication.status({"TICO_BACKUP_MODE": "off"}, stamp)
    assert off["mode"] == "off" and off["target_kind"] == "none" and off["warning"]
    # No status file yet: the replica has not been written, which is not the same as a time.
    assert replication.status({"TICO_BACKUP_MODE": "remote", "TICO_BACKUP_URL": "s3://b"}, tmp_path / "none")["last_replicated_at"] is None


def test_status_outside_the_container_reports_only_what_is_configured():
    assert replication.status({})["mode"] is None      # a VM install runs its own Litestream
    assert replication.status({"TICO_BACKUP_URL": "s3://b/p"})["mode"] == "remote"
    assert replication.mode_from_env({"TICO_BACKUP": "off", "TICO_BACKUP_URL": "s3://b"}) == "off"
    assert replication.mode_from_env({}) == "local-only"


def test_config_payload_carries_the_backup_status(environment, monkeypatch):
    api = environment()
    monkeypatch.setenv("TICO_BACKUP_MODE", "local-only")
    backup = api.get("/api/v2/config", headers=signed_in()).json()["backup"]
    assert backup["mode"] == "local-only" and backup["target_kind"] == "local" and backup["warning"]


class FakeS3:
    """Just the calls S3Mirror makes, over a dict."""
    def __init__(self):
        self.objects = {}

    def get_paginator(self, name):
        assert name == "list_objects_v2"
        outer = self

        class Pages:
            def paginate(self, Bucket, Prefix):
                yield {"Contents": [{"Key": k, "LastModified": datetime(2026, 5, 1, tzinfo=timezone.utc)}
                                    for k in sorted(outer.objects) if k.startswith(Prefix)]}
        return Pages()

    def upload_file(self, path, bucket, key):
        self.objects[key] = Path(path).read_bytes()

    def download_file(self, bucket, key, path):
        Path(path).write_bytes(self.objects[key])


def put_blob(root, data):
    digest = hashlib.sha256(data).hexdigest()
    path = root / "blobs" / digest[:2] / digest
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return digest


@pytest.mark.parametrize("kind", ["local", "s3"])
def test_blobs_sync_incrementally_and_restore_verified(tmp_path, kind):
    mirror = replication.LocalMirror(tmp_path / "backups") if kind == "local" else replication.S3Mirror(FakeS3(), "bucket", "tico/")
    live = tmp_path / "live"
    first = put_blob(live, b"one")
    (live / "blobs" / "ab").mkdir(parents=True, exist_ok=True)
    (live / "blobs" / "ab" / ".upload-partial").write_bytes(b"half")
    assert replication.sync_blobs(live, mirror) == 1
    second = put_blob(live, b"two")
    assert replication.sync_blobs(live, mirror) == 1 and replication.sync_blobs(live, mirror) == 0
    fresh = tmp_path / "fresh"
    assert replication.restore_blobs(mirror, fresh) == 2
    assert (fresh / "blobs" / first[:2] / first).read_bytes() == b"one"
    assert (fresh / "blobs" / second[:2] / second).read_bytes() == b"two"
    assert not list(fresh.rglob(".upload-*")) and not list(fresh.rglob(".restore-*"))


def test_restore_rejects_a_blob_that_fails_its_checksum(tmp_path):
    mirror = replication.LocalMirror(tmp_path / "backups")
    bad = tmp_path / "backups" / "files" / "blobs" / "aa" / ("a" * 64)
    bad.parent.mkdir(parents=True)
    bad.write_bytes(b"tampered")
    with pytest.raises(SystemExit, match="checksum"):
        replication.restore_blobs(mirror, tmp_path / "fresh")


def test_write_status_uses_the_newest_replica_object(tmp_path):
    mirror = replication.LocalMirror(tmp_path / "b")
    path = tmp_path / "status.json"
    replication.write_status(mirror, path)
    assert not path.exists()
    segment = tmp_path / "b" / "0000" / "0000000000000001-0000000000000001.ltx"
    segment.parent.mkdir(parents=True)
    segment.write_bytes(b"x")
    os.utime(segment, (1_800_000_000, 1_800_000_000))
    replication.write_status(mirror, path)
    assert json.loads(path.read_text())["last_replicated_at"] == "2027-01-15T08:00:00Z"


def test_the_loop_survives_a_failing_sync_and_repeats_its_warning(tmp_path, capsys):
    env = {"TICO_BACKUP_MODE": "local-only", "TICO_BACKUP_DIR": str(tmp_path / "b"), "TICO_BLOB_DIR": str(tmp_path / "blobs"),
           "TICO_BACKUP_STATUS_FILE": str(tmp_path / "s.json")}
    replication.loop(env, interval=0, warn_every=0, sleep=lambda _: None, rounds=2)
    assert capsys.readouterr().out.count("WARNING") == 2


def entrypoint(tmp_path, *args, command="restore", env=None):
    data, backups, bin_dir = tmp_path / "data", tmp_path / "backups", tmp_path / "bin"
    data.mkdir(exist_ok=True)
    backups.mkdir(exist_ok=True)
    bin_dir.mkdir(exist_ok=True)
    stub = bin_dir / "litestream"
    # restore -if-replica-exists -config CFG DB: write the database it would have restored
    stub.write_text(textwrap.dedent("""\
        #!/bin/sh
        echo "$@" >> "$STUB_LOG"
        if [ "$1" = restore ]; then
          [ -z "$STUB_FAIL" ] || { echo "AccessDenied" >&2; exit 1; }
          [ -f "$STUB_DB" ] && cp "$STUB_DB" "$(eval echo \\${$#})"
        fi
        exit 0
    """))
    stub.chmod(0o755)
    source = tmp_path / "source.sqlite"
    with sqlite3.connect(source) as db:
        db.execute("CREATE TABLE IF NOT EXISTS t(x)")
        db.execute("INSERT INTO t VALUES(1)")
    env = {**os.environ, "PATH": f"{bin_dir}:{Path(__import__('sys').executable).parent}:{os.environ['PATH']}",
           "TICO_DATA_DIR": str(data), "TICO_BACKUP_DIR": str(backups), "PYTHONPATH": str(ROOT),
           "STUB_LOG": str(tmp_path / "stub.log"), "STUB_DB": str(source), **(env or {})}
    env.pop("TICO_BACKUP_URL", None)
    return subprocess.run(["bash", str(ENTRYPOINT), command, *([] if command == "prepare" else args)], env=env, capture_output=True, text=True, timeout=60)


def test_restore_refuses_a_non_empty_volume_without_force(tmp_path):
    (tmp_path / "data").mkdir()
    (tmp_path / "data" / "hub.sqlite").write_bytes(b"live")
    result = entrypoint(tmp_path)
    assert result.returncode != 0 and "--force" in result.stderr
    assert (tmp_path / "data" / "hub.sqlite").read_bytes() == b"live"
    assert not (tmp_path / "stub.log").exists()


def test_restore_into_an_empty_volume_and_force_over_a_full_one(tmp_path):
    result = entrypoint(tmp_path)
    assert result.returncode == 0, result.stderr
    assert sqlite3.connect(tmp_path / "data" / "hub.sqlite").execute("SELECT x FROM t").fetchone() == (1,)
    forced = entrypoint(tmp_path)
    assert forced.returncode != 0
    forced = entrypoint(tmp_path, "--force")
    assert forced.returncode == 0, forced.stderr
    assert list((tmp_path / "data").glob("hub.sqlite.before-restore.*"))


def test_restore_with_backups_off_says_there_is_nothing_to_restore(tmp_path, monkeypatch):
    monkeypatch.setenv("TICO_BACKUP", "off")
    result = entrypoint(tmp_path)
    assert result.returncode != 0 and "nothing to restore" in result.stderr


def prepare(tmp_path, restore_fails=False, **extra):
    """`docker/entrypoint.sh prepare` on a file replica (the tico-backups directory), with a fake litestream."""
    env = {"TICO_COMPANY_NAME": "Acme", "TICO_OWNER_EMAIL": "owner@example.com", "TICO_AUTH_PROXY": "none",
           "TICO_LOCAL_OWNER_TOKEN_FILE": str(tmp_path / "token"), "STUB_FAIL": "1" if restore_fails else "",
           "STUB_DB": str(tmp_path / "no-replica"), **extra}
    data = tmp_path / "data"
    data.mkdir(exist_ok=True)
    result = entrypoint(tmp_path, "prepare", command="prepare", env=env)
    return result, data


def test_a_failed_restore_of_an_existing_company_refuses_to_start(tmp_path):
    (tmp_path / "backups").mkdir()
    (tmp_path / "backups" / replication.MARKER).write_text('{"environment_id": "acme1"}')
    result, data = prepare(tmp_path, restore_fails=True)
    assert result.returncode != 0 and "existing company" in result.stderr and "TICO_INITIALIZE_EMPTY" in result.stderr
    assert not (data / "hub.sqlite").exists() and not (data / replication.LOCAL_MARKER).exists()


def test_an_unreadable_backup_refuses_even_with_no_marker(tmp_path):
    result, data = prepare(tmp_path, restore_fails=True)
    assert result.returncode != 0 and "unknown whether" in result.stderr and not (data / "hub.sqlite").exists()


def test_a_new_company_over_an_existing_backup_needs_initialize_empty(tmp_path):
    level = tmp_path / "backups" / "ltx" / "0"
    level.mkdir(parents=True)
    (level / "0000000000000001-0000000000000001.ltx").write_bytes(b"x")      # a replica holds a database, no marker yet
    refused, data = prepare(tmp_path)
    assert refused.returncode != 0 and "existing company" in refused.stderr and not (data / "hub.sqlite").exists()
    allowed, _ = prepare(tmp_path, TICO_INITIALIZE_EMPTY="1")
    assert allowed.returncode == 0, allowed.stderr
    assert (data / "hub.sqlite").exists() and (data / replication.LOCAL_MARKER).exists()
    assert (tmp_path / "backups" / replication.MARKER).exists()


def test_a_fresh_install_starts_and_leaves_markers_a_later_empty_volume_respects(tmp_path):
    fresh, data = prepare(tmp_path)
    assert fresh.returncode == 0, fresh.stderr
    marker = json.loads((tmp_path / "backups" / replication.MARKER).read_text())["environment_id"]
    assert json.loads((data / replication.LOCAL_MARKER).read_text())["environment_id"] == marker
    for item in data.iterdir():                     # the volume is lost; the backup location keeps the marker
        subprocess.run(["rm", "-rf", str(item)])
    again, _ = prepare(tmp_path, restore_fails=True)
    assert again.returncode != 0 and not (data / "hub.sqlite").exists()
