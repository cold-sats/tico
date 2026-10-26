"""Scenarios seen on a real team's Dev board, each with the checks the factory must pass. A check names the work that
fixes it when it is a known gap today, so a failing check reads as "not built yet", not as a broken simulation."""
from collections import Counter

from .sim import Scenario, at, tickets
from .world import START

QUEUE = "queue cleanup"   # stale notices dropped, the rest folded into one turn (Dev 601 spec)
TIMEOUT = "Dev 601 task timeout"
HOLD = "Dev 598"
SLOTS = "Dev 542"
HOE = "Dev 606"
SHIPPED = ("Done", "Closed", "Post Release QA", "Pending Release")


# ---------------------------------------------------------------------------------------------- checks
def all_through(run):
    left = [f"{t['title']} @ {t['step']}" for t in run.final if t["step"] not in SHIPPED]
    return not left, ", ".join(left[:6]) + (f" (+{len(left) - 6})" if len(left) > 6 else "")


def never_blocked_after_merge(run):
    seen = run.violations["merged_blocked"]
    return not seen, ", ".join(sorted({t for _, t in seen})[:6])


def no_stale_turns(run):
    stale = [r for r in run.turns() if r["stale"]]
    kinds = Counter(r["news"] for r in stale)
    return not stale, f"{len(stale)} turns on stale notices: " + ", ".join(f"{k} {n}" for k, n in kinds.most_common())


def noise_under(share):
    def check(run):
        s = run.summary()
        ratio = s["noise"] / max(1, s["turns"])
        return ratio <= share, f"{s['noise']} of {s['turns']} turns did nothing ({ratio:.0%})"
    return check


def one_review_per_round(run):
    """Linear reviews: each ticket gets at most one Review 1 and one Review 2 subtask."""
    extra = []
    for t in run.final:
        kinds = Counter(c["title"].split(":")[0] for c in run.w.checks(t["id"]))
        extra += [f"{t['title']} {k} x{n}" for k, n in kinds.items() if k.startswith("Review") and n > 1]
    return not extra, ", ".join(extra[:6])


def max_at_review(hours):
    """No ticket waits longer than `hours` at a review step."""
    def check(run):
        long = []
        for t in run.final:
            spans = run.w.step_spans(t["id"], until=run.end.strftime("%Y-%m-%dT%H:%M:%S.%fZ"))
            long += [f"{t['title']} {name} {span:.1f}h" for name, span in spans
                     if name in ("Review 1", "Review 2") and span > hours]
        return not long, ", ".join(long[:6])
    return check


def burst_after(when, bound, bots=None):
    """In the hour after `when`, no bot runs more than `bound` turns: a backlog arrives as one folded turn."""
    def check(run):
        since = START + when
        per = Counter(r["bot"] for r in run.turns(since=since, until=since + at(1), bots=bots))
        over = {b: n for b, n in per.items() if n > bound}
        return not over, "turns in the hour after: " + ", ".join(f"{b} {n}" for b, n in per.most_common(5))
    return check


def peak_doing(cap):
    def check(run):
        over = {b: n for b, n in run.peak_doing.items() if n > cap}
        return not over, ", ".join(f"{b} {n}" for b, n in run.peak_doing.items())
    return check


def no_uncertain_runs(run):
    """No run is left 'uncertain' (its computer stopped answering partway): such a job waits for a person, and its
    ticket waits with it."""
    rows = run.w.sql("SELECT bot, count(*) n FROM jobs WHERE state='uncertain' GROUP BY bot")
    return not rows, ", ".join(f"{r['bot']} {r['n']}" for r in rows)


def lead_heard_of(word):
    """Head of Engineering was told (a note or a wake) of something matching `word`."""
    def check(run):
        rows = run.w.sql("SELECT body FROM messages WHERE to_actor='bot:engineering-lead' AND body LIKE ?",
                         (f"%{word}%",))
        return bool(rows), f"{len(rows)} messages mention {word!r}"
    return check


def stuck_unseen(hours):
    """Every ticket that sat still for `hours` at a working or review step was looked at by Head of Engineering."""
    def check(run):
        seen = {r["task"] for r in run.t.bot("engineering-lead").turns}
        stuck = [t for t in run.final if t["step"] not in SHIPPED + ("On Deck",)
                 and run.w.idle_hours(t["id"], until=run.end) >= hours and t["id"] not in seen]
        return not stuck, ", ".join(f"{t['title']} @ {t['step']}" for t in stuck[:6])
    return check


def hourly_spend_under(cap, slack=2.0):
    """The cap stops new runs, not running ones: a single hour may go over by what was already running (up to
    `slack` times the cap), but busy hours average no more than the cap."""
    def check(run):
        per = Counter()
        for r in run.turns():
            per[r["at"].strftime("%H:00")] += run.cost([r])
        busy = [v for v in per.values() if v > cap / 2]
        average = sum(busy) / len(busy) if busy else 0
        over = {h: round(v, 2) for h, v in per.items() if v > cap * slack}
        return not over and average <= cap * 1.1, (f"peak hour ${max(per.values() or [0]):.2f}, busy-hour average "
                                                     f"${average:.2f}" + (f", over: {over}" if over else ""))
    return check


def company_cap(hourly):
    def setup(run, w, team):
        from backend import usage_limits
        with w.store.transaction() as c:
            usage_limits.save_pool(c, usage_limits.COMPANY, {"hourly_usd": hourly, "daily_usd": None,
                                                              "weekly_usd": None, "monthly_usd": None}, "human:ana")
        tickets(run, w, 10)
    return setup


BASE = [("every ticket ships", None, all_through),
        ("merged tickets never Blocked", HOLD, never_blocked_after_merge)]


# ---------------------------------------------------------------------------------------------- events
def outage(start, hours, slugs=None, kind="quota"):
    """Bots out from `start` for `hours`: on a usage limit (runs refused, jobs held until the reset) or with their
    computer off (nothing claimed)."""
    def during(run, w, team, i):
        now = w.now()
        for b in team.all:
            if slugs and b.slug not in slugs:
                continue
            if kind == "quota":
                b.limited_until = START + start + at(hours) if START + start <= now else None
            else:
                b.available = not (START + start <= now < START + start + at(hours))
    return during


def close_many(when, count):
    """A person triages the board: closes `count` On Deck tickets in one go."""
    def during(run, w, team, i):
        if w.now() != START + when:
            return
        for t in [t for t in w.tickets() if t["step"] == "On Deck"][:count]:
            w.update(t["id"], step="Closed")
    return during


def both(*events):
    def during(run, w, team, i):
        for event in events:
            event(run, w, team, i)
    return during


def stale_blocker(run, w, team, i):
    """A ticket's leftover blocker (an old lead task nobody closes) is still open when the ticket merges."""
    if w.now() != START + at(0, 5):
        return
    first = next(t for t in w.tickets() if t["title"] == "Ticket 1")
    old = w.post("tasks", {"owner": "engineering-lead", "title": "Restore an old check", "body": "Old."})
    old = old.get("task", old)
    w.post(f"tasks/{first['id']}/relations", {"task": old["id"], "kind": "blocked_by"})


SCENARIOS = [
    Scenario("happy_path", "Six tickets, every bot answers well: R1, R2, QA, merge, release.",
             setup=lambda run, w, team: tickets(run, w, 6),
             checks=[*BASE, ("no turns on stale notices", QUEUE, no_stale_turns),
                     ("at most a fifth of turns are noise", QUEUE, noise_under(0.2))]),
    Scenario("review_changes", "Reviewers ask for changes most of the time: the builder fixes and moves on.",
             setup=lambda run, w, team: tickets(run, w, 6), styles={"reviewer": {"changes": 0.7}},
             checks=[*BASE, ("one review per round, no re-review", None, one_review_per_round)]),
    Scenario("garbled_reviews", "Reviewers' replies are often garbled: no verdict line, so finishing is refused.",
             setup=lambda run, w, team: tickets(run, w, 6), styles={"reviewer": {"garbled": 0.4, "changes": 0.3}},
             checks=[*BASE, ("no ticket waits over 1.5h at a review", TIMEOUT, max_at_review(1.5))]),
    Scenario("silent_reviewer", "One reviewer never reports back: its reviews must time out after an hour.",
             setup=lambda run, w, team: tickets(run, w, 6), styles={"reviewer-gpt": {"silent": 1.0}},
             checks=[*BASE, ("no ticket waits over 1.5h at a review", TIMEOUT, max_at_review(1.5))]),
    Scenario("quota_outage", "Every bot hits its usage limit for 3h while tickets are mid-flight and a person triages.",
             setup=lambda run, w, team: tickets(run, w, 14),
             during=both(outage(at(0, 30), 3), close_many(at(1), 4)), hours=16,
             checks=[*BASE, ("no turns on stale notices", QUEUE, no_stale_turns),
                     ("at most 3 turns per bot in the hour after", QUEUE, burst_after(at(3, 30), 3))]),
    Scenario("computer_off", "The builders' computer is off for 3h while reviews and QA finish.",
             setup=lambda run, w, team: tickets(run, w, 10),
             during=outage(at(0, 20), 3, slugs={"builder-claude", "builder-openai"}, kind="off"),
             checks=[*BASE, ("no run left waiting for a person", "uncertain runs", no_uncertain_runs), ("no turns on stale notices", QUEUE, no_stale_turns),
                     ("at most 3 builder turns in the hour after", QUEUE,
                      burst_after(at(3, 20), 3, bots={"builder-claude", "builder-openai"}))]),
    Scenario("bulk_triage", "A person closes 12 of 20 queued tickets at once.",
             setup=lambda run, w, team: tickets(run, w, 20), during=close_many(at(0, 5), 12), slots=2,
             checks=[*BASE, ("no turns on stale notices", QUEUE, no_stale_turns)]),
    Scenario("merged_stale_blocker", "A ticket keeps an old open blocker; it merges and must still ship.",
             setup=lambda run, w, team: tickets(run, w, 3), during=stale_blocker,
             checks=[*BASE]),
    Scenario("backlog_30", "Thirty tickets land on one builder.",
             setup=lambda run, w, team: tickets(run, w, 30, owner="builder-claude"), hours=16,
             checks=[("at most 4 tickets in work per builder", SLOTS, peak_doing(4)),
                     ("Head of Engineering hears of the backlog", HOE, lead_heard_of("backlog"))]),
    Scenario("qa_mixed", "QA fails a third of changes and can't test another third.",
             setup=lambda run, w, team: tickets(run, w, 8), styles={"qa": {"fail": 0.33, "cant_test": 0.33}},
             checks=[*BASE]),
    Scenario("off_script", "Reviewers sometimes try to move the ticket themselves (refused).",
             setup=lambda run, w, team: tickets(run, w, 6), styles={"reviewer": {"off_script": 0.3}},
             checks=[*BASE, ("no ticket waits over 1.5h at a review", TIMEOUT, max_at_review(1.5))]),
    Scenario("engineering_budget", "An hourly budget of $10 for the team (below what it would spend): work slows to it, and still ships.",
             setup=company_cap(10), hours=24,
             checks=[*BASE, ("the $10 hourly cap holds", None, hourly_spend_under(10))]),
    Scenario("stuck_ticket", "A builder's runs on one ticket keep crashing: Head of Engineering must notice.",
             setup=lambda run, w, team: tickets(run, w, 4),
             styles={"builder-claude": {"crash_titles": ["Ticket 1"]}},
             checks=[("every stuck ticket seen by Head of Engineering within 2h", HOE, stuck_unseen(2))]),
]
