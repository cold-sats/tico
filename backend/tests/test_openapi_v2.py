"""The v2 contract a frontend builds on: served to signed-in callers, limited to the stable
resources, committed as docs/openapi/v2.json, and true to what the API answers."""

import re

from backend import openapi_v2
from backend.tests.test_api import api, get, headers, post  # noqa: F401  (the api fixture)


def conforms(value, schema, root, where="$"):
    """The subset of JSON Schema the contract uses: type, required, properties, items, oneOf, enum, $ref."""
    if "$ref" in schema:
        return conforms(value, root["components"]["schemas"][schema["$ref"].rsplit("/", 1)[1]], root, where)
    if "oneOf" in schema:
        errors = [conforms(value, option, root, where) for option in schema["oneOf"]]
        return None if any(e is None for e in errors) else "; ".join(errors)
    if "enum" in schema:
        return None if value in schema["enum"] else "%s: %r not in %r" % (where, value, schema["enum"])
    kinds = schema.get("type")
    kinds = [kinds] if isinstance(kinds, str) else kinds
    names = {dict: "object", list: "array", str: "string", bool: "boolean", int: "integer", float: "number",
             type(None): "null"}
    actual = names[type(value)]
    if kinds and actual not in kinds and not (actual == "integer" and "number" in kinds):
        return "%s: %s is not %s" % (where, actual, kinds)
    if isinstance(value, dict):
        for key in schema.get("required", []):
            if key not in value:
                return "%s: missing %s" % (where, key)
        for key, sub in schema.get("properties", {}).items():
            if key in value and (error := conforms(value[key], sub, root, where + "." + key)):
                return error
    if isinstance(value, list) and "items" in schema:
        for i, item in enumerate(value[:5]):
            if error := conforms(item, schema["items"], root, "%s[%d]" % (where, i)):
                return error
    return None


def test_the_committed_copy_is_current():
    assert openapi_v2.COPY.read_text() == openapi_v2.render(openapi_v2.generate()), \
        "docs/openapi/v2.json is stale: run python -m backend.openapi_v2"


def test_served_to_the_signed_in_only_and_limited_to_the_stable_resources(api):
    assert api.get("/api/v2/openapi.json").status_code == 401
    assert api.get("/openapi.json").status_code == 401 and api.get("/docs").status_code == 401
    for path in ("/openapi.json", "/docs", "/redoc"):
        assert api.get(path, headers=headers()).status_code == 404       # FastAPI's own pages stay off
    document = api.get("/api/v2/openapi.json", headers=headers("ben-test")).json()
    assert document == api.get("/api/v2/openapi.json", headers=headers()).json()
    assert document["info"]["version"] == "2.0.0" and document["openapi"].startswith("3.")
    served = {(p, m) for p, ops in document["paths"].items() for m in ops}
    assert served == {(p, m) for p, m, *_ in openapi_v2.STABLE}
    for internal in ("/api/v2/runners/heartbeat", "/api/v2/jobs/claim", "/api/v2/credentials", "/scim/v2/Users",
                     "/api/v2/settings/history", "/api/v2/access"):
        assert not any(path.startswith(internal) for path in document["paths"])
    ids = [op["operationId"] for ops in document["paths"].values() for op in ops.values()]
    assert len(ids) == len(set(ids)) and all(re.fullmatch(r"[a-z][A-Za-z0-9]+", i) for i in ids)
    tagged = {tag for ops in document["paths"].values() for op in ops.values() for tag in op["tags"]}
    assert tagged == set(openapi_v2.TAGS) == {t["name"] for t in document["tags"]}
    text = str(document)
    assert all(ref in document["components"]["schemas"] for ref in re.findall(r"#/components/schemas/(\w+)", text))


def test_every_write_asks_for_an_idempotency_key(api):
    document = api.get("/api/v2/openapi.json", headers=headers()).json()
    for path, ops in document["paths"].items():
        if path.startswith("/api/v2/") and "post" in ops:
            names = [p["name"] for p in ops["post"]["parameters"]]
            assert "Idempotency-Key" in names, path


def test_the_declared_answers_match_the_live_ones(api):
    document = api.get("/api/v2/openapi.json", headers=headers()).json()
    by_id = {op["operationId"]: op for ops in document["paths"].values() for op in ops.values()}

    def check(operation, response):
        schema = by_id[operation]["responses"]["200"]["content"]["application/json"]["schema"]
        assert conforms(response.json(), schema, document) is None, (operation, conforms(response.json(), schema, document), response.text[:400])

    def call(operation, method, path, **kw):
        response = getattr(api, method)(path, headers=headers(), **kw)
        assert response.status_code == 200, (path, response.text)
        check(operation, response)
        return response.json()

    call("getMe", "get", "/api/v2/me")
    call("getConfig", "get", "/api/v2/config")
    call("getOrg", "get", "/api/v2/org")
    call("listBots", "get", "/api/v2/bots")
    call("listRecentBots", "get", "/api/v2/me/recent")
    chat = call("chatWithBot", "post", "/api/v2/chat/ops", json={"text": "hello"})
    cid = chat["conversation"]["id"]
    call("listConversations", "get", "/api/v2/conversations")
    call("listMessages", "get", "/api/v2/conversations/%s/messages" % cid)
    call("getConversationSnapshot", "get", "/api/v2/conversations/%s/snapshot" % cid)
    call("replyInConversation", "post", "/api/v2/conversations/%s/messages" % cid, json={"text": "again"})
    call("getMessage", "get", "/api/v2/messages/" + chat["message"]["id"])
    call("sendMessage", "post", "/api/v2/messages", json={"to": "bot:ops", "text": "third"})
    task = call("createTask", "post", "/api/v2/tasks",
                json={"title": "Draft the launch plan", "body": "Please draft it.", "owner": "human:ana"})["task"]
    call("listTasks", "get", "/api/v2/tasks")
    detail = call("getTask", "get", "/api/v2/tasks/" + task["id"])
    call("updateTask", "post", "/api/v2/tasks/" + task["id"], json={"version": detail["task"]["version"], "status": "doing"})
    call("commentOnTask", "post", "/api/v2/tasks/" + task["id"] + "/comments", json={"text": "looks good"})
    call("listUpdates", "get", "/api/v2/updates")
    call("countUnreadUpdates", "get", "/api/v2/updates/unread")
    call("getNeedsYou", "get", "/api/v2/needs-you")
    call("getNeedsYou", "get", "/api/v2/needs-you", params={"count": "true"})
    call("searchMeetings", "get", "/api/v2/meetings/search")
    call("searchDocs", "get", "/api/v2/context/search", params={"q": "plan"})
    call("getHealth", "get", "/api/v2/health")
