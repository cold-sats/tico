"""Authorized callers hand us a blob; storage addresses never grant Tico rights."""
import re
from urllib.parse import quote

from fastapi.responses import Response, StreamingResponse

from .blobs import disposition

IMMUTABLE = "private, max-age=31536000, immutable"


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
    digest, size = row["digest"], row["size"]
    mime = row["content_type"].split(";", 1)[0].strip().lower()
    headers = {"ETag": '"' + digest + '"', "X-Content-SHA256": digest, "Accept-Ranges": "bytes",
               "Cache-Control": IMMUTABLE if versioned else "no-cache",
               "X-Content-Type-Options": "nosniff", "Content-Security-Policy": "default-src 'none'; sandbox",
               "Content-Disposition": disposition(mime) + "; filename*=UTF-8''" + quote(row["name"], safe="")}
    if mime == "application/pdf":
        headers["Content-Security-Policy"] = "default-src 'none'; style-src 'unsafe-inline'"
    etags = request.headers.get("if-none-match", "").split(",")
    if any(tag.strip().removeprefix("W/") in (headers["ETag"], "*") for tag in etags):
        return Response(status_code=304, headers=headers)
    start, end, status = 0, size - 1, 200
    value = request.headers.get("range")
    if value and "," not in value and request.method != "HEAD" and request.headers.get("if-range", headers["ETag"]) == headers["ETag"]:
        try:
            start, end = byte_range(value, size)
        except ValueError:
            return Response(status_code=416, headers={**headers, "Content-Range": f"bytes */{size}"})
        headers["Content-Range"] = f"bytes {start}-{end}/{size}"
        status = 206
    headers["Content-Length"] = str(max(0, end - start + 1))
    if request.method == "HEAD":
        return Response(media_type=mime or "application/octet-stream", headers=headers)
    return StreamingResponse(blobs.open_range(digest, start, end), status_code=status,
                             media_type=mime or "application/octet-stream", headers=headers)
