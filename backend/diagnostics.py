"""Support diagnostics: the redacted bundle a person may attach to a support request (PRIVACY.md, docs/support.md).

Two rules make it safe to send. It is built from an allowlist: every fact below is written out by name, so a field nobody
listed cannot appear, and no task, message, doc, meeting or ticket text is ever read. And every string in it passes the
`Redactor` on the way out: emails, keys and tokens, addresses, URL query strings, the company's domain and other
hostnames become placeholders, and each bot and person becomes a label (`bot-3`, `person-1`) that is the same all through
one bundle and means nothing outside it.

The preview is the bundle. `GET /api/v2/support/diagnostics` builds one and remembers it for a few minutes under its
SHA-256; the request that files the ticket names that digest and the server sends the remembered bytes, so what a person
looked at is what leaves, not a second build that could differ.
"""
import collections
import hashlib
import ipaddress
import json
import logging
import os
import platform
import re
import threading
import time

import httpx

from . import releases
from .store import H

FORMAT = 1
MAX_BYTES = 256 * 1024            # HQ refuses more (hq/support.py)
LOG_LINES = 200                   # server WARN and ERROR lines
RUNNER_LINES = 50
LINE = 300                        # characters of one log line
KEEP_S = 15 * 60                  # a preview may be sent for this long
KEEP_N = 20
UPDATER_WAIT = 3

# Hostnames a product runs on; every other hostname in a string becomes [host].
KNOWN_HOSTS = ("tico.team", "github.com", "githubusercontent.com", "ghcr.io", "docker.io", "openrouter.ai", "openai.com",
               "chatgpt.com", "anthropic.com", "claude.ai", "claude.com", "googleapis.com", "x.ai", "cursor.com",
               "google.com", "npmjs.org", "pypi.org")
# A dotted word is a hostname only when it ends in a real top-level domain: `service.py` and `hub.db` are files.
TLDS = ("com", "org", "net", "io", "dev", "ai", "team", "cloud", "xyz", "us", "uk", "de", "fr", "nl", "eu", "ca", "au", "jp",
        "ch", "se", "info", "biz", "tech", "online", "site", "example", "local", "internal", "lan", "test", "localdomain",
        "corp", "home")


class LogRing(logging.Handler):
    """The last WARNING and ERROR lines this process logged, for a support bundle. The message only: never an
    exception's text or traceback, which can carry what was being processed."""

    def __init__(self, size=400):
        super().__init__(logging.WARNING)
        self.lines = collections.deque(maxlen=size)

    def emit(self, record):
        try:
            line = "%s %s %s: %s" % (time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(record.created)), record.levelname,
                                     record.name, record.getMessage())
            if record.exc_info and record.exc_info[0]:
                line += " (" + record.exc_info[0].__name__ + ")"
            self.lines.append(line.replace("\n", " ")[:LINE * 2])
        except Exception:                                   # a logging handler never raises into the app
            pass


RING = LogRing()


def watch_logs():
    """Attach the ring to the root logger once per process."""
    root = logging.getLogger()
    if RING not in root.handlers:
        root.addHandler(RING)


# ---------------------------------------------------------------------- the redactor
SECRETS = [
    (re.compile(r"\bsk-[A-Za-z0-9_-]{8,}"), "[key]"),
    (re.compile(r"\b(?:ghp|gho|ghs|ghu|ghr)_[A-Za-z0-9]{8,}"), "[token]"),
    (re.compile(r"\bgithub_pat_[A-Za-z0-9_]{10,}"), "[token]"),
    (re.compile(r"\bxox[abprs]-[A-Za-z0-9-]{6,}"), "[token]"),
    (re.compile(r"\bxapp-[A-Za-z0-9-]{6,}"), "[token]"),
    (re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b"), "[key]"),
    (re.compile(r"\beyJ[A-Za-z0-9_-]{5,}\.[A-Za-z0-9_-]{5,}\.[A-Za-z0-9_-]*"), "[jwt]"),
    (re.compile(r"(?i)\b(bearer|basic)\s+[A-Za-z0-9._~+/=-]{6,}"), r"\1 [token]"),
    (re.compile(r"(?i)\b([A-Za-z0-9_.-]*(?:api[_-]?key|token|secret|password|passwd)[A-Za-z0-9_.-]*)"
                r"(\s*[=:]\s*)[\"']?[^\s\"',;]{4,}[\"']?"), r"\1\2[redacted]"),
]
LONG = re.compile(r"(?<![A-Za-z0-9+/_=-])[A-Za-z0-9+/_=-]{32,}")
CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f\u2028\u2029\u202a-\u202e\u2066-\u2069]")   # HQ refuses these (hq/support.py)
UUID = re.compile(r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}")
EMAIL = re.compile(r"[A-Za-z0-9._%+'-]{1,64}@[A-Za-z0-9](?:[A-Za-z0-9.-]{0,251}[A-Za-z0-9])?\.[A-Za-z]{2,24}")
QUERY = re.compile(r"(\b[a-z][a-z0-9+.-]*://[^\s?#\"'<>]*)\?[^\s\"'<>#]*(#[^\s\"'<>]*)?", re.I)
IPV4 = re.compile(r"(?<![\d.])(?:(?:25[0-5]|2[0-4]\d|1?\d?\d)\.){3}(?:25[0-5]|2[0-4]\d|1?\d?\d)(?![\d.]*\d)")
IPV6 = re.compile(r"(?<![A-Za-z0-9:])[0-9A-Fa-f:]*:[0-9A-Fa-f:.]*(?![A-Za-z0-9:])")
HOST = re.compile(r"(?<![A-Za-z0-9@._-])(?:[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?\.)+(?:%s)\b(?![A-Za-z0-9_-])"
                  % "|".join(TLDS), re.I)


def _looks_secret(token):
    """A long unbroken run is a secret when it mixes letters and digits; a UUID, a path or a plain word is not."""
    return bool(re.search(r"\d", token) and re.search(r"[A-Za-z]", token)) and not UUID.fullmatch(token)


def _ipv6(match):
    text = match.group(0)
    if text.count(":") < 2:
        return text
    try:
        ipaddress.IPv6Address(text.strip(":") if not text.startswith("::") and text.endswith(":") and not text.endswith("::") else text)
    except ValueError:
        return text
    return "[ip]"


WORD_MIN = 4        # a name or slug shorter than this is not a word: `coo` or `pm` would relabel ordinary text
ACTOR = re.compile(r"(?<![A-Za-z0-9])(bot|human):([A-Za-z0-9](?:[A-Za-z0-9_.-]*[A-Za-z0-9])?)")


class Redactor:
    """Every string in a bundle goes through `text()`. `people` and `bots` are the names to turn into labels; a label is
    made once per bundle, in sorted order, so the same person is the same `person-N` wherever they appear.

    A name or slug is relabeled as a word only when it has WORD_MIN letters or more. A short one (`coo`) is still
    relabeled where it cannot be an ordinary word: as an exact `bot:<slug>` or `human:<id>` actor reference, in `label()`,
    and inside an email address, which is always relabeled (or, for an address nobody here owns, `[email]`)."""

    def __init__(self, company_domains=(), bots=(), people=()):
        self.domains = sorted({d.lower().strip(".") for d in company_domains if d and "." in d}, key=len, reverse=True)
        self.labels = {}                      # lower-case spelling -> label
        self.exact = {}                       # case-sensitive short aliases (given names) -> label
        self.actors = {"bot": {}, "human": {}}    # the slug or person id, lower case -> label
        self._names = []                      # (compiled pattern, label), longest spelling first
        for number, (slug, names) in enumerate(sorted(bots), 1):
            self._alias("bot-%d" % number, [slug, *names])
            self.actors["bot"].setdefault(str(slug or "").strip().lower(), "bot-%d" % number)
        for number, (ident, names) in enumerate(sorted(people), 1):
            self._alias("person-%d" % number, [ident, *names], parts=True)
            self.actors["human"].setdefault(str(ident or "").strip().lower(), "person-%d" % number)
        self._names.sort(key=lambda item: len(item[0]), reverse=True)
        self._pattern = re.compile("|".join("(?<![A-Za-z0-9])%s(?![A-Za-z0-9])" % re.escape(spelling)
                                          for spelling, _ in self._names), re.I) if self._names else None
        self._exact = re.compile("|".join("(?<![A-Za-z0-9])%s(?![A-Za-z0-9])" % re.escape(s) for s in
                                          sorted(self.exact, key=len, reverse=True))) if self.exact else None

    def _alias(self, label, spellings, parts=False):
        for spelling in spellings:
            spelling = str(spelling or "").strip()
            if len(spelling) < 2:
                continue
            key = spelling.lower()
            if key not in self.labels:
                self.labels[key] = label
                if len(spelling) >= WORD_MIN or "@" in spelling:
                    self._names.append((spelling, label))
            if parts and " " in spelling:
                for word in spelling.split():
                    if len(word) >= WORD_MIN and word not in self.exact and word.lower() not in self.labels:
                        self.exact[word] = label

    def _actor(self, match):
        label = self.actors[match.group(1)].get(match.group(2).lower())
        return label or match.group(0)

    def label(self, value):
        """The label for a bot slug, name or person known to this bundle, else None."""
        return self.labels.get(str(value or "").strip().lower())

    def text(self, value):
        s = CONTROL.sub("", str(value if value is not None else ""))
        s = ACTOR.sub(self._actor, s)
        if self._pattern:
            s = self._pattern.sub(lambda m: self.labels[m.group(0).lower()], s)
        if self._exact:
            s = self._exact.sub(lambda m: self.exact[m.group(0)], s)
        s = EMAIL.sub("[email]", s)
        s = QUERY.sub(lambda m: m.group(1) + "?[query]" + (m.group(2) or ""), s)
        for pattern, replacement in SECRETS:
            s = pattern.sub(replacement, s)
        s = LONG.sub(lambda m: "[secret]" if _looks_secret(m.group(0)) else m.group(0), s)
        s = IPV4.sub("[ip]", s)
        s = IPV6.sub(_ipv6, s)
        for domain in self.domains:
            s = re.sub(r"(?<![A-Za-z0-9-])(?:[A-Za-z0-9-]+\.)*%s\b" % re.escape(domain), "[company-domain]", s, flags=re.I)
        return HOST.sub(lambda m: m.group(0) if known_host(m.group(0)) else "[host]", s)

    def clean(self, value):
        """A whole structure: strings redacted, numbers, booleans and nothing kept as they are, everything else dropped."""
        if isinstance(value, str):
            return self.text(value)
        if isinstance(value, bool) or value is None or isinstance(value, (int, float)):
            return value
        if isinstance(value, dict):
            return {str(k): self.clean(v) for k, v in value.items()}
        if isinstance(value, (list, tuple)):
            return [self.clean(v) for v in value]
        return None


def known_host(host):
    host = host.lower().strip(".")
    return host.startswith("tico.") or any(host == known or host.endswith("." + known) for known in KNOWN_HOSTS)


# ---------------------------------------------------------------------- the allowlist
# Every path a bundle may hold. A key that is not here is dropped by `allowed()`, whatever a builder put there; the
# tests read this table to prove no content field can appear.
ALLOWED = {
    "format": None, "created": None,
    "versions": {"tico": None, "server": None, "runners": None, "updater": None},
    "system": {"os": None, "arch": None, "docker": None, "compose": None, "in_docker": None},
    "containers": [{"name": None, "state": None, "health": None, "restarts": None}],
    "update": {"state": None, "from": None, "to": None, "message": None, "restored": None},
    "health": [{"name": None, "status": None}],
    "runners": [{"label": None, "online": None, "platform": None, "kind": None, "release": None, "update": None,
                 "update_error": None, "runtimes": [{"name": None, "installed": None, "version": None, "ready": None,
                                                     "state": None, "detail": None}],
                 "bots": None, "bots_ready": None, "problems": None, "log": None}],
    "database": {"migration": None, "cloud_migration": None},
    "features": {},
    "counts": {"bots": None, "people": None, "routines": None},
    "logs": {"server": None, "updater": None},
}
FEATURES = ("demo", "updater", "update_check", "usage_count", "backups", "github_app", "slack", "sign_in_proxy",
            "blob_storage", "scheduler", "observability", "assistant", "librarian")


def allowed(value, shape=ALLOWED):
    """`value` cut down to the keys `shape` names."""
    if isinstance(shape, list):
        return [allowed(item, shape[0]) for item in value] if isinstance(value, list) else []
    if isinstance(shape, dict):
        if not isinstance(value, dict):
            return {}
        if shape == {} and value is not None:            # a map of booleans
            return {str(k): bool(v) for k, v in value.items() if k in FEATURES}
        return {k: allowed(v, shape[k]) for k, v in value.items() if k in shape}
    return value


def fit(bundle):
    """The bundle under MAX_BYTES: the long lists shrink first, the logs before anything else."""
    def size():
        return len(json.dumps(bundle, sort_keys=True, separators=(",", ":")).encode())
    for step in range(12):
        if size() <= MAX_BYTES:
            return bundle
        logs = bundle.get("logs") or {}
        for key in ("server", "updater"):
            logs[key] = (logs.get(key) or [])[len(logs.get(key) or []) // 2:]
        for row in bundle.get("runners") or []:
            row["log"] = (row.get("log") or [])[len(row.get("log") or []) // 2:]
            row["problems"] = (row.get("problems") or [])[:10]
        bundle["containers"] = (bundle.get("containers") or [])[:50]
    bundle["logs"] = {"server": [], "updater": []}
    for row in bundle.get("runners") or []:
        row["log"], row["problems"] = [], []
    return bundle


def canonical(bundle):
    return json.dumps(bundle, sort_keys=True, indent=2, ensure_ascii=False)


def digest(bundle):
    return hashlib.sha256(canonical(bundle).encode()).hexdigest()


# ---------------------------------------------------------------------- the facts
def _domains(settings, roster):
    found = set()
    for value in (settings.owner_email, settings.local_owner_email):
        if "@" in str(value or ""):
            found.add(str(value).rsplit("@", 1)[1])
    host = re.sub(r"^[a-z]+://", "", str(settings.public_url or "")).split("/")[0].split(":")[0]
    if host and not re.fullmatch(r"[\d.]+|localhost", host):
        found.add(host)
    found.update(str(d) for d in (settings.oidc_allowed_domains or ()))
    for person in roster.get("people") or []:
        email = str((person or {}).get("email") or "")
        if "@" in email:
            found.add(email.rsplit("@", 1)[1])
    # Webmail is not the company's own domain; only its addresses are people, and those are labelled already.
    return {d for d in found if d.lower() not in ("gmail.com", "outlook.com", "icloud.com", "yahoo.com", "hotmail.com")}


def _updater_report(settings):
    url, token = releases._updater()
    if not url:
        return {}
    try:
        with httpx.Client(timeout=UPDATER_WAIT, transport=releases.TRANSPORT, follow_redirects=False) as http:
            answer = http.get(url + "/diagnostics", headers={"Authorization": "Bearer " + token})
        return answer.json() if answer.status_code == 200 and isinstance(answer.json(), dict) else {}
    except (httpx.HTTPError, ValueError):
        return {}


def _update_result():
    try:
        return releases.status()
    except Exception:
        return {}


def _version(value):
    value = str(value or "")
    return value if re.fullmatch(r"[0-9A-Za-z._+-]{1,40}", value) else ""


def _lines(lines, keep):
    return [str(x)[:LINE] for x in list(lines or [])[-keep:]]


def _runner_rows(c, fleet, online_ids):
    from .store import readiness_document
    from . import runner_versions
    rows = []
    for index, row in enumerate(c.execute("SELECT id,label,last_seen,version,platform,readiness_json FROM runners "
                                          "WHERE revoked_at IS NULL ORDER BY id"), 1):
        doc = readiness_document(row["readiness_json"])
        bots = doc.get("bots") or {}
        problems = []
        for slug, b in bots.items():
            for text in (b or {}).get("problems") or []:
                if str(text).startswith(str(slug) + ": "):        # the runner leads a bot's problem with its slug: an exact reference
                    text = "bot:" + str(text)
                if text not in problems:
                    problems.append(text)
        update = runner_versions.view(fleet.get(row["id"]))
        runtimes = []
        for name, v in sorted((doc.get("runtimes") or {}).items()):
            if not (v or {}).get("installed"):
                continue
            runtimes.append({"name": name, "installed": True, "version": _version(v.get("version")) or str(v.get("version") or "")[:60],
                             "ready": v.get("authenticated") == "ready", "state": str(v.get("authenticated") or ""),
                             "detail": str(v.get("detail") or "")[:200]})
        rows.append({"label": "runner-%d" % index, "online": row["id"] in online_ids, "platform": str(row["platform"] or ""),
                     "kind": update["kind"], "release": update["release"] or _version(row["version"]),
                     "update": update["state"], "update_error": update["error"][:200], "runtimes": runtimes,
                     "bots": len(bots), "bots_ready": sum(1 for b in bots.values() if (b or {}).get("ready")),
                     "problems": problems[:20], "log": _lines(doc.get("recent_errors"), RUNNER_LINES)})
    return rows


def build(store, settings, auth, who, census, github=None, config=None):
    """The redacted bundle for this install, as a dictionary (`fit`-ted, allowlisted, every string redacted)."""
    from . import health, onboarding, replication, runner_versions
    from .getting_started import _online_runners
    from .views import roster
    updater = _updater_report(settings)
    result = _update_result()
    with store.read() as c:
        people = roster(c)
        bot_rows = [(b["slug"], [b.get("display_name")]) for b in H.bots(c)]
        humans = [((p or {}).get("id") or "", [(p or {}).get("name"), (p or {}).get("email")]) for p in people.get("people") or []]
        redactor = Redactor(_domains(settings, people), bot_rows, humans)
        config = config or onboarding.config_view(c, settings, who)
        checks = health.view(c, who, settings, auth, github, config)["checks"]
        online_ids = {r["id"] for r in _online_runners(c)}
        runners = _runner_rows(c, runner_versions.load(c), online_ids)
        bots_total = sum(1 for b in H.bots(c) if b.get("state") != "archived")
        routines = c.execute("SELECT count(*) FROM schedules").fetchone()[0]
        migration = c.execute("PRAGMA user_version").fetchone()[0]
        cloud = c.execute("SELECT coalesce(max(version),0) FROM cloud_migrations").fetchone()[0]
        backup = replication.status()
        slack = bool(c.execute("SELECT 1 FROM sqlite_master WHERE name='slack_credentials'").fetchone()
                     and c.execute("SELECT 1 FROM slack_credentials WHERE id='app'").fetchone())
        assistant = H.bot(c, settings.assistant_bot)
        librarian = H.bot(c, "librarian")
        github_on = bool(github and github.row(c) and github.row(c)["installation_id"])
    features = {"demo": bool(settings.demo), "updater": bool(releases._updater()[0]),
                "update_check": releases.Checker.enabled(), "usage_count": census.enabled(),
                "backups": backup.get("mode") not in (None, "off"), "github_app": github_on, "slack": slack,
                "sign_in_proxy": bool(settings.proxy_kind), "blob_storage": bool(settings.blob_bucket),
                "scheduler": bool(settings.scheduler_enabled),
                "observability": bool(settings.sentry_dsn or settings.posthog_key),
                "assistant": bool(assistant and assistant.get("state") == "active"),
                "librarian": bool(librarian and librarian.get("state") == "active")}
    bundle = {
        "format": FORMAT, "created": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "versions": {"tico": _version(releases.version()), "server": _version(releases.version()),
                     "runners": sorted({r["release"] for r in runners if r["release"]}),
                     "updater": _version(updater.get("version"))},
        "system": {"os": platform.system(), "arch": platform.machine(), "docker": _version(updater.get("docker")),
                   "compose": _version(updater.get("compose")), "in_docker": onboarding.running_in_docker()},
        "containers": [{"name": str(x.get("name") or ""), "state": str(x.get("state") or ""),
                        "health": str(x.get("health") or ""), "restarts": int(x.get("restarts") or 0)}
                       for x in (updater.get("containers") or [])[:50] if isinstance(x, dict)],
        "update": {"state": str(result.get("state") or ""), "from": _version(result.get("from")),
                   "to": _version(result.get("to")), "message": str(result.get("message") or "")[:300],
                   "restored": bool(result.get("restored"))},
        "health": [{"name": x["label"], "status": x["status"]} for x in checks],
        "runners": runners,
        "database": {"migration": migration, "cloud_migration": cloud},
        "features": features,
        "counts": {"bots": bots_total, "people": len(people.get("people") or []), "routines": routines},
        "logs": {"server": _lines(RING.lines, LOG_LINES), "updater": _lines(updater.get("errors"), RUNNER_LINES)},
    }
    return fit(redactor.clean(allowed(bundle)))


class Previews:
    """The bundles people have looked at, by digest, for a few minutes: what is sent is what was shown."""

    def __init__(self, clock=time.monotonic):
        self.clock, self.lock, self.items = clock, threading.Lock(), collections.OrderedDict()

    def keep(self, actor, bundle):
        key = digest(bundle)
        with self.lock:
            self.items[(actor, key)] = (self.clock(), bundle)
            while len(self.items) > KEEP_N:
                self.items.popitem(last=False)
        return key

    def take(self, actor, key):
        with self.lock:
            found = self.items.get((actor, str(key or "")))
        if found and self.clock() - found[0] <= KEEP_S:
            return found[1]
        return None
