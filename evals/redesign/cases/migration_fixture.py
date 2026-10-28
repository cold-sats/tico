"""The migration fixture (PLAN §7, scenarios 39-44): an Acme install made only through the routes main has today, with
one or more of every object PLAN §8 maps. It is installed with the redesign setting off, as a real install's data was
written, so a `hourly_usd` is stored as an hourly limit and nothing is converted on the way in.

Each call is one step under the key "fx:<name>". A call main refuses keeps an Unmet naming the call and its answer, so
a bad payload fails every check that needs that object instead of leaving a silent gap. install_fixture() returns the
ids it made (None for a call that failed) and keeps them in facts["fixture"].

What it makes:
- routines: two cron (Europe/London daily, UTC hourly at :30), one on an event, one on an incoming webhook, and the
  Librarian's market briefing (cron, America/Los_Angeles, weekdays)
- the incoming trigger the webhook routine listens for; its secret is kept to post to the old address after converting
- custom wake rules: two on Builder (Claude) (wake, note), one on Builder (OpenAI) (batch)
- a task rule; the system jobs' controls (Stale ticket review off and hourly; Still wanted? daily at 10:00)
- two inboxes, Dana's and Priya's, each read by its own Inbox Manager bot (the roster's inbox_bot and mailbox)
- listening destinations: market (the Librarian) and leads (the Engineering Lead)
- hourly spend limits 3.00, 5.00 and 0.25; team turn budgets below the guard (120 an hour, 1,000 a day) and one bot
  above it (600 an hour)
- a goal; and the CEO Bot, the Health Monitor and the Librarian as org bots (FIXTURE_BOTS, passed as Scenario.bots)"""
from ..harness import CLAUDE_ID, DANA_ID, LEAD_ID, OPENAI_ID, PRIYA_ID, RELEASE_ID, W5, Unmet

CEO, LIBRARIAN, HEALTH = "goal-manager", "librarian", "health-monitor"   # backend/ceo_bot.py SLUG, groups.SYSTEM_BOTS
INBOX_DANA, INBOX_PRIYA = "inbox-manager-dana", "inbox-manager-priya"
FIXTURE_BOTS = {CEO: ("ceo", "claude"), LIBRARIAN: ("librarian", "claude"), HEALTH: ("health", "claude"),
                INBOX_DANA: ("inbox", "claude"), INBOX_PRIYA: ("inbox", "claude")}

HOOK_ID = "deploy-failed"
# name -> (bot, the routine as POST /api/v2/bots/{bot}/routines takes it)
ROUTINES = {
    "standup": (CLAUDE_ID, {"title": "Morning standup notes", "text": "Post yesterday's work and today's plan.",
                            "cron": "0 9 * * *", "timezone": "Europe/London"}),
    "pr_sweep": (OPENAI_ID, {"title": "Open PR sweep", "text": "Nudge every pull request that has waited a day.",
                             "cron": "30 * * * *", "timezone": "UTC"}),
    "release_notes": (RELEASE_ID, {"title": "Release notes", "text": "Write the notes for the new release.",
                                   "on": "release_published"}),
    "deploy_triage": (LEAD_ID, {"title": "Deploy failure triage", "text": "Find why the deploy failed and file a fix.",
                                "on": "webhook." + HOOK_ID}),
    "briefing": (LIBRARIAN, {"title": "Market briefing", "text": "Write today's market briefing from the graph.",
                             "cron": "0 7 * * 1-5", "timezone": "America/Los_Angeles"}),
}
CRON = ("standup", "pr_sweep", "briefing")
# name -> (bot, event, outcome): custom rows in the rules table, each a bot-scope wake rule (backend/rules.py)
WAKE_RULES = {
    "claude_comment": (CLAUDE_ID, "comment", "wake"),
    "claude_step": (CLAUDE_ID, "step_entered", "note"),
    "openai_comment": (OPENAI_ID, "comment", "batch"),
}
TASK_RULE = {"name": "Close 48h after done", "department": "engineering",
             "triggers": [{"key": "done_untouched", "hours": 48}], "actions": ["close"], "preset": "hourly"}
SYSTEM_JOBS = {"stale_review": {"on": False, "preset": "hourly"},           # PLAN §8: keeps Off + hourly
               "still_wanted": {"on": True, "preset": "daily", "at": "10:00"}}   # a control a built-in keeps
BUILTIN_JOBS = ("assigned_tasks", "assignment_recovery")   # "Start assigned tasks", "Recover unstarted assignments"
# person -> (their Inbox Manager bot, the mailbox it reads)
INBOXES = {DANA_ID: (INBOX_DANA, "dana@acme.example"), PRIYA_ID: (INBOX_PRIYA, "priya@acme.example")}
DESTINATIONS = {"market": {"category": "market", "threshold": 0.6, "receiver": LIBRARIAN},
                "leads": {"category": "lead", "threshold": 0.7, "receiver": LEAD_ID}}
HOURLY = {OPENAI_ID: 3.00, CLAUDE_ID: 5.00, RELEASE_ID: 0.25}
TEAM_BUDGET = {"turns_per_hour": 120, "turns_per_day": 1000}
GUARD = {"turns_per_hour": 300, "turns_per_day": 2500}   # CONTRACT §1 run guard defaults
BOT_BUDGET = (OPENAI_ID, {"turns_per_hour": 600})         # set above the guard: kept
GOAL = {"title": "Ship the v2 billing page", "owner": LEAD_ID}


def _call(org, name, method, path, payload=None):
    """One fixture write through today's route. Anything but a 2xx keeps an Unmet with the call and its answer."""
    reply = org.api(method, path, payload, wave=W5)
    if not 200 <= reply.status < 300:
        raise Unmet(W5, f"fixture {name} did not install on {method.upper()} {path}: {reply.status} {reply.excerpt()}")
    return reply


def _budget(org):
    current = _call(org, "bot_budget_read", "get", f"/api/v2/bots/{BOT_BUDGET[0]}/budget")
    return _call(org, "bot_budget", "post", f"/api/v2/bots/{BOT_BUDGET[0]}/budget",
                 {**BOT_BUDGET[1], "expected_revision": current.body["revision"]})


def _id(facts, key, *path):
    """A value from a fixture step's answer, or None when the step did not install."""
    value = facts.get(key)
    if value is None or isinstance(value, Unmet):
        return None
    value = value.body
    for part in path:
        value = value.get(part) if isinstance(value, dict) else None
    return value


def install_fixture(org, facts):
    """Install the fixture; returns {routines, hook, rules, task_rule, inboxes, destinations, goal, bots, ...} ids."""
    step = lambda name, *args: org.step(facts, "fx:" + name, _call, org, name, *args)
    # The trigger first: a routine may listen for a webhook only while its trigger exists (backend/routines.py).
    step("trigger", "post", "/api/v2/triggers", {"name": "Deploy failed", "id": HOOK_ID})
    for name, (bot, routine) in ROUTINES.items():
        step("routine:" + name, "post", f"/api/v2/bots/{bot}/routines", routine)
    for name, (bot, event, outcome) in WAKE_RULES.items():
        step("rule:" + name, "post", "/api/v2/rules",
             {"scope_kind": "bot", "scope_id": bot, "event": event, "then": outcome})
    step("task_rule", "post", "/api/v2/task-rules", TASK_RULE)
    for job, control in SYSTEM_JOBS.items():
        step("job:" + job, "put", f"/api/v2/system-routines/{job}", control)
    for person, (bot, mailbox) in INBOXES.items():
        step("inbox:" + person, "post", f"/api/v2/access/people/{person}", {"inbox_bot": bot, "mailbox": mailbox})
    for key, destination in DESTINATIONS.items():
        step("destination:" + key, "put", f"/api/v2/listening/destinations/{key}", destination)
    for bot, usd in HOURLY.items():
        step("limit:" + bot, "put", f"/api/v2/usage/limits/{bot}", {"hourly_usd": usd})
    # The team's run budgets rebuild the caller from the access list (auth.identity_for_actor), whose owner is the
    # factory's seeded owner, not Dana: Dana is made an admin first, as an owner would make a co-founder one.
    step("dana_admin", "post", f"/api/v2/access/people/{DANA_ID}", {"role": "admin"})
    step("team_budget", "post", "/api/v2/settings/turn-budgets", TEAM_BUDGET)
    org.step(facts, "fx:bot_budget", _budget, org)
    step("goal", "post", "/api/v2/goals", GOAL)
    secret = None
    url = _id(facts, "fx:trigger", "trigger", "url")
    if url:
        secret = url.rstrip("/").rsplit("/", 1)[-1]
    ids = {"routines": {name: _id(facts, "fx:routine:" + name, "routine", "id") for name in ROUTINES},
           "hook": {"id": _id(facts, "fx:trigger", "trigger", "id"), "secret": secret},
           "rules": {name: _id(facts, "fx:rule:" + name, "rule", "id") for name in WAKE_RULES},
           "task_rule": _id(facts, "fx:task_rule", "job", "key"),
           "jobs": [job for job in SYSTEM_JOBS if _id(facts, "fx:job:" + job, "job", "key")],
           "inboxes": {person: {"bot": bot, "mailbox": mailbox} for person, (bot, mailbox) in INBOXES.items()
                       if _id(facts, "fx:inbox:" + person, "person")},
           "destinations": [key for key in DESTINATIONS if _id(facts, "fx:destination:" + key, "destination", "key")],
           "limits": {bot: usd for bot, usd in HOURLY.items() if _id(facts, "fx:limit:" + bot, "bot")},
           "goal": _id(facts, "fx:goal", "goal", "id"),
           "bots": {"ceo": CEO, "librarian": LIBRARIAN, "health": HEALTH}}
    facts["fixture"] = ids
    return ids


def installed(facts, *names):
    """Raise the fixture step's Unmet when any named fixture call failed ("routine:standup", "limit:builder-openai")."""
    for name in names:
        value = facts.get("fx:" + name)
        if value is None:
            raise Unmet(W5, f"fixture {name} was never installed")
        if isinstance(value, Unmet):
            raise value
