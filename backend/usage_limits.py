"""Spend limits: a daily and a monthly cap per bot, in estimated USD (docs/usage.md).

A bot's own limit wins; a bot with none follows the company default; the default is no limit. What
counts against a limit is the estimate of the runs the bot has finished in the period (backend/usage.py
prices each run as it completes). Runs on a ChatGPT or Claude sign-in are flat cost, so their
API-equivalent counts only when the company opts in.

  80%   one notice to the bot's operator (the company owner when it has none), once per period and limit
  100%  the bot takes no new job until the period turns over or the limit is raised: the job stays
        queued and the bot reads "Paused: over its daily limit". A run already going finishes.

The day is the UTC day and the month the UTC calendar month.
"""

import json
from datetime import datetime, timedelta, timezone

from .store import H

KEY = "usage_limits"                       # the company default, in registry_metadata
WARN = 80
MAX_USD = 10_000_000
PERIODS = (("daily", "day"), ("monthly", "month"))


def company(c):
    """The default for bots with no limit of their own: {daily_usd, monthly_usd, count_subscription}."""
    row = c.execute("SELECT value_json FROM registry_metadata WHERE key=?", (KEY,)).fetchone()
    try:
        stored = json.loads(row[0]) if row else {}
    except ValueError:
        stored = {}
    stored = stored if isinstance(stored, dict) else {}
    return {"daily_usd": _amount(stored.get("daily_usd")), "monthly_usd": _amount(stored.get("monthly_usd")),
            "count_subscription": stored.get("count_subscription") is True}


def _amount(value):
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return round(number, 6) if 0 < number <= MAX_USD else None


def own(c, bot):
    row = c.execute("SELECT daily_usd, monthly_usd FROM usage_limits WHERE bot=?", (bot,)).fetchone()
    return {"daily_usd": row["daily_usd"], "monthly_usd": row["monthly_usd"]} if row else {"daily_usd": None, "monthly_usd": None}


def effective(c, bot, default=None):
    """(daily, monthly) in USD or None, and where each came from: `bot`, `company` or None."""
    default = default or company(c)
    mine = own(c, bot)
    out, source = {}, {}
    for name, _ in PERIODS:
        key = name + "_usd"
        out[key] = mine[key] if mine[key] is not None else default[key]
        source[name] = "bot" if mine[key] is not None else "company" if default[key] is not None else None
    return out, source


def bounds(at=None):
    """The current period's key and its [from, to) timestamps: {daily: (key, from, to), monthly: ...}."""
    at = at or datetime.now(timezone.utc)
    day = at.strftime("%Y-%m-%d")
    first = at.replace(day=1)
    following = first.replace(year=first.year + (first.month == 12), month=first.month % 12 + 1)
    return {"daily": (day, day + "T00:00:00", (at + timedelta(days=1)).strftime("%Y-%m-%dT00:00:00")),
            "monthly": (at.strftime("%Y-%m"), first.strftime("%Y-%m-%dT00:00:00"), following.strftime("%Y-%m-%dT00:00:00"))}


def spent(c, bot, start, end, subscription):
    """The estimate for the bot's runs that started in [start, end), API-billed, and the subscription
    runs' API-equivalent too when the company counts them."""
    row = c.execute("SELECT coalesce(sum(est_cost_usd), 0) FROM turns WHERE bot=? AND started >= ? AND started < ? "
                    "AND (? OR coalesce(billing, 'api') != 'subscription')", (bot, start, end, 1 if subscription else 0)).fetchone()
    return float(row[0] or 0)


def state(c, bot, at=None, default=None):
    """Where the bot stands: its limits and their source, what it has spent, the highest percentage of a
    limit reached, and `blocked` (`daily` or `monthly`) when a limit is met."""
    default = default or company(c)
    limits, source = effective(c, bot, default)
    when = bounds(at)
    result = {"daily_usd": limits["daily_usd"], "monthly_usd": limits["monthly_usd"], "source": source,
              "day_spent": None, "month_spent": None, "percent": 0, "blocked": None}
    if limits["daily_usd"] is None and limits["monthly_usd"] is None:
        return result
    for name, label in PERIODS:
        _, start, end = when[name]
        amount = spent(c, bot, start, end, default["count_subscription"])
        result[label + "_spent"] = round(amount, 6)
        cap = limits[name + "_usd"]
        if cap:
            result["percent"] = max(result["percent"], int(100 * amount / cap))
            if amount >= cap and not result["blocked"]:
                result["blocked"] = name
    return result


def blocked(c, bot, at=None, default=None):
    """`daily` or `monthly` when the bot may take no new job, else None."""
    return state(c, bot, at, default)["blocked"]


def why(blocked_by):
    return f"Paused: over its {blocked_by} limit"


def overlay(c, row, default=None):
    """A bot's status row as the pages should read it: paused, and why, while a limit is met (unless it is running)."""
    if not row or row.get("state") in ("running", "quarantined"):
        return row
    met = blocked(c, row["bot"], default=default)
    return {**row, "state": "paused", "focus": why(met)} if met else row


def after_run(c, bot, owner_email="", at=None):
    """Called as a run completes: the one notice when a limit reaches 80% and another at 100%. A notice is sent once
    per bot, period and limit, so raising a limit rearms it; a run that jumps past both sends only the higher."""
    default = company(c)
    limits, _ = effective(c, bot, default)
    if limits["daily_usd"] is None and limits["monthly_usd"] is None:
        return
    when = bounds(at)
    for name, _ in PERIODS:
        cap = limits[name + "_usd"]
        if not cap:
            continue
        key, start, end = when[name]
        amount = spent(c, bot, start, end, default["count_subscription"])
        level = 100 if amount >= cap else WARN if amount >= cap * WARN / 100 else 0
        if not level:
            continue
        period = f"{key}:{cap:g}"
        if c.execute("SELECT 1 FROM usage_alerts WHERE bot=? AND period=? AND level>=?", (bot, period, level)).fetchone():
            continue
        for reached in (WARN, 100):
            if reached <= level:
                c.execute("INSERT OR IGNORE INTO usage_alerts(bot, period, level, sent) VALUES(?,?,?,?)",
                          (bot, period, reached, H.now()))
        notify(c, bot, level, name, amount, cap, owner_email)


def recipients(c, bot, owner_email=""):
    """The person to tell: the bot's operator, else the company owner."""
    row = c.execute("SELECT operator FROM bot_config WHERE bot=?", (bot,)).fetchone()
    person = H.human(c, row["operator"]) if row and row["operator"] else None
    if not person and owner_email:
        owner = c.execute("SELECT id FROM humans WHERE lower(email)=?", (owner_email.lower(),)).fetchone()
        person = H.human(c, owner["id"]) if owner else None
    return person


def notify(c, bot, level, label, amount, cap, owner_email=""):
    person = recipients(c, bot, owner_email)
    name = (H.bot(c, bot) or {}).get("display_name") or bot
    money = f"${amount:,.2f} of ${cap:,.2f}"
    text = (f"{name} is at {level}% of its {label} limit ({money}, estimated)." if level < 100 else
            f"{name} reached its {label} limit ({money}, estimated) and takes no new work until it resets or the limit is raised.")
    if person:
        H.say(c, H.KEEPER, H.human_actor(person["id"]), text, kind="notice")
    H.event(c, H.KEEPER, "usage.limit", H.bot_actor(bot), {"level": level, "period": label, "spent": round(amount, 4), "limit": cap})
