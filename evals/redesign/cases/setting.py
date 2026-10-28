"""Redesign off (PLAN §7, scenario 45): nothing changes for an install. The dormant code must leave today's hourly limit,
routines, task flow and turn budgets as they are. These checks pass on main now and must keep passing."""
from ..harness import (CLAUDE, CLAUDE_ID, LEAD_ID, OPENAI_ID, W2, W3, Check, Scenario, accepted, body, find, got, put_limit,
                       rows, send, setup)


def s45_steps(org, f):
    org.step(f, "limit", put_limit, org, OPENAI_ID, {"hourly_usd": 2.0})
    org.step(f, "limits", lambda: org.api("get", "/api/v2/usage/limits", wave=W2))
    org.step(f, "routine", lambda: org.api("post", f"/api/v2/bots/{CLAUDE_ID}/routines", {
        "title": "Morning check", "text": "Check the queue.", "cron": "0 9 * * *", "timezone": "UTC",
        "enabled": True}, wave=W3))
    org.step(f, "routines", lambda: org.api("get", f"/api/v2/bots/{CLAUDE_ID}/routines", wave=W3))
    org.step(f, "task", send, org, CLAUDE, LEAD_ID, "Ordinary task")
    org.step(f, "defaults", lambda: org.api("get", "/api/v2/settings/turn-budgets", wave=W2))


def hourly_kept(f):
    setup(f, "limit", "limits")
    hit = find(body(f, "limits"), lambda d: d.get("hourly_usd") == 2.0)
    return hit is not None, "hourly_usd 2.0 listed" if hit else "no 2.0 hourly limit listed"


def routine_listed(f):
    setup(f, "routine", "routines")
    titles = [r.get("title") for r in rows(body(f, "routines"))]
    return "Morning check" in titles, f"{len(titles)} routine(s) listed"


def budget_defaults(f):
    setup(f, "defaults")
    hit = find(body(f, "defaults"), lambda d: d.get("turns_per_hour") == 300 and d.get("turns_per_day") == 2500)
    return hit is not None, "300 an hour, 2,500 a day" if hit else f"got {got(f, 'defaults').excerpt()}"


SCENARIOS = [
    Scenario(45, "setting-off-unchanged", "redesign off: nothing changes for an install (holds today)", s45_steps, [
        Check("hourly spend limit kept: 2.00 an hour is listed back", W2, hourly_kept),
        Check("a routine saved for its bot is listed", W3, routine_listed),
        Check("an ordinary task from the bot to its lead is accepted", W2,
              lambda f: accepted(f, "task")),
        Check("turn budgets default to 300 runs an hour and 2,500 a day", W2, budget_defaults),
    ], setting=False),
]
