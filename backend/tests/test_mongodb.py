"""`hub db` on MongoDB (Atlas first): the read-only rules, the audit shape, catalogs and the doctor.

The rules and the mongodb+srv parsing are tested without a server. Enforcement is tested against a
throwaway MongoDB container when Docker can run one (skipped otherwise), with a `read` user, a
`readWrite` user (to show the tool refuses writes even when the user could make them) and a user
whose role reaches beyond one database."""

import datetime
import json
import shutil
import subprocess
import time
import types
import uuid

import pytest
import yaml

from backend import integrations as I
from backend.config import ROOT
from backend.tests.test_api import api, headers, post, setup_attempt  # noqa: F401
from backend.tests.test_databases import FakeHub, workspace
from clients import dbmongo as M
from clients import dbquery as D
from clients.tico import APIError

SRV = "mongodb+srv://tico_ro:p%40ss-w0rd-secret@cluster0.ab1cd.mongodb.net/app?retryWrites=true&w=majority"
GRANT = {"service": "mongodb", "database": "atlas", "can": ["read"], "identity": "Atlas read user"}


def margs(target, verb=None, *rest, **kw):
    base = dict(target=target, sql=verb, extra=list(rest), query_id=None, param=[], json=False, csv=False, max_rows=None,
                timeout=None, projection=None, sort=None, limit=None)
    return types.SimpleNamespace(**{**base, **kw})


def env(tmp_path, url, entry=None):
    return {**workspace(tmp_path, "ops", [{**GRANT, **(entry or {})}]), "DB_ATLAS_URL": url}


# ----------------------------------------------------------------------------- no server: mongodb+srv parsing
def test_an_atlas_srv_string_is_parsed_without_the_network():
    target = M.parse_target(SRV)
    assert (target.srv, target.hosts, target.database, target.atlas, target.local) == (True, "cluster0.ab1cd.mongodb.net", "app", True, False)
    assert target.options == {"retrywrites": "true", "w": "majority"}
    assert D.kind_of(SRV) == "mongodb" and D.kind_of("mongodb://u:p@h1:27017,h2:27017/app") == "mongodb"
    db = D.Database("atlas", "mongodb", SRV)
    options = M.client_options(db, 20)
    # Atlas users live in `admin`, and a database in the path would otherwise become the auth database.
    assert options["authSource"] == "admin" and options["readPreference"] == "secondaryPreferred"
    assert options["retryWrites"] is False and options["socketTimeoutMS"] == 25_000
    explicit = D.Database("atlas", "mongodb", SRV.replace("?", "?authSource=app&"))
    assert "authSource" not in M.client_options(explicit, 20)


def test_a_connection_string_that_cannot_work_is_refused_with_the_fix():
    for url, word in (("mongodb+srv://u:p@cluster0.ab1cd.mongodb.net/", "database in its path"),
                      ("mongodb+srv://u:p@cluster0.ab1cd.mongodb.net:27017/app", "no port"),
                      ("mongodb+srv://u:p@h1.mongodb.net,h2.mongodb.net/app", "exactly one host"),
                      ("mongodb://u:p@/app", "no host")):
        with pytest.raises(D.Refusal, match=word):
            M.parse_target(url)


def test_read_preference_comes_from_the_grant_then_the_url_then_the_default():
    plain = "mongodb://u:p@127.0.0.1:27017/app"
    assert M.read_preference(D.Database("a", "mongodb", plain)) == "secondaryPreferred"
    assert M.read_preference(D.Database("a", "mongodb", plain + "?readPreference=nearest")) == "nearest"
    assert M.read_preference(D.Database("a", "mongodb", plain + "?readPreference=nearest", options={"read_preference": "primary"})) == "primary"
    with pytest.raises(D.Refusal, match="not one of"):
        M.read_preference(D.Database("a", "mongodb", plain, options={"read_preference": "anywhere"}))


def test_open_database_reads_the_read_preference_and_the_scheme_from_the_grant(tmp_path):
    db = D.open_database("atlas", "bot:ops", env(tmp_path, SRV, {"read_preference": "primaryPreferred", "max_rows": 50}))
    assert (db.kind, db.max_rows, M.read_preference(db)) == ("mongodb", 50, "primaryPreferred")


def test_an_srv_dns_failure_gets_a_plain_message_and_no_password(tmp_path, monkeypatch):
    import pymongo

    def fail(uri, **_):
        raise pymongo.errors.ConfigurationError(f"The DNS query name does not exist: _mongodb._tcp.cluster0.ab1cd.mongodb.net. ({uri})")
    monkeypatch.setattr(pymongo, "MongoClient", fail)
    db = D.open_database("atlas", "bot:ops", env(tmp_path, SRV))
    with pytest.raises(D.Refusal) as caught:
        M.execute(db, {"op": "count", "collection": "orders"})
    assert caught.value.code == "srv_dns" and "SRV record" in caught.value.detail
    assert "p%40ss-w0rd-secret" not in caught.value.detail and "p@ss-w0rd-secret" not in caught.value.detail


def test_pymongo_errors_map_to_actionable_codes():
    import pymongo.errors as E
    assert M.classify(E.ServerSelectionTimeoutError("cluster0-shard-00-00: timed out"))[0] == "unreachable"
    assert "IP access list" in M.classify(E.ServerSelectionTimeoutError("timed out"))[1]
    assert M.classify(E.ServerSelectionTimeoutError("SSL handshake failed: certificate verify failed"))[0] == "tls"
    assert M.classify(E.OperationFailure("Authentication failed.", code=18))[0] == "auth"
    assert M.classify(E.ExecutionTimeout("operation exceeded time limit", code=50))[0] == "timeout"
    assert M.classify(E.OperationFailure("not authorized on app to execute command", code=13))[0] == "read_only"


def test_a_missing_driver_says_how_to_install_it(monkeypatch):
    import builtins
    real = builtins.__import__

    def no_pymongo(name, *a, **kw):
        if name == "pymongo":
            raise ImportError(name)
        return real(name, *a, **kw)
    monkeypatch.setattr(builtins, "__import__", no_pymongo)
    with pytest.raises(D.Refusal, match="pip install 'pymongo"):
        M.connect(D.Database("a", "mongodb", SRV), 5)


# ----------------------------------------------------------------------------- no server: the read-only rules
@pytest.mark.parametrize("call, operator", [
    ({"op": "aggregate", "collection": "c", "pipeline": [{"$match": {}}, {"$out": "copy"}]}, "$out"),
    ({"op": "aggregate", "collection": "c", "pipeline": [{"$merge": {"into": "copy"}}]}, "$merge"),
    ({"op": "find", "collection": "c", "filter": {"$where": "sleep(1000)"}}, "$where"),
    ({"op": "count", "collection": "c", "filter": {"$or": [{"a": 1}, {"$where": "true"}]}}, "$where"),
    ({"op": "aggregate", "collection": "c", "pipeline": [{"$addFields": {"x": {"$function": {"body": "function(){}", "args": [], "lang": "js"}}}}]}, "$function"),
    ({"op": "aggregate", "collection": "c", "pipeline": [{"$group": {"_id": 1, "x": {"$accumulator": {"init": "x"}}}}]}, "$accumulator"),
    ({"op": "aggregate", "collection": "c", "pipeline": [{"$unionWith": {"coll": "o", "pipeline": [{"$out": "x"}]}}]}, "$out"),
    ({"op": "aggregate", "collection": "c", "pipeline": [{"$lookup": {"from": "o", "pipeline": [{"$merge": "x"}], "as": "y"}}]}, "$merge"),
    ({"op": "distinct", "collection": "c", "field": "a", "filter": {"$where": "1"}}, "$where"),
    ({"op": "find", "collection": "c", "projection": {"x": {"$function": {}}}}, "$function"),
])
def test_write_and_javascript_operators_are_refused_at_any_depth(call, operator):
    with pytest.raises(D.Refusal) as caught:
        M.validate(dict(call), 10)
    assert caught.value.code == "read_only" and operator in caught.value.detail


def test_only_the_read_verbs_run_and_the_shapes_are_checked():
    for verb in ("insert", "update", "delete", "drop", "runCommand", "eval", "mapReduce"):
        with pytest.raises(D.Refusal, match="is not a MongoDB operation"):
            M.call_from_args(verb, ["c", "{}"], margs("a"))
    for bad, match in ((("find", ["c", "{nope"]), "not valid JSON"), (("find", ["c", "[]"]), "must be a JSON object"),
                       (("aggregate", ["c", '{"$match": {}}']), "non-empty JSON array"), (("aggregate", ["c"]), "aggregate <collection>"),
                       (("aggregate", ["c", '[{"$match": {}, "$limit": 1}]']), "exactly one"), (("count", []), "count <collection>"),
                       (("distinct", ["c"]), "distinct <collection> <field>"), (("collections", ["x"]), "no arguments")):
        with pytest.raises(D.Refusal, match=match):
            M.validate(M.call_from_args(bad[0], bad[1], margs("a")), 10)
    with pytest.raises(D.Refusal, match="system collections"):
        M.validate({"op": "find", "collection": "system.users"}, 10)
    with pytest.raises(D.Refusal, match="deployment"):
        M.validate({"op": "aggregate", "collection": "c", "pipeline": [{"$currentOp": {}}]}, 10)
    with pytest.raises(D.Refusal, match="1 or -1"):
        M.validate({"op": "find", "collection": "c", "sort": {"a": "up"}}, 10)


def test_extended_json_input_becomes_real_types_and_output_survives_a_round_trip():
    from bson import ObjectId
    oid = "650000000000000000000abc"
    call = M.call_from_args("find", ["orders", json.dumps({"_id": {"$oid": oid}, "at": {"$gte": {"$date": "2026-09-01T00:00:00Z"}}})], margs("a"))
    assert call["filter"]["_id"] == ObjectId(oid) and call["filter"]["at"]["$gte"] == datetime.datetime(2026, 9, 1, tzinfo=datetime.timezone.utc)
    out = M.dumps({"_id": ObjectId(oid), "at": call["filter"]["at"]["$gte"], "n": 3})
    assert out == {"_id": {"$oid": oid}, "at": {"$date": "2026-09-01T00:00:00Z"}, "n": 3}
    assert M.loads(json.dumps(out), "x")["_id"] == ObjectId(oid)


def test_the_audit_statement_keeps_the_shape_and_drops_every_value():
    call = M.call_from_args("find", ["accounts", '{"email": "ana@acme.example", "age": {"$gt": 34}, "at": {"$date": "2026-09-01T00:00:00Z"}, '
                                                 '"plan": {"$in": ["a", "b", "c", "d", "e", "f", "g"]}, "vip": true, "gone": null}'],
                            margs("a", projection='{"email": 1, "_id": 0}', sort='{"at": -1}', limit=5))
    statement = M.audit_statement(call)
    for value in ("ana@acme.example", "34", "2026-09-01"):
        assert value not in statement
    shaped = json.loads(statement.split(" ", 2)[2])
    assert statement.startswith("find accounts ")
    assert shaped["filter"] == {"email": "<string>", "age": {"$gt": "<number>"}, "at": "<date>",
                                "plan": {"$in": ["<string>"] * 5 + ["...+2"]}, "vip": "<bool>", "gone": "<null>"}
    assert shaped["projection"] == {"email": 1, "_id": 0} and shaped["sort"] == {"at": -1} and shaped["limit"] == 5
    pipeline = M.call_from_args("aggregate", ["orders", '[{"$match": {"status": "paid", "_id": {"$oid": "650000000000000000000abc"}}}, {"$limit": 3}]'], margs("a"))
    assert "paid" not in M.audit_statement(pipeline) and "<objectid>" in M.audit_statement(pipeline)
    assert M.audit_statement({"op": "distinct", "collection": "orders", "field": "status", "filter": {"a": "x"}}).startswith("distinct orders")


# ----------------------------------------------------------------------------- no server: named queries
ENTRY = {"id": "by-status", "params": [{"name": "status", "type": "text"}, {"name": "since", "type": "date"}],
         "mongo": {"op": "find", "collection": "orders", "filter": {"status": {"$param": "status"}, "at": {"$gte": {"$param": "since"}}},
                   "sort": {"at": -1}, "limit": 10}}


def test_catalog_values_are_substituted_as_typed_values_and_stay_values():
    injection = '{"$ne": null}'
    call = M.named_call(ENTRY, {"status": injection, "since": M.coerce("2026-09-01", "date", "since")})
    assert call["filter"]["status"] == injection and isinstance(call["filter"]["status"], str)
    assert call["filter"]["at"]["$gte"] == datetime.datetime(2026, 9, 1, tzinfo=datetime.timezone.utc)
    # The template itself is untouched, and is what the audit records.
    assert call["template"]["filter"]["status"] == {"$param": "status"}
    assert M.audit_statement(call["template"], keep_values=True).count("$param") == 2
    # A value can never carry an operator key or reach another field through a path.
    for text in ("$secret", "$ne"):
        with pytest.raises(D.Refusal, match="field path or operator"):
            M.coerce(text, "text", "status")
    with pytest.raises(D.Refusal, match="not a valid date"):
        M.coerce("yesterday", "date", "since")
    assert M.coerce("a, b ,c", "list", "x") == ["a", "b", "c"] and M.coerce("02134", "text", "zip") == "02134"


def test_a_catalog_entry_cannot_smuggle_a_write_or_a_bad_placeholder():
    hostile = {"id": "x", "params": [], "mongo": {"op": "aggregate", "collection": "c", "pipeline": [{"$out": "copy"}]}}
    with pytest.raises(D.Refusal, match=r"\$out"):
        M.validate(M.named_call(hostile, {}), 10)
    with pytest.raises(D.Refusal, match="no other keys"):
        M.named_call({"id": "x", "mongo": {"op": "find", "collection": "c", "filter": {"a": {"$param": "p", "$ne": 1}}}}, {"p": 1})
    with pytest.raises(D.Refusal, match="no value for p"):
        M.named_call({"id": "x", "mongo": {"op": "find", "collection": "c", "filter": {"a": {"$param": "p"}}}}, {})
    with pytest.raises(D.Refusal, match="no valid `mongo:` block"):
        M.named_call({"id": "x", "mongo": {"op": "insert", "collection": "c"}}, {})


def catalog_entry(**mongo):
    return {"id": "q", "title": "Q", "description": "", "category": "", "tags": [], "database": "atlas",
            "mongo": {"op": "find", "collection": "c", **mongo}, "params": [{"name": "p", "type": "text"}]}


def test_the_server_validates_mongo_catalog_entries():
    assert I.parse_queries(yaml.safe_dump({"queries": [catalog_entry(filter={"a": {"$param": "p"}})]}), "q.yaml")[0]["mongo"]["op"] == "find"
    for entry, message in ((catalog_entry(filter={"a": {"$param": "nope"}}), "unknown: nope"),
                           (catalog_entry(filter={"a": {"$param": "p", "x": 1}}), r"\$param"),
                           (catalog_entry(op="insert"), "needs op"), (catalog_entry(pipeline=[]), "aggregate takes"),
                           (catalog_entry(surprise=1), "unknown keys"), ({**catalog_entry(), "sql": "SELECT 1"}, "must have exactly")):
        with pytest.raises(ValueError, match=message):
            I.parse_queries(yaml.safe_dump({"queries": [entry]}), "q.yaml")


def test_the_acme_example_config_carries_a_mongo_catalog_that_loads_and_validates():
    pages, _ = I.load(ROOT / "integrations", ROOT / "templates" / "company-config" / "integrations")
    assert "mongodb" in pages and pages["mongodb"]["writes"] == "never"
    queries = {q["id"]: q for q in pages["atlas"]["queries"]}
    assert {"signups-since", "signups-by-region", "event-types"} <= set(queries)
    from clients.hubtools import query_search
    assert [q["id"] for q in query_search(pages["atlas"]["queries"], "region")] == ["signups-by-region"]
    for query in queries.values():
        values = {p["name"]: M.coerce(p.get("default", "2026-09-01"), p.get("type", ""), p["name"]) for p in query["params"]}
        M.validate(M.named_call(query, values), 10)


def test_the_hub_accepts_the_mongo_audit_fields(api):
    _, _, attempt = setup_attempt(api)
    body = {"database": "atlas", "kind": "mongodb", "statement": 'find accounts {"filter":{"email":"<string>"}}', "rows": 1,
            "truncated": False, "ms": 4, "query": None, "params": [], "error": None, "operation": "find", "collection": "accounts"}
    post(api, "databases/audit", body, token=attempt["token"])
    with api.app.state.store.read() as c:
        detail = json.loads(c.execute("SELECT detail_json FROM events WHERE action = 'db.query'").fetchone()["detail_json"])
    assert (detail["kind"], detail["operation"], detail["collection"]) == ("mongodb", "find", "accounts")
    post(api, "databases/audit", {**body, "operation": "Find; DROP"}, token=attempt["token"], expected=422)


# ----------------------------------------------------------------------------- no server: audit through the command
def test_the_command_audits_shape_and_row_count_and_refusals_without_a_server(tmp_path, monkeypatch):
    monkeypatch.setattr(M, "perform", lambda db, call, max_rows, timeout: ([{"n": 1}, {"n": 2}], False))
    hub, environ = FakeHub(), env(tmp_path, SRV)
    result = D.run(hub, margs("atlas", "find", "accounts", '{"email": "ana@acme.example"}'), environ)
    assert result["row_count"] == 2
    (audit,) = hub.audits
    assert audit["kind"] == "mongodb" and audit["operation"] == "find" and audit["collection"] == "accounts" and audit["rows"] == 2
    assert "ana@acme.example" not in json.dumps(audit) and "<string>" in audit["statement"] and audit["params"] == []
    with pytest.raises(APIError) as caught:
        D.run(hub, margs("atlas", "aggregate", "accounts", '[{"$match": {"email": "bo@acme.example"}}, {"$out": "leak"}]'), environ)
    assert caught.value.code == "read_only"
    refusal = hub.audits[-1]
    assert refusal["error"] == "read_only" and refusal["rows"] == 0 and "bo@acme.example" not in json.dumps(refusal)
    with pytest.raises(APIError, match="fills a named query"):
        D.run(hub, margs("atlas", "count", "accounts", param=["a=b"]), environ)
    hub.fail_audit = True
    with pytest.raises(APIError) as caught:
        D.run(hub, margs("atlas", "count", "accounts"), environ)
    assert caught.value.code == "audit"


def test_a_named_query_audits_the_template_and_the_parameter_names_only(tmp_path, monkeypatch):
    seen = {}
    monkeypatch.setattr(M, "perform", lambda db, call, max_rows, timeout: (seen.update(call=call) or [], False))
    entry = {**ENTRY, "title": "T", "params": [{"name": "status", "type": "text", "required": True}, {"name": "since", "type": "date", "default": "2026-01-01"}]}
    hub = FakeHub(catalog={("atlas", "by-status"): entry})
    D.run(hub, margs("atlas", query_id="by-status", param=['status={"$ne": null}']), env(tmp_path, SRV))
    assert seen["call"]["filter"]["status"] == '{"$ne": null}'
    (audit,) = hub.audits
    assert audit["query"] == "by-status" and audit["params"] == ["since", "status"]
    assert "$ne" not in audit["statement"] and audit["statement"].count("$param") == 2
    with pytest.raises(APIError, match="required"):
        D.run(hub, margs("atlas", query_id="by-status"), env(tmp_path, SRV))
    with pytest.raises(APIError, match="either an operation or --query"):
        D.run(hub, margs("atlas", "find", "orders", query_id="by-status"), env(tmp_path, SRV))


def test_redaction_removes_a_mongodb_srv_password_from_any_message():
    text = f"failed to connect to {SRV} as tico_ro:p%40ss-w0rd-secret@cluster0 and mongodb+srv://x:other-secret@h/db"
    clean = D.redact(text, SRV)
    assert "p%40ss-w0rd-secret" not in clean and "p@ss-w0rd-secret" not in clean and "other-secret" not in clean


def test_render_prints_one_extended_json_document_per_line_and_the_cli_parses_mongo_arguments():
    result = {"documents": [{"_id": {"$oid": "650000000000000000000abc"}}, {"n": 1}], "row_count": 2, "truncated": True, "ms": 7}
    lines = D.render(result, margs("a")).splitlines()
    assert lines[0] == '{"_id":{"$oid":"650000000000000000000abc"}}' and lines[-1].startswith("2 documents shown (more available")
    from clients import hubcli
    parsed = hubcli.parser().parse_args(["db", "atlas", "find", "orders", '{"a": 1}', "--projection", '{"a": 1}', "--sort", '{"a": -1}', "--limit", "5"])
    assert (parsed.target, parsed.sql, parsed.extra, parsed.limit) == ("atlas", "find", ["orders", '{"a": 1}'], 5)
    assert hubcli.parser().parse_args(["db", "warehouse", "SELECT 1"]).extra == []


def test_the_doctor_flags_write_actions_and_scope_from_connection_status():
    assert M.write_actions([{"actions": ["find", "collStats", "listCollections", "changeStream"]}]) == []
    assert M.write_actions([{"actions": ["find", "insert", "createIndex", "dropCollection", "grantRole", "anyAction"]}]) == \
        ["anyAction", "createIndex", "dropCollection", "grantRole", "insert"]


# ----------------------------------------------------------------------------- MongoDB, when Docker can run one
@pytest.fixture(scope="module")
def mongo():
    docker = shutil.which("docker")
    if not docker:
        pytest.skip("docker is not installed")
    pymongo = pytest.importorskip("pymongo")
    name = "tico-mongo-test-" + uuid.uuid4().hex[:8]
    try:
        started = subprocess.run([docker, "run", "-d", "--rm", "--name", name, "-e", "MONGO_INITDB_ROOT_USERNAME=root",
                                  "-e", "MONGO_INITDB_ROOT_PASSWORD=admin-pw", "-p", "127.0.0.1::27017", "mongo:7"],
                                 capture_output=True, text=True, timeout=180)
        if started.returncode:
            pytest.skip("cannot start a mongo container: " + started.stderr.strip()[:120])
    except subprocess.TimeoutExpired:
        pytest.skip("docker did not answer")
    try:
        port = subprocess.run([docker, "port", name, "27017/tcp"], capture_output=True, text=True).stdout.splitlines()[0].split(":")[-1].strip()
        admin = None
        for _ in range(90):
            try:
                admin = pymongo.MongoClient(f"mongodb://root:admin-pw@127.0.0.1:{port}/?authSource=admin", serverSelectionTimeoutMS=1500)
                admin.admin.command("ping")
                break
            except pymongo.errors.PyMongoError:
                time.sleep(1)
        else:
            pytest.skip("mongo did not come up")
        app = admin["app"]
        app.orders.insert_many([{"n": i, "status": "paid" if i % 2 else "pending", "email": f"user{i}@example.com",
                                 "at": datetime.datetime(2026, 1, 1, tzinfo=datetime.timezone.utc) + datetime.timedelta(days=i)} for i in range(1000)])
        app.one.insert_one({"a": 1})
        admin["other"].secrets.insert_one({"s": 1})
        for user, roles in (("tico_ro", [{"role": "read", "db": "app"}]), ("tico_rw", [{"role": "readWrite", "db": "app"}]),
                            ("tico_wide", [{"role": "read", "db": "app"}, {"role": "read", "db": "other"}])):
            admin.admin.command("createUser", user, pwd=user + "-secret-pw", roles=roles)
        url = lambda user: f"mongodb://{user}:{user}-secret-pw@127.0.0.1:{port}/app?authSource=admin"  # noqa: E731
        yield {"ro": url("tico_ro"), "rw": url("tico_rw"), "wide": url("tico_wide"), "admin": admin, "port": port}
        admin.close()
    finally:
        subprocess.run([docker, "rm", "-f", name], capture_output=True)


def go(url, verb, *rest, max_rows=None, timeout=None, **kw):
    limits = {k: v for k, v in (("max_rows", max_rows), ("timeout", timeout)) if v}
    return M.execute(D.Database("atlas", "mongodb", url, **limits), M.call_from_args(verb, rest, margs("atlas", **kw)))


def test_mongo_reads_caps_rows_and_supports_the_five_operations(mongo):
    result = go(mongo["ro"], "find", "orders", '{"status": "paid"}', sort='{"n": -1}', projection='{"n": 1, "_id": 0}', limit=3)
    assert [d["n"] for d in result["documents"]] == [999, 997, 995] and not result["truncated"]
    capped = go(mongo["ro"], "find", "orders", max_rows=100)
    assert capped["row_count"] == 100 and capped["truncated"]
    assert not go(mongo["ro"], "find", "orders", max_rows=100, limit=100)["truncated"]
    agg = go(mongo["ro"], "aggregate", "orders", '[{"$group": {"_id": "$status", "n": {"$sum": 1}}}, {"$sort": {"_id": 1}}]')
    assert agg["documents"] == [{"_id": "paid", "n": 500}, {"_id": "pending", "n": 500}]
    assert go(mongo["ro"], "aggregate", "orders", '[{"$match": {}}]', max_rows=10)["truncated"]
    assert go(mongo["ro"], "count", "orders", '{"status": "paid"}')["documents"] == [{"count": 500}]
    assert go(mongo["ro"], "distinct", "orders", "status")["documents"] == ["paid", "pending"]
    found = {c["collection"]: c["fields"] for c in go(mongo["ro"], "collections")["documents"]}
    assert set(found) == {"orders", "one"} and found["orders"]["email"] == "str" and found["orders"]["_id"] == "objectId"


def test_mongo_extended_json_round_trips_object_ids_and_dates(mongo):
    doc = go(mongo["ro"], "find", "orders", '{"n": 5}', limit=1)["documents"][0]
    assert set(doc["_id"]) == {"$oid"} and doc["at"] == {"$date": "2026-01-06T00:00:00Z"}
    again = go(mongo["ro"], "find", "orders", json.dumps({"_id": doc["_id"], "at": {"$gte": doc["at"]}}))
    assert again["documents"] == [doc]
    assert go(mongo["ro"], "count", "orders", '{"at": {"$lt": {"$date": "2026-01-11T00:00:00Z"}}}')["documents"] == [{"count": 10}]


def test_the_read_role_cannot_write_and_the_doctor_says_so(mongo):
    import pymongo
    client = pymongo.MongoClient(mongo["ro"])
    with pytest.raises(pymongo.errors.OperationFailure):
        client["app"].orders.insert_one({"x": 1})
    with pytest.raises(pymongo.errors.OperationFailure):
        client["app"].orders.delete_many({})
    client.close()
    checks = M.probe(D.Database("atlas", "mongodb", mongo["ro"]))
    assert all(c["level"] == "ok" for c in checks), checks
    assert any(c["check"] == "role privileges" and "read@app" in c["detail"] for c in checks)


def test_the_doctor_warns_when_the_user_could_write_or_reaches_other_databases(mongo):
    rw = {c["check"]: c for c in M.probe(D.Database("atlas", "mongodb", mongo["rw"]))}
    assert rw["role privileges"]["level"] == "warn" and "insert" in rw["role privileges"]["detail"] and "read" in rw["role privileges"]["detail"]
    wide = {c["check"]: c for c in M.probe(D.Database("atlas", "mongodb", mongo["wide"]))}
    assert wide["role privileges"]["level"] == "ok" and wide["role scope"]["level"] == "warn" and "other" in wide["role scope"]["detail"]
    report = D.probe(D.Database("atlas", "mongodb", mongo["rw"]))
    assert any(c["level"] == "warn" for c in report)


def test_writes_are_refused_before_they_leave_even_for_a_user_who_could_write(mongo):
    for pipeline in ('[{"$match": {}}, {"$out": "copy"}]', '[{"$merge": {"into": "copy"}}]',
                     '[{"$unionWith": {"coll": "one", "pipeline": [{"$out": "copy"}]}}]'):
        with pytest.raises(D.Refusal) as caught:
            go(mongo["rw"], "aggregate", "orders", pipeline)
        assert caught.value.code == "read_only"
    with pytest.raises(D.Refusal):
        go(mongo["rw"], "find", "orders", '{"$where": "this.n == 1"}')
    with pytest.raises(D.Refusal):
        go(mongo["rw"], "aggregate", "orders", '[{"$addFields": {"x": {"$function": {"body": "function(){return 1}", "args": [], "lang": "js"}}}}]')
    assert "copy" not in mongo["admin"]["app"].list_collection_names()
    assert mongo["admin"]["app"].orders.count_documents({}) == 1000


def test_maxtimems_stops_a_slow_operation(mongo):
    slow = ('[{"$set": {"x": {"$reduce": {"input": {"$range": [0, 200000]}, "initialValue": 0, '
            '"in": {"$add": ["$$value", "$$this"]}}}}}]')                       # 1,000 documents x 200,000 additions
    db = D.Database("atlas", "mongodb", mongo["ro"], timeout=1)
    started = time.monotonic()
    with pytest.raises(D.Refusal) as caught:
        M.execute(db, M.call_from_args("aggregate", ["orders", slow], margs("atlas")), timeout=0.05)
    assert caught.value.code == "timeout" and time.monotonic() - started < 10


def test_the_client_reads_with_secondary_preferred_unless_configured(mongo):
    db = D.Database("atlas", "mongodb", mongo["ro"])
    client = M.connect(db, 5)
    assert client.read_preference.mongos_mode == "secondaryPreferred"
    client.close()
    client = M.connect(D.Database("atlas", "mongodb", mongo["ro"], options={"read_preference": "primary"}), 5)
    assert client.read_preference.mongos_mode == "primary"
    client.close()


def test_the_command_audits_no_values_against_a_real_server(mongo, tmp_path):
    hub, environ = FakeHub(), env(tmp_path, mongo["ro"])
    result = D.run(hub, margs("atlas", "find", "orders", '{"email": "user7@example.com", "n": 7}'), environ)
    assert result["row_count"] == 1
    (audit,) = hub.audits
    blob = json.dumps(audit)
    assert "user7@example.com" not in blob and audit["rows"] == 1 and (audit["operation"], audit["collection"]) == ("find", "orders")
    assert audit["statement"] == 'find orders {"filter":{"email":"<string>","n":"<number>"}}'
    assert "user7@example.com" in D.render(result, margs("atlas"))                      # the bot sees the row; the hub does not


def test_a_named_query_treats_an_injection_attempt_as_a_value(mongo, tmp_path):
    entry = {"id": "by-status", "title": "T", "params": [{"name": "status", "type": "text", "required": True}],
             "mongo": {"op": "count", "collection": "orders", "filter": {"status": {"$param": "status"}}}}
    hub, environ = FakeHub(catalog={("atlas", "by-status"): entry}), env(tmp_path, mongo["ro"])
    assert D.run(hub, margs("atlas", query_id="by-status", param=["status=paid"]), environ)["documents"] == [{"count": 500}]
    for attack in ('{"$ne": null}', '{"$gt": ""}', 'paid" , "$or": [{}]', "x'; //"):
        assert D.run(hub, margs("atlas", query_id="by-status", param=[f"status={attack}"]), environ)["documents"] == [{"count": 0}], attack
    with pytest.raises(APIError, match="field path or operator"):
        D.run(hub, margs("atlas", query_id="by-status", param=["status=$ne"]), environ)
    assert all("$ne" not in a["statement"] and "paid" not in a["statement"] for a in hub.audits)


def test_a_failed_login_never_shows_the_password(mongo):
    wrong = mongo["ro"].replace("tico_ro-secret-pw", "wr0ng-pw-1234")
    with pytest.raises(D.Refusal) as caught:
        go(wrong, "count", "orders")
    assert caught.value.code == "auth" and "wr0ng-pw-1234" not in caught.value.detail
    dead = f"mongodb://tico_ro:dead-pw-4321@127.0.0.1:1/app"
    with pytest.raises(D.Refusal) as caught:
        M.execute(D.Database("atlas", "mongodb", dead), {"op": "count", "collection": "orders"})
    assert caught.value.code == "unreachable" and "dead-pw-4321" not in caught.value.detail
