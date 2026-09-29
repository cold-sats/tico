"""Updates this Tico install to another image version, and undoes it when the server does not come back.

POST /update {"version": "1.2.3" | "v1.2.3" | "latest"}   start an update (409 while one runs)
GET  /status                                     {"state", "from", "to", "message"}
Both need `Authorization: Bearer <token>`, the token the server wrote to /control/updater-token.

It talks to Docker through the mounted socket, which is root on the host: it listens on the compose
network only, and runs nothing but `docker compose` for the one service it manages.

Runner mode (TICO_UPDATER_MODE=runner) is the same updater beside a Docker runner (docker/runner.compose.yaml).
It manages the `runner` service and the tico-runner image, answers "healthy" from the container's own
health check, and writes its own token to /control (the runner reads it there, read-only) because no server
does. The runner asks for an update only when no turn is running, and only for the release its server names.

The compose bundle moves with the image. Before touching any container the updater downloads the target release's
tico-bundle-vX.Y.Z.tar.gz and SHA256SUMS (the URLs scripts/install.sh uses), checks the checksum, and replaces the
bundle's files in the install directory (compose.yaml, .env.example, docker/runner.compose.yaml, ...; a runner box
only runner.compose.yaml; never .env) one atomic rename at a time, keeping the old copies in .bundle-previous/.
A bad checksum or download refuses the update and changes nothing. If the new version does not turn healthy, the
image and the bundle are both put back. The updater itself keeps running its old image until the next
`docker compose up -d` on the host: it cannot recreate itself mid-run.
"""

import hashlib
import hmac
import json
import os
import re
import secrets
import shutil
import subprocess
import tarfile
import tempfile
import threading
import time
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

PROJECT = os.environ.get("TICO_PROJECT_DIR", "/project")
TOKEN_FILE = os.environ.get("TICO_UPDATER_TOKEN_FILE", "/control/updater-token")
MODE = "runner" if os.environ.get("TICO_UPDATER_MODE") == "runner" else "server"
SERVICE = "runner" if MODE == "runner" else "server"
IMAGE = os.environ.get("TICO_IMAGE", "ghcr.io/ticoteam/tico-runner" if MODE == "runner" else "ghcr.io/ticoteam/tico")
COMPOSE_FILE = os.environ.get("TICO_COMPOSE_FILE", "")   # relative to PROJECT; the runner box uses runner.compose.yaml
HEALTH_URL = os.environ.get("TICO_HEALTH_URL", "http://server:8765/healthz")
HEALTH_SECONDS = int(os.environ.get("TICO_HEALTH_SECONDS", "180"))
PULL = os.environ.get("TICO_UPDATER_PULL", "always")   # "never" only in docker/smoke.sh, whose tags exist only locally
RELEASES = os.environ.get("TICO_RELEASES_URL", "https://github.com/ticoteam/tico/releases")
LATEST_API = os.environ.get("TICO_LATEST_URL", "https://api.github.com/repos/ticoteam/tico/releases/latest")
BUNDLE = os.environ.get("TICO_UPDATER_BUNDLE", "always")   # "never" only in docker/smoke.sh, whose releases exist only as local tags
PREVIOUS = ".bundle-previous"
NEVER_TOUCH = {".env"}
MAX_BUNDLE = 20 * 1024 * 1024
VERSION = re.compile(r"latest|v?[0-9]+\.[0-9]+\.[0-9]+(?:-[0-9A-Za-z.]+)?")

lock = threading.Lock()
status = {"state": "idle", "from": "", "to": "", "message": ""}


def set_status(**fields):
    with lock:
        status.update(fields)


def compose(*args, tag=None, timeout=600):
    env = {**os.environ, **({"TICO_TAG": tag} if tag else {})}
    files = ["-f", os.path.join(PROJECT, COMPOSE_FILE)] if COMPOSE_FILE else []
    result = subprocess.run(["docker", "compose", *files, "--project-directory", PROJECT, *args], env=env,
                            capture_output=True, text=True, timeout=timeout)
    if result.returncode:
        lines = (result.stderr or result.stdout).strip().splitlines()
        raise RuntimeError(lines[-1] if lines else "docker compose failed")
    return result.stdout


def running_image():
    """(image id, tag) of the running service, so a failed update can put exactly that back."""
    container = compose("ps", "-q", SERVICE).split()[0]
    out = subprocess.run(["docker", "inspect", "--format", "{{.Image}} {{.Config.Image}}", container],
                         capture_output=True, text=True, check=True).stdout.split()
    return out[0], out[1].rsplit(":", 1)[-1]


def container_healthy(seconds):
    """The runner image has a HEALTHCHECK; the container must report `healthy`, not merely be running."""
    deadline = time.time() + seconds
    while time.time() < deadline:
        try:
            container = compose("ps", "-q", SERVICE).split()
            state = subprocess.run(["docker", "inspect", "--format", "{{.State.Health.Status}}", container[0]],
                                   capture_output=True, text=True).stdout.strip() if container else ""
            if state == "healthy":
                return True
        except (RuntimeError, OSError, subprocess.SubprocessError):
            pass
        time.sleep(3)
    return False


def healthy(seconds):
    if MODE == "runner":
        return container_healthy(seconds)
    deadline = time.time() + seconds
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(HEALTH_URL, timeout=3) as reply:
                if reply.status == 200:
                    return True
        except OSError:
            pass
        time.sleep(3)
    return False


def remember(tag):
    """Keep `docker compose up` from the host on the version this install now runs."""
    path = os.path.join(PROJECT, ".env")
    try:
        lines = [line for line in open(path).read().splitlines() if not line.startswith("TICO_TAG=")]
        with open(path, "w") as stream:  # in place: the file may be bind-mounted by inode
            stream.write("\n".join(lines + ["TICO_TAG=" + tag]) + "\n")
    except OSError:
        pass


class BundleError(RuntimeError):
    pass


def http_get(url, limit=MAX_BUNDLE):
    with urllib.request.urlopen(url, timeout=30) as reply:
        data = reply.read(limit + 1)
    if len(data) > limit:
        raise BundleError("%s is larger than %d bytes" % (url, limit))
    return data


def release_of(version):
    """The release tag whose bundle goes with an image tag; `latest` is looked up on GitHub."""
    if version != "latest":
        return version
    try:
        tag = json.loads(http_get(LATEST_API, 1 << 20)).get("tag_name", "")
    except (OSError, ValueError) as exc:
        raise BundleError("could not look up the latest release: %s" % exc)
    if not isinstance(tag, str) or tag == "latest" or not VERSION.fullmatch(tag):
        raise BundleError("the latest release has no usable tag")
    return tag


def bundle_targets(names):
    """{path inside the bundle: path in the install directory}. A runner box wants runner.compose.yaml, nothing else."""
    if MODE == "runner":
        return {"docker/runner.compose.yaml": "runner.compose.yaml"} if "docker/runner.compose.yaml" in names else {}
    return {name: name for name in names}


def fetch_bundle(release, into):
    """Download and verify the release's bundle, unpack it under `into`, and return {bundle path: unpacked file}."""
    name = "tico-bundle-%s.tar.gz" % release
    base = "%s/download/%s" % (RELEASES.rstrip("/"), release)
    try:
        sums = http_get(base + "/SHA256SUMS", 1 << 20).decode("utf-8", "replace")
        blob = http_get(base + "/" + name)
    except OSError as exc:
        raise BundleError("could not download the %s bundle: %s" % (release, exc))
    want = ""
    for line in sums.splitlines():
        fields = line.split()
        if len(fields) == 2 and fields[1].lstrip("*") == name:
            want = fields[0].lower()
            break
    if not want:
        raise BundleError("SHA256SUMS does not list %s; refusing to use it" % name)
    got = hashlib.sha256(blob).hexdigest()
    if got != want:
        raise BundleError("checksum mismatch for %s (expected %s, got %s); nothing was changed" % (name, want, got))
    archive = os.path.join(into, "bundle.tar.gz")
    with open(archive, "wb") as stream:
        stream.write(blob)
    files = {}
    with tarfile.open(archive) as tar:
        for member in tar.getmembers():
            path = os.path.normpath(member.name)
            if path.startswith("/") or path == ".." or path.startswith("../") or not (member.isfile() or member.isdir()):
                raise BundleError("the bundle has unsafe paths; refusing to unpack it")
            if member.isdir():
                continue
            out = os.path.join(into, "files", path)
            os.makedirs(os.path.dirname(out), exist_ok=True)
            with tar.extractfile(member) as source, open(out, "wb") as target:
                shutil.copyfileobj(source, target)
            os.chmod(out, 0o755 if member.mode & 0o111 else 0o644)
            files[path] = out
    return files


def install_file(source, dest):
    """One atomic rename: a reader sees the old file or the new one, never half of it."""
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    temp = dest + ".tico-new"
    shutil.copyfile(source, temp)
    os.chmod(temp, os.stat(source).st_mode & 0o777)
    try:
        info = os.stat(dest)
        os.chown(temp, info.st_uid, info.st_gid)   # keep the installer's ownership when we are allowed to
    except OSError:
        pass
    os.replace(temp, dest)


def apply_bundle(files, release):
    """Replace the install directory's bundle files, keeping the old ones in .bundle-previous/ for rollback."""
    targets = {rel: dest for rel, dest in bundle_targets(files).items() if dest not in NEVER_TOUCH}
    keep = os.path.join(PROJECT, PREVIOUS)
    shutil.rmtree(keep, ignore_errors=True)
    os.makedirs(keep)
    manifest = {"release": release, "existed": [], "added": []}
    try:
        manifest["version_file"] = open(os.path.join(PROJECT, ".bundle-version")).read()
    except OSError:
        manifest["version_file"] = None
    for dest in targets.values():
        current = os.path.join(PROJECT, dest)
        if os.path.isfile(current):
            saved = os.path.join(keep, "files", dest)
            os.makedirs(os.path.dirname(saved), exist_ok=True)
            shutil.copy2(current, saved)
            manifest["existed"].append(dest)
        else:
            manifest["added"].append(dest)
    with open(os.path.join(keep, "manifest.json"), "w") as stream:
        json.dump(manifest, stream)
    try:
        for rel, dest in targets.items():
            install_file(files[rel], os.path.join(PROJECT, dest))
        marker = os.path.join(PROJECT, ".bundle-version")
        with open(marker + ".tico-new", "w") as stream:
            stream.write(release + "\n")
        os.replace(marker + ".tico-new", marker)
    except OSError:
        restore_bundle()
        raise


def restore_bundle():
    """Put the previous bundle back: the files it replaced, and gone again the ones it added. Never touches .env."""
    keep = os.path.join(PROJECT, PREVIOUS)
    try:
        manifest = json.load(open(os.path.join(keep, "manifest.json")))
    except (OSError, ValueError):
        return False
    for dest in manifest.get("existed", []):
        if dest not in NEVER_TOUCH:
            install_file(os.path.join(keep, "files", dest), os.path.join(PROJECT, dest))
    for dest in manifest.get("added", []):
        try:
            os.remove(os.path.join(PROJECT, dest))
        except OSError:
            pass
    version_path = os.path.join(PROJECT, ".bundle-version")
    try:
        if manifest.get("version_file") is None:
            os.remove(version_path)
        else:
            with open(version_path, "w") as stream:
                stream.write(manifest["version_file"])
    except OSError:
        pass
    return True


def other_services():
    """Services of the (new) compose file that follow the release, except the one being moved and this updater."""
    try:
        names = compose("config", "--services").split()
    except RuntimeError:
        return []
    return [n for n in names if n not in (SERVICE, "updater")]


def update(version):
    staging = None
    bundled = False
    try:
        image_id, previous = running_image()
        set_status(state="pulling", **{"from": previous, "to": version}, message="")
        if BUNDLE != "never":
            # Everything that can refuse the update happens here, before any file or container changes.
            try:
                staging = tempfile.mkdtemp(prefix="tico-bundle-")
                release = release_of(version)
                files = fetch_bundle(release, staging)
            except BundleError as exc:
                set_status(state="failed", message="Not updated: %s." % exc)
                return
            apply_bundle(files, release)
            bundled = True
        try:
            if PULL != "never":
                compose("pull", SERVICE, tag=version)
            set_status(state="restarting")
            compose("up", "-d", "--no-deps", "--pull", "never", SERVICE, tag=version)
            if not healthy(HEALTH_SECONDS):
                raise RuntimeError(("the runner" if MODE == "runner" else "the server") + " did not come up healthy within %d seconds" % HEALTH_SECONDS)
        except RuntimeError as exc:
            # The old image is still on disk; point its tag back at it and start it again, with the old bundle.
            subprocess.run(["docker", "tag", image_id, IMAGE + ":" + previous], check=False)
            try:
                if bundled:
                    restore_bundle()
                compose("up", "-d", "--no-deps", "--pull", "never", SERVICE, tag=previous)
                back = healthy(HEALTH_SECONDS)
            except (RuntimeError, OSError):
                back = False
            set_status(state="rolled_back" if back else "failed",
                       message=str(exc) + (". Went back to " + previous + "." if back else ". The old version did not start either."))
            return
        remember(version)
        message = ""
        if bundled and MODE == "server":
            # Slack, the front door and anything new follow the new compose file; the updater itself stays put.
            for name in other_services():
                try:
                    compose("up", "-d", "--no-deps", name, tag=version)
                except RuntimeError as exc:
                    message = "Updated, but %s did not restart: %s" % (name, exc)
        set_status(state="healthy", message=message)
    except Exception as exc:  # anything unexpected must show in /status rather than kill the thread
        set_status(state="failed", message=str(exc))
    finally:
        if staging:
            shutil.rmtree(staging, ignore_errors=True)


class Handler(BaseHTTPRequestHandler):
    server_version = "tico-updater"

    def reply(self, code, body):
        data = json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def authorized(self):
        try:
            expected = open(TOKEN_FILE).read().strip()
        except OSError:
            expected = ""
        given = self.headers.get("Authorization", "")
        return bool(expected) and hmac.compare_digest(given, "Bearer " + expected)

    def do_GET(self):
        if not self.authorized():
            return self.reply(401, {"error": "unauthorized"})
        if self.path != "/status":
            return self.reply(404, {"error": "not found"})
        with lock:
            self.reply(200, dict(status))

    def do_POST(self):
        if not self.authorized():
            return self.reply(401, {"error": "unauthorized"})
        if self.path != "/update":
            return self.reply(404, {"error": "not found"})
        try:
            length = int(self.headers.get("Content-Length", "0"))
            version = json.loads(self.rfile.read(min(length, 1024)) or b"{}").get("version", "")
        except (ValueError, AttributeError):
            version = ""
        if not isinstance(version, str) or not VERSION.fullmatch(version):
            return self.reply(422, {"error": "version is latest or X.Y.Z"})
        if version[0].isdigit():
            version = "v" + version  # the server names a release 1.2.3; its image tag is v1.2.3
        with lock:
            if status["state"] in ("pulling", "restarting"):
                return self.reply(409, {"error": "an update is already running", **status})
            status.update(state="pulling", to=version, message="")
        threading.Thread(target=update, args=(version,), daemon=True).start()
        self.reply(202, dict(status))

    def log_message(self, *args):
        pass


def ensure_token():
    """Runner mode: nothing else writes the token, so the updater does, once, for the runner to read."""
    if MODE != "runner" or os.path.exists(TOKEN_FILE):
        return
    with open(TOKEN_FILE, "w") as stream:
        stream.write(secrets.token_hex(32) + "\n")
    os.chmod(TOKEN_FILE, 0o644)   # the runner is another user; only the two services mount this volume


if __name__ == "__main__":
    ensure_token()
    ThreadingHTTPServer(("0.0.0.0", 8080), Handler).serve_forever()
