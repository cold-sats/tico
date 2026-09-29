"""hcloud / doctl are replaced by a recorder: no test here can create anything."""
import json

import pytest
import yaml

from setup import cli, cloud, verify
from setup.cloud import Cli
from setup.tests import fakes
from setup.tests.fakes import CaptureIO

SECRET = "GOCSPX-supersecret"
BASE = ["--non-interactive", "--yes", "--domain", "tico.example.com", "--auth", "google", "--client-id", "cid.apps.googleusercontent.com",
        "--company", "Acme", "--owner-email", "me@example.com", "--tico-version", "v1.2.3", "--skip-dns-wait"]


class FakeCli:
    """Answers by argv prefix; remembers argv and the user-data file the CLI was pointed at."""

    def __init__(self, replies=None):
        self.replies, self.calls, self.user_data, self.rules = replies or {}, [], None, None
        self.mode = None

    def __call__(self, argv):
        self.calls.append(argv)
        for flag in ("--user-data-from-file", "--user-data-file"):
            if flag in argv:
                import os
                path = argv[argv.index(flag) + 1]
                self.user_data, self.mode = open(path).read(), os.stat(path).st_mode & 0o777
        if "--rules-file" in argv:
            self.rules = json.load(open(argv[argv.index("--rules-file") + 1]))
        best = max((k for k in self.replies if argv[:len(k)] == list(k)), key=len, default=None)
        return self.replies[best] if best else Cli(0, "")

    def verbs(self):
        return [" ".join(a[:3]) for a in self.calls]


def hz(over=None):
    r = {("hcloud", "server", "describe"): Cli(1, "", "not found"), ("hcloud", "primary-ip", "describe"): Cli(1, "", "not found"),
         ("hcloud", "firewall", "describe"): Cli(1, "", "not found"),
         ("hcloud", "primary-ip", "create"): Cli(0, json.dumps({"primary_ip": {"id": 7, "ip": "203.0.113.9"}})),
         ("hcloud", "server", "create"): Cli(0, json.dumps({"server": {"id": 42, "public_net": {"ipv4": {"ip": "203.0.113.9"}}},
                                                            "root_password": "ROOTPW-leak"})),
         ("hcloud", "ssh-key", "list"): Cli(0, "laptop\n")}
    r.update(over or {})
    return FakeCli(r)


def do(over=None):
    r = {("doctl", "compute", "droplet", "list"): Cli(0, ""), ("doctl", "compute", "firewall", "list"): Cli(0, ""),
         ("doctl", "compute", "reserved-ip", "create"): Cli(0, "198.51.100.5\n"),
         ("doctl", "compute", "droplet", "create"): Cli(0, "999 192.0.2.44\n"),
         ("doctl", "compute", "ssh-key", "list"): Cli(0, "123\n")}
    r.update(over or {})
    return FakeCli(r)


@pytest.fixture(autouse=True)
def env(monkeypatch):
    monkeypatch.setenv("TICO_OIDC_CLIENT_SECRET", SECRET)
    monkeypatch.setattr(verify, "check_health", lambda d: verify.Check("h", True, "ok"))
    monkeypatch.setattr(verify, "run_all", lambda **kw: [verify.Check("stub", True, "ok")])


def go(argv, fake, installed=True, **kw):
    d = fakes.deps(cloud_cli=fake, which=lambda c: f"/usr/bin/{c}" if installed else None, **kw)
    io = CaptureIO()
    code = cli.main(argv, deps=d, io=io)
    return code, io.text


def test_cloud_flag_is_the_target_and_dry_run_prints_size_price_and_firewall():
    for cloud_name, want in (("hetzner", ["cax11", "EUR 5.99", "Primary IP", "inbound 80, 443"]),
                             ("digitalocean", ["s-1vcpu-2gb", "$12/month", "Reserved IP"])):
        code, out = go(["--dry-run", "--cloud", cloud_name, *BASE], FakeCli())
        assert code == 0, out
        assert all(w in out for w in want) and "<reserved-ip>" in out and SECRET not in out


def test_hetzner_creates_ip_firewall_then_server_with_the_right_argv_and_private_user_data():
    f = hz()
    code, out = go(["--cloud", "hetzner", *BASE], f)
    assert code == 0, out
    assert f.verbs() == ["hcloud location list", "hcloud ssh-key list", "hcloud server describe", "hcloud primary-ip describe",
                         "hcloud primary-ip create", "hcloud firewall describe", "hcloud firewall create", "hcloud server create"]
    n = "tico-tico-example-com"
    create = next(a for a in f.calls if a[:3] == ["hcloud", "server", "create"])
    for pair in (["--name", n], ["--type", "cax11"], ["--image", "ubuntu-24.04"], ["--location", "nbg1"], ["--primary-ipv4", n],
                 ["--firewall", n], ["--ssh-key", "laptop"], ["--label", "ManagedBy=tico-setup"], ["--label", f"tico-setup-name={n}"]):
        i = create.index(pair[0])
        assert create[i:i + 2] == pair or pair in [create[j:j + 2] for j in range(len(create) - 1)], pair
    ip_create = next(a for a in f.calls if a[:3] == ["hcloud", "primary-ip", "create"])
    assert "--auto-delete=false" in ip_create and ip_create[ip_create.index("--type") + 1] == "ipv4"
    assert {(r["protocol"], r["port"]) for r in f.rules} == {("tcp", "22"), ("tcp", "80"), ("tcp", "443"), ("udp", "443")}
    assert f.mode == 0o600
    env = yaml.safe_load(f.user_data)["write_files"][0]["content"]
    assert "TICO_CLOUD_SERVER_IP=203.0.113.9" in env and "TICO_CLOUD_VERSION=v1.2.3" in env and "TICO_CLOUD_ALLOW_SSH=1" in env
    assert not any(SECRET in " ".join(a) for a in f.calls)  # secrets travel in the file, never in argv
    assert SECRET not in out and "ROOTPW-leak" not in out
    assert "A tico.example.com 203.0.113.9" in out or "203.0.113.9" in out


def test_hetzner_without_an_ssh_key_opens_no_port_22():
    f = hz({("hcloud", "ssh-key", "list"): Cli(0, "")})
    code, out = go(["--cloud", "hetzner", *BASE], f)
    assert code == 0 and "--ssh-key" not in next(a for a in f.calls if a[:3] == ["hcloud", "server", "create"])
    assert {r["port"] for r in f.rules} == {"80", "443"} and "TICO_CLOUD_ALLOW_SSH=0" in f.user_data
    assert "no SSH access" in out


def test_hetzner_cloudflared_needs_no_ip_and_only_ssh_inbound(monkeypatch):
    import base64
    monkeypatch.setenv("CLOUDFLARE_TUNNEL_TOKEN", base64.b64encode(json.dumps({"a": "acct", "t": "tun-1", "s": "sec"}).encode()).decode())
    f = hz()
    args = ["--non-interactive", "--yes", "--domain", "tico.example.com", "--front-door", "cloudflared", "--auth", "cloudflare",
            "--access-issuer", "https://t.cloudflareaccess.com", "--access-audience", "aud", "--company", "Acme",
            "--owner-email", "me@example.com", "--tico-version", "v1.2.3", "--skip-dns-wait"]
    code, out = go(["--cloud", "hetzner", *args], f)
    assert code == 0, out
    assert not any(a[:3] == ["hcloud", "primary-ip", "create"] for a in f.calls)
    assert "--primary-ipv4" not in next(a for a in f.calls if a[:3] == ["hcloud", "server", "create"])
    assert [r["port"] for r in f.rules] == ["22"] and "COMPOSE_PROFILES=cloudflared,updater" in f.user_data


def test_existing_server_is_reused_not_created_twice():
    f = hz({("hcloud", "server", "describe"): Cli(0, json.dumps({"id": 42, "public_net": {"ipv4": {"ip": "203.0.113.9"}}}))})
    code, out = go(["--cloud", "hetzner", *BASE], f)
    assert code == 0 and "already exists" in out and not any(a[:3] == ["hcloud", "server", "create"] for a in f.calls)


def test_hetzner_create_failure_is_scrubbed_and_stops():
    f = hz({("hcloud", "server", "create"): Cli(1, "", f"invalid input in field 'user_data' {SECRET}")})
    code, out = go(["--cloud", "hetzner", *BASE], f)
    assert code == 1 and "Creating the server failed" in out and "invalid input" in out and SECRET not in out
    assert "reused" in out


def test_not_signed_in_prints_login_and_manual_steps_and_creates_nothing():
    f = hz({("hcloud", "location", "list"): Cli(1, "", "no active context")})
    code, out = go(["--cloud", "hetzner", *BASE], f)
    assert code == 2 and "not signed in" in out and "hcloud context create" in out and "Cloud config: paste" in out
    assert f.verbs() == ["hcloud location list"]


@pytest.mark.parametrize("target,want", [("hetzner", ["Cloud config: paste the whole contents", "hcloud server create"]),
                                         ("digitalocean", ["no link that pre-fills", "Add Initialization scripts", "doctl compute droplet create"])])
def test_missing_cli_prints_exact_steps_and_writes_a_private_cloud_init(target, want, tmp_path):
    f = FakeCli()
    code, out = go(["--cloud", target, *BASE], f, installed=False)
    assert code == 0 and f.calls == []
    assert all(w in out for w in want) and "is not installed" in out and SECRET not in out
    p = tmp_path / "home" / "tico.example.com" / "user-data.yaml"
    assert p.exists() and p.stat().st_mode & 0o777 == 0o600 and SECRET in p.read_text()
    assert str(p) in out and "TICO_CLOUD_VERSION=v1.2.3" in p.read_text()


def test_digitalocean_reserves_ip_firewall_droplet_then_assigns():
    f = do()
    code, out = go(["--cloud", "digitalocean", *BASE], f)
    assert code == 0, out
    assert f.verbs() == ["doctl account get", "doctl compute ssh-key", "doctl compute droplet", "doctl compute reserved-ip",
                         "doctl compute firewall", "doctl compute firewall", "doctl compute droplet", "doctl compute reserved-ip-action"]
    n = "tico-tico-example-com"
    create = next(a for a in f.calls if a[:4] == ["doctl", "compute", "droplet", "create"])
    assert create[4] == n
    for pair in (["--size", "s-1vcpu-2gb"], ["--region", "nyc3"], ["--image", "ubuntu-24-04-x64"], ["--ssh-keys", "123"],
                 ["--tag-names", f"tico-setup,{n}"]):
        assert create[create.index(pair[0]):][:2] == pair
    assert "--wait" in create
    fw = next(a for a in f.calls if a[:4] == ["doctl", "compute", "firewall", "create"])
    inbound = fw[fw.index("--inbound-rules") + 1]
    assert "protocol:tcp,ports:80" in inbound and "protocol:tcp,ports:443" in inbound and "protocol:udp,ports:443" in inbound
    assert fw[fw.index("--tag-names") + 1] == n
    assign = f.calls[-1]
    assert assign[-3:] == ["assign", "198.51.100.5", "999"] and "TICO_CLOUD_SERVER_IP=198.51.100.5" in f.user_data
    assert f.mode == 0o600 and not any(SECRET in " ".join(a) for a in f.calls) and SECRET not in out


def test_digitalocean_failure_names_the_unassigned_reserved_ip():
    f = do({("doctl", "compute", "droplet", "create"): Cli(1, "", "Error: 422 size not available")})
    code, out = go(["--cloud", "digitalocean", *BASE], f)
    assert code == 1 and "size not available" in out and "198.51.100.5" in out and "reserved-ip delete" in out


def test_digitalocean_not_signed_in():
    f = do({("doctl", "account", "get"): Cli(1, "", "Error: unable to initialize DigitalOcean API client")})
    code, out = go(["--cloud", "digitalocean", *BASE], f)
    assert code == 2 and "doctl auth init" in out and len(f.calls) == 1


def test_latest_release_lookup_is_used_only_when_no_version_is_given():
    args = [a for a in BASE if a not in ("--tico-version", "v1.2.3")]
    f = hz()
    code, _ = go(["--cloud", "hetzner", *args], f, latest_release=lambda: "v9.9.9")
    assert code == 0 and "TICO_CLOUD_VERSION=v9.9.9" in f.user_data
    code, out = go(["--cloud", "hetzner", *args[:3], "other.example.com", *args[4:]], hz(), latest_release=lambda: "")
    assert code == 2 and "--tico-version" in out


def test_state_is_saved_without_secrets(tmp_path):
    go(["--cloud", "hetzner", *BASE], hz())
    saved = (tmp_path / "home" / "tico.example.com" / "state.json").read_text()
    assert SECRET not in saved and '"target": "hetzner"' in saved and "203.0.113.9" in saved
    code, out = go(["destroy", "--domain", "tico.example.com"], FakeCli())
    assert code == 0 and "hcloud server delete tico-tico-example-com" in out


def test_find_ip_reads_nested_json_and_ignores_ipv6():
    assert cloud.find_ip({"server": {"public_net": {"ipv6": {"ip": "2001:db8::/64"}, "ipv4": {"ip": "203.0.113.1"}}}}) == "203.0.113.1"
    assert cloud.find_ip({"x": [{"ip": "nope"}]}) == ""


def test_the_runner_wizard_does_not_offer_cloud_targets():
    from setup import runner_setup
    assert set(runner_setup.TARGETS) == {"ssh", "aws", "command"}
