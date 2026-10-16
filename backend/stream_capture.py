"""A run's raw provider stream, kept for a week to turn into a replay fixture (`hub run export --fixture`).

A bot whose `capture_stream` is on has its runner record every frame it wrote to the harness and every
frame it read back (runner-rs/src/capture.rs), scrubbed of the turn's secrets and capped at about 5 MB.
A raw stream can hold customer text, so only owners and engineering bots read it, and only for a run
they may already see.
"""

import json
import re

from . import task_privacy as privacy
from .store import H, Problem

KEEP_DAYS = 7
# The runner's 5 MB cap plus its truncation marker and the JSON around it.
MAX_FRAMES = 5_200_000
# Credential shapes masked again here, whatever the runner missed: provider keys, GitHub and Slack tokens,
# AWS access key ids and bearer headers.
TOKEN_RE = re.compile(r"\b(?:sk-ant-[A-Za-z0-9_-]{10,}|sk-[A-Za-z0-9_-]{20,}|gh[pousr]_[A-Za-z0-9]{20,}"
                      r"|github_pat_[A-Za-z0-9_]{20,}|xox[abeprs]-[A-Za-z0-9-]{10,}|AKIA[0-9A-Z]{16})"
                      r"|(?i:bearer)\s+[A-Za-z0-9._~+/-]{16,}=*")
MASK = "••••"
# A fixture's expected events: enough for any replay; a run with more says so instead of growing the answer.
MAX_EVENTS = 5000


def wanted(config):
    return (config or {}).get("capture_stream") == "on"


def sweep(c):
    c.execute("DELETE FROM attempt_captures WHERE created<?", (H.shift(H.now(), days=-KEEP_DAYS),))


def mask(text):
    return TOKEN_RE.sub(MASK, text)


def scrub_value(c, value, label, attempt_id="", conversation_id=""):
    """A secret taken out after the run (backend/credential_cards.py) leaves the raw streams that carried it too:
    the run named, and every run in the conversation named."""
    forms = {value, json.dumps(value)[1:-1]}
    ids = {attempt_id} if attempt_id else set()
    if conversation_id:
        ids.update(r[0] for r in c.execute("SELECT attempt_id FROM attempt_conversations WHERE conversation_id=?",
                                           (conversation_id,)))
    for aid in ids:
        row = c.execute("SELECT frames FROM attempt_captures WHERE attempt_id=?", (aid,)).fetchone()
        if row and any(f in row["frames"] for f in forms):
            frames = row["frames"]
            for form in sorted(forms, key=len, reverse=True):
                frames = frames.replace(form, label)
            c.execute("UPDATE attempt_captures SET frames=?,bytes=? WHERE attempt_id=?",
                      (frames, len(frames.encode()), aid))


def keep(c, row, body):
    """A runner hands in its attempt's stream (`row` is the attempt, already checked as that runner's)."""
    sweep(c)
    found = c.execute("SELECT config_json FROM bot_config WHERE bot=?", (row["bot"],)).fetchone()
    if not wanted(json.loads(found[0] or "{}") if found else {}):
        # Turned off since the turn began, or never on: nothing is kept.
        raise Problem("capture_off", "This bot does not capture its provider stream", 409)
    frames = mask(body.frames)
    c.execute("INSERT INTO attempt_captures(attempt_id,bot,provider,frames,truncated,dropped_bytes,bytes,created) "
              "VALUES(?,?,?,?,?,?,?,?) ON CONFLICT(attempt_id) DO UPDATE SET provider=excluded.provider,"
              "frames=excluded.frames,truncated=excluded.truncated,dropped_bytes=excluded.dropped_bytes,"
              "bytes=excluded.bytes,created=excluded.created",
              (row["id"], row["bot"], body.provider, frames, int(body.truncated), body.dropped_bytes,
               len(frames.encode()), H.now()))
    return {"kept": True, "bytes": len(frames.encode()), "truncated": body.truncated}


def may_read(c, who):
    if who.role == "owner":
        return True
    if who.role != "bot" or not str(who.actor).startswith("bot:"):
        return False
    team = c.execute("SELECT team FROM bot_config WHERE bot=?", (who.actor[4:],)).fetchone()
    return bool(team and team["team"] == "engineering")


def export(c, who, aid):
    """The run as a three-part replay fixture: what it was given, the raw stream, and what Tico made of it."""
    if not may_read(c, who):
        raise Problem("forbidden", "Only owners and engineering bots read a run's raw stream", 403)
    privacy.require_attempt(c, who, aid)
    cap = c.execute("SELECT * FROM attempt_captures WHERE attempt_id=? AND created>=?",
                    (aid, H.shift(H.now(), days=-KEEP_DAYS))).fetchone()
    if not cap:
        raise Problem("not_found", "No stream was captured for this run, or it is over a week old", 404)
    attempt = c.execute("SELECT * FROM attempts WHERE id=?", (aid,)).fetchone()
    msg = H.message(c, c.execute("SELECT message_id FROM jobs WHERE id=?", (attempt["job_id"],)).fetchone()[0])
    # A deleted message's text is not served again; the stream may still hold it until the week is out.
    message = ({"kind": msg["kind"], "from": msg["from_actor"], "body": mask(msg["body"] or "")} if msg
               else {"deleted": True})
    config = c.execute("SELECT config_json FROM bot_config WHERE bot=?", (attempt["bot"],)).fetchone()
    declared = json.loads(config[0] or "{}") if config else {}
    events = [{"seq": e["seq"], "kind": e["kind"], "payload": json.loads(e["payload_json"])}
              for e in c.execute("SELECT seq,kind,payload_json FROM attempt_events WHERE attempt_id=? ORDER BY seq "
                                 "LIMIT ?", (aid, MAX_EVENTS + 1))]
    result = json.loads(attempt["result_json"]) if attempt["result_json"] else {}
    return {
        "attempt": {"id": aid, "bot": attempt["bot"], "state": attempt["state"], "created": attempt["created"],
                    "started": attempt["started"], "finished": attempt["finished"]},
        "provider": cap["provider"],
        "truncated": bool(cap["truncated"]),
        "dropped_bytes": cap["dropped_bytes"],
        "captured": cap["created"],
        "input": {"message": message,
                  "config": {k: declared.get(k) for k in ("runtime", "harness", "model", "reasoning_effort")
                             if declared.get(k) is not None}},
        "transcript": cap["frames"],
        "output": {"events": json.loads(mask(json.dumps(events[:MAX_EVENTS]))),
                   "events_truncated": len(events) > MAX_EVENTS,
                   "result": json.loads(mask(json.dumps(result))),
                   "final_text": mask(attempt["final_text"] or "")},
    }
