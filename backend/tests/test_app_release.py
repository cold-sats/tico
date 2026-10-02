"""The public updater manifest must point at signed assets from its own release."""
import json
import subprocess
import sys
from pathlib import Path

import pytest

from scripts.app_release import classify, manifest

ROOT = Path(__file__).resolve().parents[2]


def test_github_cli_writes_a_complete_tauri_manifest(tmp_path):
    names = ["Tico_1.2.3_universal.dmg", "Tico.app.tar.gz", "Tico_1.2.3_x64-setup.exe", "Tico_1.2.3_amd64.AppImage", "Tico_1.2.3_amd64.deb"]
    for name in names:
        (tmp_path / name).write_bytes(b"bundle")
        if name.endswith((".app.tar.gz", "-setup.exe", ".AppImage")):
            (tmp_path / (name + ".sig")).write_text("update-signature")
    output = tmp_path / "latest.json"
    subprocess.run([sys.executable, str(ROOT / "scripts/app_release.py"), "--github", "--version", "1.2.3-rc.1",
                    "--tag", "v1.2.3-rc.1", "--output", str(output), str(tmp_path)], check=True, capture_output=True)
    value = json.loads(output.read_text())
    assert value["version"] == "1.2.3-rc.1"
    assert value["pub_date"].endswith("Z")
    assert set(value["platforms"]) == {"darwin-aarch64", "darwin-x86_64", "windows-x86_64", "linux-x86_64"}
    for entry in value["platforms"].values():
        assert entry["signature"] == "update-signature"
        assert entry["url"].startswith("https://github.com/ticoteam/tico/releases/download/v1.2.3-rc.1/")
    assert value["platforms"]["darwin-aarch64"] == value["platforms"]["darwin-x86_64"]
    assert set(value["installers"]) == {"mac", "windows", "linux", "linux_deb"}
    (tmp_path / "Tico.app.tar.gz.sig").unlink()
    with pytest.raises(SystemExit, match="has no .sig"):
        manifest("1.2.3", "", [classify(tmp_path)], None, github=True)


def test_company_s3_publish_with_prefix_and_quiet_output(tmp_path, monkeypatch, capsys):
    import boto3
    from scripts.app_release import main
    calls = []
    class S3:
        def get_object(self, **kw):
            raise KeyError("missing")
        def upload_file(self, source, bucket, key):
            calls.append(("file", bucket, key))
        def put_object(self, **kw):
            calls.append(("manifest", kw))
    monkeypatch.setattr(boto3, "client", lambda name: S3())
    for name in ("Acme Tico.app.tar.gz", "Acme Tico.dmg", "Acme Tico-setup.exe", "Acme Tico.AppImage", "Acme Tico.deb"):
        (tmp_path / name).write_bytes(b"bundle")
        if name.endswith((".app.tar.gz", "-setup.exe", ".AppImage")):
            (tmp_path / (name + ".sig")).write_text("signature")
    assert main(["--version", "1.2.3", "--bucket", "acme-files", "--base", "https://runner.example.com",
                 "--prefix", "team", "--complete", "--quiet", str(tmp_path)]) == 0
    assert capsys.readouterr().out == ""
    assert calls[-1][0] == "manifest"
    value = json.loads(calls[-1][1]["Body"])
    assert value["app_kind"] == "company"
    assert value["platforms"]["darwin-aarch64"]["url"].endswith("/Acme%20Tico.app.tar.gz")
    assert calls[-1][1]["Key"] == "team/releases/app/latest.json"
    assert all(call[2].startswith("team/releases/app/1.2.3/") for call in calls[:-1])
    calls.clear()
    (tmp_path / "Acme Tico.app.tar.gz.sig").unlink()
    with pytest.raises(SystemExit):
        main(["--version", "1.2.3", "--bucket", "acme-files", "--base", "https://runner.example.com",
              "--complete", "--quiet", str(tmp_path)])
    assert not calls


def test_apple_signing_flags_do_not_claim_windows_or_linux_code_signing(tmp_path):
    for name in ("Tico.dmg", "Tico-setup.exe", "Tico.AppImage"):
        (tmp_path / name).write_bytes(b"bundle")
        if name != "Tico.dmg":
            (tmp_path / (name + ".sig")).write_text("signature")
    value = manifest("1.2.3", "https://runner.example.com", [classify(tmp_path)], None, signed=True, notarized=True)
    assert value["installers"]["mac"]["signed"] and value["installers"]["mac"]["notarized"]
    assert all(not entry["signed"] and not entry["notarized"] for os_name, entry in value["installers"].items() if os_name != "mac")
