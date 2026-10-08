"""Pooled reads (backend/store.py Store.read): reused, rolled back, and never carrying a caller's state."""
import os
import sqlite3

from backend.config import Settings
from backend.store import Store
from backend import read_cache
from backend.sql import schema_columns


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
        assert read_cache.rows(first, "SELECT x FROM t")[0][0] == 1
        enriched = read_cache.value(first, ("synthetic",), lambda: {"allowed": ["ana"]})
        enriched["allowed"].append("ben")
        assert read_cache.value(first, ("synthetic",), lambda: {}) == {"allowed": ["ana"]}
        first.execute("UPDATE t SET x=2")
        assert read_cache.rows(first, "SELECT x FROM t")[0][0] == 2
        first.rollback()
        first.execute("BEGIN")
        assert read_cache.rows(first, "SELECT x FROM t")[0][0] == 1
        first.commit()
        with s.transaction() as writer:
            writer.execute("UPDATE t SET x=3")
        first.execute("BEGIN")
        assert read_cache.rows(first, "SELECT x FROM t")[0][0] == 3
    with s.read() as second:
        assert second is first and not second.in_transaction
        assert second.execute("SELECT x FROM t").fetchone()["x"] == 3
        assert second.read_cache == {}


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
        assert schema_columns(first, s.settings.db_path).get("t") == ("x",)
    copy = tmp_path / "copy.sqlite"
    with sqlite3.connect(copy) as replacement:
        replacement.execute("CREATE TABLE t(y)")   # same schema version, different file/columns
    os.replace(copy, s.settings.db_path)
    with s.read() as second:
        assert second is not first
        assert schema_columns(second, s.settings.db_path).get("t") == ("y",)

