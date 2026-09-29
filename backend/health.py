"""The Health page: what needs attention right now, computed from real state on every read.

Nothing here is stored. A check is `ok`, `warn`, `bad`, `info` or `unknown`; `unknown` means the thing
that would tell us is not reporting, which is not the same as fine, and `info` is an optional thing
that is not set up (neither fine nor a problem). Each check may carry fixes,
which the page turns into one-click links. People who are not administrators see counts only.
"""

import json

from . import inbox_isolation, model_login, providers, releases, runner_versions
from .getting_started import _online_runners, _signed_in_runtime, _wanted_runtimes, _person
from .store import H, readiness_document
from .views import roster

QUEUE_MINUTES = 10          # work that has waited this long on a computer that is up is stuck
BACKUP_STALE_HOURS = 6      # the replica normally trails by seconds
RECENT_HOURS = 24
GITHUB_HEALTH = "github:token"
PROXIES = {"cloudflare": "Cloudflare Access", "aws-alb": "an AWS load balancer", "oidc": "OpenID Connect"}


def _fix(label, href="", tab="", click=""):
    return {"label": label, "href": href, "tab": tab, "click": click}


def _check(key, label, status, summary, fixes=()):
    return {"id": key, "label": label, "status": status, "summary": summary, "fixes": list(fixes)}


def _plural(n, one, many=None):
    return f"{n} {one if n == 1 else many or one + 's'}"


def _computers(c, runners_online, settings):
    since = {r["id"] for r in runners_online}
    rows, fleet = [], runner_versions.load(c)
    wanted, assigned = providers.runtimes_needed(c, settings)
    for r in c.execute("SELECT id,label,last_seen,platform,readiness_json FROM runners WHERE revoked_at IS NULL "
                       "ORDER BY label"):
        runtimes = (readiness_document(r["readiness_json"]).get("runtimes") or {})
        rows.append({"id": r["id"], "label": r["label"], "online": r["id"] in since, "last_seen": r["last_seen"],
                     "platform": r["platform"] or "", "update": runner_versions.view(fleet.get(r["id"])),
                     # Only what the company or an assigned bot uses, or what is installed anyway: the
                     # other harnesses are not this computer's business, so they are not listed.
                     "runtimes": [{"name": n, "installed": bool(v.get("installed")),
                                   "needed": n in wanted or n in assigned.get(r["id"], ()),
                                   "ready": bool(v.get("installed")) and v.get("authenticated") == "ready",
                                   "rejected": v.get("authenticated") == "rejected",
                                   "rejected_at": v.get("rejected_at") or "" if v.get("authenticated") == "rejected" else "",
                                   "rejected_reason": v.get("rejected_reason") or "" if v.get("authenticated") == "rejected" else "",
                                   "signable": bool(v.get("installed")) and v.get("authenticated") != "ready"
                                   and n in model_login.RUNTIMES}
                                  for n, v in sorted(runtimes.items())
                                  if v.get("installed") or n in wanted or n in assigned.get(r["id"], ())]})
    return rows


def _unpublished(c):
    """Bots whose local history the runner could not give a GitHub repository (runner/service.py `publish`)."""
    out = []
    for r in c.execute("SELECT readiness_json FROM runners WHERE revoked_at IS NULL"):
        for bot, row in ((readiness_document(r["readiness_json"]).get("bots")) or {}).items():
            for warning in (row or {}).get("warnings") or []:
                if str(warning).startswith("GitHub history not published: "):
                    out.append((bot, str(warning).split(": ", 1)[1][:160]))
    return sorted(set(out))


def _rejected(computers):
    """Online computers whose wanted harness refused its key or login: (computer, runtime, when, why)."""
    return [(x["label"], r["name"], r["rejected_at"], r["rejected_reason"])
            for x in computers if x["online"] for r in x["runtimes"] if r["rejected"] and r["needed"]]


def _rejected_summary(rows):
    """What to do about it; the reason is the harness's own sanitized words, never the key."""
    first = ", ".join(sorted({f"{name} on {label}" for label, name, _, _ in rows}))
    when, why = rows[0][2], rows[0][3]
    return (f"Sign-in rejected for {first}" + (f" at {when}" if when else "") + (f": {why}" if why else ".")
            + " Replace the key in the runner's secrets, or sign in again from Settings > Devices. "
            "It takes no work that needs it until then.")


def _waiting(c, online_ids):
    """Active bots whose computer is offline (or that have none while work is queued), with the
    work stuck behind them, and bots whose queued work is old even though their computer is up."""
    cutoff = H.shift(H.now(), minutes=-QUEUE_MINUTES)
    queued = {r["bot"]: (r["n"], r["oldest"]) for r in c.execute(
        "SELECT bot, count(*) n, min(created) oldest FROM jobs WHERE state='queued' GROUP BY bot")}
    assigned = {r["bot"]: (r["runner_id"], r["label"]) for r in c.execute(
        "SELECT a.bot, a.runner_id, r.label FROM assignments a JOIN runners r ON r.id=a.runner_id "
        "WHERE r.revoked_at IS NULL")}
    waiting, slow = [], []
    for bot in c.execute("SELECT slug,display_name FROM bots WHERE state='active' ORDER BY slug"):
        slug = bot["slug"]
        count, oldest = queued.get(slug, (0, None))
        where = assigned.get(slug)
        row = {"bot": slug, "name": bot["display_name"] or slug, "queued": count, "oldest": oldest,
               "computer": where[1] if where else ""}
        if where and where[0] not in online_ids:
            waiting.append({**row, "reason": "computer_offline"})
        elif not where and count and not online_ids:
            waiting.append({**row, "reason": "no_computer"})
        elif where and count and oldest and oldest < cutoff:
            slow.append(row)
    return waiting, slow


def _github(c, github):
    row = github.row(c) if github else None
    health = c.execute("SELECT last_success,last_error,detail_json FROM service_health WHERE service=?",
                       (GITHUB_HEALTH,)).fetchone()
    recent = H.shift(H.now(), hours=-RECENT_HOURS)
    failure = None
    if health and health["last_error"] and health["last_error"] > recent \
            and health["last_error"] > (health["last_success"] or ""):
        try:
            failure = str(json.loads(health["detail_json"] or "{}").get("message") or "")
        except ValueError:
            failure = ""
    fix = _fix("Open GitHub settings", "#/settings", "cloud")
    if not row:
        return _check("github", "GitHub", "info", "Not connected. Optional: connect it to keep bot work in your GitHub.", [fix])
    if not row["installation_id"]:
        return _check("github", "GitHub", "warn", "The app is created but not installed on your organization.", [fix])
    if failure is not None:
        return _check("github", "GitHub", "bad",
                      "GitHub refused a token in the last day" + (": " + failure if failure else "."), [fix])
    return _check("github", "GitHub", "ok", f"Connected to {row['org']}.")


def _slack(c):
    """Only once the owner has pasted tokens: the gateway reports its own state (backend/slack_app.py)."""
    from . import slack_app
    state = slack_app.status(c)
    if not state["configured"]:
        return None
    fix = _fix("Open Slack settings", "#/settings", "cloud")
    if state["state"] == "connected":
        return _check("slack", "Slack", "ok", "Connected.")
    if state["state"] == "waiting":
        return _check("slack", "Slack", "warn", "Tokens saved; the Slack service has not connected yet. "
                      "Is the slack profile on in COMPOSE_PROFILES?", [fix])
    return _check("slack", "Slack", "bad", "Slack is disconnected" + (": " + state["message"] if state["message"] else "."), [fix])


def _backups(config):
    backup = config.get("backup")
    fix = _fix("Backup settings", "#/settings", "cloud")
    if not isinstance(backup, dict) or not backup.get("mode"):
        return _check("backups", "Backups", "unknown", "This server does not report its backup state.")
    mode = str(backup["mode"]).replace("_", "-")
    last = backup.get("last_replicated_at") or ""
    target = str(backup.get("target_kind") or "")
    if mode == "off":
        return _check("backups", "Backups", "bad", "Backups are off.", [fix])
    if mode in ("local-only", "local"):
        return _check("backups", "Backups", "warn",
                      "Copies stay on this server only. A lost disk loses everything.", [fix])
    if last and last < H.shift(H.now(), hours=-BACKUP_STALE_HOURS):
        return _check("backups", "Backups", "warn", f"Last copy to {target or 'the remote'} was {last}.", [fix])
    if not last:
        return _check("backups", "Backups", "warn", "Set up, but nothing has been copied yet.", [fix])
    return _check("backups", "Backups", "ok", f"Copied to {target or 'a remote'}.")


def _signin(settings):
    kind = settings.proxy_kind
    if kind:
        return _check("signin", "Sign-in", "ok", "People sign in through " + PROXIES.get(kind, kind) + ".")
    if settings.loopback or settings.local_signin:
        return _check("signin", "Sign-in", "ok", "Local sign-in on this machine.")
    return _check("signin", "Sign-in", "warn",
                  "No identity proxy is configured for this address, so people cannot sign in safely.",
                  [_fix("Sign-in settings", "#/settings", "access")])


def _failed(c):
    since = H.shift(H.now(), hours=-RECENT_HOURS)
    rows = c.execute("SELECT bot,state,finished FROM attempts WHERE state IN ('failed','expired') AND finished>? "
                     "ORDER BY finished DESC LIMIT 5", (since,)).fetchall()
    total = c.execute("SELECT count(*) FROM attempts WHERE state IN ('failed','expired') AND finished>?",
                      (since,)).fetchone()[0]
    return total, [{"bot": r["bot"], "state": r["state"], "at": r["finished"]} for r in rows]


def _v(version):
    """A release as people write it, `v0.2.3`, whichever way the source spelled it."""
    version = str(version or "")
    return "v" + version if version[:1].isdigit() else version


def view(c, who, settings, auth, github, config):
    _person(who)
    kind = "owner" if who.role == "owner" else "admin" if auth.bot_admin(who) else "human"
    full = kind != "human"
    online = _online_runners(c)
    online_ids = {r["id"] for r in online}
    computers = _computers(c, online, settings)
    waiting, slow = _waiting(c, online_ids)
    failed, failures = _failed(c)
    checks = []

    if full:
        notice = config.get("update") or {}
        if notice.get("available"):
            checks.append(_check("version", "Version", "warn",
                                 f"{_v(notice.get('latest'))} is available. You are on {_v(releases.version())}.",
                                 [_fix("Update", click="#new-version"), _fix("What is new", "#/changelog")]))
        else:
            checks.append(_check("version", "Version", "ok", f"Running {_v(releases.version())}, the latest we know of."
                                 if notice.get("latest") else f"Running {_v(releases.version())}."))

    unpublished = _unpublished(c) if full else []
    if unpublished:
        checks.append(_check("publish", "Bot history", "warn",
                             "Some bots' history is not on GitHub yet: " + "; ".join(f"{bot} ({why})" for bot, why in unpublished[:3])
                             + ("." if len(unpublished) <= 3 else f"; and {len(unpublished) - 3} more."),
                             [_fix("Open bots", "#/settings", "bots")]))
    fixes = [_fix("Add a computer", "#/settings", "devices")] if full else []
    if not computers:
        checks.append(_check("computers", "Computers", "bad", "No computer is set up. Bots need one to run.", fixes))
    elif not online:
        checks.append(_check("computers", "Computers", "bad", "Every computer is offline.",
                             [_fix("Open Devices", "#/settings", "devices")] if full else []))
    elif len(online) < len(computers):
        off = [x for x in computers if not x["online"]]
        checks.append(_check("computers", "Computers", "warn",
                             f"{len(online)} of {len(computers)} online. Offline: "
                             + ", ".join(x["label"] for x in off) + ".",
                             [_fix("Open Devices", "#/settings", "devices")] if full else []))
    else:
        checks.append(_check("computers", "Computers", "ok", f"{_plural(len(online), 'computer')} online."))

    if full:
        wanted = _wanted_runtimes(providers.load(c, settings))
        signed = _signed_in_runtime(online, wanted)
        rejected = _rejected(computers)
        if not wanted:
            checks.append(_check("models", "Models", "warn", "No AI provider is chosen yet.",
                                 [_fix("Choose providers", "#/settings", "providers")]))
        elif online and not signed and rejected:
            checks.append(_check("models", "Models", "bad", _rejected_summary(rejected),
                                 [_fix("Open Devices", "#/settings", "devices")]))
        elif online and not signed:
            checks.append(_check("models", "Models", "bad", "No online computer is signed in to your model.",
                                 [_fix("Open Devices", "#/settings", "devices")]))
        elif signed and rejected:
            checks.append(_check("models", "Models", "warn", f"{signed} is signed in on another computer. " + _rejected_summary(rejected), [_fix("Open Devices", "#/settings", "devices")]))
        elif signed:
            checks.append(_check("models", "Models", "ok", f"{signed} is signed in."))
        else:
            checks.append(_check("models", "Models", "unknown", "Nothing to check until a computer is online."))

    if full and (versions := runner_versions.health_check(computers)):
        checks.append(versions)
    if waiting:
        names = ", ".join(w["name"] for w in waiting[:5])
        checks.append(_check("waiting", "Bots waiting", "warn" if online else "bad",
                             f"{_plural(len(waiting), 'bot')} cannot run because their computer is offline"
                             + (f": {names}." if full else "."),
                             [_fix("Open Devices", "#/settings", "devices")] if full else []))
    else:
        checks.append(_check("waiting", "Bots waiting", "ok", "Every active bot has a computer that is up."))
    if slow:
        checks.append(_check("queue", "Work queueing", "warn",
                             f"{_plural(len(slow), 'bot')} with work waiting more than {QUEUE_MINUTES} minutes"
                             + (": " + ", ".join(s["name"] for s in slow[:5]) + "." if full else "."),
                             [_fix("Open Runs", "#/runs")] if full else []))
    else:
        checks.append(_check("queue", "Work queueing", "ok", "No work is waiting long."))

    if full and (mixed := inbox_isolation.violations(c, roster(c))):
        checks.append(_check("inbox", "Inbox bots", "warn",
                             "An inbox bot shares a computer with " + "; ".join(
                                 f"{v['label']}: {', '.join(v['inbox'])} beside "
                                 + ", ".join(v["others"] or ["another inbox bot"]) for v in mixed[:3])
                             + ". Its mail key can open every mailbox, so any bot there could read it. "
                             "Add a computer for the inbox bot and move it there.",
                             [_fix("Add a computer", "#/settings", "devices")]))
    if full:
        checks.append(_github(c, github))
        slack = _slack(c)
        if slack:
            checks.append(slack)
        checks.append(_check("backups", "Backups", "ok", "Demo data: there is nothing to back up.")
                      if settings.demo else _backups(config))
        checks.append(_signin(settings))
    checks.append(_check("failed", "Failed runs", "warn" if failed else "ok",
                         f"{_plural(failed, 'run')} failed in the last day." if failed else "No failed runs in the last day.",
                         [_fix("Open Runs", "#/runs")] if failed and full else []))
    return {"audience": kind, "checks": checks, "attention": sum(1 for x in checks if x["status"] in ("warn", "bad")),
            "computers": computers if full else [], "waiting": waiting if full else [], "slow": slow if full else [],
            "failures": failures if full else [], "checked": H.now(),
            # The sidebar's notice reads the same fresh answer, so the two never disagree.
            "update": config.get("update") or {}}


def note_github_token(store, error=None):
    """Called around minting a GitHub token so the page can say the last attempt failed."""
    now = H.now()
    with store.transaction() as c:
        if error:
            c.execute("INSERT INTO service_health(service,last_success,last_error,detail_json) VALUES(?,NULL,?,?) "
                      "ON CONFLICT(service) DO UPDATE SET last_error=excluded.last_error,detail_json=excluded.detail_json",
                      (GITHUB_HEALTH, now, json.dumps({"message": error})))
        else:   # only a recovery is written, so a healthy turn costs no extra write
            c.execute("UPDATE service_health SET last_success=?,last_error=NULL WHERE service=? AND last_error IS NOT NULL",
                      (now, GITHUB_HEALTH))


def install(app, store, auth, settings):
    from fastapi import Request

    from . import onboarding

    @app.get("/api/v2/health")
    def read(request: Request):
        who = request.state.identity
        _person(who)
        github = getattr(request.app.state, "github_app", None)
        with store.read() as c:
            return view(c, who, settings, auth, github, onboarding.config_view(c, settings, who))
