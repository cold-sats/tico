"""scripts/install.sh in real distro containers (ubuntu:24.04, debian:12) with docker and friends stubbed.

The scenarios are in install_scenarios.sh. They install curl and python3 from the distro's own packages, so the
containers need network access; the tests skip when Docker is not available."""
import hashlib
import shutil
import subprocess
import tarfile
import uuid
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "scripts"
sys_path = str(SCRIPTS)


def _builder():
    import importlib.util
    spec = importlib.util.spec_from_file_location("build_install_bundle", SCRIPTS / "build_install_bundle.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


build = _builder()

FAKE_WIZARD = '''import os, pathlib, sys
d = pathlib.Path(os.environ["TICO_INSTALL_DIR"])
with (d / "wizard-args.txt").open("a") as f:
    f.write(" ".join(sys.argv[1:]) + "\\n")
tag = sys.argv[sys.argv.index("--tico-version") + 1]
fd = os.open(d / ".env", os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
os.write(fd, ("TICO_DOMAIN=tico.example.com\\nTICO_OIDC_CLIENT_SECRET=" + os.environ.get("TICO_OIDC_CLIENT_SECRET", "") + "\\nTICO_TAG=" + tag + "\\n").encode())
'''


def release(base: Path, source: Path, version: str, tamper: bool = False) -> None:
    (source / "compose.yaml").write_text(f"# marker {version}\nname: tico\n")
    out = base / "download" / version
    assert build.main(["--version", version, "--output", str(out), "--source", str(source)]) == 0
    if tamper:  # a bundle that no longer matches its SHA256SUMS
        bundle = out / f"tico-bundle-{version}.tar.gz"
        bundle.write_bytes(bundle.read_bytes() + b"x")


@pytest.fixture(scope="module")
def rel(tmp_path_factory):
    base = tmp_path_factory.mktemp("rel")
    src = tmp_path_factory.mktemp("src")
    (src / "scripts").mkdir()
    shutil.copy(SCRIPTS / "install.sh", src / "scripts" / "install.sh")
    (src / "docker").mkdir()
    (src / "docker" / "runner.compose.yaml").write_text("name: tico-runner\n")
    (src / "setup").mkdir()
    (src / "setup" / "__init__.py").write_text("")
    (src / "setup" / "__main__.py").write_text(FAKE_WIZARD)
    for v in ("v0.2.0", "v0.3.0", "v0.9.0"):
        release(base, src, v, tamper=v == "v0.9.0")
    (base / "unpinned").mkdir()
    shutil.copy(SCRIPTS / "install.sh", base / "unpinned" / "install.sh")
    (base / "latest.json").write_text('{"url": "x", "tag_name": "v0.3.0", "name": "v0.3.0"}\n')
    return base


def docker_ready() -> bool:
    if not shutil.which("docker"):
        return False
    return subprocess.run(["docker", "info"], capture_output=True).returncode == 0


@pytest.mark.skipif(not docker_ready(), reason="Docker is not available")
@pytest.mark.parametrize("image", ["ubuntu:24.04", "debian:12"])
def test_installer_scenarios(image, rel):
    name = "tico-install-test-" + uuid.uuid4().hex[:8]
    try:
        r = subprocess.run(
            ["docker", "run", "--name", name, "--rm", "-v", f"{rel}:/rel:ro", "-v", f"{Path(__file__).parent / 'install_scenarios.sh'}:/scen.sh:ro",
             image, "sh", "-c", "apt-get update -qq >/dev/null 2>&1; sh /scen.sh"],
            capture_output=True, text=True, timeout=900)
    finally:
        subprocess.run(["docker", "rm", "-f", name], capture_output=True)
    lines = r.stdout.splitlines()
    failed = [l for l in lines if l.startswith("not ok")]
    assert not failed, "\n".join(failed) + "\n" + r.stderr[-2000:]
    assert lines and lines[-1] == "done", r.stdout[-2000:] + r.stderr[-2000:]
    passed = {l[3:] for l in lines if l.startswith("ok ")}
    for must in ("preflight-memory", "preflight-disk", "preflight-port-80", "fresh-secret-not-echoed", "rerun-env-untouched",
                 "rerun-skips-wizard", "upgrade-keeps-settings", "checksum-mismatch-refused", "checksum-installs-nothing",
                 "unpinned-uses-latest-release", "version-flag-overrides-baked", "older-installer-holds",
                 "mac-team-install-refused", "mac-local-exit", "mac-runner-exit", "mac-docker-not-running"):
        assert must in passed, f"scenario {must} did not run"


def test_bundle_from_the_real_repo_has_what_a_server_needs_and_is_reproducible(tmp_path):
    assert build.main(["--version", "v1.2.3", "--output", str(tmp_path / "a")]) == 0
    assert build.main(["--version", "v1.2.3", "--output", str(tmp_path / "b")]) == 0
    a, b = tmp_path / "a", tmp_path / "b"
    assert (a / "tico-bundle-v1.2.3.tar.gz").read_bytes() == (b / "tico-bundle-v1.2.3.tar.gz").read_bytes()
    with tarfile.open(a / "tico-bundle-v1.2.3.tar.gz") as t:
        names = set(t.getnames())
        assert t.extractfile("VERSION").read() == b"1.2.3\n"
    assert {"compose.yaml", ".env.example", "setup/__main__.py", "setup/cli.py", "scripts/tico-setup", "docker/runner.compose.yaml"} <= names
    assert not [n for n in names if "/tests/" in n or n.endswith((".pyc", ".env")) or n.startswith("/") or ".." in n]
    sums = dict(reversed(l.split("  ")) for l in (a / "SHA256SUMS").read_text().splitlines())
    for f, digest in sums.items():
        assert hashlib.sha256((a / f.strip()).read_bytes()).hexdigest() == digest
    script = (a / "install.sh").read_text()
    assert "TICO_VERSION_BAKED='v1.2.3'" in script and "@TICO_VERSION@" not in script


def test_build_refuses_a_non_release_version_and_a_script_without_the_placeholder(tmp_path):
    assert build.main(["--version", "latest", "--output", str(tmp_path)]) == 2
    with pytest.raises(SystemExit):
        build.bake("nothing to replace", "v1.2.3")


@pytest.mark.skipif(not shutil.which("shellcheck"), reason="shellcheck not installed")
def test_install_sh_is_shellcheck_clean_posix_sh():
    r = subprocess.run(["shellcheck", "-s", "sh", str(SCRIPTS / "install.sh")],
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stdout
