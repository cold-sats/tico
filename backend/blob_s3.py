"""S3 settings shared by attachments and desktop downloads."""

import os
import threading
import time

CLIENT_BUILD_TIMEOUT = 5


class Sources:
    """One process's selected attachment identity, shared with desktop downloads."""
    def __init__(self, settings):
        self.settings = settings
        self.selected = None
        self._clients = {}
        self._building = {}
        self._lock = threading.Lock()

    @property
    def kind(self):
        return self.selected or kinds(self.settings)[0]

    def client_for(self, kind, reads=False):
        cache_key = kind, reads
        with self._lock:
            if cache_key in self._clients:
                return self._clients[cache_key]
            task = self._building.get(cache_key)
            if task is None or (task[0].is_set() and time.monotonic() - task[2] >= 30):
                done, errors = threading.Event(), []
                task = self._building[cache_key] = done, errors, time.monotonic()
                def build():
                    try:
                        if reads:
                            from botocore.config import Config
                            config = Config(connect_timeout=2, read_timeout=5, retries={"total_max_attempts": 1})
                            s3 = client(self.settings, kind=kind, config=config)
                        else:
                            s3 = client(self.settings, kind=kind)
                        with self._lock:
                            self._clients[cache_key] = s3
                    except Exception as exc:
                        errors.append(exc)
                    finally:
                        done.set()
                # Credential providers (including IMDS) run before SDK socket timeouts apply.
                # At most one construction per kind/access mode survives a caller timeout.
                threading.Thread(target=build, name="tico-s3-client", daemon=True).start()
        done, errors, _ = task
        if not done.wait(CLIENT_BUILD_TIMEOUT):
            raise TimeoutError("S3 credential lookup timed out")
        if errors:
            raise errors[0]
        with self._lock:
            return self._clients[cache_key]

    @property
    def s3(self):
        return self.client_for(self.kind)

    def read_s3(self, operation, **options):
        return read(lambda kind: self.client_for(kind, reads=True), self.kind,
                    kinds(self.settings, reads=True), operation, **options)


def region(settings, env=None):
    env = os.environ if env is None else env
    return (settings.blob_region or
            (env.get("TICO_BACKUP_REGION") if not settings.blob_endpoint and not env.get("TICO_BACKUP_ENDPOINT") else None) or
            env.get("AWS_REGION") or env.get("AWS_DEFAULT_REGION") or None)


def kinds(settings, env=None, reads=False):
    env = os.environ if env is None else env
    mode = getattr(settings, "blob_credentials", "auto") or "auto"
    if mode != "auto" and not reads:
        return [mode]
    candidates = []
    for kind, prefix in (("keys", "TICO_BLOB"), ("backup", "LITESTREAM")):
        if ((kind == "keys" or settings.blob_bucket) and env.get(prefix + "_ACCESS_KEY_ID")
                and env.get(prefix + "_SECRET_ACCESS_KEY")):
            candidates.append(kind)
    return candidates + ["role"]


def client(settings, config=None, kind=None):
    import boto3
    options = {"region_name": region(settings), "endpoint_url": settings.blob_endpoint or None}
    if config is not None:
        options["config"] = config
    kind = kind or kinds(settings)[0]
    if kind != "role":
        prefix = "TICO_BLOB" if kind == "keys" else "LITESTREAM"
        key, secret = os.environ.get(prefix + "_ACCESS_KEY_ID"), os.environ.get(prefix + "_SECRET_ACCESS_KEY")
        if not key or not secret:
            from botocore.exceptions import NoCredentialsError
            raise NoCredentialsError()
        options.update(aws_access_key_id=key, aws_secret_access_key=secret)
    return boto3.client("s3", **options)


def read(client_for, selected, candidates, operation, **options):
    """Retry other identities only after access denial; return the signing client too."""
    try:
        s3 = client_for(selected)
        return getattr(s3, operation)(**options), s3
    except Exception as exc:
        if getattr(exc, "response", {}).get("Error", {}).get("Code") not in ("AccessDenied", "403"):
            raise
        denied = exc
    for kind in candidates:
        if kind == selected:
            continue
        try:
            s3 = client_for(kind)
            return getattr(s3, operation)(**options), s3
        except Exception:
            continue
    raise denied


def write_error(exc, bucket, cleanup=False):
    # Only known error codes or the exception type: SDK messages can contain credential material.
    code = getattr(exc, "response", {}).get("Error", {}).get("Code")
    known = {"AccessDenied", "InvalidAccessKeyId", "SignatureDoesNotMatch", "ExpiredToken", "InvalidToken",
             "NoSuchBucket", "AuthorizationHeaderMalformed", "RequestTimeTooSkewed", "SlowDown", "ServiceUnavailable"}
    reason = code if code in known else type(exc).__name__
    if cleanup and code == "AccessDenied":
        return f"S3 storage cleanup permission missing: s3:AbortMultipartUpload on {bucket}"
    if cleanup:
        return f"S3 storage can't clean up its write check: {reason} on {bucket}"
    action = " (s3:PutObject)" if code == "AccessDenied" else ""
    return f"S3 storage can't write: {reason} on {bucket}{action}"
