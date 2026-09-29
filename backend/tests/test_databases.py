"""`hub db`: read-only company-database access, its grants, audit and private catalogs.

Enforcement is tested against a real SQLite file, and against a throwaway PostgreSQL container
when Docker can run one (skipped otherwise). The statement scanner and binder are tested for
MySQL's dialect without a server."""

import json
import shutil
import sqlite3
import subprocess
import time
import types
import uuid
from pathlib import Path

import pytest
import yaml

from backend import integrations as I
from backend.config import ROOT, Settings
from backend.tests.test_api import api, headers, post, setup_attempt  # noqa: F401
from clients import dbquery as D
from clients.tico import APIError


# ----------------------------------------------------------------------------- helpers
def make_sqlite(tmp_path, rows=50):
    path = tmp_path / "acme.db"
    path.unlink(missing_ok=True)
    db = sqlite3.connect(path)
    db.execute("CREATE TABLE orders (id INTEGER PRIMARY KEY, status TEXT, total_cents INTEGER)")
    db.executemany("INSERT INTO orders (status, total_cents) VALUES (?, ?)",
                   [("paid" if i % 2 else "pending", 100 * i) for i in range(rows)])
    db.commit()
    db.close()
    return path


def sqlite_db(tmp_path, **kw):
    return D.Database("acme", "sqlite", f"sqlite:///{make_sqlite(tmp_path)}", **kw)


class FakeHub:
    """The two hub calls `hub db` makes: who am I, and record this query."""

    def __init__(self, actor="bot:ops", catalog=None, fail_audit=False):
        self.actor, self.catalog, self.fail_audit, self.audits = actor, catalog or {}, fail_audit, []

    def get(self, path, **query):
        if path == "me":
            return {"actor": self.actor}
        name = path.split("/")[1]
        query_id = query.get("id")
        if (name, query_id) not in self.catalog:
            raise APIError("not_found", "No query", 404)
        return self.catalog[(name, query_id)]

    def post(self, path, body, key=None):
        assert path == "databases/audit"
        if self.fail_audit:
            raise APIError("unavailable", "hub down", 503, retryable=True)
        self.audits.append(body)
        return {"ok": True}


def args(target, sql=None, **kw):
    base = dict(target=target, sql=sql, query_id=None, param=[], json=False, csv=False, max_rows=None, timeout=None)
    return types.SimpleNamespace(**{**base, **kw})


def workspace(tmp_path, slug="ops", entries=None):
    """A workspace with emp-<slug>/employee.yaml declaring `entries` under access."""
    repo = tmp_path / "ws" / f"emp-{slug}"
    repo.mkdir(parents=True, exist_ok=True)
    (repo / "employee.yaml").write_text(yaml.safe_dump({"name": slug, "access": entries or []}))
    return {"HUB_WORKSPACE": str(tmp_path / "ws")}


GRANT = {"service": "sqlite", "database": "acme", "can": ["read"], "identity": "file"}


# ----------------------------------------------------------------------------- SQLite: real enforcement
@pytest.mark.parametrize("sql", [
    "INSERT INTO orders (status) VALUES ('x')", "UPDATE orders SET status = 'x'", "DELETE FROM orders",
    "DROP TABLE orders", "CREATE TABLE t (x)", "PRAGMA writable_schema = 1", "ATTACH DATABASE ':memory:' AS m",
    "SELECT 1; DELETE FROM orders", "SELECT * INTO copy FROM orders", "", "-- nothing\n",
])
def test_writes_and_extra_statements_are_refused_and_the_file_is_untouched(tmp_path, sql):
    db = sqlite_db(tmp_path)
    with pytest.raises(D.Refusal):
        D.execute(db, sql)
    check = sqlite3.connect(D.sqlite_path(db.url))
    assert check.execute("SELECT count(*), sum(status = 'x') FROM orders").fetchone() == (50, 0)


def test_the_session_itself_refuses_a_write_the_scanner_missed(tmp_path):
    db = sqlite_db(tmp_path)
    conn = D.sqlite_connect(db, 5)
    for statement in ("INSERT INTO orders (status) VALUES ('x')", "CREATE TABLE t (x)", "PRAGMA query_only = OFF"):
        with pytest.raises(sqlite3.Error):
            conn.execute(statement)
    # A write hidden in a CTE reaches the driver, and the read-only session still stops it.
    with pytest.raises(sqlite3.Error):
        D.RUNNERS["sqlite"](db, "WITH x AS (SELECT 1) DELETE FROM orders", [], 10, 5)


def test_a_writable_looking_cte_is_stopped_end_to_end(tmp_path):
    db = sqlite_db(tmp_path)
    with pytest.raises(D.Refusal) as caught:
        D.execute(db, "WITH x AS (SELECT 1) DELETE FROM orders")
    assert caught.value.code == "read_only"


def test_reads_return_the_hub_sql_result_shape(tmp_path):
    result = D.execute(sqlite_db(tmp_path), "SELECT status, count(*) AS n FROM orders GROUP BY 1 ORDER BY 1;")
    assert result["columns"] == ["status", "n"]
    assert result["rows"] == [["paid", 25], ["pending", 25]]
    assert result["row_count"] == 2 and result["truncated"] is False and isinstance(result["ms"], int)


def test_the_row_cap_truncates_and_a_request_can_only_lower_it(tmp_path):
    db = sqlite_db(tmp_path, max_rows=30)
    assert D.execute(db, "SELECT id FROM orders")["row_count"] == 30
    assert D.execute(db, "SELECT id FROM orders")["truncated"] is True
    assert D.execute(db, "SELECT id FROM orders", max_rows=5)["row_count"] == 5
    assert D.execute(db, "SELECT id FROM orders", max_rows=5000)["row_count"] == 30
    assert D.execute(db, "SELECT id FROM orders WHERE id <= 10")["truncated"] is False
    assert D.execute(sqlite_db(tmp_path, max_rows=10**9), "SELECT id FROM orders")["row_count"] == 50


def test_a_runaway_statement_is_stopped_by_the_timeout(tmp_path):
    db = sqlite_db(tmp_path, timeout=1)
    started = time.monotonic()
    with pytest.raises(D.Refusal) as caught:
        D.execute(db, "WITH RECURSIVE r(n) AS (SELECT 1 UNION ALL SELECT n + 1 FROM r) SELECT count(*) FROM r")
    assert caught.value.code == "timeout" and time.monotonic() - started < 10


def test_parameters_bind_by_name_and_by_position(tmp_path):
    db = sqlite_db(tmp_path)
    assert D.execute(db, "SELECT count(*) FROM orders WHERE status = :s AND id > :n", {"s": "paid", "n": 40})["rows"] == [[5]]
    assert D.execute(db, "SELECT count(*) FROM orders WHERE id > $2 AND status = $1", {"a": "paid", "b": 40}, order=["a", "b"])["rows"] == [[5]]
    with pytest.raises(D.Refusal) as caught:
        D.execute(db, "SELECT :missing")
    assert caught.value.code == "params"


def test_a_missing_file_is_an_error_that_does_not_leak_more_than_the_path(tmp_path):
    db = D.Database("gone", "sqlite", f"sqlite:///{tmp_path}/nope.db")
    with pytest.raises(D.Refusal) as caught:
        D.execute(db, "SELECT 1")
    assert caught.value.code == "db_error"


# ----------------------------------------------------------------------------- scanner and binder
@pytest.mark.parametrize("kind,sql,ok", [
    ("postgres", "SELECT 'a;b', \"c;d\", $$e;f$$ FROM t;", True),
    ("postgres", "SELECT E'it\\'s; fine' FROM t", True),
    ("postgres", "SELECT 'it\\'; DROP TABLE t; --'", False),          # standard string: the backslash is literal
    ("postgres", "SELECT 1 /* a /* nested */ ; */", True),
    ("postgres", "SELECT 1; SELECT 2", False),
    ("postgres", "select 1 -- trailing; comment", True),
    ("postgres", "COPY t TO '/tmp/x'", False),
    ("postgres", "WITH a AS (SELECT 1) SELECT * FROM a", True),
    ("postgres", "SHOW transaction_read_only", True),
    ("postgres", "EXPLAIN SELECT 1", True),
    ("postgres", "SELECT * INTO backup FROM t", False),
    ("mysql", "SELECT 'it\\'s; fine' FROM t", True),
    ("mysql", "SELECT 'x\\'; DROP TABLE t; #'", True),                # inside the string for MySQL
    ("mysql", "SELECT 1 # comment; more", True),
    ("mysql", "SELECT 1; DROP TABLE t", False),
    ("mysql", "SELECT 1 /*! ; DROP TABLE t */", False),
    ("mysql", "SELECT `a;b` FROM t", True),
    ("mysql", "SELECT 1 INTO OUTFILE '/tmp/x'", False),
    ("mysql", "CALL do_things()", False),
    ("mysql", "DESCRIBE orders", True),
    ("sqlite", "REPLACE INTO t VALUES (1)", False),
])
def test_statement_shape_rules_per_dialect(kind, sql, ok):
    if ok:
        assert D.check_statement(sql, kind)
    else:
        with pytest.raises(D.Refusal):
            D.check_statement(sql, kind)


def test_binding_translates_placeholders_and_leaves_casts_strings_and_percent_alone():
    sql, args_ = D.bind("SELECT a::int, ':not', '50%' FROM t WHERE x = :x AND y LIKE 'a%' AND z = $2 AND w = :x",
                        "postgres", {"x": 1, "second": 2}, ["first", "second"])
    assert sql == "SELECT a::int, ':not', '50%%' FROM t WHERE x = %s AND y LIKE 'a%%' AND z = %s AND w = %s"
    assert args_ == [1, 2, 1]
    assert D.bind("SELECT '50%' FROM t", "postgres", {}) == ("SELECT '50%' FROM t", [])       # no args, no escaping
    assert D.bind("SELECT :x", "sqlite", {"x": 3}) == ("SELECT ?", [3])
    with pytest.raises(D.Refusal):
        D.bind("SELECT $3", "postgres", {"a": 1}, ["a"])


def test_param_coercion_follows_the_catalog_type():
    assert D.coerce("2026-09-01", "date").isoformat() == "2026-09-01"
    assert D.coerce("7", "int") == 7 and D.coerce("true", "bool") is True
    assert D.coerce("acme", "text") == "acme"
    with pytest.raises(D.Refusal):
        D.coerce("soon", "date")


# ----------------------------------------------------------------------------- redaction
def test_credentials_never_appear_in_errors_or_the_audit_statement():
    url = "postgresql://readonly:s3cr%40t-pw@db.internal:5432/app?sslmode=require"
    db = D.Database("w", "postgres", url)
    assert D.redact(f"could not connect using {url}: password s3cr@t-pw / s3cr%40t-pw rejected", url) == \
        "could not connect using ***: password *** / *** rejected"
    assert "hunter22" not in D.redact("dsn mysql://root:hunter22@host/db failed")
    assert "hunter22" not in db.redact("postgres://x:hunter22@h/d")
    hub = FakeHub()
    D.audit(hub, db, "SELECT 'postgresql://u:hunter22@h/d'", None, error="db_error")
    assert "hunter22" not in json.dumps(hub.audits)


def test_a_driver_error_is_redacted_before_it_reaches_the_caller(tmp_path, monkeypatch):
    secret = "p4ssw0rd-xyz"
    db = D.Database("w", "postgres", f"postgresql://u:{secret}@127.0.0.1:1/x")

    def boom(*a, **k):
        raise RuntimeError(f"connection to postgresql://u:{secret}@127.0.0.1:1/x failed")
    monkeypatch.setitem(D.RUNNERS, "postgres", boom)
    with pytest.raises(D.Refusal) as caught:
        D.execute(db, "SELECT 1")
    assert secret not in caught.value.detail and "***" in caught.value.detail


# ----------------------------------------------------------------------------- per-bot grants
def test_a_bot_needs_a_declared_entry_and_the_credential(tmp_path):
    url = f"sqlite:///{make_sqlite(tmp_path)}"
    env = {**workspace(tmp_path, "ops", [GRANT]), "DB_ACME_URL": url}
    assert D.open_database("acme", "bot:ops", env).kind == "sqlite"
    with pytest.raises(D.Refusal) as caught:                    # another bot has no entry, though the env carries the URL
        D.open_database("acme", "bot:cpo", {**workspace(tmp_path, "cpo", []), "DB_ACME_URL": url})
    assert caught.value.code == "grant" and "does not declare" in caught.value.detail
    with pytest.raises(D.Refusal) as caught:
        D.open_database("other", "bot:ops", env)
    assert caught.value.code == "grant"
    with pytest.raises(D.Refusal) as caught:                    # declared, but no credential on this computer
        D.open_database("acme", "bot:ops", workspace(tmp_path, "ops", [GRANT]))
    assert caught.value.code == "credential"
    read_less = workspace(tmp_path / "x", "ops", [{**GRANT, "can": ["use"]}])
    with pytest.raises(D.Refusal) as caught:
        D.open_database("acme", "bot:ops", {**read_less, "DB_ACME_URL": url})
    assert caught.value.code == "grant"


def test_an_entry_names_its_own_env_var_and_can_lower_the_limits(tmp_path):
    url = f"sqlite:///{make_sqlite(tmp_path)}"
    entry = {**GRANT, "env": "REPORTING_DB", "max_rows": 7, "timeout_seconds": 3}
    db = D.open_database("acme", "bot:ops", {**workspace(tmp_path, "ops", [entry]), "REPORTING_DB": url})
    assert (db.max_rows, db.timeout) == (7, 3)
    raised = workspace(tmp_path / "y", "ops", [{**GRANT, "max_rows": 10**9, "timeout_seconds": 10**6}])
    db = D.open_database("acme", "bot:ops", {**raised, "DB_ACME_URL": url})
    assert (db.max_rows, db.timeout) == (D.MAX_ROWS_CEILING, D.TIMEOUT_CEILING)


def test_list_shows_only_the_bots_declared_databases(tmp_path):
    env = {**workspace(tmp_path, "ops", [GRANT, {"service": "mysql", "database": "billing", "can": ["read"]}]),
           "DB_ACME_URL": "sqlite:///x.db"}
    rows = {r["database"]: r for r in D.listing("bot:ops", env)}
    assert set(rows) == {"acme", "billing"} and rows["acme"]["credential"] and not rows["billing"]["credential"]


def test_the_command_refuses_an_undeclared_database_and_reserved_names(tmp_path):
    hub = FakeHub()
    env = workspace(tmp_path, "ops", [])
    with pytest.raises(APIError) as caught:
        D.run(hub, args("acme", "SELECT 1"), env)
    assert caught.value.code == "grant" and not hub.audits
    with pytest.raises(D.Refusal):
        D.open_database("doctor", "human:ana", {"DB_DOCTOR_URL": "sqlite:///x"})


# ----------------------------------------------------------------------------- the command and its audit
def command_env(tmp_path, **extra):
    return {**workspace(tmp_path, "ops", [GRANT]), "DB_ACME_URL": f"sqlite:///{make_sqlite(tmp_path)}", **extra}


def test_a_query_is_audited_with_the_statement_and_row_count_but_no_data(tmp_path):
    hub = FakeHub()
    result = D.run(hub, args("acme", "SELECT id, status FROM orders WHERE status = :s LIMIT 3", param=["s=paid"]),
                   command_env(tmp_path))
    assert result["row_count"] == 3
    (event,) = hub.audits
    assert set(event) == {"database", "kind", "statement", "rows", "truncated", "ms", "query", "params", "error"}
    assert event["database"] == "acme" and event["kind"] == "sqlite" and event["rows"] == 3
    assert event["statement"].startswith("SELECT id, status") and event["params"] == ["s"]
    assert "paid" not in json.dumps({k: v for k, v in event.items() if k != "statement"})
    assert event["error"] is None and event["query"] is None


def test_a_refused_statement_is_audited_with_its_error_code(tmp_path):
    hub = FakeHub()
    with pytest.raises(APIError) as caught:
        D.run(hub, args("acme", "DELETE FROM orders"), command_env(tmp_path))
    assert caught.value.code == "read_only"
    assert hub.audits[0]["error"] == "read_only" and hub.audits[0]["rows"] == 0


def test_when_the_hub_cannot_record_the_query_the_rows_are_withheld(tmp_path):
    with pytest.raises(APIError) as caught:
        D.run(FakeHub(fail_audit=True), args("acme", "SELECT id FROM orders"), command_env(tmp_path))
    assert caught.value.code == "audit" and "withheld" in caught.value.detail


def test_a_named_query_comes_from_the_catalog_with_defaults_and_types(tmp_path):
    query = {"id": "paid-since", "title": "t", "description": "", "category": "", "tags": [], "database": "acme",
             "sql": "SELECT count(*) AS n FROM orders WHERE status = 'paid' AND id > $1 AND total_cents >= :floor\n",
             "params": [{"name": "min_id", "type": "int", "required": True},
                        {"name": "floor", "type": "int", "default": "0"}]}
    hub = FakeHub(catalog={("acme", "paid-since"): query})
    result = D.run(hub, args("acme", query_id="paid-since", param=["min_id=40"]), command_env(tmp_path))
    assert result["rows"] == [[5]] and hub.audits[0]["query"] == "paid-since"
    with pytest.raises(APIError) as caught:
        D.run(hub, args("acme", query_id="paid-since"), command_env(tmp_path))
    assert caught.value.code == "params"
    with pytest.raises(APIError) as caught:
        D.run(hub, args("acme", query_id="nope"), command_env(tmp_path))
    assert caught.value.code == "catalog"


def test_a_catalog_query_is_held_to_the_same_read_only_rules(tmp_path):
    query = {"id": "bad", "sql": "DELETE FROM orders", "params": []}
    with pytest.raises(APIError) as caught:
        D.run(FakeHub(catalog={("acme", "bad"): query}), args("acme", query_id="bad"), command_env(tmp_path))
    assert caught.value.code == "read_only"


def test_a_person_needs_only_their_own_credential(tmp_path):
    env = {"DB_ACME_URL": f"sqlite:///{make_sqlite(tmp_path)}"}
    result = D.run(FakeHub("human:ana"), args("acme", "SELECT count(*) FROM orders"), env)
    assert result["rows"] == [[50]]


def test_doctor_reports_read_only_and_names_a_missing_credential(tmp_path):
    report = D.doctor("bot:ops", ["acme"], command_env(tmp_path))
    assert report["ok"] and any(c["check"] == "session is read-only" and c["level"] == "ok"
                                for c in report["databases"][0]["checks"])
    report = D.doctor("bot:ops", ["acme"], workspace(tmp_path / "z", "ops", [GRANT]))
    assert not report["ok"] and report["databases"][0]["checks"][0]["check"] == "credential"


def test_output_renders_as_table_csv_and_json(tmp_path):
    result = D.run(FakeHub(), args("acme", "SELECT id, status FROM orders WHERE id <= 2 ORDER BY id"), command_env(tmp_path))
    assert D.render(result, args("acme")).splitlines()[-1].startswith("2 rows (")
    assert D.render(result, args("acme", csv=True)).splitlines() == ["id,status", "1,pending", "2,paid"]


def test_the_cli_declares_db_and_keeps_it_off_the_servers_tool_table():
    from clients import hubcli, hubtools
    parsed = hubcli.parser().parse_args(["db", "warehouse", "SELECT 1", "--param", "a=b", "--max-rows", "5", "--csv"])
    assert (parsed.target, parsed.sql, parsed.param, parsed.max_rows, parsed.csv) == ("warehouse", "SELECT 1", ["a=b"], 5, True)
    assert "hub_db" in hubtools.SHELL_ONLY and "hub_db" not in hubtools.BY_NAME


# ----------------------------------------------------------------------------- the hub: audit event and private catalogs
def test_the_hub_stores_the_audit_as_an_event_for_a_bot_and_refuses_a_bad_shape(api):
    _, _, attempt = setup_attempt(api)
    body = {"database": "acme", "kind": "postgres", "statement": "SELECT 1", "rows": 1, "truncated": False, "ms": 4,
            "query": None, "params": ["since"], "error": None}
    post(api, "databases/audit", body, token=attempt["token"])
    with api.app.state.store.read() as c:
        row = c.execute("SELECT actor, target, detail_json FROM events WHERE action = 'db.query'").fetchone()
    assert (row["actor"], row["target"]) == ("bot:ops", "acme")
    detail = json.loads(row["detail_json"])
    assert detail["rows"] == 1 and detail["statement"] == "SELECT 1" and detail["params"] == ["since"]
    assert set(detail) == {"kind", "statement", "rows", "truncated", "ms", "query", "params", "error", "operation", "collection"}
    post(api, "databases/audit", {**body, "database": "Bad Name"}, token=attempt["token"], expected=422)
    post(api, "databases/audit", {**body, "rows": "many"}, token=attempt["token"], expected=422)
    post(api, "databases/audit", {**body, "extra": 1}, token=attempt["token"], expected=422)


def company_config(root, service="warehouse"):
    (root / "queries").mkdir(parents=True)
    template = ROOT / "templates" / "company-config" / "integrations"
    for path in template.rglob("*"):
        if path.is_file():
            target = root / path.relative_to(template)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy(path, target)
    return root


def test_the_example_company_config_is_valid_and_loads_over_the_release(tmp_path):
    config = company_config(tmp_path / "integrations")
    pages, aliases = I.load(ROOT / "integrations", config)
    assert {"postgres", "mysql", "sqlite", "hub-sql"} <= set(pages) and "warehouse" in pages
    ids = {q["id"] for q in pages["warehouse"]["queries"]}
    assert {"revenue-by-month", "orders-by-status", "top-products"} <= ids
    assert aliases["acme-db"] == "warehouse"
    # Upstream alone never carries a company's database.
    assert "warehouse" not in I.load(ROOT / "integrations")[0]
    for query in pages["warehouse"]["queries"]:
        D.check_statement(query["sql"], "postgres")
        D.bind(query["sql"], "postgres", {p["name"]: 1 for p in query["params"]}, [p["name"] for p in query["params"]])


def test_a_company_page_replaces_a_release_page_and_a_catalog_replaces_queries(tmp_path):
    config = tmp_path / "company"
    (config / "queries").mkdir(parents=True)
    page = (ROOT / "integrations" / "hub-sql.md").read_text().replace("title: Hub database (SQL)", "title: Our override")
    (config / "hub-sql.md").write_text(page)
    pages, _ = I.load(ROOT / "integrations", config)
    upstream, _ = I.load(ROOT / "integrations")
    assert pages["hub-sql"]["title"] == "Our override"
    assert pages["hub-sql"]["queries"] == upstream["hub-sql"]["queries"]           # no catalog of its own: keeps the release's
    (config / "queries" / "hub-sql.yaml").write_text(yaml.safe_dump({"queries": [
        {"id": "mine", "title": "Mine", "description": "", "category": "", "tags": [], "database": "hub.sqlite",
         "sql": "SELECT 1", "params": []}]}))
    assert [q["id"] for q in I.load(ROOT / "integrations", config)[0]["hub-sql"]["queries"]] == ["mine"]


def test_a_catalog_without_a_page_and_a_missing_company_directory(tmp_path):
    config = tmp_path / "company"
    (config / "queries").mkdir(parents=True)
    (config / "queries" / "ghost.yaml").write_text(yaml.safe_dump({"queries": []}))
    with pytest.raises(ValueError, match="no page named ghost"):
        I.load(ROOT / "integrations", config)
    assert I.load(ROOT / "integrations", tmp_path / "absent")[0] == I.load(ROOT / "integrations")[0]


def test_the_server_serves_the_private_catalog_from_the_registry_directory(api):
    # The catalog is read on first use, so the company's directory can be filled after start.
    (directory,) = api.app.state.integrations.company
    assert directory == api.app.state.store.settings.registry_dir / "integrations"
    company_config(directory)
    one = api.get("/api/v2/integrations/acme-db/queries", params={"id": "orders-by-status"}, headers=headers())
    assert one.status_code == 200 and one.json()["params"][0]["name"] == "since"
    found = api.get("/api/v2/integrations/warehouse/queries", params={"term": "revenue"}, headers=headers()).json()
    assert [q["id"] for q in found["queries"]] == ["revenue-by-month"]
    assert api.get("/api/v2/integrations/postgres", headers=headers()).status_code == 200


def test_the_explicit_integrations_directory_wins_over_the_registry_default(tmp_path):
    other = company_config(tmp_path / "elsewhere")
    settings = Settings(db_path=tmp_path / "hub.db", registry_dir=tmp_path / "registry", company_integrations_dir=other)
    assert settings.company_integrations_dir == other


# ----------------------------------------------------------------------------- PostgreSQL, when Docker can run one
@pytest.fixture(scope="module")
def postgres():
    docker = shutil.which("docker")
    if not docker:
        pytest.skip("docker is not installed")
    try:
        psycopg = pytest.importorskip("psycopg")
        name = "tico-db-test-" + uuid.uuid4().hex[:8]
        started = subprocess.run([docker, "run", "-d", "--rm", "--name", name, "-e", "POSTGRES_PASSWORD=admin-pw",
                                  "-p", "127.0.0.1::5432", "postgres:16-alpine"], capture_output=True, text=True, timeout=120)
        if started.returncode:
            pytest.skip("cannot start a postgres container: " + started.stderr.strip()[:120])
    except subprocess.TimeoutExpired:
        pytest.skip("docker did not answer")
    try:
        port = subprocess.run([docker, "port", name, "5432/tcp"], capture_output=True, text=True).stdout.split(":")[-1].strip()
        admin = f"postgresql://postgres:admin-pw@127.0.0.1:{port}/postgres"
        for _ in range(60):
            try:
                conn = psycopg.connect(admin, autocommit=True, connect_timeout=2)
                break
            except psycopg.OperationalError:
                time.sleep(1)
        else:
            pytest.skip("postgres did not come up")
        conn.execute("CREATE TABLE orders (id serial PRIMARY KEY, status text, total_cents int)")
        conn.execute("INSERT INTO orders (status, total_cents) SELECT CASE WHEN g % 2 = 0 THEN 'paid' ELSE 'pending' END, g * 100 "
                     "FROM generate_series(1, 1000) g")
        conn.execute("CREATE ROLE tico_readonly LOGIN PASSWORD 'ro-secret-pw'")
        conn.execute("GRANT SELECT ON ALL TABLES IN SCHEMA public TO tico_readonly")
        conn.execute("CREATE ROLE tico_writer LOGIN PASSWORD 'rw-secret-pw'")
        conn.execute("GRANT ALL ON ALL TABLES IN SCHEMA public TO tico_writer")
        conn.execute("GRANT USAGE ON ALL SEQUENCES IN SCHEMA public TO tico_writer")
        conn.close()
        yield {"readonly": f"postgresql://tico_readonly:ro-secret-pw@127.0.0.1:{port}/postgres",
               "writer": f"postgresql://tico_writer:rw-secret-pw@127.0.0.1:{port}/postgres"}
    finally:
        subprocess.run([docker, "rm", "-f", name], capture_output=True)


def test_postgres_reads_and_caps_rows(postgres):
    db = D.Database("w", "postgres", postgres["readonly"], max_rows=100)
    result = D.execute(db, "SELECT id, status FROM orders ORDER BY id")
    assert result["row_count"] == 100 and result["truncated"] and result["columns"] == ["id", "status"]
    assert D.execute(db, "SELECT count(*) FROM orders WHERE status = :s", {"s": "paid"})["rows"] == [[500]]
    assert D.execute(db, "SELECT count(*) FROM orders WHERE id > $1", {"n": 990}, order=["n"])["rows"] == [[10]]
    assert D.execute(db, "SHOW transaction_read_only")["rows"] == [["on"]]


def test_postgres_session_is_read_only_even_for_a_role_that_can_write(postgres):
    db = D.Database("w", "postgres", postgres["writer"])
    with pytest.raises(D.Refusal) as caught:
        D.execute(db, "DELETE FROM orders")
    assert caught.value.code == "read_only"
    # A write the scanner cannot see: hidden in a CTE, so only the read-only transaction stops it.
    with pytest.raises(D.Refusal) as caught:
        D.execute(db, "WITH gone AS (DELETE FROM orders RETURNING id) SELECT count(*) FROM gone")
    assert caught.value.code == "read_only"
    assert D.execute(db, "SELECT count(*) FROM orders")["rows"] == [[1000]]
    report = D.probe(db)
    assert {"level": "warn", "check": "role privileges"}.items() <= next(c for c in report if c["check"] == "role privileges").items()
    assert any(c["check"] == "session is read-only" and c["level"] == "ok" for c in report)


def test_postgres_readonly_role_passes_the_doctor_clean(postgres):
    report = D.probe(D.Database("w", "postgres", postgres["readonly"]))
    assert all(c["level"] == "ok" for c in report), report


def test_postgres_timeout_cancels_the_statement(postgres):
    db = D.Database("w", "postgres", postgres["readonly"], timeout=1)
    started = time.monotonic()
    with pytest.raises(D.Refusal) as caught:
        D.execute(db, "SELECT pg_sleep(30)")
    assert caught.value.code == "timeout" and time.monotonic() - started < 10


def test_postgres_errors_do_not_leak_the_password(postgres):
    wrong = postgres["readonly"].replace("ro-secret-pw", "bad-pw-123")
    with pytest.raises(D.Refusal) as caught:
        D.execute(D.Database("w", "postgres", wrong), "SELECT 1")
    assert "bad-pw-123" not in caught.value.detail and "ro-secret-pw" not in caught.value.detail


# ----------------------------------------------------------------------------- MySQL, when Docker can run one
@pytest.fixture(scope="module")
def mysql():
    docker = shutil.which("docker")
    if not docker:
        pytest.skip("docker is not installed")
    pymysql = pytest.importorskip("pymysql")
    name = "tico-db-test-" + uuid.uuid4().hex[:8]
    try:
        started = subprocess.run([docker, "run", "-d", "--rm", "--name", name, "-e", "MYSQL_ROOT_PASSWORD=admin-pw",
                                  "-p", "127.0.0.1::3306", "mysql:8.4"], capture_output=True, text=True, timeout=120)
    except subprocess.TimeoutExpired:
        pytest.skip("docker did not answer")
    if started.returncode:
        pytest.skip("cannot start a mysql container: " + started.stderr.strip()[:120])
    try:
        port = int(subprocess.run([docker, "port", name, "3306/tcp"], capture_output=True, text=True).stdout.split(":")[-1])
        for _ in range(90):
            try:
                conn = pymysql.connect(host="127.0.0.1", port=port, user="root", password="admin-pw", connect_timeout=2, autocommit=True)
                conn.cursor().execute("SELECT 1")
                break
            except pymysql.err.OperationalError:
                time.sleep(1)
        else:
            pytest.skip("mysql did not come up")
        cur = conn.cursor()
        for statement in ("CREATE DATABASE app", "CREATE TABLE app.orders (id INT AUTO_INCREMENT PRIMARY KEY, status VARCHAR(20), total_cents INT)",
                          "INSERT INTO app.orders (status, total_cents) WITH RECURSIVE n(g) AS (SELECT 1 UNION ALL SELECT g + 1 FROM n WHERE g < 300) "
                          "SELECT IF(g % 2 = 0, 'paid', 'pending'), g * 100 FROM n",
                          "CREATE USER 'ro'@'%' IDENTIFIED BY 'ro-secret-pw'", "GRANT SELECT ON app.* TO 'ro'@'%'",
                          "CREATE USER 'rw'@'%' IDENTIFIED BY 'rw-secret-pw'", "GRANT ALL ON app.* TO 'rw'@'%'"):
            cur.execute(statement)
        conn.close()
        yield {"readonly": f"mysql://ro:ro-secret-pw@127.0.0.1:{port}/app", "writer": f"mysql://rw:rw-secret-pw@127.0.0.1:{port}/app"}
    finally:
        subprocess.run([docker, "rm", "-f", name], capture_output=True)


def test_mysql_reads_binds_and_caps_rows(mysql):
    db = D.Database("w", "mysql", mysql["readonly"], max_rows=50)
    result = D.execute(db, "SELECT id, status FROM orders ORDER BY id")
    assert result["row_count"] == 50 and result["truncated"]
    assert D.execute(db, "SELECT count(*) FROM orders WHERE status = :s", {"s": "paid"})["rows"] == [[150]]
    assert D.execute(db, "SELECT '50%' AS p, count(*) FROM orders WHERE id > $1", {"n": 290}, order=["n"])["rows"] == [["50%", 10]]


def test_mysql_session_is_read_only_even_for_an_account_that_can_write(mysql):
    db = D.Database("w", "mysql", mysql["writer"])
    with pytest.raises(D.Refusal):
        D.execute(db, "DELETE FROM orders")
    assert D.execute(db, "SELECT count(*) FROM orders")["rows"] == [[300]]
    report = D.probe(db)
    assert next(c for c in report if c["check"] == "role privileges")["level"] == "warn"
    assert next(c for c in report if c["check"] == "session is read-only")["level"] == "ok"
    clean = D.probe(D.Database("w", "mysql", mysql["readonly"]))
    assert all(c["level"] == "ok" for c in clean), clean


def test_mysql_timeout_and_redaction(mysql):
    started = time.monotonic()
    with pytest.raises(D.Refusal) as caught:
        D.execute(D.Database("w", "mysql", mysql["readonly"], timeout=1), 
                  "SELECT sum(length(sha2(concat(a.id, b.id, c.id), 256))) FROM orders a, orders b, orders c")
    assert caught.value.code == "timeout" and time.monotonic() - started < 15
    wrong = mysql["readonly"].replace("ro-secret-pw", "bad-pw-123")
    with pytest.raises(D.Refusal) as caught:
        D.execute(D.Database("w", "mysql", wrong), "SELECT 1")
    assert "bad-pw-123" not in caught.value.detail
