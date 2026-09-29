import io as _io
import json

import pytest

from setup import cli, runner_setup as rs, state, verify
from setup.remote import Result
from setup.tests import fakes
from setup.tests.fakes import CaptureIO, FakeShell

CODE = "one-time-code-abcdefghijklmnopqrstuvwxyz0123456789"


def go(argv, deps=None):
    io = CaptureIO()
    return cli.main(argv, deps=deps or fakes.deps(), io=io), io.text


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

