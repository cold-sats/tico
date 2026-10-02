"""Attachment/download clients share credential precedence without changing the environment."""

import os
from pathlib import Path

import boto3
import pytest

from backend.blobs import Blobs
from backend.config import Settings
from backend.downloads import Downloads


@pytest.fixture
def client_options(monkeypatch):
    for key in list(os.environ):
        if key.startswith(("AWS_", "LITESTREAM_", "TICO_BLOB_")) or key.startswith("TICO_BACKUP_"):
            monkeypatch.delenv(key)
    calls = []
    result = object()
    monkeypatch.setattr(boto3, "client", lambda service, **options: calls.append((service, options)) or result)
    return calls, result


@pytest.mark.parametrize("storage", [Blobs, Downloads])
@pytest.mark.parametrize("aws", [{}, {"AWS_ACCESS_KEY_ID": "testing", "AWS_SECRET_ACCESS_KEY": "testing"},
    {"AWS_ACCESS_KEY_ID": "testing", "AWS_SECRET_ACCESS_KEY": "testing", "AWS_SESSION_TOKEN": "testing-token"},
    {"AWS_ACCESS_KEY_ID": "testing"}, {"AWS_SECRET_ACCESS_KEY": "testing"}, {"AWS_SESSION_TOKEN": "testing-token"},
    {"AWS_PROFILE": "example"}, {"AWS_ROLE_ARN": "example-role", "AWS_WEB_IDENTITY_TOKEN_FILE": "/example/token"},
    {"AWS_CONTAINER_CREDENTIALS_RELATIVE_URI": "/example/credentials"}])
def test_backup_keys_only_when_no_aws_credential_source(storage, aws, client_options, monkeypatch):
    calls, result = client_options
    monkeypatch.setenv("LITESTREAM_ACCESS_KEY_ID", "testing-backup")
    monkeypatch.setenv("LITESTREAM_SECRET_ACCESS_KEY", "testing-backup-secret")
    for key, value in aws.items():
        monkeypatch.setenv(key, value)
    before = dict(os.environ)
    client = storage(Settings(db_path=Path("/example/hub.db"), blob_bucket="acme-files", blob_region="us-east-1"))
    assert client.s3 is result and client.s3 is result
    expected = {"region_name": "us-east-1", "endpoint_url": None}
    if not aws:
        expected.update(aws_access_key_id="testing-backup", aws_secret_access_key="testing-backup-secret")
    assert calls == [("s3", expected)]
    assert dict(os.environ) == before


@pytest.mark.parametrize("backup", [{}, {"LITESTREAM_ACCESS_KEY_ID": "testing"},
    {"LITESTREAM_SECRET_ACCESS_KEY": "testing"},
    {"LITESTREAM_ACCESS_KEY_ID": "", "LITESTREAM_SECRET_ACCESS_KEY": ""},
    {"LITESTREAM_ACCESS_KEY_ID": "testing", "LITESTREAM_SECRET_ACCESS_KEY": ""}])
def test_absent_or_incomplete_backup_pair_keeps_default_chain(backup, client_options, monkeypatch):
    calls, _ = client_options
    for key, value in backup.items():
        monkeypatch.setenv(key, value)
    Blobs(Settings(db_path=Path("/example/hub.db"), blob_bucket="acme-files")).s3
    assert calls == [("s3", {"region_name": None, "endpoint_url": None})]


def test_no_file_bucket_does_not_use_backup_keys(client_options, monkeypatch):
    calls, _ = client_options
    monkeypatch.setenv("LITESTREAM_ACCESS_KEY_ID", "testing")
    monkeypatch.setenv("LITESTREAM_SECRET_ACCESS_KEY", "testing")
    Downloads(Settings(db_path=Path("/example/hub.db"))).s3
    assert calls == [("s3", {"region_name": None, "endpoint_url": None})]


@pytest.mark.parametrize("storage", [Blobs, Downloads])
@pytest.mark.parametrize("env,expected", [
    ({"TICO_BLOB_REGION": "us-west-2", "TICO_BACKUP_REGION": "us-east-1", "AWS_REGION": "eu-west-1"}, "us-west-2"),
    ({"TICO_BACKUP_REGION": "us-east-1", "AWS_DEFAULT_REGION": "eu-west-1"}, "us-east-1"),
    ({"TICO_BLOB_ENDPOINT": "https://s3.example.com", "TICO_BACKUP_REGION": "auto", "AWS_DEFAULT_REGION": "eu-west-1"}, "eu-west-1"),
    ({"TICO_BLOB_ENDPOINT": "https://s3.example.com", "TICO_BLOB_REGION": "auto", "TICO_BACKUP_REGION": "us-east-1"}, "auto"),
    ({"AWS_REGION": "us-west-2", "AWS_DEFAULT_REGION": "us-east-1"}, "us-west-2"),
    ({"AWS_DEFAULT_REGION": "us-east-1"}, "us-east-1"),
    ({"TICO_BACKUP_ENDPOINT": "https://s3.example.com", "TICO_BACKUP_REGION": "auto",
      "AWS_REGION": "us-west-2"}, "us-west-2"),
    ({"TICO_BACKUP_ENDPOINT": "https://s3.example.com", "TICO_BACKUP_REGION": "auto"}, None),
    ({"TICO_BACKUP_ENDPOINT": "", "TICO_BACKUP_REGION": "us-east-1"}, "us-east-1"),
    ({"TICO_BLOB_REGION": "", "TICO_BACKUP_REGION": "", "AWS_REGION": "", "AWS_DEFAULT_REGION": ""}, None),
    ({}, None),
])
def test_region_resolution(storage, env, expected, client_options, monkeypatch):
    calls, _ = client_options
    monkeypatch.setenv("TICO_DB", "/example/hub.db")
    monkeypatch.setenv("TICO_BLOB_BUCKET", "acme-files")
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    storage(Settings.from_env()).s3
    assert calls == [("s3", {"region_name": expected, "endpoint_url": env.get("TICO_BLOB_ENDPOINT") or None})]


@pytest.mark.parametrize("storage", [Blobs, Downloads])
def test_dedicated_file_keys_override_aws_and_backup_without_export(storage, client_options, monkeypatch):
    calls, result = client_options
    for key, value in {"TICO_BLOB_ACCESS_KEY_ID": "testing-files", "TICO_BLOB_SECRET_ACCESS_KEY": "testing-files-secret",
                       "LITESTREAM_ACCESS_KEY_ID": "testing-backup", "LITESTREAM_SECRET_ACCESS_KEY": "testing-backup-secret",
                       "AWS_ACCESS_KEY_ID": "testing-aws", "AWS_SECRET_ACCESS_KEY": "testing-aws-secret",
                       "AWS_SESSION_TOKEN": "testing-token"}.items():
        monkeypatch.setenv(key, value)
    before = dict(os.environ)
    assert storage(Settings(db_path=Path("/example/hub.db"), blob_bucket="acme-files")).s3 is result
    assert calls == [("s3", {"region_name": None, "endpoint_url": None,
                             "aws_access_key_id": "testing-files", "aws_secret_access_key": "testing-files-secret"})]
    assert dict(os.environ) == before


@pytest.mark.parametrize("storage", [Blobs, Downloads])
@pytest.mark.parametrize("key,secret", [("", ""), ("testing", ""), ("", "testing")])
def test_empty_or_incomplete_file_keys_use_backup_pair(storage, key, secret, client_options, monkeypatch):
    calls, _ = client_options
    for name, value in {"TICO_BLOB_ACCESS_KEY_ID": key, "TICO_BLOB_SECRET_ACCESS_KEY": secret,
                        "LITESTREAM_ACCESS_KEY_ID": "testing-backup", "LITESTREAM_SECRET_ACCESS_KEY": "testing-secret",
                        "AWS_ACCESS_KEY_ID": "", "AWS_SECRET_ACCESS_KEY": "", "AWS_PROFILE": ""}.items():
        monkeypatch.setenv(name, value)
    storage(Settings(db_path=Path("/example/hub.db"), blob_bucket="acme-files")).s3
    assert calls[0][1]["aws_access_key_id"] == "testing-backup"
    assert calls[0][1]["aws_secret_access_key"] == "testing-secret"


def test_empty_storage_settings_are_unset(client_options, monkeypatch):
    calls, _ = client_options
    monkeypatch.setenv("TICO_DB", "/example/hub.db")
    for key in ("TICO_BLOB_BUCKET", "TICO_BLOB_ENDPOINT", "TICO_BLOB_REGION", "TICO_UPLOAD_MAX_BYTES",
                "TICO_BLOB_ACCESS_KEY_ID", "TICO_BLOB_SECRET_ACCESS_KEY"):
        monkeypatch.setenv(key, "")
    settings = Settings.from_env()
    assert not settings.blob_bucket and settings.upload_max_bytes == 2 * 1024 ** 3
    Downloads(settings).s3
    assert calls == [("s3", {"region_name": None, "endpoint_url": None})]
