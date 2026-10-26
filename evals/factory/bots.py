"""Simulated bots: each turn reads what woke it and acts through the API the way a real bot of its role does.

A bot's `style` is how its model behaves, as probabilities per turn that does real work:
- `changes`: a reviewer asks for changes; `fail`: QA fails the change
- `garbled`: the reply is cut off or garbled; a reviewer's verdict line is missing, so finishing its subtask is refused
- `silent`: the run never reports back (its lease lapses)
- `crash`: the run fails partway
- `cant_test`: QA says it can't test the change
- `off_script`: the bot moves its ticket somewhere the process doesn't allow (to Blocked, or back a step)
Every number is drawn from the scenario's seeded random generator, so a run repeats exactly."""
import os
import re

from .world import Refusal

TOKENS = {  # (cached input, uncached input, output) per kind of turn: a real team's averages over a week
    "work": (3_700_000, 90_000, 17_000),     # a Builder's run
    "review": (2_100_000, 93_000, 29_000),   # a reviewer's or QA's run
    "noise": (760_000, 40_000, 5_300),       # woken, read the ticket, nothing to do (a lead's average run)
}
TRACE = os.environ.get("SIM_TRACE") == "1"
CHECK = re.compile(r"^(Review [12]|QA)\b", re.I)


class Bot:
    def __init__(self, world, slug, role, rng, style=None, family="claude", model="claude-opus-5-5", slots=4):
        self.world, self.slug, self.role, self.rng = world, slug, role, rng
        self.style = style or {}
        self.family, self.model, self.slots = family, model, slots
        self.available = True       # False: its computer is off (claims nothing)
        self.limited_until = None   # set: every run is refused on a usage limit until then
        self.turns = []             # one dict per finished turn

    @property
    def token(self):
        return self._token

    def chance(self, what):
        return self.rng.random() < self.style.get(what, 0.0)

    # ------------------------------------------------------------------ one turn
    # Minutes a turn takes, as (shortest, longest, most likely): a build can take two minutes or two hours.
    MINUTES = {"build": (2, 120, 30), "fix": (2, 60, 12), "review": (2, 30, 8), "qa": (3, 40, 12), "short": (1, 4, 2)}

    def start(self, attempt):
        """Begin a claimed turn: read what woke the bot, and decide how long the turn runs. It acts when it ends."""
        w = self.world
        self._token = attempt["token"]
        self.attempt = attempt
        message = attempt.get("message") or {}
        refs = message.get("refs") or {}
        task = attempt.get("task")
        self.record = {"at": w.now(), "bot": self.slug, "news": refs.get("handoff") or refs.get("news") or refs.get("rule")
                       or message.get("kind"), "task": task and task["id"], "kind": "noise",
                       "stale": self.stale(task, message), "action": None,
                       "text": str(message.get("body") or "").replace("\n", " ")}
        w.post(f"attempts/{attempt['id']}/started", {"thread_id": "sim"}, token=w.runner["token"])
        self.ends = w.now() + __import__("datetime").timedelta(minutes=self.minutes(task))

    def minutes(self, task):
        if not task or self.limited_until and self.world.now() < self.limited_until:
            return 0
        kind = self.kind_of_turn(task)
        return self.rng.triangular(*self.MINUTES[kind])

    def kind_of_turn(self, task):
        step = self.world.step_of(task)
        if self.role == "builder" and task["owner"] == "bot:" + self.slug:
            if step in ("On Deck", "In Progress"):
                return "build"
            return "fix" if step and ("Fixes" in step or step.startswith("Review") or step == "In QA") else "short"
        if self.role == "reviewer" and CHECK.match(task["title"]):
            return "review"
        if self.role == "qa" and CHECK.match(task["title"]):
            return "qa"
        return "short"

    def end(self):
        """Finish the running turn: act on the task as it is now, and report the run finished, failed or silent."""
        w, attempt, record = self.world, self.attempt, self.record
        self.attempt = self.record = None
        task = attempt.get("task") and w.task(attempt["task"]["id"])
        message = attempt.get("message") or {}
        if self.limited_until and w.now() < self.limited_until:
            record["kind"] = "limited"
            self.finish(attempt, "failed", limited=True, resets=self.limited_until, tokens=None)
            return self.log(record)
        if self.chance("silent"):
            record["kind"] = "silent"
            return self.log(record)
        if self.chance("crash") or task and task["title"] in self.style.get("crash_titles", ()):
            record["kind"] = "crash"
            self.finish(attempt, "failed", tokens=TOKENS["noise"])
            return self.log(record)
        try:
            if record["news"] == "update":
                # Every real bot answers Tico's daily update request by posting one.
                w.post("updates", {"body": "- Worked my tickets."}, token=self.token)
                action = "posted update"
            else:
                action = self.act(task, message) if task else None
        except Refusal as exc:
            action = "refused: " + exc.body[:160]
        if action:
            record["kind"] = "review" if self.role in ("reviewer", "qa") else "work"
            record["action"] = action
        self.finish(attempt, "completed", tokens=TOKENS[record["kind"]])
        return self.log(record)

    @property
    def running(self):
        return getattr(self, "attempt", None) is not None

    def renew(self):
        if self.running:
            self.world.call("post", f"attempts/{self.attempt['id']}/renew", {}, token=self.world.runner["token"],
                            ok=False)

    def log(self, record):
        self.turns.append(record)
        if TRACE:
            print(f"{record['at']:%H:%M} {self.slug:16} {record['news'] or '-':18} {record['kind']:7}{'*' if record['stale'] else ' '}"
                  f"{(self.world.title(record['task']) if record['task'] else '')[:28]:28} {record['action'] or ''}"
                  + ("" if record["task"] else f" [{record['text'][:90]}]"))
        return record

    def finish(self, attempt, outcome, limited=False, resets=None, tokens=None):
        w = self.world
        body = {"outcome": outcome, "text": "done", "last_seq": 0, "limited": limited}
        if resets:
            body["limit_resets_at"] = resets.strftime("%Y-%m-%dT%H:%M:%SZ")
        if tokens:
            cached, fresh, out = tokens
            body["usage"] = {"input_tokens": fresh, "cached_tokens": cached, "output_tokens": out,
                             "model": self.model, "runtime": "claude", "billing": "api"}
        w.post(f"attempts/{attempt['id']}/complete", body, token=w.runner["token"])

    def stale(self, task, message):
        """Whether the notice was out of date when the bot read it: its task had already finished, or had moved to
        another step after the notice was written."""
        if not task:
            return False
        if task["status"] in ("done", "closed", "declined"):
            return True
        moved = self.world.step_entered_at(task["id"], claimed_by="bot:" + self.slug)
        return bool(moved and message.get("created") and message["created"] < moved)

    # ------------------------------------------------------------------ role behaviour
    def act(self, task, message):
        raise NotImplementedError


FIXES = {"Review 1 Fixes": "Review 1", "Review 2 Fixes": "Review 2", "QA Fixes": "QA"}


class Builder(Bot):
    """Builds its tickets and walks each through the linear process: Review 1, its fixes, Review 2, its fixes, then
    QA until it passes, then merges. It acts on what the ticket shows now, whatever woke it, as a real builder reads
    its ticket: the board moves the ticket on a verdict and on green CI after fixes, and the builder moves it only
    when the board has not."""

    def __init__(self, *a, reviewers=(), qa=(), **kw):
        super().__init__(*a, **kw)
        self.reviewers, self.qa = list(reviewers), list(qa)

    def act(self, task, message):
        w = self.world
        if task["owner"] != "bot:" + self.slug or task["status"] in ("done", "closed", "declined"):
            return None
        step, pr = w.step_of(task), w.pr_of(task["id"])
        if step == "On Deck":
            if w.slots(self.slug) >= self.slots:
                return None
            w.update(task["id"], token=self.token, step="In Progress")
            step = "In Progress"
        if step == "In Progress":
            # A real builder runs the tests itself, opens the PR and hands it to Review 1 in the same turn.
            if not pr:
                pr = w.open_pr(task["id"], token=self.token)
                self.receipt(task["id"], pr)
            elif w.ci_state(pr) == "failing":
                self.push(task, pr, "fixed CI")
            return self.move(task, "Review 1")
        if step in FIXES:
            judged = w.latest_check(task["id"], FIXES[step])
            ci = w.ci_state(pr)
            if judged and str(judged.get("verdict_head") or "-") == w.prs[pr]["head"] or ci == "failing":
                return self.push(task, pr, "pushed fixes")
            if ci == "pending":
                return None
            after = self.after_fixes(task, step)
            return self.move(task, after) if after else self.merge(task, pr)
        if step in ("Review 1", "Review 2", "In QA"):
            last = "In QA" if self.qa_ticket(task) else "Review 2"
            check = w.latest_check(task["id"], step.replace("In ", ""))
            if step == last and check and check.get("verdict") in ("approve", "pass") \
                    and check.get("verdict_head") == w.prs[pr]["head"] and w.ci_state(pr) == "passing":
                return self.merge(task, pr)
        return None

    @staticmethod
    def qa_ticket(task):
        return "qa" in [str(t).lower() for t in (task.get("labels") or [])]

    def after_fixes(self, task, step):
        if step == "Review 1 Fixes":
            return "Review 2"
        if step == "Review 2 Fixes":
            return "In QA" if self.qa_ticket(task) else None
        return "In QA"

    def push(self, task, pr, what):
        self.world.push(pr)
        self.receipt(task["id"], pr)
        return what

    def move(self, task, step):
        self.world.update(task["id"], token=self.token, step=step)
        return "moved to " + step

    def merge(self, task, pr):
        if self.world.ci_state(pr) != "passing":
            return None
        self.world.merge(pr)
        return "merged #%d" % pr

    def receipt(self, task_id, pr):
        head = self.world.prs[pr]["head"]
        self.world.update(task_id, token=self.token, note=f"Tests: base {'c' * 40} head {head}: 9 passed, 0 failed")

    def pick(self, bots, avoid):
        """The least busy check bot, preferring another model family and one not used on this ticket."""
        ranked = sorted(bots, key=lambda b: (b.slug in avoid, b.family == self.family, self.world.open_checks(b.slug),
                                             b.slug))
        return ranked[0].slug


class Reviewer(Bot):
    """Owns Review 1 / Review 2 subtasks: comments, then finishes the subtask with a verdict. It never moves the
    ticket."""

    def act(self, task, message):
        w = self.world
        if task["owner"] != "bot:" + self.slug or not CHECK.match(task["title"]) or task["status"] in (
                "done", "closed", "declined"):
            return None
        head = w.head_for(task)
        if self.chance("off_script"):
            parent = task.get("parent_id") or w.parent_of(task["id"])
            w.update(parent, token=self.token, step="Review 1 Fixes")   # refused: reviewers never move the ticket
            return "moved the ticket"
        if self.chance("garbled"):
            w.post(f"tasks/{task['id']}/comments", {"text": "Findings: the hand"}, token=self.token)
            w.update(task["id"], token=self.token, status="done")   # refused: no verdict
            return "garbled"
        verdict = "changes" if self.chance("changes") else "approve"
        w.post(f"tasks/{task['id']}/comments", {"text": f"Review: {verdict}"}, token=self.token)
        w.update(task["id"], token=self.token, status="done", verdict=verdict, verdict_head=head)
        return verdict


class QA(Bot):
    """Owns QA subtasks: passes or fails the change at its head, or says it can't test it. A failure moves the
    ticket to QA Fixes."""

    def act(self, task, message):
        w = self.world
        if task["owner"] != "bot:" + self.slug or task["status"] in ("done", "closed", "declined"):
            return None
        if not CHECK.match(task["title"]):
            return None
        head = w.head_for(task)
        if self.chance("cant_test"):
            w.post(f"tasks/{task['id']}/comments", {"text": "I can't test this change here."}, token=self.token)
            w.update(task["id"], token=self.token, status="done", verdict="pass", verdict_head=head,
                     note="Can't test: passed through")
            return "cant_test"
        verdict = "fail" if self.chance("fail") else "pass"
        w.update(task["id"], token=self.token, status="done", verdict=verdict, verdict_head=head)
        return verdict


class Lead(Bot):
    """Head of Engineering: looks for stuck tickets and moves them on by hand. Today it only answers wakes."""

    def act(self, task, message):
        return None


class Quiet(Bot):
    """A bot whose turns are all noise for this simulation (Release Manager notes, for one)."""

    def act(self, task, message):
        return None

