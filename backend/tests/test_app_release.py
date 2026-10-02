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
