"""The runner engine switch (runner/engine.py): exec the Rust runner only when it is asked for and current."""

import json
import os

from runner import engine
from runner.service import RUNNER_VERSION


def fake_binary(path, version):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"#!/bin/sh\necho 'tico-runner {version}'\n")
    path.chmod(0o755)
    return path


def test_a_current_rust_binary_takes_the_process_and_anything_else_stays_in_python(tmp_path):
    calls = []
    execv = lambda program, argv, env: calls.append((program, argv, env))  # noqa: E731
    argv = ["--config", "/x/runner.json", "run"]
    given = fake_binary(tmp_path / "bin" / "tico-runner", RUNNER_VERSION)

    engine.maybe_exec({}, argv, env={"TICO_RUNNER_BIN": str(given)}, execv=execv)
    engine.maybe_exec({"engine": "rust"}, argv, env={"TICO_RUNNER_ENGINE": "python", "TICO_RUNNER_BIN": str(given)}, execv=execv)
    assert calls == []                                   # not asked for, or turned off for this start

    engine.maybe_exec({"engine": "rust"}, argv, env={"TICO_RUNNER_BIN": str(given), "PATH": ""}, execv=execv)
    program, args, env = calls.pop()
    assert (program, args[1:]) == (str(given), argv)
    assert json.loads(env["TICO_RUNNER_PYTHON_ARGV"])[-3:] == argv  # a refusal comes back here

    # A stale binary and no checkout build or cargo: one log line, and Python runs.
    stale = fake_binary(tmp_path / "old" / "tico-runner", "0.0.1")
    assert engine.choose({"engine": "rust"}, {"TICO_RUNNER_BIN": str(stale)}, root=tmp_path, building=lambda *a: False) is None
    # The checkout's own build is used when it is current, and rebuilt (once) when it is older than its sources.
    own = fake_binary(tmp_path / "runner-rs" / "target" / "release" / "tico-runner", RUNNER_VERSION)
    source = tmp_path / "runner-rs" / "src" / "main.rs"
    source.parent.mkdir(parents=True)
    source.write_text("fn main() {}\n")
    os.utime(own, (1, 1))
    built = []
    rebuild = lambda root, env: built.append(root) or os.utime(own) or True  # noqa: E731
    assert engine.choose({"engine": "rust"}, {"TICO_RUNNER_BIN": str(stale)}, root=tmp_path, building=rebuild) == own
    assert built == [tmp_path]
