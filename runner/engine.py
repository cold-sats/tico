"""The one switch between runner engines: `python -m runner run` hands the process to the Rust runner
(runner-rs/) when runner.json says `"engine": "rust"` or the environment says
TICO_RUNNER_ENGINE=rust (the environment wins, so TICO_RUNNER_ENGINE=python turns it off for one start).

The binary is $TICO_RUNNER_BIN (the Docker image's), else this checkout's runner-rs/target/release/tico-runner,
and only one whose `--version` is this checkout's RUNNER_VERSION; the checkout's own build must also be newer
than its sources. A missing or stale build is rebuilt once with cargo when cargo is on PATH, behind a lock so
two runners never build together. Anything that goes wrong is one log line and the Python runner carries on,
so a computer never goes down over the switch, and rollback is removing the setting.

The Rust runner gets TICO_RUNNER_PYTHON_ARGV: a computer it cannot run yet (a bot on a runtime it does not
drive) execs back into this Python runner with TICO_RUNNER_ENGINE=python instead of exiting.
"""

import fcntl
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

from .service import RUNNER_VERSION, log

ROOT = Path(__file__).resolve().parents[1]
BUILD_TIMEOUT_S = 1800


def wanted(config, env):
    choice = str(env.get("TICO_RUNNER_ENGINE") or "").strip().lower()
    if choice:
        return choice == "rust"
    return str((config or {}).get("engine") or "").strip().lower() == "rust"


def version_of(binary):
    try:
        out = subprocess.run([str(binary), "--version"], capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.SubprocessError):
        return ""
    words = out.stdout.split() if out.returncode == 0 else []
    return words[-1] if words else ""


def _newest_source(root):
    crate = root / "runner-rs"
    paths = [crate / "Cargo.toml", crate / "Cargo.lock", *(crate / "src").rglob("*.rs")]
    return max((p.stat().st_mtime for p in paths if p.is_file()), default=0.0)


def current(binary, root, own):
    """Why `binary` cannot run this checkout, or "" when it can."""
    if not binary.is_file() or not os.access(binary, os.X_OK):
        return f"{binary} is missing"
    found = version_of(binary)
    if found != RUNNER_VERSION:
        return f"{binary} is version {found or 'unknown'}, this checkout is {RUNNER_VERSION}"
    if own and binary.stat().st_mtime < _newest_source(root):
        return f"{binary} is older than runner-rs/src"
    return ""


def build(root, env):
    """Build the checkout's release binary once; two runners wait on one build. True when it finished."""
    cargo = shutil.which("cargo", path=env.get("PATH"))
    if not cargo:
        return False
    crate = root / "runner-rs"
    (crate / "target").mkdir(parents=True, exist_ok=True)
    with open(crate / "target" / "tico-runner-build.lock", "w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        if not current(crate / "target" / "release" / "tico-runner", root, own=True):
            return True                      # another runner built it while this one waited
        log("Tico runner: building the Rust runner (cargo build --release); this takes a few minutes once")
        try:
            done = subprocess.run([cargo, "build", "--release", "--locked", "-q"], cwd=crate, env=env,
                                  stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=BUILD_TIMEOUT_S)
        except (OSError, subprocess.SubprocessError) as exc:
            log(f"Tico runner: the Rust runner did not build ({exc})")
            return False
        if done.returncode:
            log("Tico runner: the Rust runner did not build: " + (done.stderr.strip().splitlines() or ["cargo failed"])[-1][:300])
            return False
        return True


def choose(config, env, root=ROOT, building=build):
    """The Rust binary to exec, or None to stay in Python (with the reason logged)."""
    if not wanted(config, env):
        return None
    given = str(env.get("TICO_RUNNER_BIN") or "").strip()
    if given:
        binary = Path(given)
        problem = current(binary, root, own=False)
        if not problem:
            return binary
        log(f"Tico runner: engine is rust but {problem}; trying this checkout's build")
    binary = root / "runner-rs" / "target" / "release" / "tico-runner"
    problem = current(binary, root, own=True)
    if problem and building(root, env):
        problem = current(binary, root, own=True)
    if problem:
        log(f"Tico runner: engine is rust but {problem}; running the Python runner")
        return None
    return binary


def maybe_exec(config, argv, env=None, execv=os.execve):
    """Hand this process to the Rust runner when it is chosen; return only when staying in Python."""
    env = dict(os.environ if env is None else env)
    try:
        binary = choose(config, env)
        if binary is None:
            return
        env.setdefault("TICO_ROOT", str(ROOT))
        env.setdefault("TICO_RUNNER_PYTHON", sys.executable)
        env["TICO_RUNNER_PYTHON_ARGV"] = json.dumps([sys.executable, "-m", "runner", *argv])
        log(f"Tico runner: running the Rust runner ({binary})")
        execv(str(binary), [str(binary), *argv], env)
    except Exception as exc:  # noqa: BLE001 - the switch never takes the computer down
        log(f"Tico runner: could not start the Rust runner ({exc}); running the Python runner")
