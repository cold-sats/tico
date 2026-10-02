"""The desktop app's downloads (backend/downloads.py): the manifest and the installers come from
`releases/app/` in the bucket or the running GitHub release, served without a sign-in."""
import json
from types import SimpleNamespace

import httpx
import pytest

from backend.downloads import Downloads

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
                         "url": "https://runner.test/download/file/2.1.0/Tico_2.1.0_universal.dmg", "notarized": True, "signed": True, "app_kind": "company"}
    assert api.get("/api/download/windows", headers=headers()).json()["notarized"] is False


def github_fixture(version="0.3.7"):
    base = f"https://github.com/ticoteam/tico/releases/download/v{version}/"
    names = ["latest.json", "Tico_universal.dmg", "Tico.app.tar.gz", "Tico_x64-setup.exe", "Tico.AppImage", "Tico.deb"]
    value = {"version": version, "pub_date": "2026-10-02T00:00:00Z",
             "platforms": {"darwin-aarch64": {"url": base + "Tico.app.tar.gz", "signature": "sig"}},
             "installers": {"mac": {"notarized": True, "signed": True}}}
    release = {"tag_name": "v" + version, "assets": [
        {"name": name, "browser_download_url": base + name, "size": 12_582_912} for name in names]}
    return base, release, value


def test_no_bucket_uses_running_github_release_and_caches_without_credentials(api):
    base, release, value = github_fixture()
    requests = []

    def get(request):
        requests.append(request)
        assert "authorization" not in request.headers and "cookie" not in request.headers
        if request.url.host == "api.github.com":
            assert request.url.path.endswith("/tags/v0.3.7")
            return httpx.Response(200, json=release)
        assert str(request.url) == base + "latest.json"
        return httpx.Response(200, json=value)

    built = api.app.state.downloads
    built.bucket, built.version = "", "0.3.7"
    built._github_transport = httpx.MockTransport(get)
    assert api.get("/download/latest.json").status_code == 404
    assert not requests
    for os_name, name in [("mac", "Tico_universal.dmg"), ("windows", "Tico_x64-setup.exe"), ("linux", "Tico.AppImage")]:
        response = api.get("/download/" + os_name, follow_redirects=False)
        assert response.status_code == 302 and response.headers["location"] == base + name
        described = api.get("/api/download/" + os_name, headers=headers()).json()
        assert described["available"] is True and described["url"] == base + name
        assert described["app_kind"] == "generic"
    assert len(requests) == 2


@pytest.mark.parametrize("bucket_version,github_expected", [("0.3.6", False), ("0.3.7", False), ("0.3.8", False), ("0.3.10", False)])
def test_bucket_version_selection(bucket_version, github_expected):
    base, release, value = github_fixture()
    requests = []

    def get(request):
        requests.append(request)
        return httpx.Response(200, json=release if request.url.host == "api.github.com" else value)

    s3 = FakeS3()
    s3.keys["releases/app/latest.json"] = json.dumps({**MANIFEST, "version": bucket_version}).encode()
    downloads = Downloads(SimpleNamespace(blob_bucket="b", runner_url="https://runner.example.com", public_url=""),
                          s3, httpx.MockTransport(get))
    downloads.version = "0.3.7"
    assert downloads.manifest()["version"] == ("0.3.7" if github_expected else bucket_version)
    assert bool(requests) == github_expected


@pytest.mark.parametrize("failure", ["offline", "missing", "malformed"])
def test_github_failure_is_unavailable_and_cached(api, failure):
    requests = []

    def get(request):
        requests.append(request)
        if failure == "offline":
            raise httpx.ConnectError("offline", request=request)
        return httpx.Response(404 if failure == "missing" else 200, json=[])

    built = api.app.state.downloads
    built.bucket, built.version = "", "0.3.7"
    built._github_transport = httpx.MockTransport(get)
    assert api.get("/api/download/mac", headers=headers()).json() == {"available": False}
    assert api.get("/download/latest.json").status_code == 404
    assert api.get("/download/mac", follow_redirects=False).status_code == 404
    assert len(requests) == 1


def test_updater_keeps_environment_build_even_when_older_than_server(api):
    built = api.app.state.downloads
    built.bucket, built._s3, built.version = "b", FakeS3(), "3.0.0"
    built._github_transport = httpx.MockTransport(lambda request: pytest.fail("Updater must not fetch GitHub"))
    assert api.get("/download/latest.json").json()["version"] == MANIFEST["version"]


def test_download_storage_uses_blob_region_endpoint_and_prefix(monkeypatch, tmp_path):
    from backend.config import Settings
    import boto3
    settings = Settings(db_path=tmp_path / "hub.db", blob_bucket="s3://private/team/files", blob_region="us-east-1",
                        blob_endpoint="https://s3.example.com")
    s3 = FakeS3()
    s3.keys = {"team/files/" + key: value for key, value in s3.keys.items()}
    calls = []
    def client(service, **options):
        calls.append((service, options))
        return s3
    monkeypatch.setattr(boto3, "client", client)
    downloads = Downloads(settings)
    assert downloads.bucket_manifest()["version"] == MANIFEST["version"]
    url = downloads.file_url("2.1.0", "Tico_2.1.0_universal.dmg")
    assert url.startswith("https://s3.test/team/files/releases/app/2.1.0/")
    assert calls == [("s3", {"region_name": "us-east-1", "endpoint_url": "https://s3.example.com"})]


@pytest.mark.parametrize("warm", [False, True])
def test_github_fetch_is_single_flight_and_does_not_hold_lock(warm):
    import threading
    from concurrent.futures import ThreadPoolExecutor
    downloads = Downloads(SimpleNamespace(blob_bucket="", runner_url="", public_url=""))
    stale = {"version": "0.3.6"} if warm else None
    downloads._github = (1.0, stale)
    entered, finish = threading.Event(), threading.Event()
    calls = []
    def fetch():
        calls.append(True)
        entered.set()
        assert finish.wait(2)
        return MANIFEST
    downloads._fetch_github_manifest = fetch
    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(downloads.manifest)
        assert entered.wait(1)
        try:
            assert pool.submit(downloads.manifest).result(timeout=0.5) is stale
            assert len(calls) == 1
        finally:
            finish.set()
        assert first.result(timeout=1) == MANIFEST
    assert downloads.manifest() == MANIFEST and len(calls) == 1
