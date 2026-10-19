"""Visuals in replies, on the bot's own computer (Dev 245): before a visual page or SVG is uploaded, the images and
fonts it refers to from its own folder are embedded as data: URIs, so it still shows when those files move.

Only files inside the bot's checkout are read, with the same checks as a published file (clients/bot_files.py
local_file: no leaving the checkout, no symbolic links, no credential-like names). Remote addresses are never
fetched: they are listed, and the server removes them from the stored copy (backend/visuals.py clean)."""
import base64
import mimetypes
import posixpath
import re
from pathlib import Path

from . import bot_files as BF

EMBED_TYPES = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".gif": "image/gif",
               ".webp": "image/webp", ".svg": "image/svg+xml", ".woff": "font/woff", ".woff2": "font/woff2",
               ".ttf": "font/ttf", ".otf": "font/otf"}
PAGE_TYPES = {".html": "text/html", ".htm": "text/html", ".svg": "image/svg+xml"}
MAX_EMBED = 10 * 1024 * 1024
# Where a page names another file: src/href/poster/xlink:href attribute values, srcset entries and CSS url().
ATTRIBUTE = re.compile(r"""(\b(?:src|href|poster|xlink:href)\s*=\s*)(["'])(.*?)\2""", re.I | re.S)
SRCSET = re.compile(r"""(\bsrcset\s*=\s*)(["'])(.*?)\2""", re.I | re.S)
CSS_URL = re.compile(r"""url\(\s*(['"]?)(.*?)\1\s*\)""", re.I | re.S)
REMOTE = re.compile(r"^(?:[a-z][a-z0-9+.\-]*:|//)", re.I)


def is_page(path):
    return Path(str(path)).suffix.lower() in PAGE_TYPES


def embed(root, rel):
    """(bytes, embedded, unembedded) for a page or SVG at `rel` inside `root`: each local image or font it names,
    read through local_file's checks, becomes a data: URI. Remote references and anything that can't be read are
    listed in `unembedded` and left for the server to remove."""
    path, name = BF.local_file(root, rel)
    text = path.read_bytes().decode("utf-8", errors="replace")
    folder = posixpath.dirname(name)
    embedded, unembedded, cache = [], [], {}

    def inline(value):
        raw = value.strip()
        if not raw or raw.startswith(("#", "data:")) or raw.lower().startswith(("data:", "mailto:")):
            return None
        if REMOTE.match(raw):
            if raw not in unembedded:
                unembedded.append(raw)
            return None
        target = raw.split("#", 1)[0].split("?", 1)[0]
        if target in cache:
            return cache[target]
        ext = Path(target).suffix.lower()
        uri = None
        if ext in EMBED_TYPES:
            try:
                local, _ = BF.local_file(root, posixpath.normpath(posixpath.join(folder, target)),
                                         extra_types=tuple(EMBED_TYPES))
                data = local.read_bytes()
                if len(data) <= MAX_EMBED:
                    uri = "data:" + EMBED_TYPES[ext] + ";base64," + base64.b64encode(data).decode()
            except (BF.Refused, OSError):
                uri = None
        cache[target] = uri
        if uri:
            embedded.append(raw)
        elif raw not in unembedded:
            unembedded.append(raw)
        return uri

    def attribute(match):
        uri = inline(match.group(3))
        return match.group(0) if uri is None else match.group(1) + match.group(2) + uri + match.group(2)

    def srcset(match):
        parts = []
        for candidate in match.group(3).split(", "):
            bits = candidate.strip().split(None, 1)
            if bits:
                uri = inline(bits[0])
                parts.append(" ".join([uri or bits[0], *bits[1:]]))
        return match.group(1) + match.group(2) + ", ".join(parts) + match.group(2)

    def css(match):
        uri = inline(match.group(2))
        return match.group(0) if uri is None else "url(" + uri + ")"

    text = CSS_URL.sub(css, SRCSET.sub(srcset, ATTRIBUTE.sub(attribute, text)))
    return text.encode("utf-8"), embedded, unembedded


def guess_type(name):
    return PAGE_TYPES.get(Path(name).suffix.lower()) or mimetypes.guess_type(name)[0] or "application/octet-stream"
