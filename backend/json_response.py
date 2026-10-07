"""Compress API JSON without buffering live streams or changing downloaded file bytes."""
import asyncio
import gzip

from fastapi.responses import JSONResponse


def accepts_gzip(headers):
    accepted = {}
    for item in headers.get("accept-encoding", "").lower().split(","):
        name, *parameters = item.strip().split(";")
        quality = 1.0
        try:
            for parameter in parameters:
                key, _, value = parameter.strip().partition("=")
                if key == "q":
                    quality = float(value)
        except ValueError:
            quality = 0.0
        accepted[name] = quality
    return 0 < accepted.get("gzip", accepted.get("*", 0)) <= 1


async def compress(request, response):
    # Behind Cloudflare (cf-ray) the edge compresses for the browser; doing it here too only spends this server's CPU.
    if (not isinstance(response, JSONResponse) or request.method == "HEAD" or "cf-ray" in request.headers
            or response.status_code != 200 or len(response.body) < 1024
            or "content-encoding" in response.headers
            or "content-disposition" in response.headers or "x-content-sha256" in response.headers):
        return response
    response.headers.add_vary_header("Accept-Encoding")
    if not accepts_gzip(request.headers):
        return response
    # Large task pages must not hold up the event loop's other requests and live events.
    if len(response.body) >= 128 * 1024:
        body = await asyncio.to_thread(gzip.compress, response.body, compresslevel=3, mtime=0)
    else:
        body = gzip.compress(response.body, compresslevel=3, mtime=0)
    if len(body) < len(response.body):
        response.body = body
        response.headers["Content-Encoding"] = "gzip"
        response.headers["Content-Length"] = str(len(body))
    return response
