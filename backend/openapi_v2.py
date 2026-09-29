"""The stable v2 contract for a company's own frontend: `GET /api/v2/openapi.json`.

FastAPI would describe every route, runner and bot endpoint included. A frontend team needs the
resources a person's app is built from, so this module keeps only those (STABLE below), names
each operation, groups them by resource and describes the answers a person gets. Handlers return
plain dictionaries rather than response models, so the answer shapes are declared here; a test
(backend/tests/test_openapi_v2.py) checks them against live responses, and that the committed copy
`docs/openapi/v2.json` matches. Regenerate it with `python -m backend.openapi_v2`.

Anything not listed is internal and may change in any release. See docs/api.md.
"""

import copy
import json
import sys
from pathlib import Path

VERSION = "2.0.0"
COPY = Path(__file__).resolve().parents[1] / "docs" / "openapi" / "v2.json"

TAGS = {
    "Session": "Who is calling, and how a frontend signs in (docs/custom-frontend.md).",
    "Company": "This installation's names and settings.",
    "Org chart": "People and bots, and who reports to whom.",
    "Bots": "The bots a person can see, and their live status.",
    "Conversations": "Chats with bots: send, list, and stream replies.",
    "Tasks": "Work assigned to people and bots.",
    "Updates": "Daily and weekly updates bots post to people.",
    "Needs you": "What is waiting on the signed-in person: questions, tasks, approvals.",
    "Meetings": "Recorded meetings.",
    "Files": "What a bot creates, revises or delivers, listed on its page (docs/files.md).",
    "Docs": "Company documents and search.",
    "Assistant": "The signed-in person's own private Assistant chat (docs/assistant.md): ask, and confirm what it proposes.",
    "Health": "Whether the installation is working.",
}

# Path, method, tag, operationId, summary, name of the 200 answer in ANSWERS.
STABLE = [
    ("/api/v2/me", "get", "Session", "getMe", "The signed-in caller", "Me"),
    ("/auth/login", "get", "Session", "startSignIn",
     "Start browser sign-in (redirects); a frontend passes next and code_challenge", None),
    ("/auth/token", "post", "Session", "exchangeCode", "Exchange the one-time sign-in code for a bearer session", "Token"),
    ("/auth/token/revoke", "post", "Session", "revokeSession", "Sign the bearer session out", "Revoked"),
    ("/api/v2/me/tokens", "get", "Session", "listMyTokens", "The caller's personal API tokens (never the secret)", None),
    ("/api/v2/me/tokens", "post", "Session", "createMyToken",
     "Mint a personal API token for server-to-server use (owner and bot administrators; cookie sessions only)", None),
    ("/api/v2/me/tokens/{token_id}/revoke", "post", "Session", "revokeMyToken", "Revoke a personal API token", None),
    ("/api/v2/openapi.json", "get", "Session", "getOpenApi", "This document", None),
    ("/api/v2/config", "get", "Company", "getConfig", "Company and app names, version, setup state", "Config"),
    ("/api/v2/org", "get", "Org chart", "getOrg",
     "People, the bots the caller can see and reports_to; ?can=read|write keeps the bots they can read or write to", "Org"),
    ("/api/v2/people/{pid}", "post", "Org chart", "updatePerson", "Edit a person's profile or reports_to", None),
    ("/api/v2/bots", "get", "Bots", "listBots",
     "Bots the caller can see, each with the caller's own access; ?can=read|write keeps the ones they can read or write to",
     "BotList"),
    ("/api/v2/bots/{bot}", "get", "Bots", "getBot",
     "One bot: its profile for anyone who can see it; status, machine, queue and goals too for anyone who can read it",
     "BotDetail"),
    ("/api/v2/bots/{bot}/routines", "get", "Bots", "listBotRoutines",
     "A bot's routines, its recurring work (Read on the bot; add include_deleted=true for removed ones)", "RoutineList"),
    ("/api/v2/bots/{bot}/access", "get", "Bots", "getBotAccess",
     "Who may see, read and write to a bot (its managers only; docs/permissions.md)", "BotAccess"),
    ("/api/v2/bots/{bot}/access", "put", "Bots", "setBotAccess",
     "Set who may see, read and write to a bot; send the revision you read (409 version_conflict otherwise)", "BotAccess"),
    ("/api/v2/models", "get", "Bots", "listModels", "Models a bot can be set to", None),
    ("/api/v2/me/recent", "get", "Bots", "listRecentBots", "Bots the caller worked with lately", "Recent"),
    ("/api/v2/bots/{bot}/updates", "get", "Updates", "getBotUpdateSettings", "A bot's daily and weekly update settings", None),
    ("/api/v2/conversations", "get", "Conversations", "listConversations",
     "The caller's conversations; chat_with=<bot> for that bot's chat", "ConversationList"),
    ("/api/v2/conversations", "post", "Conversations", "createConversation", "Open a conversation", None),
    ("/api/v2/conversations/{cid}/messages", "get", "Conversations", "listMessages",
     "The newest messages (up to 200); before=<message id> pages back, since=<timestamp> only newer", "MessagePage"),
    ("/api/v2/conversations/{cid}/messages", "post", "Conversations", "replyInConversation",
     "Send a message in a conversation", "MessageResult"),
    ("/api/v2/conversations/{cid}/snapshot", "get", "Conversations", "getConversationSnapshot",
     "The newest messages and the bot's current run, in one read", "Snapshot"),
    ("/api/v2/conversations/{cid}/watch", "get", "Conversations", "watchConversation",
     "Server-sent events: whole-conversation snapshots while a bot works (reconnect for a fresh one)", None),
    ("/api/v2/conversations/{cid}/stream", "get", "Conversations", "streamConversation",
     "Server-sent events: bot output deltas with a resumable cursor (after=<id>) and message lists", None),
    ("/api/v2/chat/{bot}", "post", "Conversations", "chatWithBot", "Send a message to a bot (opens the chat if needed)", "ChatResult"),
    ("/api/v2/chat/{bot}/new", "post", "Conversations", "startNewChat", "Archive the current personal chat and start fresh", None),
    ("/api/v2/messages", "post", "Conversations", "sendMessage", "Send a message to a person or bot", "Message"),
    ("/api/v2/messages/{mid}", "get", "Conversations", "getMessage", "One message", "Message"),
    ("/api/v2/tasks", "get", "Tasks", "listTasks", "Tasks the caller can see", "TaskList"),
    ("/api/v2/tasks", "post", "Tasks", "createTask", "Create a task", "TaskResult"),
    ("/api/v2/tasks/dry-run", "post", "Tasks", "checkTask", "The checks a create would fail; writes nothing", None),
    ("/api/v2/tasks/labels", "get", "Tasks", "listTaskLabels", "Labels in use", None),
    ("/api/v2/tasks/{tid}", "get", "Tasks", "getTask", "A task with its history, comments and messages", "TaskDetail"),
    ("/api/v2/tasks/{tid}", "post", "Tasks", "updateTask",
     "Change a task; send the version you read (409 version_conflict otherwise)", "TaskResult"),
    ("/api/v2/tasks/{tid}/comments", "post", "Tasks", "commentOnTask", "Comment on a task", "CommentResult"),
    ("/api/v2/updates", "get", "Updates", "listUpdates", "Daily and weekly updates", "UpdateList"),
    ("/api/v2/updates/unread", "get", "Updates", "countUnreadUpdates", "How many updates are unread", "Unread"),
    ("/api/v2/updates/read", "post", "Updates", "markUpdatesRead", "Mark updates read or unread", None),
    ("/api/v2/updates/{uid}", "get", "Updates", "getUpdate", "One update and the replies to it", None),
    ("/api/v2/updates/{uid}/reply", "post", "Updates", "replyToUpdate", "Reply to an update (goes to the bot)", None),
    ("/api/v2/needs-you", "get", "Needs you", "getNeedsYou",
     "What waits on the caller; count=true for the number alone", "NeedsYou"),
    ("/api/v2/messages/{mid}/answer", "post", "Needs you", "answerMessage", "Answer a question a bot asked", None),
    ("/api/v2/approvals/{aid}", "get", "Needs you", "getApproval", "One approval request", None),
    ("/api/v2/approvals/{aid}", "post", "Needs you", "decideApproval", "Approve or reject", None),
    ("/api/v2/meetings/search", "get", "Meetings", "searchMeetings", "Search or list recorded meetings", "MeetingSearch"),
    ("/api/v2/meetings/transcript", "get", "Meetings", "getMeetingTranscript", "A meeting's transcript", None),
    ("/api/v2/bots/{bot}/files", "get", "Files", "listBotFiles",
     "A bot's files the caller may see, newest activity first, with the visible total; limit and cursor page", "BotFileList"),
    ("/api/v2/files/uploads", "post", "Files", "uploadBotFile",
     "A bot (or its computer) publishes a file: raw bytes with the fields in the query, or JSON text/content_base64", "BotFileResult"),
    ("/api/v2/files/links", "post", "Files", "addFileLink",
     "Register or touch an https document (Google, Notion, Figma, any site); Tico keeps the address only", "BotFileResult"),
    ("/api/v2/files/imports", "post", "Files", "importFile",
     "Bytes the bot's computer copied from an S3 object; a changed etag is a new version", "BotFileResult"),
    ("/api/v2/files/{fid}", "patch", "Files", "editBotFile",
     "Change a file's title or task, remove it from the list (archive) or promote it bot-wide (owner and bot administrators)",
     "BotFileResult"),
    ("/api/v2/files/{fid}/activity", "get", "Files", "listFileActivity", "A file's append-only activity, newest first", "FileActivity"),
    ("/api/v2/files/{fid}/versions", "get", "Files", "listFileVersions", "A file's versions, newest first", "FileVersions"),
    ("/api/v2/files/{fid}/versions/{number}", "get", "Files", "getFileVersion",
     "The bytes of one version (a download, never a storage address)", None),
    ("/api/v2/context/search", "get", "Docs", "searchDocs", "Search company documents", "DocSearch"),
    ("/api/v2/context/document", "get", "Docs", "getDocument", "One document", None),
    ("/api/v2/assistant", "get", "Assistant", "getAssistant",
     "The caller's Assistant: their private room id, whether it is on, the recent messages and what waits for their OK",
     "Assistant"),
    ("/api/v2/assistant/messages", "post", "Assistant", "sendAssistantMessage",
     "Say something to the Assistant. A lookup is answered at once (fast: true, with the reply); anything else "
     "is a turn of the assistant bot, shown as `execution` on GET /api/v2/assistant", "AssistantSent"),
    ("/api/v2/assistant/turn-on", "post", "Assistant", "turnOnAssistant",
     "Owner only: restore the archived assistant, or add it from the catalog, and activate it", None),
    ("/api/v2/assistant/actions", "post", "Assistant", "proposeAssistantAction",
     "Propose one operation for the caller to confirm (what the assistant's `hub assistant propose` calls)", "AssistantActionResult"),
    ("/api/v2/assistant/actions/{aid}", "get", "Assistant", "getAssistantAction", "One proposal and how it ended",
     "AssistantActionResult"),
    ("/api/v2/assistant/actions/{aid}/confirm", "post", "Assistant", "confirmAssistantAction",
     "The person's own click: runs the proposal as them, once. Never callable by the assistant or a personal token",
     "AssistantActionResult"),
    ("/api/v2/assistant/actions/{aid}/cancel", "post", "Assistant", "cancelAssistantAction",
     "Drop a proposal; it never runs", "AssistantActionResult"),
    ("/healthz", "get", "Health", "getLiveness", "Is the server up (no sign-in)", None),
    ("/api/v2/health", "get", "Health", "getHealth", "Checks, computers and failures (people only)", "Health"),
]


def _t(kind):
    return {"s": {"type": "string"}, "i": {"type": "integer"}, "b": {"type": "boolean"}, "o": {"type": "object"},
            "n": {"type": ["string", "null"]}, "a": {"type": "array"}, "f": {"type": "number"}}[kind]


def obj(fields, required=None, **arrays):
    """An object schema from {"name": "s|i|b|o|n|a|f"} or {"name": {schema}}. Other fields are allowed."""
    props = {k: (_t(v) if isinstance(v, str) else v) for k, v in fields.items()}
    props.update(arrays)
    return {"type": "object", "properties": props, "required": sorted(required if required is not None else props),
            "additionalProperties": True}


def items(schema):
    return {"type": "array", "items": schema}


ref = lambda name: {"$ref": "#/components/schemas/" + name}   # noqa: E731
ACTORS = {"type": "object", "additionalProperties": {"type": "string"},
          "description": "On reads: display names for every actor id in the answer, {\"human:ana\": \"Ana Alvarez\"}"}

SCHEMAS = {
    "Message": obj({"id": "s", "conversation_id": "s", "from_actor": "s", "to_actor": "s", "kind": "s", "body": "s",
                    "created": "s", "in_reply_to": "n", "refs": "o"}, required=["id", "conversation_id", "from_actor", "to_actor", "kind", "body", "created", "in_reply_to", "refs"],
                   from_name={"type": "string", "description": "Display name of from_actor, when it is a person or a bot"},
                   to_name={"type": "string", "description": "Display name of to_actor"},
                   body_raw={"type": "string", "description": "A notice the hub wrote, as stored (with actor ids); `body` shows names to people"}),
    "Conversation": obj({"id": "s", "kind": "s", "subject": "s", "participants": items({"type": "string"}),
                         "created": "s", "last_message_at": "s", "closed_at": "n"}),
    "Task": obj({"id": "s", "title": "s", "body": "s", "requester": "s", "owner": "s", "status": "s", "created": "s",
                 "updated": "s", "due": "n", "version": "i", "lane": "s", "labels": items({"type": "string"}),
                 "acceptance_criteria": items({"type": "string"})},
                required=["id", "title", "body", "requester", "owner", "status", "created", "updated", "due", "version", "lane", "labels", "acceptance_criteria"],
                owner_name={"type": "string", "description": "Display name of owner (`owner` stays the actor id)"},
                requester_name={"type": "string", "description": "Display name of requester"}),
    "Person": obj({"id": "s", "name": "s", "email": "s", "title": "s", "team": "s", "reports_to": "n", "org_parent": "s"},
                  required=["id", "name", "org_parent"]),
    "Access": obj({"see": "b", "read": "b", "write": "b"},
                  required=["see", "read", "write"]),
    "OrgBot": obj({"id": "s", "display_name": "s", "description": "s", "team": "s", "reports_to": "n", "org_parent": "s",
                   "owners": items({"type": "string"}), "status": "s", "access": ref("Access")},
                  required=["id", "display_name", "org_parent", "status", "access"]),
    "Bot": obj({"slug": "s", "display_name": "s", "state": "s", "online": "b", "queued": "i", "description": "s",
                "reports_to": "n", "team": "n", "operator": "n", "owners": "a", "status": {"type": ["object", "null"]},
                "access": ref("Access")},
               required=["slug", "display_name", "state", "owners", "access"]),
    "BotDetail": obj({"slug": "s", "display_name": "s", "description": "s", "state": "s", "online": "b", "queued": "i",
                      "status": {"type": ["object", "null"]}, "reports_to": "n", "reports_to_name": "s",
                      "operator": "n", "operator_name": "s", "team": "n", "owners": "a", "goals": "s",
                      "access": ref("Access")},
                     required=["slug", "display_name", "state", "owners", "access"]),
    "Routine": obj({"id": "s", "bot": "s", "key": "n", "title": "s", "cron": "s", "on": "s", "kind": "s",
                    "timezone": "s", "enabled": "b", "text": "s", "last_fired": "n", "next_due": "n",
                    "deleted_at": "n", "updated_at": "n", "active": "b"},
                   required=["id", "bot", "title", "cron", "on", "kind", "timezone", "enabled", "active"]),
    "RoutineList": obj({"routines": items(ref("Routine"))}, required=["routines"]),
    "Audience": obj({"everyone": "b", "people": items({"type": "string"}), "teams": items({"type": "string"}),
                     "bots": items({"type": "string"})}, required=["everyone", "people", "teams", "bots"]),
    "BotAccess": obj({"bot": "s", "see": ref("Audience"), "read": ref("Audience"), "write": ref("Audience"),
                      "revision": "i", "you": ref("Access"), "teams": items({"type": "object"})},
                     required=["bot", "see", "read", "write", "revision"]),
    "Me": obj({"actor": "s", "role": "s", "email": "s"}),
    "Config": obj({"company_name": "s", "app_name": "s", "assistant_name": "s", "assistant_bot": "s",
                   "public_url": "s", "owner_email": "s", "version": "s"}),
    "Org": obj({"people": items(ref("Person")), "bots": items(ref("OrgBot")), "org_groups": "a", "teams": "o"}),
    "BotList": items(ref("Bot")),
    "Recent": obj({"actor": "s", "since": "s", "bots": "a"}),
    "ConversationList": obj({"actor": "s", "conversations": items(ref("Conversation"))},
                            required=["actor", "conversations"], actors=ACTORS),
    "MessagePage": obj({"conversation": ref("Conversation"), "messages": items(ref("Message")), "has_more": "b",
                        "next_before": "n"},
                       required=["conversation", "messages", "has_more", "next_before"], actors=ACTORS),
    "Snapshot": obj({"messages": items(ref("Message")), "has_more": "b", "next_before": "n",
                     "execution": {"type": ["object", "null"], "description": "The latest run: state, label, text (the reply so far), bot"}}),
    "MessageResult": obj({"message": ref("Message")}),
    "ChatResult": obj({"conversation": ref("Conversation"), "message": ref("Message")}),
    "TaskList": obj({"tasks": items(ref("Task")), "next_offset": {"type": ["integer", "null"]}},
                     required=["tasks", "next_offset"], actors=ACTORS),
    "TaskResult": obj({"task": ref("Task")}),
    "TaskDetail": obj({"task": ref("Task"), "events": "a", "children": "a", "comments": items(ref("Message")),
                       "messages": items(ref("Message")), "has_more": "b"},
                       required=["task", "events", "children", "comments", "messages", "has_more"], actors=ACTORS),
    "CommentResult": obj({"comment": ref("Message"), "comments": items(ref("Message")), "woke": "b"}),
    "UpdateList": obj({"updates": "a", "unread": "i", "next_before": "n"}, required=["updates", "unread"]),
    "Unread": obj({"unread": "i"}),
    "NeedsYou": {"oneOf": [obj({"actor": "s", "items": items({
        "type": "object", "required": ["id", "kind", "title"], "additionalProperties": True,
        "properties": {"id": {"type": "string"}, "kind": {"enum": ["task", "question", "declined", "approval"]},
                       "title": {"type": "string"}}})}), obj({"actor": "s", "count": "i"})]},
    "MeetingSearch": obj({"results": "a", "next_offset": {"type": ["integer", "null"]}, "mode": "s"}),
    "DocSearch": obj({"query": "s", "results": "a", "has_more": "b", "mode": "s"}),
    "Health": obj({"audience": "s", "checks": "a", "attention": "i", "checked": "s"}),
    "BotFile": obj({"id": "s", "bot": "s", "title": "s", "kind": "s", "mime": "s", "locator": "s", "scope": "s",
                    "version": "i", "state": "s", "synced": "b", "size": {"type": ["integer", "null"]},
                    "name": "n", "open": {"type": ["object", "null"], "description": "{type: tico|external, url}: "
                                          "a Tico route, or the provider's address; null when nothing can be opened"},
                    "provider": "s", "provider_label": "s", "note": "s", "source": "s", "task_id": "n", "task_title": "n",
                    "working": "b", "github_url": "n", "actor": "n", "action": "n", "first_activity_at": "s",
                    "last_activity_at": "s", "archived": "b"},
                   required=["id", "bot", "title", "kind", "locator", "scope", "version", "state", "synced", "open",
                             "working", "last_activity_at"]),
    "BotFileList": obj({"bot": "s", "files": items(ref("BotFile")), "total": "i", "next_cursor": "n", "has_more": "b",
                        "can_manage": "b"}, required=["bot", "files", "total", "next_cursor", "has_more", "can_manage"],
                       actors=ACTORS),
    "BotFileResult": obj({"file": "o", "created": "b"}, required=["file"]),
    "FileActivity": obj({"file": "s", "activity": "a"}, actors=ACTORS),
    "FileVersions": obj({"file": "s", "versions": "a"}),
    "Assistant": obj({"available": "b", "state": "s", "bot": "s", "name": "s", "can_turn_on": "b", "room_id": "n",
                      "messages": items(ref("Message")), "has_more": "b", "next_before": "n",
                      "execution": {"type": ["object", "null"], "description": "The assistant's current run: state, label, "
                                    "text so far; null when it is not working (show a thinking state while it is)"},
                      "actions": {"type": "object", "description": "{action id: proposal} for every card in `messages` "
                                  "(a message whose refs.action names one is a Confirm / Cancel card)"},
                      "pending": "a"},
                     required=["available", "state", "bot", "name", "can_turn_on", "room_id", "messages", "has_more",
                               "next_before", "execution", "actions", "pending"], actors=ACTORS),
    "AssistantSent": obj({"message": ref("Message"), "reply": {"type": ["object", "null"]}, "fast": "b", "intent": "n"},
                         required=["message", "fast"]),
    "AssistantActionResult": obj({"action": {"type": "object", "description": "id, summary, method, path, body, status "
                                            "(pending, running, done, failed, cancelled, expired), result"}, "message_id": "s"},
                                 required=["action"]),
    "Token": obj({"access_token": "s", "token_type": "s", "expires_in": "i", "idle_timeout": "i", "person": "s"}),
    "Revoked": obj({"revoked": "b"}),
}
ANSWERS = SCHEMAS

# Documentation for the two sign-in routes whose bodies the handlers read by hand.
TOKEN_REQUEST = {"required": True, "content": {"application/json": {"schema": {
    "type": "object", "required": ["code", "code_verifier"], "additionalProperties": False,
    "properties": {"code": {"type": "string", "description": "From the URL fragment: #tico_code=..."},
                   "code_verifier": {"type": "string", "minLength": 43, "maxLength": 128,
                                     "description": "The PKCE verifier whose S256 hash was the code_challenge."}}}}}}

ERROR = {"description": "A problem: {\"error\": {\"code\", \"detail\", \"retryable\", ...}}",
         "content": {"application/json": {"schema": ref("Problem")}}}
PROBLEM = {"type": "object", "required": ["error"], "properties": {"error": {
    "type": "object", "required": ["code", "detail"], "additionalProperties": True,
    "properties": {"code": {"type": "string"}, "detail": {"type": "string"}, "retryable": {"type": "boolean"},
                   "sign_in": {"type": "string", "description": "On a 401 with built-in sign-in: the login path"}}}}}

DESCRIPTION = (
    "The stable API for building your own frontend on Tico. Everything here keeps its shape within v2: fields are added, "
    "never removed or renamed, and a breaking change is a new /api/v3. Routes not listed are internal. "
    "Every write needs an `Idempotency-Key` header (1-200 characters; a retry with the same key and body "
    "returns the first answer). Errors are `{\"error\": {code, detail, retryable}}`. See docs/custom-frontend.md.")


def _refs(node, found):
    if isinstance(node, dict):
        for key, value in node.items():
            if key == "$ref" and isinstance(value, str) and value.startswith("#/components/schemas/"):
                found.add(value.rsplit("/", 1)[1])
            else:
                _refs(value, found)
    elif isinstance(node, list):
        for value in node:
            _refs(value, found)


def spec(app):
    """The v2 document for this app: the stable operations of `app.openapi()`, described."""
    full = copy.deepcopy(app.openapi())
    paths = {}
    for path, method, tag, op_id, summary, answer in STABLE:
        op = (full["paths"].get(path) or {}).get(method)
        if op is None:
            raise RuntimeError("the stable API lists %s %s, which the server does not serve" % (method.upper(), path))
        op["tags"], op["operationId"], op["summary"] = [tag], op_id, summary
        op.pop("description", None)
        responses = {code: r for code, r in op.get("responses", {}).items() if code != "422"}
        if answer:
            responses["200"] = {"description": "OK", "content": {"application/json": {"schema": ref(answer)}}}
        if path.endswith(("/stream", "/watch")):
            events = ("`event: output` (id = cursor) and `event: messages`" if path.endswith("/stream")
                      else "`event: snapshot`, `event: expired`, and `: keepalive` comments")
            responses["200"] = {"description": "text/event-stream: " + events + ". Ends after about a minute; reconnect.",
                                "content": {"text/event-stream": {"schema": {"type": "string"}}}}
        if path.endswith("/versions/{number}"):
            responses["200"] = {"description": "The file's bytes (application/octet-stream, sent as an attachment)",
                                "content": {"application/octet-stream": {"schema": {"type": "string", "format": "binary"}}}}
        if path == "/auth/login":
            responses = {"302": {"description": "Redirect to the identity provider"},
                         "400": {"description": "next is not an allowed origin, or code_challenge is missing"}}
        if path not in ("/healthz", "/auth/login", "/auth/token"):
            responses["401"] = {"description": "Not signed in", **ERROR}
            responses["422"] = {"description": "The request did not validate: {\"detail\": [{\"loc\", \"msg\", \"type\"}]}, "
                                "or a Problem for a rule the server enforces"}
        if path == "/auth/token":
            op["requestBody"] = TOKEN_REQUEST
            op["security"] = []
            responses["400"] = {"description": "invalid_grant, or the request is malformed", **ERROR}
        if path in ("/healthz", "/auth/login"):
            op["security"] = []
        op["responses"] = dict(sorted(responses.items()))
        if method in ("post", "patch") and path.startswith("/api/v2/"):
            op.setdefault("parameters", []).append({
                "name": "Idempotency-Key", "in": "header", "required": True, "schema": {"type": "string"},
                "description": "1-200 characters. Reusing a key with the same body replays the first answer."})
        paths.setdefault(path, {})[method] = op
    used = set()
    _refs(paths, used)
    components = {"Problem": PROBLEM, **SCHEMAS, **full.get("components", {}).get("schemas", {})}
    keep, queue = {}, sorted(used | {"Problem"})
    while queue:
        name = queue.pop()
        if name in keep or name not in components:
            continue
        keep[name] = components[name]
        more = set()
        _refs(components[name], more)
        queue.extend(sorted(more))
    return {
        "openapi": full["openapi"],
        "info": {"title": "Tico API (v2)", "version": VERSION, "description": DESCRIPTION},
        "tags": [{"name": name, "description": text} for name, text in TAGS.items()],
        "paths": dict(sorted(paths.items())),
        "components": {
            "schemas": dict(sorted(keep.items())),
            "securitySchemes": {
                "bearer": {"type": "http", "scheme": "bearer",
                           "description": "A bearer session from POST /auth/token (browser apps) or a personal API token (servers)."},
                "cookie": {"type": "apiKey", "in": "cookie", "name": "tico_session",
                           "description": "The browser session of Tico's own page (`__Host-tico_session` over https)."}}},
        "security": [{"bearer": []}, {"cookie": []}],
    }


def generate():
    """The document for a default installation: what docs/openapi/v2.json holds."""
    import tempfile
    from .app import create_app
    from .config import Settings
    with tempfile.TemporaryDirectory() as tmp:
        return spec(create_app(Settings(db_path=Path(tmp) / "hub.db")))


def render(document):
    return json.dumps(document, indent=2, sort_keys=False) + "\n"


if __name__ == "__main__":
    text = render(generate())
    if "--check" in sys.argv:
        sys.exit(0 if COPY.exists() and COPY.read_text() == text else "docs/openapi/v2.json is stale: python -m backend.openapi_v2")
    COPY.parent.mkdir(parents=True, exist_ok=True)
    COPY.write_text(text)
    print("wrote", COPY)
