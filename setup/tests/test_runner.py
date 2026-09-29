import io as _io
import json

import pytest

from setup import cli, runner_setup as rs, state, verify
from setup.remote import Result
from setup.tests import fakes
from setup.tests.fakes import CaptureIO, FakeShell, aws_clients

CODE = "one-time-code-abcdefghijklmnopqrstuvwxyz0123456789"


def go(argv, deps=None):
    io = CaptureIO()
    return cli.main(argv, deps=deps or fakes.deps(), io=io), io.text


def test_join_env_is_shell_safe():
    env = rs.join_env("https://t", CODE, "my box; rm -rf /")
    assert "TICO_JOIN_LABEL='my box; rm -rf /'" in env


def test_join_script_is_idempotent_and_removes_the_code_file():
    text = "\n".join(rs.join_lines("v1", "/x/join.env"))
    assert "grep -qx tico-runner" in text and "docker run" not in text
    assert "releases/download/v1/install.sh | sh -s -- --runner" in text
    assert '--url "$TICO_JOIN_URL" --code "$TICO_JOIN_CODE" --label "$TICO_JOIN_LABEL"' in text
    assert "releases/latest/download/install.sh" in "\n".join(rs.join_lines("latest", "/x/join.env"))
    assert text.rstrip().endswith("rm -f /x/join.env")
    rejoin = "\n".join(rs.join_lines("v1", "/x/join.env", rejoin=True))
    assert "docker rm -f" in rejoin and "rm -f /opt/tico-runner/.env" in rejoin  # a new code needs a new .env


def test_aws_bootstrap_takes_the_code_from_ssm_not_from_user_data():
    s = rs.bootstrap_script(os_family="ubuntu", tag="latest", env_param=("/tico/runner-a/env", "us-east-1"))
    assert "ssm get-parameter" in s and CODE not in s


def test_dry_run_each_target_no_inbound_ports():
    args = ["runner", "--dry-run", "--non-interactive", "--server-url", "https://tico.example.com", "--label", "build-1"]
    code, out = go([*args, "--target", "aws"])
    assert code == 0 and "no inbound rules at all" in out and "t4g.medium" in out and "per bot" in out
    code, out = go([*args, "--target", "ssh", "--ssh", "me@10.0.0.5"])
    assert code == 0 and "install.sh --runner" in out
    code, out = go([*args, "--target", "command"])
    assert code == 0 and "one-time join code" in out


def test_ssh_target_mints_code_late_and_passes_it_by_stdin(monkeypatch):
    monkeypatch.setenv("TICO_OWNER_TOKEN", "owner-token-xyz")
    monkeypatch.setattr(rs, "mint_code", lambda url, tok: CODE)
    shell = FakeShell({"docker ps": Result(0, "Up 3 seconds\n")})
    d = fakes.deps()
    d.ssh_shell = lambda *a: shell
    monkeypatch.setattr(verify, "check_computer_online", lambda *a: None)
    code, out = go(["runner", "--non-interactive", "--yes", "--server-url", "https://tico.example.com", "--target", "ssh",
                    "--ssh", "root@10.0.0.5", "--label", "build-1"], deps=d)
    assert code == 0, out
    assert CODE not in out and "owner-token-xyz" not in out
    assert any(CODE.encode() in (i or b"") for _, i in shell.calls) and not any(CODE in c for c in shell.cmds())
    assert state.load_runners("https://tico.example.com")[0]["label"] == "build-1"


def test_missing_code_is_a_clear_error_in_non_interactive_mode():
    shell = FakeShell()
    d = fakes.deps()
    d.ssh_shell = lambda *a: shell
    code, out = go(["runner", "--non-interactive", "--yes", "--server-url", "https://t.example.com", "--target", "ssh",
                    "--ssh", "root@h", "--label", "x"], deps=d)
    assert code == 2 and "TICO_ENROLL_CODE" in out


def test_aws_runner_stores_code_in_parameter_and_verifies_over_ssm(monkeypatch):
    monkeypatch.setenv("TICO_ENROLL_CODE", CODE)
    ec2, iam, ssm, factory = aws_clients()
    ssm.commands.clear()
    d = fakes.deps()
    d.aws_clients = factory
    monkeypatch.setattr(verify, "check_runner_container", lambda sh, label="": verify.Check("Runner container", True, "Up"))
    code, out = go(["runner", "--non-interactive", "--yes", "--server-url", "https://tico.example.com", "--target", "aws",
                    "--label", "build-1"], deps=d)
    assert code == 0, out
    (run,) = ec2.called("run_instances")
    assert CODE not in run["UserData"] and CODE not in out
    assert CODE in ssm.called("put_parameter")[0]["Value"]
    assert run["InstanceType"] == "t4g.medium" and run["MetadataOptions"]["HttpPutResponseHopLimit"] == 1
    assert not ec2.called("authorize_security_group_ingress") and not ec2.called("allocate_address")
    assert {"Key": "tico-setup-name", "Value": "runner-build-1"} in run["TagSpecifications"][0]["Tags"]


def test_mint_code_uses_bearer_and_maps_errors():
    seen = {}

    class Resp(_io.BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, *a):
            pass

    def opener(req, timeout):
        seen["auth"], seen["url"] = req.get_header("Authorization"), req.full_url
        seen["key"] = req.get_header("Idempotency-key")
        return Resp(json.dumps({"code": CODE}).encode())

    assert rs.mint_code("https://t/", "tok", opener) == CODE
    assert seen["auth"] == "Bearer tok" and seen["url"] == "https://t/api/v2/enrollments"
    assert seen["key"]  # the server refuses a write without an Idempotency-Key


def test_computer_online_check_reads_the_server_list():
    class Resp(_io.BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, *a):
            pass

    def rows(data):
        return lambda req, timeout: Resp(json.dumps(data).encode())

    def machines(*rows_):
        return rows(({"server_time": "2026-10-01T12:00:30.000000Z", "machines": list(rows_)}))

    fresh = {"label": "a", "last_seen": "2026-10-01T12:00:10.000000Z", "revoked_at": None}
    assert verify.check_computer_online("https://t", "tok", "a", get=machines(fresh)).ok
    assert not verify.check_computer_online("https://t", "tok", "b", get=machines(fresh)).ok
    assert not verify.check_computer_online("https://t", "tok", "a", get=machines({**fresh, "last_seen": "2026-10-01T11:58:00.000000Z"})).ok
    assert not verify.check_computer_online("https://t", "tok", "a", get=machines({**fresh, "revoked_at": "2026-10-01T12:00:00Z"})).ok
