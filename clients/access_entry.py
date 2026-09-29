"""One `access:` entry of an employee.yaml, as a schema (docs/creating-bots.md, "Access and credentials").

Two callers share it. The runner (`runner/declared_access.py`) reads a bot's entries and reports the
fields listed here. The server (`backend/bot_tools.py`) checks an entry a person registers for a bot
before it asks BotOps to write it into the bot's repository, so a request can only name what the
runner would report back. An entry holds names and verbs, never a credential: `env` is the variable's
name, and text that looks like a key, a token or a password is refused (`secret_in`).

Pure stdlib apart from PyYAML, like the rest of clients/.
"""

import math
import re

import yaml

# The fields, beyond service, identity, can, env and note, that describe what a tool is scoped to.
SCOPE_KEYS = ("database", "channels", "channel", "project", "projects", "mailbox", "mailboxes", "sites", "site",
              "repo", "repos", "repositories", "org", "organization", "workspace", "account", "region", "domain",
              "domains", "calendars", "folders", "drive", "drives", "bucket", "buckets", "table", "tables",
              "dataset", "datasets", "collections", "read_only", "org_read", "max_rows", "timeout_seconds",
              "read_preference")
MAX_CAN = 20
MAX_SCOPE = 20
SERVICE_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,59}$")
VERB_RE = re.compile(r"^[a-z][a-z_-]{0,39}$")
ENV_RE = re.compile(r"^[A-Z_][A-Z0-9_]{0,99}$")
# The names a bot's turn owns; a credential may not arrive under one (runner/service.py `environment`).
RESERVED_ENV = {"HOME", "PATH", "SHELL", "PYTHONPATH", "PYTHONHOME", "NODE_OPTIONS", "LD_PRELOAD",
                "DYLD_INSERT_LIBRARIES", "CODEX_HOME", "HUB_DB", "HUB_HUMAN_OVERRIDE"}
RESERVED_PREFIXES = ("TICO_", "HUB_", "DYLD_", "LD_")

# Key shapes seen in the wild, and a URL with a password in it.
SECRET_SHAPES = re.compile(
    r"sk-[A-Za-z0-9_-]{8,}|[sr]k_(?:live|test)_\w+|gh[pousr]_[A-Za-z0-9]{16,}|github_pat_\w+|glpat-[\w-]{10,}|"
    r"xox[abposr]-[\w-]+|xapp-[\w-]+|ph[xcs]_[A-Za-z0-9]{10,}|AKIA[0-9A-Z]{12,}|ASIA[0-9A-Z]{12,}|AIza[\w-]{20,}|"
    r"ya29\.[\w.-]+|eyJ[\w-]{8,}\.[\w-]{8,}\.[\w-]*|-----BEGIN [A-Z ]*KEY|npm_[A-Za-z0-9]{20,}|SG\.[\w-]{16,}|"
    r"\bBearer\s+\S{12,}|\b[a-z][a-z0-9+.-]*://[^/\s:@]+:[^/\s@]+@|\bop://\S+")
TOKEN_PARTS = re.compile(r"[\s,;()\"'<>]+")
TOKEN_CHARS = re.compile(r"^[A-Za-z0-9_+/=-]+$")


class EntryError(ValueError):
    """The entry cannot be registered; the message says what to change."""

    def __init__(self, message, code="entry"):
        super().__init__(message)
        self.code = code


def entropy(token):
    counts = {ch: token.count(ch) for ch in set(token)}
    return -sum(n / len(token) * math.log2(n / len(token)) for n in counts.values())


def secret_in(text):
    """A reason when `text` looks like a credential value, else "". A guard, not a proof: the docs
    say where credentials go, and this stops the common mistake of pasting one into a field."""
    text = str(text or "")
    found = SECRET_SHAPES.search(text)
    if found:
        return "it contains what looks like a key, token or password"
    for token in TOKEN_PARTS.split(text):
        if (len(token) >= 24 and TOKEN_CHARS.match(token) and re.search(r"[a-z]", token) and re.search(r"[A-Z]", token)
                and re.search(r"\d", token) and entropy(token) >= 3.9):
            return "it contains a long random-looking string"
    return ""


def one_line(value, limit):
    return " ".join(str(value).split())[:limit]


def scalar(value, limit):
    if isinstance(value, bool):
        return "yes" if value else "no"
    return one_line(value, limit) if isinstance(value, (str, int, float)) else ""


def scope_of(entry):
    """The scope fields of an entry as {key: text | [text]}, capped; the runner's report and the form agree."""
    result = {}
    for key in SCOPE_KEYS:
        value = entry.get(key)
        if isinstance(value, (list, tuple)):
            items = [scalar(item, 100) for item in value[:20]]
            items = [item for item in items if item]
            if items:
                result[key] = items
        elif value not in (None, "") and scalar(value, 200):
            result[key] = scalar(value, 200)
        if len(result) >= MAX_SCOPE:
            break
    return result


def clean(entry):
    """A registered entry, validated and normalised, in employee.yaml's key order. Raises EntryError."""
    if not isinstance(entry, dict):
        raise EntryError("An access entry is an object with a service, an identity and what it can do")
    service = str(entry.get("service") or "").strip().lower()
    if not SERVICE_RE.match(service):
        raise EntryError("service is a short name such as posthog or google-calendar (lowercase, digits, - and _)")
    can = entry.get("can")
    can = [can] if isinstance(can, str) else can
    if not isinstance(can, list) or not can:
        raise EntryError("can lists what the bot may do, at least one verb: read, draft, post, act, use, send, write")
    verbs = []
    for verb in can[:MAX_CAN + 1]:
        verb = str(verb).strip().lower()
        if not VERB_RE.match(verb):
            raise EntryError(f"{verb!r} is not a verb; use words such as read, draft, post, act, use, write")
        if verb not in verbs:
            verbs.append(verb)
    if len(verbs) > MAX_CAN:
        raise EntryError(f"can holds at most {MAX_CAN} verbs")
    scope = entry.get("scope") or {}
    if not isinstance(scope, dict):
        raise EntryError("scope is an object such as {\"database\": \"warehouse\"}")
    unknown = sorted(str(key) for key in scope if key not in SCOPE_KEYS)
    if unknown:
        raise EntryError(f"scope does not take {', '.join(unknown)}; it takes {', '.join(SCOPE_KEYS)}")
    kept = scope_of(scope)
    given = {key for key, value in scope.items() if value not in (None, "", [])}
    if given - set(kept):
        raise EntryError("scope values are text, numbers, yes/no, or lists of them")
    env = str(entry.get("env") or "").strip()
    if env and (not ENV_RE.match(env) or env in RESERVED_ENV or env.startswith(RESERVED_PREFIXES)):
        raise EntryError("env is the name of the environment variable that holds the credential, such as "
                         "POSTHOG_KEY (capitals, digits, underscores), never the credential itself", "secret"
                         if len(env) > 30 or secret_in(env) else "entry")
    identity, note = one_line(entry.get("identity") or "", 300), one_line(entry.get("note") or "", 500)
    for field, text in (("service", service), ("identity", identity), ("note", note), *(
            ("scope." + key, " ".join(value) if isinstance(value, list) else value) for key, value in kept.items())):
        why = secret_in(text)
        if why:
            raise EntryError(f"{field} is not accepted: {why}. Tico never takes a credential value; the operator "
                             "puts it on the bot's computer and this entry names only its variable", "secret")
    result = {"service": service}
    if identity:
        result["identity"] = identity
    result["can"] = verbs
    result.update(kept)
    if env:
        result["env"] = env
    if note:
        result["note"] = note
    return result


def to_yaml(entry):
    """The entry as a list item ready to paste under `access:` in employee.yaml."""
    text = yaml.safe_dump([entry], sort_keys=False, default_flow_style=None, allow_unicode=True, width=200)
    return text.rstrip("\n")
