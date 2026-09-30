"""Usage: what the bots' model runs cost, estimated from their token counts (`GET /api/v2/usage`).

Each finished run carries the tokens its runner counted, the model that ran it and, when the model
has a list price (providers.PRICES), an estimated cost in USD. A run on a ChatGPT or Claude sign-in
is `subscription`: it is billed to the plan, so its cost is what the same tokens would cost through
the API, shown apart and never added to the estimate of what was spent. Days are UTC.

Who sees what: the owner and the bot administrators see every bot; anyone else sees the bots they
run or own. A bot's own credentials see nothing here.
"""

from datetime import date, datetime, timedelta, timezone

from fastapi import Request

from . import bot_access as A
from . import providers, views
from .store import H, P, Problem

GROUPS = ("bot", "day", "routine")
MAX_DAYS = 366
TOP_ROUTINES = 10

# Sums over `turns` shared by every grouping. A run with no token counts (a runtime that reports none,
# or one from before usage) still counts as a run.
SUMS = """count(*) AS runs,
  sum(coalesce(t.input_tokens, 0)) AS input_tokens,
  sum(coalesce(t.cached_tokens, 0)) AS cached_tokens,
  sum(coalesce(t.output_tokens, 0)) AS output_tokens,
  sum(CASE WHEN t.billing = 'subscription' THEN 0 ELSE coalesce(t.est_cost_usd, 0) END) AS api_usd,
  sum(CASE WHEN t.billing = 'subscription' THEN coalesce(t.est_cost_usd, 0) ELSE 0 END) AS subscription_usd,
  sum(CASE WHEN coalesce(t.billing, 'api') != 'subscription' AND t.est_cost_usd IS NOT NULL THEN 1 ELSE 0 END) AS api_priced,
  sum(CASE WHEN coalesce(t.billing, 'api') != 'subscription' AND t.est_cost_usd IS NULL
            AND coalesce(t.input_tokens, 0) + coalesce(t.cached_tokens, 0) + coalesce(t.output_tokens, 0) > 0
       THEN 1 ELSE 0 END) AS api_unpriced"""
ROUTINE_JOIN = ("LEFT JOIN schedule_occurrences o ON o.task_id = t.task_id "
                "LEFT JOIN schedules s ON s.id = o.schedule_id")
EMPTY_DAY = {"runs": 0, "input_tokens": 0, "cached_tokens": 0, "output_tokens": 0, "est_cost_usd": 0.0,
             "subscription_equiv_usd": 0.0, "unpriced_runs": 0}


def money(value):
    return round(float(value or 0), 6)


def figures(row):
    """The fields every row shares. `est_cost_usd` is null when the row has API-billed tokens and none
    of them has a price (an unknown model), so the page shows a dash and not a false zero."""
    return {"runs": row["runs"], "input_tokens": row["input_tokens"], "cached_tokens": row["cached_tokens"],
            "output_tokens": row["output_tokens"],
            "est_cost_usd": None if not row["api_priced"] and row["api_unpriced"] else money(row["api_usd"]),
            "subscription_equiv_usd": money(row["subscription_usd"]),
            "unpriced_runs": row["api_unpriced"]}


def spend(item):
    """What ranks a row and sizes its bar: estimated spend plus the API-equivalent of subscription runs."""
    return (item["est_cost_usd"] or 0) + item["subscription_equiv_usd"]


def install(app, store, auth, settings):
    def own_bots(c, who):
        """The slugs `who` may see usage for: every bot for the owner and administrators, else the
        bots they run or own."""
        slugs = {row["slug"] for row in H.bots(c)}
        if auth.bot_admin(who):
            return slugs
        pid = H.actor_id(who.actor)
        mine = set()
        for row in c.execute("SELECT bot, operator, bot_owners_json FROM bot_config"):
            if row["operator"] == pid or pid in A.owner_ids(row["bot_owners_json"]):
                mine.add(row["bot"])
        return mine & slugs

    def window(start, end):
        """(first day, last day) from the query; the default is the last seven days."""
        try:
            last = date.fromisoformat(end) if end else datetime.now(timezone.utc).date()
            first = date.fromisoformat(start) if start else last - timedelta(days=6)
        except ValueError:
            raise Problem("range", "from and to are dates, YYYY-MM-DD", 422)
        if first > last:
            raise Problem("range", "from is after to", 422)
        if (last - first).days >= MAX_DAYS:
            raise Problem("range", f"A range is at most {MAX_DAYS} days", 422)
        return first, last

    def query(c, key, join, slugs, first, last):
        """Grouped sums for the runs that finished in the window on these bots."""
        if not slugs:
            return []
        marks = ",".join("?" * len(slugs))
        sql = (f"SELECT {key} AS k, {SUMS} FROM turns t {join} WHERE t.finished IS NOT NULL AND t.started >= ? "
               f"AND t.started < ? AND t.bot IN ({marks}) GROUP BY k")
        args = [first.isoformat() + "T00:00:00", (last + timedelta(days=1)).isoformat() + "T00:00:00", *sorted(slugs)]
        return c.execute(sql, args).fetchall()

    def totals(rows):
        keys = ("runs", "input_tokens", "cached_tokens", "output_tokens", "api_usd", "subscription_usd",
                "api_priced", "api_unpriced")
        return figures({k: sum(r[k] or 0 for r in rows) for k in keys})

    def routine_row(c, row, names):
        """A routine's title and bot; runs that came from no routine are one `Other runs` row."""
        found = c.execute("SELECT bot, title FROM schedules WHERE id=?", (row["k"],)).fetchone() if row["k"] else None
        return {"routine": row["k"] or None,
                "title": (found["title"] if found else "") or ("Routine" if row["k"] else "Other runs"),
                "bot": found["bot"] if found else None,
                "name": names.get(found["bot"], found["bot"]) if found else None, **figures(row)}

    @app.get("/api/v2/usage")
    def usage(request: Request, group: str = "bot", department: str | None = None, bot: str | None = None):
        """Estimated model spend per bot, per day or per routine over `from`..`to` (UTC dates, default the last
        seven days); `bot` is one bot's daily series and top routines."""
        who = request.state.identity
        auth.domain(who)
        if who.role not in ("owner", "human"):
            raise Problem("forbidden", "Usage is for people", 403)
        first, last = window(request.query_params.get("from"), request.query_params.get("to"))
        if group not in GROUPS:
            raise Problem("group", "group is bot, day or routine", 422)
        with store.read() as c:
            allowed = own_bots(c, who)
            people, configs = views.roster(c), views.entries(c, settings.github_owner)
            depts = {slug: P.team_of(slug, configs, people["teams"]) or "" for slug in allowed}
            names = {row["slug"]: row["display_name"] or row["slug"] for row in H.bots(c)}
            base = {"from": first.isoformat(), "to": last.isoformat(), "prices_as_of": providers.PRICES_AS_OF}
            if bot:
                if bot not in names or not auth.visible_bot(c, who, bot):
                    raise Problem("not_found", "Bot not found", 404)
                if bot not in allowed:
                    raise Problem("forbidden", "Usage is for a bot's owners and administrators", 403)
                daily = {r["k"]: r for r in query(c, "substr(t.started, 1, 10)", "", {bot}, first, last)}
                series = []
                for offset in range((last - first).days + 1):
                    day = (first + timedelta(days=offset)).isoformat()
                    series.append({"day": day, **(figures(daily[day]) if day in daily else EMPTY_DAY)})
                routines = sorted((routine_row(c, r, names) for r in query(c, "coalesce(s.id, '')", ROUTINE_JOIN, {bot}, first, last)),
                                  key=lambda r: (-spend(r), -r["runs"]))
                return {**base, "bot": bot, "name": names[bot], "department": depts.get(bot) or None,
                        "totals": totals(query(c, "'all'", "", {bot}, first, last)), "daily": series,
                        "routines": routines[:TOP_ROUTINES]}
            slugs = {s for s in allowed if not department or depts.get(s) == department}
            total = totals(query(c, "'all'", "", slugs, first, last))
            if group == "bot":
                rows = [{"bot": r["k"], "name": names.get(r["k"], r["k"]), "department": depts.get(r["k"]) or None,
                         **figures(r)} for r in query(c, "t.bot", "", slugs, first, last)]
            elif group == "day":
                rows = [{"day": r["k"], **figures(r)} for r in query(c, "substr(t.started, 1, 10)", "", slugs, first, last)]
            else:
                rows = [routine_row(c, r, names) for r in query(c, "coalesce(s.id, '')", ROUTINE_JOIN, slugs, first, last)]
            whole = spend(total)
            for row in rows:
                row["share"] = round(spend(row) / whole, 4) if whole else 0.0
            if group == "day":
                rows.sort(key=lambda r: r["day"])
            else:
                rows.sort(key=lambda r: (-spend(r), -(r["input_tokens"] + r["cached_tokens"] + r["output_tokens"]), -r["runs"]))
            return {**base, "group": group, "department": department or None, "totals": total, "rows": rows,
                    "departments": sorted({d for d in depts.values() if d})}
