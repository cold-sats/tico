"""Grok Bot sync: a person's Grok Bots (xAI's cloud agents) as bots on the Org chart.

Grok Bot has no API, export or webhook for its Bots. What it does have is a Bot on the person's
own account that can list their other Bots, read each one's full instructions and transcripts,
and call a custom MCP server on a routine. So the person connects the hub's MCP with their own
personal token and gives one of their Bots a routine that calls `hub_grokbot_sync` with the Bots
they want kept (docs/grok-bot-sync.md). The hub does the rest here:

- A Grok Bot it has not seen becomes a bot with the `grokbot` harness, placed under the person
  who synced it (`reports_to: human:<them>`). They may move it anywhere on the chart afterwards;
  a later sync never moves it back.
- Its name and description follow Grok; its full instructions are kept in `config_json.grok`,
  so the bot can be rebuilt somewhere else if the Grok account goes away.
- Its transcript is copied into the syncing person's own room with the bot, read and quiet
  (no job, no unread badge). A message's id is derived from the Grok Bot and the message, so
  sending the same messages again adds nothing.

Nothing is dispatched to these bots: `grokbot` is an external harness, so a message written
here waits in the bot's inbox, and presence is "last synced" rather than a heartbeat.
"""

import base64
import binascii
import hashlib
import ipaddress
import mimetypes
import re
import socket
import uuid
from urllib.parse import urljoin, urlsplit

import httpx
from pydantic import Field

from . import models as M
from . import rooms
from .blobs import register
from .store import H, Problem, encode

HARNESS = "grokbot"
MODEL = "grokbot-own"
# A routine runs on a schedule of days, not minutes: a bot synced within the last day and a bit
# is reporting in.
PRESENCE_GAP = 26 * 60 * 60
NAMESPACE = uuid.UUID("5b0c7f1e-8d0a-4c55-9d0b-6f3a1c2e9a41")


IMAGE_BYTES = 10_000_000
IMAGE_TIMEOUT = 20
IMAGE_REDIRECTS = 3


class GrokImage(M.Contract):
    """An image a Grok Bot showed: a link Tico fetches, or the bytes themselves (small ones)."""
    url: str = Field(default="", max_length=4000)
    name: str = Field(default="", max_length=200)
    content_base64: str = Field(default="", max_length=7_000_000)


class GrokMessage(M.Contract):
    role: str = Field(pattern=r"^(user|bot)$")
    text: str = Field(min_length=1, max_length=40_000)
    at: str = Field(default="", max_length=50)
    id: str = Field(default="", max_length=200)
    images: list[GrokImage] = Field(default_factory=list, max_length=10)


class GrokBot(M.Contract):
    grok_id: str = Field(min_length=1, max_length=100, pattern=r"^[A-Za-z0-9_.:-]+$")
    name: str = Field(min_length=1, max_length=100)
    description: str = Field(default="", max_length=2000)
    instructions: str = Field(default="", max_length=40_000)
    messages: list[GrokMessage] = Field(default_factory=list, max_length=500)


class GrokSync(M.Contract):
    bots: list[GrokBot] = Field(min_length=1, max_length=50)
    source: str = Field(default="", max_length=200)      # which Bot ran the sync, for the page


TICO_WORD = re.compile(r"\bTico\b", re.I)


def local_name(name):
    """What a Grok Bot is called here. In Grok a Bot says "Tico" to mark it as one of ours; here
    every bot is Tico's, so the word says where it runs instead: "Tico Designer" in Grok is "Grok
    Designer" in Tico."""
    renamed = " ".join(TICO_WORD.sub("Grok", name).split())
    return re.sub(r"\b(Grok)(\s+Grok\b)+", r"\1", renamed, flags=re.I) or name


def slug_for(c, name):
    base = "-".join("".join(ch if ch.isalnum() else " " for ch in name.lower()).split())[:60] or "grok-bot"
    slug, n = base, 2
    while H.bot(c, slug):
        slug, n = f"{base}-{n}", n + 1
    return slug


def find(c, person, grok_id):
    for row in c.execute("SELECT bot,config_json FROM bot_config WHERE operator=? AND "
                         "json_extract(config_json,'$.harness')=?", (person, HARNESS)):
        grok = (H._json(row["config_json"], {}) or {}).get("grok") or {}
        if grok.get("id") == grok_id:
            return row["bot"]
    return None


# ----------------------------------------------------------------------------- images
# A synced message may carry images. Each one is fetched once, stored like a chat attachment and shown inline; one
# that cannot be fetched stays a link. Tico fetches only public https addresses, so a sync can
# never make it read something on its own network.
def public_host(host):
    try:
        infos = socket.getaddrinfo(host, 443, proto=socket.IPPROTO_TCP)
    except (OSError, UnicodeError):
        return False
    addresses = {ipaddress.ip_address(info[4][0].split("%")[0]) for info in infos}
    return bool(addresses) and all(a.is_global for a in addresses)


def fetch_image(url, transport=None):
    """(bytes, content type) for an image at a public https address, or None."""
    for _ in range(IMAGE_REDIRECTS + 1):
        parts = urlsplit(url)
        if parts.scheme != "https" or not parts.hostname or (transport is None and not public_host(parts.hostname)):
            return None
        try:
            with httpx.Client(timeout=IMAGE_TIMEOUT, follow_redirects=False, transport=transport) as client:
                with client.stream("GET", url) as response:
                    if response.is_redirect:
                        url = urljoin(url, response.headers.get("location", ""))
                        continue
                    kind = response.headers.get("content-type", "").split(";")[0].strip().lower()
                    if response.status_code != 200 or not kind.startswith("image/"):
                        return None
                    data = b""
                    for chunk in response.iter_bytes():
                        data += chunk
                        if len(data) > IMAGE_BYTES:
                            return None
                    return (data, kind) if data else None
        except httpx.HTTPError:
            return None
    return None


def image_bytes(image, transport=None):
    """(bytes, content type, name) for one GrokImage, or None when it cannot be had."""
    name = image.name or (urlsplit(image.url).path.rsplit("/", 1)[-1] if image.url else "") or "grok-image"
    if image.content_base64:
        try:
            data = base64.b64decode(image.content_base64, validate=True)
        except (ValueError, binascii.Error):
            return None
        kind = mimetypes.guess_type(name)[0]
        return (data, kind or "image/png", name) if 0 < len(data) <= IMAGE_BYTES else None
    fetched = fetch_image(image.url, transport) if image.url else None
    return (fetched[0], fetched[1], name) if fetched else None


def allowed(auth, who):
    if who.role not in ("human", "owner"):
        raise Problem("forbidden", "A person syncs their own Grok Bots, with their own token", 403)
    if not auth.bot_admin(who):
        raise Problem("forbidden", "Only the owner or a bot administrator may add bots", 403)


def prefetch_images(store, blobs, body, transport=None):
    """Fetch and store the images of messages Tico does not have yet, outside any transaction.
    {message id: [(digest, size, name, content type) or (None, url)]}."""
    wanted = {}
    for item in body.bots:
        for msg in item.messages:
            if msg.images:
                wanted[message_id(item.grok_id, msg)] = msg.images
    if not wanted:
        return {}
    with store.read() as c:
        marks = ",".join("?" * len(wanted))
        have = {r[0] for r in c.execute(f"SELECT id FROM messages WHERE id IN ({marks})", tuple(wanted))}
    out = {}
    for mid, images in wanted.items():
        if mid in have:
            continue
        rows = []
        for image in images:
            got = image_bytes(image, transport)
            if got:
                data, kind, name = got
                rows.append((blobs.put(data), len(data), name, kind))
            elif image.url:
                rows.append((None, image.url))
        out[mid] = rows
    return out


def message_id(grok_id, msg):
    key = msg.id or f"{msg.role}|{msg.at}|{msg.text[:500]}"
    return "grok-" + str(uuid.uuid5(NAMESPACE, grok_id + "|" + key))


def moment(value, fallback):
    at = H.parse_ts(value) if value else None
    return at.strftime("%Y-%m-%dT%H:%M:%S.%f") + "Z" if at else fallback


def import_messages(c, person, slug, grok_id, messages, images=None, who=None):
    """Copy a transcript into the person's room with the bot. Returns (added, already there)."""
    if not messages:
        return 0, 0
    me, bot = "human:" + person, "bot:" + slug
    room = rooms.personal_room(c, me, slug, subject="Grok Bot")
    now = H.now()
    added = 0
    for msg in messages:
        mid = message_id(grok_id, msg)
        sender, target = (me, bot) if msg.role == "user" else (bot, me)
        created = moment(msg.at, now)
        refs = {"quiet": True, "grok": {"bot": grok_id, "id": msg.id or None}}
        text, attached = msg.text, []
        for row in (images or {}).get(mid) or []:
            if row[0] is None:          # could not be fetched: the link, so it is not lost
                text += f"\n\n[Image in Grok]({row[1]})"
            elif who is not None:
                attached.append(register(c, who, *row))
        if attached:
            refs["attachments"] = attached
        cur = c.execute(
            "INSERT OR IGNORE INTO messages (id, conversation_id, from_actor, to_actor, kind, body, "
            "refs_json, created, delivered_at, read_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
            (mid, room["id"], sender, target, "say", text, encode(refs), created, now, now))
        added += cur.rowcount
        if cur.rowcount:
            for item in attached:
                c.execute("INSERT INTO message_assets VALUES(?,?)", (mid, item["id"]))
    if added:
        last = c.execute("SELECT max(created) FROM messages WHERE conversation_id=?", (room["id"],)).fetchone()[0]
        c.execute("UPDATE conversations SET last_message_at=? WHERE id=?", (last, room["id"]))
    return added, len(messages) - added


def synced_through(c, person, slug):
    row = c.execute("SELECT max(m.created) FROM messages m JOIN conversations v ON v.id=m.conversation_id "
                    "WHERE v.scope='personal' AND v.owner_actor=? AND v.room_key=? AND m.id LIKE 'grok-%'",
                    ("human:" + person, slug)).fetchone()
    return row[0] if row else None


def sync(c, auth, settings_admin, who, body, images=None):
    allowed(auth, who)
    person = H.actor_id(who.actor)
    now = H.now()
    out = []
    for item in body.bots:
        slug = find(c, person, item.grok_id)
        created = not slug
        name = local_name(item.name)
        if created:
            slug = slug_for(c, name)
            settings_admin.create_bot(c, who, M.BotDefinitionCreate(
                slug=slug, display_name=name, description=item.description,
                reports_to="human:" + person, status="active", thread_mode="personal",
                model=MODEL, effort="as-configured", harness=HARNESS, operator=person,
                owners=[person]))
        row = c.execute("SELECT config_json,description FROM bot_config WHERE bot=?", (slug,)).fetchone()
        config = H._json(row["config_json"], {}) or {}
        before = dict(config.get("grok") or {})
        grok = {**before, "id": item.grok_id, "name": item.name, "last_sync": now,
                "source": body.source or before.get("source") or ""}
        if item.instructions:
            grok["instructions"] = item.instructions
            grok["instructions_hash"] = hashlib.sha256(item.instructions.encode()).hexdigest()[:16]
            if grok["instructions_hash"] != before.get("instructions_hash"):
                grok["instructions_updated"] = now
        config["grok"] = grok
        config["display_name"] = name
        c.execute("UPDATE bot_config SET config_json=?,description=? WHERE bot=?",
                  (encode(config), item.description or row["description"], slug))
        c.execute("UPDATE bots SET display_name=? WHERE slug=?", (name, slug))
        added, known = import_messages(c, person, slug, item.grok_id, item.messages, images, who)
        H.event(c, who.actor, "grokbot.synced", slug, {"grok": item.grok_id, "created": created,
                                                        "messages": added})
        out.append({"grok_id": item.grok_id, "bot": slug, "created": created,
                    "messages_added": added, "messages_known": known,
                    "instructions_changed": grok.get("instructions_updated") == now,
                    "synced_through": synced_through(c, person, slug)})
    return {"person": person, "bots": out, "synced": now}


def presence(c, bot, config, now=None):
    """`agents.presence` for a Grok Bot: reporting in means synced lately."""
    grok = config.get("grok") or {}
    last = grok.get("last_sync")
    now = now or H.now()
    online = bool(last and last > H.shift(now, seconds=-PRESENCE_GAP))
    agent = {"harness": HARNESS, "credential": True, "last_seen": last, "revoked_at": None,
             "version": "", "platform": "grok bot", "model": "", "provider": "xai",
             "profile": grok.get("name") or "", "detail": grok.get("source") or "",
             "synced": True, "instructions_updated": grok.get("instructions_updated")}
    return {"online": online, "awake": online, "ready": online, "machine": None, "agent": agent}
