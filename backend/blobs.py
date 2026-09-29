"""Immutable binary storage. Only opaque, authorized IDs are exposed over HTTP."""

import hashlib
import os
import re
import tempfile
from pathlib import Path

from .store import H, Problem


class Blobs:
    def __init__(self, settings, s3=None):
        self.bucket = settings.blob_bucket
        self.directory = settings.blob_dir or settings.db_path.parent / "blobs"
        self._s3 = s3

    @property
    def s3(self):
        if self._s3 is None:
            import boto3
            self._s3 = boto3.client("s3")
        return self._s3

    @staticmethod
    def key(digest):
        if not re.fullmatch(r"[0-9a-f]{64}", digest):
            raise ValueError("Invalid content digest")
        return "blobs/" + digest[:2] + "/" + digest

    def put(self, data):
        digest = hashlib.sha256(data).hexdigest()
        key = self.key(digest)
        if self.bucket:
            import base64
            checksum = base64.b64encode(bytes.fromhex(digest)).decode()
            try:
                self.s3.put_object(Bucket=self.bucket, Key=key, Body=data,
                                   ContentType="application/octet-stream", ChecksumSHA256=checksum,
                                   ServerSideEncryption="AES256", IfNoneMatch="*")
            except Exception as exc:
                # Identical immutable bytes already exist. Never overwrite a blob.
                if getattr(exc, "response", {}).get("Error", {}).get("Code") not in ("PreconditionFailed", "412"):
                    raise Problem("blob_storage", "File storage is unavailable; retry without discarding your file", 503, True) from exc
                self.get(digest)  # Existing object must still pass its content hash.
            return digest
        path = self.directory / key
        path.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
        fd, temporary = tempfile.mkstemp(prefix=".upload-", dir=path.parent)
        try:
            with os.fdopen(fd, "wb") as stream:
                stream.write(data)
                stream.flush()
                os.fsync(stream.fileno())
            try:
                os.link(temporary, path)
            except FileExistsError:
                self.get(digest)
            directory = os.open(path.parent, os.O_RDONLY)
            try:
                os.fsync(directory)
            finally:
                os.close(directory)
        finally:
            os.unlink(temporary)
        return digest

    def get(self, digest):
        key = self.key(digest)
        if self.bucket:
            try:
                response = self.s3.get_object(Bucket=self.bucket, Key=key)
                with response["Body"] as stream:
                    data = stream.read()
            except Exception as exc:
                raise Problem("blob_storage", "File storage is unavailable", 503, True) from exc
        else:
            try:
                data = (self.directory / key).read_bytes()
            except OSError as exc:
                raise Problem("blob_storage", "Stored file is unavailable", 503, True) from exc
        if hashlib.sha256(data).hexdigest() != digest:
            raise Problem("blob_integrity", "Stored file failed its integrity check", 503)
        return data


def register(c, who, digest, size, name, content_type="application/octet-stream"):
    # A display name is never used to construct a storage path.
    name = Path(str(name).replace("\\", "/")).name
    name = re.sub(r"[\x00-\x1f\x7f]", "", name)[:200] or "attachment"
    row = {"id": H.new_id(), "owner": who.actor, "digest": digest, "size": size,
           "name": name, "content_type": content_type, "created": H.now()}
    c.execute("INSERT INTO blobs VALUES(:id,:owner,:digest,:size,:name,:content_type,:created)", row)
    return brief(row)


def brief(row):
    return {k: row[k] for k in ("id", "name", "size", "content_type")} | {
        "url": "/api/v2/files/" + row["id"]}
