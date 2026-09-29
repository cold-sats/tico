"""No ambient owner identity: all requests carry verified human or machine credentials."""

import hmac
import json
import sqlite3
import stat
from dataclasses import dataclass
from http.cookies import SimpleCookie, CookieError

import yaml

from . import identity_proxy
from . import people as P
from . import rooms
from .store import H, Problem, digest

# Loopback sign-in for an environment with no identity proxy in front of it.
LOCAL_COOKIE = "tico_local_session"
LOCAL_SIGNIN_PATH = "/api/v2/local-signin"
LOGOUT_PATH = "/api/v2/logout"


def cookies(headers):
    jar = SimpleCookie()
    try:
        jar.load(headers.get("cookie", ""))
    except CookieError:
        return {}
    return {name: morsel.value for name, morsel in jar.items()}


@dataclass(frozen=True)
class Identity:
    actor: str
    role: str
    email: str = ""
    runner_id: str = ""
    attempt_id: str = ""
    # The harness id when this bot is run by an external agent (a Hermes profile) with its
    # own standing credential rather than a runner's per-turn lease (backend/agents.py).
    agent: str = ""
    # A person acting through a personal API token (backend/personal_tokens.py) rather than a
    # browser sign-in. The same person with the same rights, except that a token cannot make
    # or revoke tokens.
    via_token: bool = False
    # That token's label ("grok-bot", "muse"): which assistant is acting for the person, said
    # where it matters, e.g. on the message a batch sends a bot (backend/batch.py).
    token_label: str = ""
    # A browser session vouched for by the identity proxy in front of the server (Cloudflare Access,
    # the AWS load balancer), the only kind that /api/v2/logout can end; the UI offers "Sign out" for it.
    via_proxy: bool = False


def has_left(c, pid):
    """Marked as left on the roster (backend/app.py person_update), which also ended their tokens."""
    row = c.execute("SELECT value_json FROM registry_metadata WHERE key='people'").fetchone()
    if not row:
        return False
    try:
        people = json.loads(row[0]).get("people") or []
    except (ValueError, AttributeError):
        return False
    return any(p.get("id") == pid and p.get("hidden") for p in people if isinstance(p, dict))


def validate_identity(c, who):
    if who.role in ("owner", "human"):
        if not H.human(c, H.actor_id(who.actor)):
            raise Problem("identity", "Unknown person", 401)
        if has_left(c, H.actor_id(who.actor)):
            raise Problem("identity", "This person has left the company", 403)
        return
    if who.role == "bot" and who.agent:
        record = c.execute("SELECT revoked_at FROM agents WHERE bot=?", (H.actor_id(who.actor),)).fetchone()
        if not record or record["revoked_at"]:
            raise Problem("revoked", "Agent credential is revoked or unknown", 401)
        state = (H.bot(c, H.actor_id(who.actor)) or {}).get("state")
        if state != "active":
            raise Problem("paused", "This bot is " + str(state or "unknown") + ", not active; "
                          "a person changes that in Settings", 409)
        return
    runner = c.execute("SELECT * FROM runners WHERE id=? AND revoked_at IS NULL",
                       (who.runner_id,)).fetchone()
    if not runner:
        raise Problem("revoked", "Runner credential is revoked or unknown", 401)
    if who.role == "bot":
        row = c.execute("SELECT a.*, x.runner_id AS assigned_runner, x.generation AS assigned_generation "
                        "FROM attempts a JOIN assignments x ON x.bot=a.bot WHERE a.id=?",
                        (who.attempt_id,)).fetchone()
        if (not row or row["state"] not in ("leased", "running") or row["lease_until"] <= H.now()
                or row["assigned_runner"] != who.runner_id
                or row["assigned_generation"] != row["generation"]
                or H.bot(c, row["bot"])["state"] != "active"):
            raise Problem("stale_lease", "Execution ownership expired; stop work and reconnect", 409)


def _own_ask_to_a_person(who, row):
    """A bot's own question to a person: reachable from whichever run it is in.

    A turn is granted the conversations its attempt was handed, which for a scheduled routine is
    that routine's task and nothing else. So a routine had no way to ask a person anything --
    `hub ask ben` came back "outside the current execution context" -- and the bots that run
    entirely on routines fell back to `hub task create --owner ben`. That put questions on a
    person's task list in a shape nobody wanted, and made them clear the human-item lint first:
    a bot could spend several attempts getting one title past it, to file something
    that was a question the whole time.

    An ask conversation is two participants, one of them human, and no task. Granting a bot its
    own exposes no chat history -- that is the `chat` kind, and it stays scoped to the run.
    """
    if row.get("kind") != "ask" or row.get("task_id"):
        return False
    participants = row.get("participants") or []
    people = [p for p in participants if H.is_human(p)]
    return len(participants) == 2 and len(people) == 1 and who.actor in participants


class Auth:
    def __init__(self, store):
        self.store = store
        self.settings = store.settings
        acl_path = self.settings.registry_dir / "hub-access.yaml"
        self.acl = yaml.safe_load(acl_path.read_text()) if acl_path.exists() else {}
        self.private = set(self.acl.get("private_owners", []))
        self.bot_admins = set()
        self.allowed_emails, self.allowed_domains = set(), set()
        self.routing_permissions = {
            str(target).strip().lower(): {str(s).strip().lower() for s in (senders or [])}
            for target, senders in (self.acl.get("routing_permissions") or self.acl.get("dispatch_permissions") or {}).items()
        }
        self.owner_email = self.settings.owner_email
        self._owner_id = ""
        self._access_seen = None
        self.proxy = identity_proxy.build(self.settings, store)

    def sync_access(self, c):
        """Adopt the stored owner and access list. One indexed read per request keeps a transfer
        or a list change effective at once, with no restart."""
        rows = tuple(sorted(tuple(r) for r in c.execute(
            "SELECT key,value_json FROM registry_metadata WHERE key IN ('owner','access')")))
        if rows == self._access_seen:
            return
        from . import access
        owner = access.load_owner(c, self.settings)
        lists = access.load_access(c, self.settings)
        self._access_seen = rows
        self.owner_email = owner["email"]
        self._owner_id = ""
        self.bot_admins = set(lists["bot_admins"])
        self.allowed_emails, self.allowed_domains = set(lists["allowed"]), set(lists["allowed_domains"])
        # Everything that still reads the settings sees the owner in force.
        previous, self.settings.owner_email = self.settings.owner_email, self.owner_email
        if (getattr(self.settings, "credential_admins_follow_owner", False)
                and self.settings.credential_admins == ((previous,) if previous else ())):
            self.settings.credential_admins = (self.owner_email,) if self.owner_email else ()

    def admits(self, email):
        email = str(email or "").strip().lower()
        return bool(email and "@" in email and (email in self.allowed_emails
                                                 or email.rsplit("@", 1)[1] in self.allowed_domains))

    def warm(self):
        """Fetch the proxy's signing keys once at startup, so no person's request waits for them."""
        try:
            if self.proxy:
                self.proxy.warm()
        except Exception:
            pass                        # the first sign-in fetches them instead

    def owner_id(self, c):
        """The roster id of this environment's owner. One process serves one company, so the
        lookup is kept once it succeeds; an empty roster is retried on the next request."""
        if not self._owner_id and self.owner_email:
            row = c.execute("SELECT id FROM humans WHERE lower(email)=?", (self.owner_email,)).fetchone()
            self._owner_id = row["id"] if row else ""
        return self._owner_id

    def owner_identity(self, c):
        pid = self.owner_id(c)
        if not pid:
            raise Problem("identity", "The owner of this environment (" + (self.owner_email or "unset")
                          + ") is not on the people roster", 403)
        return Identity("human:" + pid, "owner", email=self.owner_email)

    def local_token(self):
        """The loopback session secret, or "" when local sign-in is not configured."""
        path = self.settings.local_owner_token_file
        if not path:
            return ""
        try:
            mode = stat.S_IMODE(path.stat().st_mode)
            token = path.read_text().strip()
        except OSError:
            raise Problem("identity", "The local sign-in token file is missing or unreadable", 500) from None
        if mode & 0o077:
            raise Problem("identity", "The local sign-in token file must be readable only by its owner (chmod 600)", 500)
        return token

    def local_owner(self, token):
        """Whether this bearer token or cookie is the loopback owner session secret."""
        expected = self.local_token()
        return bool(expected and token and hmac.compare_digest(expected, str(token)))

    def identity_from_local_owner_token(self, c, token):
        """Admit a configured local-only bearer when no identity proxy is in use.

        For self-hosted / loopback installs without an identity proxy: set
        TICO_LOCAL_OWNER_EMAIL and TICO_LOCAL_OWNER_TOKEN (at least 32 characters).
        The bearer maps to the roster human with that email; role is owner only when
        the email matches this environment's owner.
        """
        if self.settings.proxy_kind:
            return None
        email = (self.settings.local_owner_email or "").strip().lower()
        expected = self.settings.local_owner_token or ""
        if not email or len(expected) < 32:
            return None
        if not token or len(token) != len(expected) or not hmac.compare_digest(expected, token):
            return None
        row = c.execute("SELECT id FROM humans WHERE lower(email)=?", (email,)).fetchone()
        if not row:
            raise Problem("identity", "This account is not on the " + self.settings.app_name
                          + " roster", 403)
        role = "owner" if email and email == self.owner_email else "human"
        return Identity("human:" + row["id"], role, email=email)

    def identity_from_personal_token(self, c, token):
        """The person behind a personal API token, or None when no live token has this hash.

        A revoked or expired token is refused exactly like an unknown one. The lookup answers
        with the same identity the browser sign-in builds for that person, marked `via_token`.
        """
        row = c.execute("SELECT t.id,t.label,t.last_used,t.expires_at,t.revoked_at,h.id AS human,h.email "
                        "FROM human_tokens t JOIN humans h ON h.id=t.human WHERE t.token_hash=?",
                        (digest(token),)).fetchone()
        if not row or row["revoked_at"] or (row["expires_at"] and row["expires_at"] <= H.now()):
            return None
        now = H.now()
        # last_used is a hint for the token list, not part of the decision: a script in a loop
        # should not write a row per request, and a locked database must not refuse a read.
        if not row["last_used"] or row["last_used"] < H.shift(now, seconds=-60):
            try:
                c.execute("UPDATE human_tokens SET last_used=? WHERE id=?", (now, row["id"]))
            except sqlite3.Error:
                pass
        email = str(row["email"] or "").lower()
        role = "owner" if email and email == self.owner_email else "human"
        return Identity("human:" + row["human"], role, email=email, via_token=True,
                        token_label=str(row["label"] or ""))

    def authenticate(self, headers):
        bearer = headers.get("authorization", "")
        token = bearer[7:] if bearer.startswith("Bearer ") else ""
        if token.startswith("tico_st_") and getattr(self.proxy, "sessions", False):
            # A frontend's bearer session (backend/oidc.py): looked up like the browser's cookie.
            headers = {"cookie": self.proxy.cookie + "=" + token[len("tico_st_"):]}
            token = ""
        with self.store.read() as c:
            self.sync_access(c)
            if token in self.settings.test_identities:
                who = self.settings.test_identities[token]
            elif token and self.local_owner(token):
                who = self.owner_identity(c)
            elif token and (who := self.identity_from_local_owner_token(c, token)):
                pass
            elif token:
                row = c.execute("SELECT id FROM runners WHERE token_hash=? AND revoked_at IS NULL",
                                (digest(token),)).fetchone()
                agent = None if row else c.execute(
                    "SELECT bot,harness FROM agents WHERE token_hash=? AND revoked_at IS NULL",
                    (digest(token),)).fetchone()
                if row:
                    who = Identity("runner:" + row["id"], "runner", runner_id=row["id"])
                elif agent:
                    who = Identity("bot:" + agent["bot"], "bot", agent=agent["harness"])
                else:
                    attempt = c.execute("SELECT * FROM attempts WHERE token_hash=?", (digest(token),)).fetchone()
                    if attempt:
                        who = Identity("bot:" + attempt["bot"], "bot", runner_id=attempt["runner_id"],
                                       attempt_id=attempt["id"])
                    elif not (who := self.identity_from_personal_token(c, token)):
                        raise Problem("identity", "Invalid credential", 401)
            elif self.local_owner(cookies(headers).get(LOCAL_COOKIE, "")):
                who = self.owner_identity(c)
            else:
                if self.proxy and getattr(self.proxy, "sessions", False):
                    email = self.proxy.email(headers, c)
                else:
                    email = self.proxy.email(headers) if self.proxy else None
                if email is None:
                    # The UI's fetch layer follows `sign_in` to the built-in login page.
                    extra = {"sign_in": "/auth/login"} if self.proxy and self.proxy.name == "oidc" else None
                    raise Problem("identity", "Sign in to " + self.settings.app_name, 401, extra=extra)
                # A signed assertion without an email (a Cloudflare service token) would otherwise
                # match a roster entry that has none, and "" is also an unset owner email.
                if not email:
                    raise Problem("identity", "This sign-in carries no email address", 401)
                row = c.execute("SELECT id FROM humans WHERE lower(email)=?", (email,)).fetchone()
                if not row and self.admits(email):
                    row = {"id": self.join(email)}
                # The people roster is the approved internal-user list; the allow list adds to it.
                if not row:
                    raise Problem("identity", "This account is not on the " + self.settings.app_name
                                  + " roster", 403)
                who = Identity("human:" + row["id"],
                               "owner" if email == self.owner_email else "human", email=email, via_proxy=True)
            validate_identity(c, who)
            return who

    def join(self, email):
        """The allow list admitted this verified address: add them to the roster as a person."""
        from . import access
        with self.store.transaction() as c:
            row = c.execute("SELECT id FROM humans WHERE lower(email)=?", (email,)).fetchone()
            return row["id"] if row else access.join_on_sign_in(c, email)

    def visible_bot(self, who, slug):
        if who.role == "owner" or slug not in self.private or who.actor == "bot:" + slug:
            return True
        if who.role == "bot":
            caller_slug = H.actor_id(who.actor)
            if caller_slug in self.routing_permissions.get(slug, set()):
                return True
        return False

    def operator(self, c, who, bot):
        row = c.execute("SELECT operator FROM bot_config WHERE bot=?", (bot,)).fetchone()
        return bool(row and (who.role == "owner" or
                            who.role == "human" and who.actor == "human:" + row["operator"]))

    def manages(self, c, who, kind, ident):
        """The owner, or a person above this person or bot on the org chart (backend/people.py
        `manages`). The one rule behind editing a profile, a bot, or a place in the chart."""
        if who.role == "owner":
            return True
        if who.role != "human":
            return False
        from . import views
        archived = {row["slug"] for row in H.bots(c) if row.get("state") == "archived"}
        return P.manages(H.actor_id(who.actor), kind, ident, views.roster(c), views.entries(c), archived)

    def bot_admin(self, who):
        """Whether a person may administer bots assigned to their own operator identity."""
        return who.role == "owner" or (who.role == "human" and who.email.lower() in self.bot_admins)

    def identity_for_actor(self, c, actor):
        """Rebuild a human identity for deferred work without elevating its permissions."""
        human = H.human(c, H.actor_id(actor)) if str(actor).startswith("human:") else None
        if not human:
            raise Problem("identity", "The person who requested this change is no longer on the roster", 403)
        email = str(human.get("email") or "").lower()
        role = "owner" if email and email == self.owner_email else "human"
        return Identity(actor, role, email=email)

    def domain(self, who):
        if who.role == "runner":
            raise Problem("identity", "Runner credentials cannot act as a human or bot", 403)

    def bot_contact(self, c, who, slug, conversation_id=None, task_id=None, kind="message"):
        """Whether this sender may open something with `slug`.

        `tasks` is the strict one and the simplest to reason about: work arrives as a task and
        nothing else. No bot may chat it, ask it anything or steer it — not its manager, not a
        bot holding one of its tickets. A task is a thing to do and it is dispatched without a
        reply; a message is a conversation, and a conversation between bots is a run spent on
        somebody else's business. Bots file work on each other and walk away.

        A bot set to `bot_contact: replies` does not take chats, questions or tasks from other
        bots it has no business with. Every run costs its operator real money, and a bot with a
        narrow job should not be a free help desk for the rest of the fleet.

        People are never affected: the point is to stop bots pinging bots, not to make a bot
        unreachable. Four things still get through, because each one is the protected bot's own
        doing or its own chain of command:

        - itself, and the keeper (notices about its own tasks are written directly, not here)
        - its manager, the bot named in `reports_to`: the org chart is what decides who directs
          whom, and a manager that cannot assign its report is not a manager
        - a bot holding an open task this bot requested — how a ticket gets a question back
        - a bot in a conversation this bot opened with it

        The last two are scoped to that task and that conversation, so answering once does not
        hand out a standing invitation. An answer to a waiting `ask` never comes through here at
        all (`hubdb.answer` checks only that the ask was addressed to you), so refusing contact
        cannot strand a bot that is blocking on a reply.
        """
        if who.role != "bot":
            return True
        sender = who.actor
        if sender == "bot:" + slug or sender == H.KEEPER:
            return True
        row = c.execute("SELECT config_json,reports_to FROM bot_config WHERE bot=?", (slug,)).fetchone()
        if not row:
            return True
        declared = json.loads(row["config_json"]) if row["config_json"] else {}
        mode = declared.get("bot_contact", "open")
        if mode == "tasks":
            return kind == "task"
        if mode != "replies":
            return True
        if H.bot_actor(row["reports_to"] or declared.get("reports_to") or "") == sender:
            return True
        asked = "bot:" + slug
        if task_id:
            task = c.execute("SELECT requester,owner FROM tasks WHERE id=?", (task_id,)).fetchone()
            if task and task["requester"] == asked and task["owner"] == sender:
                return True
        if c.execute("SELECT 1 FROM tasks WHERE requester=? AND owner=? AND status NOT IN "
                     "('done','closed','declined') LIMIT 1", (asked, sender)).fetchone():
            return True
        if conversation_id and c.execute(
                "SELECT 1 FROM messages WHERE conversation_id=? AND from_actor=? AND to_actor=? LIMIT 1",
                (conversation_id, asked, sender)).fetchone():
            return True
        return False

    def require_bot_contact(self, c, who, actor, conversation_id=None, task_id=None, kind="message"):
        """`bot_contact` as a gate. The refusal names the way back in, because the sending bot
        reads it and has to decide what to do next."""
        if not str(actor).startswith("bot:"):
            return
        slug = H.actor_id(actor)
        if self.bot_contact(c, who, slug, conversation_id, task_id, kind):
            return
        row = c.execute("SELECT config_json FROM bot_config WHERE bot=?", (slug,)).fetchone()
        declared = json.loads(row["config_json"]) if row and row["config_json"] else {}
        if declared.get("bot_contact") == "tasks":
            raise Problem("bot_contact", f"{slug} takes work as a task and nothing else. File one "
                                         f"with `hub task create --owner {slug}`, say what you want "
                                         "done in the body, and do not wait for it.", 403)
        raise Problem("bot_contact", f"{slug} does not take contact from other bots. Ask its "
                                     "manager or a person to pass this on, or reply on a task or "
                                     "conversation it opened with you.", 403)

    def target(self, c, who, target):
        self.domain(who)
        actor = H.resolve_actor(c, target)
        if not actor or actor == H.KEEPER:
            raise Problem("not_found", "Unknown recipient", 404)
        if actor.startswith("bot:") and not self.visible_bot(who, H.actor_id(actor)):
            raise Problem("forbidden", "This bot is private", 403)
        return actor

    def conversation(self, c, who, conversation_id):
        self.domain(who)
        row = H.conversation(c, conversation_id)
        if not row:
            raise Problem("not_found", "Conversation not found", 404)
        if who.role == "bot":
            # A runner turn sees the conversations its attempt was handed. An external agent
            # has no attempt: it sees the conversations it is in, which is what a claim would
            # have granted a turn for the same message.
            if who.agent:
                grant = who.actor in row["participants"] or rooms.room_bot(row) == H.actor_id(who.actor)
            else:
                grant = c.execute("SELECT 1 FROM attempt_conversations WHERE attempt_id=? AND conversation_id=?",
                                  (who.attempt_id, conversation_id)).fetchone()
            # Task discussions are shared with their owners/delegates. Personal chat history
            # is scoped to this execution, not every human who has used the same bot.
            if not grant:
                if row.get("task_id") and row["kind"] == "task":
                    self.task(c, who, row["task_id"])
                elif _own_ask_to_a_person(who, row):
                    pass
                else:
                    raise Problem("forbidden", "This conversation is outside the current execution context", 403)
            return row
        scope = row.get("scope") or "direct"
        if scope == rooms.PERSONAL:
            owner = row.get("owner_actor") or next(
                (p for p in row["participants"] if str(p).startswith("human:")), None)
            # Personal assistant rooms do not inherit the normal owner inspection bypass.
            if who.actor != owner:
                raise Problem("forbidden", "This personal conversation belongs to another person", 403)
        elif scope == rooms.SHARED:
            bot = rooms.room_bot(row)
            if not bot or not rooms.shared_member(c, self, who.actor, bot):
                raise Problem("forbidden", "You are not a member of this shared bot room", 403)
        elif who.role != "owner" and who.actor not in row["participants"]:
            raise Problem("forbidden", "This conversation is private", 403)
        return row

    def tico_principal(self, c, who):
        """The signed-in person represented by a private assistant execution."""
        name = self.settings.assistant_name
        if who.role in ("owner", "human"):
            return who
        if who.role != "bot" or who.actor != "bot:" + self.settings.assistant_bot:
            raise Problem("forbidden", "This endpoint is available only to people and " + name, 403)
        row = c.execute(
            "SELECT v.scope,v.owner_actor,m.from_actor FROM attempts a "
            "JOIN jobs j ON j.id=a.job_id JOIN messages m ON m.id=j.message_id "
            "JOIN conversations v ON v.id=m.conversation_id WHERE a.id=?", (who.attempt_id,)).fetchone()
        if not row or row["scope"] != rooms.PERSONAL:
            raise Problem("forbidden", "Fleet access requires a private " + name + " conversation", 403)
        actor = row["owner_actor"]
        if not actor or not str(actor).startswith("human:"):
            raise Problem("forbidden", "This " + name + " turn is not acting for a signed-in person", 403)
        human = H.human(c, H.actor_id(actor))
        if not human:
            raise Problem("forbidden", "The initiating person is no longer on the roster", 403)
        email = str(human.get("email") or "").lower()
        role = "owner" if email and email == self.owner_email else "human"
        return Identity(actor, role, email=email)

    def task_row(self, c, who, row):
        self.domain(who)
        if not row:
            raise Problem("not_found", "Task not found", 404)
        if who.role == "owner":
            return row
        participants = (row["owner"], row["requester"])
        if any(a.startswith("bot:") and H.actor_id(a) in self.private for a in participants) and who.actor not in participants:
            raise Problem("forbidden", "This task is private", 403)
        if who.role == "bot" and who.actor not in participants:
            delegated = c.execute("SELECT 1 FROM task_delegations WHERE task_id=? AND delegate=? AND expires>?",
                                  (row["id"], who.actor, H.now())).fetchone()
            if not delegated:
                raise Problem("forbidden", "This task is not assigned or delegated to you", 403)
        return row

    def task(self, c, who, task_id):
        return self.task_row(c, who, H.task(c, task_id))

    def approval(self, c, who, approval_id, decide=False):
        self.domain(who)
        row = H.approval(c, approval_id)
        if not row:
            raise Problem("not_found", "Approval not found", 404)
        msg = H.message(c, row["message_id"])
        if decide:
            allowed = who.role in ("owner", "human") and msg["to_actor"] == who.actor
        else:
            allowed = who.role == "owner" or who.actor in (row["requested_by"], msg["to_actor"])
        if not allowed:
            raise Problem("forbidden", "This approval is not yours", 403)
        return row
