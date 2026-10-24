"""Invite emails: the owner clicks Invite and the person gets "You're invited to Tico" from Tico's own sign-in mail,
the sender and family of the sign-in codes, never the company's connected mailbox. The install asks its Tico account
issuer to send it (`Oidc.invite`, the issuer's POST /oauth2/invite), so the mail says only who is invited and where to
sign in. An install that signs in some other way can't send one, and says so: the owner tells the person themselves.

Every outcome is the owner's to see: a refusal is a Problem with a plain reason, and a sent invite is recorded in
registry_metadata `invites` ({person id: {at, by}}) so the People page can say when. A refusal is a 422, never a 429
or 502: the browser retries those writes as unconfirmed (ui/app/api.js), which would ask the issuer three times, spend
the address's daily invites and hide the reason.
"""

import json

from .store import H, Problem, encode

KEY = "invites"
REASONS = {
    "too_many": "Too many invites to this address today. Try again tomorrow.",
    "invalid_email": "Tico's sign-in mail can't send to {email}. Check the address.",
    "mail_unavailable": "Tico's sign-in mail isn't available right now. Try again later.",
    "not_sent": "Tico's sign-in mail couldn't deliver the invite to {email}. Check the address, then try again.",
}


def sent(c):
    """{person id: {at, by}} for every invite sent."""
    row = c.execute("SELECT value_json FROM registry_metadata WHERE key=?", (KEY,)).fetchone()
    value = json.loads(row["value_json"]) if row else {}
    return value if isinstance(value, dict) else {}


def record(c, actor, pid):
    at = H.now()
    invites = {**sent(c), pid: {"at": at, "by": actor}}
    c.execute("INSERT INTO registry_metadata(key,value_json) VALUES(?,?) "
              "ON CONFLICT(key) DO UPDATE SET value_json=excluded.value_json", (KEY, encode(invites)))
    H.event(c, actor, "person.invited", pid, {})
    return at


def send(auth, settings, person):
    """Mail `person` (a roster row) an invite to sign in here, or raise a Problem the owner sees. Runs outside a
    transaction: it waits on the issuer, which waits on the mail."""
    from .oidc import SignInError

    email, name = person.get("email") or "", person.get("name") or "this person"
    where = settings.public_url
    proxy = getattr(auth, "proxy", None)
    if not email:
        raise Problem("invite_email", f"{name} has no email address to invite", 422)
    if not proxy or getattr(proxy, "name", "") != "oidc" or not hasattr(proxy, "invite"):
        raise Problem("invite_unavailable", f"This Tico doesn't sign in with Tico accounts, so it can't email invites. "
                                            f"Tell {name} to sign in at {where} with {email}.", 409)
    try:
        answer = proxy.invite(email)
    except SignInError:
        raise Problem("invite_failed", "Tico's sign-in service couldn't be reached, so the invite wasn't sent. "
                                       "Try again in a minute.", 422) from None
    if answer is None:
        raise Problem("invite_unavailable", f"This Tico's sign-in provider doesn't send Tico invites. "
                                            f"Tell {name} to sign in at {where} with {email}.", 409)
    status, body = answer
    if status == 202 and body.get("status") == "sent":
        return
    code = str(body.get("error") or "")
    reason = REASONS.get(code, "Tico's sign-in mail refused the invite, so it wasn't sent.").format(email=email)
    raise Problem("invite_limited" if code == "too_many" else "invite_failed", reason, 422)
