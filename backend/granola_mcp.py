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

from .auth import Identity, validate_identity
from .imports import MeetingImport, segments_of
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
        self.locks, self.jobs = weakref.WeakValueDictionary(), {}
        self.registration_lock = asyncio.Lock()
        self.pace_lock = asyncio.Lock()
        self.next_call = 0
        self.starts = {}
        self.revocations = set()

    async def pace(self):
        async with self.pace_lock:
            wait = self.next_call - self.clock()
            if wait > 0:
                await self.sleep(wait)
            self.next_call = self.clock() + 1.05

    @staticmethod
    def seconds(value, default):
        try:
            return max(1, int(value))
        except (ValueError, TypeError, OverflowError):
            return default

    @staticmethod
    def verification(url):
        from urllib.parse import urlsplit
        try:
            parsed = urlsplit(url)
            host = parsed.hostname or ""
            return (parsed.scheme == "https" and (host == "granola.ai" or host.endswith(".granola.ai"))
                    and not parsed.username and not parsed.password)
        except (ValueError, TypeError):
            return False

    def metadata(self, actor):
        with self.store.read() as c:
            row = c.execute("SELECT metadata_json FROM granola_connections WHERE actor=?", (actor,)).fetchone()
        return json.loads(row[0]) if row else {}

    def delete(self, actor):
        with self.store.transaction() as c:
            c.execute("DELETE FROM granola_connections WHERE actor=?", (actor,))

    def eligible(self, who):
        with self.store.read() as c:
            try:
                validate_identity(c, who)
                return True
            except Problem:
                return False

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
        await self.pace()
        try:
            async with httpx.AsyncClient(transport=self.transport, timeout=45, follow_redirects=False) as client:
                async with client.stream(method, url, **kwargs) as response:
                    payload = bytearray()
                    async for chunk in response.aiter_bytes():
                        payload.extend(chunk)
                        if len(payload) > 20_000_000:
                            raise GranolaError("bad_response")
                    # aiter_bytes() already decoded gzip/br: drop the encoding headers or the rebuilt response
                    # decodes the body a second time and fails (Granola gzips every answer).
                    headers = [(k, v) for k, v in response.headers.items()
                               if k.lower() not in ("content-encoding", "content-length", "transfer-encoding")]
                    return httpx.Response(response.status_code, headers=headers, content=bytes(payload),
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
            def read_client():
                with self.store.read() as c:
                    return c.execute("SELECT value_json FROM registry_metadata WHERE key='granola-mcp-client'").fetchone()
            row = await asyncio.to_thread(read_client)
            if row and not rejected:
                return json.loads(row[0])["client_id"]
            response = await self.http("POST", AUTH + "/oauth2/register", json={
                "client_name": "Tico", "token_endpoint_auth_method": "none",
                "grant_types": ["urn:ietf:params:oauth:grant-type:device_code", "refresh_token"],
                # Granola rejects a registration without redirect_uris, even for a device-code client that never
                # redirects ("redirect_uris must be an array"); a loopback address is never used.
                "redirect_uris": ["http://127.0.0.1/callback"]})
            if response.status_code >= 400:
                raise GranolaError()
            client_id = self.payload(response).get("client_id")
            if not isinstance(client_id, str) or not client_id:
                raise GranolaError("bad_response")
            def save_client():
                with self.store.transaction() as c:
                    c.execute("INSERT INTO registry_metadata VALUES('granola-mcp-client',?) ON CONFLICT(key) "
                              "DO UPDATE SET value_json=excluded.value_json", (encode({"client_id": client_id}),))
            await asyncio.to_thread(save_client)
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
            if not all(self.verification(value[k]) for k in ("verification_uri", "verification_uri_complete") if k in value):
                raise GranolaError("bad_response")
            interval = self.seconds(value.get("interval"), 5)
            previous = await asyncio.to_thread(self.load, who.actor)
            meta = {"state": "pending", "expires": now + self.seconds(value["expires_in"], 600), "interval": interval,
                    "next_poll": now + interval, "needs_signin": False, "last_sync": None,
                    "imported_count": 0, "plan_hint": None}
            secret = {"device_code": value["device_code"], "client_id": client_id}
            if previous:
                old_secret = previous[2].get("previous_secret", previous[2])
                if old_secret.get("refresh_token"):
                    secret["previous_secret"] = old_secret
            if previous:
                active_meta = previous[1].get("previous_meta", previous[1])
                if active_meta.get("state") == "connected":
                    meta["previous_meta"] = active_meta
            def store_connection():
                with self.store.transaction() as c:
                    cid = "granola:" + uuid.uuid4().hex
                    ciphertext, nonce = self.app.state.vault.cipher.encrypt(c, cid, encode(secret))
                    c.execute("INSERT INTO granola_connections VALUES(?,?,?,?,?,?) ON CONFLICT(actor) DO UPDATE SET "
                              "id=excluded.id,email=excluded.email,ciphertext=excluded.ciphertext,nonce=excluded.nonce,"
                              "metadata_json=excluded.metadata_json",
                              (who.actor, cid, who.email, ciphertext, nonce, encode(meta)))
            await asyncio.to_thread(store_connection)
            return {k: value[k] for k in ("user_code", "verification_uri", "verification_uri_complete", "expires_in")
                    if k in value} | {"interval": interval, "expires_in": self.seconds(value["expires_in"], 600)}

    def status(self, who):
        # Reading status does not decrypt a token.
        with self.store.read() as c:
            row = c.execute("SELECT email,metadata_json FROM granola_connections WHERE actor=?", (who.actor,)).fetchone()
            api_key = c.execute("SELECT enabled FROM meeting_importers WHERE source='granola'").fetchone()
        meta = json.loads(row["metadata_json"]) if row else {}
        return {"mode": "account" if row else "api_key" if api_key and api_key[0] else "off",
                "connected": meta.get("state") == "connected" or bool(meta.get("previous_meta")), "email": None,
                "plan_hint": meta.get("plan_hint"), "last_sync": meta.get("last_sync"),
                "last_error": meta.get("last_error"), "imported_count": meta.get("imported_count", 0),
                "needs_signin": meta.get("needs_signin", False), "syncing": who.actor in self.jobs,
                "skipped": meta.get("skipped", 0)}

    def failed_signin(self, row, meta, secret):
        meta.update(state="needs_signin", needs_signin=True, last_error="Granola needs sign-in again")
        # Do not keep a rejected access token or device code.
        self.save(row, meta, {"client_id": secret.get("client_id", "")})

    async def poll(self, who):
        async with self.lock(who.actor):
            saved = await asyncio.to_thread(self.load, who.actor)
            if not saved:
                return {"state": "off", **await asyncio.to_thread(self.status, who)}
            row, meta, secret = saved
            revoke_after_save = None
            if meta["state"] != "pending":
                return {"state": meta["state"], **await asyncio.to_thread(self.status, who)}
            now = self.clock()
            if now >= meta["expires"]:
                meta.update(state="expired", last_error="Sign-in expired")
                await asyncio.to_thread(self.save, row, meta, secret if meta.get("previous_meta") else {})
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
                    secret = secret if meta.get("previous_meta") else {}
                elif error in ("invalid_client", "unauthorized_client"):
                    await self.client_id(rejected=True)
                    if meta.get("previous_meta"):
                        meta, secret = meta["previous_meta"], secret["previous_secret"]
                        await asyncio.to_thread(self.save, row, meta, secret)
                        return {"state": meta["state"], **await asyncio.to_thread(self.status, who)}
                    await asyncio.to_thread(self.failed_signin, row, meta, secret)
                    return {"state": "needs_signin", **await asyncio.to_thread(self.status, who)}
                elif response.status_code >= 400 or error:
                    raise GranolaError()
                else:
                    if not value.get("access_token") or not value.get("refresh_token"):
                        raise GranolaError("bad_response")
                    old_secret = secret
                    secret = {"client_id": secret["client_id"], "access_token": value["access_token"],
                              "refresh_token": value["refresh_token"],
                              "expiry": self.clock() + self.seconds(value.get("expires_in"), 3600)}
                    revoke_after_save = old_secret.get("previous_secret", {})
                    meta.pop("previous_meta", None)
                    meta.update(state="connected", needs_signin=False, last_error=None)
                await asyncio.to_thread(self.save, row, meta, secret)
                if revoke_after_save:
                    self.queue_revoke(revoke_after_save)
            if meta["state"] in ("expired", "denied") and meta.get("previous_meta"):
                meta = meta["previous_meta"]
                secret = secret["previous_secret"]
                await asyncio.to_thread(self.save, row, meta, secret)
            return {"state": meta["state"], **await asyncio.to_thread(self.status, who)}

    async def refresh(self, row, meta, secret):
        for attempt in range(2):
            response = await self.http("POST", AUTH + "/oauth2/token", data={
                "grant_type": "refresh_token", "client_id": secret["client_id"],
                "refresh_token": secret["refresh_token"], "resource": MCP})
            if response.status_code == 429:
                raise GranolaError("rate_limited")
            if response.status_code >= 500:
                raise GranolaError("unreachable")
            value = self.payload(response)
            error = value.get("error")
            if response.status_code in (400, 401) and error in ("invalid_grant", "invalid_client", "unauthorized_client"):
                if error != "invalid_grant" and attempt == 0:
                    secret["client_id"] = await self.client_id(rejected=True)
                    continue
                client_id = secret.get("client_id", "")
                secret.clear()
                secret["client_id"] = client_id
                await asyncio.to_thread(self.failed_signin, row, meta, secret)
                raise GranolaError("needs_signin")
            if response.status_code >= 400 or error or not value.get("access_token"):
                raise GranolaError("bad_response")
            secret.update(access_token=value["access_token"], refresh_token=value.get("refresh_token") or secret["refresh_token"],
                          expiry=self.clock() + self.seconds(value.get("expires_in"), 3600))
            await asyncio.to_thread(self.save, row, meta, secret)
            return

    def queue_revoke(self, secret):
        secret = secret.get("previous_secret", secret)
        if secret.get("refresh_token"):
            task = asyncio.create_task(self.revoke(dict(secret)))
            self.revocations.add(task)
            task.add_done_callback(self.revocations.discard)

    async def revoke(self, secret):
        try:
            response = await self.http("GET", AUTH + "/.well-known/oauth-authorization-server")
            endpoint = self.payload(response).get("revocation_endpoint", "")
            if endpoint.startswith(AUTH + "/"):
                await self.http("POST", endpoint, data={"token": secret["refresh_token"],
                                "client_id": secret["client_id"], "token_type_hint": "refresh_token"})
        except Exception:
            pass

    async def disconnect(self, who):
        task = self.jobs.get(who.actor)
        if task:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        async with self.lock(who.actor):
            try:
                saved = await asyncio.to_thread(self.load, who.actor)
            except (Problem, ValueError):
                saved = None
            await asyncio.to_thread(self.delete, who.actor)
            self.starts.pop(who.actor, None)
            if saved:
                self.queue_revoke(saved[2])
        return {"ok": True}

    async def rpc(self, row, meta, secret, session, method, params=None, notification=False):
        if secret.get("expiry", 0) <= self.clock() + 30:
            await self.refresh(row, meta, secret)
        for attempt in range(4):
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
                raise GranolaError("provider_error")
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
                if node.get(key) is not None:
                    row[key] = node.get(key)
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
            return [r if isinstance(r, dict) else {} for r in value]
        if isinstance(value, dict):
            for key in ("meetings", "notes", "results"):
                if isinstance(value.get(key), list):
                    return [r if isinstance(r, dict) else {} for r in value[key]]
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
            who = Identity(actor, "human")
            if not await asyncio.to_thread(self.eligible, who):
                try:
                    saved = await asyncio.to_thread(self.load, actor)
                except Problem:
                    saved = None
                await asyncio.to_thread(self.delete, actor)
                if saved:
                    self.queue_revoke(saved[2])
                return
            saved = await asyncio.to_thread(self.load, actor)
            if not saved:
                return
            row, meta, secret = saved
            if meta["state"] != "connected":
                return
            who = Identity(actor, "human", row["email"])
            meta["last_attempt"] = self.clock()
            await asyncio.to_thread(self.save, row, meta, secret)
            try:
                meta["transcripts_unavailable"] = False
                meta["skipped"] = 0
                transcript_errors = 0
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
                ids, dates = [], {}
                for entry in listed:
                    try:
                        date = moment(entry.get("created_at") or entry.get("date") or entry.get("start_time"))
                        if date and not datetime.fromisoformat(since) <= date <= until:
                            continue
                        nid = entry.get("id") or entry.get("meeting_id") or entry.get("note_id")
                        if not nid:
                            raise ValueError()
                        ids.append(str(nid))
                        dates[str(nid)] = date or datetime.fromisoformat(since)
                    except Exception:
                        meta["skipped"] += 1
                ids = sorted(dict.fromkeys(ids), key=dates.get)
                if len(ids) > 5000:
                    raise GranolaError("import_limit")
                id_properties = (tools["get_meetings"].get("inputSchema") or {}).get("properties", {})
                batch_size = max(1, min([20] + [v["maxItems"] for k, v in id_properties.items()
                                                if k in ("meeting_ids", "ids", "note_ids") and isinstance(v.get("maxItems"), int)]))
                for offset in range(0, len(ids), batch_size):
                    batch = ids[offset:offset + batch_size]
                    try:
                        value = await self.call(row, meta, secret, session, tools["get_meetings"],
                                                {"meeting_ids": batch, "ids": batch, "note_ids": batch})
                        notes = self.rows(value)
                    except GranolaError as exc:
                        if exc.code in ("unreachable", "rate_limited", "needs_signin"):
                            raise
                        # A bad ID must not hide the other meetings in its batch.
                        notes = []
                        for nid in batch:
                            try:
                                value = await self.call(row, meta, secret, session, tools["get_meetings"],
                                                        {"meeting_ids": [nid], "ids": [nid], "note_ids": [nid]})
                                notes.extend(self.rows(value))
                            except GranolaError as exc:
                                if exc.code in ("unreachable", "rate_limited", "needs_signin"):
                                    raise
                                meta["skipped"] += 1
                    for note in notes:
                        transcript = ""
                        nid = note.get("id") or note.get("meeting_id") or note.get("note_id")
                        if "get_meeting_transcript" in tools and not meta.get("transcripts_unavailable"):
                            try:
                                data = await self.call(row, meta, secret, session, tools["get_meeting_transcript"],
                                                       {"meeting_id": nid, "id": nid, "note_id": nid})
                                transcript = data.get("transcript", "") if isinstance(data, dict) else data if isinstance(data, (list, str)) else ""
                                segments_of(MeetingImport(transcript=transcript))
                                transcript_errors = 0
                            except Exception:
                                transcript = ""
                                transcript_errors += 1
                                if transcript_errors >= 3:
                                    meta["transcripts_unavailable"] = True
                                meta["plan_hint"] = "free"
                        try:
                            item = self.item(note, transcript)
                            if item:
                                def file_item():
                                    with self.store.transaction() as c:
                                        validate_identity(c, who)
                                        result = self.app.state.import_meeting(c, who, item, [], fill_empty=True)
                                        if not result["existing"]:
                                            meta["imported_count"] = meta.get("imported_count", 0) + 1
                                # A worker transaction must finish before cancellation releases the person lock.
                                worker = asyncio.create_task(asyncio.to_thread(file_item))
                                try:
                                    await asyncio.shield(worker)
                                except asyncio.CancelledError:
                                    await worker
                                    raise
                        except Exception:
                            meta["skipped"] += 1
                        await asyncio.to_thread(self.save, row, meta, secret)
                    # IDs are processed by list date, so this checkpoint cannot pass an unprocessed batch.
                    checkpoint = max(dates[nid] for nid in batch)
                    if not meta.get("cursor") or checkpoint > datetime.fromisoformat(meta["cursor"]):
                        meta["cursor"] = checkpoint.isoformat()
                    await asyncio.to_thread(self.save, row, meta, secret)
                if meta.get("state") == "needs_signin":
                    return
                meta["failures"] = 0
                meta.pop("retry_after", None)
                meta.update(last_sync=H.now(), last_finished=self.clock(), cursor=until.isoformat(),
                            last_error=f"{meta['skipped']} notes skipped" if meta["skipped"] else None)
            except GranolaError as exc:
                if exc.code == "needs_signin":
                    return
                meta["last_error"] = "Granola sync: " + exc.code
                meta["failures"] = min(meta.get("failures", 0) + 1, 4)
                meta["retry_after"] = self.clock() + SCHEDULE * 2 ** (meta["failures"] - 1)
            except Exception:
                # In particular never persist validation errors containing provider data.
                meta["last_error"] = "Granola sync failed; retry or reconnect in Meetings"
            await asyncio.to_thread(self.save, row, meta, secret)

    async def trigger(self, who, interval=DEBOUNCE):
        if not await asyncio.to_thread(self.eligible, who):
            await self.disconnect(who)
            return {"state": "off", "last_sync": None}
        status = await asyncio.to_thread(self.status, who)
        if who.actor in self.jobs:
            return {"state": "syncing", "last_sync": status["last_sync"]}
        meta = await asyncio.to_thread(self.metadata, who.actor)
        if meta.get("previous_meta") and self.clock() >= meta.get("expires", 0):
            await self.poll(who)
            meta = await asyncio.to_thread(self.metadata, who.actor)
        if not meta or meta["state"] != "connected":
            return {"state": "needs_signin" if status["needs_signin"] else "off", "last_sync": status["last_sync"]}
        if self.clock() - max(meta.get("last_attempt", 0), meta.get("last_finished", 0)) < interval:
            return {"state": "recent", "last_sync": status["last_sync"]}
        if who.actor in self.jobs:
            return {"state": "syncing", "last_sync": status["last_sync"]}
        if interval == SCHEDULE and self.clock() < meta.get("retry_after", 0):
            return {"state": "recent", "last_sync": status["last_sync"]}
        def record_failure():
            with self.store.transaction() as c:
                row = c.execute("SELECT metadata_json FROM granola_connections WHERE actor=?", (who.actor,)).fetchone()
                if row:
                    meta = json.loads(row[0])
                    meta.update(last_attempt=self.clock(), last_error="Granola sync failed; check Credential encryption in Health")
                    c.execute("UPDATE granola_connections SET metadata_json=? WHERE actor=?", (encode(meta), who.actor))
        async def run():
            try:
                await self.sync(who.actor)
            except asyncio.CancelledError:
                raise
            except Exception:
                await asyncio.to_thread(record_failure)
        task = asyncio.create_task(run())
        self.jobs[who.actor] = task
        def finished(task):
            if self.jobs.get(who.actor) is task:
                self.jobs.pop(who.actor, None)
        task.add_done_callback(finished)
        return {"state": "syncing", "last_sync": status["last_sync"]}

    async def tick(self):
        def connections():
            with self.store.read() as c:
                return [dict(r) for r in c.execute("SELECT actor,email FROM granola_connections")]
        rows = await asyncio.to_thread(connections)
        active = {row["actor"] for row in rows}
        self.starts = {actor: value for actor, value in self.starts.items() if actor in active}
        for index, row in enumerate(rows):
            try:
                start = self.starts.setdefault(row["actor"], self.clock() + index * 5)
                if self.clock() >= start:
                    await self.trigger(Identity(row["actor"], "human", row["email"]), SCHEDULE)
            except Exception:
                continue

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
        for task in list(self.jobs.values()) + list(self.revocations):
            task.cancel()
        await asyncio.gather(*list(self.jobs.values()), *list(self.revocations), return_exceptions=True)


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
        return await service.trigger(person(request))
