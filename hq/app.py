"""The HQ collector: `GET /v1/latest` (a release lookup that also counts the install), `GET /v1/stats`, `POST /v1/recruit`
(the org builder's suggestions, recruit.py) and the support tickets a person files from their app (support.py).

What it keeps is in db.py and support.py and what it is sent is in PRIVACY.md. The address of a request is used for rate limiting in
memory (limits.py) and nowhere else; nothing here logs a request, and the server is started with its access log off
(__main__.py), so no address or query string reaches a log.
"""
import asyncio
import re
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from . import recruit
from .db import Database
from .limits import Limiter
from .releases import Latest
from .support import Tickets, install as install_support

INSTALL_ID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}")
VERSION = re.compile(r"[0-9]{1,4}\.[0-9]{1,4}\.[0-9]{1,4}(?:-[0-9A-Za-z][0-9A-Za-z.-]{0,31})?")
FIELDS = ("install_id", "version", "active_people", "active_bots")
BOOLEANS = {"true": True, "false": False}
PURGE_EVERY = 24 * 3600


def parse(params):
    """The four fields, strictly: each exactly once, a v4 UUID, a version, and the words true or false. Anything else,
    or a field left out, is refused (returns None); fields beyond these four are ignored, not read."""
    values = {}
    for name in FIELDS:
        found = params.getlist(name)
        if len(found) != 1:
            return None
        values[name] = found[0]
    if not INSTALL_ID.fullmatch(values["install_id"]) or not VERSION.fullmatch(values["version"]):
        return None
    if values["active_people"] not in BOOLEANS or values["active_bots"] not in BOOLEANS:
        return None
    return (values["install_id"], values["version"], BOOLEANS[values["active_people"]],
            BOOLEANS[values["active_bots"]])


def create_app(db, latest, limiter=None, client_ip_header="", staff_key="", tickets=None):
    limiter = limiter or Limiter()
    tickets = tickets or Tickets(db)
    header = client_ip_header.strip().lower()

    def address(request):
        """Who is asking, for the rate limit only. Behind a proxy that sets `header`, that header's last entry."""
        if header:
            value = request.headers.get(header, "").split(",")[-1].strip()
            if value:
                return value
        return request.client.host if request.client else ""

    async def purge_daily():
        while True:
            await asyncio.to_thread(db.purge)
            await asyncio.sleep(PURGE_EVERY)

    @asynccontextmanager
    async def lifespan(app):
        task = asyncio.create_task(purge_daily())
        try:
            yield
        finally:
            task.cancel()

    app = FastAPI(title="Tico HQ", lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)

    @app.middleware("http")
    async def rate_limit(request: Request, call_next):
        # The support routes have limits of their own (support.py): a person's app polls for replies.
        path = request.url.path
        if path != "/healthz" and not path.startswith(("/v1/support", "/v1/staff")) and not limiter.allow(address(request)):
            return JSONResponse({"error": "rate_limited"}, status_code=429, headers={"Retry-After": "3600"})
        return await call_next(request)

    @app.get("/healthz")
    def healthz():
        return {"ok": True}

    @app.get("/v1/latest")
    def latest_release(request: Request):
        params = request.query_params
        if any(name in params for name in FIELDS):
            ping = parse(params)
            if ping is None:
                return JSONResponse({"error": "invalid"}, status_code=422, headers={"Cache-Control": "no-store"})
            db.record(*ping)
        release = latest.get()
        if release is None:
            return JSONResponse({"error": "unavailable"}, status_code=503, headers={"Cache-Control": "no-store"})
        return JSONResponse(release, headers={"Cache-Control": "no-store"})

    @app.get("/v1/stats")
    def stats():
        return JSONResponse(db.stats(), headers={"Cache-Control": "public, max-age=300",
                                                 "Access-Control-Allow-Origin": "*"})

    # POST /v1/recruit, the org builder's suggestions (recruit.py): stores nothing, and the limit above applies too.
    recruit.install(app, address=address)
    install_support(app, tickets, address, staff_key)
    return app
