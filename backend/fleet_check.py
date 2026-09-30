"""`hub fleet check`: what is wrong with the bots this person may see, most urgent first (docs/permissions.md scopes it).

Read from the records the server already holds, per bot: not on a computer, its computer offline, failing runs, a
credential it declares but does not have, setup that never finished, paused (and paused over a limit), quarantined.
Each issue says in a plain sentence what is wrong and the one command that fixes it, so BotOps can fix what it may and
report the rest.
"""
from . import bot_tools, usage_limits
from .getting_started import _online_runners
from .store import H

HIGH, MEDIUM, LOW = "high", "medium", "low"
STUCK_SETUP_HOURS = 1
FAILING_HOURS = 24
ORDER = {HIGH: 0, MEDIUM: 1, LOW: 2}


def check(c, who, auth, settings):
    online = {r["id"] for r in _online_runners(c)}
    seen = auth.bot_accesses(c, who)
    since = H.shift(H.now(), hours=-FAILING_HOURS)
    stuck_before = H.shift(H.now(), hours=-STUCK_SETUP_HOURS)
    failed = {r["bot"]: r["n"] for r in c.execute(
        "SELECT bot, count(*) n FROM attempts WHERE state IN ('failed','expired') AND finished>? GROUP BY bot", (since,))}
    assigned = {r["bot"]: (r["runner_id"], r["label"]) for r in c.execute(
        "SELECT a.bot,a.runner_id,r.label FROM assignments a JOIN runners r ON r.id=a.runner_id WHERE r.revoked_at IS NULL")}
    issues = []

    def add(bot, kind, severity, text, fix):
        issues.append({"bot": bot["slug"], "name": bot["display_name"] or bot["slug"], "kind": kind, "severity": severity,
                       "text": text, "fix": fix})

    from .agents import external_harness
    for bot in c.execute("SELECT b.slug,b.display_name,b.state,b.created,bc.onboarding_state FROM bots b "
                         "JOIN bot_config bc ON bc.bot=b.slug WHERE b.state<>'archived' ORDER BY b.slug"):
        slug = bot["slug"]
        if not (seen.get(slug) or {}).get("see"):
            continue
        state, where = bot["state"], assigned.get(slug)
        name = bot["display_name"] or slug
        external = external_harness(c, slug)
        if state == "quarantined":
            add(bot, "quarantined", HIGH, f"{name} is stopped: it did something it may not.", f"hub api POST /api/v2/bots/{slug}/quarantine/clear")
        elif state == "planned":
            if (bot["created"] or "") < stuck_before:
                add(bot, "stuck_setup", MEDIUM, f"{name} is still being set up.", f"hub bot go-live {slug}")
        elif state == "paused":
            reason = (c.execute("SELECT reason FROM bot_status_history WHERE bot=? AND state='paused' ORDER BY since DESC LIMIT 1",
                                (slug,)).fetchone() or {"reason": ""})["reason"] or ""
            if "limit" in reason.lower():
                add(bot, "paused_over_limit", HIGH, f"{name} is paused: it went over a limit.", f"hub bot resume {slug}")
            else:
                add(bot, "paused", LOW, f"{name} is paused.", f"hub bot resume {slug}")
        elif state == "active":
            if not where and not external:
                add(bot, "not_placed", HIGH, f"{name} is on, but no computer runs it.", f"hub bot place {slug}")
            elif where and where[0] not in online:
                add(bot, "computer_offline", HIGH, f"{name} cannot run: its computer, {where[1]}, is offline.", "hub computers")
            if bot["onboarding_state"] == "needs_onboarding" and (bot["created"] or "") < H.shift(H.now(), hours=-24):
                add(bot, "needs_setup", MEDIUM, f"{name} is waiting for its first setup with its owner.", f"hub bot go-live {slug}")
        if state == "active":
            try:
                met = usage_limits.blocked(c, slug, default=usage_limits.company(c))
            except Exception:
                met = None
            if met:
                add(bot, "paused_over_limit", HIGH, f"{name} is paused: it reached its spending limit.",
                    f"hub api PUT usage/limits/{slug} (a card: raising a limit is their click)")
        if failed.get(slug):
            n = failed[slug]
            add(bot, "failing_runs", HIGH if n >= 3 else MEDIUM, f"{name} had {n} failed run{'s' if n != 1 else ''} today.",
                f"hub turns {slug} --since 24h")
        if state in ("active", "paused"):
            try:
                tools = bot_tools.listing(c, settings, slug)["tools"]
            except Exception:
                tools = []
            for tool in tools:
                if tool.get("status") == "problem" and tool.get("env"):
                    add(bot, "missing_credential", HIGH, f"{name} needs {tool.get('name') or tool.get('service')}: {tool['env']} is not set.",
                        f"hub credential request {tool['env']} --for-bot {slug}")
    issues.sort(key=lambda i: (ORDER[i["severity"]], i["name"].lower(), i["kind"]))
    counts = {level: sum(1 for i in issues if i["severity"] == level) for level in (HIGH, MEDIUM, LOW)}
    return {"issues": issues, "counts": counts, "checked": H.now(),
            "bots": sum(1 for s in seen.values() if s.get("see"))}
