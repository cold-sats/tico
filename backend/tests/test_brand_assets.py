"""Every image the page, the manifest and the desktop app name exists, and none is the retired robot."""
import json
import re

from backend.config import ROOT

UI = ROOT / "ui"


def test_the_icons_the_page_manifest_and_desktop_app_name_exist():
    page = (UI / "index.html").read_text()
    head = page[:page.index("</head>")]
    wanted = [UI / m.lstrip("/") for m in re.findall(r'<link rel="(?:icon|apple-touch-icon)"[^>]*href="([^"]+)"', head)]
    wanted += [UI / i["src"].lstrip("/") for i in json.loads((UI / "manifest.webmanifest").read_text())["icons"]]
    wanted += [ROOT / "app" / i for i in json.loads((ROOT / "app/tauri.conf.json").read_text())["bundle"]["icon"]]
    wanted += [ROOT / "app/icons/tray.png"] + [UI / "assets/tico" / n for n in (
        "tico-mark.svg", "tico-glyph.svg", "tico-wordmark.svg", "tico-wordmark-reversed.svg")]
    assert len(wanted) >= 12 and [str(p) for p in wanted if not p.is_file()] == []
    assert any(i["purpose"] == "maskable" for i in json.loads((UI / "manifest.webmanifest").read_text())["icons"])


def test_the_page_uses_the_brand_files_only():
    page = (UI / "index.html").read_text()
    for old in ("tico-tile", "tico-monochrome", "assets/tico/tico.svg", "bowtie"):
        assert old not in page
    assert "assets/tico/tico-glyph.svg" in page and "tico-wordmark-reversed.svg" in page
