"""Invite emails (backend/invites.py): the owner clicks Invite and Tico's own sign-in mail sends it, through the Tico
account issuer the install signs in with. Never the company's mailbox; every refusal is shown with a plain reason."""

import uuid

import pytest

from backend.tests.test_api import api  # noqa: F401  (the api fixture)
from backend.tests.test_oidc import CLIENT, SECRET, provider, signin  # noqa: F401  (the fixtures)


def owner(signin):  # noqa: F811
    """Ana, the owner, signed in through the issuer; the headers a browser write carries."""
    done = signin.login(claims={"email": "ana@acme.example"})
    assert done.status_code == 302, done.text
    return {"origin": signin.settings.public_url, "idempotency-key": "invite-" + uuid.uuid4().hex}


def invites_sent(signin):  # noqa: F811
    with signin.auth.store.read() as c:
        from backend import invites
        return invites.sent(c)


def test_invite_goes_out_from_the_tico_issuer_with_the_installs_client_credentials_and_is_recorded(signin):  # noqa: F811
    signin.fake.invites = [(202, {"status": "sent"})]
    headers = owner(signin)
    sent = signin.api.post("/api/v2/access/people/cara/invite", json={}, headers=headers)
    assert sent.status_code == 200, sent.text
    assert sent.json()["person"] == "cara" and sent.json()["invited_at"]
    call, = signin.fake.invite_calls
    # Only the address goes with the install's own client id and secret: no text of the caller's reaches the mail.
    assert call == {"client_id": CLIENT, "client_secret": SECRET, "email": "cara@acme.example"}
    assert invites_sent(signin)["cara"]["by"] == "human:ana"


@pytest.mark.parametrize("answer, code, words", [
    ((502, {"error": "not_sent"}), "invite_failed", "couldn't deliver the invite to cara@acme.example"),
    ((429, {"error": "too_many", "retry_after": 3600}), "invite_limited", "Too many invites"),
    ((503, {"error": "mail_unavailable"}), "invite_failed", "isn't available right now"),
    ((401, {"error": "invalid_client"}), "invite_failed", "refused the invite"),
], ids=["not-sent", "too-many", "no-mail", "bad-client"])
def test_an_invite_that_does_not_go_out_is_a_visible_error_and_is_not_recorded(signin, answer, code, words):  # noqa: F811
    signin.fake.invites = [answer]
    refused = signin.api.post("/api/v2/access/people/cara/invite", json={}, headers=owner(signin))
    # 422, never 429 or 502: the browser retries those as unconfirmed, asking the issuer again and hiding the reason.
    assert refused.status_code == 422, refused.text
    assert refused.json()["error"]["code"] == code and words in refused.json()["error"]["detail"], refused.text
    assert "cara" not in invites_sent(signin)
    assert len(signin.fake.invite_calls) == 1


def test_an_issuer_that_sends_no_invites_is_never_sent_the_secret_and_the_owner_is_told_what_to_do(signin):  # noqa: F811
    refused = signin.api.post("/api/v2/access/people/cara/invite", json={}, headers=owner(signin))
    assert refused.status_code == 409 and refused.json()["error"]["code"] == "invite_unavailable"
    assert "Tell Cara to sign in at " + signin.settings.public_url in refused.json()["error"]["detail"]
    assert signin.fake.invite_calls == []


def test_only_an_owner_or_admin_sends_invites_and_only_to_someone_on_the_roster(signin):  # noqa: F811
    signin.fake.invites = [(202, {"status": "sent"})]
    assert signin.login(claims={"email": "cara@acme.example"}).status_code == 302
    headers = {"origin": signin.settings.public_url}
    assert signin.api.post("/api/v2/access/people/ben/invite", json={}, headers=headers).status_code == 403
    signin.api.cookies.clear()
    headers = owner(signin)
    assert signin.api.post("/api/v2/access/people/nobody/invite", json={}, headers=headers).status_code == 404
    assert signin.fake.invite_calls == []
