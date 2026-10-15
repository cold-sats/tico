"""The runner engine switch (runner/engine.py): the Rust runner by default, Python when asked or when Rust can't run."""

import gzip
import hashlib
import json
import os

import pytest

from runner import engine
from runner.version import RUNNER_VERSION


def fake_binary(path, version, build_id):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("#!/bin/sh\ncase \"$1\" in\n"
                    f"  --version) echo 'tico-runner {version}' ;;\n  --build-id) echo '{build_id}' ;;\n  *) exit 2 ;;\nesac\n")
    path.chmod(0o755)
    return path


def checkout(tmp_path):
    root = tmp_path / "checkout"
    (root / "runner-rs" / "src").mkdir(parents=True)
    (root / "runner-rs" / "src" / "main.rs").write_text("fn main() {}\n")
    return root


@pytest.fixture(autouse=True)
def fresh_status(monkeypatch):
    monkeypatch.setattr(engine, "STATUS", {"name": "python", "build": "", "note": ""})
    monkeypatch.setattr(engine, "_WAIT", {"on": False, "checked": 0.0, "started": 0.0})


def test_rust_is_the_default_and_python_only_when_asked_or_handed_back(tmp_path, monkeypatch):
    calls = []
    execv = lambda program, argv, env: calls.append((program, argv, env))  # noqa: E731
    argv = ["--config", "/x/runner.json", "run"]
    given = str(fake_binary(tmp_path / "bin" / "tico-runner", RUNNER_VERSION, engine.source_id(engine.ROOT)))
    cases = [  # (runner.json, environment, runs Rust, the note readiness shows)
        ({}, {}, True, ""),
        ({"engine": "rust"}, {}, True, ""),
        ({"engine": "python"}, {}, False, '"engine": "python" in runner.json'),
        ({"engine": "rust"}, {"TICO_RUNNER_ENGINE": "python"}, False, "TICO_RUNNER_ENGINE=python"),
        ({"engine": "python"}, {"TICO_RUNNER_ENGINE": "rust"}, True, ""),
        ({}, {engine.FALLBACK: "the Rust runner does not run this yet: ana needs the pi runtime"}, False,
         "the Rust runner does not run this yet: ana needs the pi runtime"),
    ]
    for config, env, rust, note in cases:
        monkeypatch.setenv(engine.FALLBACK, "x")
        engine.maybe_exec(config, argv, env={"TICO_RUNNER_BIN": given, "PATH": "", **env}, execv=execv)
        assert engine.FALLBACK not in os.environ          # a hand-back holds for this start only
        assert bool(calls) == rust, (config, env)
        assert engine.report() == ({"name": "rust", "build": engine.source_id(engine.ROOT)} if rust else {"name": "python", "note": note})
        if rust:
            program, args, sent = calls.pop()
            assert (program, args[1:]) == (given, argv)
            assert json.loads(sent["TICO_RUNNER_PYTHON_ARGV"])[-3:] == argv and engine.FALLBACK not in sent
    assert not engine.switch_due(clock=lambda: 10 ** 6)  # chosen or handed back: nothing to wait for


def test_a_missing_binary_stays_on_python_then_switches_once_it_is_built(tmp_path):
    root = checkout(tmp_path)
    prepared = []
    stale = fake_binary(tmp_path / "old" / "tico-runner", "0.0.1", engine.source_id(root))
    env = {"TICO_RUNNER_BIN": str(stale)}
    chose = engine.choose({}, env, root=root, fetching=lambda *a: False, preparing=lambda *a: prepared.append(a) or True)
    assert chose is None and prepared
    assert engine.report()["name"] == "python" and "being built" in engine.report()["note"]
    assert not engine.switch_due(env, root, clock=lambda: 10 ** 6)       # not built yet
    own = fake_binary(root / "runner-rs" / "target" / "release" / "tico-runner", RUNNER_VERSION, engine.source_id(root))
    assert not engine.switch_due(env, root, clock=lambda: 10 ** 6 + 1)   # looked a moment ago
    assert engine.switch_due(env, root, clock=lambda: 10 ** 7)
    # Built from older sources: not run, however its version reads.
    (root / "runner-rs" / "src" / "main.rs").write_text("fn main() { run() }\n")
    assert engine.choose({}, env, root=root, fetching=lambda *a: False, preparing=lambda *a: False) is None
    assert engine.report()["note"].startswith("no Rust runner here")
    fake_binary(own, RUNNER_VERSION, engine.source_id(root))
    assert engine.choose({}, env, root=root, fetching=lambda *a: False, preparing=lambda *a: False) == own


def test_a_release_checkout_downloads_its_binary_only_when_the_checksum_matches(tmp_path, monkeypatch):
    root = checkout(tmp_path)
    name = engine.asset()
    if not name:
        pytest.skip("no release binary for this platform")
    script = fake_binary(tmp_path / "built" / "tico-runner", RUNNER_VERSION, engine.source_id(root)).read_bytes()
    release = tmp_path / "releases" / "download" / "v0.3.46"
    release.mkdir(parents=True)
    (release / name).write_bytes(gzip.compress(script))
    env = {"TICO_RUNNER_RELEASES": (tmp_path / "releases").as_uri()}
    (release / engine.SUMS).write_text(f"{'0' * 64}  {name}\n")
    assert not engine.fetch(root, env, release="0.3.46")
    assert not engine.dist(root).exists()
    (release / engine.SUMS).write_text(f"{hashlib.sha256((release / name).read_bytes()).hexdigest()}  {name}\n")
    assert engine.fetch(root, env, release="0.3.46")
    assert engine.ready(env, root) == engine.dist(root)
    assert not engine.fetch(root, env, release="")                     # a checkout on main has nothing to download
