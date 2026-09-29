from pathlib import Path
from unittest.mock import Mock, patch

import pytest

from backend.operations import api_healthy, backup, health, replication_healthy, restore_check, tunnel_healthy
from backend.store import H
from backend.tests.test_api import api


def test_operational_health_never_advances_backup_time_after_failed_upload(api):
    store = api.app.state.store
    s3, cw = Mock(), Mock()
    with patch("backend.operations.upload_bundle", return_value={"verified": True, "sha256": "a" * 64,
                                                                "bytes": 1, "objects": 0, "object_bytes": 0,
                                                                "manifest_sha256": "b" * 64}):
        backup(store, s3, cw, "test-bucket")
    with store.read() as c:
        before = c.execute("SELECT last_success FROM service_health WHERE service='backup'").fetchone()[0]
    with patch("backend.operations.upload_bundle", side_effect=RuntimeError("cannot upload")), pytest.raises(RuntimeError):
        backup(store, s3, cw, "test-bucket")
    with store.read() as c:
        row = c.execute("SELECT * FROM service_health WHERE service='backup'").fetchone()
        assert row["last_success"] == before and row["last_error"] == "RuntimeError"
    with patch("backend.operations.api_healthy", return_value=True), patch("backend.operations.replication_healthy", return_value=True), patch("backend.operations.tunnel_healthy", return_value=True):
        metrics = health(store, cw)
    assert metrics["disk_free_bytes"] > 0
    assert metrics["api_healthy"] is True and metrics["replication_healthy"] is True and metrics["tunnel_healthy"] is True
    assert cw.put_metric_data.call_count == 9
    assert all({"Name": "Scope", "Value": "default"} in call.kwargs["MetricData"][0]["Dimensions"]
               for call in cw.put_metric_data.call_args_list)


def test_failed_restore_check_does_not_advance_prior_success(api, tmp_path):
    store = api.app.state.store
    from backend.tests.test_backup_bundle import ObjectStore
    s3, cw = ObjectStore(), Mock()
    backup(store, s3, cw, "bucket")
    with patch("backend.operations.RESTORE_ROOT", tmp_path / "checks"):
        restore_check(store, s3, cw, "bucket")
        with store.read() as c:
            before = c.execute("SELECT last_success FROM service_health WHERE service='restore-check'").fetchone()[0]
        with patch("backend.operations.restore_bundle", side_effect=RuntimeError("corrupt")), pytest.raises(RuntimeError):
            restore_check(store, s3, cw, "bucket")
    with store.read() as c:
        row = c.execute("SELECT * FROM service_health WHERE service='restore-check'").fetchone()
    assert row["last_success"] == before and row["last_error"] == "RuntimeError"
    assert cw.put_metric_data.call_args.kwargs["MetricData"][0]["Value"] == 0

