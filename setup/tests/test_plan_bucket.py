"""--plan-bucket (Tico's hosted servers): a starter plan too big for the env's 8 KB parameter goes to the server by S3,
one object per install at plans/<name>/<sha256>; the server copies it to a file at first boot, checks its sha256, and
setup deletes the object once the server is up. Fake AWS only, plus the copy step run here with a stand-in `aws`."""
import argparse
import hashlib
import json
import os
import stat
import subprocess
from pathlib import Path

import pytest

from backend import company_file as C
from backend.company_file import starter
from setup import aws, contract, envfile, remote, settings, wizard
from setup.tests.test_preview_flags import CREATE, NAME, env, go, world  # noqa: F401 (env: its secrets, autouse)
from setup.ui import MissingInput

BUCKET = "tico-preview-planbucket-abc123"


class FakeS3:
    def __init__(self, region, log, fail=None):
        self.region, self.log, self.fail = region, log, fail

    def put_object(self, **kw):
        self.log.append(("put_object", kw))

    def delete_object(self, **kw):
        self.log.append(("delete_object", kw))
        if self.fail:
            raise self.fail


class ClientError(Exception):
    def __init__(self, code):
        super().__init__(code)
        self.response = {"Error": {"Code": code}}


@pytest.fixture(scope="module")
def big(tmp_path_factory):
    """A whole 300-seat chart: far over the env's 8 KB and over what one env string may hold once it grows."""
    from backend.tests.test_company_file import chart
    draft = chart(300)
    draft["company"].update(name="Acme Finance", about="We help small firms manage their books.")
    path = tmp_path_factory.mktemp("plan") / "tico.company.yaml"
    path.write_text(C.to_yaml(draft))
    return path


def hosted(path, *extra):
    d, ec2, iam, ssm, r53 = world()
    log, regions = [], []

    def s3(region, profile):
        regions.append(region)
        log.append(("instances so far", len(ec2.called("run_instances"))))
        return FakeS3(region, log)
    d.aws_s3 = s3
    code, out = go([*CREATE, "--company-file", str(path), *extra], d)
    return code, out, ec2, iam, ssm, log, regions


def test_a_300_seat_chart_reaches_the_server_by_the_plan_bucket_and_never_by_its_env(big):
    code, out, ec2, iam, ssm, log, regions = hosted(big, "--plan-bucket", BUCKET, "--plan-bucket-region", "us-west-2")
    assert code == 0, out
    assert regions == ["us-west-2"]
    calls = [name for name, _ in log]
    assert calls == ["instances so far", "put_object", "delete_object"] and log[0][1] == 0     # put before the launch
    put, deleted = log[1][1], log[2][1]
    body = put["Body"].decode()
    sha = hashlib.sha256(put["Body"]).hexdigest()
    assert put["Bucket"] == BUCKET and put["Key"] == f"plans/{NAME}/{sha}"
    assert deleted == {"Bucket": BUCKET, "Key": put["Key"]}                                     # gone once it is up
    assert len(body) > starter.ENV_PACKED and len(starter.unpack(body)["bots"]) == 300
    (param,) = ssm.called("put_parameter")
    env = envfile.parse(param["Value"])
    assert "TICO_COMPANY_FILE_B64" not in env and "Tier" not in param and len(param["Value"]) < 4096
    assert env["TICO_COMPANY_FILE_S3"] == f"s3://{BUCKET}/{put['Key']}" and env["TICO_COMPANY_FILE_SHA256"] == sha
    assert env["TICO_COMPANY_FILE_S3_REGION"] == "us-west-2" and env["TICO_SAMPLE_COMPANY"] == "off"
    assert env["TICO_COMPANY_FILE"] == "/run/tico/company-file/plan.b64"
    # The server's own role reads its own plan only; the boundary limits, it never grants.
    (inline,) = iam.called("put_role_policy")
    statements = json.loads(inline["PolicyDocument"])["Statement"]
    assert {"Effect": "Allow", "Action": "s3:GetObject", "Resource": f"arn:aws:s3:::{BUCKET}/plans/{NAME}/*"} in statements
    user_data = ec2.called("run_instances")[0]["UserData"]
    assert body not in user_data + out and "aws s3 cp" in user_data


def test_the_retry_keeps_the_plan_on_this_computer_and_puts_it_again(big, monkeypatch, tmp_path):
    monkeypatch.setenv("TICO_SETUP_HOME", str(tmp_path))
    from setup import state
    code, out, *_ = hosted(big, "--plan-bucket", BUCKET)
    assert code == 0, out
    saved, env_text = state.load(f"{NAME}.preview.example")
    resumed = settings.from_saved(saved, env_text)
    assert resumed.plan_bucket == BUCKET and len(starter.unpack(resumed.company_file_data)["bots"]) == 300
    assert envfile.parse(envfile.render(resumed.to_env()))["TICO_COMPANY_FILE_S3"].startswith(f"s3://{BUCKET}/plans/{NAME}/")


def test_without_the_plan_bucket_a_chart_over_the_env_limit_is_refused_before_any_cloud_change(big):
    d, ec2, iam, ssm, r53 = world()
    code, out = go([*CREATE, "--company-file", str(big)], d)
    assert code != 0 and "import the file in the app instead" in out
    assert not ssm.called("put_parameter") and not ec2.called("run_instances")


def test_a_301_seat_chart_gets_the_plain_300_error_even_by_the_plan_bucket(big, tmp_path):
    extra = "  - id: one-too-many\n    template: bookkeeping\n    title: One Too Many\n"
    over = tmp_path / "over.yaml"
    over.write_text(big.read_text().replace("employees:\n", "employees:\n" + extra, 1))
    with pytest.raises(MissingInput, match="more than 300 entries"):
        wizard.gather_company_file(argparse.Namespace(company_file=str(over), company=None, plan_bucket=BUCKET),
                                   settings.Settings(preset="recommended"))


def test_the_plan_bucket_is_for_aws_only_and_takes_bucket_and_region_names(big):
    d, *_ = world()
    for argv, said in ((["--plan-bucket", "Not_A_Bucket"], "S3 bucket name"),
                       (["--plan-bucket", BUCKET, "--plan-bucket-region", "west"], "AWS region")):
        code, out = go([*CREATE, "--company-file", str(big), *argv], d)
        assert code != 0 and said in out
    code, out = go(["--target", "ssh", "--ssh", "root@203.0.113.9", "--domain", "tico.example.com", "--plan-bucket", BUCKET,
                    "--non-interactive", "--yes"], d)
    assert code != 0 and "for a server on AWS" in out


def test_deleting_a_plan_already_gone_is_fine_and_any_other_failure_is_not():
    deployer = aws.Deployer(aws.plan_aws(domain="a.example", front_door="caddy", region="us-east-1", name=NAME,
                                         plan_bucket=BUCKET), None, None, None, "123456789012")
    deployer.delete_plan(FakeS3("us-west-2", [], ClientError("NoSuchKey")), f"plans/{NAME}/x")
    with pytest.raises(ClientError):
        deployer.delete_plan(FakeS3("us-west-2", [], ClientError("AccessDenied")), f"plans/{NAME}/x")
    with pytest.raises(ValueError):
        deployer.put_plan(FakeS3("us-west-2", []), "plans/pv-other/x", "data")


# --- the copy at first boot, run here: pull-env.sh's plan lines with a stand-in `aws` and `chown` -----------------------

def boot(tmp_path, monkeypatch, plan: bytes, sha: str, existing: bytes | None = None):
    root = tmp_path / "opt"
    monkeypatch.setattr(contract, "REMOTE_DIR", str(root))
    bin_dir, source = tmp_path / "bin", tmp_path / "bucket-object"
    bin_dir.mkdir()
    source.write_bytes(plan)
    # aws s3 cp --only-show-errors --region R SRC DST: the bucket object is `source`; it logs each call.
    (bin_dir / "aws").write_text(f'#!/bin/sh\necho "$@" >> {tmp_path}/aws.log\ncp {source} "$7"\n')
    (bin_dir / "chown").write_text("#!/bin/sh\nexit 0\n")
    for f in bin_dir.iterdir():
        f.chmod(0o755)
    folder = root / contract.COMPANY_FILE_DIR
    folder.mkdir(parents=True)
    if existing is not None:
        (folder / contract.COMPANY_FILE_NAME).write_bytes(existing)
    (root / ".env").write_text(f"TICO_COMPANY_FILE_S3=s3://{BUCKET}/plans/{NAME}/{sha}\nTICO_COMPANY_FILE_S3_REGION=us-west-2\n"
                               f"TICO_COMPANY_FILE_SHA256={sha}\n")
    script = "set -eu\numask 077\n" + "\n".join(remote.plan_copy_lines()) + "\n"
    run = subprocess.run(["sh", "-c", script], capture_output=True, text=True,
                         env={**os.environ, "PATH": f"{bin_dir}:{os.environ['PATH']}"})
    calls = (tmp_path / "aws.log").read_text() if (tmp_path / "aws.log").exists() else ""
    return run, folder / contract.COMPANY_FILE_NAME, calls


def test_the_server_copies_the_plan_once_private_and_read_only(tmp_path, monkeypatch):
    plan = b"H4sIAAAAAAAA/plan"
    run, copy, calls = boot(tmp_path, monkeypatch, plan, hashlib.sha256(plan).hexdigest())
    assert run.returncode == 0, run.stderr
    assert copy.read_bytes() == plan and stat.S_IMODE(copy.stat().st_mode) == 0o400
    assert calls.split() == ["s3", "cp", "--only-show-errors", "--region", "us-west-2", f"s3://{BUCKET}/plans/{NAME}/"
                             + hashlib.sha256(plan).hexdigest(), str(copy) + ".new"]


def test_a_sha256_mismatch_fails_the_boot_loudly_and_leaves_no_plan(tmp_path, monkeypatch):
    run, copy, _ = boot(tmp_path, monkeypatch, b"tampered", "0" * 64)
    assert run.returncode == 3 and "FAILED: the starter plan" in run.stderr and "not starting Tico" in run.stderr
    assert not copy.exists() and not Path(str(copy) + ".new").exists()


def test_a_copy_already_in_place_is_kept_once_the_bucket_object_is_gone(tmp_path, monkeypatch):
    plan = b"H4sIAAAAAAAA/plan"
    run, copy, calls = boot(tmp_path, monkeypatch, b"never fetched", hashlib.sha256(plan).hexdigest(), existing=plan)
    assert run.returncode == 0, run.stderr
    assert copy.read_bytes() == plan and calls == ""


def test_every_aws_boot_makes_the_folder_compose_mounts_even_without_a_plan():
    script = remote.bootstrap_script(os_family="ubuntu", domain="a.example", front_door="caddy", compose=None,
                                     compose_url="https://example.com/compose.yaml", env_param=("/tico/a/env", "us-east-1"))
    folder = f"{contract.REMOTE_DIR}/{contract.COMPANY_FILE_DIR}"
    assert f"mkdir -p {folder}" in script and f"chmod 700 {folder}" in script
    assert script.index("pull-env.sh\n") < script.index("docker compose up")
