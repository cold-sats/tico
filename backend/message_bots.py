"""A message bot is a person's: the server has to be told whose, or its runs get no mail token.

The Inbox Manager template only writes `Mailbox: <email>` into the bot's instructions. What lets a run ask its
computer for a token is the roster: the person's `inbox_bot` names the bot, and the bot's `gmail` tool names the
address (routines.token_mailboxes). `link` writes both wherever a message bot is made (Settings' add from template,
the team builder, BotOps registering one for the person who asked), and `backfill` does it once at start for the
bots made before that, when there is no doubt whose they are.
"""
import json
import re
from types import SimpleNamespace

from . import access as Access
from . import routines
from .store import H, P, Problem

TEMPLATES = frozenset({"inbox"})
LINE = re.compile(r"^Mailbox:[ \t]*(\S+@\S+)[ \t]*$", re.M)
DONE = "message-bots-linked"          # bots the start-up pass linked once: an owner who unlinks one is not overruled


def is_message_bot(config):
    return str((config or {}).get("template") or "") in TEMPLATES


def declared_line(text):
    """The address a `Mailbox:` line names in the instructions, lowercased, or empty."""
    found = LINE.search(str(text or ""))
    address = found.group(1).strip().lower() if found else ""
    return address if routines.MAILBOX.fullmatch(address) else ""


def _config(c, bot):
    row = c.execute("SELECT config_json FROM bot_config WHERE bot=?", (bot,)).fetchone()
    try:
        return json.loads(row["config_json"] or "{}") if row else {}
    except ValueError:
        return {}


def _roster(c):
    from . import rooms
    return rooms.roster(c)


def _link(c, actor, roster, bot, person, mailbox):
    """Name `bot` as `person`'s message bot reading `mailbox`, by the same rules as the owner's route (a bot is one
    person's, a message bot gets a computer to itself). Returns the person's id, or None with nothing changed."""
    if not person or person.get("hidden") or not routines.MAILBOX.fullmatch(mailbox or ""):
        return None
    if person.get("inbox_bot") not in (None, "", bot):
        return None                                  # they have a message bot already: theirs to change
    try:
        row = Access.assign_message_bot(c, roster, dict(person), SimpleNamespace(inbox_bot=bot, mailbox=mailbox))
    except Problem:
        return None                                  # another person's bot, or a computer shared with other bots
    row = P._person(row)
    Access.save_roster(c, {**roster, "people": [row if p["id"] == person["id"] else p for p in roster["people"]]})
    Access._sync_human(c, row)
    H.event(c, actor, "person.message_bot_linked", person["id"], {"bot": bot, "mailbox": mailbox})
    return person["id"]


def link(c, actor, bot, requester=None, instructions=None):
    """A message bot was just made for a person: link it. The person is whoever the `Mailbox:` line names (by their
    roster email), else the requester when there is no line. The mailbox is that line, else what the bot already
    declares, else the person's own email. Anything that is not a message bot is left alone."""
    config = _config(c, bot)
    if not is_message_bot(config):
        return None
    roster = _roster(c)
    line = declared_line(instructions if instructions is not None else config.get("instructions"))
    person = P.person_by_email(line, roster) if line else P.person(H.actor_id(requester or ""), roster)
    if not person:
        return None
    mailbox = line or routines.declared_mailbox(config) or str(person.get("email") or "").strip().lower()
    return _link(c, actor, roster, bot, person, mailbox)


def backfill(c, actor="keeper"):
    """Link the message bots made before the server did: a bot from a message-bot template that is nobody's yet,
    whose mailbox is written in its instructions (a `Mailbox:` line) or declared by its `gmail` tool. Its person is
    the one whose email is that mailbox, else the only person on the roster. Two bots for one person, or a person
    with a message bot already, is a choice for an owner and is left. Returns the bots linked."""
    roster = _roster(c)
    people = [p for p in roster["people"] if not p.get("hidden")]
    taken = {p.get("inbox_bot") for p in roster["people"] if p.get("inbox_bot")}
    found = c.execute("SELECT value_json FROM registry_metadata WHERE key=?", (DONE,)).fetchone()
    done = set(json.loads(found[0])) if found else set()
    wanted = []
    for row in c.execute("SELECT b.slug FROM bots b WHERE b.state<>'archived' ORDER BY b.slug"):
        bot = row["slug"]
        config = _config(c, bot)
        mailbox = declared_line(config.get("instructions")) or routines.declared_mailbox(config)
        if bot in taken or bot in done or not is_message_bot(config) or not mailbox:
            continue
        person = P.person_by_email(mailbox, roster) or (people[0] if len(people) == 1 else None)
        if person and not person.get("inbox_bot"):
            wanted.append((bot, person, mailbox))
    claimed = [p["id"] for _, p, _ in wanted]
    linked = []
    for bot, person, mailbox in wanted:
        if claimed.count(person["id"]) > 1:
            continue
        if _link(c, actor, roster, bot, person, mailbox):
            linked.append(bot)
            roster = _roster(c)
    if linked:
        c.execute("INSERT INTO registry_metadata VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value_json=excluded.value_json",
                  (DONE, json.dumps(sorted(done | set(linked)))))
    return linked
