"""Authorized callers hand us a blob; storage addresses never grant Tico rights."""
import base64
import json
import re
import time
from urllib.parse import quote, urlsplit

from fastapi.responses import Response, RedirectResponse, StreamingResponse
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding

from .blobs import disposition
from .store import Problem

IMMUTABLE = "private, max-age=31536000, immutable"


def signed_url(settings, digest, private_key, now=None):
    origin = settings.cdn_url.rstrip("/")
    parsed = urlsplit(origin)
    if parsed.scheme != "https" or not parsed.netloc or parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise Problem("cdn_config", "File CDN URL must be an HTTPS origin", 503)
    from .blobs import Blobs
    url = origin + "/" + Blobs.key(digest)
    expires = int(time.time() if now is None else now) + 3600
    policy = json.dumps({"Statement": [{"Resource": url, "Condition": {
        "DateLessThan": {"AWS:EpochTime": expires}}}]}, separators=(",", ":")).encode()
    key = serialization.load_pem_private_key(private_key.encode() if isinstance(private_key, str) else private_key, password=None)
    signature = base64.b64encode(key.sign(policy, padding.PKCS1v15(), hashes.SHA1())).decode().translate(str.maketrans("+=/", "-_~"))
    return f"{url}?Expires={expires}&Signature={signature}&Key-Pair-Id={quote(settings.cdn_key_id, safe='')}"


def private_key(app, settings):
    try:
        if settings.cdn_credential_id:
            with app.state.store.read() as c:
                vault = app.state.vault
                row = vault.row(c, settings.cdn_credential_id)
                return vault.cipher.decrypt(c, row)
        if settings.cdn_secret_arn:
            import boto3
            return boto3.client("secretsmanager").get_secret_value(SecretId=settings.cdn_secret_arn)["SecretString"]
    except Exception:
        raise Problem("cdn_config", "File CDN signing credential is unavailable; check the server secret", 503) from None
    raise Problem("cdn_config", "Configure the file CDN signing credential in the server secrets or vault", 503)


def byte_range(value, size):
    match = re.fullmatch(r"bytes=(\d*)-(\d*)", value)
    if not match or not any(match.groups()) or size == 0:
        raise ValueError
    left, right = match.groups()
    if not left:
        suffix = int(right)
        if suffix == 0:
            raise ValueError
        return max(0, size - suffix), size - 1
    start, end = int(left), min(int(right), size - 1) if right else size - 1
    if start >= size or start > end:
        raise ValueError
    return start, end


def serve(request, blobs, row, versioned=False):
    settings = request.app.state.store.settings
    digest, size = row["digest"], row["size"]
    mime = row["content_type"].split(";", 1)[0].strip().lower()
    headers = {"ETag": '"' + digest + '"', "X-Content-SHA256": digest, "Accept-Ranges": "bytes",
               "Cache-Control": IMMUTABLE if versioned else "no-cache",
               "X-Content-Type-Options": "nosniff", "Content-Security-Policy": "default-src 'none'; sandbox",
               "Content-Disposition": disposition(mime) + "; filename*=UTF-8''" + quote(row["name"], safe="")}
    if settings.cdn_url and settings.cdn_key_id and blobs.bucket:
        # Retained local files remain readable during copy, including when S3 is down.
        in_s3 = not (blobs.directory / blobs.key(digest)).is_file()
        if not in_s3:
            with request.app.state.store.read() as c:
                in_s3 = bool(c.execute("SELECT 1 FROM blob_locations WHERE digest=? AND bucket=?", (digest, blobs.bucket)).fetchone())
        if in_s3:
            try:
                url = signed_url(settings, digest, private_key(request.app, settings))
            except Problem:
                raise
            except Exception:
                raise Problem("cdn_config", "File CDN signing credential is invalid", 503) from None
            return RedirectResponse(url, 302, headers={"Cache-Control": "private, no-store", "X-Content-SHA256": digest})
    etags = request.headers.get("if-none-match", "").split(",")
    if any(tag.strip().removeprefix("W/") in (headers["ETag"], "*") for tag in etags):
        return Response(status_code=304, headers=headers)
    start, end, status = 0, size - 1, 200
    value = request.headers.get("range")
    if value and request.headers.get("if-range", headers["ETag"]) == headers["ETag"]:
        try:
            start, end = byte_range(value, size)
        except ValueError:
            return Response(status_code=416, headers={**headers, "Content-Range": f"bytes */{size}"})
        headers["Content-Range"] = f"bytes {start}-{end}/{size}"
        status = 206
    headers["Content-Length"] = str(max(0, end - start + 1))
    return StreamingResponse(blobs.open_range(digest, start, end), status_code=status,
                             media_type=mime or "application/octet-stream", headers=headers)
