import shutil
import subprocess

import pytest
import yaml

from setup import cloudinit, envfile
from setup.settings import Settings

TEMPLATES = ["tico-server.yaml", "tico-runner.yaml"]


def load(name):
    return yaml.safe_load((cloudinit.TEMPLATE_DIR / name).read_text())


def files(doc):
    return {f["path"]: f for f in doc["write_files"]}


def script(doc, path):
    return files(doc)[path]["content"]


def settings(**kw):
    base = dict(domain="tico.example.com", company="Acme Inc", owner_email="me@example.com", auth="google", client_id="cid",
                client_secret="S3CRET$x", front_door="caddy")
    return Settings(**{**base, **kw})


@pytest.mark.parametrize("name", TEMPLATES)
def test_templates_are_cloud_config_with_private_inputs_and_a_bootstrap(name):
    text = (cloudinit.TEMPLATE_DIR / name).read_text()
    assert text.startswith("#cloud-config\n")
    doc = yaml.safe_load(text)
    f = files(doc)
    inputs = next(p for p in f if p.startswith("/etc/tico/") and p.endswith(".env"))
    assert f[inputs]["permissions"] == "0600"
    boot = next(p for p in f if "bootstrap" in p)
    assert f[boot]["permissions"] == "0700" and f[boot]["content"].startswith("#!/bin/bash\n") and "\nset -euo pipefail\n" in f[boot]["content"]
    assert doc["runcmd"] == [[boot]]
    assert cloudinit.BEGIN in f[inputs]["content"] and cloudinit.END in f[inputs]["content"]


@pytest.mark.skipif(not shutil.which("cloud-init"), reason="cloud-init not installed (CI runs this in an Ubuntu container)")
@pytest.mark.parametrize("name", TEMPLATES)
def test_cloud_init_schema_accepts_the_templates(name):
    r = subprocess.run(["cloud-init", "schema", "-c", str(cloudinit.TEMPLATE_DIR / name)], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr + r.stdout


@pytest.mark.skipif(not shutil.which("shellcheck"), reason="shellcheck not installed")
@pytest.mark.parametrize("name,path", [("tico-server.yaml", "/usr/local/sbin/tico-bootstrap"),
                                       ("tico-runner.yaml", "/usr/local/sbin/tico-runner-bootstrap")])
def test_bootstrap_scripts_pass_shellcheck(name, path, tmp_path):
    p = tmp_path / "s.sh"
    p.write_text(script(load(name), path))
    r = subprocess.run(["shellcheck", "-s", "bash", "-S", "warning", str(p)], capture_output=True, text=True)
    assert r.returncode == 0, r.stdout


def test_server_render_puts_the_env_in_the_inputs_block_and_stays_valid_yaml():
    s = settings()
    text = cloudinit.server_user_data(s.to_env(), version="v1.2.3", server_ip="203.0.113.7", allow_ssh=True)
    doc = yaml.safe_load(text)
    env = envfile.parse(files(doc)["/etc/tico/tico.env"]["content"])
    assert env["TICO_CLOUD_VERSION"] == "v1.2.3" and env["TICO_CLOUD_SERVER_IP"] == "203.0.113.7" and env["TICO_CLOUD_ALLOW_SSH"] == "1"
    assert env["TICO_DOMAIN"] == "tico.example.com" and env["COMPOSE_PROFILES"] == "caddy,updater"
    assert env["TICO_COMPANY_NAME"] == "Acme Inc" and env["TICO_OIDC_CLIENT_SECRET"] == "S3CRET$x"
    assert "TICO_TAG" not in env  # the bootstrap pins it to the version
    assert "you@example.com" not in text  # the template's example values are all replaced
    assert files(doc)["/usr/local/sbin/tico-bootstrap"]["content"] == script(load("tico-server.yaml"), "/usr/local/sbin/tico-bootstrap")


def test_server_render_cloudflared_and_no_ssh():
    s = settings(front_door="cloudflared", tunnel_token="tok-abcdef", auth="cloudflare", access_issuer="https://t.cloudflareaccess.com",
                 access_audience="aud")
    doc = yaml.safe_load(cloudinit.server_user_data(s.to_env(), version="v1.2.3-rc.1"))
    env = envfile.parse(files(doc)["/etc/tico/tico.env"]["content"])
    assert env["COMPOSE_PROFILES"] == "cloudflared,updater" and env["CLOUDFLARE_TUNNEL_TOKEN"] == "tok-abcdef"
    assert env["TICO_CLOUD_ALLOW_SSH"] == "0" and "TICO_CLOUD_SERVER_IP" not in env


@pytest.mark.parametrize("bad", ["latest", "main", "1.2.3", "v1.2", "v1.2.3; rm -rf /", "v1.2.3\n"])
def test_a_version_must_be_a_pinned_release(bad):
    with pytest.raises(ValueError):
        cloudinit.server_user_data(settings().to_env(), version=bad)
    with pytest.raises(ValueError):
        cloudinit.runner_user_data(url="https://t.example.com", code="c", label="l", version=bad)


def test_runner_render_has_the_join_inputs_and_no_inbound_by_default():
    doc = yaml.safe_load(cloudinit.runner_user_data(url="https://tico.example.com", code="abc-123", label="Build box", version="v1.2.3"))
    env = envfile.parse(files(doc)["/etc/tico/runner.env"]["content"])
    assert env == {"TICO_CLOUD_VERSION": "v1.2.3", "TICO_CLOUD_ALLOW_SSH": "0", "TICO_URL": "https://tico.example.com",
                   "TICO_CODE": "abc-123", "TICO_RUNNER_LABEL": "Build box"}
    body = script(doc, "/usr/local/sbin/tico-runner-bootstrap")
    assert "ufw default deny incoming" in body and "allow 80" not in body and "allow 443" not in body


def test_server_script_opens_only_web_ports_and_never_prints_the_inputs():
    body = script(load("tico-server.yaml"), "/usr/local/sbin/tico-bootstrap")
    assert "ufw allow 80/tcp" in body and "ufw allow 443/tcp" in body and "ufw default deny incoming" in body
    assert "set -x" not in body and "cat \"$IN\"" not in body and "echo \"$IN\"" not in body
    assert body.index("rm -f \"$IN\"") > body.index("\"$installer\" --yes")  # inputs are removed only after the installer started the stack
    assert "$D/.env\" ]; then" in body  # an existing .env (with the updater's TICO_TAG) is never overwritten


@pytest.mark.parametrize("name,path", [("tico-server.yaml", "/usr/local/sbin/tico-bootstrap"),
                                       ("tico-runner.yaml", "/usr/local/sbin/tico-runner-bootstrap")])
def test_bootstraps_reuse_the_release_installer_instead_of_their_own_docker_logic(name, path):
    body = script(load(name), path)
    assert "releases/download/$version/install.sh" in body
    assert "get.docker.com" not in body and "docker compose pull" not in body


def test_runner_bootstrap_uses_install_sh_runner_pinned_to_the_release_so_it_gets_the_updater():
    body = script(load("tico-runner.yaml"), "/usr/local/sbin/tico-runner-bootstrap")
    assert 'sh "$installer" --runner --url "$url" --code "$code" --label "$label"' in body
    assert "releases/download/$version/install.sh" in body
    assert "docker run" not in body and "--docker-only" not in body


def test_bootstrap_rejects_the_unedited_placeholder_version(tmp_path):
    """Runs the real script far enough to see it refuse v0.0.0 before touching the machine."""
    doc = load("tico-server.yaml")
    inputs = tmp_path / "in.env"
    inputs.write_text(files(doc)["/etc/tico/tico.env"]["content"])
    body = script(doc, "/usr/local/sbin/tico-bootstrap").replace("/etc/tico/tico.env", str(inputs)).replace(
        ">>/var/log/tico-setup.log", f">>{tmp_path}/log").replace("D=/opt/tico", f"D={tmp_path}/opt")
    r = subprocess.run(["bash", "-c", body], capture_output=True, text=True)
    assert r.returncode == 1 and "must be a release" in (tmp_path / "log").read_text()
    assert not (tmp_path / "opt").exists()
