"""The HTTP contract. Unknown fields fail validation rather than changing identity."""

from typing import Annotated, Literal

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, model_validator

Text = Annotated[str, Field(min_length=1, max_length=200_000)]
ID = Annotated[str, Field(min_length=1, max_length=200)]
Slug = Annotated[str, Field(pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$", max_length=80)]
# A person chooses how work reaches the company from a fixed list. Both spellings are
# accepted so the wizard may send either the answer or the catalog tag it maps to.
WorkArrival = Literal["email", "slack", "crm", "tickets",
                      "uses_email", "uses_slack", "uses_crm", "uses_tickets"]


def repo_reference(value):
    """A bot repository as the operator wrote it: a bare name, `owner/name`, or an https URL.
    The environment's GitHub owner completes a bare name when one is configured."""
    repo = str(value or "").strip()
    if any(character.isspace() for character in repo):
        raise ValueError("A repository reference cannot contain spaces")
    if "://" in repo and not repo.startswith("https://"):
        raise ValueError("A repository URL must use https")
    return repo


Repo = Annotated[str, Field(max_length=200), AfterValidator(repo_reference)]


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class ConversationCreate(Contract):
    participants: list[ID] = Field(min_length=1, max_length=20)
    kind: Literal["chat", "ask", "notice"] = "chat"
    subject: str = Field(default="", max_length=300)


class MessageCreate(Contract):
    to: ID
    text: Text
    conversation_id: ID | None = None
    kind: Literal["say", "ask", "notice", "steer"] = "say"
    refs: dict = Field(default_factory=dict)
    in_reply_to: ID | None = None
    wait_s: int | None = Field(default=None, ge=0, le=300)


class ChatCreate(Contract):
    text: Text
    refs: dict = Field(default_factory=dict)


class BatchStart(Contract):
    """Which part of the list: omitted for all of it, `next` for the bot that most needs the
    person, a bot slug or person for theirs, `me` for the person's own (backend/batch.py)."""
    bot: str | None = Field(default=None, max_length=80)


class BatchRespond(Contract):
    kind: Literal["decide", "needs_info", "instruct", "rule", "skip", "later"]
    text: str = Field(default="", max_length=4000)
    item: int | None = Field(default=None, ge=1)          # 1-based position; the current item when omitted
    decision: Literal["approve", "decline", "done", "close", "answer"] | None = None
    heard: str = Field(default="", max_length=2000)       # what the person actually said, when spoken
    until: str | None = Field(default=None, max_length=40)


class ChangelogPost(Contract):
    title: str = Field(min_length=1, max_length=90)
    bullets: list[str] = Field(min_length=1, max_length=12)


class TaskChat(Contract):
    text: Text
    expected_recipient: ID | None = None


class PageChat(Contract):
    page: Literal["tasks", "docs", "doc-pr"]
    text: str = Field(default="", max_length=200_000)
    task_id: str | None = None
    doc_id: str | None = None
    collection: Literal["docs", "notes", "market"] = "docs"
    action: Literal["load", "feedback", "merge"] | None = None
    repo: str | None = Field(default=None, max_length=200)
    number: int | None = Field(default=None, ge=1)
    head_sha: str | None = Field(default=None, pattern=r"^[0-9a-f]{40}$")


class DocumentSource(Contract):
    repo: str = Field(min_length=1, max_length=1000)
    folder: str = Field(default="docs", max_length=500)
    branch: str = Field(default="", max_length=200)


class DocumentCatalog(Contract):
    catalog: dict


class Answer(Contract):
    text: Text
    unknown: bool = False


Lane = Literal["company", "product"]


class TaskCreate(Contract):
    title: str = Field(min_length=1, max_length=300)
    body: Text
    owner: ID
    due: str | None = None
    parent_id: ID | None = None
    goal_id: ID | None = None
    acceptance_criteria: list[str] = Field(default_factory=list, max_length=50)
    lane: Lane | None = None
    labels: list[str] = Field(default_factory=list, max_length=20)
    top: bool = False
    links: list[str] = Field(default_factory=list, max_length=20)
    # Wait for the owner's next run instead of starting one (a bot owner only).
    next_run: bool = False


class NoteCreate(Contract):
    """A quiet note: something for a bot's next run to know, asking nothing (backend/hubdb.py)."""
    to: ID
    text: Text


class TaskUpdate(Contract):
    version: int = Field(ge=1)
    status: Literal["open", "doing", "waiting", "review", "ready", "done", "declined"] | None = None
    note: str | None = Field(default=None, max_length=200_000)
    owner: ID | None = None
    due: str | None = None
    body: Text | None = None
    goal_id: str | None = Field(default=None, max_length=200)   # "" takes the goal off
    close: bool = False
    lane: Lane | None = None
    labels: list[str] | None = Field(default=None, max_length=20)
    blocked_by: str | None = Field(default=None, max_length=64)     # "" clears
    parent_id: str | None = Field(default=None, max_length=64)      # "" clears
    rank: float | None = None
    # BotOps applying a person's own request to a task they own or requested (backend/app.py
    # delegated_identity): checked as that person, never as BotOps.
    on_behalf_of: ID | None = None


class TaskComment(Contract):
    text: Text


class TaskLink(Contract):
    url: str | None = Field(default=None, max_length=2000)
    title: str | None = Field(default=None, max_length=200)
    remove: ID | None = None


class Preference(Contract):
    value: dict | list | str | int | float | bool | None = None


# Getting started (backend/getting_started.py). The state is the person's own choices only;
# the checklist's ticks are computed, never sent.
class GettingStartedState(Contract):
    tour: bool | None = None
    checklist: bool | None = None
    card: str | None = Field(default=None, max_length=32)
    skip: str | None = Field(default=None, max_length=32)


class GettingStartedBot(Contract):
    what: str = Field(min_length=1, max_length=2000)
    name: str = Field(default="", max_length=80)


class GettingStartedDocs(Contract):
    kind: Literal["drive", "notion", "github", "website", "upload", "none"]
    value: str = Field(default="", max_length=500)


class GettingStartedMarket(Contract):
    sells: str = Field(min_length=1, max_length=2000)
    customers: str = Field(min_length=1, max_length=2000)
    competitors: str = Field(default="", max_length=2000)
    channels: str = Field(default="", max_length=2000)
    add_analyst: bool = False


# Goals (backend/goals.py). `owner` is a bot slug, a person id
# or `me`; the colour is the owner's word with one sentence; a reading is a fact with an author.
class GoalCreate(Contract):
    title: str = Field(min_length=1, max_length=300)
    owner: ID
    parent_id: ID | None = None
    body: str = Field(default="", max_length=100_000)
    top: bool = False


class GoalStatus(Contract):
    status: Literal["red", "yellow", "green", "done", "dropped"]
    note: str = Field(default="", max_length=2000)


class GoalUpdate(Contract):
    title: str | None = Field(default=None, min_length=1, max_length=300)
    body: str | None = Field(default=None, max_length=100_000)
    parent_id: str | None = Field(default=None, max_length=200)   # "" makes it a company goal
    owner: ID | None = None
    rank: int | None = None
    top: bool = False


class KpiCreate(Contract):
    name: str = Field(min_length=1, max_length=300)
    unit: str = Field(default="", max_length=40)
    target: float | None = None


class KpiUpdate(Contract):
    name: str | None = Field(default=None, min_length=1, max_length=300)
    unit: str | None = Field(default=None, max_length=40)
    target: float | None = None
    clear_target: bool = False


class KpiLog(Contract):
    value: float
    note: str = Field(default="", max_length=2000)
    source: str = Field(default="measured", max_length=40)
    at: str | None = None


# Market (backend/market.py). Reporters send prose. The curator and the owner write the graph.
class MarketReport(Contract):
    kind: Literal["new-entity", "edge", "property-change", "correction", "question", "other"]
    about: str = Field(default="", max_length=300)
    claim: str = Field(min_length=1, max_length=20_000)
    source_url: str = Field(default="", max_length=2000)
    quote: str = Field(default="", max_length=20_000)
    confidence: Literal["high", "medium", "low"] = "medium"
    urgent: bool = False
    source_ref: str | None = Field(default=None, max_length=200)


class MarketAsk(Contract):
    question: str = Field(min_length=1, max_length=2000)


class MarketEvidenceCreate(Contract):
    source_url: str = Field(default="", max_length=2000)
    source_kind: str = Field(default="other", max_length=40)
    captured_at: str | None = None
    quote: str = Field(default="", max_length=100_000)
    our_read: str = Field(default="", max_length=20_000)
    insight_id: str | None = Field(default=None, max_length=80)


class MarketEntityCreate(Contract):
    id: str | None = Field(default=None, max_length=200)
    type: Literal["company", "product", "person", "segment", "channel", "geography", "regulation", "event"]
    name: str = Field(min_length=1, max_length=300)
    aliases: list[str] = Field(default_factory=list, max_length=50)
    external_ids: dict = Field(default_factory=dict)
    tier: Literal["core", "lookalike", "phrase-stealer", "secondary"] | None = None
    summary: str = Field(default="", max_length=20_000)
    properties: dict = Field(default_factory=dict)
    last_verified: str | None = None
    evidence_ids: list[str] = Field(default_factory=list, max_length=20)
    force: bool = False
    insight_id: str | None = Field(default=None, max_length=80)


class MarketEntityWrite(Contract):
    name: str | None = Field(default=None, max_length=300)
    aliases: list[str] | None = None
    external_ids: dict | None = None
    tier: Literal["core", "lookalike", "phrase-stealer", "secondary"] | None = None
    clear_tier: bool = False
    summary: str | None = Field(default=None, max_length=20_000)
    properties: dict | None = None
    last_verified: str | None = None
    status: Literal["active", "retired", "merged"] | None = None
    evidence_ids: list[str] | None = None
    insight_id: str | None = Field(default=None, max_length=80)
    into: str | None = Field(default=None, max_length=200)


class MarketEdgeCreate(Contract):
    id: str | None = Field(default=None, max_length=200)
    src: str = Field(min_length=1, max_length=200)
    rel: str = Field(min_length=1, max_length=40)
    dst: str = Field(min_length=1, max_length=200)
    since: str | None = None
    until: str | None = None
    confidence: Literal["high", "medium", "low"] = "medium"
    properties: dict = Field(default_factory=dict)
    evidence_ids: list[str] = Field(default_factory=list, max_length=20)
    insight_id: str | None = Field(default=None, max_length=80)


class MarketEdgeUpdate(Contract):
    rel: str | None = Field(default=None, max_length=40)
    since: str | None = None
    until: str | None = None
    set_since: bool = False
    set_until: bool = False
    confidence: Literal["high", "medium", "low"] | None = None
    properties: dict | None = None
    evidence_ids: list[str] | None = None
    insight_id: str | None = Field(default=None, max_length=80)


class MarketCitation(Contract):
    claim_kind: Literal["entity", "edge", "evidence", "document"]
    claim_id: str = Field(min_length=1, max_length=200)
    evidence_id: str = Field(min_length=1, max_length=80)
    insight_id: str | None = Field(default=None, max_length=80)


class MarketResolve(Contract):
    status: Literal["applied", "merged", "rejected", "needs-human"]
    resolution: str = Field(default="", max_length=2000)
    applied_events: list[str] = Field(default_factory=list, max_length=50)


class MarketApply(Contract):
    evidence: MarketEvidenceCreate
    entity: MarketEntityCreate | None = None
    edge: MarketEdgeCreate | None = None
    entity_id: str | None = Field(default=None, max_length=200)
    summary: str | None = Field(default=None, max_length=20_000)
    properties: dict | None = None
    tier: Literal["core", "lookalike", "phrase-stealer", "secondary"] | None = None
    aliases: list[str] | None = None
    last_verified: str | None = None


class MarketUnverified(Contract):
    id: str = Field(min_length=1, max_length=200)
    look_for: str = Field(default="", max_length=2000)


class MarketSweep(Contract):
    today: str | None = None
    unverified: list[MarketUnverified] = Field(default_factory=list, max_length=100)


class MarketRefresh(Contract):
    today: str | None = None


class MarketPage(Contract):
    """A market page rewritten by the curator (backend/market.py `PAGES`), whole, in Markdown."""
    body: str = Field(min_length=1, max_length=100_000)


class ApprovalCreate(Contract):
    kind: Literal["send", "spend", "publish", "merge"]
    payload: dict
    task_id: ID | None = None


class ApprovalDecision(Contract):
    decision: Literal["approved", "declined"]
    note: str = Field(default="", max_length=2000)


class ApprovalConsume(Contract):
    payload_hash: str = Field(min_length=64, max_length=64)


class StatusUpdate(Contract):
    state: str | None = None
    focus: str = Field(default="", max_length=2000)
    task_id: ID | None = None


class QuarantineClear(Contract):
    note: str = Field(default="", max_length=2000)     # optional
    # BotOps lifting it because a person asked in chat: checked as that person (backend/app.py).
    on_behalf_of: ID | None = None


class EnrollmentRequest(Contract):
    operator: ID | None = None


class Enrollment(Contract):
    code: str = Field(min_length=32, max_length=200)
    label: str = Field(min_length=1, max_length=100)
    platform: str = Field(default="", max_length=100)


class ProfileReadiness(Contract):
    """One subscription profile on the runner: the provider login its bots share."""
    runtime: str = Field(default="", max_length=100)
    installed: bool = False
    authenticated: Literal["ready", "missing", "failed", "unknown"] = "unknown"
    version: str = Field(default="", max_length=100)
    models: list[ID] = Field(default_factory=list, max_length=50)
    controls: list[Literal["interrupt", "new-session"]] = Field(default_factory=list)
    detail: str = Field(default="", max_length=500)


class HarnessReadiness(Contract):
    """One model CLI on the runner (runner/harnesses/*.toml): what is installed and whether it can
    be kept current from Settings."""
    name: str = Field(default="", max_length=100)
    runtime: str = Field(default="", max_length=100)
    installed: bool = False
    version: str = Field(default="", max_length=100)
    # "tools": installed by the runner, so it can update it; "path": the person's own install.
    managed: bool = False
    source: Literal["tools", "path", ""] = ""
    pinned: bool = False
    pin: str = Field(default="", max_length=100)
    authenticated: Literal["ready", "missing", "failed", "unknown"] = "unknown"
    update_available: bool = False
    latest: str = Field(default="", max_length=100)
    wanted: bool = False
    state: Literal["idle", "installing", "updating", "queued", "failed"] = "idle"
    detail: str = Field(default="", max_length=500)


class RuntimeReadiness(Contract):
    installed: bool
    # "rejected": the provider refused the key or sign-in on a real turn (rejected_at, rejected_reason).
    authenticated: Literal["ready", "missing", "failed", "unknown", "rejected"] = "unknown"
    rejected_at: str = Field(default="", max_length=40)
    rejected_reason: str = Field(default="", max_length=300)
    version: str = Field(default="", max_length=100)
    models: list[ID] = Field(default_factory=list, max_length=50)
    controls: list[Literal["interrupt", "new-session"]] = Field(default_factory=list)
    detail: str = Field(default="", max_length=500)
    # One machine may hold several subscriptions for the same runtime. The runtime row keeps
    # the profile that needs attention first; this is the per-profile breakdown behind it.
    profiles: dict[str, ProfileReadiness] = Field(default_factory=dict, max_length=50)


class BotReadiness(Contract):
    ready: bool
    runtime: str = Field(default="", max_length=100)
    model: str = Field(default="", max_length=200)
    repository_present: bool = False
    repository_revision: str = Field(default="", max_length=100)
    configuration_valid: bool = False
    problems: list[str] = Field(default_factory=list, max_length=20)
    # Soft guidance that does not block claiming work (for example a long AGENT.md).
    warnings: list[str] = Field(default_factory=list, max_length=20)
    # Runners before 0.5.4 reported the routines they read from a repository manifest. Routines
    # are the hub's own rows now (backend/routines.py); these are accepted and dropped.
    schedules: list | None = None
    schedule_error: str = Field(default="", max_length=500)
    routine_revisions: list[str] = Field(default_factory=list, max_length=100)
    routine_preparation_error: str = Field(default="", max_length=500)
    # The subscription profile this bot's turns run on, and that profile's own sign-in state.
    profile: str = Field(default="", max_length=100)
    sign_in: Literal["ready", "missing", "failed", "unknown"] = "unknown"


class StructuredReadiness(Contract):
    schema_version: Literal[1] = 1
    runtimes: dict[str, RuntimeReadiness] = Field(default_factory=dict)
    bots: dict[str, BotReadiness] = Field(default_factory=dict)
    harnesses: dict[str, HarnessReadiness] = Field(default_factory=dict, max_length=50)
    mail_key: Literal["exposed"] | None = None      # the mail key is where bots can read it (runner/mail_key.py)
    shared_env: Literal[True] | None = None         # secrets/_shared.env holds keys every bot there receives


class Heartbeat(Contract):
    version: str = Field(max_length=100)
    platform: str = Field(max_length=100)
    capacity: int = Field(default=4, ge=1, le=32)
    # The bool map remains accepted during runner rollout. The server normalizes both
    # shapes before storing them, so every read path sees one structured document.
    readiness: StructuredReadiness | dict[str, bool] = Field(default_factory=dict)
    # Actual AGENT.md text for assigned personal inbox bots, read from their runner checkout.
    mail_agent_instructions: dict[str, str] = Field(default_factory=dict, max_length=20)
    # Changed AGENT.md files for assigned bots. The runner sends each file on first heartbeat
    # and when it changes; the server keeps the last published copy for Messaging.
    agent_instructions: dict[str, str] = Field(default_factory=dict, max_length=100)
    # The runner's own checkout against origin/main (runner/service.py `checkout_status`), #492.
    checkout: "Checkout | None" = None
    # Which release the runner is on and how its self-update stands (backend/runner_versions.py).
    release: str | None = Field(default=None, max_length=100)
    kind: Literal["mac", "linux", "docker"] | None = None
    update: "RunnerUpdate | None" = None


class RunnerUpdate(Contract):
    state: Literal["idle", "waiting", "updating", "failed", "rolled_back", "pinned", "blocked"]
    target: str = Field(default="", max_length=100)
    error: str = Field(default="", max_length=300)


class Checkout(Contract):
    head: str = Field(pattern=r"^[0-9a-f]{40}$")
    running: str = Field(pattern=r"^[0-9a-f]{40}$")
    ahead: int = Field(ge=0, le=100_000)
    behind: int = Field(ge=0, le=100_000)
    checked_at: str = Field(max_length=40)
    # Why the runner is not updating itself (runner/service.py self_update's note), when it is behind.
    blocked: str | None = Field(default=None, max_length=300)


Heartbeat.model_rebuild()


class RunnerMemberBots(Contract):
    accepts: bool


class Assignment(Contract):
    runner_id: ID
    expected_generation: int = Field(ge=0)
    on_behalf_of: ID | None = None


class AgentHeartbeat(Contract):
    """What an external agent (a Hermes profile) says about itself when it reports in.
    Nothing here is trusted for authorization; it is what the bot page shows."""
    version: str = Field(default="", max_length=100)
    platform: str = Field(default="", max_length=100)
    model: str = Field(default="", max_length=200)
    provider: str = Field(default="", max_length=100)
    profile: str = Field(default="", max_length=100)
    detail: str = Field(default="", max_length=500)


class BotOwners(Contract):
    owners: list[ID] = Field(min_length=1, max_length=50)
    expected_revision: int = Field(ge=1)


class AccessAudience(Contract):
    """One level of a bot's access: everyone, or these people, teams and bots."""
    everyone: bool = False
    people: list[ID] = Field(default_factory=list, max_length=500)
    teams: list[ID] = Field(default_factory=list, max_length=500)
    bots: list[Slug] = Field(default_factory=list, max_length=500)


class BotAccess(Contract):
    see: AccessAudience
    read: AccessAudience
    write: AccessAudience
    revision: int = Field(ge=1)
    # BotOps making the change the requester asked for in chat ("turn", or their message's id).
    on_behalf_of: ID | None = None


class BotRegister(Contract):
    """Register a bot with the server, planned, before BotOps builds its repository."""
    slug: Slug
    display_name: str = Field(default="", max_length=100)
    description: str = Field(default="", max_length=2000)
    reports_to: ID | None = None
    template: str = Field(default="", max_length=80)
    model: ID | None = None
    on_behalf_of: ID | None = None


class BotCoOwners(Contract):
    """Add or remove people who own a bot (its creator is the first)."""
    add: list[ID] = Field(default_factory=list, max_length=50)
    remove: list[ID] = Field(default_factory=list, max_length=50)
    on_behalf_of: ID | None = None

    @model_validator(mode="after")
    def has_change(self):
        if not (self.add or self.remove):
            raise ValueError("Name someone to add or remove")
        return self


class BotDefinitionCreate(Contract):
    slug: Slug
    display_name: str = Field(min_length=1, max_length=100)
    description: str = Field(default="", max_length=2000)
    reports_to: ID | None = None
    status: Literal["active", "paused", "planned"] = "planned"
    repo: Repo = ""
    thread_mode: Literal["personal", "shared"] = "personal"
    model: ID
    effort: ID
    harness: ID | None = None
    operator: ID | None = None
    # Who the bot works for (shared-room members). Left out, that is its operator; who may use it is
    # its access (docs/permissions.md), which starts Open.
    owners: list[ID] = Field(default_factory=list, max_length=50)
    runner_id: ID | None = None
    # "Add from catalog": the template this bot is built from and the instructions a person
    # reviewed for it. Both are empty for a bot typed in by hand.
    template: str = Field(default="", max_length=80)
    instructions: str = Field(default="", max_length=20_000)


class BotArchive(Contract):
    successor: ID | None = None          # a bot that takes its open tasks and any team it roots
    expected_revision: int = Field(ge=1)
    # BotOps applying a person's own request, as for a definition change (backend/app.py).
    on_behalf_of: ID | None = None


class BotDefinitionUpdate(Contract):
    display_name: str | None = Field(default=None, min_length=1, max_length=100)
    description: str | None = Field(default=None, max_length=2000)
    reports_to: ID | None = None
    bot_contact: Literal["open", "replies", "tasks"] | None = None
    status: Literal["active", "paused", "planned"] | None = None
    repo: Annotated[str, Field(min_length=1, max_length=200), AfterValidator(repo_reference)] | None = None
    thread_mode: Literal["personal", "shared"] | None = None
    # Temporary work expected to end: a flag, not "Project"/"Temp" in the name.
    temp: bool | None = None
    expected_revision: int = Field(ge=1)
    # BotOps applying a person's own request: the id of that person's message to BotOps. The
    # change is checked as that person, never as BotOps (backend/app.py update_bot).
    on_behalf_of: ID | None = None

    @model_validator(mode="after")
    def has_change(self):
        if not (self.model_fields_set - {"expected_revision", "on_behalf_of"}):
            raise ValueError("Provide at least one bot definition field to change")
        return self


class BotGoals(Contract):
    goals: str = Field(default="", max_length=8000)


RoutineKey = Annotated[str, Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,99}$")]


class RoutineCreate(Contract):
    """A routine: what a bot is told, and when (backend/routines.py). `cron` (five fields, in
    `timezone`) or `on` (an event the hub emits), never both. `key` names the routine stably so
    creating it again updates it instead of adding a twin."""
    title: str = Field(min_length=1, max_length=300)
    text: str = Field(default="", max_length=100_000)
    cron: str = Field(default="", max_length=100)
    on: str = Field(default="", max_length=100)
    timezone: str = Field(default="", max_length=100)
    enabled: bool = True
    key: RoutineKey | None = None


class RoutineUpdate(Contract):
    title: str | None = Field(default=None, min_length=1, max_length=300)
    text: str | None = Field(default=None, max_length=100_000)
    cron: str | None = Field(default=None, max_length=100)
    on: str | None = Field(default=None, max_length=100)
    timezone: str | None = Field(default=None, max_length=100)
    enabled: bool | None = None


class PersonUpdate(Contract):
    # The line under their name and the description under that.
    title: str | None = Field(default=None, max_length=120)
    about: str | None = Field(default=None, max_length=2000)
    goals: str | None = Field(default=None, max_length=8000)
    notes: str | None = Field(default=None, max_length=20_000)
    # Where this person sits on the org chart: another person's id, or "" for the top.
    reports_to: str | None = Field(default=None, max_length=80)
    # Someone who no longer works here is removed from the org chart. The
    # owner takes someone off the org chart; their history stays, they drop out of every list.
    left: bool | None = None
    # BotOps making the change a person asked for in chat, as that person (app.delegated_identity).
    on_behalf_of: ID | None = None

    @model_validator(mode="after")
    def has_change(self):
        if not (self.model_fields_set - {"on_behalf_of"}):
            raise ValueError("Provide title, about, goals, notes, reports_to or left")
        return self


class BotPlacement(Contract):
    runner_id: ID
    expected_generation: int = Field(ge=0)
    expected_revision: int = Field(ge=1)
    on_behalf_of: ID | None = None


class BotModel(Contract):
    model: ID
    effort: ID | None = None
    harness: ID | None = None
    expected_revision: int = Field(ge=1)


class BotFallbackChoice(Contract):
    harness: ID
    model: ID
    effort: ID | None = None


class BotFallback(Contract):
    fallback: BotFallbackChoice | None = None
    expected_revision: int = Field(ge=1)


class BotTransitionCreate(Contract):
    kind: Literal["model", "machine"]
    model: ID | None = None
    effort: ID | None = None
    harness: ID | None = None
    runner_id: ID | None = None
    expected_revision: int = Field(ge=1)
    expected_generation: int = Field(default=0, ge=0)
    # BotOps applying a person's own request, as for a definition change (backend/app.py).
    on_behalf_of: ID | None = None

    @model_validator(mode="after")
    def exact_target(self):
        if self.kind == "model" and (not self.model or self.runner_id):
            raise ValueError("A model transition requires a model and optional effort")
        if self.kind == "machine" and (not self.runner_id or self.model or self.effort or self.harness):
            raise ValueError("A machine transition requires only runner_id")
        return self


class BotTransitionApply(Contract):
    change_without_checkpoint: Literal[True]


class SettingsUndo(Contract):
    expected_revision: int = Field(ge=1)


class ProvidersUpdate(Contract):
    """The owner's AI provider choice. `expected_revision` is the revision the editor read."""
    enabled: list[Annotated[str, Field(min_length=1, max_length=40)]] = Field(max_length=10)
    runtime: str = Field(default="", max_length=40)
    model: str = Field(default="", max_length=100)
    expected_revision: int = Field(default=0, ge=0)


class SystemUpdate(Contract):
    version: str = Field(min_length=1, max_length=64)


class AccessPersonAdd(Contract):
    name: str = Field(default="", max_length=120)
    email: str = Field(min_length=3, max_length=320)
    title: str = Field(default="", max_length=120)
    team: str = Field(default="", max_length=80)
    reports_to: str = Field(default="", max_length=80)
    # BotOps adding the person the requester asked for: "turn" or the id of their message to it. A
    # Confirm card comes back instead of a person until the requester clicks it.
    on_behalf_of: ID | None = None


class AccessPersonEdit(Contract):
    """The owner's edits to one person. `left: false` brings back someone marked as left."""
    name: str | None = Field(default=None, max_length=120)
    email: str | None = Field(default=None, max_length=320)
    title: str | None = Field(default=None, max_length=120)
    team: str | None = Field(default=None, max_length=80)
    left: bool | None = None
    bot_admin: bool | None = None           # the old name for role: admin
    # Owners set roles; owners and admins set what a member may do (docs/permissions.md).
    role: Literal["admin", "member"] | None = None
    create_bots: bool | None = None
    add_people: bool | Literal["default"] | None = None
    # BotOps making the change a person asked for in chat (a Confirm card for the risky ones).
    on_behalf_of: ID | None = None


class AccessLimits(Contract):
    """How many active bots one member may have."""
    member_bot_limit: int = Field(ge=0, le=1000)
    on_behalf_of: ID | None = None


class AccessAllowUpdate(Contract):
    """Who may join by signing in. `expected_revision` is the revision the editor read."""
    allowed: list[str] = Field(max_length=500)
    allowed_domains: list[str] = Field(max_length=100)
    expected_revision: int = Field(default=0, ge=0)


class OwnerTransfer(Contract):
    person: ID
    previous_owner_bot_admin: bool = False
    expected_revision: int = Field(default=0, ge=0)
    # The client only sends this after its confirm dialog.
    confirm: Literal[True]


class OnboardingNames(Contract):
    """What this company calls itself, its app, and the assistant people talk to."""
    company_name: str = Field(default="", max_length=100)
    app_name: str = Field(default="", max_length=100)
    assistant_name: str = Field(default="", max_length=100)


class OnboardingAnswers(Contract):
    """The interview behind the recommendations. Free text is shown to a person, never parsed."""
    what_we_do: str = Field(default="", max_length=2000)
    customers: Literal["businesses", "consumers", "both", ""] = ""
    team_size: str = Field(default="", max_length=40)
    work_arrives: list[WorkArrival] = Field(default_factory=list, max_length=8)
    repetitive_work: str = Field(default="", max_length=2000)
    never_without_person: list[Literal["send", "spend", "publish", "hire"]] = Field(
        default_factory=list, max_length=4)


class OnboardingSelection(Contract):
    """One bot the person chose: which template builds it, and what they named and told it."""
    template: str = Field(min_length=1, max_length=80)
    display_name: str = Field(min_length=1, max_length=100)
    instructions: str = Field(default="", max_length=20_000)


class OnboardingDraft(Contract):
    names: OnboardingNames = Field(default_factory=OnboardingNames)
    answers: OnboardingAnswers = Field(default_factory=OnboardingAnswers)
    selected: dict[Slug, OnboardingSelection] = Field(default_factory=dict, max_length=50)


class Claim(Contract):
    bot: ID | None = None
    # The runner puts next-run tasks in its prompt. One that does not say so is never handed
    # any, so they wait for it rather than being marked carried and never read.
    next_run: bool = False


class Started(Contract):
    thread_id: ID


class Event(Contract):
    seq: int = Field(ge=1)
    kind: Literal["delta", "message", "tokens", "status", "error", "tool", "diagnostic"]
    payload: dict


class EventBatch(Contract):
    events: list[Event] = Field(min_length=1, max_length=100)


class AuthRejected(Contract):
    runtime: str = Field(max_length=100)
    reason: str = Field(default="", max_length=300)


class Completion(Contract):
    outcome: Literal["completed", "failed", "interrupted"]
    text: str = Field(default="", max_length=200_000)
    last_seq: int = Field(ge=0)
    tokens_in: int | None = Field(default=None, ge=0)
    tokens_out: int | None = Field(default=None, ge=0)
    limited: bool = False   # the local runtime refused the turn on a subscription usage limit
    retryable: bool = False  # the runtime could not renew its sign-in; the turn never started
    fallback: str | None = Field(default=None, max_length=80)  # harness that actually ran the turn
    auth_rejected: AuthRejected | None = None  # the provider refused this computer's key or sign-in


class Retry(Contract):
    acknowledge_uncertain_effects: bool


class ReconcileJob(Contract):
    attempt_id: ID
    decision: Literal["resume", "dismiss"]
    note: str = Field(min_length=20, max_length=4000)
    acknowledge_uncertain_effects: bool


class Adopt(Contract):
    bot: ID
    expected_generation: int = Field(ge=0)


class BotControl(Contract):
    action: Literal["drain", "resume", "pause"]
    expected_revision: int = Field(ge=1)


class Empty(Contract):
    pass


class AssistantMessage(Contract):
    text: Annotated[str, Field(min_length=1, max_length=8000)]


class AssistantAction(Contract):
    """What the Assistant proposes: one operation on this API, run as the person only when they
    confirm it (backend/assistant.py)."""
    summary: Annotated[str, Field(min_length=1, max_length=300)]
    method: Literal["POST", "PUT", "PATCH", "DELETE"] = "POST"
    path: Annotated[str, Field(min_length=9, max_length=300)]
    body: dict = Field(default_factory=dict)


class InboxSharing(Contract):
    allowed: bool


class LoginStart(Contract):
    runtime: Literal["codex", "claude"]
    profile: Annotated[str, Field(pattern=r"^(?:[a-z0-9]+(?:-[a-z0-9]+)*)?$", max_length=80)] = ""


class LoginCode(Contract):
    code: Annotated[str, Field(min_length=1, max_length=700)]


class LoginReport(Contract):
    state: Literal["starting", "waiting", "signed_in", "failed"]
    url: str = Field(default="", max_length=2100)
    code: str = Field(default="", max_length=40)
    lines: list[str] = Field(default_factory=list, max_length=40)
    message: str = Field(default="", max_length=500)
    code_taken: bool = False


class HarnessAction(Contract):
    harness: Annotated[str, Field(pattern=r"^[a-z0-9][a-z0-9-]*$", max_length=60)]
    action: Literal["update", "pin", "unpin"]


class HarnessActionReport(Contract):
    state: Literal["running", "done", "failed"]
    message: str = Field(default="", max_length=500)


class UpdatePost(Contract):
    body: Annotated[str, Field(min_length=1, max_length=20_000)]
    headline: Annotated[str, Field(max_length=300)] | None = None     # ignored: an update is its bullets
    kind: Literal["daily", "weekly"] | None = None


class UpdateRead(Contract):
    ids: list[ID] = Field(default_factory=list, max_length=500)
    all: bool = False
    read: bool = True


class UpdateReply(Contract):
    text: Text


class UpdateSettings(Contract):
    daily: bool | None = None
    weekly: bool | None = None


class PersonalTokenCreate(Contract):
    """A personal API token (backend/personal_tokens.py): a label to tell it apart in the list
    and how long it lives; 90 days unless asked, never more than a year."""
    label: str = Field(min_length=1, max_length=80)
    expires_in_days: int = Field(default=90, ge=1, le=365)
