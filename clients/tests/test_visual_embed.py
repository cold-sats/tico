"""Visual replies 1/4 (Dev 245), on the bot's computer: a page's local images and fonts are embedded before upload."""
import argparse
import base64
import os

import pytest

from clients import hubtools, visual_embed
from clients.remotecli import visuals_from_args

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 16


def checkout(tmp_path):
    (tmp_path / "charts").mkdir(parents=True)
    (tmp_path / "charts" / "a.png").write_bytes(PNG)
    (tmp_path / "charts" / "img").mkdir()
    (tmp_path / "charts" / "img" / "b.png").write_bytes(PNG + b"b")
    (tmp_path / "charts" / "f.woff2").write_bytes(b"wOF2font")
    return tmp_path


def test_a_page_with_two_local_images_gets_both_embedded_and_reports_nothing_unembedded(tmp_path):
    """Spec 2, the part that runs where the files are."""
    root = checkout(tmp_path)
    (root / "charts" / "page.html").write_text(
        '<img src="a.png"><div style="background:url(img/b.png)"></div>'
        '<style>@font-face{src:url(f.woff2)}</style>')
    data, embedded, unembedded = visual_embed.embed(root, "charts/page.html")
    assert unembedded == [] and embedded == ["a.png", "img/b.png", "f.woff2"]
    assert b"a.png" not in data and b"img/b.png" not in data
    assert ("data:image/png;base64," + base64.b64encode(PNG).decode()).encode() in data
    assert b"data:font/woff2;base64," in data


def test_remote_and_out_of_checkout_references_are_listed_never_read(tmp_path):
    """Spec 3, local side: remote addresses are not fetched; a path that leaves the checkout or is a link is not read."""
    root = checkout(tmp_path / "repo")
    secret = tmp_path / "outside.png"
    secret.write_bytes(PNG)
    os.symlink(secret, root / "charts" / "linked.png")
    (root / "charts" / "page.html").write_text(
        '<img src="https://img.example/x.png"><img src="../../outside.png"><img src="linked.png">'
        '<img srcset="//cdn.example/y.png 2x">')
    data, embedded, unembedded = visual_embed.embed(root, "charts/page.html")
    assert embedded == []
    assert unembedded == ["https://img.example/x.png", "../../outside.png", "linked.png", "//cdn.example/y.png"]
    assert base64.b64encode(PNG).decode().encode() not in data


def test_visual_flags_pair_titles_in_order_and_tell_a_tico_file_from_a_path(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "chart.png").write_bytes(PNG)
    args = argparse.Namespace(visual=["chart.png", "file-abc@2"], visual_title=["Signups", "Funnel"])
    assert visuals_from_args(args) == [{"path": "chart.png", "title": "Signups"},
                                       {"file": "file-abc@2", "title": "Funnel"}]
    with pytest.raises(Exception):
        visuals_from_args(argparse.Namespace(visual=["chart.png"], visual_title=["a", "b"]))


def test_a_server_side_tool_never_reads_a_local_path():
    """The in-process MCP server has no checkout: a path is refused there, a file already in Tico is fine."""
    class ServerApi:
        def post(self, *a, **k):
            raise AssertionError("nothing is uploaded")
    with pytest.raises(ValueError):
        hubtools._visuals(ServerApi(), [{"path": "/etc/passwd"}], lambda *a: None)
    assert hubtools._visuals(ServerApi(), [{"file": "f@1", "title": "T"}], lambda *a: None) == \
        ([{"ref": "f@1", "title": "T"}], [])
