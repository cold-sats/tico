"""The one list of named events: routines (`on:`), rules (WHEN), outgoing webhook subscriptions, `hub event-types` and
the docs all read it.

An event is a dot name in a group (`task.done`) with a one-line description and an `example`: the `data` object of a
typical payload, in Acme's words. "Send example" posts it and the docs show it. Every payload carries its event's
`version` (starts at 1); a change that breaks a receiver adds a new version, never edits one.

`aliases` are spellings that came before the catalog and still work (`release_published`). `sourceless` marks events
that are not a message to a bot and have no task, so a rule judges them with `rules.judge_event` (scopes team,
department and bot only). `webhook.<id>` (one incoming webhook) and `custom.<x>` (anything a bot or rule sends) are not
listed one by one: `canonical` lets them through.

This module imports nothing from Tico: runners and clients validate routines with it too.
"""
import re
from dataclasses import dataclass

CUSTOM = "custom."
# One incoming webhook's own event, `webhook.<id>` (backend/triggers.py): a routine may listen for it.
_WEBHOOK_ID = re.compile(r"webhook\.[a-z0-9][a-z0-9-]{0,39}")
_CUSTOM = re.compile(r"custom\.[a-z0-9][a-z0-9_.-]{0,59}")


@dataclass(frozen=True)
class Event:
    name: str            # "task.done"
    group: str           # "task"
    description: str     # one short line, plain words
    example: dict        # the `data` object of a typical payload; what "Send example" posts
    version: int = 1
    aliases: tuple = ()  # old spellings still accepted: ("release_published",)
    sourceless: bool = False    # no task and no message: rules judge it with judge_event


# Ids in the examples are made up; they look like the real ones.
_TASK = "5b1d2c0e-7f34-4a9e-8c1b-2f6a9d3e4b10"


def _task(**more):
    return {"task": {"id": _TASK, "title": "Renew the acme.example domain", "step": "Doing", "state": "doing",
                     "owner": "bot:ops", "requester": "human:ana", **more}}


def _build():
    found = []

    def add(name, description, example, aliases=(), sourceless=False):
        found.append(Event(name, name.split(".", 1)[0], description, example, 1, tuple(aliases), sourceless))

    add("task.created", "A task was filed.", {**_task(step="Open", state="open"), "actor": "human:ana"})
    add("task.assigned", "A task was given to someone else.",
        {**_task(), "actor": "human:ana", "change": {"owner": {"from": "bot:ops", "to": "bot:finance"}}})
    add("task.step_changed", "A task moved to another step.",
        {**_task(step="Review"), "actor": "bot:ops", "change": {"step": {"from": "Doing", "to": "Review"}}})
    add("task.state_changed", "A task's state changed (open, doing, waiting, review, ready).",
        {**_task(state="waiting"), "actor": "bot:ops", "change": {"state": {"from": "doing", "to": "waiting"}}})
    add("task.commented", "Someone commented on a task.",
        {**_task(), "actor": "human:ana", "comment": {"id": "c1", "text": "Use the Acme card on file."}})
    add("task.done", "A task was finished.", {**_task(step="Done", state="done"), "actor": "bot:ops"})
    add("task.declined", "A task was declined.",
        {**_task(state="declined"), "actor": "bot:ops", "reason": "Acme already renewed it."})
    add("task.blocked", "A task now waits on someone or something.",
        {**_task(state="waiting"), "actor": "bot:ops", "waiting_on": "human:ana"})
    add("task.closed", "A task was closed without finishing.", {**_task(state="closed"), "actor": "human:ana"})
    add("task.reopened", "A finished task was opened again.", {**_task(state="open"), "actor": "human:ana"})

    approval = {"id": "a1", "kind": "send", "task": _TASK, "requested_by": "bot:ops"}
    add("approval.requested", "A bot asked a person to approve something.",
        {"approval": {**approval, "summary": "Email the Acme invoice to billing@acme.example"}})
    add("approval.decided", "A person approved or declined a request.",
        {"approval": {**approval, "decision": "approved", "decided_by": "human:ana"}})
    add("approval.withdrawn", "A request was withdrawn because it no longer applies.",
        {"approval": {**approval, "decision": "withdrawn"}})

    add("needs_you.created", "Something now needs a person's answer.",
        {"item": {"id": "n1", "for": "human:ana", "title": "Which Acme plan should we renew?", "task": _TASK}})
    add("needs_you.answered", "A person answered something that needed them.",
        {"item": {"id": "n1", "for": "human:ana", "title": "Which Acme plan should we renew?", "task": _TASK},
         "answer": "The annual plan."})

    add("bot.run_failed", "A bot's run failed.",
        {"bot": "ops", "run": "r1", "task": _TASK, "reason": "The model login expired."})
    add("bot.held", "A bot was held: it hit a limit or kept failing.",
        {"bot": "ops", "reason": "budget", "detail": "The daily turn budget is used up."})
    add("bot.released", "A held bot was released.", {"bot": "ops", "by": "human:ana"})

    add("release.published", "A Tico release was published.",
        {"release": "v1.4.0", "url": "https://github.com/acme/app/releases/tag/v1.4.0", "tickets": 6},
        aliases=("release_published",), sourceless=True)
    add("meeting.ready", "A team meeting with a transcript was imported.",
        {"meeting": {"id": "m1", "title": "Acme weekly sync", "ended": "2026-03-02T17:30:00Z", "duration_ms": 1800000}},
        aliases=("recording.ready",))
    add("strategy.published", "A new version of the strategy was published.",
        {"version": 3, "note": "Focus on Acme's renewals.", "published_by": "human:ana"})
    add("market.insight.urgent", "An urgent market insight was reported.",
        {"insight": {"id": "i1", "title": "Acme's biggest rival cut prices by 20%", "company": "Rival Co"}})
    add("market.briefing", "The weekly market briefing is ready.",
        {"week": "2026-W10", "bets": ["Renewals", "Self-serve onboarding"]})
    add("inbound.received", "New mail arrived for a person's inbox bot.",
        {"mail": {"id": "g1", "from": "buyer@customer.example", "subject": "Quote for 50 seats"},
         "inbox": "ana@acme.example"})
    add("health.finding", "Tico found a problem on this install.",
        {"finding": {"id": "f1", "severity": "warning", "title": "A computer has not reported for an hour"}},
        sourceless=True)
    add("webhook.received", "An incoming webhook was accepted.",
        {"trigger": {"id": "shop", "name": "Acme shop"}, "delivery": "d1", "type": "order.created",
         "payload": {"order": 42, "total": "120.00"}, "via": "direct"}, sourceless=True)
    add("tico.notice", "A notice from the Tico team reached this install.",
        {"id": "tn1", "kind": "info", "body": "Version 1.4.1 fixes a mail sync bug.", "url": "https://tico.team/notices/1"},
        sourceless=True)
    add("custom.*", "Anything a bot or rule sends: custom.<name>.",
        {"note": "custom.<name> carries whatever its sender puts in data."})
    return found


EVENTS: dict = {e.name: e for e in _build()}
_ALIASES = {alias: e.name for e in EVENTS.values() for alias in e.aliases}


def canonical(name):
    """The catalog name for `name` (an alias becomes its event), or None when it is not an event. `webhook.<id>` and
    `custom.<x>` pass through."""
    if not isinstance(name, str):
        return None
    if name in EVENTS:
        return name
    if name in _ALIASES:
        return _ALIASES[name]
    if _WEBHOOK_ID.fullmatch(name) or _CUSTOM.fullmatch(name):
        return name
    return None


def matches(pattern, name):
    """Whether `name` is `pattern`: exactly, or by prefix when the pattern ends with `*` (`task.*`, `*`)."""
    if not isinstance(pattern, str) or not isinstance(name, str):
        return False
    if pattern.endswith("*"):
        return name.startswith(pattern[:-1])
    return pattern == name


def spellings(name):
    """Every spelling of the event `name` is: its catalog name and its aliases. A name that is no event is itself."""
    found = canonical(name) or name
    return (found,) + tuple(EVENTS[found].aliases if found in EVENTS else ())


def listing(group=None):
    """The catalog as the API shows it, optionally one group."""
    return [{"name": e.name, "group": e.group, "description": e.description, "version": e.version,
             "example": e.example, "aliases": list(e.aliases), "sourceless": e.sourceless}
            for e in EVENTS.values() if group in (None, e.group)]


def sourceless():
    """The names of the events rules judge without a task."""
    return tuple(e.name for e in EVENTS.values() if e.sourceless)
