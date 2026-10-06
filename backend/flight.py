"""The flight recorder: this server's own request, process and database history, kept in its database.

An incident (a server pinned at 100% CPU for hours) should be one query, and a release should be comparable with the one
before it, without installing profilers on the server. So the server keeps, per minute: requests per route template and
caller kind (count, 5xx, p50/p95/max, bytes), process CPU, memory, threads, open files and event-loop lag, and the write
transactions' lock waits and hold times; per hour: SQL time by query shape and the database's size by table; and as
events: each start (release, commit, dependency and settings hashes, whether the image is the published release) and
each stall of the event loop with every thread's stack at that moment.

The request path pays for two clock reads and a deque append (`Recorder.request`, `Recorder.query`); everything else
(bucketing, fingerprinting SQL, writing) happens in one background thread (`Flight`), which writes once a minute in one
short transaction. Nothing leaves the server: no query text with values (SQL is reduced to its shape), no request paths
with ids (route templates only), no bodies, no setting values. Owners and admins read it at `GET /api/v2/system/metrics`
and on the Health page. Retention: minutes for two days, then hours; requests, slow requests and process rows 14 days,
SQL, database and events 90 days (`sweep`, run by the scheduler's hourly sweep).
"""
import bisect
import collections
import hashlib
import json
import logging
import os
import re
import sqlite3
import sys
import threading
import time
import traceback

LOG = logging.getLogger("tico.flight")

SCHEMA = """
CREATE TABLE IF NOT EXISTS flight_requests(ts INTEGER NOT NULL, span INTEGER NOT NULL, route TEXT NOT NULL,
  caller TEXT NOT NULL, n INTEGER NOT NULL, errors INTEGER NOT NULL, bytes INTEGER NOT NULL, total_ms REAL NOT NULL,
  p50 REAL, p95 REAL, max_ms REAL, hist TEXT, PRIMARY KEY(ts, span, route, caller)) WITHOUT ROWID;
CREATE TABLE IF NOT EXISTS flight_slow(id INTEGER PRIMARY KEY, ts INTEGER NOT NULL, route TEXT, caller TEXT,
  actor TEXT, ms REAL, bytes INTEGER, status INTEGER);
CREATE TABLE IF NOT EXISTS flight_process(ts INTEGER PRIMARY KEY, cpu REAL, rss INTEGER, threads INTEGER,
  fds INTEGER, sockets INTEGER, lag_p95 REAL, lag_max REAL, requests INTEGER, queries INTEGER, sql_ms REAL,
  txns INTEGER, wait_max REAL, hold_max REAL, hold_p95 REAL, locked INTEGER, dropped INTEGER);
CREATE TABLE IF NOT EXISTS flight_sql(ts INTEGER NOT NULL, fingerprint TEXT NOT NULL, n INTEGER NOT NULL,
  total_ms REAL NOT NULL, p95 REAL, max_ms REAL, hist TEXT, PRIMARY KEY(ts, fingerprint)) WITHOUT ROWID;
CREATE TABLE IF NOT EXISTS flight_db(ts INTEGER PRIMARY KEY, bytes INTEGER, wal_bytes INTEGER, free_bytes INTEGER,
  detail_json TEXT);
CREATE TABLE IF NOT EXISTS flight_events(id INTEGER PRIMARY KEY, ts INTEGER NOT NULL, kind TEXT NOT NULL,
  detail_json TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS flight_events_kind ON flight_events(kind, ts);
"""

SLOW_MS = 1000                  # a request this slow is logged on its own
SLOW_PER_MINUTE = 50
SLOW_KEEP = 5000
STALL_S = 2.0                   # the event loop late by this much: every thread's stack is taken
STALL_GAP = 300                 # at most one capture this often
TICK = 0.25
MINUTE_DAYS = 2                 # request minutes older than this become hours
SHORT_DAYS = 14                 # requests, slow requests, process minutes
LONG_DAYS = 90                  # SQL hours, database sizes, events
SQL_TOP = 100                   # query shapes kept per hour; the rest are one "(other)" row
BUFFER = 200_000                # samples waiting for the background thread, at most
# The tables that grow, counted each hour; with the column that dates their oldest row, read by rowid or an index.
BIG = {"events": "ts", "messages": "created", "attempt_events": "created", "attempts": "created", "jobs": "created",
       "idempotency": "created", "changes": "at", "tasks": "created", "mail_messages": None, "flight_requests": None}
# Histogram bucket edges in milliseconds: 25% apart from 0.05 ms to about a minute. A percentile is its bucket's upper
# edge, so it reads at most a quarter high and never low.
EDGES = [0.05 * 1.25 ** i for i in range(64)]

_LITERAL = re.compile(r"'(?:[^']|'')*'")
_NUMBER = re.compile(r"\b\d+(?:\.\d+)?\b")
_LIST = re.compile(r"\(\s*\?(?:\s*,\s*\?)+\s*\)")
_SPACE = re.compile(r"\s+")


def fingerprint(sql):
    """A statement's shape: literals, numbers and lists of placeholders folded, so one query is one row."""
    text = _SPACE.sub(" ", _NUMBER.sub("N", _LITERAL.sub("'?'", str(sql)))).strip()
    return _LIST.sub("(?,…)", text)[:300]


def quantile(hist, q):
    total = sum(hist.values())
    if not total:
        return 0
    seen, target = 0, q * total
    for i in sorted(hist):
        seen += hist[i]
        if seen >= target:
            return round(EDGES[min(i, len(EDGES) - 1)], 2)
    return 0


def _add(hist, ms):
    i = bisect.bisect_left(EDGES, ms)
    hist[i] = hist.get(i, 0) + 1


def _merge(into, hist):
    for k, v in hist.items():
        into[int(k)] = into.get(int(k), 0) + v


def caller_kind(who):
    role = getattr(who, "role", "") if who is not None else ""
    return {"owner": "human", "human": "human", "bot": "bot", "runner": "runner", "service": "service"}.get(role, "anonymous")


class Recorder:
    """In-memory collection. The request and SQL paths only append; `drain` (the background thread) does the rest."""

    def __init__(self):
        self.samples = collections.deque(maxlen=BUFFER)
        self.lock = threading.Lock()
        self.fingerprints = {}
        self._reset()
        self.sql = {}               # hour -> fingerprint -> [n, total, max, hist]
        self.beat = None            # monotonic time the event loop last woke
        self.loop_thread = None
        self.last_stall = 0.0
        self.cpu = (time.monotonic(), time.process_time())
        self.dropped = 0

    def _reset(self):
        self.requests = {}          # (route, caller) -> [n, errors, bytes, total, max, hist]
        self.slow = []
        self.lag = {}
        self.lag_max = 0.0
        self.queries = 0
        self.sql_ms = 0.0
        self.txns = 0
        self.wait_max = self.hold_max = 0.0
        self.hold = {}
        self.locked = 0

    # The hot paths: one append each, safe from any thread. A full buffer (the background thread is not keeping up)
    # discards the oldest sample; `dropped` counts them, approximately, so the gap shows in the minute's row.
    def request(self, route, caller, status, ms, nbytes=0, actor=""):
        if len(self.samples) >= BUFFER:
            self.dropped += 1
        self.samples.append(("r", route, caller, status, ms, nbytes, actor))

    def query(self, sql, ms, locked=False):
        if len(self.samples) >= BUFFER:
            self.dropped += 1
        self.samples.append(("q", sql, ms, locked))

    def transaction(self, wait_ms, hold_ms, locked=False):
        if len(self.samples) >= BUFFER:
            self.dropped += 1
        self.samples.append(("t", wait_ms, hold_ms, locked))

    def tick(self, lag_ms):
        """The event loop woke `lag_ms` late (backend/timing.py watch_loop)."""
        self.beat = time.monotonic()
        if self.loop_thread is None:
            self.loop_thread = threading.get_ident()
        if len(self.samples) >= BUFFER:
            self.dropped += 1
        self.samples.append(("l", lag_ms))

    def drain(self, now=None):
        hour = int((now or time.time()) // 3600 * 3600)
        edges, fingerprints, find = EDGES, self.fingerprints, bisect.bisect_left
        with self.lock:
            shapes = self.sql.setdefault(hour, {})
            while True:
                try:
                    s = self.samples.popleft()
                except IndexError:
                    return
                kind = s[0]
                if kind == "q":
                    _, sql, ms, locked = s
                    fp = fingerprints.get(sql)
                    if fp is None:
                        if len(fingerprints) > 5000:
                            fingerprints.clear()
                        fp = fingerprints[sql] = fingerprint(sql)
                    row = shapes.get(fp)
                    if row is None:
                        row = shapes[fp] = [0, 0.0, 0.0, {}]
                    row[0] += 1
                    row[1] += ms
                    if ms > row[2]:
                        row[2] = ms
                    hist = row[3]
                    i = find(edges, ms)
                    hist[i] = hist.get(i, 0) + 1
                    self.queries += 1
                    self.sql_ms += ms
                    if locked:
                        self.locked += 1
                elif kind == "r":
                    _, route, caller, status, ms, nbytes, actor = s
                    row = self.requests.get((route, caller))
                    if row is None:
                        row = self.requests[(route, caller)] = [0, 0, 0, 0.0, 0.0, {}]
                    row[0] += 1
                    row[1] += status >= 500
                    row[2] += nbytes or 0
                    row[3] += ms
                    row[4] = max(row[4], ms)
                    _add(row[5], ms)
                    if ms >= SLOW_MS and len(self.slow) < SLOW_PER_MINUTE:
                        self.slow.append((int(time.time()), route, caller, actor, round(ms, 1), nbytes or 0, status))
                elif kind == "t":
                    _, wait, hold, locked = s
                    self.txns += 1
                    self.wait_max = max(self.wait_max, wait)
                    self.hold_max = max(self.hold_max, hold)
                    _add(self.hold, hold)
                    self.locked += bool(locked)
                elif kind == "l":
                    _add(self.lag, s[1])
                    self.lag_max = max(self.lag_max, s[1])

    def stalled(self, now=None):
        """The event loop has not woken for STALL_S past its half-second sleep: take every stack, at most every
        STALL_GAP seconds. Returns the capture, or None."""
        now = now if now is not None else time.monotonic()
        if self.beat is None or now - self.beat < STALL_S + 0.5 or now - self.last_stall < STALL_GAP:
            return None
        self.last_stall = now
        return {"stalled_s": round(now - self.beat, 1), "threads": stacks(self.loop_thread)}

    def take(self, minute):
        """The minute's rows, and the SQL hours, ready to write; the minute's counters start again."""
        with self.lock:
            requests, slow, lag, lag_max = self.requests, self.slow, self.lag, self.lag_max
            totals = (self.queries, self.sql_ms, self.txns, self.wait_max, self.hold_max, self.hold, self.locked)
            self._reset()
            dropped, self.dropped = self.dropped, 0
            sql = {hour: {fp: [r[0], r[1], r[2], dict(r[3])] for fp, r in shapes.items()}
                   for hour, shapes in self.sql.items() if shapes}
            current = max(self.sql) if self.sql else None
            self.sql = {current: self.sql[current]} if current is not None else {}
        mono, cpu = time.monotonic(), time.process_time()
        then = self.cpu
        self.cpu = (mono, cpu)
        process = process_stats()
        queries, sql_ms, txns, wait_max, hold_max, hold, locked = totals
        rows = [(minute, 60, route, caller, r[0], r[1], r[2], round(r[3], 1), quantile(r[5], .5), quantile(r[5], .95),
                 round(r[4], 1), json.dumps(r[5], separators=(",", ":"))) for (route, caller), r in requests.items()]
        proc = (minute, round(100 * (cpu - then[1]) / max(mono - then[0], 1e-6), 1), process["rss"], process["threads"],
                process["fds"], process["sockets"], quantile(lag, .95), round(lag_max, 1),
                sum(r[0] for r in requests.values()), queries, round(sql_ms, 1), txns, round(wait_max, 1),
                round(hold_max, 1), quantile(hold, .95), locked, dropped)
        sql_rows = []
        for hour, shapes in sql.items():
            ranked = sorted(shapes.items(), key=lambda kv: -kv[1][1])
            other = [0, 0.0, 0.0, {}]
            for fp, (n, total, peak, hist) in ranked[SQL_TOP:]:
                other[0] += n
                other[1] += total
                other[2] = max(other[2], peak)
                _merge(other[3], hist)
            kept = ranked[:SQL_TOP] + ([("(other)", other)] if other[0] else [])
            sql_rows += [(hour, fp, n, round(total, 1), quantile(hist, .95), round(peak, 2),
                          json.dumps(hist, separators=(",", ":"))) for fp, (n, total, peak, hist) in kept]
        return {"requests": rows, "slow": slow, "process": proc, "sql": sql_rows}


def write(c, taken):
    c.executemany("INSERT OR REPLACE INTO flight_requests VALUES(?,?,?,?,?,?,?,?,?,?,?,?)", taken["requests"])
    c.executemany("INSERT INTO flight_slow(ts,route,caller,actor,ms,bytes,status) VALUES(?,?,?,?,?,?,?)", taken["slow"])
    c.execute("INSERT OR REPLACE INTO flight_process VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", taken["process"])
    c.executemany("INSERT OR REPLACE INTO flight_sql VALUES(?,?,?,?,?,?,?)", taken["sql"])


def process_stats():
    out = {"rss": None, "threads": threading.active_count(), "fds": None, "sockets": None}
    try:
        with open("/proc/self/statm") as f:
            out["rss"] = int(f.read().split()[1]) * os.sysconf("SC_PAGE_SIZE")
    except (OSError, ValueError, IndexError):
        try:
            import resource         # peak, not current, where /proc is missing (macOS)
            peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
            out["rss"] = peak if sys.platform == "darwin" else peak * 1024
        except Exception:
            pass
    try:
        fds = os.listdir("/proc/self/fd")
        out["fds"] = len(fds)
        sockets = 0
        for fd in fds:
            try:
                sockets += os.readlink("/proc/self/fd/" + fd).startswith("socket:")
            except OSError:
                pass
        out["sockets"] = sockets
    except OSError:
        pass
    return out


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
IDLE = {("threading.py", "wait"), ("queue.py", "get"), ("selectors.py", "select"), ("thread.py", "_worker"),
        ("threading.py", "_wait_for_tstate_lock")}


def _where(filename):
    if filename.startswith(ROOT):
        return os.path.relpath(filename, ROOT)
    parts = filename.replace("\\", "/").split("/")
    if "site-packages" in parts:
        return "/".join(parts[parts.index("site-packages") + 1:])
    return "/".join(parts[-2:])


def stacks(loop_thread=None, depth=14, limit=24):
    """Every thread's innermost frames as `file:line function`: where each one is, never its values. Idle pool threads
    are counted, not listed."""
    names = {t.ident: t.name for t in threading.enumerate()}
    me = threading.get_ident()
    out, idle = [], 0
    for ident, frame in sys._current_frames().items():
        if ident == me:
            continue
        frames = traceback.extract_stack(frame)[-depth:]
        inner = frames[-1] if frames else None
        loop = ident == loop_thread
        if not loop and inner and (os.path.basename(inner.filename), inner.name) in IDLE:
            idle += 1
            continue
        out.append({"thread": names.get(ident, str(ident)), "loop": loop,
                    "stack": [f"{_where(f.filename)}:{f.lineno} {f.name}" for f in frames]})
    out.sort(key=lambda t: not t["loop"])
    return {"busy": out[:limit], "idle": idle}


_clock = time.perf_counter


class TimedCursor(sqlite3.Cursor):
    """A statement's cursor that adds the time spent fetching its rows to the statement's one sample, recorded when the
    rows run out, at `fetchall`, or when the cursor is dropped. Iteration is timed row by row, never the caller's work
    between rows."""
    recorder = None
    _sql = None
    _ms = 0.0

    def _record(self):
        sql = self._sql
        if sql is not None:
            self._sql = None
            self.recorder.query(sql, self._ms)

    def fetchone(self):
        started = _clock()
        row = super().fetchone()
        self._ms += (_clock() - started) * 1000
        if row is None:
            self._record()
        return row

    def fetchall(self):
        started = _clock()
        rows = super().fetchall()
        self._ms += (_clock() - started) * 1000
        self._record()
        return rows

    def fetchmany(self, size=None):
        started = _clock()
        rows = super().fetchmany() if size is None else super().fetchmany(size)
        self._ms += (_clock() - started) * 1000
        if len(rows) < (self.arraysize if size is None else size):
            self._record()
        return rows

    def __iter__(self):
        return self._rows()

    def _rows(self):
        # Rows are stepped in small batches so the clock is read per batch, not per row.
        fetch = sqlite3.Cursor.fetchmany
        while True:
            started = _clock()
            rows = fetch(self, 32)
            self._ms += (_clock() - started) * 1000
            if not rows:
                self._record()
                return
            yield from rows

    def __del__(self):
        if self._sql is not None:
            self._record()


class TimedConnection(sqlite3.Connection):
    """A Store connection whose statements are timed, rows fetched included, for the flight recorder."""
    recorder = None
    cursor_class = TimedCursor

    def execute(self, sql, parameters=()):
        cursor = self.cursor(self.cursor_class)
        started = _clock()
        try:
            cursor.execute(sql, parameters)
        except sqlite3.OperationalError as exc:
            self.recorder.query(sql, (_clock() - started) * 1000, "locked" in str(exc))
            raise
        except Exception:
            self.recorder.query(sql, (_clock() - started) * 1000)
            raise
        cursor._ms = (_clock() - started) * 1000
        cursor._sql = sql
        return cursor

    def executemany(self, sql, parameters):
        started = _clock()
        try:
            return super().executemany(sql, parameters)
        finally:
            self.recorder.query(sql, (_clock() - started) * 1000)


def connection_class(recorder):
    cursor = type("RecordedCursor", (TimedCursor,), {"recorder": recorder})
    return type("RecordedConnection", (TimedConnection,), {"recorder": recorder, "cursor_class": cursor})


# ---------------------------------------------------------------------------- what this server is

SECRET = re.compile(r"secret|token|password|key|dsn|credential|arn|identities|email|url|issuer|audience|owner", re.I)


def config_fingerprint(settings):
    """Per non-secret setting a short hash (so two starts show which changed), and one hash of them all. Fields kept out
    of repr, and any whose name could hold a secret or an address, are left out entirely: no value is ever recorded."""
    import dataclasses
    fields = {}
    for f in dataclasses.fields(settings):
        if not f.repr or SECRET.search(f.name):
            continue
        fields[f.name] = hashlib.sha256(repr(getattr(settings, f.name, None)).encode()).hexdigest()[:10]
    whole = hashlib.sha256(json.dumps(fields, sort_keys=True).encode()).hexdigest()[:16]
    return whole, fields


def dependency_hash():
    try:
        from importlib import metadata
        pins = sorted(f"{d.metadata['Name']}=={d.version}" for d in metadata.distributions() if d.metadata["Name"])
    except Exception:
        return ""
    return hashlib.sha256("\n".join(pins).encode()).hexdigest()[:16]


def code_state(root=ROOT):
    """`modified` when the code differs from what the image was built with (files copied over a release image), `match`
    when it is the same, None when the image recorded no hash (a source checkout, or an image from before the hash)."""
    try:
        expected = json.loads(open(os.path.join(root, "release-manifest.json")).read()).get("code")
    except (OSError, ValueError, AttributeError):
        return None
    if not expected:
        return None
    from .code_hash import digest
    return "match" if digest(root) == expected else "modified"


def provenance(settings, version, root=ROOT):
    """Whether this image runs the code it was built with, from the commit its release tag names on GitHub. `modified`
    is code changed after the build (files copied over a release image); `mismatch` an image built elsewhere and
    labelled as a release; `unverified` a release label with no commit to check."""
    from . import releases
    if code_state(root) == "modified":
        return "modified"
    if not releases.parse(version) or settings.rehearsal or not releases.Checker.enabled():
        return "unknown"
    if not settings.release_commit or not settings.release_repo:
        return "unverified"
    try:
        with releases._client(timeout=5) as http:
            reply = http.get(f"https://api.github.com/repos/{settings.release_repo}/commits/v{version}",
                             headers={"Accept": "application/vnd.github.sha"})
        if reply.status_code != 200:
            return "unknown"
        published = reply.text.strip()
    except Exception:
        return "unknown"
    return "match" if published == settings.release_commit else "mismatch"


def start_event(settings, check=True):
    from . import releases
    version = releases.version()
    whole, fields = config_fingerprint(settings)
    return {"version": version, "commit": settings.release_commit, "repository": settings.release_repo,
            "python": sys.version.split()[0], "sqlite": sqlite3.sqlite_version, "dependencies": dependency_hash(),
            "config": whole, "config_fields": fields,
            "provenance": provenance(settings, version) if check else "unknown"}


def record_event(store, kind, detail, now=None):
    with store.transaction() as c:
        c.execute("INSERT INTO flight_events(ts,kind,detail_json) VALUES(?,?,?)",
                  (int(now or time.time()), kind, json.dumps(detail, separators=(",", ":"))))


def last_start(c):
    row = c.execute("SELECT ts,detail_json FROM flight_events WHERE kind='start' ORDER BY ts DESC,id DESC LIMIT 1"
                    ).fetchone()
    return {"at": row[0], **json.loads(row[1])} if row else None


# ---------------------------------------------------------------------------- the database itself

def db_stats(store, use_dbstat=True):
    path = str(store.settings.db_path)
    size = os.path.getsize(path) if os.path.exists(path) else 0
    wal = os.path.getsize(path + "-wal") if os.path.exists(path + "-wal") else 0
    detail = {"objects": None, "rows": {}, "oldest": {}}
    with store.read() as c:
        page_size = c.execute("PRAGMA page_size").fetchone()[0]
        free = c.execute("PRAGMA freelist_count").fetchone()[0] * page_size
        present = {r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if use_dbstat:
            try:
                objects = c.execute("SELECT name, sum(pgsize) FROM dbstat GROUP BY name ORDER BY 2 DESC LIMIT 40"
                                    ).fetchall()
                detail["objects"] = {r[0]: r[1] for r in objects}
            except sqlite3.OperationalError:
                detail["objects"] = None            # SQLite built without dbstat
        for table, column in BIG.items():
            if table not in present:
                continue
            detail["rows"][table] = c.execute(f"SELECT count(*) FROM {table}").fetchone()[0]
            if column:
                row = c.execute(f"SELECT {column} FROM {table} ORDER BY rowid LIMIT 1").fetchone()
                detail["oldest"][table] = row[0] if row else None
    return size, wal, free, detail


# ---------------------------------------------------------------------------- retention

def sweep(store, now=None):
    """Request minutes older than two days become hours; old rows go. Each step is its own short transaction."""
    now = int(now or time.time())
    cutoff = now - MINUTE_DAYS * 86400
    while True:
        with store.transaction() as c:
            row = c.execute("SELECT min(ts) FROM flight_requests WHERE span=60 AND ts<?", (cutoff,)).fetchone()
            if row[0] is None:
                break
            hour = row[0] // 3600 * 3600
            end = min(hour + 3600, cutoff)
            merged = {}
            for r in c.execute("SELECT route,caller,n,errors,bytes,total_ms,max_ms,hist FROM flight_requests "
                               "WHERE span=60 AND ts>=? AND ts<?", (hour, end)):
                m = merged.setdefault((r[0], r[1]), [0, 0, 0, 0.0, 0.0, {}])
                m[0] += r[2]
                m[1] += r[3]
                m[2] += r[4]
                m[3] += r[5]
                m[4] = max(m[4], r[6] or 0)
                _merge(m[5], json.loads(r[7] or "{}"))
            for (route, caller), m in merged.items():
                old = c.execute("SELECT n,errors,bytes,total_ms,max_ms,hist FROM flight_requests WHERE ts=? AND span=3600 "
                                "AND route=? AND caller=?", (hour, route, caller)).fetchone()
                if old:                         # the hour's earlier part, rolled up by an earlier sweep
                    m[0] += old[0]
                    m[1] += old[1]
                    m[2] += old[2]
                    m[3] += old[3]
                    m[4] = max(m[4], old[4] or 0)
                    _merge(m[5], json.loads(old[5] or "{}"))
                c.execute("INSERT OR REPLACE INTO flight_requests VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                          (hour, 3600, route, caller, m[0], m[1], m[2], round(m[3], 1), quantile(m[5], .5),
                           quantile(m[5], .95), m[4], json.dumps(m[5], separators=(",", ":"))))
            c.execute("DELETE FROM flight_requests WHERE span=60 AND ts>=? AND ts<?", (hour, end))
    short, long = now - SHORT_DAYS * 86400, now - LONG_DAYS * 86400
    with store.transaction() as c:
        c.execute("DELETE FROM flight_requests WHERE ts<?", (short,))
        c.execute("DELETE FROM flight_slow WHERE ts<? OR id<=(SELECT max(id) FROM flight_slow)-?", (short, SLOW_KEEP))
        c.execute("DELETE FROM flight_process WHERE ts<?", (short,))
        c.execute("DELETE FROM flight_sql WHERE ts<?", (long,))
        c.execute("DELETE FROM flight_db WHERE ts<?", (long,))
        c.execute("DELETE FROM flight_events WHERE ts<? AND kind<>'start'", (long,))
        c.execute("DELETE FROM flight_events WHERE kind='start' AND id NOT IN "
                  "(SELECT id FROM flight_events WHERE kind='start' ORDER BY id DESC LIMIT 500)")


# ---------------------------------------------------------------------------- the background thread

class Flight(threading.Thread):
    """Drains the samples, watches for stalls, writes once a minute and sizes the database each hour."""

    def __init__(self, recorder, store, settings):
        super().__init__(name="tico-flight", daemon=True)
        self.recorder, self.store, self.settings = recorder, store, settings
        self.halt = threading.Event()
        self.db_every = 3600
        self.db_next = time.time() + 120          # not on the busy first minutes after a start

    def run(self):
        try:
            record_event(self.store, "start", start_event(self.settings))
        except Exception as exc:
            LOG.warning("Flight recorder start event failed: %s", type(exc).__name__)
        minute = int(time.time() // 60 * 60)
        while not self.halt.wait(TICK):
            try:
                self.recorder.drain()
                stall = self.recorder.stalled()
                if stall:
                    loop = next((t for t in stall["threads"]["busy"] if t["loop"]), None)
                    LOG.warning("Event loop stalled %.1fs; loop thread at: %s", stall["stalled_s"],
                                " < ".join(reversed(loop["stack"][-6:])) if loop else "unknown")
                    record_event(self.store, "stall", stall)
                now = time.time()
                if now >= minute + 60:
                    self.flush(minute)
                    minute = int(now // 60 * 60)
                if now >= self.db_next:
                    self.size_db(now)
            except Exception as exc:
                LOG.warning("Flight recorder pass failed: %s", type(exc).__name__)
        try:
            self.recorder.drain()
            self.flush(minute)
        except Exception:
            pass

    def flush(self, minute):
        taken = self.recorder.take(minute)
        with self.store.transaction() as c:
            write(c, taken)

    def size_db(self, now):
        started = time.monotonic()
        size, wal, free, detail = db_stats(self.store)
        took = time.monotonic() - started
        detail["seconds"] = round(took, 2)
        with self.store.transaction() as c:
            c.execute("INSERT OR REPLACE INTO flight_db VALUES(?,?,?,?,?)",
                      (int(now // 3600 * 3600), size, wal, free, json.dumps(detail, separators=(",", ":"))))
        # The size pass reads every page; on a large file it runs less often, so it stays a small share of a CPU.
        self.db_every = max(3600, int(took * 400))
        self.db_next = now + self.db_every

    def stop(self):
        self.halt.set()
        self.join(timeout=5)


# ---------------------------------------------------------------------------- reading it back

SECTIONS = ("requests", "slow", "process", "sql", "db", "events")


def _requests(c, since):
    merged = {}
    for r in c.execute("SELECT route,caller,n,errors,bytes,total_ms,max_ms,hist FROM flight_requests WHERE ts>=?",
                       (since,)):
        m = merged.setdefault(r[0], {"route": r[0], "n": 0, "errors": 0, "bytes": 0, "total_ms": 0.0, "max_ms": 0.0,
                                     "callers": {}, "_h": {}})
        m["n"] += r[2]
        m["errors"] += r[3]
        m["bytes"] += r[4]
        m["total_ms"] += r[5]
        m["max_ms"] = max(m["max_ms"], r[6] or 0)
        m["callers"][r[1]] = m["callers"].get(r[1], 0) + r[2]
        _merge(m["_h"], json.loads(r[7] or "{}"))
    every, rows = {}, []
    for m in merged.values():
        hist = m.pop("_h")
        _merge(every, hist)
        rows.append({**m, "total_ms": round(m["total_ms"], 1), "p50": quantile(hist, .5), "p95": quantile(hist, .95)})
    rows.sort(key=lambda r: -r["total_ms"])
    return {"n": sum(r["n"] for r in rows), "errors": sum(r["errors"] for r in rows),
            "p50": quantile(every, .5), "p95": quantile(every, .95), "routes": rows[:25]}


def _sql(c, since):
    merged = {}
    for r in c.execute("SELECT fingerprint,n,total_ms,max_ms,hist FROM flight_sql WHERE ts>=?", (since // 3600 * 3600,)):
        m = merged.setdefault(r[0], {"sql": r[0], "n": 0, "total_ms": 0.0, "max_ms": 0.0, "_h": {}})
        m["n"] += r[1]
        m["total_ms"] += r[2]
        m["max_ms"] = max(m["max_ms"], r[3] or 0)
        _merge(m["_h"], json.loads(r[4] or "{}"))
    rows = [{**{k: v for k, v in m.items() if k != "_h"}, "total_ms": round(m["total_ms"], 1),
             "p95": quantile(m["_h"], .95)} for m in merged.values()]
    rows.sort(key=lambda r: -r["total_ms"])
    return {"queries": rows[:25]}


def _process(c, since):
    rows = [dict(r) for r in c.execute("SELECT * FROM flight_process WHERE ts>=? ORDER BY ts", (since,))]
    def peak(key):
        values = [r[key] for r in rows if r[key] is not None]
        return max(values) if values else None
    cpu = [r["cpu"] for r in rows if r["cpu"] is not None]
    return {"cpu_avg": round(sum(cpu) / len(cpu), 1) if cpu else None, "cpu_max": peak("cpu"),
            "rss": rows[-1]["rss"] if rows else None, "threads": rows[-1]["threads"] if rows else None,
            "sockets": rows[-1]["sockets"] if rows else None, "lag_max": peak("lag_max"), "lag_p95": peak("lag_p95"),
            "wait_max": peak("wait_max"), "hold_max": peak("hold_max"),
            "locked": sum(r["locked"] or 0 for r in rows), "dropped": sum(r["dropped"] or 0 for r in rows),
            "minutes": rows[-180:]}


def _db(c, now):
    latest = c.execute("SELECT * FROM flight_db ORDER BY ts DESC LIMIT 1").fetchone()
    if not latest:
        return {}
    day = c.execute("SELECT * FROM flight_db WHERE ts<=? ORDER BY ts DESC LIMIT 1", (latest["ts"] - 86400 + 1800,)
                    ).fetchone()
    detail = json.loads(latest["detail_json"] or "{}")
    before = json.loads(day["detail_json"] or "{}") if day else {}
    return {"at": latest["ts"], "bytes": latest["bytes"], "wal_bytes": latest["wal_bytes"],
            "free_bytes": latest["free_bytes"], "growth_24h": latest["bytes"] - day["bytes"] if day else None,
            "objects": detail.get("objects"), "rows": detail.get("rows"), "oldest": detail.get("oldest"),
            "rows_24h": {k: v - (before.get("rows") or {}).get(k, v) for k, v in (detail.get("rows") or {}).items()}
            if day else None}


def view(c, minutes=60, sections=SECTIONS, now=None):
    now = int(now or time.time())
    since = now - minutes * 60
    out = {"since": since, "now": now, "minutes": minutes}
    if "requests" in sections:
        out["requests"] = _requests(c, since)
    if "slow" in sections:
        out["slow"] = [dict(r) for r in c.execute(
            "SELECT ts,route,caller,actor,ms,bytes,status FROM flight_slow WHERE ts>=? ORDER BY id DESC LIMIT 50",
            (since,))]
    if "process" in sections:
        out["process"] = _process(c, since)
    if "sql" in sections:
        out["sql"] = _sql(c, since)
    if "db" in sections:
        out["db"] = _db(c, now)
    if "events" in sections:
        out["events"] = {"start": last_start(c), "recent": [
            {"id": r[0], "at": r[1], "kind": r[2], **json.loads(r[3])} for r in c.execute(
                "SELECT id,ts,kind,detail_json FROM flight_events WHERE ts>=? ORDER BY id DESC LIMIT 20", (since,))]}
    return out


def install(app, store, auth):
    from fastapi import Request

    from .store import Problem

    @app.get("/api/v2/system/metrics")
    def system_metrics(request: Request, minutes: int = 60, section: str = "all"):
        """The flight recorder (backend/flight.py): owners and admins, or BotOps for one of them."""
        who = request.state.identity
        auth.domain(who)
        if not auth.bot_admin(who):
            raise Problem("forbidden", "Only an owner or an admin reads the server's metrics", 403)
        wanted = SECTIONS if section == "all" else tuple(s for s in section.split(",") if s in SECTIONS)
        if not wanted:
            raise Problem("section", "section is all or a list of: " + ", ".join(SECTIONS), 422)
        with store.read() as c:
            return view(c, max(1, min(int(minutes), SHORT_DAYS * 1440)), wanted)
