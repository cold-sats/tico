"""The desktop app's downloads and updates.

CI builds the app for macOS, Windows and Linux (`.github/workflows/app.yml`) and puts the
bundles and one manifest under `releases/app/` in the storage bucket, the prefix the deploy role
may write and the server may read. Three routes serve them, none needing a sign-in (the app's
updater has no browser session, and an installer is nothing to protect):

- `GET /download/latest.json` — the manifest, in the shape Tauri's updater reads
  (`version`, `pub_date`, `platforms[<target>].url/.signature`), plus `installers[<os>]`
  for people: the file to hand a visitor on each OS.
- `GET /download/{os}` — `mac`, `windows` or `linux`: redirects to the current installer.
- `GET /download/file/{version}/{name}` — one bundle, as a short-lived S3 link.

`GET /api/download/{os}` is the signed-in question the site asks before it offers a download.
A server with no bucket (a local hub) answers `available: false` everywhere.

The no-sign-in promise holds on the runner hostname (`runner.<host>`), which the tunnel routes
for `/api/v2` and `/download` (your tunnel's public hostname rules) and which the updater
and the installer links use (`settings.runner_url`). On the main hostname Cloudflare Access
answers first, so a `/download/...` link there works only for a signed-in browser.
"""
import json
import re
import time

from fastapi import Request
from fastapi.responses import JSONResponse, RedirectResponse

from .store import Problem

PREFIX = "releases/app/"
OS_NAMES = ("mac", "windows", "linux")
FILE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._ +-]{0,200}$")
VERSION_RE = re.compile(r"^[0-9]+\.[0-9]+\.[0-9]+(?:[-+][A-Za-z0-9.]+)?$")


class Downloads:
    def __init__(self, settings, s3=None):
        self.bucket = settings.blob_bucket
        self.base = settings.runner_url or settings.public_url
        self._s3 = s3
        self._manifest = (0.0, None)

    @property
    def s3(self):
        if self._s3 is None:
            import boto3
            self._s3 = boto3.client("s3")
        return self._s3

    def manifest(self):
        """The current manifest, read from the bucket at most once a minute."""
        if not self.bucket:
            return None
        fetched, cached = self._manifest
        if cached is not None and time.time() - fetched < 60:
            return cached
        try:
            body = self.s3.get_object(Bucket=self.bucket, Key=PREFIX + "latest.json")["Body"].read()
            value = json.loads(body)
            if not isinstance(value, dict) or not VERSION_RE.match(str(value.get("version") or "")):
                value = None
        except Exception:
            value = None
        self._manifest = (time.time(), value)
        return value

    def file_url(self, version, name):
        if not self.bucket or not VERSION_RE.match(version) or not FILE_RE.match(name):
            return None
        key = f"{PREFIX}{version}/{name}"
        try:
            self.s3.head_object(Bucket=self.bucket, Key=key)
            return self.s3.generate_presigned_url("get_object", Params={"Bucket": self.bucket, "Key": key}, ExpiresIn=600)
        except Exception:
            return None

    def installer(self, os_name):
        manifest = self.manifest()
        if not manifest or os_name not in OS_NAMES:
            return None
        entry = (manifest.get("installers") or {}).get(os_name)
        if not isinstance(entry, dict) or not FILE_RE.match(str(entry.get("file") or "")):
            return None
        return {"version": manifest["version"], "file": entry["file"], "bytes": entry.get("bytes"),
                "notarized": bool(entry.get("notarized", False)), "signed": bool(entry.get("signed", False)),
                "url": f"{self.base}/download/file/{manifest['version']}/{entry['file']}"}


def install_downloads(app, store):
    downloads = Downloads(store.settings)
    app.state.downloads = downloads

    @app.get("/download/latest.json")
    def latest(request: Request):
        manifest = downloads.manifest()
        if not manifest:
            return JSONResponse({"error": {"code": "not_found", "detail": "No app build is published"}}, status_code=404)
        return JSONResponse(manifest, headers={"Cache-Control": "no-cache"})

    @app.get("/download/file/{version}/{name}")
    def file(request: Request, version: str, name: str):
        url = downloads.file_url(version, name)
        if not url:
            raise Problem("not_found", "No such app build", 404)
        return RedirectResponse(url, status_code=302)

    @app.get("/download/{os_name}")
    def installer(request: Request, os_name: str):
        entry = downloads.installer(os_name)
        if not entry:
            raise Problem("not_found", "No app build is published for that system", 404)
        return RedirectResponse(entry["url"], status_code=302)

    @app.get("/api/download/{os_name}")
    def describe(request: Request, os_name: str):
        entry = downloads.installer(os_name)
        if not entry:
            return {"available": False}
        size = entry.get("bytes")
        return {"available": True, "version": entry["version"], "url": entry["url"], "file": entry["file"],
                "size_mb": round(size / 1048576) if isinstance(size, (int, float)) and size else None,
                "notarized": entry["notarized"], "signed": entry["signed"]}
