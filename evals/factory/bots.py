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
from .board import MERGE
from .world import Refusal

TOKENS = {  # (cached input, uncached input, output) per kind of turn: a real team's averages over a week
    "work": (3_700_000, 90_000, 17_000),     # a Builder's run
    "review": (2_100_000, 93_000, 29_000),   # a reviewer's or QA's run
    "noise": (760_000, 40_000, 5_300),       # woken, read the ticket, nothing to do (a lead's average run)
    "plan": (2_500_000, 150_000, 40_000),    # an architect's plan for a major feature, on a bigger model
}
FINISHED = ("done", "closed", "declined")
TRACE = os.environ.get("SIM_TRACE") == "1"


class Bot:
    def __init__(self, world, slug, role, rng, style=None, family="claude", model="claude-opus-5-5", slots=4):
        self.world, self.slug, self.role, self.rng = world, slug, role, rng
        self.architects = []
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
    MINUTES = {"build": (2, 120, 30), "fix": (2, 60, 12), "review": (2, 30, 8), "qa": (3, 40, 12), "plan": (10, 60, 25),
               "short": (1, 4, 2)}
    # One turn in twenty runs long: a build of three or four hours, an hour-long review.
    TAIL = {"build": (180, 240), "fix": (60, 120), "review": (30, 60), "qa": (40, 60), "plan": (60, 120)}

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
        if kind in self.TAIL and self.rng.random() < 0.05:
            return self.rng.uniform(*self.TAIL[kind])
        return self.rng.triangular(*self.MINUTES[kind])

    def kind_of_turn(self, task):
        w = self.world
        if task["owner"] != "bot:" + self.slug or task["status"] in ("done", "closed", "declined"):
            return "short"
        if self.role == "builder":
            step = w.board.step(w.step_of(task))
            if step and step.work:
                return "fix" if w.board.fixes_for(step.name) else "build"
            return "short"
        if self.role in ("reviewer", "qa", "architect") and w.parent_of(task["id"]):
            return {"reviewer": "review", "qa": "qa", "architect": "plan"}[self.role]
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
            record["kind"] = {"reviewer": "review", "qa": "review", "architect": "plan"}.get(self.role, "work")
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
                  + ("" if record["task"] and not record["stale"] else f" [{record['text'][:90]}]"))
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
        """Whether the notice was out of date when the bot read it: its task had already finished, its CI news was
        for a head the PR has moved past, or it had moved to another step after the notice was written."""
        if not task:
            return False
        if task["status"] in ("done", "closed", "declined"):
            return True
        head = (message.get("refs") or {}).get("pr_head")
        if head:   # CI news is about a head, not a step: it is out of date once the PR moved on
            pr = self.world.pr_of(task["id"])
            return bool(pr) and self.world.prs[pr]["head"] != head
        moved = self.world.step_entered_at(task["id"], claimed_by="bot:" + self.slug)
        return bool(moved and message.get("created") and message["created"] < moved)

    # ------------------------------------------------------------------ role behaviour
    def act(self, task, message):
        raise NotImplementedError


class Builder(Bot):
    """Builds its tickets and takes each through the board. It acts on what the ticket shows now, whatever woke it,
    as a real builder reads its ticket, and on the step's settings, never its name. The board is to move the ticket
    on a verdict, on green CI after fixes and on the merge; when it has not, the builder makes the move itself and the
    run records it as a fallback (a task feature missing or not configured)."""

    def act(self, task, message):
        w, board = self.world, self.world.board
        if task["owner"] != "bot:" + self.slug or task["status"] in FINISHED:
            return None
        step = board.step(w.step_of(task))
        if not step or step.merged:
            return None
        pr = w.pr_of(task["id"])
        if pr and w.prs[pr]["merged"]:
            return self.fallback(task, board.on_merge, "merged, but still at " + step.name)
        if step.assign:
            if w.slots(self.slug) >= self.slots:
                return None
            nxt = board.steps[board.steps.index(step) + 1]
            w.update(task["id"], token=self.token, step=nxt.name)
            step = nxt
        if step.work:
            fixes = board.fixes_for(step.name)
            return self.fix(task, step, fixes, pr) if fixes else self.build(task, step, pr)
        if step.check:
            return self.at_check(task, step, pr, message)
        return None

    def build(self, task, step, pr):
        """A building step: plan first when the ticket is major and the board has an architect, then build, open the
        PR when the next step is a check, and hand the ticket on in the same turn."""
        w, board = self.world, self.world.board
        if "major" in labels(task) and self.architects:
            plan = next((c for c in w.checks(task["id"]) if c["title"].startswith("Plan:")), None)
            if not plan:
                w.post("tasks", {"owner": self.pick(self.architects, set()), "title": f"Plan: {task['title']}",
                                 "body": "Plan this feature: the approach, the risks, the order of work.",
                                 "relations": [{"task": task["id"], "kind": "parent"}]}, token=self.token)
                return "asked the architect for a plan"
            if plan["status"] not in FINISHED:
                return None
        nxt = board.step(step.next)
        if nxt and nxt.check:
            if not pr:
                pr = w.open_pr(task["id"], token=self.token)
                self.receipt(task["id"], pr)
            elif w.ci_state(pr) == "failing":
                self.push(task, pr)
        return self.move(task, step.next)

    def fix(self, task, step, check_step, pr):
        """A fixes step: push fixes for the check's comments, whatever form they came in. On a step whose owner moves
        the ticket on (`next`), the builder hands it on in the same turn, as it does after a build, unless it forgets
        (`forget_move`): then the ticket sits until something wakes the builder again. On a step the board moves on
        green CI (`after_green`), the builder waits for that."""
        w = self.world
        judged = w.judged(task["id"], check_step.name)
        tag = check_step.check.skip_tag
        if not pr:
            return None
        pushed = None
        if judged and str(judged.get("verdict_head") or "-") == w.prs[pr]["head"] or w.ci_state(pr) == "failing" \
                or not judged and self.untouched_since_step(task, pr):
            if tag and tag not in labels(task) and self.chance("skip_check"):
                w.update(task["id"], token=self.token, labels=sorted(labels(task) | {tag}))
            self.push(task, pr)
            pushed = "pushed fixes"
        if step.next:
            if self.chance("forget_move"):
                return pushed or "forgot to hand it on"
            if step.next == MERGE:
                return self.merge(task, pr) or pushed
            return (pushed + ", " if pushed else "") + self.move(task, step.next)
        if pushed or w.ci_state(pr) != "passing":
            return pushed
        target = step.after_green
        if tag and tag in labels(task) and target == check_step.name:
            target = check_step.check.passed
        if target == MERGE:
            return self.merge(task, pr)
        return self.fallback(task, target, "green CI at the new head, still at " + step.name)

    def untouched_since_step(self, task, pr):
        """No push since the ticket came to this step (a check finished with no verdict sends it here too)."""
        entered = self.world.step_entered_at(task["id"])
        pushed = self.world.prs[pr].get("pushed")
        return not pushed or (entered and pushed < entered)

    def at_check(self, task, step, pr, message=None):
        """Waiting on a check. The builder merges when Tico says the merge is next (a pass, a skip or a skipped
        round), or when the check passed at the head and CI is green; a pass the board did not act on, or a skip tag
        the board ignored, the builder moves on by hand."""
        w = self.world
        check = step.check
        if check.passed == MERGE and pr and ((message or {}).get("refs") or {}).get("handoff") == "merge":
            return self.merge(task, pr)
        if check.passed == MERGE and pr and w.cleared(task["id"]):
            return self.merge(task, pr)
        if check.skip_tag and check.skip_tag in labels(task):
            return self.merge(task, pr, fallback="skip tag ignored at " + step.name) if check.passed == MERGE else \
                self.fallback(task, check.passed, "skip tag ignored at " + step.name)
        if pr and w.ci_state(pr) == "failing":
            self.push(task, pr)
            return "pushed a fix for failing CI"
        judged = w.judged(task["id"], step.name)
        if not judged or not pr or judged.get("verdict_head") != w.prs[pr]["head"]:
            return None
        if judged["verdict"] in ("approve", "pass"):
            if check.passed == MERGE:
                return self.merge(task, pr)
            return self.fallback(task, check.passed, "passed, still at " + step.name)
        return self.fallback(task, check.other, judged["verdict"] + ", still at " + step.name)

    def push(self, task, pr):
        self.world.push(pr)
        self.world.prs[pr]["pushed"] = self.world.H.now()
        self.receipt(task["id"], pr)

    def move(self, task, step):
        self.world.update(task["id"], token=self.token, step=step)
        return "moved to " + step

    def fallback(self, task, step, why):
        self.world.fallback(self.slug, task["id"], f"moved to {step} by hand: {why}")
        return self.move(task, step)

    def merge(self, task, pr, fallback=None):
        w = self.world
        if w.ci_state(pr) != "passing":
            return None
        w.merge(pr)
        if fallback:
            w.fallback(self.slug, task["id"], "merged by hand: " + fallback)
        after = w.board.step(w.step_of(w.task(task["id"])))
        if after and not after.merged:
            return self.fallback(task, w.board.on_merge, "merged, the board did not move it")
        return "merged #%d" % pr

    def receipt(self, task_id, pr):
        head = self.world.prs[pr]["head"]
        self.world.update(task_id, token=self.token, note=f"Tests: base {'c' * 40} head {head}: 9 passed, 0 failed")

    def pick(self, bots, avoid):
        """The least busy bot, preferring another model family and one not used on this ticket."""
        ranked = sorted(bots, key=lambda b: (b.slug in avoid, b.family == self.family, self.world.open_checks(b.slug),
                                             b.slug))
        return ranked[0].slug


def labels(task):
    return {str(t).lower() for t in (task.get("labels") or [])}


class Checker(Bot):
    """Owns check subtasks (reviews, QA): judges the change at its head and finishes the subtask with a verdict. It
    never moves the ticket. Its style is how its model goes wrong."""
    GOOD, BAD = "approve", "changes"

    def act(self, task, message):
        w = self.world
        parent = w.parent_of(task["id"])
        if task["owner"] != "bot:" + self.slug or task["status"] in FINISHED or not parent:
            return None
        head = w.head_for(task)
        if self.chance("off_script"):
            target = next(s.name for s in w.board.steps if s.work)
            w.update(parent, token=self.token, step=target)   # refused: a checker never moves the ticket
            return "moved the ticket"
        if self.chance("fallback_stop"):
            # A run on a fallback model stops itself and leaves the check open, as a real one did.
            w.update(task["id"], token=self.token, note="Runtime blocker: this turn ran on a fallback model after the "
                                                          "usage limit; stopping without a verdict.")
            return "stopped on a fallback model"
        if self.chance("garbled"):
            w.post(f"tasks/{task['id']}/comments", {"text": "Findings: the hand"}, token=self.token)
            w.update(task["id"], token=self.token, status="done")   # no verdict line: today this is refused
            return "garbled"
        if self.chance("stale_head"):
            old = w.prs[w.pr_of(parent)].get("old_heads") or []
            head = old[-1] if old else head
        if self.chance("cant_test"):
            w.post(f"tasks/{task['id']}/comments", {"text": "I can't test this change here."}, token=self.token)
            w.update(task["id"], token=self.token, status="done", verdict=self.GOOD, verdict_head=head,
                     note="Can't test: passed through")
            return "can't test"
        verdict = self.BAD if self.chance(self.BAD_STYLE) else self.GOOD
        w.post(f"tasks/{task['id']}/comments", {"text": f"Findings: {verdict}"}, token=self.token)
        w.update(task["id"], token=self.token, status="done", verdict=verdict, verdict_head=head)
        return verdict


class Reviewer(Checker):
    BAD_STYLE = "changes"


class QA(Checker):
    GOOD, BAD, BAD_STYLE = "pass", "fail", "fail"


class Architect(Bot):
    """A senior architect on a big model: builders ask it to plan major features, nobody else wakes it."""

    def act(self, task, message):
        w = self.world
        if task["owner"] != "bot:" + self.slug or task["status"] in FINISHED or not task["title"].startswith("Plan:"):
            return None
        w.update(task["id"], token=self.token, status="done",
                 note="Plan: 1. data model first; 2. API; 3. UI. Risks: migration order. Build in that order.")
        return "planned"


class Lead(Bot):
    """Head of Engineering: on its hourly sweep (a routine) it looks for stuck tickets and gets each moving the way a
    lead does: it tells the owner, with what it sees. It never moves a ticket itself. Any other wake is noise."""

    def act(self, task, message):
        if not task["title"].startswith("Hourly board sweep") or task["owner"] != "bot:" + self.slug \
                or task["status"] in FINISHED:
            return None
        told = self.sweep()
        self.world.update(task["id"], token=self.token, status="done", note=told)
        return told

    def sweep(self):
        w, board = self.world, self.world.board
        told = []
        for t in w.tickets():
            step = board.step(t["step"])
            if not step or step.merged or board.finished(t["step"]) or not str(t["owner"]).startswith("bot:"):
                continue
            limit = step.wake_after_hours or (step.check.timeout_hours if step.check else 2)
            if w.idle_hours(t["id"]) < limit:
                continue
            w.post(f"tasks/{t['id']}/comments", {"text": f"@{t['owner'][4:]} this ticket has sat at {step.name} for "
                                                          f"{w.idle_hours(t['id']):.1f} h: what moves it on?"},
                   token=self.token)
            w.stuck_told.append((w.now(), t["id"]))
            told.append(t["title"])
        return ("told owners of " + ", ".join(told)) if told else "swept: nothing stuck"


class Quiet(Bot):
    """A bot whose turns are all noise for this simulation (Release Manager notes, for one)."""

    def act(self, task, message):
        return None
