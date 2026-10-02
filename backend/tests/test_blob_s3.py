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
        if key.startswith(("AWS_", "LITESTREAM_", "TICO_BLOB_")) or key == "TICO_BACKUP_REGION":
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
    {"LITESTREAM_SECRET_ACCESS_KEY": "testing"}])
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
    ({}, None),
])
def test_region_resolution(storage, env, expected, client_options, monkeypatch):
    calls, _ = client_options
    monkeypatch.setenv("TICO_DB", "/example/hub.db")
    monkeypatch.setenv("TICO_BLOB_BUCKET", "acme-files")
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    storage(Settings.from_env()).s3
    assert calls == [("s3", {"region_name": expected, "endpoint_url": env.get("TICO_BLOB_ENDPOINT")})]
