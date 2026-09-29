"""The UI's icon font is a subset: an icon missing from it renders as its raw name."""
import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location("build_icon_font", ROOT / "scripts" / "build-icon-font.py")
build = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(build)


def test_every_icon_in_use_is_in_the_font_manifest():
    used = set(build.used_icons())
    listed = set(build.read_manifest())
    assert used, "the scanner found no icons; it has drifted from how the UI renders them"
    assert not used - listed, "icons used but not in the font; run scripts/build-icon-font.py: %s" % sorted(used - listed)
    assert not listed - used, "icons.txt lists icons nothing uses; run scripts/build-icon-font.py: %s" % sorted(listed - used)


def test_font_file_is_a_woff2():
    assert build.FONT.read_bytes()[:4] == b"wOF2"
