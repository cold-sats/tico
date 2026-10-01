"""Which release each computer runs, and whether this server can work with it.

A runner reports its release (`0.3.0`, or "" for a checkout that is not on a release tag), its kind
(mac, linux, docker) and how its self-update stands. The server answers with the release it runs
(`GET /api/v2/runners/desired`); runners follow that, never GitHub. `MIN_RUNNER_RELEASE` is the
oldest runner this server accepts: raise it in the release that changes the runner/server contract.
A runner below it is paused (it gets no work, with the reason) instead of failing turns. A runner that
does not report a release (before this existed, or a development checkout) is never paused.
"""
from . import releases
from .store import H

MIN_RUNNER_RELEASE = "0.1.0"
KINDS = ("mac", "linux", "docker")
LABELS = {"current": "Up to date", "updating": "Updating", "needs_update": "Needs update",
          "incompatible": "Incompatible (bots paused)", "unknown": "Version not reported"}

SCHEMA = """
CREATE TABLE IF NOT EXISTS runner_versions(
 runner_id TEXT PRIMARY KEY REFERENCES runners(id), release TEXT NOT NULL DEFAULT '',
 kind TEXT NOT NULL DEFAULT '', update_state TEXT NOT NULL DEFAULT '', update_target TEXT NOT NULL DEFAULT '',
 update_error TEXT NOT NULL DEFAULT '', reported TEXT NOT NULL);
"""


def clean(value):
    return str(value or "").strip().lstrip("v")


def desired():
    """What a runner should be on: this server's release, or "" for a build that has none (dev)."""
    server = releases.version()
    return {"version": server if releases.parse(server) else "", "min_runner": MIN_RUNNER_RELEASE}


def incompatible(release):
    parsed = releases.parse(release)
    return bool(parsed and parsed < releases.parse(MIN_RUNNER_RELEASE))


def at_least(c, runner_id, minimum):
    """One-time runner steps require a reported version that supports the step.

    Unknown versions keep the step pending, rather than consuming it without doing it.
    """
    row = c.execute("SELECT release FROM runner_versions WHERE runner_id=?", (runner_id,)).fetchone()
    have = releases.parse(row["release"]) if row else None
    want = releases.parse(minimum)
    return bool(have and want and have >= want)


def state(release, update_state="", server=None):
    """One of current, updating, needs_update, incompatible, unknown."""
    server = releases.version() if server is None else server
    if incompatible(release):
        return "incompatible"
    if update_state == "updating":
        return "updating"
    have, want = releases.parse(release), releases.parse(server)
    if not have or not want:
        return "unknown"
    return "needs_update" if have < want else "current"


def record(c, runner_id, body):
    """Store what a heartbeat reported. Called only when the runner sent a release."""
    release = clean(body.release)
    update = body.update
    c.execute("INSERT INTO runner_versions(runner_id,release,kind,update_state,update_target,update_error,reported) "
              "VALUES(?,?,?,?,?,?,?) ON CONFLICT(runner_id) DO UPDATE SET release=excluded.release,"
              "kind=excluded.kind,update_state=excluded.update_state,update_target=excluded.update_target,"
              "update_error=excluded.update_error,reported=excluded.reported",
              (runner_id, release, body.kind or "", update.state if update else "", update.target if update else "",
               update.error if update else "", H.now()))
    if body.checkout is None:   # it follows the server's release now, not main: an old "behind main" note is stale
        c.execute("UPDATE runners SET checkout_json=NULL WHERE id=?", (runner_id,))


def paused(c, runner_id):
    """Why this computer must not claim work, or "" when it may."""
    row = c.execute("SELECT release FROM runner_versions WHERE runner_id=?", (runner_id,)).fetchone()
    if not row or not incompatible(row["release"]):
        return ""
    return (f"This computer runs Tico {row['release']}, which this server ({releases.version()}) cannot work with; "
            f"it needs {MIN_RUNNER_RELEASE} or later. Its bots are paused until it updates.")


def load(c):
    return {r["runner_id"]: dict(r) for r in c.execute("SELECT * FROM runner_versions")}


# What a runner before this release said when nothing supervised it; the line now says how to fix that.
NO_SUPERVISOR = ("no supervisor would start this runner again after an update: run `scripts/tico install` "
                 "once on this computer and it updates itself")


def view(row, server=None):
    row = row or {}
    release = row.get("release") or ""
    found = state(release, row.get("update_state") or "", server) if row else "unknown"
    return {"release": release, "kind": row.get("kind") or "", "state": found, "label": LABELS[found],
            "update_state": row.get("update_state") or "", "target": row.get("update_target") or "",
            "error": NO_SUPERVISOR if str(row.get("update_error") or "").startswith("nothing would start this runner")
            else row.get("update_error") or "", "min_runner": MIN_RUNNER_RELEASE}


def health_check(computers, server=None):
    """The Health line about runner versions, or None on a development build that has no release to
    compare with. `computers` carry `online`, `label` and `update`."""
    server = releases.version() if server is None else server
    online = [x for x in computers if x["online"]]
    if not releases.parse(server):
        return None
    bad = [x for x in online if x["update"]["state"] == "incompatible"]
    behind = [x for x in online if x["update"]["state"] in ("needs_update", "updating")]
    failed = [x for x in online if x["update"]["error"]]
    fixes = [{"label": "Open Computers", "href": "#/settings", "tab": "devices", "click": ""}]
    names = lambda rows: ", ".join(x["label"] for x in rows[:5])   # noqa: E731
    unknown = [x for x in online if x["update"]["state"] == "unknown"]
    newer = [x for x in online if releases.parse(x["update"].get("release"))
             and releases.parse(x["update"]["release"]) > releases.parse(server)]
    notes = []
    if unknown:
        notes.append(f"Version not reported: {names(unknown)}.")
    if newer:
        notes.append("Newer than this server: " + ", ".join(
            f"{x['label']} ({x['update']['release']})" for x in newer[:5]) + ".")
    extra = " " + " ".join(notes) if notes else ""
    if bad:
        return {"id": "runners", "label": "Runner versions", "status": "bad", "fixes": fixes,
                "summary": f"{names(bad)} cannot work with {server} and its bots are paused until it updates." + extra}
    if behind or failed:
        note = f" Last update error: {failed[0]['update']['error']}" if failed else ""
        return {"id": "runners", "label": "Runner versions", "status": "warn", "fixes": fixes,
                "summary": f"{names(behind or failed)} {'is' if len(behind or failed) == 1 else 'are'} not on {server} yet." + note + extra}
    return {"id": "runners", "label": "Runner versions", "status": "unknown" if unknown else "info" if newer else "ok",
            "fixes": fixes if unknown else [], "summary": " ".join(notes) if notes else
            f"Every online computer is on {server}." if online else "No computer is online to compare."}
