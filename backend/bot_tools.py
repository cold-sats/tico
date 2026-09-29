"""The Tools row on a bot's page: what the bot uses, at a glance (docs/creating-bots.md, "What people
see about a bot's tools").

Three sources make the list, none of them a secret. The model and harness the bot runs on come from
its stored config and the company's provider choice. Its repository comes from the bot's record. The
rest are the `access:` entries of its employee.yaml, which the runner reads from the bot's checkout
and reports on every heartbeat with whether each credential is on its computer
(runner/declared_access.py, `bots.<bot>.tools` in the readiness report). A runner from before that
report yields the first two only. No value ever passes through here: env is a variable's name.
"""

from fastapi import Request

from . import providers
from .harnesses import EXTERNAL_HARNESSES, resolve_harness
from .store import H, Problem, readiness_document, repo_url

ONLINE_WITHIN_S = 60

HARNESS_NAMES = {"codex": "Codex", "claude": "Claude Code", "gemini": "Gemini CLI", "antigravity": "Antigravity",
                 "grok": "Grok Build", "pi": "pi", "cursor": "Cursor", "hermes": "Hermes", "grokbot": "Grok Bot"}
PROVIDER_LOGOS = {"openai": "openai", "anthropic": "anthropic", "google": "google"}

SERVICE_NAMES = {
    "github": "GitHub", "github-app": "GitHub App", "slack": "Slack", "gmail": "Gmail", "google-calendar": "Google Calendar",
    "google-drive": "Google Drive", "google-workspace": "Google Workspace", "google-workspace-admin": "Google Workspace admin",
    "google-ads": "Google Ads", "meta-ads": "Meta Ads", "posthog": "PostHog", "mongodb": "MongoDB", "postgres": "PostgreSQL",
    "postgresql": "PostgreSQL", "mysql": "MySQL", "mariadb": "MariaDB", "sqlite": "SQLite", "openai": "OpenAI",
    "anthropic": "Anthropic", "notion": "Notion", "linear": "Linear", "stripe": "Stripe", "aws": "AWS", "s3": "Amazon S3",
    "cloudflare": "Cloudflare", "zoom": "Zoom", "fireflies": "Fireflies", "linkedin": "LinkedIn", "x": "X", "reddit": "Reddit",
    "close-crm": "Close CRM", "calendly": "Calendly", "brex": "Brex", "mercury": "Mercury", "web-search": "Web search",
    "hugging-face": "Hugging Face", "elevenlabs": "ElevenLabs", "heygen": "HeyGen", "xai": "xAI", "gemini": "Gemini",
}
# The logo a service is drawn with: a Simple Icons slug for a mark ui/tool-icons.js bundles (or fireflies, which
# Simple Icons lacks: a frontend without one draws the name's first two letters). Anything else has none.
LOGO_KEYS = {
    "github": "github", "github-app": "github", "slack": "slack", "gmail": "gmail", "google-calendar": "googlecalendar",
    "google-drive": "googledrive", "google-workspace": "google", "google-workspace-admin": "google", "posthog": "posthog",
    "mongodb": "mongodb", "postgres": "postgresql", "postgresql": "postgresql", "mysql": "mysql", "openai": "openai",
    "anthropic": "anthropic", "notion": "notion", "linear": "linear", "stripe": "stripe", "aws": "amazonaws",
    "s3": "amazonaws", "cloudflare": "cloudflare", "zoom": "zoom", "fireflies": "fireflies",
}


def service_name(service):
    key = str(service or "").strip().lower()
    return SERVICE_NAMES.get(key) or key.replace("-", " ").replace("_", " ").title() or "Tool"


def _unique(used, base):
    name, n = base, 1
    while name in used:
        n += 1
        name = f"{base}-{n}"
    used.add(name)
    return name


def _model_tool(c, settings, bot, config, readiness, label):
    row = H.bot(c, bot) or {}
    runtime, model = providers.bot_choice(c, settings, config)
    runtime = runtime or row.get("runtime") or ""
    harness = resolve_harness(config, runtime)
    model = model or row.get("model") or ""
    catalog = providers.MODEL_BY_ID.get(model) or {}
    provider = catalog.get("provider") or ""
    scope = {}
    effort = config.get("reasoning_effort") or config.get("effort") or row.get("effort")
    if effort and effort != "as-configured":
        scope["effort"] = str(effort)
    fallback = config.get("fallback")
    if isinstance(fallback, dict) and fallback.get("model"):
        scope["fallback"] = "/".join(str(fallback[k]) for k in ("harness", "model") if fallback.get(k))
    status, problem = "unknown", ""
    state = (readiness.get("runtimes") or {}).get(runtime) if harness not in EXTERNAL_HARNESSES else None
    if isinstance(state, dict):
        if not state.get("installed"):
            status, problem = "problem", "Runtime is not installed on " + label
        elif state.get("authenticated") in ("missing", "failed", "rejected"):
            status, problem = "problem", state.get("detail") or "Runtime is not signed in on " + label
        else:
            status = "ready"
    tool = {"id": "model", "service": harness or runtime or "model", "name": HARNESS_NAMES.get(harness) or harness.title() or "Model",
            "logo_key": PROVIDER_LOGOS.get(provider), "identity": (provider + "/" + model) if provider and model else model,
            "can": ["use"], "scope": scope, "note": "", "status": status,
            "detail": "The AI model and harness this bot's turns run on."}
    if problem:
        tool["problem"] = problem
    return tool


def _repo_tool(settings, bot, repo, report):
    """The bot's own repository, when it has a browsable address."""
    url = repo_url(repo or "emp-" + bot, settings.github_owner)
    if not url:
        return None
    name = (url.split("github.com/", 1)[-1] if "github.com/" in url else url).removesuffix(".git")
    tool = {"id": "repo", "service": "github", "name": "GitHub", "logo_key": "github", "identity": name,
            "can": [], "scope": {"repo": name}, "note": "", "url": url,
            "status": "unknown", "detail": "The repository that holds this bot's instructions and memory."}
    if report.get("repository_present") is True:
        tool["status"] = "ready"
    elif report.get("repository_present") is False:
        tool["status"], tool["problem"] = "problem", "Repository is not checked out on the bot's computer"
    return tool


def _declared_tool(entry, used, label):
    service = str(entry.get("service") or "")
    env, credential = entry.get("env") or "", entry.get("credential") or "not-declared"
    status, problem, detail = "unknown", entry.get("problem") or "", ""
    if credential == "present":
        status, detail = "ready", f"{env} is set on {label}"
    elif credential == "missing":
        status, problem = "problem", problem or f"Credential missing on {label}"
    elif credential == "hub-vault":
        detail = "Granted through the credential vault; it arrives when a run starts"
    else:
        detail = "No credential is declared, so there is nothing to check"
    if problem:
        status = "problem"
    tool = {"id": _unique(used, service.lower() or "tool"), "service": service, "name": service_name(service),
            "logo_key": LOGO_KEYS.get(service.strip().lower()), "identity": entry.get("identity") or "",
            "can": list(entry.get("can") or []), "scope": dict(entry.get("scope") or {}), "env": env,
            "note": entry.get("note") or "", "status": status, "detail": detail}
    if problem:
        tool["problem"] = problem
    return tool


def listing(c, settings, bot):
    """Everything the row shows for one bot, from records this server already holds."""
    row = c.execute("SELECT config_json,repo FROM bot_config WHERE bot=?", (bot,)).fetchone()
    config = H._json(row["config_json"], {}) if row else {}
    config = config if isinstance(config, dict) else {}
    runner = c.execute("SELECT r.label,r.last_seen,r.revoked_at,r.readiness_json FROM assignments a "
                       "JOIN runners r ON r.id=a.runner_id WHERE a.bot=?", (bot,)).fetchone()
    readiness = readiness_document(runner["readiness_json"]) if runner else {}
    report = (readiness.get("bots") or {}).get(bot)
    report = report if isinstance(report, dict) else {}
    label = (runner["label"] if runner else "") or "its computer"
    online = bool(runner and not runner["revoked_at"] and runner["last_seen"]
                  and runner["last_seen"] > H.shift(H.now(), seconds=-ONLINE_WITHIN_S))
    used = {"model", "repo"}
    declared = [_declared_tool(entry, used, label) for entry in report.get("tools") or [] if isinstance(entry, dict)]
    tools = [_model_tool(c, settings, bot, config, readiness, label)]
    # A declared GitHub access names the repository itself; a second GitHub icon would say nothing new.
    repo = None if any(tool["service"].lower() in ("github", "github-app") for tool in declared) \
        else _repo_tool(settings, bot, row and row["repo"], report)
    if repo:
        tools.append(repo)
    return {"bot": bot, "tools": tools + declared, "computer": label if runner else None, "online": online,
            "reported_at": runner["last_seen"] if runner else None}


def install(app, store, auth):
    @app.get("/api/v2/bots/{bot}/tools")
    def bot_tools(request: Request, bot: str):
        who = request.state.identity
        auth.domain(who)
        with store.read() as c:
            if not auth.visible_bot(who, bot):      # access: read
                raise Problem("forbidden", "This bot is private", 403)
            if not H.bot(c, bot):
                raise Problem("not_found", "Bot not found", 404)
            return listing(c, store.settings, bot)
