"""Pooled reads (backend/store.py Store.read): reused, rolled back, and never carrying a caller's state."""
import os
import shutil

from backend.config import Settings
from backend.store import Store


def store(tmp_path):
    s = Store(Settings(db_path=tmp_path / "hub.sqlite"))
    with s.transaction() as c:
        c.execute("CREATE TABLE IF NOT EXISTS t(x)")
        c.execute("INSERT INTO t VALUES(1)")
    return s


def test_reads_reuse_a_connection_left_clean(tmp_path):
    s = store(tmp_path)
    with s.read() as first:
        first.execute("BEGIN")
        first.execute("SELECT * FROM t").fetchall()
    with s.read() as second:
        assert second is first and not second.in_transaction
        assert second.execute("SELECT x FROM t").fetchone()["x"] == 1


def test_a_connection_a_caller_changed_is_not_reused(tmp_path):
    s = store(tmp_path)
    with s.read() as first:
        first.create_function("who", 0, lambda: "ana")
    with s.read() as second:
        assert second is not first
        assert second.execute("SELECT count(*) FROM pragma_function_list WHERE name='who'").fetchone()[0] == 0


def test_a_replaced_database_file_drops_the_pool(tmp_path):
    s = store(tmp_path)
    with s.read() as first:
        pass
    copy = tmp_path / "copy.sqlite"
    shutil.copy(s.settings.db_path, copy)
    os.replace(copy, s.settings.db_path)
    with s.read() as second:
        assert second is not first

