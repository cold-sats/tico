import io

import pytest
from PIL import Image

from backend.tests.test_api import api, headers, setup_attempt  # noqa: F401


def image(kind="PNG", colour="red"):
    out = io.BytesIO()
    Image.new("RGB", (16, 16), colour).save(out, kind)
    return out.getvalue()


def test_icon_owner_rights_public_png_cache_and_replacement(api):
    assert api.get("/api/v2/team/icon").status_code == 404
    for token in ("ben-test", "cara-test"):
        assert api.post("/api/v2/team/icon", content=image(), headers=headers(token)).status_code == 403
    _, _, attempt = setup_attempt(api, "coo")
    assert api.post("/api/v2/team/icon", content=image(), headers=headers(attempt["token"])).status_code == 403
    assert api.post("/api/v2/team/icon", content=image(), headers=headers()).json()["url"] == "/api/v2/team/icon"
    first = api.get("/api/v2/team/icon")
    assert first.headers["content-type"] == "image/png"
    assert first.headers["cache-control"] == "public, max-age=300"
    assert api.get("/api/v2/team/icon", headers={"If-None-Match": first.headers["etag"]}).status_code == 304
    for kind in ("JPEG", "WEBP"):
        assert api.post("/api/v2/team/icon", content=image(kind, "blue"), headers=headers()).status_code == 200
    assert api.get("/api/v2/team/icon").headers["etag"] != first.headers["etag"]
    with api.app.state.store.read() as c:
        assert c.execute("SELECT count(*) FROM blobs WHERE name='team-icon.png'").fetchone()[0] == 1
    assert len([p for p in api.app.state.blobs.directory.rglob("*") if p.is_file()]) == 1


@pytest.mark.parametrize("data,status", [(b"bad", 422), (image("GIF"), 422), (b"x" * (1024 * 1024 + 1), 413)])
def test_icon_rejects_size_and_format(api, data, status):
    assert api.post("/api/v2/team/icon", content=data, headers=headers()).status_code == status


def test_failed_old_icon_cleanup_preserves_current_logo_and_retry_finishes(api, monkeypatch):
    from pathlib import Path
    assert api.post("/api/v2/team/icon", content=image(), headers=headers()).status_code == 200
    first = api.get("/api/v2/team/icon")
    unlink = Path.unlink
    def failed(path, *args, **kwargs):
        raise OSError("unavailable")
    monkeypatch.setattr(Path, "unlink", failed)
    retry = headers()
    assert api.post("/api/v2/team/icon", content=image(colour="blue"), headers=retry).status_code == 503
    current = api.get("/api/v2/team/icon")
    assert current.status_code == 200 and current.headers["etag"] != first.headers["etag"]
    # Another replacement cannot accumulate a third logo while cleanup is unavailable.
    assert api.post("/api/v2/team/icon", content=image(colour="green"), headers=headers()).status_code == 503
    monkeypatch.setattr(Path, "unlink", unlink)
    assert api.post("/api/v2/team/icon", content=image(colour="blue"), headers=retry).status_code == 200
    assert len([p for p in api.app.state.blobs.directory.rglob("*") if p.is_file()]) == 1
