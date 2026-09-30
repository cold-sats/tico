"""First run: the catalog people pick bots from, and the record of what they chose.

A company starts with three built-in bots: the assistant, which is each person's private Assistant
chat (backend/assistant.py) and works in the background (Slack routing, meetings' Auto delivery),
BotOps, which builds every other bot, and the Librarian, which answers questions from the company's
docs (backend/librarian.py). Onboarding names the company, asks the first-run questions, chooses at most
five starter templates against the answers (`choose`), and on completion defines the chosen bots. A
starter is created at once, `needs_onboarding`, and its repository is materialized by the computer;
every other template is still a task for BotOps. Nothing here reaches a machine: it writes definitions
and tasks.
"""

import json
import re
from pathlib import Path
from types import SimpleNamespace

import yaml

from . import goals as G
from . import models as M
from . import providers
from . import releases, replication, runner_versions
from . import rooms, routines
from . import access as Access
from .store import H, Problem, encode, readiness_document

KEY = "onboarding"
BOTOPS = "botops"
LIBRARIAN = "librarian"
ASSISTANT_TEMPLATE_SLUG = "coo"
CARD_FILE = "card.yaml"
INSTRUCTIONS_FILE = "AGENT.md"
# Filled wherever a person reads a card: a template names itself after the assistant, and
# its AGENT.md is written against the company that is about to adopt it. The wizard no longer
# asks for assistant_name; an empty one falls back to TICO_ASSISTANT_NAME (display_names).
PLACEHOLDERS = ("company_name", "app_name", "assistant_name", "bot_name")
# Which catalog tag each answer implies. The free-text answers are never parsed: BotOps and
# the owner read them, the recommender does not.
WORK_ARRIVES = {"email": ("uses_email",), "slack": ("uses_slack",), "crm": ("uses_crm",),
                # A ticket queue is a support inbox; one answer earns both tags.
                "tickets": ("uses_tickets", "has_support_inbox")}
SMALL_TEAM = 10
# The starter team is the best pain matches, what a ticked tool names outright and the always-useful
# Chief of Staff: about three to five bots. It is a starting point, not a limit: the full org chart
# proposes every template that fits, and either can be edited freely before Create.
STARTER_TEAM_MAX = 5
MAX_PAIN_PICKS = 2
# A card's `pack` is the team it sits in on the org chart. Teams appear in this order.
TEAMS = {"basics": "Leadership", "sales": "Sales", "marketing": "Marketing", "support": "Support",
         "operations": "Operations", "engineering": "Engineering"}
OTHER_TEAM = "Other"
NEEDS_ONBOARDING = "needs_onboarding"
ONBOARDED = "onboarded"
# What each ticked tool implies, as catalog tags (`recommend_when`) and as a prerequisite a card lists.
TOOL_TAGS = {"mail": ("uses_email",), "chat": ("uses_slack",), "crm": ("uses_crm", "has_pipeline"),
             "github": ("uses_github",), "meetings": ("uses_meetings",), "docs": ("uses_docs",)}
# A ticked tool that names a starter outright: it recommends the card even with no matching pain.
SIGNAL_TAGS = {"uses_github": "You use GitHub", "uses_meetings": "You use a meetings importer"}
# Tools every company has whatever it ticked (Tico itself, the public web and its calendar).
ALWAYS_TOOLS = ("hub", "web", "calendar")
# Older answers said where work arrives; each implies a tool.
WORK_TOOLS = {"email": "mail", "slack": "chat", "crm": "crm", "tickets": "mail"}
STOP_WORDS = frozenset("""a an and are as at be but by can do does for from get gets had has have how i if in into is it its
just like more most much my no not of on one or our out over so than that the their them then there these they this those
to too up us was we were what when where which who why will with without you your really still every again things thing
going about people""".split())

EMPTY_NAMES = {"company_name": "", "app_name": "", "assistant_name": ""}
EMPTY_ANSWERS = {"what_we_do": "", "customers": "", "team_size": "", "work_arrives": [],
                 "repetitive_work": "", "never_without_person": [], "pains": [], "pains_text": "",
                 "tools": [], "software_product": ""}
ANSWER_LABELS = (("what_we_do", "What we do"), ("customers", "Customers"),
                 ("team_size", "Team size"), ("work_arrives", "Work arrives by"),
                 ("repetitive_work", "Repetitive work"), ("pains", "Top pains"),
                 ("pains_text", "In their words"), ("tools", "Tools they use"),
                 ("software_product", "Software is the product"),
                 ("never_without_person", "Never without a person"))


def _json(value, fallback=None):
    try:
        return json.loads(value) if isinstance(value, str) else value
    except (TypeError, ValueError):
        return fallback


def _line(item):
    """One list entry as a sentence. YAML reads `- The watchlist: names, queries` as a mapping;
    a card author meant the sentence, so it is put back together rather than shown as a dict."""
    if isinstance(item, dict):
        return "; ".join(f"{key}: {text}" for key, text in item.items())
    return str(item)


def _strings(value, limit=50):
    return [line for line in map(_line, value) if line][:limit] if isinstance(value, list) else []


def fill(text, names, bot_name=""):
    """Replace the four template placeholders with this company's own words."""
    values = {**names, "bot_name": bot_name}
    for key in PLACEHOLDERS:
        text = str(text).replace("{{" + key + "}}", str(values.get(key) or ""))
    return text


def render(card, names, bot_name=""):
    """One card as a person reads it. A card is written for whichever company adopts it, so
    every word it shows carries the placeholders, not only its AGENT.md."""
    name = fill(bot_name or card["name"], names)
    return {**card, "name": name,
            "summary": fill(card["summary"], names, name),
            "instructions": fill(card["instructions"], names, name),
            "owns": [fill(item, names, name) for item in card["owns"]],
            "never": [fill(item, names, name) for item in card["never"]]}


def _prerequisites(value):
    """`{tool, why, required}` rows; anything else in the list is left out rather than guessed at."""
    rows = []
    for item in value if isinstance(value, list) else []:
        if isinstance(item, dict) and str(item.get("tool") or "").strip():
            rows.append({"tool": str(item["tool"]).strip(), "why": str(item.get("why") or ""),
                         "required": bool(item.get("required"))})
    return rows[:12]


def _routine(value):
    value = value if isinstance(value, dict) else {}
    return {"title": str(value.get("title") or ""), "cadence": str(value.get("cadence") or "")} if value else {}


def _card(document, instructions):
    """One card.yaml as the API serves it: every field present, nothing extra."""
    template = str(document.get("template") or "").strip()
    return {"template": template, "slug": str(document.get("slug") or template).strip(),
            "name": str(document.get("name") or template), "required": bool(document.get("required")),
            "bootstrap": bool(document.get("bootstrap")),
            # The template that leads its pack's team in the full org chart (one per pack).
            "lead": bool(document.get("lead")),
            # Checked when the wizard first shows the card, and `when` says who wants it.
            "default": bool(document.get("default")), "when": str(document.get("when") or ""),
            "summary": str(document.get("summary") or ""),
            "owns": _strings(document.get("owns")), "never": _strings(document.get("never")),
            "runtime": str(document.get("runtime") or ""), "model": str(document.get("model") or ""),
            "reasoning_effort": str(document.get("reasoning_effort") or ""),
            "recommend_when": _strings(document.get("recommend_when")),
            # What a chooser reads from a starter template (docs/starter-bots.md). A card with a first
            # routine and an onboarding conversation is a starter; the others are built by BotOps.
            "pack": str(document.get("pack") or ""), "pains": _strings(document.get("pains")),
            "prerequisites": _prerequisites(document.get("prerequisites")),
            "first_routine": _routine(document.get("first_routine")),
            "approval_required": _strings(document.get("approval_required")),
            "starter": bool(document.get("first_routine")) and bool(document.get("onboarding")),
            "instructions": instructions}


def read_cards(settings):
    """Every template on disk, unrendered. A missing or half-written catalog yields the cards
    that do parse: onboarding still runs, it just has less to offer."""
    try:
        folders = sorted(p for p in Path(settings.catalog_dir).iterdir() if p.is_dir())
    except OSError:
        return []
    cards = []
    for folder in folders:
        try:
            document = yaml.safe_load((folder / CARD_FILE).read_text())
        except (OSError, yaml.YAMLError):
            continue
        if not isinstance(document, dict) or not str(document.get("template") or "").strip():
            continue
        try:
            instructions = (folder / INSTRUCTIONS_FILE).read_text()
        except OSError:
            instructions = ""
        cards.append(_card(document, instructions))
    return cards


def load(c):
    """The stored record, with every field a client reads present even before a first save."""
    row = c.execute("SELECT value_json FROM registry_metadata WHERE key=?", (KEY,)).fetchone()
    stored = (_json(row[0], {}) if row else {}) or {}
    return {"names": {**EMPTY_NAMES, **(stored.get("names") or {})},
            "answers": {**EMPTY_ANSWERS, **(stored.get("answers") or {})},
            "selected": dict(stored.get("selected") or {}),
            "completed": stored.get("completed") or None,
            "assigned_to": stored.get("assigned_to") or None,
            "updated": stored.get("updated") or "", "updated_by": stored.get("updated_by") or ""}


def display_names(settings, record):
    """The environment's configured names, with whatever onboarding saved on top."""
    configured = {"company_name": settings.company_name, "app_name": settings.app_name,
                  "assistant_name": settings.assistant_name}
    return {key: str(record["names"].get(key) or "") or value for key, value in configured.items()}


def needed(c, who, record):
    """Whether the owner still owes us the first-run wizard.

    A company that already runs active bots is past its first run even if nobody ever finished
    the wizard: deployments older than onboarding, or one set up by hand, must not be sent back
    to screen one.
    """
    if who is None or who.role != "owner" or record["completed"]:
        return False
    active = c.execute("SELECT 1 FROM bots WHERE state='active' LIMIT 1").fetchone()
    return active is None


def config_view(c, settings, who=None):
    """What every client needs to name this environment: the env settings, the names
    onboarding saved over them, and whether the owner still owes us the first-run wizard."""
    record = load(c)
    value = {**settings.environment(), **display_names(settings, record)}
    value["onboarding_needed"] = needed(c, who, record)
    chosen = providers.load(c, settings)
    value["providers_configured"] = providers.configured(chosen)
    if who is not None:
        # A runner installs only the harnesses these providers need (runner/harness_tools.py).
        value["enabled_providers"] = list(chosen["enabled"])
    value["version"] = releases.version()
    value["update"] = releases.notice()
    value["backup"] = replication.status()
    value["runner_compat"] = runner_versions.desired()
    return value


def tools_of(answers):
    """What the company already uses: the tools it ticked, plus what an older answer to "where does
    work arrive" implies, plus the three every company has (ALWAYS_TOOLS)."""
    have = set(ALWAYS_TOOLS) | set(answers.get("tools") or [])
    for value in answers.get("work_arrives") or []:
        tool = WORK_TOOLS.get(re.sub(r"^uses_", "", str(value)))
        if tool:
            have.add(tool)
    return have


def tags(answers):
    """The catalog tags an answer set implies; `always` matches any card that asks for it."""
    derived = {"always"}
    customers = str(answers.get("customers") or "")
    if customers in ("businesses", "both"):
        derived.add("sells_to_businesses")
    if customers in ("consumers", "both"):
        derived.add("sells_to_consumers")
    for value in answers.get("work_arrives") or []:
        derived.update(WORK_ARRIVES.get(re.sub(r"^uses_", "", str(value)), ()))
    for tool in tools_of(answers):
        derived.update(TOOL_TAGS.get(tool, ()))
    if str(answers.get("software_product") or "") == "yes":
        derived.add("sells_software")
    # "1-5", "6-10", "12 people": the largest number the person wrote is the team's size.
    sizes = [int(n) for n in re.findall(r"\d+", str(answers.get("team_size") or ""))]
    if sizes and max(sizes) <= SMALL_TEAM:
        derived.add("small_team")
    # A company that gates publishing publishes; one with a CRM or business customers has a
    # pipeline; one that publishes wants to hear what is said about it.
    if "publish" in (answers.get("never_without_person") or []):
        derived.update({"publishes_content", "tracks_mentions"})
    if derived & {"sells_to_businesses", "uses_crm"}:
        derived.add("has_pipeline")
    return derived


def _stem(word):
    for suffix in ("ing", "ed", "es", "s"):
        if word.endswith(suffix) and len(word) - len(suffix) >= 3:
            return word[:-len(suffix)]
    return word


def _stems(text):
    return {_stem(word) for word in re.findall(r"[a-z']+", str(text).lower().replace("'", ""))
            if len(word) > 2 and word not in STOP_WORDS}


def pain_match(card, chips, text):
    """How well a company's stated pains match a card's `pains`: (score, the card's phrase that matched).

    A chip ticked from the card's own phrases is a strong match. Free text matches a phrase when it
    shares all of the phrase's words, at least two of them, or its one or two keywords."""
    score, best = 0, ""
    phrases = {" ".join(sorted(_stems(phrase))): phrase for phrase in card.get("pains") or []}
    for chip in chips or []:
        hit = phrases.get(" ".join(sorted(_stems(chip))))
        if hit:
            score, best = score + 10, best or hit
    words = _stems(text)
    for phrase in card.get("pains") or []:
        wanted = _stems(phrase)
        shared = wanted & words
        if shared and (len(shared) >= 2 or len(shared) == len(wanted) or len(wanted) <= 2):
            score, best = score + len(shared), best or phrase
    return score, best


def _first_sentence(text, limit=190):
    first = re.split(r"(?<=[.!?])\s", str(text or "").strip(), maxsplit=1)[0]
    return first if len(first) <= limit else first[:limit - 1].rstrip() + "…"


def _prerequisite_rows(card, have):
    return [{**row, "met": row["tool"] in have} for row in card.get("prerequisites") or []]


def choose(cards, answers, limit=STARTER_TEAM_MAX):
    """The starter team: about three to five bots for these answers, best first, each with why.

    The best one or two pain matches, then the starters a ticked tool names outright (GitHub, a
    meetings importer), then every starter that asks for `always` (Chief of Staff). A card whose
    required tool the company did not tick is never proposed; it is `held_back` with what it needs,
    because a bot that cannot read anything only disappoints. The built-ins (required cards) are
    always there and are not part of this. Returns (recommendations, held_back). `full_chart` is the
    other starting point.
    """
    derived, have = tags(answers), tools_of(answers)
    chips, text = answers.get("pains") or [], " ".join(
        str(answers.get(key) or "") for key in ("pains_text", "repetitive_work"))
    eligible, held = [], []
    for card in (card for card in cards if not card["required"]):
        missing = [row for row in card.get("prerequisites") or [] if row["required"] and row["tool"] not in have]
        (held if missing else eligible).append((card, missing))
    scored = []
    for card, _ in eligible:
        score, phrase = pain_match(card, chips, text)
        hits = len((set(card["recommend_when"]) & derived) - {"always"})
        scored.append({"card": card, "pain": score, "phrase": phrase, "tags": hits})
    scored.sort(key=lambda row: (-row["pain"], -row["tags"], row["card"]["name"].lower()))
    picks, why = [], {}

    def take(row, reason):
        if row["card"]["template"] not in why:
            picks.append(row["card"])
            why[row["card"]["template"]] = reason

    for row in [row for row in scored if row["pain"] > 0][:MAX_PAIN_PICKS]:
        take(row, {"matched_pain": row["phrase"], "signal": ""})
    if not picks:
        # Nothing said matches a card's words: the best fit for who they sell to and how work arrives.
        for row in [row for row in scored if row["tags"] > 0 and "always" not in row["card"]["recommend_when"]][:1]:
            take(row, {"matched_pain": "", "signal": ""})
    for row in scored:
        signals = [SIGNAL_TAGS[tag] for tag in sorted(set(row["card"]["recommend_when"]) & derived & set(SIGNAL_TAGS))]
        if signals:
            take(row, {"matched_pain": "", "signal": signals[0]})
    for row in scored:
        if "always" in row["card"]["recommend_when"]:
            take(row, {"matched_pain": "", "signal": ""})
    # An always-useful card keeps its slot: trim the weakest earlier pick rather than lose it.
    keepers = [card for card in picks if "always" in card["recommend_when"]]
    rest = [card for card in picks if card not in keepers]
    chosen = rest[:max(0, limit - len(keepers))] + keepers[:limit]
    recommendations = []
    for card in (card for card in picks if card in chosen):
        reason = why[card["template"]]
        recommendations.append({
            "template": card["template"], "slug": card["slug"], "name": card["name"],
            "why": _why(reason, card["summary"]),
            "matched_pain": reason["matched_pain"],
            "prerequisites": _prerequisite_rows(card, have)})
    held_back = []
    for card, missing in held:
        score, phrase = pain_match(card, chips, text)
        if score > 0 or set(card["recommend_when"]) & derived & set(SIGNAL_TAGS):
            held_back.append(_held(card, phrase, missing))
    return recommendations, held_back[:3]


def _why(reason, summary):
    story = ("You said \"" + reason["matched_pain"] + "\". " if reason.get("matched_pain")
             else reason["signal"][:1].upper() + reason["signal"][1:] + ". " if reason.get("signal") else "")
    return story + _first_sentence(summary)


def full_chart(cards, answers, home=""):
    """The other starting point: every template that fits these answers, grouped into the teams of a
    real org chart, each team with a lead and the rest reporting to it. A team's lead is its pack's
    `lead: true` template (Ops Manager, Support Lead, ...), added even when nothing said points at it.
    Leads report to `home` (the company owner). A template whose required tool the company did not tick is left out, and named in
    `held_back` with what it needs. It fits when it matches a pain, names a ticked tool or one of the
    answers' tags, or is for every company. Returns {"teams": [...], "held_back": [...]}.
    """
    derived, have = tags(answers), tools_of(answers)
    chips, text = answers.get("pains") or [], " ".join(
        str(answers.get(key) or "") for key in ("pains_text", "repetitive_work"))
    teams, held, leads = {}, [], {}

    def member(card, reason, score, overlap):
        return {"template": card["template"], "slug": card["slug"], "name": card["name"],
                "why": _why(reason, card["summary"]), "matched_pain": reason["matched_pain"],
                "prerequisites": _prerequisite_rows(card, have), "lead": bool(card.get("lead")),
                "_order": (0 if card.get("lead") else 1, 0 if "always" in card["recommend_when"] else 1, -score, -len(overlap - {"always"}), card["name"].lower())}

    for card in (card for card in cards if not card["required"]):
        missing = [row for row in card.get("prerequisites") or [] if row["required"] and row["tool"] not in have]
        score, phrase = pain_match(card, chips, text)
        overlap = set(card["recommend_when"]) & derived
        if missing:
            if score > 0 or overlap & set(SIGNAL_TAGS):
                held.append(_held(card, phrase, missing))
            continue
        team = TEAMS.get(card.get("pack") or "", OTHER_TEAM)
        if card.get("lead"):
            leads[team] = (card, score, overlap)
        if not (score > 0 or overlap):
            continue
        signals = [SIGNAL_TAGS[tag] for tag in sorted(overlap & set(SIGNAL_TAGS))]
        teams.setdefault(team, []).append(member(card, {"matched_pain": phrase, "signal": signals[0] if signals else ""},
                                                 score, overlap))
    # A team that has anyone in it gets its pack's lead, even when nothing said points at the lead itself.
    for team, rows in teams.items():
        if team in leads and not any(row["lead"] for row in rows):
            card, score, overlap = leads[team]
            rows.append(member(card, {"matched_pain": "", "signal": ""}, score, overlap))
    ordered = []
    for team in [*TEAMS.values(), OTHER_TEAM]:
        members = sorted(teams.get(team, []), key=lambda row: row["_order"])
        if not members:
            continue
        # The template marked `lead: true` leads; a team with none (or whose lead needs a tool that was not
        # ticked) is led by its first member.
        lead = members[0]["slug"]
        for row in members:
            row.pop("_order")
            row["lead"] = row["slug"] == lead
            row["reports_to"] = home if row["lead"] else lead
        ordered.append({"team": team, "lead": lead, "members": members})
    return {"teams": ordered, "held_back": held[:5]}


def _held(card, phrase, missing):
    needs = " and ".join(row["tool"] for row in missing)
    return {"template": card["template"], "name": card["name"], "needs": [row["tool"] for row in missing],
            "why": (("It matches \"" + phrase + "\" but it needs ") if phrase else "It needs ")
                   + needs + ", which you did not tick."}


def recommend(cards, answers):
    return [row["template"] for row in choose(cards, answers)[0]]


# The pains the wizard shows as chips: two per team, the ones people say most. Every card's `pains` still
# match what someone types or ticks; this only chooses what is on the screen (a test keeps each phrase real).
FEATURED_PAINS = {
    "basics": ["I don't know what is really going on across the company", "too much email"],
    "sales": ["leads go cold", "I can't tell which deals are really moving"],
    "marketing": ["we don't post regularly", "we don't have a clear picture of our competitors"],
    "support": ["support inbox is overflowing", "customers wait too long for an answer"],
    "operations": ["meetings without follow-up", "renewals and deadlines sneak up on us"],
    "engineering": ["issues pile up untriaged", "pull requests wait days for a first review"],
}


def pain_options(cards):
    """The phrases a person can tick as their pains: every card's own, each with its template, its team
    and whether it is `featured` (on the screen). The wizard shows the featured ones; a pain that was
    ticked earlier stays visible."""
    seen, options = set(), []
    order = {pack: i for i, pack in enumerate(TEAMS)}
    for card in sorted(cards, key=lambda card: (order.get(card.get("pack") or "", len(order)), card["name"].lower())):
        pack = card.get("pack") or ""
        for phrase in card.get("pains") or []:
            if phrase not in seen:
                seen.add(phrase)
                options.append({"text": phrase, "template": card["template"], "team": TEAMS.get(pack, OTHER_TEAM),
                                "featured": phrase in FEATURED_PAINS.get(pack, ())})
    return options


def _answer_lines(answers):
    lines = []
    for key, label in ANSWER_LABELS:
        value = answers.get(key)
        text = ", ".join(str(item) for item in value) if isinstance(value, list) else str(value or "")
        lines.append("- " + label + ": " + (text or "not answered"))
    return lines


def setup_body(slug, choice, answers):
    """What BotOps needs to build one bot without asking: the names, the reviewed
    instructions verbatim, and what the company said about itself."""
    return "\n".join([
        "Create emp-" + slug + " from the " + choice["template"] + " template and bring "
        + choice["display_name"] + " up.",
        "",
        "- slug: " + slug,
        "- template: " + choice["template"],
        "- display name: " + choice["display_name"],
        "",
        "Instructions the owner reviewed, for AGENT.md:",
        "",
        "```markdown",
        choice["instructions"].strip(),
        "```",
        "",
        "What the company told us during onboarding:",
        *_answer_lines(answers),
    ])


class Onboarding:
    def __init__(self, store, auth, settings_admin, execution, models):
        self.store, self.auth, self.admin = store, auth, settings_admin
        self.execution, self.models = execution, models
        self.settings = store.settings

    # ------------------------------------------------------------------ access
    @staticmethod
    def _owner(who):
        if who.role != "owner":
            raise Problem("forbidden", "Only the owner may set this company up", 403)

    def require_reader(self, who):
        """The owner and bot administrators run onboarding; runners and bots read the answers
        so they can write knowledge/company.md into the repositories they materialize."""
        if who.role in ("runner", "bot") or self.auth.bot_admin(who):
            return
        raise Problem("forbidden", "Only the owner or a bot administrator may read onboarding", 403)

    # ------------------------------------------------------------------ catalog
    def catalog(self, c, rendered=True):
        cards = read_cards(self.settings)
        if rendered:
            record = load(c)
            names = display_names(self.settings, record)
            # A bot the person already named and renamed reads under that name, not the card's.
            cards = [render(card, names, (record["selected"].get(card["slug"]) or {}).get("display_name"))
                     for card in cards]
        # What the company must have comes first; the rest reads as an alphabetical menu.
        cards.sort(key=lambda card: (not card["required"], card["name"].lower()))
        return cards

    def _template(self, name):
        card = next((card for card in read_cards(self.settings) if card["template"] == name), None)
        if not card:
            raise Problem("template", "No such template in the catalog: " + str(name), 422)
        return card

    # ------------------------------------------------------------------ reads
    def view(self, c, who):
        record = load(c)
        cards = self.catalog(c)
        recommendations, held_back = choose(cards, record["answers"])
        owner = self.auth.owner_id(c)
        home = "human:" + owner if owner and H.human(c, owner) else ""
        return {**record, "recommended": [row["template"] for row in recommendations],
                "recommendations": recommendations, "held_back": held_back,
                "full_chart": full_chart(cards, record["answers"], home), "home": home,
                "pain_options": pain_options(cards),
                "bots": self._bots(c), "machine": self._machine(c),
                "needed": needed(c, who, record)}

    def _bots(self, c):
        rows = []
        for row in c.execute("SELECT bot,config_json,onboarding_state,reports_to FROM bot_config ORDER BY bot").fetchall():
            declared = _json(row["config_json"], {}) or {}
            bot = H.bot(c, row["bot"]) or {}
            if bot.get("state") == "archived":          # the assistant a company chose not to have
                continue
            machine, present = self._placement(c, row["bot"])
            rows.append({"slug": row["bot"], "display_name": bot.get("display_name") or row["bot"],
                         "status": bot.get("state") or "", "template": declared.get("template") or "",
                         "setup_task_id": declared.get("setup_task_id") or None,
                         "onboarding_state": row["onboarding_state"] or "",
                         "reports_to": row["reports_to"] or "",
                         "assigned_to": machine, "repository_present": present})
        return rows

    @staticmethod
    def _placement(c, slug):
        """The machine this bot runs on, and what it last said about the repository. A null
        repository report means no machine has looked yet, not that the repository is missing."""
        row = c.execute("SELECT r.id,r.label,r.readiness_json FROM assignments a "
                        "JOIN runners r ON r.id=a.runner_id WHERE a.bot=?", (slug,)).fetchone()
        if not row:
            return None, None
        reported = readiness_document(row["readiness_json"]).get("bots", {}).get(slug)
        return ({"runner_id": row["id"], "label": row["label"]},
                bool(reported.get("repository_present")) if isinstance(reported, dict) else None)

    @staticmethod
    def _machine(c):
        recent = H.shift(H.now(), seconds=-60)
        runners = [{"id": row["id"], "label": row["label"],
                    "online": bool(row["last_seen"] and row["last_seen"] > recent)}
                   for row in c.execute("SELECT id,label,last_seen FROM runners "
                                        "WHERE revoked_at IS NULL ORDER BY created")]
        return {"runners": runners, "enrolled": bool(runners)}

    # ------------------------------------------------------------------ writes
    def save(self, c, who, body):
        self._owner(who)
        record = load(c)
        selected = {}
        for slug, choice in body.selected.items():
            self._template(choice.template)
            selected[slug] = {"template": choice.template, "display_name": choice.display_name,
                              "instructions": choice.instructions, "reports_to": choice.reports_to}
            self._reports_to_valid(c, slug, choice.reports_to)
        record.update(names=body.names.model_dump(), answers=body.answers.model_dump(),
                      selected=selected)
        self._store(c, record, who.actor)
        H.event(c, who.actor, "onboarding.saved", "", {"selected": sorted(selected)})
        return self.view(c, who)

    def _reports_to_valid(self, c, slug, reports_to):
        """A person on the chart (`human:<id>`), or a bot that exists now or is being created with it."""
        if not reports_to:
            return
        if reports_to.startswith("human:"):
            if not H.human(c, reports_to[6:]):
                raise Problem("not_found", "Reports-to person was not found: " + reports_to[6:], 404)
        elif reports_to == slug:
            raise Problem("hierarchy", "A bot cannot report to itself", 422)

    def complete(self, c, who):
        self._owner(who)
        if not providers.configured(providers.load(c, self.settings)):
            raise providers.NoProvider("Setting up the company")
        record = load(c)
        names = display_names(self.settings, record)
        cards = {card["template"]: card for card in read_cards(self.settings)}
        plan = self._plan(record, cards, names)
        owner = self.auth.owner_id(c)
        home = "human:" + owner if owner and H.human(c, owner) else ""
        rank, parents = 0, {}
        for slug, choice in plan.items():
            raw = cards.get(choice["template"])
            card = render(raw, names, choice["display_name"]) if raw else {}
            starter = bool(card.get("starter")) and not card.get("bootstrap")
            reports_to = str(choice.get("reports_to") or "") or (home if starter else "")
            now = reports_to if reports_to.startswith("human:") or (reports_to and H.bot(c, reports_to)) else ""
            self._define(c, who, slug, choice, card, reports_to=now)
            if reports_to != now:
                parents[slug] = reports_to          # it reports to a bot that is created later in this plan
            if starter:
                # A starter is created whole, now: parked until its first conversation, no BotOps task.
                self._make_starter(c, who, slug, choice["template"], rank)
                rank += 1
            else:
                self._setup_task(c, who, slug, choice, card, record["answers"])
            if card.get("bootstrap"):
                self._seed_routines(c, who, slug, choice["template"])
            if slug == BOTOPS:
                G.ensure_botops_goal(c)
        for slug, parent in parents.items():
            row = c.execute("SELECT revision,reports_to FROM bot_config WHERE bot=?", (slug,)).fetchone()
            if row["reports_to"] != parent:
                self.admin.update_bot(c, who, slug, M.BotDefinitionUpdate(
                    reports_to=parent, expected_revision=row["revision"]))
        # Completing twice keeps the moment the company actually finished.
        record.update(selected=plan, completed=record["completed"] or H.now())
        self._wire(c, record, who.actor)
        self._store(c, record, who.actor)
        H.event(c, who.actor, "onboarding.completed", "", {"bots": sorted(plan)})
        return self.view(c, who)

    def _make_starter(self, c, who, slug, template, rank=None):
        """A starter template's bot, as first run creates it: it records the template and its version,
        waits for the computer to materialize its repository (`materialize`), keeps its first routine
        paused, and is `needs_onboarding` until it says the person approved that routine. Nothing
        claims work for it before then except a message from a person (execution.candidate)."""
        declared = self._declared(c, slug)
        declared.update(template=template, template_version=releases.version(), materialize=True)
        if rank is not None:
            declared["setup_rank"] = rank
        self._write_config(c, slug, declared)
        c.execute("UPDATE bot_config SET onboarding_state=? WHERE bot=? AND COALESCE(onboarding_state,'')<>?",
                  (NEEDS_ONBOARDING, slug, ONBOARDED))
        self._seed_routines(c, who, slug, template)
        H.event(c, who.actor, "bot.needs_onboarding", slug, {"template": template})

    def onboarded(self, c, who, slug):
        """The bot's own word, or its manager's, that a person approved its first routine: it stops being
        parked, its routines may run and its work is claimed. A member's bot counts toward their
        limit from here on, so the limit is checked now."""
        if not H.bot(c, slug):
            raise Problem("not_found", "Bot not found", 404)
        if not (who.role == "bot" and H.actor_id(who.actor) == slug):
            self.admin._manager(c, who, slug)
        row = c.execute("SELECT onboarding_state,created_by FROM bot_config WHERE bot=?", (slug,)).fetchone()
        if row["onboarding_state"] != NEEDS_ONBOARDING:
            return {"bot": slug, "onboarding_state": row["onboarding_state"] or "", "changed": False}
        if self.auth.member_bot(c, slug):
            limit = Access.load_access(c, self.settings)["member_bot_limit"]
            if self.admin.counted_bots(c, row["created_by"], excluding=slug) >= limit:
                raise Problem("bot_limit", "The person who owns this bot already has the most active bots a member may "
                              f"have ({limit}). Archive one they no longer need, or ask an admin to raise the limit", 409)
        declared = self._declared(c, slug)
        declared.update(onboarded_at=H.now(), onboarded_by=who.actor)
        self._write_config(c, slug, declared)
        c.execute("UPDATE bot_config SET onboarding_state=? WHERE bot=?", (ONBOARDED, slug))
        H.event(c, who.actor, "bot.onboarded", slug, {})
        return {"bot": slug, "onboarding_state": ONBOARDED, "changed": True}

    def attach_template(self, c, who, slug, template, instructions):
        """Settings' "add from catalog": the same record and the same BotOps task as the wizard."""
        record = load(c)
        display = (H.bot(c, slug) or {}).get("display_name") or slug
        card = render(self._template(template), display_names(self.settings, record), display)
        declared = self._declared(c, slug)
        choice = {"template": template, "display_name": display,
                  "instructions": instructions or card["instructions"]}
        declared.update(template=template, instructions=choice["instructions"])
        self._write_config(c, slug, declared)
        if card.get("starter") and not card.get("bootstrap"):
            self._make_starter(c, who, slug, template)
            return {"template": template, "setup_task_id": None, "onboarding_state": NEEDS_ONBOARDING}
        declared["template_version"] = releases.version()
        self._write_config(c, slug, declared)
        return {"template": template,
                "setup_task_id": self._setup_task(c, who, slug, choice, card, record["answers"])}

    def assign_pending(self, c, runner_id):
        """Give every catalog bot without a machine to this one. The runner bootstraps only
        the bots assigned to it, so a bot nobody placed never gets its repository. This is the
        same call Settings makes, so generations, refusals and audit events are identical."""
        who = self.auth.owner_identity(c)
        placed = []
        computer = c.execute("SELECT operator,accepts_member_bots FROM runners WHERE id=? AND revoked_at IS NULL",
                             (runner_id,)).fetchone()
        for row in c.execute("SELECT bot,config_json,operator FROM bot_config ORDER BY bot").fetchall():
            if not (_json(row["config_json"], {}) or {}).get("template"):
                continue
            if c.execute("SELECT 1 FROM assignments WHERE bot=?", (row["bot"],)).fetchone():
                continue                     # a bot a person already placed is never moved
            if self.auth.member_bot(c, row["bot"]) and not (
                    computer and (computer["accepts_member_bots"] or computer["operator"] == row["operator"])):
                continue                     # a member's bot goes on its member's computer, or one open to members' bots
            try:
                self.execution.assign(c, who, row["bot"], SimpleNamespace(
                    runner_id=runner_id, expected_generation=0))
            except Problem as refusal:
                if refusal.code != "inbox_isolation":
                    raise
                continue                     # an inbox bot never shares a computer; Health says so
            placed.append(row["bot"])
        return placed

    def turn_on_assistant(self, c, who):
        """The owner's one click on the Assistant tab: bring the company's assistant back (the v0.2.1
        restore of an archived one) or add it from the catalog, put it on the computer BotOps runs
        on and activate it. With no computer yet it is left planned, and the answer says so."""
        return self._turn_on(c, who, self.settings.assistant_bot, "assistant",
                             self.settings.assistant_name, "assistant.turned_on")

    def turn_on_librarian(self, c, who):
        """The Docs page's Turn on Librarian: the same for the built-in docs bot (docs/librarian.md)."""
        return self._turn_on(c, who, LIBRARIAN, LIBRARIAN, "Librarian", "librarian.turned_on")

    def name_default_assistant(self, c):
        """An assistant named after the company (the old default) becomes "Assistant", once. Idempotent:
        a name anyone chose since, or the one already set, is left alone."""
        slug = self.settings.assistant_bot
        row = H.bot(c, slug)
        company = display_names(self.settings, load(c))["company_name"].strip().lower()
        if not row or not company or (row["display_name"] or "").strip().lower() != company:
            return False
        c.execute("UPDATE bots SET display_name='Assistant' WHERE slug=?", (slug,))
        config = c.execute("SELECT config_json FROM bot_config WHERE bot=?", (slug,)).fetchone()
        if config and config["config_json"]:
            try:
                declared = json.loads(config["config_json"])
                declared["display_name"] = "Assistant"
                c.execute("UPDATE bot_config SET config_json=? WHERE bot=?", (encode(declared), slug))
            except ValueError:
                pass
        return True

    def ensure_librarian(self, c):
        """A company set up before the Librarian was built in gets it without anyone clicking, once
        it can run: the owner is on the roster, a model is chosen and a computer is enrolled. Called
        when the server starts (an update) and when a computer enrolls; with any of those missing it
        does nothing, and the owner's Turn on Librarian stays available. An owner who paused it
        keeps it paused: only a missing or unplaced one is touched."""
        if not load(c)["completed"] or not providers.configured(providers.load(c, self.settings)):
            return None
        if not c.execute("SELECT 1 FROM runners WHERE revoked_at IS NULL").fetchone():
            return None
        row = H.bot(c, LIBRARIAN)
        if row and (row["state"] != "planned" or c.execute("SELECT 1 FROM assignments WHERE bot=?",
                                                           (LIBRARIAN,)).fetchone()):
            return None
        if row and row["state"] == "archived":
            return None
        if not any(card["template"] == LIBRARIAN for card in read_cards(self.settings)):
            return None
        # Best effort and all or nothing: an update or an enrollment never fails because of this.
        c.execute("SAVEPOINT ensure_librarian")
        try:
            who = self.auth.owner_identity(c)
            done = self._turn_on(c, who, LIBRARIAN, LIBRARIAN, "Librarian", "librarian.turned_on")
        except Problem:
            c.execute("ROLLBACK TO ensure_librarian")
            done = None
        c.execute("RELEASE ensure_librarian")
        return done

    def _turn_on(self, c, who, slug, template, name, event):
        row = H.bot(c, slug)
        if row and row["state"] == "active":
            return {"bot": slug, "state": "active", "restored": False}
        if row and row["state"] not in ("archived", "planned", "paused"):
            raise Problem("state", "The " + name + " is " + row["state"]
                          + "; a person changes that in Settings", 409)
        record = load(c)
        card = render(self._template(template), display_names(self.settings, record), name)
        choice = {"template": card["template"], "display_name": card["name"], "instructions": card["instructions"]}
        restored = bool(row and row["state"] == "archived")
        if restored:
            # The restore keeps the bot's own model and settings; only the name and description are renewed.
            self.admin.create_bot(c, who, M.BotDefinitionCreate(
                slug=slug, display_name=choice["display_name"], description=str(card.get("summary") or ""),
                status="planned", repo="emp-" + slug, thread_mode="personal", model=row.get("model") or "restore",
                effort=row.get("effort") or "high", owners=[H.actor_id(who.actor)]))
        elif not row:
            self._define(c, who, slug, choice, card)
        if not c.execute("SELECT 1 FROM assignments WHERE bot=?", (slug,)).fetchone():
            machine = (c.execute("SELECT runner_id FROM assignments WHERE bot=?", (BOTOPS,)).fetchone()
                       or c.execute("SELECT id AS runner_id FROM runners WHERE revoked_at IS NULL "
                                    "ORDER BY created LIMIT 1").fetchone())
            if machine:
                self.execution.assign(c, who, slug, SimpleNamespace(runner_id=machine["runner_id"],
                                                                    expected_generation=0))
        placed = bool(c.execute("SELECT 1 FROM assignments WHERE bot=?", (slug,)).fetchone())
        if placed and H.bot(c, slug)["state"] != "active":
            self.admin.update_bot(c, who, slug, M.BotDefinitionUpdate(
                status="active", expected_revision=self.admin._config(c, slug)["revision"]))
        self._seed_routines(c, who, slug, template)
        H.event(c, who.actor, event, slug, {"restored": restored, "placed": placed})
        return {"bot": slug, "state": H.bot(c, slug)["state"], "restored": restored, "placed": placed}

    def _seed_routines(self, c, who, slug, template):
        """The template's `schedules:` become the bot's first routines, once. A routine a person
        changed or deleted is never put back: only a key the bot has never had is created. (A bot
        BotOps builds gets these from `hub bot create`; a built-in one is made here.)"""
        from clients.routines import validate_schedules
        folder = Path(self.settings.catalog_dir) / template
        try:
            declared = (yaml.safe_load((folder / "employee.yaml").read_text()) or {}).get("schedules")
            names = display_names(self.settings, load(c))
            entries = validate_schedules(declared, lambda rel: fill((folder / rel).read_text(), names))
        except (OSError, ValueError, TypeError, yaml.YAMLError):
            return []
        made = []
        for entry in entries:
            if c.execute("SELECT 1 FROM schedules WHERE bot=? AND routine_key=?", (slug, entry["id"])).fetchone():
                continue
            routines.create(c, who.actor, slug, {"title": entry["title"], "text": entry["instructions"],
                                                 "cron": entry["cron"], "on": entry["on"],
                                                 "timezone": entry["timezone"],
                                                 "enabled": entry["enabled"]}, key=entry["id"])
            made.append(entry["id"])
        return made

    def on_runner_enrolled(self, c, runner_id, operator):
        """Enrolling the owner's Mac after the wizard finishes wires it up too, so the order
        the company happens to do things in does not decide whether its bots ever start."""
        if operator != self.auth.owner_id(c):
            return []
        record = load(c)
        if not record["completed"]:
            return []
        self.ensure_librarian(c)              # a company from before it was built in
        placed = self._wire(c, record, "human:" + operator, runner_id)
        self._store(c, record, "human:" + operator)
        return placed

    def _wire(self, c, record, actor, runner_id=None):
        """Hand the unplaced bots to a machine and record which one took them. With several
        enrolled, the newest wins: it is the one the person just set up."""
        if runner_id:
            row = c.execute("SELECT id,label FROM runners WHERE id=? AND revoked_at IS NULL",
                            (runner_id,)).fetchone()
        else:
            row = c.execute("SELECT id,label FROM runners WHERE operator=? AND revoked_at IS NULL "
                            "ORDER BY created DESC, rowid DESC LIMIT 1", (self.auth.owner_id(c),)).fetchone()
            if not row:
                # The owner changed after the machine enrolled; a lone online machine is still
                # the one this company's bots belong on.
                online = c.execute("SELECT id,label FROM runners WHERE revoked_at IS NULL AND last_seen>?",
                                   (H.shift(H.now(), seconds=-60),)).fetchall()
                row = online[0] if len(online) == 1 else None
                if row:
                    # Only the owner's machines may host every bot, so this one becomes the owner's.
                    c.execute("UPDATE runners SET operator=? WHERE id=?", (self.auth.owner_id(c), row["id"]))
                    H.event(c, actor, "runner.adopted", row["id"], {"operator": self.auth.owner_id(c)})
        if not row:
            return []
        placed = self.assign_pending(c, row["id"])
        self._activate_bootstrap(c, actor)
        if placed:
            # Only a machine that actually took bots is the one onboarding wired things to.
            record["assigned_to"] = {"runner_id": row["id"], "label": row["label"]}
            H.event(c, actor, "onboarding.assigned", row["id"], {"bots": placed})
        return placed

    def _activate_bootstrap(self, c, actor):
        """Activate the bootstrap bots (the assistant, BotOps) and the starters once a machine hosts
        them. Every other bot is set up by BotOps, and BotOps cannot be handed a task while it is
        planned, so leaving these to a separate click strands the whole setup."""
        cards = {card["template"]: card for card in read_cards(self.settings)}
        who = self.auth.owner_identity(c)
        for row in c.execute("SELECT bc.bot,bc.revision,bc.config_json FROM bot_config bc "
                             "JOIN assignments a ON a.bot=bc.bot JOIN bots b ON b.slug=bc.bot "
                             "WHERE b.state='planned' ORDER BY bc.bot").fetchall():
            declared = _json(row["config_json"], {}) or {}
            # A starter is parked (`needs_onboarding`), so activating it lets it answer a person and nothing else.
            if not ((cards.get(declared.get("template")) or {}).get("bootstrap") or declared.get("materialize")):
                continue
            self.admin.update_bot(c, who, row["bot"], M.BotDefinitionUpdate(
                status="active", expected_revision=row["revision"]))
            H.event(c, actor, "onboarding.activated", row["bot"], {})

    # ------------------------------------------------------------------ internals
    @staticmethod
    def _store(c, record, actor):
        record = {**record, "updated": H.now(), "updated_by": actor}
        c.execute("INSERT INTO registry_metadata VALUES(?,?) ON CONFLICT(key) DO UPDATE SET "
                  "value_json=excluded.value_json", (KEY, encode(record)))
        return record

    def _plan(self, record, cards, names):
        """What onboarding builds: the templates the product requires first (BotOps), so it exists
        before anything asks it for work, then everything the person picked. The assistant is a
        pick like any other; its card slug is the environment's assistant bot."""
        plan = {}
        for card in sorted(cards.values(), key=lambda card: card["slug"]):
            if not card["required"]:
                continue
            card = render(card, names)
            plan[self._bot_slug(card["slug"])] = {"template": card["template"], "display_name": card["name"],
                                                  "instructions": card["instructions"]}
        for slug, choice in record["selected"].items():
            plan[self._bot_slug(slug)] = dict(choice)
        return plan

    def _bot_slug(self, card_slug):
        return self.settings.assistant_bot if card_slug == ASSISTANT_TEMPLATE_SLUG else card_slug

    @staticmethod
    def _declared(c, slug):
        row = c.execute("SELECT config_json FROM bot_config WHERE bot=?", (slug,)).fetchone()
        if not row:
            raise Problem("not_found", "Bot not found: " + str(slug), 404)
        return _json(row["config_json"], {}) or {}

    @staticmethod
    def _write_config(c, slug, declared):
        c.execute("UPDATE bot_config SET config_json=? WHERE bot=?", (encode(declared), slug))

    def _runtime(self, c, card):
        """The model a bot built from this card runs on: the card's own pick when it names a
        current model of an enabled provider, else the company default, else the first enabled
        provider's recommended model. With no provider chosen this is an error, never a vendor."""
        company = providers.load(c, self.settings)
        named = self.models.get(str(card.get("model") or ""))
        own = {}
        if (named and not named.get("deprecated") and named.get("provider") in company["enabled"]):
            own = {"model": named["id"], "runtime": named["runtime"]}
        runtime, model = providers.resolve(company, own, what="Onboarding")
        choice = self.models[model]
        effort = str(card.get("reasoning_effort") or "").strip().lower()
        return choice["id"], (effort if effort in tuple(choice.get("efforts") or ())
                              else choice.get("default_effort") or "")

    def _define(self, c, who, slug, choice, card, reports_to=""):
        """Create the bot, or bring an existing definition up to the chosen name. A bot that
        is already running is never demoted back to planned."""
        summary = str(card.get("summary") or "")
        existing = c.execute("SELECT revision FROM bot_config WHERE bot=?", (slug,)).fetchone()
        if not existing:
            model, effort = self._runtime(c, card)
            self.admin.create_bot(c, who, M.BotDefinitionCreate(
                slug=slug, display_name=choice["display_name"], description=summary,
                status="planned", repo="emp-" + slug, thread_mode="personal",
                reports_to=reports_to or None,
                model=model, effort=effort, owners=[H.actor_id(who.actor)]))
        else:
            before = self.admin.definition(c, slug)
            if (before["display_name"], before["description"]) != (choice["display_name"], summary):
                self.admin.update_bot(c, who, slug, M.BotDefinitionUpdate(
                    display_name=choice["display_name"], description=summary,
                    expected_revision=existing["revision"]))
        declared = self._declared(c, slug)
        declared.update(template=choice["template"], instructions=choice["instructions"],
                        template_version=releases.version())
        self._write_config(c, slug, declared)

    def _setup_task(self, c, who, slug, choice, card, answers):
        """BotOps builds every bot people picked. A bootstrap template (the assistant, BotOps
        itself) is materialized by the machine at first run, so it gets no task."""
        if card.get("bootstrap") or not H.bot(c, BOTOPS) or slug == BOTOPS:
            return None
        declared = self._declared(c, slug)
        if declared.get("setup_task_id"):
            return declared["setup_task_id"]          # completing twice never reopens the work
        title = ("Set up " + choice["display_name"] + " from the " + choice["template"]
                 + " template")
        task = H.task_create(c, who.actor, title, setup_body(slug, choice, answers),
                             "bot:" + BOTOPS, allow_planned=True,
                             conversation_id=rooms.task_conversation_id(
                                 c, self.auth, "bot:" + BOTOPS, who.actor))
        declared["setup_task_id"] = task["id"]
        self._write_config(c, slug, declared)
        return task["id"]
