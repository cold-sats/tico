"""The Cloudflare tunnel's route, for hq/compose.yaml's `cloudflared` profile.

A tunnel run with only its token and no route of its own (a locally managed one) logs "No ingress rules" and answers
every request with a 503. So HQ writes the one route it needs at every start, from HQ_DOMAIN, into a volume the
cloudflared container reads with `--config`: the domain to http://hq:8770, anything else a 404. The same as the Tico
server does for its own tunnel (docker/entrypoint.sh). A tunnel whose Public Hostname is set in the Cloudflare dashboard
keeps that route: cloudflared prefers the configuration Cloudflare holds and uses this file only when the tunnel has none.

cloudflared runs as a different, non-root user, so the file and its directory are world-readable. It holds no secret:
the tunnel token stays in cloudflared's own environment.
"""
import os
import re
import sys
from pathlib import Path

SERVICE = "http://hq:8770"
FILE = "cloudflared.yml"
_HOST = re.compile(r"^(?=.{1,253}$)[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?(?:\.[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?)*$")


def ingress(domain):
    """The config text: `domain` to HQ and a 404 for the rest; with no domain, only the 404 (a dashboard route still wins)."""
    domain = (domain or "").strip()
    if domain and not _HOST.match(domain):
        raise ValueError("HQ_DOMAIN is not a plain hostname: " + domain)
    rules = [f"  - hostname: {domain}\n    service: {SERVICE}\n"] if domain else []
    return "ingress:\n" + "".join(rules) + "  - service: http_status:404\n"


def write(directory, domain):
    """Write the config into `directory` (the shared volume), readable by every user. Returns the path, or None when
    there is no such writable directory (HQ run outside compose, or without the cloudflared volume)."""
    directory = Path(directory)
    if not directory.is_dir() or not os.access(directory, os.W_OK):
        return None
    text = ingress(domain)
    temporary = directory / (FILE + ".new")
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o644)
    with os.fdopen(descriptor, "w") as handle:
        handle.write(text)
    os.chmod(temporary, 0o644)          # whatever the umask: cloudflared is another user
    try:
        os.chmod(directory, 0o755)
    except OSError:
        pass
    path = directory / FILE
    os.replace(temporary, path)
    return path


def prepare(environ=os.environ):
    """At start: write the route when the volume is there. A bad HQ_DOMAIN stops HQ with the reason."""
    domain = environ.get("HQ_DOMAIN", "")
    try:
        path = write(environ.get("HQ_TUNNEL_DIR", "/tunnel"), domain)
    except ValueError as error:
        sys.exit("tico-hq: " + str(error))
    if path and not domain.strip():
        print("tico-hq: HQ_DOMAIN is not set, so the tunnel's own route answers only 404s; set HQ_DOMAIN in hq/.env "
              "or route the hostname in the Cloudflare dashboard (docs/telemetry.md).", file=sys.stderr)
    return path
