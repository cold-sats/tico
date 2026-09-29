"""The desktop app's downloads (backend/downloads.py): the manifest and the installers come from
`releases/app/` in the bucket, are served without a sign-in, and a hub with no bucket offers none."""
import json

from backend.tests.test_api import api, headers  # noqa: F401

MANIFEST = {"version": "2.1.0", "pub_date": "2026-09-19T00:00:00Z",
            "platforms": {"darwin-aarch64": {"url": "https://runner.test/download/file/2.1.0/Tico.app.tar.gz", "signature": "sig"}},
            "installers": {"mac": {"file": "Tico_2.1.0_universal.dmg", "bytes": 12_582_912, "signed": True, "notarized": True},
                           "windows": {"file": "Tico_2.1.0_x64-setup.exe", "bytes": 9_000_000}}}


class FakeS3:
    def __init__(self):
        self.keys = {"releases/app/latest.json": json.dumps(MANIFEST).encode(),
                     "releases/app/2.1.0/Tico_2.1.0_universal.dmg": b"dmg"}

    def get_object(self, Bucket, Key):
        return {"Body": type("B", (), {"read": lambda _self: self.keys[Key]})()}

    def head_object(self, Bucket, Key):
        if Key not in self.keys:
            raise KeyError(Key)

    def generate_presigned_url(self, op, Params, ExpiresIn):
        return f"https://s3.test/{Params['Key']}?signed"


def test_installers_and_the_manifest_are_served_without_a_sign_in(api):
    # The routes hold the Downloads instance they were built with: point it at a fake bucket.
    built = api.app.state.downloads
    built.bucket, built.base, built._s3, built._manifest = "b", "https://runner.test", FakeS3(), (0.0, None)

    r = api.get("/download/latest.json")                        # no Authorization header at all
    assert r.status_code == 200 and r.json()["version"] == "2.1.0"
    assert r.json()["platforms"]["darwin-aarch64"]["signature"] == "sig"
    r = api.get("/download/mac", follow_redirects=False)
    assert r.status_code == 302 and r.headers["location"] == "https://runner.test/download/file/2.1.0/Tico_2.1.0_universal.dmg"
    r = api.get("/download/file/2.1.0/Tico_2.1.0_universal.dmg", follow_redirects=False)
    assert r.status_code == 302 and r.headers["location"].startswith("https://s3.test/releases/app/2.1.0/")
    assert api.get("/download/file/2.1.0/missing.dmg", follow_redirects=False).status_code == 404
    assert api.get("/download/linux", follow_redirects=False).status_code == 404   # not in this manifest
    described = api.get("/api/download/mac", headers=headers()).json()
    assert described == {"available": True, "version": "2.1.0", "file": "Tico_2.1.0_universal.dmg", "size_mb": 12,
                         "url": "https://runner.test/download/file/2.1.0/Tico_2.1.0_universal.dmg", "notarized": True, "signed": True}
    assert api.get("/api/download/windows", headers=headers()).json()["notarized"] is False
