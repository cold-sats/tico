"""The Librarian: the built-in bot that answers questions from the team's docs (docs/librarian.md).

A person's question (`POST /api/v2/docs/ask`) goes to one private docs room per person
(`rooms.DOCS_ROOM`, scope personal, owner_actor the person), the same machinery as the Assistant's
room: only they read it, the owner and administrators included (`Auth.conversation`). The response
carries the instant search results, so the page shows matches at once, and the room id, so it can
stream the Librarian's answer from `/api/v2/conversations/{id}/watch`.

The Librarian acts as itself, never as the person. It only reads docs (`hub doc ...`) and fetches
public links on its own computer (`hub doc fetch`), so nothing it does needs a person's identity and
none is mapped to it. A bot that wants an answer sends the Librarian an `ask` message (`hub doc ask`),
which is the ordinary ask and answer path and needs nothing here.
"""

import asyncio

from fastapi import Request

from . import models as M
from . import rooms
from .assistant import Internal
from .store import H, Problem

LIBRARIAN = "librarian"
NAME = "Librarian"
RESULT_LIMIT = 8


def availability(c, who):
    bot = H.bot(c, LIBRARIAN)
    state = bot["state"] if bot else "missing"
    return {"available": state == "active", "state": state, "bot": LIBRARIAN, "name": NAME,
            "can_turn_on": who.role == "owner" and state != "active" and state != "quarantined"}


def find_room(c, actor):
    row = c.execute("SELECT id FROM conversations WHERE scope='personal' AND owner_actor=? AND room_key=? "
                    "AND closed_at IS NULL ORDER BY created LIMIT 1", (actor, rooms.DOCS_ROOM)).fetchone()
    return H.conversation(c, row["id"]) if row else None


def ensure_room(c, actor):
    return find_room(c, actor) or H.open_conversation(
        c, actor, [actor, "bot:" + LIBRARIAN], kind="chat", subject="Docs", scope=rooms.PERSONAL,
        owner_actor=actor, room_key=rooms.DOCS_ROOM)


async def _search(request, question):
    """The instant results: stream A's `GET /api/v2/docs/search` (internal and linked docs), read as the
    person with the credential they came in with, so it shows exactly what the Docs page would."""
    data = await Internal(request).get("docs/search", q=question, collection="all", limit=RESULT_LIMIT)
    return list((data or {}).get("results") or [])[:RESULT_LIMIT]


def install(app, store, auth, mutate, onboarding):
    def person(request):
        who = request.state.identity
        if who.role not in ("owner", "human"):
            raise Problem("identity", "Bots ask the " + NAME + " with `hub doc ask` (a message of kind ask); "
                          "this route is for people", 403)
        return who

    @app.get("/api/v2/librarian")
    def librarian(request: Request):
        who = person(request)
        with store.read() as c:
            return availability(c, who)

    @app.post("/api/v2/librarian/turn-on")
    def turn_on(request: Request, body: M.Empty):
        who = person(request)
        if who.role != "owner":
            raise Problem("forbidden", "Only the owner turns the " + NAME + " on", 403)
        return mutate(request, body, lambda c: onboarding.turn_on_librarian(c, who))

    def send(request, body, who, results):
        def work(c):
            if not availability(c, who)["available"]:
                raise Problem("librarian_off", "The " + NAME + " is off", 409)
            if body.new_conversation and body.conversation_id:
                raise Problem("conversation", "Ask in a conversation or start a new one, not both", 422)
            if body.new_conversation:
                rooms.archive_personal_room(c, who.actor, rooms.DOCS_ROOM)     # 409 busy while it is answering
                room = ensure_room(c, who.actor)
            elif body.conversation_id:
                room = auth.conversation(c, who, body.conversation_id)     # someone else's room is a 403
                if (room.get("room_key") != rooms.DOCS_ROOM or room.get("owner_actor") != who.actor
                        or room.get("closed_at")):
                    raise Problem("conversation", "That is not your docs conversation", 422)
            else:
                room = ensure_room(c, who.actor)
            message = H.say(c, who.actor, "bot:" + LIBRARIAN, body.question, conversation_id=room["id"],
                            kind="say", refs={"docs_ask": True})
            H.event(c, who.actor, "docs.ask", message["id"], {"conversation": room["id"]})
            return {"conversation_id": room["id"], "message_id": message["id"], "results": results}
        return mutate(request, body, work)

    @app.post("/api/v2/docs/ask")
    async def ask(request: Request, body: M.DocsAsk):
        who = person(request)
        results = await _search(request, body.question)
        return await asyncio.to_thread(send, request, body, who, results)
