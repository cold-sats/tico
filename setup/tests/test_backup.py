import hashlib
import json
from datetime import datetime, timedelta, timezone

import pytest

from setup import backup, dns, state
from setup.cloudflare import Cloudflare
from setup.settings import from_saved
from setup.tests import fakes
from setup.tests.fakes import CaptureIO, aws_clients
from setup.tests.test_cloudflare import Api
from setup.tests.test_wizard import BASE, SECRET, go, secret_env  # noqa: F401


class Missing(Exception):
    def __init__(self, code):
        self.response = {"Error": {"Code": code}}


class FakeS3:
    def __init__(self, exists=False):
        self.exists, self.calls = exists, []

    def head_bucket(self, Bucket):
        if not self.exists:
            raise Missing("404")

    def __getattr__(self, name):
        return lambda **kw: self.calls.append((name, kw))

    def called(self, name):
        return [kw for n, kw in self.calls if n == name]


class Iam(fakes.FakeIAM):
    def __init__(self, user_tags=None, keys=()):
        super().__init__()
        self.user_tags, self.keys = user_tags, list(keys)

    def get_user(self, UserName):
        if self.user_tags is None:
            raise self.exceptions.NoSuchEntityException()
        return {}

    def list_user_tags(self, UserName):
        return {"Tags": self.user_tags}

    def list_access_keys(self, UserName):
        return {"AccessKeyMetadata": self.keys}

    def create_access_key(self, UserName):
        self._rec("create_access_key", UserName=UserName)
        return {"AccessKey": {"AccessKeyId": "AKIANEW", "SecretAccessKey": "s3cr3t"}}


OURS = [{"Key": "ManagedBy", "Value": "tico-setup"}, {"Key": "tico-setup-name", "Value": "tico-example-com"}]


def make(s3=None, iam=None, region="us-west-2"):
    s3, iam = s3 or FakeS3(), iam or Iam()
    values = backup.create_s3(s3, iam, domain="tico.example.com", region=region, account_id="123456789012",
                              name="tico-example-com", say=lambda _: None)
    return s3, iam, values


def test_the_bucket_is_versioned_encrypted_private_and_expires_old_versions():
    s3, iam, values = make()
    (created,) = s3.called("create_bucket")
    assert created["Bucket"] == "tico-backup-tico-example-com-123456789012"
    assert created["CreateBucketConfiguration"] == {"LocationConstraint": "us-west-2"}
    assert s3.called("put_bucket_versioning")[0]["VersioningConfiguration"] == {"Status": "Enabled"}
    assert s3.called("put_bucket_encryption")[0]["ServerSideEncryptionConfiguration"]["Rules"][0]["ApplyServerSideEncryptionByDefault"] == {"SSEAlgorithm": "AES256"}
    assert all(s3.called("put_public_access_block")[0]["PublicAccessBlockConfiguration"].values())
    (rule,) = s3.called("put_bucket_lifecycle_configuration")[0]["LifecycleConfiguration"]["Rules"]
    assert rule["NoncurrentVersionExpiration"]["NoncurrentDays"] == 90 and "AbortIncompleteMultipartUpload" in rule
    assert '"aws:SecureTransport": "false"' in s3.called("put_bucket_policy")[0]["Policy"]
    assert values == {"TICO_BACKUP_URL": "s3://tico-backup-tico-example-com-123456789012/tico", "TICO_BACKUP_REGION": "us-west-2",
                      "LITESTREAM_ACCESS_KEY_ID": "AKIANEW", "LITESTREAM_SECRET_ACCESS_KEY": "s3cr3t"}


def test_us_east_1_takes_no_location_constraint():
    s3, _, _ = make(region="us-east-1")
    assert "CreateBucketConfiguration" not in s3.called("create_bucket")[0]


def test_the_iam_user_can_only_reach_that_bucket_and_is_tagged():
    _, iam, _ = make()
    assert iam.called("create_user")[0]["Tags"] == OURS
    statements = json.loads(iam.called("put_user_policy")[0]["PolicyDocument"])["Statement"]
    resources = {r for st in statements for r in ([st["Resource"]] if isinstance(st["Resource"], str) else st["Resource"])}
    assert resources == {"arn:aws:s3:::tico-backup-tico-example-com-123456789012", "arn:aws:s3:::tico-backup-tico-example-com-123456789012/*"}
    assert not any("iam:" in a or a == "s3:*" for st in statements for a in st["Action"])


def test_rerunning_keeps_the_bucket_and_replaces_the_oldest_key():
    old = datetime(2026, 1, 1, tzinfo=timezone.utc)
    keys = [{"AccessKeyId": "NEWER", "CreateDate": old + timedelta(days=1)}, {"AccessKeyId": "OLDER", "CreateDate": old}]
    s3, iam, _ = make(FakeS3(exists=True), Iam(user_tags=OURS, keys=keys))
    assert not s3.called("create_bucket") and not iam.called("create_user")
    assert iam.called("delete_access_key") == [{"UserName": "tico-backup-tico-example-com", "AccessKeyId": "OLDER"}]


def test_a_same_named_user_it_did_not_create_is_left_alone():
    with pytest.raises(RuntimeError, match="not created by tico setup"):
        make(iam=Iam(user_tags=[]))


def test_a_bucket_someone_else_owns_is_an_error_not_a_silent_success():
    class Forbidden(FakeS3):
        def head_bucket(self, Bucket):
            raise Missing("403")
    with pytest.raises(RuntimeError, match="403"):
        make(Forbidden())


def test_r2_creates_the_bucket_and_derives_its_s3_keys_from_the_token():
    api = Api({("GET", "/accounts/a1/r2/buckets/tico-backup-tico-example-com"): (404, {"success": False, "errors": []}),
               ("POST", "/accounts/a1/r2/buckets"): {}, ("GET", "/user/tokens/verify"): {"id": "tokid"}})
    values = backup.create_r2(Cloudflare("TOKENVALUE", api), token="TOKENVALUE", account_id="a1", domain="tico.example.com", say=lambda _: None)
    assert ("POST", "/accounts/a1/r2/buckets", {"name": "tico-backup-tico-example-com"}) in api.calls
    assert values == {"TICO_BACKUP_URL": "s3://tico-backup-tico-example-com/tico", "TICO_BACKUP_ENDPOINT": "https://a1.r2.cloudflarestorage.com",
                      "TICO_BACKUP_REGION": "auto", "LITESTREAM_ACCESS_KEY_ID": "tokid",
                      "LITESTREAM_SECRET_ACCESS_KEY": hashlib.sha256(b"TOKENVALUE").hexdigest()}


def wizard_deps(s3, iam):
    ec2, _, ssm, factory = aws_clients(iam=iam)
    d = fakes.deps()
    r = fakes.FakeResolver({("tico.example.com", dns.A): ["203.0.113.9"]}, {"example.com": fakes.NETLIFY_NS})
    d.resolver, d.public_resolvers, d.aws_clients, d.aws_s3 = r, (lambda: [("Google", r)]), factory, (lambda region, profile: s3)
    return d, ssm


def test_aws_setup_creates_backup_storage_and_writes_its_key_to_the_server_env_only():
    s3, iam = FakeS3(), Iam()
    d, ssm = wizard_deps(s3, iam)
    code, out = go(["--target", "aws", "--yes", "--front-door", "caddy", *BASE], deps=d)
    assert code == 0, out
    env = ssm.called("put_parameter")[0]["Value"]
    assert "TICO_BACKUP_URL=s3://tico-backup-tico-example-com-123456789012/tico" in env and "LITESTREAM_SECRET_ACCESS_KEY=s3cr3t" in env
    assert "s3cr3t" not in out and "s3cr3t" not in json.dumps(state.load("tico.example.com")[0])
    assert "Note: No off-server backup" not in out


def test_a_failed_bucket_stops_setup_before_anything_else_and_says_how_to_go_on():
    class Boom(FakeS3):
        def create_bucket(self, **kw):
            raise RuntimeError("AccessDenied")
    d, ssm = wizard_deps(Boom(), Iam())
    code, out = go(["--target", "aws", "--yes", *BASE], deps=d)
    assert code == 1 and "Could not create the backup storage: AccessDenied" in out and "--backup local" in out
    assert not ssm.called("put_parameter")


def test_local_backups_are_named_in_the_plan_and_after_the_run():
    code, out = go(["--dry-run", "--target", "ssh", "--ssh", "root@203.0.113.7", *BASE])
    assert code == 0 and "Backups: local only" in out and "No off-server backup" in out
    code, out = go(["--target", "command", "--server-ip", "203.0.113.7", "--yes", "--skip-dns-wait", *BASE])
    assert code == 0 and "Note: No off-server backup" in out


def test_dry_run_plans_the_aws_bucket_without_touching_aws():
    s3, iam = FakeS3(), Iam()
    d, _ = wizard_deps(s3, iam)
    code, out = go(["--dry-run", "--target", "aws", *BASE], deps=d)
    assert code == 0 and "versioning on, AES-256 encryption, all public access blocked" in out
    assert 'TICO_BACKUP_URL="<bucket created when you run setup>"' in out and not s3.calls and not iam.calls


def test_an_existing_bucket_goes_straight_into_env(monkeypatch):
    monkeypatch.setenv("LITESTREAM_SECRET_ACCESS_KEY", "existing-secret")
    io = CaptureIO()
    from setup import cli
    code = cli.main(["--target", "command", "--server-ip", "203.0.113.7", "--yes", "--skip-dns-wait", "--backup", "existing",
                     "--backup-url", "s3://mine/tico", "--backup-endpoint", "https://x.r2.cloudflarestorage.com",
                     "--backup-region", "auto", "--backup-key-id", "AKID", *BASE], deps=fakes.deps(), io=io)
    assert code == 0 and "existing-secret" not in io.text
    saved, env = state.load("tico.example.com")
    restored = from_saved(saved, env)
    assert (restored.backup_url, restored.backup_key_id, restored.backup_secret) == ("s3://mine/tico", "AKID", "existing-secret")
    assert "existing-secret" not in json.dumps(saved)


def test_an_existing_bucket_without_its_url_is_a_named_error():
    code, out = go(["--target", "command", "--server-ip", "203.0.113.7", "--yes", "--backup", "existing", *BASE])
    assert code == 2 and "--backup-url" in out


def test_backup_storage_runs_where_the_aws_credentials_are_and_prints_what_the_server_needs():
    from setup import cli
    from setup.ui import IO

    said = []
    io = IO(interactive=False)
    io.say = said.append
    s3, iam = FakeS3(), Iam()
    deps = type("D", (), {"aws_clients": lambda self, region, profile: (None, iam, None, "123456789012"),
                          "aws_s3": lambda self, region, profile: s3})()
    assert cli.main(["backup-storage", "--domain", "tico.example.com", "--aws-region", "us-west-2"], deps=deps, io=io) == 0
    text = "\n".join(said)
    assert "--backup existing --backup-url s3://tico-backup-tico-example-com-123456789012/tico" in text
    assert "export LITESTREAM_SECRET_ACCESS_KEY=" in text
