"""Off-volume copies of what Litestream does not carry: the attachments in /data/blobs.

It also reports how the install is backed up. The container entrypoint decides the mode and exports it;
a loop next to the server keeps the blobs mirrored and writes the time the copies last moved to a status
file the server reads. Blobs are content-addressed and immutable, so a sync only ever adds files.
"""

import hashlib
import json
import os
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

STATUS_FILE = "/tmp/tico-backup-status.json"
LOCAL_WARNING = ("Backups are only on this server's disk (the tico-backups volume). Losing the server loses them "
                 "too. Set TICO_BACKUP_URL to an S3 or R2 bucket in .env.")
OFF_WARNING = "Backups are off (TICO_BACKUP=off). Losing the data volume loses everything."
# Litestream 0.5 keeps one directory per compaction level at the top of a replica, under ltx/ on a file
# replica and not on S3; ours sits beside them. Listing the levels rather than everything keeps the check
# cheap however many attachments there are.
DB_LEVELS = tuple(prefix + str(level).rjust(width, "0") for prefix, width in (("", 4), ("ltx/", 1)) for level in (0, 1, 2, 3, 9))
FILES_PREFIX = "files"
# The environment marker: a small file OUTSIDE the database that says "this is an existing company, with this id".
# One in the data volume, one beside the replica. A start with an empty volume reads them before it may begin a
# new company, so an unreachable backup can never turn into a blank company replicating over the real one.
MARKER = "environment.json"
LOCAL_MARKER = ".tico-environment"


def target_kind(url="", endpoint=""):
    if not url:
        return "local"
    if "r2.cloudflarestorage.com" in endpoint:
        return "r2"
    return "s3-compatible" if endpoint else "s3"


def mode_from_env(env):
    """remote | local-only | off, from the same variables the entrypoint reads."""
    if (env.get("TICO_BACKUP") or "").lower() == "off":
        return "off"
    return "remote" if env.get("TICO_BACKUP_URL") else "local-only"


def _now():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def status(env=None, path=None):
    """{mode, last_replicated_at, target_kind, warning} for the config payload."""
    env = os.environ if env is None else env
    if not env.get("TICO_BACKUP_MODE"):
        # Not started by the container entrypoint (a VM install, tests). VM stacks run Litestream from
        # their own service config, so absence of TICO_BACKUP_URL says nothing: report unknown, not off.
        if not env.get("TICO_BACKUP_URL"):
            return {"mode": None, "last_replicated_at": None, "warning": "", "target_kind": "none"}
        return {"mode": "remote", "last_replicated_at": None, "warning": "",
                "target_kind": target_kind(env.get("TICO_BACKUP_URL", ""), env.get("TICO_BACKUP_ENDPOINT", ""))}
    mode = env["TICO_BACKUP_MODE"]
    kind = "none" if mode == "off" else target_kind(env.get("TICO_BACKUP_URL", ""), env.get("TICO_BACKUP_ENDPOINT", ""))
    last = None
    try:
        last = json.loads(Path(path or env.get("TICO_BACKUP_STATUS_FILE") or STATUS_FILE).read_text()).get("last_replicated_at")
    except (OSError, ValueError):
        pass
    warning = {"local-only": LOCAL_WARNING, "off": OFF_WARNING}.get(mode, "")
    return {"mode": mode, "last_replicated_at": last, "target_kind": kind, "warning": warning}


class LocalMirror:
    def __init__(self, root):
        self.root = Path(root)

    def keys(self, prefix):
        base = self.root / prefix
        return {p.relative_to(base).as_posix() for p in base.rglob("*") if p.is_file()} if base.is_dir() else set()

    def put(self, key, source):
        target = self.root / key
        target.parent.mkdir(parents=True, exist_ok=True)
        fd, temporary = tempfile.mkstemp(prefix=".part-", dir=target.parent)
        with os.fdopen(fd, "wb") as out, open(source, "rb") as src:
            while chunk := src.read(1 << 20):
                out.write(chunk)
        os.replace(temporary, target)

    def get(self, key, destination):
        with open(self.root / key, "rb") as src, open(destination, "wb") as out:
            while chunk := src.read(1 << 20):
                out.write(chunk)

    def exists(self, key):
        return (self.root / key).is_file()

    def newest(self, prefixes):
        times = [p.stat().st_mtime for prefix in prefixes if (self.root / prefix).is_dir()
                 for p in (self.root / prefix).rglob("*") if p.is_file()]
        return max(times) if times else None


class S3Mirror:
    def __init__(self, client, bucket, prefix):
        self.s3, self.bucket, self.prefix = client, bucket, prefix.strip("/")

    def _key(self, key):
        return (self.prefix + "/" if self.prefix else "") + key

    def _objects(self, prefix):
        base = self._key(prefix) + "/"
        for page in self.s3.get_paginator("list_objects_v2").paginate(Bucket=self.bucket, Prefix=base):
            for item in page.get("Contents", []):
                yield item["Key"][len(base):], item["LastModified"]

    def keys(self, prefix):
        return {key for key, _ in self._objects(prefix)}

    def put(self, key, source):
        self.s3.upload_file(str(source), self.bucket, self._key(key))

    def get(self, key, destination):
        self.s3.download_file(self.bucket, self._key(key), str(destination))

    def exists(self, key):
        from botocore.exceptions import ClientError
        try:
            self.s3.head_object(Bucket=self.bucket, Key=self._key(key))
            return True
        except ClientError as exc:
            if str(exc.response.get("Error", {}).get("Code")) in ("404", "NoSuchKey", "NotFound"):
                return False
            raise

    def newest(self, prefixes):
        times = [modified.timestamp() for prefix in prefixes for _, modified in self._objects(prefix)]
        return max(times) if times else None


def mirror_from_env(env=None):
    env = os.environ if env is None else env
    url = env.get("TICO_BACKUP_URL", "")
    if not url:
        return LocalMirror(env.get("TICO_BACKUP_DIR", "/backups"))
    parsed = urlparse(url)
    if parsed.scheme != "s3" or not parsed.netloc:
        raise ValueError("TICO_BACKUP_URL must be s3://bucket/prefix")
    import boto3
    client = boto3.client("s3", endpoint_url=env.get("TICO_BACKUP_ENDPOINT") or None,
                          region_name=env.get("TICO_BACKUP_REGION") or ("us-east-1" if env.get("TICO_BACKUP_ENDPOINT") else None),
                          aws_access_key_id=env.get("LITESTREAM_ACCESS_KEY_ID") or None,
                          aws_secret_access_key=env.get("LITESTREAM_SECRET_ACCESS_KEY") or None)
    return S3Mirror(client, parsed.netloc, parsed.path)


def _blob_files(blob_dir):
    base = Path(blob_dir) / "blobs"
    if not base.is_dir():
        return {}
    return {p.relative_to(base).as_posix(): p for p in base.rglob("*")
            if p.is_file() and not p.name.startswith(".upload-")}


def sync_blobs(blob_dir, mirror):
    """Uploads the blobs the mirror lacks; returns how many."""
    have = mirror.keys(FILES_PREFIX + "/blobs")
    sent = 0
    for key, path in sorted(_blob_files(blob_dir).items()):
        if key not in have:
            mirror.put(FILES_PREFIX + "/blobs/" + key, path)
            sent += 1
    return sent


def restore_blobs(mirror, blob_dir):
    """Downloads every mirrored blob, checking each against the sha256 in its name."""
    count = 0
    for key in sorted(mirror.keys(FILES_PREFIX + "/blobs")):
        target = Path(blob_dir) / "blobs" / key
        if target.exists():
            continue
        target.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
        fd, temporary = tempfile.mkstemp(prefix=".restore-", dir=target.parent)
        os.close(fd)
        mirror.get(FILES_PREFIX + "/blobs/" + key, temporary)
        digest = hashlib.sha256(Path(temporary).read_bytes()).hexdigest()
        if digest != key.rsplit("/", 1)[-1]:
            os.unlink(temporary)
            raise SystemExit("tico: error: backup blob " + key + " fails its checksum")
        os.replace(temporary, target)
        count += 1
    return count


def is_empty(data_dir):
    """True when nothing of an install is in the data volume."""
    root = Path(data_dir)
    return not root.is_dir() or not any(root.iterdir())


def _marker_text(environment_id):
    return json.dumps({"environment_id": environment_id, "written_at": _now()}) + "\n"


def write_markers(data_dir, environment_id, mirror=None):
    """Records that this install is an existing company. The volume marker is required; the backup one is best effort
    (a warning, because a bucket that is down must not stop a running company from starting)."""
    path = Path(data_dir) / LOCAL_MARKER
    path.write_text(_marker_text(environment_id))
    if mirror is not None:
        fd, temporary = tempfile.mkstemp(prefix=".marker-")
        try:
            with os.fdopen(fd, "w") as out:
                out.write(_marker_text(environment_id))
            mirror.put(MARKER, temporary)
        except Exception as exc:
            print("tico: warning: could not write the environment marker to the backup location: "
                  + type(exc).__name__ + ": " + str(exc)[:200], file=sys.stderr, flush=True)
        finally:
            os.unlink(temporary)


def check_new_company(data_dir, mirror, restore_failed=False, initialize_empty=False):
    """Run when the database is missing after the restore attempt. Returns None when starting a new company is
    safe, else the message to refuse with. Safe means: nothing anywhere says a company already exists, and the
    backup location could be read to find that out."""
    have_local = (Path(data_dir) / LOCAL_MARKER).exists()
    problem = None
    where = "the backup location"
    if mirror is None:
        found = False
    else:
        try:
            found = mirror.exists(MARKER) or mirror.newest(DB_LEVELS) is not None
        except Exception as exc:
            found, problem = False, "could not read " + where + " (" + type(exc).__name__ + ": " + str(exc)[:160] + ")"
    if initialize_empty:
        if found or have_local:
            print("tico: WARNING: TICO_INITIALIZE_EMPTY is set: starting a NEW company although an existing one was "
                  "found. Its backup will be overwritten.", file=sys.stderr, flush=True)
        return None
    if found or have_local:
        return ("an existing company was found in " + ("the backup location" if found else "this data volume's marker")
                + " but the database could not be restored" + (" (the restore command failed)" if restore_failed else "")
                + ". Starting would create a blank company and replicate it over the real backup. Fix the backup "
                "settings (TICO_BACKUP_URL, keys, network) and start again, or run `docker compose run --rm server "
                "restore`. To knowingly start a new company anyway, set TICO_INITIALIZE_EMPTY=1.")
    if problem or restore_failed:
        return ((problem or "the restore command failed") + ", so it is unknown whether a company already lives there. "
                "Refusing to start a blank one over it. Fix the backup settings and start again; for a genuinely new "
                "install with an unreachable bucket, set TICO_INITIALIZE_EMPTY=1.")
    return None


def write_status(mirror, path):
    newest = mirror.newest(DB_LEVELS)
    if newest is None:
        return
    text = datetime.fromtimestamp(newest, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    fd, temporary = tempfile.mkstemp(dir=Path(path).parent)
    with os.fdopen(fd, "w") as out:
        json.dump({"last_replicated_at": text, "checked_at": _now()}, out)
    os.replace(temporary, path)


def loop(env=None, interval=30, warn_every=3600, sleep=time.sleep, rounds=None):
    env = os.environ if env is None else env
    mirror = mirror_from_env(env)
    blob_dir = env.get("TICO_BLOB_DIR", "/data/blobs")
    path = env.get("TICO_BACKUP_STATUS_FILE") or STATUS_FILE
    warning = status(env, path)["warning"]
    last_warned, done = 0.0, 0
    while rounds is None or done < rounds:
        if warning and time.monotonic() - last_warned >= warn_every:
            print("tico: WARNING: " + warning, flush=True)
            last_warned = time.monotonic()
        try:
            if not env.get("TICO_BLOB_BUCKET"):
                sync_blobs(blob_dir, mirror)
            write_status(mirror, path)
        except Exception as exc:  # keep trying: the next round may find the bucket back
            print("tico: warning: backup sync failed: " + type(exc).__name__ + ": " + str(exc)[:200], flush=True)
        done += 1
        sleep(interval)


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    command = argv[0] if argv else ""
    env = os.environ
    if command == "loop":
        loop(env)
    elif command == "restore-blobs":
        n = restore_blobs(mirror_from_env(env), env.get("TICO_BLOB_DIR", "/data/blobs"))
        print("tico: restored %d attachment file(s)" % n)
    elif command == "is-empty":
        return 0 if is_empty(argv[1]) else 1
    elif command == "check-new-company":   # DIR [--restore-failed] [--initialize-empty]; backups off: no mirror
        mirror = None if env.get("TICO_BACKUP_MODE") == "off" else mirror_from_env(env)
        message = check_new_company(argv[1], mirror, "--restore-failed" in argv, "--initialize-empty" in argv)
        if message:
            print("tico: error: " + message, file=sys.stderr)
            return 1
    elif command == "mark-environment":    # DIR ID
        write_markers(argv[1], argv[2], None if env.get("TICO_BACKUP_MODE") == "off" else mirror_from_env(env))
    else:
        print("usage: python -m backend.replication loop|restore-blobs|is-empty DIR|check-new-company DIR|mark-environment DIR ID", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
