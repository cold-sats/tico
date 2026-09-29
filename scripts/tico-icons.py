#!/usr/bin/env python3
"""Export Tico's transparent SVG for the web, Slack, and native Mac app.

Requires rsvg-convert (Homebrew: librsvg). The menu bar uses eye cutouts
instead of colored eyes so AppKit can tint the entire icon as a template.
"""
from pathlib import Path
import subprocess
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parent.parent
ASSETS = ROOT / "ui/assets"
TICO = ASSETS / "tico"
SOURCE = TICO / "tico.svg"
ET.register_namespace("", "http://www.w3.org/2000/svg")
tree = ET.parse(SOURCE)
svg = tree.getroot()
teal = next(group for group in svg if group.get("id") == "teal")
# These two colored paths sit inside matching holes in the charcoal face.
eyes = list(teal)[1:3]
assert [eye.get("transform") for eye in eyes] == [
    "translate(526,511)", "translate(880.662109375,516.748046875)"
], "Source geometry changed: identify the eye paths before exporting."
for eye in eyes:
    teal.remove(eye)
for group in svg:
    if group.get("fill"):
        group.set("fill", "#000000")
# Trim excess canvas space so the mark is legible in an 18-point menu item.
svg.set("viewBox", "140 140 980 980")
template = TICO / "tico-menubar.svg"
tree.write(template, encoding="unicode")
for group in svg:
    if group.get("fill"):
        group.set("fill", "#2f3437")
monochrome = TICO / "tico-monochrome.svg"
tree.write(monochrome, encoding="unicode")


# App icons get an opaque teal tile with the mark in white: iOS and the Dock put a transparent
# icon on black, where the charcoal mark disappeared. The web tile is
# full-bleed (iOS rounds it); the Mac tile is Apple's inset rounded square on a clear canvas.
def tile(output, inset):
    for group in svg:
        if group.get("fill"):
            group.set("fill", "#f4f6f5")
    box = 980
    pad, radius = box * inset, box * (1 - 2 * inset) * 0.2237 if inset else 0   # iOS masks the full-bleed tile itself
    mark = ET.tostring(svg, encoding="unicode").split(">", 1)[1].rsplit("</svg>", 1)[0]
    scale = 1 - 2 * inset - 0.12
    shift = 140 + box * (inset + 0.06)
    output.write_text(
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="140 140 {box} {box}">'
        f'<rect x="{140 + pad}" y="{140 + pad}" width="{box - 2 * pad}" height="{box - 2 * pad}" rx="{radius}" fill="#0f6e56"/>'
        f'<g transform="translate({shift} {shift}) scale({scale}) translate(-140 -140)">{mark}</g></svg>')
    return output


web_tile = tile(TICO / "tico-tile.svg", 0)
mac_tile = tile(TICO / "tico-tile-mac.svg", 0.1)
for source, output, size in [
    (mac_tile, TICO / "tico-1024.png", 1024),
    (monochrome, TICO / "tico-slack.png", 512),
    (web_tile, ASSETS / "icon-192.png", 192),
    (web_tile, ASSETS / "icon-512.png", 512),
    (template, TICO / "tico-menubar.png", 54),
]:
    subprocess.run([
        "rsvg-convert", "--width", str(size), "--height", str(size),
        "--output", str(output), str(source)
    ], check=True)
    print(output.relative_to(ROOT))
