
from setup import envfile
from setup.settings import Settings


def s(**kw):
    base = dict(domain="t.example.com", company="Acme Inc", owner_email="me@example.com", auth="google",
                client_id="cid", client_secret="S3cret$value")
    base.update(kw)
    return Settings(**base)


def test_render_orders_and_omits_empty_and_doubles_dollars():
    text = envfile.render(s().to_env())
    assert 'TICO_TEAM_NAME="Acme Inc"' in text and 'TICO_COMPANY_NAME="Acme Inc"' in text
    assert 'TICO_OIDC_CLIENT_SECRET="S3cret$$value"' in text
    assert "COMPOSE_PROFILES=caddy,updater" in text
    assert "TICO_TAG" not in text and "CLOUDFLARE_TUNNEL_TOKEN" not in text
    assert text.index("TICO_COMPANY_NAME") < text.index("TICO_AUTH_PROXY")


def test_redact_masks_every_secret_key_and_only_those():
    x = s(decisions_provider="openai", decisions_key="sk-abc123", front_door="cloudflared", tunnel_token="tok-999")
    red = envfile.redact_env(envfile.render(x.to_env()))
    for secret in ("S3cret", "sk-abc123", "tok-999"):
        assert secret not in red
    assert "TICO_OIDC_CLIENT_ID=cid" in red and red.count("********") == 3


def test_scrub_removes_secret_values_from_free_text():
    assert envfile.scrub("boom tok-999 boom", ["tok-999"]) == "boom ******** boom"

