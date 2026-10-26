"""The simulation loop: every tick moves the clock, runs the real scheduler pass, lets each available bot claim and run
its queued turns, and records what the board and the queues look like."""
import datetime as dt
import random
from collections import Counter, defaultdict
from dataclasses import dataclass, field

from . import bots as B
from .world import MERGED, World

PRICE = {"claude-opus-5-5": (4.0, 0.20, 20.0)}   # $ per million: uncached input, cached input, output


@dataclass
class Team:
    builders: list = field(default_factory=list)
    reviewers: list = field(default_factory=list)
    qa: list = field(default_factory=list)
    others: list = field(default_factory=list)

    @property
    def all(self):
        return [*self.builders, *self.reviewers, *self.qa, *self.others]

    def bot(self, slug):
        return next(b for b in self.all if b.slug == slug)


TEAM = {  # slug: (role, family)
    "builder-claude": ("builder", "claude"), "builder-openai": ("builder", "gpt"),
    "reviewer-gpt": ("reviewer", "gpt"), "reviewer-xai": ("reviewer", "grok"), "reviewer-muse": ("reviewer", "muse"),
    "qa-claude": ("qa", "claude"), "qa-xai": ("qa", "grok"),
    "release-manager": ("other", "claude"), "engineering-lead": ("lead", "claude"),
}


class Run:
    """One scenario run: the world, the team and everything measured."""

    def __init__(self, scenario, seed):
        self.scenario, self.seed = scenario, seed
        self.rng = random.Random(seed)
        self.samples = []          # per tick: {bot: queued}
        self.violations = defaultdict(list)
        self.merged_at = {}        # ticket id -> when it first reached a merged step
        self.peak_doing = Counter()

    def team(self, w):
        styles = self.scenario.styles
        team = Team()
        made = {}
        for slug, (role, family) in TEAM.items():
            rng = random.Random(f"{self.seed}:{slug}")
            style = styles.get(slug, styles.get(role, {}))
            kind = {"builder": B.Builder, "reviewer": B.Reviewer, "qa": B.QA, "lead": B.Lead}.get(role, B.Quiet)
            made[slug] = kind(w, slug, role, rng, style=style, family=family,
                              **({"slots": self.scenario.slots} if role == "builder" else {}))
        team.reviewers = [b for b in made.values() if b.role == "reviewer"]
        team.qa = [b for b in made.values() if b.role == "qa"]
        team.builders = [b for b in made.values() if b.role == "builder"]
        team.others = [b for b in made.values() if b.role in ("other", "lead")]
        for b in team.builders:
            b.reviewers, b.qa = team.reviewers, team.qa
        return team

    def go(self):
        s = self.scenario
        with World(TEAM, tick_minutes=s.tick_minutes, rng=random.Random(f"{self.seed}:world"), ci_fail=s.ci_fail) as w:
            self.w = w
            team = self.team(w)
            self.t = team
            s.setup(self, w, team)
            ticks = int(s.hours * 60 / s.tick_minutes)
            for i in range(ticks):
                w.advance(ready=[b.slug for b in team.all if b.available],
                          beat=lambda: [b.renew() for b in team.all if b.available])
                s.during(self, w, team, i)
                self.release(w, i)
                w.scheduler_pass()
                bots = list(team.all)
                self.rng.shuffle(bots)
                for bot in bots:
                    if bot.running and not bot.available:
                        bot.attempt = bot.record = None   # its computer went off under the run: the lease lapses
                    for _ in range(8):
                        if bot.running and w.now() >= bot.ends:
                            bot.end()
                        if bot.running or not bot.available:
                            break
                        attempt = w.call("post", "jobs/claim", {"bot": bot.slug, "start_places": True},
                                         token=w.runner["token"])
                        attempt = attempt and attempt.get("attempt")
                        if not attempt:
                            break
                        bot.start(attempt)
                self.observe(w, team)
            self.final = w.tickets()
            self.end = w.now()
            return self

    def release(self, w, i):
        """The Release Manager ships every few hours: Pending Release moves to Post Release QA, and a ticket an hour
        into Post Release QA passes to Done. Done as a person, so it costs no bot turn."""
        if i % int(self.scenario.release_every_hours * 60 / self.scenario.tick_minutes) != 0 or i == 0:
            return
        for t in w.tickets():
            if t["step"] == "Post Release QA":
                w.update(t["id"], step="Done")
            elif t["step"] == "Pending Release":
                w.update(t["id"], step="Post Release QA")

    def observe(self, w, team):
        now = w.now()
        self.samples.append((now, w.queued()))
        for t in w.tickets():
            if t["step"] in MERGED and t["id"] not in self.merged_at:
                self.merged_at[t["id"]] = now
            if t["id"] in self.merged_at and (t["step"] == "Blocked" or t["blocked_since"]):
                self.violations["merged_blocked"].append((now, t["title"]))
        for b in team.builders:
            self.peak_doing[b.slug] = max(self.peak_doing[b.slug], w.slots(b.slug))

    # ------------------------------------------------------------------ measures
    def turns(self, since=None, until=None, bots=None):
        out = []
        for b in self.t.all:
            if bots and b.slug not in bots:
                continue
            out += [r for r in b.turns if (since is None or r["at"] >= since) and (until is None or r["at"] < until)]
        return out

    def cost(self, turns=None):
        total = 0.0
        for r in turns if turns is not None else self.turns():
            kind = r["kind"] if r["kind"] in B.TOKENS else None
            if kind:
                cached, fresh, out = B.TOKENS[kind]
                price = PRICE["claude-opus-5-5"]
                total += (fresh * price[0] + cached * price[1] + out * price[2]) / 1e6
        return total

    def explain(self):
        """Where each unfinished ticket stands: its step, its checks and the owners' jobs."""
        out = []
        for t in self.final:
            if t["step"] in ("Done", "Closed", "Post Release QA", "Pending Release"):
                continue
            out.append(f"{t['title']} @ {t['step']} ({t['status']}, {t['owner']})"
                       + (f" blocked: {t['blocked_since']}" if t["blocked_since"] else ""))
            for c in self.w.checks(t["id"]):
                out.append(f"  {c['title']}: {c['owner']} {c['status']} verdict={c['verdict']}")
            for j in self.w.sql("SELECT j.bot, j.state, j.held, j.wake_class, m.refs_json FROM jobs j "
                                "JOIN messages m ON m.id=j.message_id WHERE json_extract(m.refs_json,'$.task') IN "
                                "(SELECT ? UNION SELECT from_task FROM task_relations WHERE to_task=? AND kind='parent') "
                                "AND j.state NOT IN ('done','cancelled')", (t["id"], t["id"])):
                out.append(f"  job {j['bot']} {j['state']} held={j['held']} {j['wake_class'] or ''}")
        return out

    def summary(self):
        turns = self.turns()
        kinds = Counter(r["kind"] for r in turns)
        steps = Counter(t["step"] for t in self.final)
        peak_queue = Counter()
        for _, queued in self.samples:
            for bot, (n, _) in queued.items():
                peak_queue[bot] = max(peak_queue[bot], n)
        return {
            "turns": len(turns), "work": kinds["work"] + kinds["review"], "noise": kinds["noise"],
            "stale": sum(1 for r in turns if r["stale"]), "silent": kinds["silent"], "crash": kinds["crash"],
            "limited": kinds["limited"], "cost": round(self.cost(), 2), "steps": dict(steps),
            "peak_queue": dict(peak_queue.most_common(4)), "peak_doing": dict(self.peak_doing),
            "refused": sum(1 for r in turns if str(r["action"]).startswith("refused")),
        }


@dataclass
class Scenario:
    name: str
    about: str
    setup: object
    during: object = lambda run, w, team, i: None
    checks: list = field(default_factory=list)   # (name, ticket, fn(run) -> (ok, detail))
    styles: dict = field(default_factory=dict)
    hours: float = 12
    tick_minutes: int = 5
    slots: int = 4
    release_every_hours: float = 4
    qa: bool = True          # tickets carry the `qa` tag, so QA is the last check before the merge
    ci_fail: float = 0.0     # chance CI fails on a new head


def tickets(run, w, n, owner=None, step="On Deck", title="Ticket"):
    """`n` Dev tickets, spread over the builders unless an owner is given."""
    made = []
    for i in range(n):
        builder = owner or run.t.builders[i % len(run.t.builders)].slug
        made.append(w.post("tasks", {"owner": builder, "title": f"{title} {i + 1}", "body": "Build it.",
                                     "type": w.dev["id"], "step": step,
                                     "labels": ["qa"] if run.scenario.qa else []}))
    return [m.get("task", m) for m in made]


def at(hours, minutes=0):
    return dt.timedelta(hours=hours, minutes=minutes)
