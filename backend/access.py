"""Who owns this environment, who may sign in, and who is on the roster: stored, not configured.

TICO_OWNER_EMAIL and registry/hub-access.yaml only seed the first boot. From then on the owner
and the access list are two revisioned records (like the provider choice in providers.py), so
the owner changes them in the app without editing a file or restarting:

  owner   {email}                                    who holds owner rights
  access  {allowed, allowed_domains, bot_admins}     who may join, and who administers bots

The roster stays the gate for sign-in: a person on it (and not marked as left) is in. An
address on `allowed`, or at an allowed domain, joins the roster on its first verified sign-in.
"""

import json
import logging
import re

import yaml

from . import hubdb as H
from . import people as P
from .store import Problem

OWNER = "owner"
ACCESS = "access"


def emails(values):
    """Lowercase, unique, in the order given; empties dropped."""
    seen = []
    for value in values or []:
        item = str(value or "").strip().lower()
        if item and item not in seen:
            seen.append(item)
    return seen


def domains(values):
    return [d.lstrip("@") for d in emails(values)]


def _load_json(c, key):
    row = c.execute("SELECT value_json FROM registry_metadata WHERE key=?", (key,)).fetchone()
    try:
        value = json.loads(row[0]) if row else None
    except ValueError:
        value = None
    return value if isinstance(value, dict) else None


def _file_access(settings):
    try:
        document = yaml.safe_load((settings.registry_dir / "hub-access.yaml").read_text())
    except (OSError, yaml.YAMLError):
        document = None
    return document if isinstance(document, dict) else {}


def _access_seed(settings):
    document = _file_access(settings)
    return {"allowed": emails(document.get("allowed")),
            "allowed_domains": domains(document.get("allowed_domains")),
            "bot_admins": emails(document.get("bot_admins"))}


def load_owner(c, settings):
    stored = _load_json(c, OWNER)
    if stored is None:
        return {"email": str(settings.owner_email or "").strip().lower(), "revision": 0,
                "updated": "", "updated_by": "", "source": "environment"}
    return {"email": str(stored.get("email") or "").strip().lower(),
            "revision": int(stored.get("revision") or 0), "updated": str(stored.get("updated") or ""),
            "updated_by": str(stored.get("updated_by") or ""), "source": str(stored.get("source") or "")}


def load_access(c, settings):
    stored = _load_json(c, ACCESS)
    source = "owner" if stored else "environment"
    stored = stored if stored is not None else _access_seed(settings)
    return {"allowed": emails(stored.get("allowed")), "allowed_domains": domains(stored.get("allowed_domains")),
            "bot_admins": emails(stored.get("bot_admins")), "revision": int(stored.get("revision") or 0),
            "updated": str(stored.get("updated") or ""), "updated_by": str(stored.get("updated_by") or ""),
            "source": str(stored.get("source") or source)}


def seed(c, settings, now):
    """Persist the environment's owner and hub-access file once; later changes are revisioned
    and the environment is never consulted again. Called at database initialization."""
    if not _load_json(c, OWNER) and settings.owner_email:
        c.execute("INSERT INTO registry_metadata VALUES(?,?)",
                  (OWNER, json.dumps({"email": settings.owner_email.strip().lower(), "revision": 1,
                                      "updated": now, "updated_by": "environment", "source": "environment"},
                                     sort_keys=True)))
    if not _load_json(c, ACCESS):
        c.execute("INSERT INTO registry_metadata VALUES(?,?)",
                  (ACCESS, json.dumps({**_access_seed(settings), "revision": 1, "updated": now,
                                       "updated_by": "environment", "source": "environment"}, sort_keys=True)))


# ----------------------------------------------------------------------------- per-bot access
# Who may see, read and write to a bot is stored on the bot (backend/bot_access.py). The old
# `private_owners` and `routing_permissions` lists in hub-access.yaml are no longer read for
# enforcement: the first start after they stopped counting resets every bot to Open and leaves the
# owner one note on Health saying so.
BOT_ACCESS = "bot_access"
BOT_ACCESS_NOTICE = "bot_access_notice"
RETIRED_LISTS = ("private_owners", "routing_permissions", "dispatch_permissions")
RETIRED_NOTICE = ("hub-access.yaml private/routing lists are no longer used; bots are now Open; "
                  "set access in Settings > Bots")


def retire_bot_lists(c, settings, now):
    """Once per database: note that the file's private/routing lists are retired. Returns the
    names of the lists that were present (empty when there was nothing to warn about)."""
    if _load_json(c, BOT_ACCESS) is not None:
        return []
    document = _file_access(settings)
    present = [name for name in RETIRED_LISTS if document.get(name)]
    _store(c, BOT_ACCESS, {"migrated": now, "retired": present})
    if present:
        logging.getLogger("tico.access").warning("%s (found: %s)", RETIRED_NOTICE, ", ".join(present))
        _store(c, BOT_ACCESS_NOTICE, {"message": RETIRED_NOTICE, "lists": present, "created": now})
    return present


def bot_access_notice(c):
    """The note the owner still has to read on Health, or None."""
    return _load_json(c, BOT_ACCESS_NOTICE)


def clear_bot_access_notice(c):
    c.execute("DELETE FROM registry_metadata WHERE key=?", (BOT_ACCESS_NOTICE,))


def _store(c, key, record):
    c.execute("INSERT INTO registry_metadata VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value_json=excluded.value_json",
              (key, json.dumps(record, sort_keys=True)))


def admitted(access, email):
    """Whether an address is on the allowed list or at an allowed domain."""
    email = str(email or "").strip().lower()
    if not email or "@" not in email:
        return False
    return email in access["allowed"] or email.rsplit("@", 1)[1] in access["allowed_domains"]


def acl(c, settings):
    """The `hub-access.yaml` shape with the stored owner and lists, for the Slack gateway."""
    access = load_access(c, settings)
    return {**_file_access(settings), "owner": load_owner(c, settings)["email"],
            "allowed": access["allowed"], "allowed_domains": access["allowed_domains"],
            "bot_admins": access["bot_admins"]}


# ----------------------------------------------------------------------------- roster
def _save_roster(c, roster):
    c.execute("INSERT INTO registry_metadata VALUES('people',?) ON CONFLICT(key) DO UPDATE SET "
              "value_json=excluded.value_json", (json.dumps(roster, sort_keys=True),))


def _sync_human(c, row):
    teams = sorted({t for t in [row.get("team"), *(row.get("primary_for") or [])] if t})
    values = {"id": row["id"], "name": row["name"], "email": row["email"],
              "slack_id": row.get("slack_id") or None, "teams_json": json.dumps(teams)}
    if H.human(c, row["id"]) is None:
        c.execute("INSERT INTO humans (id, name, email, slack_id, teams_json) "
                  "VALUES (:id, :name, :email, :slack_id, :teams_json)", values)
    else:
        c.execute("UPDATE humans SET name=:name, email=:email, teams_json=:teams_json WHERE id=:id", values)


def _email_taken(c, email, except_id=""):
    row = c.execute("SELECT id FROM humans WHERE lower(email)=? AND id<>?", (email, except_id)).fetchone()
    return row is not None


_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def _valid_email(value):
    email = str(value or "").strip().lower()
    if not _EMAIL.match(email):
        raise Problem("email", "Enter a full email address, like name@company.com", 422)
    return email


def _new_id(c, email):
    base = re.sub(r"[^a-z0-9]+", "-", email.split("@")[0]).strip("-") or "person"
    pid, n = base, 1
    while H.human(c, pid):
        n += 1
        pid = f"{base}-{n}"
    return pid


def add_person(c, actor, roster, *, name, email, title="", team="", event="person.added"):
    """A new roster person and the people the org chart shows; returns (roster, row)."""
    email = _valid_email(email)
    if _email_taken(c, email):
        raise Problem("conflict", "Someone with that email is already on the roster", 409)
    row = P._person({"id": _new_id(c, email), "name": name or "", "email": email,
                     "title": title, "team": team})
    _save_roster(c, {**roster, "people": [*roster["people"], row]})
    _sync_human(c, row)
    H.event(c, actor, event, row["id"], {"email": email})
    return {**roster, "people": [*roster["people"], row]}, row


def leave(c, people, row):
    """Take one person off the chart: end their tokens and sessions and move their reports up.
    Mutates `people` (the caller's list) and returns the person's new row."""
    row = {**row, "hidden": True}
    # Their API tokens outlive a browser session by up to a year.
    c.execute("UPDATE human_tokens SET revoked_at=? WHERE human=? AND revoked_at IS NULL", (H.now(), row["id"]))
    c.execute("DELETE FROM oidc_sessions WHERE human=?", (row["id"],))
    # Their reports move up to their manager rather than falling off the chart.
    for j, other in enumerate(people):
        if other.get("reports_to") == row["id"]:
            people[j] = {**other, "reports_to": row.get("reports_to") or ""}
    return row


def join_on_sign_in(c, email):
    """Someone the allow list admits signs in for the first time: they join as a normal person."""
    from .views import roster as load_roster
    _, row = add_person(c, "keeper", load_roster(c), name="", email=email, event="person.joined")
    return row["id"]


def edit_person(c, actor, roster, pid, body, access, owner_email):
    """Owner edits of a roster person. Returns (roster, access_changes)."""
    person = P.person(pid, roster)
    if not person:
        raise Problem("not_found", "Person not found", 404)
    row, changed = dict(person), {}
    if body.name is not None and body.name.strip() != row["name"]:
        row["name"], changed["name"] = body.name.strip() or row["name"], True
    if body.title is not None:
        row["title"], changed["title"] = body.title.strip(), True
    if body.team is not None:
        row["team"], changed["team"] = body.team.strip(), True
    old_email = row["email"]
    if body.email is not None and body.email.strip().lower() != old_email:
        if old_email and old_email == owner_email:
            raise Problem("owner", "Transfer ownership before changing the owner's email", 409)
        row["email"] = _valid_email(body.email)
        if _email_taken(c, row["email"], pid):
            raise Problem("conflict", "Someone with that email is already on the roster", 409)
        changed["email"] = True
    admins = list(access["bot_admins"])
    if row["email"] != old_email and old_email in admins:
        admins = [row["email"] if e == old_email else e for e in admins]
    if body.left is False and row.get("hidden"):
        row["hidden"], changed["restored"] = False, True
    if body.bot_admin is not None:
        if row["email"] == owner_email:
            raise Problem("owner", "The owner already administers every bot", 409)
        if body.bot_admin and not row["email"]:
            raise Problem("email", "A bot administrator needs an email address", 422)
        admins = [e for e in admins if e != row["email"]]
        if body.bot_admin:
            admins.append(row["email"])
        changed["bot_admin"] = bool(body.bot_admin)
    row = P._person(row)
    _save_roster(c, {**roster, "people": [row if p["id"] == pid else p for p in roster["people"]]})
    _sync_human(c, row)
    return row, admins, changed


def save_access(c, actor, body, now, *, bot_admins=None, settings=None):
    """Replace the allow list (and optionally the bot administrators) at the revision read."""
    before = load_access(c, settings)
    if before["revision"] != int(body.get("expected_revision") or 0):
        raise Problem("conflict", "The access list changed since you opened it; reload and try again", 409)
    after = {"allowed": emails(body.get("allowed", before["allowed"])),
             "allowed_domains": domains(body.get("allowed_domains", before["allowed_domains"])),
             "bot_admins": before["bot_admins"] if bot_admins is None else emails(bot_admins),
             "revision": before["revision"] + 1, "updated": now, "updated_by": actor, "source": "owner"}
    for domain in after["allowed_domains"]:
        if not re.fullmatch(r"[a-z0-9]([a-z0-9.-]*[a-z0-9])?\.[a-z]{2,}", domain):
            raise Problem("domain", f"{domain!r} is not a domain like company.com", 422)
    for email in after["allowed"]:
        _valid_email(email)
    _store(c, ACCESS, after)
    return before, after


def transfer(c, actor, roster, owner, target_id, *, expected_revision, previous_bot_admin, now, settings):
    """Make another active person the owner, in the caller's transaction. Returns the new owner
    record; the previous owner becomes a normal person, optionally a bot administrator."""
    if owner["revision"] != expected_revision:
        raise Problem("conflict", "Ownership changed since you opened this page; reload and try again", 409)
    target = P.person(target_id, roster)
    if not target or target.get("hidden"):
        raise Problem("not_found", "Choose someone who is active on the roster", 404)
    if not target["email"]:
        raise Problem("email", "The new owner needs an email address to sign in with", 422)
    if target["email"] == owner["email"]:
        raise Problem("conflict", "That person is already the owner", 409)
    previous = P.person_by_email(owner["email"], roster)
    after = {"email": target["email"], "revision": owner["revision"] + 1, "updated": now,
             "updated_by": actor, "source": "transfer", "previous": owner["email"]}
    _store(c, OWNER, after)
    access = load_access(c, settings)
    if previous_bot_admin and owner["email"]:
        _store(c, ACCESS, {**access, "bot_admins": emails([*access["bot_admins"], owner["email"]]),
                           "revision": access["revision"] + 1, "updated": now, "updated_by": actor,
                           "source": "owner"})
    H.event(c, actor, "owner.transferred", target["id"],
            {"from": owner["email"], "from_person": (previous or {}).get("id", ""),
             "to": target["email"], "previous_owner_bot_admin": bool(previous_bot_admin)})
    return load_owner(c, settings)


def view(c, settings, roster, proxy_kind, owner_id):
    """What the People tab renders."""
    owner, access = load_owner(c, settings), load_access(c, settings)
    people = []
    for p in roster["people"]:
        left = bool(p.get("hidden"))
        people.append({"id": p["id"], "name": p["name"], "email": p["email"], "title": p["title"],
                       "team": p["team"], "left": left, "owner": p["email"] == owner["email"] and bool(p["email"]),
                       "bot_admin": p["email"] in access["bot_admins"] and bool(p["email"]),
                       "can_sign_in": bool(p["email"]) and not left})
    return {"owner": {**owner, "person": owner_id}, "people": people, **{
        k: access[k] for k in ("allowed", "allowed_domains", "bot_admins", "revision", "updated", "updated_by")},
        "proxy": proxy_kind}
