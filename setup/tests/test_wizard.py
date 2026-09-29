import json

import pytest

from setup import cli, dns, state, verify, wizard
from setup.remote import Result
from setup.tests import fakes
from setup.tests.fakes import CaptureIO, FakeShell, aws_clients

SECRET = "GOCSPX-supersecret"
BASE = ["--non-interactive", "--domain", "tico.example.com", "--auth", "google", "--client-id", "cid.apps.googleusercontent.com",
        "--company", "Acme", "--owner-email", "me@example.com"]


@pytest.fixture(autouse=True)
def secret_env(monkeypatch):
    monkeypatch.setenv("TICO_OIDC_CLIENT_SECRET", SECRET)
    monkeypatch.setattr(verify, "run_all", lambda **kw: [verify.Check("stub", True, "ok")])


def go(argv, deps=None, io=None):
    io = io or CaptureIO()
    code = cli.main(argv, deps=deps or fakes.deps(), io=io)
    return code, io.text


def test_dry_run_aws_caddy_google_prints_the_plan_and_changes_nothing(tmp_path):
    code, out = go(["--dry-run", "--target", "aws", "--front-door", "caddy", *BASE])
    assert code == 0
    for want in ("EC2 t4g.small", "no SSH key, no port 22", "hop limit 1", "Elastic IP", "Netlify DNS (NS1 nameservers)",
                 "A tico.example.com -> <elastic-ip>", "https://tico.example.com/auth/callback", "Estimated cost", "ManagedBy=tico-setup",
                 "Bots run on computers you add afterwards"):
        assert want in out
    assert SECRET not in out and "TICO_OIDC_CLIENT_SECRET=********" in out
    assert not (tmp_path / "home").exists()


def test_dry_run_ssh_and_command_and_cloudflared():
    code, out = go(["--dry-run", "--target", "ssh", "--ssh", "root@203.0.113.7", *BASE])
    assert code == 0 and "Over SSH to root@203.0.113.7" in out and "A tico.example.com -> 203.0.113.7" in out
    code, out = go(["--dry-run", "--target", "command", "--server-ip", "203.0.113.7", *BASE])
    assert code == 0 and "paste-able install command" in out
    code, out = go(["--dry-run", "--target", "aws", "--front-door", "cloudflared", *BASE])
    assert code == 0 and "no inbound rules at all" in out and "CNAME tico.example.com -> <tunnel-id>.cfargotunnel.com" in out
    assert "you create it in the dashboard" in out and "Elastic IP" not in out.replace("No Elastic IP", "")


def test_dry_run_with_no_answers_still_shows_placeholders_and_never_prompts():
    code, out = go(["--dry-run", "--non-interactive", "--target", "aws", "--domain", "tico.example.com"])
    assert code == 0 and "<client_id>" in out


def test_non_interactive_missing_value_names_the_flag():
    code, out = go(["--non-interactive", "--target", "aws", "--domain", "tico.example.com"])
    assert code == 2 and "--client-id" in out


def test_invalid_domain_and_email_rejected():
    assert go(["--dry-run", "--target", "aws", *BASE[:1], "--domain", "not a domain", *BASE[3:]])[0] == 2
    assert go(["--dry-run", "--target", "aws", *BASE[:-1], "nope"])[0] == 2


def test_ssh_run_orders_dns_before_starting_docker_and_never_leaks_the_secret(monkeypatch):
    shell = FakeShell()
    r = fakes.FakeResolver({("tico.example.com", dns.A): ["203.0.113.7"]}, {"example.com": fakes.NETLIFY_NS})
    d = fakes.deps()
    d.resolver, d.public_resolvers, d.ssh_shell = r, (lambda: [("Google", r)]), (lambda *a: shell)
    code, out = go(["--target", "ssh", "--ssh", "root@203.0.113.7", "--yes", *BASE], deps=d)
    assert code == 0, out
    assert out.index("Add these records there") < out.index("docker compose pull")
    assert SECRET not in out
    env_input = next(i for c, i in shell.calls if i and b"TICO_DOMAIN" in i)
    assert SECRET.encode() in env_input  # it reaches the server, via stdin only
    assert not any(SECRET in c for c in shell.cmds())
    assert "Done. Open https://tico.example.com and sign in as me@example.com" in out
    assert "Settings > Devices > Add computer" in out and "setup runner" in out
    saved, env = state.load("tico.example.com")
    assert SECRET not in json.dumps(saved) and SECRET in env


def test_ssh_run_stops_before_docker_when_dns_never_goes_live():
    shell = FakeShell()
    d = fakes.deps()
    d.ssh_shell = lambda *a: shell
    code, out = go(["--target", "ssh", "--ssh", "root@203.0.113.7", "--yes", "--dns-timeout", "0", *BASE], deps=d)
    assert code == 2 and "Still not resolving" in out and "Not starting Tico yet" in out
    assert shell.calls == []


def test_aws_run_sets_dns_from_the_eip_then_waits_then_verifies():
    ec2, iam, ssm, factory = aws_clients()
    r = fakes.FakeResolver({("tico.example.com", dns.A): ["203.0.113.9"]}, {"example.com": fakes.NETLIFY_NS})
    d = fakes.deps()
    d.resolver, d.public_resolvers, d.aws_clients = r, (lambda: [("Google", r)]), factory
    code, out = go(["--target", "aws", "--yes", "--front-door", "caddy", "--backup", "local", *BASE], deps=d)
    assert code == 0, out
    assert "A      name tico         value 203.0.113.9" in out or "203.0.113.9" in out
    (run,) = ec2.called("run_instances")
    assert SECRET not in run["UserData"] and "getent hosts tico.example.com" in run["UserData"]
    assert SECRET in ssm.called("put_parameter")[0]["Value"]
    assert state.load("tico.example.com")[0]["aws_instance_id"] == "i-1"


def test_doctor_reads_saved_state_and_reports_failures_with_hints(monkeypatch):
    go(["--dry-run", "--target", "aws", *BASE])  # dry run saves nothing
    assert go(["doctor", "--domain", "tico.example.com"])[0] == 2
    state.save("tico.example.com", {"target": "ssh", "domain": "tico.example.com", "ssh_host": "root@h", "auth": "google",
                                    "client_id": "cid", "front_door": "caddy", "server_ip": "203.0.113.7"}, "TICO_DOMAIN=tico.example.com\n")
    seen = {}
    monkeypatch.setattr(verify, "run_all", lambda **kw: seen.update(kw) or [verify.Check("HTTPS certificate", False, "boom", "open 443")])
    d = fakes.deps()
    d.ssh_shell = lambda *a: FakeShell()
    code, out = go(["doctor", "--domain", "tico.example.com"], deps=d)
    assert code == 1 and "fix: open 443" in out and seen["shell"] is not None and seen["records"][0].value == "203.0.113.7"


def test_route53_only_when_that_zone_is_the_delegated_one():
    class R53:
        def __init__(self, ns):
            self.ns, self.changes = ns, []

        def list_hosted_zones_by_name(self, **kw):
            return {"HostedZones": [{"Id": "/hostedzone/Z1", "Name": "example.com.", "Config": {}}]}

        def get_hosted_zone(self, Id):
            return {"DelegationSet": {"NameServers": self.ns}}

        def change_resource_record_sets(self, **kw):
            self.changes.append(kw)

    recs = [dns.Record("A", "tico.example.com", "1.2.3.4")]
    live = dns.Zone("example.com", tuple(fakes.AWS_NS), dns.detect_provider(fakes.AWS_NS))
    io, d = CaptureIO(), fakes.deps()
    good = R53(fakes.AWS_NS)
    d.route53_client = lambda profile: good
    s = wizard.Settings(domain="tico.example.com")
    assert wizard._route53(io, s, d, live, recs) and good.changes[0]["ChangeBatch"]["Changes"][0]["Action"] == "UPSERT"
    # the pilot lesson: a Route 53 zone exists, but Netlify/NS1 is what the internet asks
    elsewhere = dns.Zone("example.com", tuple(fakes.NETLIFY_NS), dns.detect_provider(fakes.NETLIFY_NS))
    stale = R53(["ns-99.awsdns-99.net"])
    d.route53_client = lambda profile: stale
    io2 = CaptureIO()
    assert not wizard._route53(io2, s, d, elsewhere, recs) and not stale.changes and "not using it" in io2.text


def test_cloudflare_tunnel_flow_creates_tunnel_and_uses_its_token(monkeypatch):
    from setup.tests.test_cloudflare import Api
    api = Api({("GET", "/zones?name=tico.example.com"): [],
               ("GET", "/zones?name=example.com"): [{"id": "z1", "name": "example.com", "account": {"id": "a1"}}],
               ("GET", "/accounts/a1/cfd_tunnel?"): [], ("POST", "/accounts/a1/cfd_tunnel"): {"id": "t9", "token": "TUNTOK"},
               ("PUT", "/accounts/a1/cfd_tunnel/t9/configurations"): {},
               ("GET", "/zones/z1/dns_records?"): [], ("POST", "/zones/z1/dns_records"): {}})
    monkeypatch.setenv("CLOUDFLARE_API_TOKEN", "cf-secret-token")
    shell = FakeShell()
    r = fakes.FakeResolver({("tico.example.com", dns.A): ["104.16.0.1"]}, {"example.com": ["a.ns.cloudflare.com"]})
    d = fakes.deps()
    d.resolver, d.public_resolvers, d.ssh_shell = r, (lambda: [("G", r)]), (lambda *a: shell)
    d.cloudflare = lambda tok: __import__("setup.cloudflare", fromlist=["x"]).Cloudflare(tok, api)
    code, out = go(["--target", "ssh", "--ssh", "root@h", "--front-door", "cloudflared", "--yes", *BASE], deps=d)
    assert code == 0, out
    env = next(i for c, i in shell.calls if i and b"TICO_DOMAIN" in i).decode()
    assert "CLOUDFLARE_TUNNEL_TOKEN=TUNTOK" in env and "COMPOSE_PROFILES=cloudflared,updater" in env
    assert "cf-secret-token" not in out and "TUNTOK" not in out and "cf-secret-token" not in env
    assert any(m == "POST" and p == "/zones/z1/dns_records" and b["content"] == "t9.cfargotunnel.com" for m, p, b in api.calls)


def test_tunnel_id_from_token():
    import base64
    tok = base64.b64encode(json.dumps({"a": "acct", "t": "tun-1", "s": "x"}).encode()).decode()
    assert wizard.tunnel_id_from_token(tok) == "tun-1" and wizard.tunnel_id_from_token("garbage") == ""


def test_command_target_writes_a_private_file_and_prints_no_secret():
    code, out = go(["--target", "command", "--server-ip", "203.0.113.7", "--yes", "--skip-dns-wait", *BASE])
    assert code == 0 and SECRET not in out and "install-command.txt" in out
    import os
    f = state.home() / "tico.example.com" / "install-command.txt"
    assert oct(os.stat(f).st_mode & 0o777) == "0o600" and "\n" not in f.read_text().strip()


def test_destroy_dry_run_and_confirmation():
    ec2, iam, ssm, factory = aws_clients(fakes.FakeEC2(extra_instances=[{"InstanceId": "i-mine", "Tags": [
        {"Key": "ManagedBy", "Value": "tico-setup"}, {"Key": "tico-setup-name", "Value": "tico-example-com"}]}]))
    d = fakes.deps()
    d.aws_clients = factory
    code, out = go(["destroy", "--domain", "tico.example.com", "--dry-run"], deps=d)
    assert code == 0 and "instance: i-mine" in out and not ec2.called("terminate_instances")
    code, out = go(["destroy", "--domain", "tico.example.com"], deps=d)  # non-interactive without --yes
    assert code == 1 and not ec2.called("terminate_instances")
    code, out = go(["destroy", "--domain", "tico.example.com", "--yes"], deps=d)
    assert code == 0 and ec2.called("terminate_instances")
