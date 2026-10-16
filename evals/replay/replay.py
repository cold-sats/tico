"""Behaviour replay: re-run a finished task on a candidate build or prompt and score it against what happened.

A case is one real task: its opening state (title, body, the people's messages and the files it had before the bot's
first run, and the bot's prompt version) and its original outcome (final status, what the bot said, the files it
attached, runs and minutes). capture.py writes a draft case from a finished task; a person reads it, cuts anything
private and signs it with `reviewed_by`. run.py replays signed cases on a scratch team and writes the report.

Both sides are scored by the same code: the BotOps scorers (evals/botops/score.py) for jargon, duplicates and settings
detours, and the case's `done` checks. So an edit the reviewing person makes to the original transcript applies to the
baseline too. Pure and stdlib-only apart from yaml, so the scripted test (backend/tests/test_replay_evals.py) and the
live runner score the same way.

Real cases hold a customer's words and live outside this public repository (`--cases`); `cases/` here holds only a
made-up example.
"""
import hashlib
import re
import sys
from datetime import datetime
from pathlib import Path

import yaml

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "botops"))
import score  # noqa: E402  (the BotOps scorers)

# A replayed task has settled when it reaches one of these and its bot is not running.
SETTLED = ("waiting", "review", "ready", "done", "closed", "declined")
# Lower is better for each; minutes are reported but too noisy to decide a verdict.
NUMBERS = ("person_steps", "jargon", "duplicates", "sent_elsewhere", "runs")
# What a case may never hold once signed: a key, a token, a password in a URL, an email address.
SECRET = re.compile(
    r"(?<![\w-])(sk-[A-Za-z0-9_-]{16,}|gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,}|xox[abpr]-[A-Za-z0-9-]{10,}|"
    r"AKIA[0-9A-Z]{16}|-----BEGIN [A-Z ]*PRIVATE KEY-----|eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.|"
    r"https?://[^/\s:@]+:[^/\s@]+@|[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,})")


def sha(text):
    return hashlib.sha256(str(text or "").encode()).hexdigest()


def when(stamp):
    return datetime.fromisoformat(str(stamp).replace("Z", "+00:00"))


def load(folder):
    """Every case in `folder`, sorted by file name."""
    return [yaml.safe_load(p.read_text()) | {"_path": str(p)} for p in sorted(Path(folder).glob("*.yaml"))]


def secrets_in(value):
    """Each secret-looking string anywhere in a case (keys, tokens, emails), for capture and the run's refusal."""
    if isinstance(value, dict):
        return [hit for v in value.values() for hit in secrets_in(v)]
    if isinstance(value, (list, tuple)):
        return [hit for v in value for hit in secrets_in(v)]
    return [m.group(0) for m in SECRET.finditer(value)] if isinstance(value, str) else []


def problems(case):
    """Why a case may not run: unsigned, or still holding a secret, or missing what a replay needs."""
    found = []
    if not str(case.get("reviewed_by") or "").strip():
        found.append("no reviewed_by: a person has not read and redacted it")
    for key in ("id", "bot", "task", "original"):
        if not case.get(key):
            found.append(f"no {key}")
    if not (case.get("task") or {}).get("title"):
        found.append("no task title")
    hits = secrets_in({k: v for k, v in case.items() if k != "_path"})
    if hits:
        found.append(f"{len(hits)} secret-looking value(s) left, e.g. {hits[0][:12]}…")
    return found


# ------------------------------------------------------------------ capture: a finished task -> a draft case
def _person(actor):
    return str(actor or "").startswith("human:")


def split(detail, files, instructions, bot=None):
    """A draft case from a task's detail (GET tasks/{id}), its files (GET tasks/{id}/files) and its bot's
    instructions snapshot (GET bots/{bot}/instructions). The opening state is everything a person wrote or attached
    before the bot's first run; the original outcome is what followed."""
    task = detail["task"]
    bot = bot or str(task["owner"]).removeprefix("bot:")
    runs = sorted((r for r in detail.get("runs") or [] if r.get("started")), key=lambda r: r["started"])
    if not runs:
        raise ValueError("the task has no runs to replay")
    start = when(runs[0]["started"])
    seen, opening, transcript = set(), [], []
    for m in sorted((detail.get("messages") or []) + (detail.get("comments") or []), key=lambda m: m["created"]):
        if m["id"] in seen or m.get("kind") == "notice" or m.get("deleted_at"):
            continue
        seen.add(m["id"])
        mine = m["from_actor"] == "bot:" + bot
        if when(m["created"]) < start:
            if _person(m["from_actor"]):
                opening.append({"from": "person", "text": m["body"]})
        elif mine or _person(m["from_actor"]):
            transcript.append(["bot" if mine else "person", m["body"]])
    opened, attached = [], []
    for f in files.get("files") or []:
        first = min(f.get("versions") or [{}], key=lambda v: v.get("n", 0))
        if first.get("by") == "bot:" + bot or (first.get("created") and when(first["created"]) >= start):
            attached.append(f["name"])
        else:
            opened.append({"name": f["name"], "text": first.get("text", "")})
    minutes = sum((when(r["finished"]) - when(r["started"])).total_seconds() for r in runs if r.get("finished")) / 60
    snapshot = instructions.get("content") or ""
    exact = bool(instructions.get("updated")) and when(instructions["updated"]) <= start
    status = task["status"]
    return {
        "id": re.sub(r"[^a-z0-9]+", "-", task["title"].lower()).strip("-")[:50],
        "title": task["title"],
        "source": {"task": task["id"], "captured": datetime.now().astimezone().isoformat(timespec="seconds")},
        "reviewed_by": "",
        "bot": bot,
        # The prompt the original ran on. `exact: false`: the snapshot is newer than the task's first run.
        "prompt": {"sha256": sha(snapshot), "updated": instructions.get("updated"), "exact": exact},
        "task": {"title": task["title"], "body": task.get("body") or "",
                 "acceptance_criteria": task.get("acceptance_criteria") or []},
        "conversation": opening,
        "files": opened,
        "person": [],
        "done": [{"status": ["done", "review", "ready", "closed"] if status in ("done", "review", "ready", "closed")
                  else [status]}],
        "limits": {},
        "original": {"status": status, "transcript": transcript, "files": attached, "runs": len(runs),
                     "minutes": round(minutes, 1),
                     "person_steps": sum(1 for who, _ in transcript if who == "person")},
    }


# ------------------------------------------------------------------ scoring, the same for both sides
def check(predicate, outcome, facts):
    (name, args), = ({predicate: {}} if isinstance(predicate, str) else predicate).items()
    if name == "status":
        wanted = [args] if isinstance(args, str) else list(args)
        return name, outcome["status"] in wanted, f"ended {outcome['status']}"
    if name == "file_attached":
        hit = any(re.search(str(args), n, re.I) for n in outcome.get("files") or [])
        return name, hit, "no attached file matches"
    if name in ("reply_matches", "reply_not_matches"):
        return score.check(predicate, facts)
    raise ValueError("Unknown check: " + name)


def measure(case, outcome):
    """One side's result. `outcome`: status, transcript [(from, text)], files, runs, minutes, person_steps."""
    transcript = [tuple(t) for t in outcome.get("transcript") or []]
    said = [t for who, t in transcript if who == "bot"]
    facts = score.Facts(None, None, said)
    checks = [check(p, outcome, facts) for p in case.get("done") or []]
    numbers = {"person_steps": int(outcome.get("person_steps") or 0),
               "jargon": sum(len(score.jargon_words(t)) for t in said),
               "duplicates": score.duplicates(transcript), "sent_elsewhere": score.sent_elsewhere(said),
               "runs": int(outcome.get("runs") or 0)}
    limits = case.get("limits") or {}
    over = {k: v for k, v in numbers.items() if v > limits.get(k, 10**6)}
    done = all(held for _, held, _ in checks)
    return {"done": done, "passed": done and not over, "over_limit": over, "status": outcome.get("status"),
            "minutes": outcome.get("minutes"), "checks": [{"check": n, "held": h, **({} if h else {"why": w})}
                                                          for n, h, w in checks], **numbers}


def compare(before, after):
    """win, regression, mixed or same, and why: done first, then within limits, then each number (lower is better)."""
    for key, label in (("done", "done"), ("passed", "within limits")):
        if before[key] != after[key]:
            return ("win" if after[key] else "regression"), [f"{'now' if after[key] else 'no longer'} {label}"]
    better = [f"{k} {before[k]}→{after[k]}" for k in NUMBERS if after[k] < before[k]]
    worse = [f"{k} {before[k]}→{after[k]}" for k in NUMBERS if after[k] > before[k]]
    if better and worse:
        return "mixed", better + worse
    return ("win", better) if better else ("regression", worse) if worse else ("same", [])


def report(rows, title, prompt_note=""):
    """The release-preparation report: counts, then regressions, then wins, then the full table."""
    count = {v: sum(1 for r in rows if r["verdict"] == v) for v in ("win", "regression", "mixed", "same", "error")}
    lines = [f"# {title}", "", prompt_note, "" if prompt_note else None,
             f"{len(rows)} case{'' if len(rows) == 1 else 's'}: {count['win']} wins, {count['regression']} regressions, {count['mixed']} mixed, "
             f"{count['same']} same" + (f", {count['error']} could not run" if count["error"] else "") + ".", ""]
    for verdict, heading in (("regression", "Regressions"), ("error", "Could not run"), ("win", "Wins"),
                             ("mixed", "Mixed")):
        picked = [r for r in rows if r["verdict"] == verdict]
        if picked:
            lines += [f"## {heading}", ""] + [f"- **{r['id']}**: {'; '.join(r['why']) or '—'}" for r in picked] + [""]
    lines += ["## Every case", "", "| Case | Verdict | Status (was → now) | Done | Steps | Jargon | Dupes | Settings | Runs | Minutes |",
              "|---|---|---|---|---|---|---|---|---|---|"]
    for r in rows:
        b, a = r.get("before") or {}, r.get("after") or {}
        pair = lambda k: f"{b.get(k, '—')} → {a.get(k, '—')}"  # noqa: E731
        lines.append(f"| {r['id']} | {r['verdict']} | {pair('status')} | {pair('done')} | {pair('person_steps')} | "
                     f"{pair('jargon')} | {pair('duplicates')} | {pair('sent_elsewhere')} | {pair('runs')} | {pair('minutes')} |")
    return "\n".join(line for line in lines if line is not None) + "\n"
