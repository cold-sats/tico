"""Plumbing for the redesign scenarios: one org per scenario on the factory's disposable hub, the API calls a teammate
makes, and the Unmet marker that turns a missing route or refused behaviour into "not built yet".

A scenario is setup + steps + checks. Steps run in order and keep what they got in a facts dict. A step the product
cannot do yet keeps an Unmet there and the run goes on, so each check that reads it names the wave it waits on. A check
passes only on a real reply; nothing is stubbed."""
import json
import re
import time
import uuid
from dataclasses import dataclass, field
from types import SimpleNamespace
from typing import Any, Callable

from ..factory.world import World

W1 = "wave 1 · renames & moves"
W2 = "wave 2 · budgets"
W3 = "wave 3 · automations core"
W4 = "wave 4 · branches"
GAP = "CONTRACT gap"   # a check the CONTRACT cannot back yet: it names no route or read shape

# Waves that have landed on main. The PR that merges a wave adds its label here: from then on a failing check prints
# its detail instead of "not built yet".
BUILT = set()

# Teammates: the test token each signs in with, the CONTRACT §3 ref and the bare id the API takes as an owner.
CHRIS, LEAD, CLAUDE, OPENAI, RELEASE = "chris-test", "lead-test", "claude-test", "openai-test", "release-test"
CHRIS_REF, LEAD_REF = "person:chris", "bot:engineering-lead"
CLAUDE_REF, OPENAI_REF, RELEASE_REF = "bot:builder-claude", "bot:builder-openai", "bot:release-manager"
CHRIS_ID, LEAD_ID, CLAUDE_ID, OPENAI_ID, RELEASE_ID = (
    "chris", "engineering-lead", "builder-claude", "builder-openai", "release-manager")


class Unmet(Exception):
    """Part of the contract the product does not have yet: a route it does not register, or a refusal."""

    def __init__(self, wave, what):
        super().__init__(what)
        self.wave, self.what = wave, what


@dataclass
class Reply:
    status: int
    body: Any
    wave: str

    def excerpt(self):
        return json.dumps(self.body, default=str)[:160]


@dataclass
class Check:
    label: str
    wave: str
    fn: Callable[[dict], tuple]


@dataclass
class Scenario:
    num: int
    name: str
    about: str
    steps: Callable
    checks: list = field(default_factory=list)
    setting: bool = True   # runs with the redesign setting on; the runner turns it on before the steps


@dataclass
class Result:
    label: str
    ok: bool
    text: str
    wave: str


# ---------------------------------------------------------------------------------------------- reading facts
def got(facts, key):
    """The step's result; raises its Unmet when the step could not run."""
    value = facts[key]
    if isinstance(value, Unmet):
        raise value
    return value


def setup(facts, *keys):
    """Raise unless each named step ran and got a 2xx. A check that depends on a step fails with the reason."""
    for key in keys:
        reply = got(facts, key)
        if not 200 <= reply.status < 300:
            raise Unmet(reply.wave, f"{key}: {reply.status} {reply.excerpt()}")


def body(facts, key):
    setup(facts, key)
    return facts[key].body


def replied(facts, key, *want, needs=()):
    """The step's reply has one of the statuses in `want`, once the `needs` steps were accepted."""
    setup(facts, *needs)
    reply = got(facts, key)
    return reply.status in want, f"{reply.status} {reply.excerpt()}"


def accepted(facts, *keys, needs=()):
    """Every named send was accepted (200 or 201), after the `needs` steps."""
    setup(facts, *needs)
    codes = {key: got(facts, key).status for key in keys}
    return all(code in (200, 201) for code in codes.values()), str(codes)


def rows(data):
    """The list in a listing: the body itself, or its one list field."""
    if isinstance(data, list):
        return data
    return next((v for v in (data or {}).values() if isinstance(v, list)), [])


def find(data, pred):
    """The first dict in a JSON value that `pred` accepts, or None."""
    if isinstance(data, dict):
        if pred(data):
            return data
        children = list(data.values())
    elif isinstance(data, list):
        children = data
    else:
        return None
    return next((hit for child in children if (hit := find(child, pred))), None)


def task_id_of(reply):
    data = reply.body if isinstance(reply.body, dict) else {}
    return data.get("id") or (data.get("task") or {}).get("id")


# ---------------------------------------------------------------------------------------------- the org
class Org(World):
    """The factory's World (clock, server, runner) with the scenario org on it: Chris at the top, Engineering Lead
    under him, two builders under the lead, and the Release Manager under Chris."""

    def __init__(self):
        bots = {LEAD_ID: ("lead", "claude"), OPENAI_ID: ("builder", "gpt"), CLAUDE_ID: ("builder", "claude"),
                RELEASE_ID: ("release", "claude")}
        board = SimpleNamespace(name="Redesign scenarios", steps=[SimpleNamespace(name="Work", status="open")])
        super().__init__(board, bots)
        self.log = []

    def __enter__(self):
        super().__enter__()
        from backend.auth import Identity
        from backend.store import H, encode
        identities = self.app.state.auth.settings.test_identities
        identities.update({
            CHRIS: Identity("human:chris", "owner", email="chris@acme.example"),
            LEAD: Identity(LEAD_REF, "bot", agent="test"),
            CLAUDE: Identity(CLAUDE_REF, "bot", agent="test"),
            OPENAI: Identity(OPENAI_REF, "bot", agent="test"),
        })
        people = [{"id": "ana", "email": "ana@acme.example", "primary_for": ["*"]},
                  {"id": CHRIS_ID, "name": "Chris", "email": "chris@acme.example", "reports_to": "", "primary_for": ["*"]}]
        reports = {LEAD_ID: CHRIS_ID, CLAUDE_ID: LEAD_ID, OPENAI_ID: LEAD_ID, RELEASE_ID: CHRIS_ID}
        with self.store.transaction() as c:
            H.sync_registry(c, {}, {"people": people})   # the humans rows Chris signs in as
            c.execute("DELETE FROM registry_metadata WHERE key='people'")
            c.execute("INSERT INTO registry_metadata VALUES('people',?)", (encode({"people": people}),))
            for bot in (LEAD_ID, CLAUDE_ID, OPENAI_ID):   # the agent credentials the test tokens stand for
                c.execute("INSERT INTO agents(bot,harness,token_hash,created,created_by) VALUES(?,?,?,?,?)",
                          (bot, "test", "x-" + bot, H.now(), "human:ana"))
            for bot, boss in reports.items():
                c.execute("UPDATE bot_config SET reports_to=? WHERE bot=?", (boss, bot))
        return self

    def configure(self):
        """The factory's Dev board is not used: each scenario builds the org it needs."""

    def _registered(self, method, path):
        for route in self.app.routes:
            template = getattr(route, "path", "")
            pattern = "[^/]+".join(re.escape(part) for part in re.split(r"\{[^}]+\}", template))
            if method.upper() in (getattr(route, "methods", None) or ()) and re.fullmatch(pattern, path):
                return True
        return False

    def api(self, method, path, payload=None, *, who=CHRIS, wave=W2):
        """One real API call as `who` (a test token, or the runner's). A route the app does not register is Unmet,
        not a 404, so the scenario names the wave that builds it."""
        if not self._registered(method, path):
            raise Unmet(wave, f"no route {method.upper()} {path}")
        headers = {"Authorization": "Bearer " + who}
        if method != "get":   # every write carries a key, as the hub requires
            headers["Idempotency-Key"] = str(uuid.uuid4())
        response = getattr(self.client, method)(
            path, headers=headers, **({"json": payload} if payload is not None else {}))
        try:
            data = response.json()
        except ValueError:
            data = response.text
        reply = Reply(response.status_code, data, wave)
        self.log.append(f"{method.upper()} {path} as {who} -> {reply.status} {reply.excerpt()}")
        return reply

    def step(self, facts, key, fn, *args, **kwargs):
        """Run one step; a step the product cannot do yet keeps its Unmet and the scenario goes on."""
        try:
            facts[key] = fn(*args, **kwargs)
        except Unmet as unmet:
            facts[key] = unmet

    def redesign_on(self):
        """Turn the redesign setting on. CONTRACT §0 names the setting but no route: this path is a placeholder."""
        return self.api("put", "/api/v2/settings/redesign", {"enabled": True}, wave=W1)

    def pass_time(self, delta):
        self.advance(delta)
        self.scheduler_pass()

    def turn(self, slug, tokens=2_000_000):
        """The bot's next turn, run the way a runner runs it: claim, start, complete with its token use. None when
        the hub held the bot (no job was claimed)."""
        self.scheduler_pass()
        claim = self.api("post", "/api/v2/jobs/claim", {"bot": slug, "start_places": True},
                         who=self.runner["token"], wave=W2)
        attempt = claim.body.get("attempt") if isinstance(claim.body, dict) else None
        if not attempt:
            if claim.status in (200, 201, 204, 409, 423, 429):   # nothing handed out: held, or no job queued
                return None
            raise RuntimeError(f"claim {claim.status}: {claim.excerpt()}")   # a harness or auth bug, not a hold
        base = f"/api/v2/attempts/{attempt['id']}"
        for step, payload in (("started", {"thread_id": "redesign"}),
                              ("complete", {"outcome": "completed", "text": "done", "last_seq": 0, "limited": False,
                                            "usage": {"input_tokens": tokens, "cached_tokens": 0,
                                                      "output_tokens": 10_000, "model": "claude-opus-5-5",
                                                      "runtime": "claude", "billing": "api"}})):
            reply = self.api("post", f"{base}/{step}", payload, who=self.runner["token"], wave=W2)
            if not 200 <= reply.status < 300:
                raise RuntimeError(f"attempt {step} {reply.status}: {reply.excerpt()}")
        return attempt["id"]


# ---------------------------------------------------------------------------------------------- shared steps
def send(org, who, owner, title):
    """A task from `who` to `owner` (a bare slug or person id), as the sender creates it."""
    return org.api("post", "/api/v2/tasks", {"title": title, "body": "Scenario task.", "owner": owner}, who=who,
                   wave=W2)


def work(org, slug, title):
    """A person hands the bot a task, then the bot's next turn runs (None when the hub held it)."""
    made = send(org, CHRIS, slug, title)
    if made.status >= 300:
        raise Unmet(W2, f"task for {slug}: {made.status} {made.excerpt()}")
    return org.turn(slug)


def put_cap(org, sender, receiver, per_day, who=CHRIS):
    return org.api("put", "/api/v2/task-caps", {"sender": sender, "receiver": receiver, "per_day": per_day},
                   who=who, wave=W2)


def get_caps(org):
    return org.api("get", "/api/v2/task-caps", wave=W2)


def put_limit(org, slug, payload, who=CHRIS):
    return org.api("put", f"/api/v2/usage/limits/{slug}", payload, who=who, wave=W2)


def put_budget(org, slug, payload, who=CHRIS):
    return org.api("post", f"/api/v2/bots/{slug}/budget", payload, who=who, wave=W2)


def put_pool(org, gid, payload, who=CHRIS):
    return org.api("put", f"/api/v2/usage/pools/groups/{gid}", payload, who=who, wave=W2)


def make_group(org, name, bots=(), parent=None, lead=None, who=CHRIS):
    """A group with its teammates, as Chris makes it. Returns its id."""
    payload = {"name": name, "add": {"bots": list(bots)}}
    if parent:
        payload["parent"] = parent
    if lead:
        payload["lead"] = lead   # CONTRACT §3; GroupCreate has no lead field today
    reply = org.api("post", "/api/v2/groups", payload, who=who, wave=W2)
    if reply.status >= 300:
        raise Unmet(W2, f"group {name}: {reply.status} {reply.excerpt()}")
    return (reply.body.get("group") or reply.body).get("id")


def automation(org, name, owner, trigger=None, steps=None, group=None, spend_cap=None, who=CHRIS):
    payload = {"name": name, "owner": owner, "enabled": True, "builtin": False,
               "trigger": trigger or {"type": "schedule", "cron": "0 9 * * *", "tz": "UTC"},
               "steps": steps or [{"id": "gate", "type": "filter", "enabled": True, "rules": []}]}
    if group:
        payload["group"] = group
    if spend_cap:
        payload["spend_cap"] = spend_cap
    return org.api("post", "/api/v2/automations", payload, who=who, wave=W3)


def auto_id(facts, key):
    return body(facts, key)["id"]


def run_now(org, facts, key):
    return org.api("post", f"/api/v2/automations/{auto_id(facts, key)}/run", wave=W3)


def edit_auto(org, facts, key, who, **payload):
    return org.api("patch", f"/api/v2/automations/{auto_id(facts, key)}", payload, who=who, wave=W3)


def close_task(org, facts, key, who):
    """The sender closes its own task (status closed) as `who`."""
    tid = task_id_of(got(facts, key))
    task = org.api("get", f"/api/v2/tasks/{tid}", who=who, wave=W2)
    version = (task.body.get("task") or task.body).get("version")
    return org.api("post", f"/api/v2/tasks/{tid}", {"version": version, "status": "closed"}, who=who, wave=W2)


def comment(org, facts, key, who, text):
    tid = task_id_of(got(facts, key))
    return org.api("post", f"/api/v2/tasks/{tid}/comments", {"text": text}, who=who, wave=W2)


def untestable(what):
    """A check the CONTRACT cannot back yet. It fails as untestable until the contract names the route or read."""
    def check(facts):
        raise Unmet(GAP, what)
    return check


# ---------------------------------------------------------------------------------------------- running
def _setting_on(facts):
    setup(facts, "setting")
    return True, "on"


SETTING_CHECK = Check("redesign setting turned on", W1, _setting_on)


def evaluate(check, facts):
    try:
        ok, text = check.fn(facts)
        return ok, text, check.wave
    except Unmet as unmet:
        return False, unmet.what, unmet.wave
    except Exception as exc:  # a bug in a check, shown as such rather than as a missing feature
        return False, f"check error {type(exc).__name__}: {exc}", check.wave


def run_scenario(scenario):
    """Run one scenario on a fresh org: its results, the API calls it made, and the seconds it took."""
    started = time.perf_counter()
    results, error = [], None
    with Org() as org:
        facts = {}
        try:
            if scenario.setting:
                org.step(facts, "setting", org.redesign_on)
            scenario.steps(org, facts)
        except Exception as exc:  # a bug in a step: every check reports it
            error = exc
        checks = ([SETTING_CHECK] if scenario.setting else []) + scenario.checks
        for check in checks:
            if error:
                ok, text, wave = False, f"scenario error {type(error).__name__}: {error}", check.wave
            else:
                ok, text, wave = evaluate(check, facts)
            results.append(Result(check.label, ok, text, wave))
        log = list(org.log)
    return results, log, time.perf_counter() - started
