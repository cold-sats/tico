"""What a bot's `access:` block says, cut down to what its page may show (docs/creating-bots.md,
"What people see about a bot's tools").

The runner reads employee.yaml from the bot's checkout and reports each entry on the heartbeat,
next to the bot's readiness. Only a fixed list of non-secret fields leaves the computer: the
service, the identity it acts as, the verbs, a few scope fields (database, channels, ...), the note,
and the *name* of the environment variable. Never a value. Whether the credential is on this
computer is a fact the server cannot see, so each entry carries it as `credential`.
"""

import re

SCOPE_KEYS = ("database", "channels", "channel", "project", "projects", "mailbox", "mailboxes", "sites", "site",
              "repo", "repos", "repositories", "org", "organization", "workspace", "account", "region", "domain",
              "domains", "calendars", "folders", "drive", "drives", "bucket", "buckets", "table", "tables",
              "dataset", "datasets", "collections", "read_only", "org_read", "max_rows", "timeout_seconds",
              "read_preference")
MAX_ENTRIES = 30        # backend/models.py ToolAccess and BotReadiness.tools hold the same limits
MAX_CAN = 20
MAX_SCOPE = 20
DATABASE_SERVICES = ("postgres", "postgresql", "mysql", "mariadb", "sqlite", "mongodb")
# A URL with a password in it is a secret wherever it was typed.
URL_PASSWORD = re.compile(r"(\b[a-z][a-z0-9+.-]*://)[^/\s:@]+:[^/\s@]+@", re.I)


def text(value, limit):
    value = URL_PASSWORD.sub(r"\1", " ".join(str(value).split())) if value is not None else ""
    return value[:limit]


def scalar(value, limit):
    if isinstance(value, bool):
        return "yes" if value else "no"
    return text(value, limit) if isinstance(value, (str, int, float)) else ""


def scope_of(entry):
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


def env_name(entry):
    """The variable the credential arrives in: the declared one, else the database default."""
    name = str(entry.get("env") or "").strip()
    if name:
        return name
    database = str(entry.get("database") or "").strip()
    if database and str(entry.get("service") or "").lower() in DATABASE_SERVICES:
        return "DB_" + database.upper().replace("-", "_") + "_URL"
    return ""


def credential_state(entry, name, environment):
    """present | missing | hub-vault | not-declared. Presence only: a 1Password reference counts as set
    (the turn resolves it), and the value is never read into the report."""
    if entry.get("vault") == "hub":
        return "hub-vault"
    if not name:
        return "not-declared"
    return "present" if str(environment.get(name) or "").strip() else "missing"


def declared_tools(access, environment):
    """The report rows for one bot's `access:` list; [] when it is absent or malformed."""
    if not isinstance(access, list):
        return []
    rows = []
    for entry in access:
        if not isinstance(entry, dict) or not str(entry.get("service") or "").strip():
            continue
        name = env_name(entry)
        can = entry.get("can")
        can = [can] if isinstance(can, str) else can if isinstance(can, list) else []
        row = {"service": text(entry["service"], 100), "identity": text(entry.get("identity"), 300),
               "can": [text(verb, 40) for verb in can[:MAX_CAN] if text(verb, 40)],
               "scope": scope_of(entry), "env": text(name, 100), "note": text(entry.get("note"), 500),
               "credential": credential_state(entry, name, environment)}
        if "{{" in str(entry.get("identity") or ""):
            row["problem"] = "The identity is still the template placeholder"
        rows.append(row)
        if len(rows) >= MAX_ENTRIES:
            break
    return rows
