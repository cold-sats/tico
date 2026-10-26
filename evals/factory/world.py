"""A disposable hub on a fake clock, with a fake GitHub, a Dev tickets board and one runner for every bot.

The simulation drives the real server in-process: real API calls with each bot's attempt token, real webhooks for pull
requests, and the real scheduler pass on every tick. Only the bots' replies (bots.py) and time are made up."""
import datetime as dt
import hashlib
import hmac
import json
import os
import tempfile
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
os.environ.setdefault("TICO_REGISTRY_DIR", str(ROOT / "backend/tests/fixtures/registry"))
for name, value in {"TICO_UPDATE_CHECK": "off", "TICO_RUNNER_CONTAINER_PROBE": "off", "TICO_SQLITE_SYNC": "off"}.items():
    os.environ[name] = value

import time_machine  # noqa: E402

START = dt.datetime(2026, 10, 20, 9, tzinfo=dt.timezone.utc)
SECRET = "factory-sim"
REPO = "acme/app"

DEV_STEPS = [("On Deck", "open"), ("In Progress", "doing"), ("Review 1", "review"), ("Review 1 Fixes", "doing"),
             ("Review 2", "review"), ("Review 2 Fixes", "doing"), ("In QA", "review"), ("QA Fixes", "doing"),
             ("Pending Release", "review"), ("Post Release QA", "review"), ("Done", "done"), ("Closed", "closed")]
# Steps a ticket reaches only once its change is merged.
MERGED = ("Pending Release", "Post Release QA", "Done")


class Refusal(Exception):
    def __init__(self, status, body):
        super().__init__(f"{status}: {body[:300]}")
        self.status, self.body = status, body


class World:
    """One run of one scenario. Use as a context manager: it starts the clock and the server, and stops both."""

    def __init__(self, bots, tick_minutes=5, rng=None, ci_fail=0.0):
        import random
        self.bot_slugs = list(bots)
        self.rng = rng or random.Random(0)
        self.ci_fail = ci_fail   # chance a CI run on a new head fails (a flaky or broken change)
        self.ci = {}             # pr number -> (head, when its checks finish, passed)
        self.tick = dt.timedelta(minutes=tick_minutes)
        self.tmp = Path(tempfile.mkdtemp(prefix="factory-sim-"))
        self.prs = {}        # pr number -> {"task": id, "head": sha, "merged": bool}
        self.next_pr = 100

    # ------------------------------------------------------------------ lifecycle
    def __enter__(self):
        self.travel = time_machine.travel(START, tick=False)
        self.clock = self.travel.start()
        from fastapi.testclient import TestClient
        from backend.app import create_app
        from backend.auth import Identity
        from backend.config import Settings
        from backend.scheduler import Scheduler
        from backend.store import H, encode
        from backend import rules as R
        self.H = H
        registry = self.tmp / "registry"
        registry.mkdir()
        (registry / "hub-access.yaml").write_text(json.dumps({"owner": "ana@acme.example"}))
        settings = Settings(db_path=self.tmp / "hub.db", registry_dir=registry, github_webhook_secret=SECRET,
                            release_commit="", release_repo=REPO,
                            test_identities={"ana-test": Identity("human:ana", "owner", "ana@acme.example")})
        self.app = create_app(settings)
        self.client = TestClient(self.app)
        self.client.__enter__()
        self.store = self.app.state.store
        with self.store.transaction() as c:
            bots = {slug: {"name": slug, "runtime": "fake", "status": "active"} for slug in self.bot_slugs}
            H.sync_registry(c, bots, {"people": [{"id": "ana", "email": "ana@acme.example"}]})
            c.execute("INSERT INTO registry_metadata VALUES('people',?)", (encode({"people": [
                {"id": "ana", "email": "ana@acme.example", "primary_for": ["*"]}]}),))
            for slug, config in bots.items():
                c.execute("INSERT INTO bot_config(bot,config_json,team,operator) VALUES(?,?,?,?)",
                          (slug, encode(config), "engineering", "ana"))
            c.execute("INSERT INTO registry_metadata VALUES('onboarding',?)",
                      (encode({"completed": "2026-01-01T00:00:00Z"}),))
            self.dev = H.type_create(c, H.KEEPER, "Dev tickets", [{"name": n, "status": s} for n, s in DEV_STEPS],
                                     bots="work")
            R.seed_dev(c)
        self.scheduler = Scheduler(self.store, self.app.state.execution)
        code = self.post("enrollments", {"operator": "ana"})["code"]
        self.runner = self.post("runners/enroll", {"code": code, "label": "Sim", "platform": "test"})
        for slug in self.bot_slugs:
            self.post("bots/" + slug + "/assignment", {"runner_id": self.runner["runner_id"], "expected_generation": 0})
        self.heartbeat(self.bot_slugs)
        return self

    def __exit__(self, *exc):
        self.client.__exit__(*exc)
        self.travel.stop()

    # ------------------------------------------------------------------ time
    def now(self):
        return dt.datetime.now(dt.timezone.utc)

    def advance(self, delta=None, ready=None, beat=None):
        """Move the clock on. The runner reports in every 50 seconds on the way, as a real one does: a longer gap reads
        as a computer that slept, and its claims wait for it to settle (execution.AWAKE_GAP)."""
        left = (delta or self.tick).total_seconds()
        while left > 0:
            step = min(50, left)
            self.clock.shift(step)
            left -= step
            self.finish_ci()
            self.heartbeat(self.bot_slugs if ready is None else ready)
            if beat:
                beat()

    def scheduler_pass(self):
        self.scheduler.tick()

    def heartbeat(self, ready):
        self.post("runners/heartbeat", {"version": "test", "platform": "test",
                                        "readiness": {slug: slug in ready for slug in self.bot_slugs}},
                  token=self.runner["token"])

    # ------------------------------------------------------------------ API
    def call(self, method, path, body=None, token="ana-test", ok=True):
        headers = {"Authorization": "Bearer " + token}
        if method == "post":
            headers["Idempotency-Key"] = str(uuid.uuid4())
        response = getattr(self.client, method)("/api/v2/" + path, headers=headers,
                                                **({"json": body} if body is not None else {}))
        if response.status_code >= 400:
            if ok:
                raise Refusal(response.status_code, response.text)
            return None
        return response.json()

    def post(self, path, body, token="ana-test"):
        return self.call("post", path, body, token)

    def get(self, path, token="ana-test"):
        return self.call("get", path, token=token)

    def task(self, task_id):
        return self.get("tasks/" + task_id)["task"]

    def update(self, task_id, token="ana-test", **fields):
        """Change a task; a refused change raises Refusal with the server's reason."""
        result = self.post("tasks/" + task_id, {"version": self.task(task_id)["version"], **fields}, token=token)
        return result.get("task", result)

    def step_of(self, task):
        steps = {s["id"]: s["name"] for s in self.dev["steps"]}
        if not steps.get(task.get("step_id")):
            with self.store.read() as c:
                steps.update({r["id"]: r["name"] for r in c.execute(
                    "SELECT id,name FROM task_steps WHERE type_id=?", (self.dev["id"],))})
        return steps.get(task.get("step_id"))

    def sql(self, query, args=()):
        with self.store.read() as c:
            return [dict(r) for r in c.execute(query, args)]

    # ------------------------------------------------------------------ fake GitHub
    def hook(self, event, payload):
        body = json.dumps(payload).encode()
        sign = "sha256=" + hmac.new(SECRET.encode(), body, hashlib.sha256).hexdigest()
        response = self.client.post("/api/v2/github/webhook", content=body, headers={
            "X-GitHub-Event": event, "X-Hub-Signature-256": sign,
            "Content-Type": "application/json"})
        assert response.status_code == 200, response.text

    def pr_url(self, number):
        return f"https://github.com/{REPO}/pull/{number}"

    def pr_payload(self, number, action, merged=False):
        pr = self.prs[number]
        return {"action": action, "repository": {"full_name": REPO}, "number": number, "pull_request": {
            "number": number, "html_url": self.pr_url(number), "state": "closed" if action == "closed" else "open",
            "merged": merged, "draft": False, "mergeable": True, "mergeable_state": "clean", "title": "Change", "head": {"sha": pr["head"], "ref": f"b{number}"},
            "base": {"ref": "main", "sha": "c" * 40}, "user": {"login": "sim-bot"}, "merge_commit_sha":
            ("d" * 40) if merged else None}}

    def open_pr(self, task_id, token="ana-test"):
        number = self.next_pr
        self.next_pr += 1
        self.prs[number] = {"task": task_id, "head": uuid.uuid4().hex + uuid.uuid4().hex[:8], "merged": False}
        self.post(f"tasks/{task_id}/links", {"url": self.pr_url(number)}, token=token)
        self.hook("pull_request", self.pr_payload(number, "opened"))
        self.start_ci(number)
        return number

    def push(self, number):
        self.prs[number]["head"] = uuid.uuid4().hex + uuid.uuid4().hex[:8]
        self.hook("pull_request", self.pr_payload(number, "synchronize"))
        self.start_ci(number)
        return self.prs[number]["head"]

    # CI on a new head takes 3 to 15 minutes, usually about 6.
    def start_ci(self, number):
        minutes = self.rng.triangular(3, 15, 6)
        self.ci[number] = (self.prs[number]["head"], self.now() + dt.timedelta(minutes=minutes),
                           self.rng.random() >= self.ci_fail)

    def finish_ci(self):
        for number, (head, due, passed) in list(self.ci.items()):
            if due <= self.now():
                del self.ci[number]
                if self.prs[number]["head"] == head and not self.prs[number]["merged"]:
                    self.hook("check_suite", {"action": "completed", "repository": {"full_name": REPO}, "check_suite": {
                        "id": number * 1000 + len(head), "head_sha": head, "status": "completed",
                        "conclusion": "success" if passed else "failure", "app": {"slug": "github-actions"},
                        "pull_requests": [{"number": number, "html_url": self.pr_url(number)}]}})
                    self.prs[number]["ci"] = (head, passed)

    def ci_state(self, number):
        """'passing', 'failing' or 'pending' for the PR's current head."""
        head, passed = self.prs[number].get("ci") or (None, None)
        if head != self.prs[number]["head"]:
            return "pending"
        return "passing" if passed else "failing"

    def merge(self, number):
        self.prs[number]["merged"] = True
        self.hook("pull_request", self.pr_payload(number, "closed", merged=True))

    # ------------------------------------------------------------------ board reads (no turn, no side effects)
    def tickets(self):
        """The Dev tickets: tasks of the Dev type, with their step names."""
        rows = self.sql("SELECT t.id,t.title,t.owner,t.status,t.step_id,s.name step,t.blocked_since,t.updated "
                        "FROM tasks t LEFT JOIN task_steps s ON s.id=t.step_id WHERE t.type_id=?", (self.dev["id"],))
        return rows

    def title(self, task_id):
        found = self.sql("SELECT title FROM tasks WHERE id=?", (task_id,))
        return found[0]["title"] if found else "?"

    def slots(self, slug):
        """Tickets the builder is actively working: at a building or Fixes step."""
        return self.sql("SELECT count(*) n FROM tasks t JOIN task_steps s ON s.id=t.step_id WHERE t.type_id=? "
                        "AND t.owner=? AND s.status='doing' AND t.status NOT IN ('done','closed','declined')",
                        (self.dev["id"], "bot:" + slug))[0]["n"]

    def checks(self, task_id):
        return self.sql("SELECT t.* FROM tasks t JOIN task_relations r ON r.from_task=t.id AND r.kind='parent' "
                        "WHERE r.to_task=? ORDER BY t.created, t.rowid", (task_id,))

    def latest_check(self, task_id, kind):
        found = [c for c in self.checks(task_id) if c["title"].lower().startswith(kind.lower() + ":")]
        return found[-1] if found else None

    def open_checks(self, slug):
        return self.sql("SELECT count(*) n FROM tasks WHERE owner=? AND status NOT IN ('done','closed','declined')",
                        ("bot:" + slug,))[0]["n"]

    def parent_of(self, task_id):
        found = self.sql("SELECT to_task FROM task_relations WHERE from_task=? AND kind='parent'", (task_id,))
        return found[0]["to_task"] if found else None

    def pr_of(self, task_id):
        return next((n for n, pr in self.prs.items() if pr["task"] == task_id), None)

    def head_for(self, child):
        pr = self.pr_of(self.parent_of(child["id"]) or child["id"])
        return self.prs[pr]["head"] if pr else None

    def step_entered_at(self, task_id, claimed_by=None):
        """When the task last changed step before this moment: the claim that just happened starts an On Deck task
        (as `keeper`), and that is no reason to call the notice stale."""
        found = self.sql("SELECT max(ts) ts FROM task_events WHERE task_id=? AND field='step' AND ts<?",
                         (task_id, self.H.now()))
        return found[0]["ts"] if found else None

    def step_spans(self, task_id, until=None):
        """[(step name, hours there)] in order, the last one up to `until` (default now)."""
        rows = self.sql("SELECT e.ts, s.name FROM task_events e LEFT JOIN task_steps s ON s.id=e.new "
                        "WHERE e.task_id=? AND e.field='step' ORDER BY e.ts, e.rowid", (task_id,))
        out = []
        for row, nxt in zip(rows, rows[1:] + [{"ts": until or self.H.now()}]):
            span = self.H.parse_ts(nxt["ts"]) - self.H.parse_ts(row["ts"])
            out.append((row["name"], span.total_seconds() / 3600))
        return out

    def idle_hours(self, task_id, until=None):
        """Hours since the task last changed, as of `until` (default now)."""
        row = self.sql("SELECT updated FROM tasks WHERE id=?", (task_id,))[0]
        return ((until or self.now()) - self.H.parse_ts(row["updated"])).total_seconds() / 3600

    def queued(self, slug=None):
        """Queued jobs per bot, and how many are held."""
        rows = self.sql("SELECT bot, count(*) n, sum(held) held FROM jobs WHERE state='queued' "
                        + ("AND bot=? " if slug else "") + "GROUP BY bot", (slug,) if slug else ())
        return {r["bot"]: (r["n"], r["held"] or 0) for r in rows}
