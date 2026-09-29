"""After the wizard: the Getting started checklist, the tour and the section cards.

The checklist is computed from what the database says right now (a runner's last heartbeat, a
bot's row, a finished task), so a step can never be ticked by hand and can never stay ticked
after the thing it names goes away. What a person may do by hand is limited to their own
choices: skipping an optional step, closing the tour, closing a card, hiding the checklist.
Those live in the person's `preferences` row, so each person has their own.
"""

import json
import re

from . import model_login, providers
from .store import H, Problem, encode, readiness_document

PREFERENCE = "onboarding.progress"
BOTOPS = "botops"
MARKET_BOT = "market-analyst"
MARKET_KEY = "market-context"
ONLINE_SECONDS = 120
# Sections whose card a person can close, and the checklist items a person may skip.
CARDS = ("docs", "market", "bots", "tasks", "updates", "goals", "meetings")
OPTIONAL = ("github",)
EMPTY_STATE = {"tour": False, "checklist": False, "skipped": [], "cards": []}


def _person(who):
    if who.role not in ("owner", "human"):
        raise Problem("forbidden", "Getting started is for people, not machines or bots", 403)


def _owner(who, what):
    if who.role != "owner":
        raise Problem("forbidden", "Only the owner " + what, 403)


def load_state(c, who):
    row = c.execute("SELECT value_json FROM preferences WHERE actor=? AND key=?",
                    (who.actor, PREFERENCE)).fetchone()
    try:
        stored = json.loads(row[0]) if row else {}
    except ValueError:
        stored = {}
    stored = stored if isinstance(stored, dict) else {}
    return {"tour": bool(stored.get("tour")), "checklist": bool(stored.get("checklist")),
            "skipped": [k for k in stored.get("skipped") or [] if k in OPTIONAL],
            "cards": [k for k in stored.get("cards") or [] if k in CARDS]}


def save_state(c, who, state):
    c.execute("INSERT INTO preferences(actor,key,value_json,updated) VALUES(?,?,?,?) "
              "ON CONFLICT(actor,key) DO UPDATE SET value_json=excluded.value_json, updated=excluded.updated",
              (who.actor, PREFERENCE, encode(state), H.now()))


def change_state(c, who, body):
    _person(who)
    state = load_state(c, who)
    if body.tour is not None:
        state["tour"] = body.tour
    if body.checklist is not None:
        state["checklist"] = body.checklist
    if body.card:
        if body.card not in CARDS:
            raise Problem("kind", "A card is one of " + ", ".join(CARDS), 422)
        state["cards"] = sorted({*state["cards"], body.card})
    if body.skip:
        if body.skip not in OPTIONAL:
            raise Problem("kind", "Only optional steps can be skipped: " + ", ".join(OPTIONAL), 422)
        state["skipped"] = sorted({*state["skipped"], body.skip})
    save_state(c, who, state)
    return state


# ------------------------------------------------------------------ live checks
def _online_runners(c):
    since = H.shift(H.now(), seconds=-ONLINE_SECONDS)
    return c.execute("SELECT id,label,readiness_json FROM runners WHERE revoked_at IS NULL "
                     "AND last_seen>? ORDER BY last_seen DESC", (since,)).fetchall()


_wanted_runtimes = providers.wanted_runtimes


def _signed_in_runtime(runners, wanted):
    for runner in runners:
        for name, row in (readiness_document(runner["readiness_json"]).get("runtimes") or {}).items():
            if name in wanted and row.get("installed") and row.get("authenticated") == "ready":
                return name
    return ""


def _login_target(runners, wanted):
    """A computer that has a wanted runtime installed but not signed in, and that the browser
    can sign in (backend/model_login.py): where the checklist's Sign in button goes."""
    for runner in runners:
        for name, row in sorted((readiness_document(runner["readiness_json"]).get("runtimes") or {}).items()):
            if name in wanted and name in model_login.RUNTIMES and row.get("installed") \
                    and row.get("authenticated") != "ready":
                return {"runner_id": runner["id"], "runtime": name, "machine": runner["label"]}
    return None


def own_bots(c, settings):
    """Bots the company added, as opposed to the three built in."""
    bootstrap = {settings.assistant_bot, BOTOPS, "librarian"}
    return [row["slug"] for row in c.execute("SELECT slug FROM bots WHERE state!='archived' ORDER BY slug")
            if row["slug"] not in bootstrap]


def _next_bot(c, settings):
    """The starter bot to set up next: parked (`needs_onboarding`), in the order first run put them, which
    puts the one matching the top pain first. Returns (slug, name, why), or None when nothing is waiting."""
    from . import onboarding
    rows = c.execute("SELECT bc.bot,b.display_name,bc.config_json FROM bot_config bc JOIN bots b ON b.slug=bc.bot "
                     "WHERE bc.onboarding_state='needs_onboarding' AND b.state!='archived'").fetchall()
    if not rows:
        return None
    ranked = sorted(((json.loads(row["config_json"] or "{}"), row) for row in rows),
                    key=lambda pair: (pair[0].get("setup_rank", 999), pair[1]["bot"]))
    config, row = ranked[0]
    answers = onboarding.load(c)["answers"]
    card = next((card for card in onboarding.read_cards(settings) if card["template"] == config.get("template")), None)
    score, pain = onboarding.pain_match(card, answers.get("pains"), " ".join(
        [answers.get("pains_text") or "", answers.get("repetitive_work") or ""])) if card else (0, "")
    why = ("It matches what hurts most: \"" + pain + "\". " if pain else "") \
        + "Press Start setup on its page and answer its questions; it drafts a first result for you to approve."
    return row["bot"], row["display_name"], why


def _first_output(c):
    """A starter bot has been onboarded: a person approved its first routine, which is its first
    reviewed output. The bot says so itself (`hub bot onboarded`), so this is what the database records."""
    return c.execute("SELECT bc.bot FROM bot_config bc JOIN bots b ON b.slug=bc.bot "
                     "WHERE bc.onboarding_state='onboarded' AND b.state!='archived' LIMIT 1").fetchone()


def _item(key, label, done, why, href="", tab="", optional=False, action="", login=None):
    return {"id": key, "label": label, "done": bool(done), "optional": optional,
            "why": "" if done else why, "href": href, "tab": tab, "action": action,
            **({"login": login} if login and not done else {})}


def checklist(c, who, settings, github):
    record = providers.load(c, settings)
    runners = _online_runners(c)
    wanted = _wanted_runtimes(record)
    signed = _signed_in_runtime(runners, wanted)
    login = (providers.PROVIDER_BY_RUNTIME.get(next(iter(sorted(wanted)), ""), {}) or {}).get("login", "")
    botops = H.bot(c, BOTOPS)
    mine = own_bots(c, settings)
    building = c.execute("SELECT id FROM tasks WHERE owner=? AND title LIKE 'Build a bot:%' "
                         "AND status NOT IN ('done','closed','declined') ORDER BY created DESC LIMIT 1",
                         ("bot:" + BOTOPS,)).fetchone()
    installed = bool(github and github["installation_id"])
    waiting = _next_bot(c, settings)
    items = [
        _item("signed_in", "Signed in", True, ""),
        _item("computer", "A computer is online", runners,
              "Bots run on a computer you set up. Add one and keep it awake.", "#/settings", "devices"),
        _item("model", "A model is signed in on it", signed,
              ("Sign in to a model on the computer" + (" (run `" + login + "`)" if login else "") + "."
               if wanted else "Choose your AI providers first."),
              "#/settings", "devices" if wanted else "providers", login=_login_target(runners, wanted)),
        _item("github", "GitHub is connected", installed,
              "Lets bots keep their work in your GitHub.", "#/settings", "cloud", optional=True),
        _item("botops", "BotOps is active", botops and botops["state"] == "active",
              "BotOps builds your other bots. It starts once a computer hosts it.", "#/bot/" + BOTOPS),
        _item("first_bot", "Create your first bot", mine,
              "BotOps is building it." if building else "Say what it should do and BotOps builds it.",
              "#/task/" + building["id"] if building else "", action="" if building else "create-bot"),
        _item("next_bot", "Set up " + waiting[1] if waiting else "No bot is waiting for setup", not waiting,
              waiting[2] if waiting else "", "#/bot/" + waiting[0] if waiting else ""),
        _item("first_output", "First approved output", _first_output(c),
              "Set up a starter bot and approve the first thing it drafts. That is the point of the team.",
              "#/bot/" + waiting[0] if waiting else "#/tasks"),
        _item("first_update", "Your first update arrived",
              c.execute("SELECT 1 FROM updates LIMIT 1").fetchone(),
              "Each active bot posts a short update every day.", "#/updates"),
    ]
    return items


# What each kind of person needs to see: the owner all of it, bot administrators what involves
# bots, everyone else only what they can act on or read.
AUDIENCE = {"owner": None,
            "admin": {"signed_in", "botops", "first_bot", "next_bot", "first_output", "first_update"},
            "human": {"signed_in", "first_output", "first_update"}}


def empty_sections(c):
    """Sections with nothing in them yet: their card stays until they have content or the person
    chooses "don't show again". The market counts once the company's own answers are saved."""
    def none(sql):
        return c.execute(sql).fetchone() is None
    return {"docs": none("SELECT 1 FROM docs WHERE archived=0 LIMIT 1") and none("SELECT 1 FROM linked_docs WHERE archived=0 LIMIT 1"),
            "market": none("SELECT 1 FROM market_entities LIMIT 1")
            and none(f"SELECT 1 FROM registry_metadata WHERE key='{MARKET_KEY}'"),
            "tasks": none("SELECT 1 FROM tasks LIMIT 1"), "updates": none("SELECT 1 FROM updates LIMIT 1"),
            "goals": none("SELECT 1 FROM goals LIMIT 1"), "meetings": none("SELECT 1 FROM meetings LIMIT 1")}


def view(c, who, settings, auth, github=None):
    _person(who)
    state = load_state(c, who)
    kind = "owner" if who.role == "owner" else "admin" if auth.bot_admin(who) else "human"
    allowed = AUDIENCE[kind]
    items = [i for i in checklist(c, who, settings, github) if allowed is None or i["id"] in allowed]
    for item in items:
        item["skipped"] = item["optional"] and not item["done"] and item["id"] in state["skipped"]
    settled = [i for i in items if i["done"] or i["skipped"]]
    return {"items": items, "done": len(settled), "total": len(items),
            "complete": len(settled) == len(items), "dismissed": state["checklist"],
            "tour_seen": state["tour"], "cards_dismissed": state["cards"],
            "can_build": auth.bot_admin(who), "owner": who.role == "owner",
            "empty": empty_sections(c)}


# ------------------------------------------------------------------ actions
def _slug(text, taken):
    base = re.sub(r"[^a-z0-9]+", "-", str(text).lower()).strip("-")[:32].strip("-") or "new-bot"
    slug, n = base, 2
    while slug in taken:
        slug, n = base + "-" + str(n), n + 1
    return slug


def _task(c, auth, who, owner, title, body):
    from . import rooms
    return H.task_create(c, who.actor, title, body, "bot:" + owner, allow_planned=True,
                         conversation_id=rooms.task_conversation_id(c, auth, "bot:" + owner, who.actor))


def _active(c, slug):
    bot = H.bot(c, slug)
    return bot if bot and bot["state"] == "active" else None


def _botops(c):
    if not _active(c, BOTOPS):
        raise Problem("botops", "BotOps is not active yet. It starts once a computer hosts it.", 409)


def _company(c):
    from . import onboarding
    return "\n".join(onboarding._answer_lines(onboarding.load(c)["answers"]))


def _host(c, who):
    """The computer a requested bot goes on: the one hosting BotOps, else the single online
    computer. None when neither is clear or it is another person's; the task then says so."""
    row = c.execute("SELECT r.id,r.operator FROM assignments a JOIN runners r ON r.id=a.runner_id "
                    "WHERE a.bot=? AND r.revoked_at IS NULL", (BOTOPS,)).fetchone()
    if not row:
        online = _online_runners(c)
        row = c.execute("SELECT id,operator FROM runners WHERE id=?", (online[0]["id"],)).fetchone() \
            if len(online) == 1 else None
    if row and (who.role == "owner" or row["operator"] == H.actor_id(who.actor)):
        return row
    return None


def _planned_bot(c, settings_admin, settings, who, slug, name, what):
    """The server record BotOps cannot create for itself: without it the bot is invisible to
    the org chart and to routines. It stays planned; activating it is a person's call."""
    from . import models as M
    owner = settings_admin.auth.owner_id(c)
    _, model = providers.resolve(providers.load(c, settings))
    choice = settings_admin.models.get(model) or {}
    host = _host(c, who)
    first = re.split(r"(?<=[.!?])\s", what.strip(), maxsplit=1)[0]
    settings_admin.create_bot(c, who, M.BotDefinitionCreate(
        slug=slug, display_name=name, description=first[:300], status="planned",
        reports_to="human:" + owner if owner and H.human(c, owner) else None,
        model=model, effort=choice.get("default_effort") or "medium",
        owners=[H.actor_id(who.actor)], runner_id=host["id"] if host else None))
    return host


def create_bot(c, auth, who, body, settings_admin=None, settings=None):
    if not auth.bot_admin(who):
        raise Problem("forbidden", "Only the owner or a bot administrator may ask for a new bot", 403)
    _botops(c)
    taken = {row["slug"] for row in c.execute("SELECT slug FROM bots")}
    source = body.name or " ".join(body.what.split()[:3])
    slug = _slug(source, taken)
    name = body.name or slug.replace("-", " ").title()
    # The hub refuses a second live task with the same title, so a repeat name says its slug.
    title = "Build a bot: " + name + (" (" + slug + ")" if slug != _slug(source, set()) else "")
    host = _planned_bot(c, settings_admin, settings, who, slug, name, body.what)
    placed = ("- computer: assigned (the one that hosts BotOps, or the only one online)" if host else
              "- computer: not assigned. Neither BotOps's computer nor a single online one was "
              "clear, so leave placement to the owner.")
    text = "\n".join([
        "Build a new bot for us: " + name + ".", "",
        "What it should do, in the owner's words:", "", body.what, "",
        "- slug: " + slug, "- display name: " + name,
        "- template: none chosen. Pick the closest one in the catalog, or tailor AGENT.md to the job.",
        "- hub record: already created, state planned, repository emp-" + slug + ". Do not create "
        "another. Build the repository, attach its daily and weekly routines and get it ready; "
        "leave it planned, the owner activates it.", placed,
        "", "What the company told us during onboarding:", _company(c)])
    task = _task(c, auth, who, BOTOPS, title, text)
    H.event(c, who.actor, "getting_started.bot_requested", slug, {"task": task["id"]})
    return {"task_id": task["id"], "slug": slug, "name": name}


def docs_links(c, who, body):
    """The links pasted into the Docs card: each becomes a linked doc (backend/docs.py). Tico keeps no
    copy of what they point to. A repeat, or an address that is not a web address, is reported and skipped."""
    from . import docs
    _owner(who, "sets up the company's docs")
    if not body.links:
        raise Problem("kind", "Paste at least one link", 422)
    linked, skipped = [], []
    for item in body.links:
        try:
            linked.append(docs.add_link(c, who.actor, docs.LinkCreate(url=item.url, description=item.description)))
        except Problem as exc:
            if exc.code not in ("already_linked", "validation"):
                raise
            skipped.append({"url": item.url, "reason": exc.detail})
    H.event(c, who.actor, "getting_started.docs_linked", "docs", {"linked": len(linked), "skipped": len(skipped)})
    return {"linked": linked, "skipped": skipped}


def market_context(c, auth, who, body):
    _owner(who, "sets up the market")
    if not _active(c, MARKET_BOT):
        _botops(c)
        if not body.add_analyst:
            # Adding a bot is a bigger step than answering four questions, so it is asked for first.
            raise Problem("confirm_analyst", "The Market Analyst is not set up yet. BotOps can add it "
                          "first; confirm to go ahead.", 409, extra={"needs_analyst": True})
    context = {"sells": body.sells, "customers": body.customers, "competitors": body.competitors,
               "channels": body.channels, "updated": H.now(), "updated_by": who.actor}
    c.execute("INSERT INTO registry_metadata VALUES(?,?) ON CONFLICT(key) DO UPDATE SET "
              "value_json=excluded.value_json", (MARKET_KEY, encode(context)))
    lines = ["- what we sell: " + body.sells, "- who to: " + body.customers,
             "- main competitors: " + (body.competitors or "not answered"),
             "- where customers talk online: " + (body.channels or "not answered")]
    if _active(c, MARKET_BOT):
        target, title = MARKET_BOT, "Start the market research"
        text = "\n".join(["Start the first pass of our market from what the owner told us.", "", *lines, "",
                          "Add the competitors and channels as entities, cite what you find, and write the "
                          "overview page."])
    else:
        _botops(c)
        target, title = BOTOPS, "Set up the Market Analyst"
        text = "\n".join(["Set up market-analyst from the market template so we can research our market.", "",
                          "- slug: market-analyst", "- template: market", "- display name: Market Analyst", "",
                          "What the owner told us about the market. Put it in the bot's task list "
                          "once it is running:", "", *lines])
    task = _task(c, auth, who, target, title, text)
    H.event(c, who.actor, "getting_started.market_requested", target, {"task": task["id"]})
    return {"task_id": task["id"], "bot": target, "needs_analyst": target == BOTOPS}


def install(app, store, auth, mutate, settings, settings_admin):
    from fastapi import Request

    from . import models as M

    @app.get("/api/v2/getting-started")
    def read(request: Request):
        who = request.state.identity
        _person(who)
        github = getattr(request.app.state, "github_app", None)
        with store.read() as c:
            return view(c, who, settings, auth, github.row(c) if github else None)

    @app.post("/api/v2/getting-started/state")
    def state(request: Request, body: M.GettingStartedState):
        who = request.state.identity
        return mutate(request, body, lambda c: change_state(c, who, body))

    @app.post("/api/v2/getting-started/bot")
    def bot(request: Request, body: M.GettingStartedBot):
        who = request.state.identity
        _person(who)
        return mutate(request, body, lambda c: create_bot(c, auth, who, body, settings_admin, settings))

    @app.post("/api/v2/getting-started/docs")
    def docs(request: Request, body: M.GettingStartedDocs):
        who = request.state.identity
        _person(who)
        return mutate(request, body, lambda c: docs_links(c, who, body))

    @app.post("/api/v2/getting-started/market")
    def market(request: Request, body: M.GettingStartedMarket):
        who = request.state.identity
        _person(who)
        return mutate(request, body, lambda c: market_context(c, auth, who, body))
