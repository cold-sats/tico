"""An actual Litestream process, WAL writes, and independent restores from its replica."""

import os
from pathlib import Path
import sqlite3
import subprocess
import time

import pytest
import yaml

from backend.config import ROOT


def test_continuous_replication_restores_wal_commits(tmp_path):
    binary = Path(os.environ.get("LITESTREAM_BINARY", ROOT / "runtime/cloud-tools/litestream"))
    if not binary.is_file():
        pytest.skip("Install the checksum-pinned Litestream binary to run the restore integration test")
    source = tmp_path / "live.sqlite"
    replica = tmp_path / "replica"
    config = tmp_path / "litestream.yml"
    config.write_text(yaml.safe_dump({"dbs": [{"path": str(source), "replica": {"url": replica.as_uri(), "sync-interval": "100ms"}}]}))
    connection = sqlite3.connect(source)
    connection.execute("PRAGMA journal_mode=WAL")
    connection.execute("PRAGMA wal_autocheckpoint=0")
    connection.execute("CREATE TABLE messages(id INTEGER PRIMARY KEY, body TEXT)")
    connection.commit()
    with (tmp_path / "replicate.log").open("w") as log:
        process = subprocess.Popen([str(binary), "replicate", "-config", str(config)], stdout=log, stderr=log)
        try:
            for n in range(30):
                connection.execute("INSERT INTO messages VALUES(?,?)", (n, "A durable conversation " + str(n)))
                connection.commit()
                time.sleep(0.02)
            deadline, index, restored = time.monotonic() + 20, 0, False
            while time.monotonic() < deadline:
                assert process.poll() is None, "Replication process exited"
                dest = tmp_path / f"restored-{index}.sqlite"
                result = subprocess.run([str(binary), "restore", "-o", str(dest), replica.as_uri()], capture_output=True, timeout=10)
                if result.returncode == 0:
                    with sqlite3.connect(dest) as c:
                        if c.execute("SELECT count(*) FROM messages").fetchone()[0] == 30:
                            assert c.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
                            assert c.execute("SELECT body FROM messages WHERE id=29").fetchone()[0] == "A durable conversation 29"
                            restored = True
                            break
                index += 1
                time.sleep(0.2)
            assert restored, "Replica never restored all committed messages"
        finally:
            process.terminate()
            process.wait(timeout=15)
            connection.close()
