"""Person-owned Granola OAuth and remote MCP. No provider payload reaches diagnostics.

Tokens and pending device codes are encrypted with the credential vault's cipher in a
separate store without reveal, grant, runner or SQL access. HTTP work runs outside transactions.
"""
import asyncio
import json
import time
import uuid
import weakref
from datetime import datetime, timedelta, timezone

import httpx
from fastapi import Request

from .auth import Identity
from .imports import MeetingImport
from .store import H, Problem, encode

MCP = "https://mcp.granola.ai/mcp"
AUTH = "https://mcp-auth.granola.ai"
SCOPES = "openid profile email offline_access mcp"
SCHEDULE = 25 * 60
DEBOUNCE = 120


class GranolaError(Exception):
    def __init__(self, code="provider_error"):
        self.code = code
        super().__init__(code)


class GranolaMCP:
    def __init__(self, app):
        self.app, self.store = app, app.state.store
        self.transport = None                 # MockTransport in tests; never an API setting
        self.clock = time.time
        self.sleep = asyncio.sleep
        self.locks, self.jobs, self.paced = weakref.WeakValueDictionary(), {}, {}
        self.registration_lock = asyncio.Lock()

    def lock(self, actor):
        return self.locks.setdefault(actor, asyncio.Lock())

    def load(self, actor):
        with self.store.transaction() as c:
            row = c.execute("SELECT * FROM granola_connections WHERE actor=?", (actor,)).fetchone()
            if not row:
                return None
            return dict(row), json.loads(row["metadata_json"]), json.loads(self.app.state.vault.cipher.decrypt(c, row))

    def save(self, row, meta, secret):
        with self.store.transaction() as c:
            ciphertext, nonce = self.app.state.vault.cipher.encrypt(c, row["id"], encode(secret))
            # A disconnect/reconnect invalidates every in-flight operation from the previous connection.
            c.execute("UPDATE granola_connections SET ciphertext=?,nonce=?,metadata_json=? WHERE actor=? AND id=?",
                      (ciphertext, nonce, encode(meta), row["actor"], row["id"]))

    async def http(self, method, url, **kwargs):
        try:
            async with httpx.AsyncClient(transport=self.transport, timeout=45, follow_redirects=False) as client:
                async with client.stream(method, url, **kwargs) as response:
                    payload = bytearray()
                    async for chunk in response.aiter_bytes():
                        payload.extend(chunk)
                        if len(payload) > 20_000_000:
                            raise GranolaError("bad_response")
                    return httpx.Response(response.status_code, headers=response.headers, content=bytes(payload),
                                          request=response.request)
        except httpx.HTTPError:
            raise GranolaError("unreachable") from None

    @staticmethod
    def payload(response):
        try:
            value = response.json()
            if not isinstance(value, dict):
                raise ValueError()
            return value
        except ValueError:
            raise GranolaError("bad_response") from None

    async def client_id(self, rejected=False):
        async with self.registration_lock:
            with self.store.read() as c:
                row = c.execute("SELECT value_json FROM registry_metadata WHERE key='granola-mcp-client'").fetchone()
            if row and not rejected:
                return json.loads(row[0])["client_id"]
            response = await self.http("POST", AUTH + "/oauth2/register", json={
                "client_name": "Tico", "token_endpoint_auth_method": "none",
                "grant_types": ["urn:ietf:params:oauth:grant-type:device_code", "refresh_token"],
                "response_types": []})
            if response.status_code >= 400:
                raise GranolaError()
            client_id = self.payload(response).get("client_id")
            if not isinstance(client_id, str) or not client_id:
                raise GranolaError("bad_response")
            with self.store.transaction() as c:
                c.execute("INSERT INTO registry_metadata VALUES('granola-mcp-client',?) ON CONFLICT(key) "
                          "DO UPDATE SET value_json=excluded.value_json", (encode({"client_id": client_id}),))
            return client_id

    async def connect(self, who):
        async with self.lock(who.actor):
            client_id = await self.client_id()
            for attempt in range(2):
                response = await self.http("POST", AUTH + "/oauth2/device_authorization", data={
                    "client_id": client_id, "scope": SCOPES, "resource": MCP})
                value = self.payload(response)
                if value.get("error") in ("invalid_client", "unauthorized_client") and attempt == 0:
                    client_id = await self.client_id(rejected=True)
                    continue
                if response.status_code >= 400 or value.get("error"):
                    raise GranolaError()
                break
            if not all(value.get(k) for k in ("device_code", "user_code", "verification_uri", "expires_in")):
                raise GranolaError("bad_response")
            now = self.clock()
            interval = max(1, int(value.get("interval", 5)))
            previous = self.load(who.actor)
            meta = {"state": "pending", "expires": now + int(value["expires_in"]), "interval": interval,
                    "next_poll": now + interval, "needs_signin": False, "last_sync": None,
                    "imported_count": 0, "plan_hint": None}
            if previous:
                meta.update({k: previous[1][k] for k in ("cursor", "last_sync", "last_attempt", "last_finished", "imported_count", "plan_hint")
                             if k in previous[1]})
            secret = {"device_code": value["device_code"], "client_id": client_id}
            with self.store.transaction() as c:
                cid = "granola:" + uuid.uuid4().hex
                ciphertext, nonce = self.app.state.vault.cipher.encrypt(c, cid, encode(secret))
                c.execute("INSERT INTO granola_connections VALUES(?,?,?,?,?,?) ON CONFLICT(actor) DO UPDATE SET "
                          "id=excluded.id,email=excluded.email,ciphertext=excluded.ciphertext,nonce=excluded.nonce,"
                          "metadata_json=excluded.metadata_json",
                          (who.actor, cid, who.email, ciphertext, nonce, encode(meta)))
            return {k: value[k] for k in ("user_code", "verification_uri", "verification_uri_complete", "expires_in")
                    if k in value} | {"interval": interval}

    def status(self, who):
        # Reading status does not decrypt a token.
        with self.store.read() as c:
            row = c.execute("SELECT email,metadata_json FROM granola_connections WHERE actor=?", (who.actor,)).fetchone()
            api_key = c.execute("SELECT enabled FROM meeting_importers WHERE source='granola'").fetchone()
        meta = json.loads(row["metadata_json"]) if row else {}
        return {"mode": "account" if row else "api_key" if api_key and api_key[0] else "off",
                "connected": meta.get("state") == "connected", "email": row["email"] if row else None,
                "plan_hint": meta.get("plan_hint"), "last_sync": meta.get("last_sync"),
                "last_error": meta.get("last_error"), "imported_count": meta.get("imported_count", 0),
                "needs_signin": meta.get("needs_signin", False)}

    def failed_signin(self, row, meta, secret):
        meta.update(state="needs_signin", needs_signin=True, last_error="Granola needs sign-in again")
        # Do not keep a rejected access token or device code.
        self.save(row, meta, {"client_id": secret.get("client_id", "")})

    async def poll(self, who):
        async with self.lock(who.actor):
            saved = self.load(who.actor)
            if not saved:
                return {"state": "off", **self.status(who)}
            row, meta, secret = saved
            if meta["state"] != "pending":
                return {"state": meta["state"], **self.status(who)}
            now = self.clock()
            if now >= meta["expires"]:
                meta.update(state="expired", last_error="Sign-in expired")
                self.save(row, meta, {})
            elif now >= meta["next_poll"]:
                response = await self.http("POST", AUTH + "/oauth2/token", data={
                    "grant_type": "urn:ietf:params:oauth:grant-type:device_code", "client_id": secret["client_id"],
                    "device_code": secret["device_code"], "resource": MCP})
                value = self.payload(response)
                error = value.get("error")
                if error in ("authorization_pending", "slow_down"):
                    if error == "slow_down":
                        meta["interval"] += 5
                    meta["next_poll"] = self.clock() + meta["interval"]
                elif error in ("expired_token", "access_denied"):
                    meta.update(state="expired" if error == "expired_token" else "denied",
                                last_error="Sign-in expired" if error == "expired_token" else "Sign-in declined")
                    secret = {}
                elif error in ("invalid_client", "unauthorized_client"):
                    await self.client_id(rejected=True)
                    self.failed_signin(row, meta, secret)
                    return {"state": "needs_signin", **self.status(who)}
                elif response.status_code >= 400 or error:
                    raise GranolaError()
                else:
                    if not value.get("access_token") or not value.get("refresh_token"):
                        raise GranolaError("bad_response")
                    secret = {"client_id": secret["client_id"], "access_token": value["access_token"],
                              "refresh_token": value["refresh_token"],
                              "expiry": self.clock() + int(value.get("expires_in", 3600))}
                    meta.update(state="connected", needs_signin=False, last_error=None)
                self.save(row, meta, secret)
            return {"state": meta["state"], **self.status(who)}

    async def refresh(self, row, meta, secret):
        try:
            response = await self.http("POST", AUTH + "/oauth2/token", data={
                "grant_type": "refresh_token", "client_id": secret["client_id"],
                "refresh_token": secret["refresh_token"], "resource": MCP})
            value = self.payload(response)
            if response.status_code >= 400 or not value.get("access_token"):
                if value.get("error") in ("invalid_client", "unauthorized_client"):
                    await self.client_id(rejected=True)
                raise GranolaError("needs_signin")
            secret.update(access_token=value["access_token"], refresh_token=value.get("refresh_token") or secret["refresh_token"],
                          expiry=self.clock() + int(value.get("expires_in", 3600)))
            self.save(row, meta, secret)
        except GranolaError:
            self.failed_signin(row, meta, secret)
            raise GranolaError("needs_signin") from None

    async def disconnect(self, who):
        # Wait for any import to finish, so none can commit after disconnect returns.
        async with self.lock(who.actor):
            try:
                saved = self.load(who.actor)
            except Problem:
                saved = None  # A missing vault key must not prevent disconnecting.
            with self.store.transaction() as c:
                c.execute("DELETE FROM granola_connections WHERE actor=?", (who.actor,))
            self.paced.pop(who.actor, None)
            if saved:
                _, _, secret = saved
                # Only a discovered, trusted HTTPS revocation endpoint may receive a token.
                try:
                    response = await self.http("GET", AUTH + "/.well-known/oauth-authorization-server")
                    endpoint = self.payload(response).get("revocation_endpoint", "")
                    if endpoint.startswith(AUTH + "/") and secret.get("refresh_token"):
                        await self.http("POST", endpoint, data={"token": secret["refresh_token"],
                                        "client_id": secret["client_id"], "token_type_hint": "refresh_token"})
                except GranolaError:
                    pass                 # Local deletion succeeds even when revocation is unavailable.
        return {"ok": True}

    async def rpc(self, row, meta, secret, session, method, params=None, notification=False):
        if secret.get("expiry", 0) <= self.clock() + 30:
            await self.refresh(row, meta, secret)
        for attempt in range(4):
            wait = self.paced.get(row["actor"], 0) - self.clock()
            if wait > 0:
                await self.sleep(wait)
            self.paced[row["actor"]] = self.clock() + 1.05
            headers = {"Authorization": "Bearer " + secret["access_token"],
                       "Accept": "application/json, text/event-stream", "MCP-Protocol-Version": session.get("version", "2025-03-26")}
            if session.get("id"):
                headers["Mcp-Session-Id"] = session["id"]
            body = {"jsonrpc": "2.0", "method": method, "params": params or {}}
            if not notification:
                body["id"] = uuid.uuid4().hex
            response = await self.http("POST", MCP, headers=headers, json=body)
            if response.status_code == 401 and not session.get("refreshed"):
                session["refreshed"] = True
                await self.refresh(row, meta, secret)
                continue
            if response.status_code == 429:
                try:
                    delay = float(response.headers.get("Retry-After", 2 ** (attempt + 1)))
                except ValueError:
                    delay = 2 ** (attempt + 1)
                await self.sleep(max(1, min(delay, 120)))
                continue
            if response.status_code == 403:
                raise GranolaError("forbidden")
            if response.status_code >= 400:
                raise GranolaError("needs_signin" if response.status_code == 401 else "provider_error")
            if response.headers.get("Mcp-Session-Id"):
                session["id"] = response.headers["Mcp-Session-Id"]
            if notification:
                return {}
            if "text/event-stream" in response.headers.get("content-type", ""):
                value = None
                for event in response.text.replace("\r\n", "\n").split("\n\n"):
                    data = "\n".join(line[5:].lstrip() for line in event.splitlines() if line.startswith("data:"))
                    if data:
                        try:
                            candidate = json.loads(data)
                            if candidate.get("id") == body["id"]:
                                value = candidate
                                break
                        except (ValueError, AttributeError):
                            pass
                if not isinstance(value, dict):
                    raise GranolaError("bad_response")
            else:
                value = self.payload(response)
            if value.get("error"):
                error = value["error"]
                code = error.get("code") if isinstance(error, dict) else None
                raise GranolaError("forbidden" if code in (403, -32003) else "provider_error")
            result = value.get("result", {})
            if result.get("isError"):
                # Read only to classify; never save/return/log the tool's free-form error message.
                message = encode(result).lower()
                raise GranolaError("forbidden" if any(word in message for word in
                                   ("permission", "paid", "upgrade", "forbidden", "not authorized", "access denied"))
                                   else "provider_error")
            return result
        raise GranolaError("rate_limited")

    @staticmethod
    def content(result, allow_text=False):
        if isinstance(result.get("structuredContent"), (dict, list)):
            return result["structuredContent"]
        for block in result.get("content", []):
            if block.get("type") == "text":
                try:
                    return json.loads(block.get("text", ""))
                except ValueError:
                    raw = block.get("text", "")
                    if raw.lstrip().startswith("<"):
                        parsed = GranolaMCP.xml_content(raw)
                        if parsed is not None:
                            return parsed
                    if allow_text:
                        return {"transcript": raw}
        raise GranolaError("bad_response")

    @staticmethod
    def xml_content(raw):
        """Some MCP tools return XML text. Read only known shared fields; discard private notes."""
        from xml.etree import ElementTree as ET
        if "<!DOCTYPE" in raw.upper() or "<!ENTITY" in raw.upper():
            raise GranolaError("bad_response")
        try:
            root = ET.fromstring(raw)
        except ET.ParseError:
            return None
        rows = [root] if root.tag in ("meeting", "note") else list(root.iter("meeting")) + list(root.iter("note"))
        out = []
        for node in rows:
            row = {"id": node.get("id") or node.get("meeting_id")}
            for key in ("id", "meeting_id", "note_id", "title", "date", "created_at", "start_time", "summary_markdown",
                        "summary_text", "ai_summary", "enhanced_notes", "summary", "web_url"):
                field = node.find(key)
                if field is not None:
                    row[key] = "".join(field.itertext()).strip()
            row["attendees"] = [{"name": a.get("name") or a.findtext("name") or (a.text or "").strip(),
                                 "email": a.get("email") or a.findtext("email") or ""}
                                for a in node.findall("./attendees/attendee")]
            out.append(row)
        if out:
            return {"meetings": out, "next_cursor": root.findtext("next_cursor")}
        if root.tag == "transcript":
            return {"transcript": "".join(root.itertext()).strip()}
        return None

    @staticmethod
    def arguments(tool, values):
        schema = tool.get("inputSchema") or {}
        properties = schema.get("properties") or {}
        out = {}
        for key, value in values.items():
            if key not in properties:
                continue
            spec = properties[key]
            if spec.get("format") == "date" and isinstance(value, str):
                value = value[:10]
            if spec.get("enum") and value not in spec["enum"]:
                if key in ("date_range", "time_range") and "custom" in spec["enum"]:
                    value = "custom"
                elif key in ("date_range", "time_range") and "last_30_days" in spec["enum"]:
                    value = "last_30_days"
                else:
                    continue
            if spec.get("type") == "object" and isinstance(value, dict) and spec.get("properties"):
                value = {k: v for k, v in value.items() if k in spec["properties"]}
            out[key] = value
        # Exact schemas are discovered at runtime; unsupported required fields fail safely.
        if any(k not in out for k in schema.get("required", [])):
            raise GranolaError("unsupported_schema")
        return out

    async def call(self, row, meta, secret, session, tool, values):
        return self.content(await self.rpc(row, meta, secret, session, "tools/call", {
            "name": tool["name"], "arguments": self.arguments(tool, values)}), allow_text=tool["name"] == "get_meeting_transcript")

    @staticmethod
    def rows(value):
        if isinstance(value, list):
            return [r for r in value if isinstance(r, dict)]
        if isinstance(value, dict):
            for key in ("meetings", "notes", "results"):
                if isinstance(value.get(key), list):
                    return [r for r in value[key] if isinstance(r, dict)]
            if value.get("id") or value.get("meeting_id"):
                return [value]
        raise GranolaError("bad_response")

    @staticmethod
    def item(note, transcript=""):
        # Do not use private_notes, raw_notes or note-taker notes. Only shared/AI summaries.
        summary = note.get("summary_markdown") or note.get("summary_text") or note.get("ai_summary") or note.get("enhanced_notes") or note.get("summary") or ""
        if isinstance(summary, dict):
            summary = summary.get("markdown") or summary.get("text") or ""
        notes = note.get("notes")
        if not summary and isinstance(notes, dict):
            summary = notes.get("summary") or notes.get("ai_summary") or ""
        external_id = note.get("note_id") or note.get("id") or note.get("meeting_id")
        if not external_id:
            raise GranolaError("bad_response")
        from runner.importers.base import moment, people, text, https_url
        attendees = note.get("attendees") or note.get("participants") or []
        participants = people(*[(a.get("name", ""), a.get("email", "")) if isinstance(a, dict) else str(a)
                                for a in attendees])
        started = moment(note.get("created_at") or note.get("date") or note.get("start_time"))
        return MeetingImport(source="granola", external_id=str(external_id), private=True,
                             title=text(note.get("title"), 300) or "Granola meeting",
                             started_at=started.isoformat() if started else None, participants=participants,
                             notes=str(summary).strip()[:200_000], transcript=transcript,
                             media_url=https_url(note.get("web_url"))) if summary or transcript else None

    async def sync(self, actor):
        async with self.lock(actor):
            saved = self.load(actor)
            if not saved:
                return
            row, meta, secret = saved
            if meta["state"] != "connected":
                return
            meta["last_attempt"] = self.clock()
            self.save(row, meta, secret)
            try:
                session = {}
                initialized = await self.rpc(row, meta, secret, session, "initialize", {
                    "protocolVersion": "2025-03-26", "capabilities": {}, "clientInfo": {"name": "Tico", "version": "0.3.2"}})
                session["version"] = initialized.get("protocolVersion", "2025-03-26")
                await self.rpc(row, meta, secret, session, "notifications/initialized", notification=True)
                tools, cursor = {}, None
                for _ in range(20):
                    page = await self.rpc(row, meta, secret, session, "tools/list", {"cursor": cursor} if cursor else {})
                    tools.update({t["name"]: t for t in page.get("tools", []) if isinstance(t, dict) and "name" in t})
                    cursor = page.get("nextCursor")
                    if not cursor:
                        break
                else:
                    raise GranolaError("import_limit")
                if not all(name in tools for name in ("list_meetings", "get_meetings")):
                    raise GranolaError("feature_unavailable")
                meta["plan_hint"] = "paid" if "get_meeting_transcript" in tools or "list_meeting_folders" in tools else "free"
                until = datetime.fromtimestamp(self.clock(), timezone.utc)
                since = meta.get("cursor") or (until - timedelta(days=30)).isoformat()
                if meta.get("cursor"):
                    # Revisit recent notes because summaries arrive after a meeting finishes.
                    since = (datetime.fromisoformat(since) - timedelta(hours=72)).isoformat()
                if meta["plan_hint"] == "free":
                    since = max(datetime.fromisoformat(since), until - timedelta(days=30)).isoformat()
                cursor, listed = None, []
                for _ in range(100):
                    value = await self.call(row, meta, secret, session, tools["list_meetings"], {
                        "since": since, "start_date": since, "after": since, "created_after": since,
                        "end_date": until.isoformat(), "until": until.isoformat(), "before": until.isoformat(),
                        "time_range": "custom", "custom_start": since, "custom_end": until.isoformat(),
                        "date_range": {"start": since, "end": until.isoformat(), "start_date": since,
                                       "end_date": until.isoformat(), "from": since, "to": until.isoformat()},
                        "involvement": {"captured_by_me": True}, "captured_by_me": True,
                        "cursor": cursor or "", "page_size": 50, "limit": 50})
                    listed.extend(self.rows(value))
                    cursor = (value.get("next_cursor") or value.get("nextCursor") or value.get("cursor")) if isinstance(value, dict) else None
                    if not cursor:
                        break
                else:
                    raise GranolaError("import_limit")
                from runner.importers.base import moment
                listed = [r for r in listed if not (date := moment(r.get("created_at") or r.get("date") or r.get("start_time")))
                          or datetime.fromisoformat(since) <= date <= until]
                ids = list(dict.fromkeys(str(r.get("id") or r.get("meeting_id") or r.get("note_id") or "") for r in listed))
                ids = [i for i in ids if i]
                if len(ids) > 5000:
                    raise GranolaError("import_limit")
                who = Identity(actor, "human", row["email"])
                id_properties = (tools["get_meetings"].get("inputSchema") or {}).get("properties", {})
                batch_size = max(1, min([20] + [v["maxItems"] for k, v in id_properties.items()
                                                if k in ("meeting_ids", "ids", "note_ids") and isinstance(v.get("maxItems"), int)]))
                for offset in range(0, len(ids), batch_size):
                    batch = ids[offset:offset + batch_size]
                    value = await self.call(row, meta, secret, session, tools["get_meetings"],
                                            {"meeting_ids": batch, "ids": batch, "note_ids": batch})
                    for note in self.rows(value):
                        transcript = ""
                        nid = note.get("id") or note.get("meeting_id") or note.get("note_id")
                        if "get_meeting_transcript" in tools and not meta.get("transcripts_unavailable"):
                            try:
                                data = await self.call(row, meta, secret, session, tools["get_meeting_transcript"],
                                                       {"meeting_id": nid, "id": nid, "note_id": nid})
                                transcript = data.get("transcript", "") if isinstance(data, dict) else data if isinstance(data, (list, str)) else ""
                            except GranolaError as exc:
                                if exc.code != "forbidden":
                                    raise
                                meta["transcripts_unavailable"] = True
                                meta["plan_hint"] = "free"
                        item = self.item(note, transcript)
                        if item:
                            def file_item():
                                with self.store.transaction() as c:
                                    result = self.app.state.import_meeting(c, who, item, [])
                                    if not result["existing"]:
                                        meta["imported_count"] = meta.get("imported_count", 0) + 1
                                    ciphertext, nonce = self.app.state.vault.cipher.encrypt(c, row["id"], encode(secret))
                                    c.execute("UPDATE granola_connections SET metadata_json=?,ciphertext=?,nonce=? WHERE actor=? AND id=?",
                                              (encode(meta), ciphertext, nonce, actor, row["id"]))
                            await asyncio.to_thread(file_item)
                meta.update(last_sync=H.now(), last_finished=self.clock(), cursor=until.isoformat(), last_error=None)
            except GranolaError as exc:
                if exc.code == "needs_signin":
                    self.failed_signin(row, meta, secret)
                    return
                meta["last_error"] = "Granola sync: " + exc.code
            except Exception:
                # In particular never persist validation errors containing provider data.
                meta["last_error"] = "Granola sync failed; retry or reconnect in Meetings"
            self.save(row, meta, secret)

    def trigger(self, who, interval=DEBOUNCE):
        status = self.status(who)
        if who.actor in self.jobs:
            return {"state": "syncing", "last_sync": status["last_sync"]}
        saved = self.load(who.actor)
        if not saved or saved[1]["state"] != "connected":
            return {"state": "needs_signin" if status["needs_signin"] else "off", "last_sync": status["last_sync"]}
        if self.clock() - max(saved[1].get("last_attempt", 0), saved[1].get("last_finished", 0)) < interval:
            return {"state": "recent", "last_sync": status["last_sync"]}
        task = asyncio.create_task(self.sync(who.actor))
        self.jobs[who.actor] = task
        def finished(task):
            self.jobs.pop(who.actor, None)
            if not task.cancelled() and task.exception() is not None:
                with self.store.transaction() as c:
                    row = c.execute("SELECT metadata_json FROM granola_connections WHERE actor=?", (who.actor,)).fetchone()
                    if row:
                        meta = json.loads(row[0])
                        meta.update(last_attempt=self.clock(), last_error="Granola sync failed; check Credential encryption in Health")
                        c.execute("UPDATE granola_connections SET metadata_json=? WHERE actor=?", (encode(meta), who.actor))
        task.add_done_callback(finished)
        return {"state": "syncing", "last_sync": status["last_sync"]}

    async def tick(self):
        with self.store.read() as c:
            rows = [dict(r) for r in c.execute("SELECT actor,email FROM granola_connections")]
        active = {row["actor"] for row in rows}
        self.paced = {actor: value for actor, value in self.paced.items() if actor in active}
        for row in rows:
            self.trigger(Identity(row["actor"], "human", row["email"]), SCHEDULE)

    async def loop(self, stop):
        while not stop.is_set():
            try:
                await self.tick()
            except Exception:
                pass
            try:
                await asyncio.wait_for(stop.wait(), timeout=30)
            except TimeoutError:
                pass
        await self.close()

    async def close(self):
        for task in list(self.jobs.values()):
            task.cancel()
        await asyncio.gather(*list(self.jobs.values()), return_exceptions=True)


def install_granola(app):
    service = app.state.granola = GranolaMCP(app)

    def person(request):
        who = request.state.identity
        if who.role not in ("human", "owner"):
            raise Problem("forbidden", "Open Meetings in your browser to connect your own Granola account", 403)
        return who

    async def safe(operation):
        try:
            return await operation
        except GranolaError as exc:
            raise Problem("granola_unavailable", "Granola: " + exc.code, 503) from None

    @app.get("/api/v2/meetings/granola")
    def status(request: Request):
        return service.status(person(request))

    @app.post("/api/v2/meetings/granola/connect")
    async def connect(request: Request):
        return await safe(service.connect(person(request)))

    @app.get("/api/v2/meetings/granola/connect/status")
    async def poll(request: Request):
        return await safe(service.poll(person(request)))

    @app.delete("/api/v2/meetings/granola/connect")
    async def disconnect(request: Request):
        return await safe(service.disconnect(person(request)))

    @app.post("/api/v2/meetings/granola/sync")
    async def sync(request: Request):
        return service.trigger(person(request))
