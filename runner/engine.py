"""The one switch between runner engines: `python -m runner run` hands the process to the Rust runner
(runner-rs/), the default. `"engine": "python"` in runner.json or TICO_RUNNER_ENGINE=python keeps the Python runner
(the environment wins); it is deprecated and goes in the next release.

The binary is $TICO_RUNNER_BIN (the Docker image's), else this checkout's runner-rs/target/release/tico-runner, else
the one downloaded for this release (runner-rs/target/dist/<source id>/tico-runner), and only one whose `--version` is
this checkout's RUNNER_VERSION and whose `--build-id` is this checkout's source fingerprint (`source_id`, stamped in by
runner-rs/build.rs), so a checkout that moved on while the binary stayed put is never run. A checkout on a release tag
downloads that release's binary from GitHub (checked against the release's tico-runner-SHA256SUMS); otherwise, with
cargo on PATH, it is built in the background, behind a lock. Until then the Python runner carries on, says why in
readiness (`engine`), and restarts onto the Rust runner once the binary is there (`switch_due`). A computer never
goes down over the switch.

The Rust runner gets TICO_RUNNER_PYTHON_ARGV: a computer it cannot run yet (a bot on a runtime it does not
drive) execs back into this Python runner with TICO_RUNNER_ENGINE_FALLBACK saying why.
"""

import fcntl
import gzip
import hashlib
import json
import os
import platform
import shutil
import subprocess
import sys
import time
import urllib.request
import zlib
from pathlib import Path

from .outage import log
from .version import RUNNER_VERSION

ROOT = Path(__file__).resolve().parents[1]
BUILD_TIMEOUT_S = 1800
RELEASES = "https://github.com/ticoteam/tico/releases"
SUMS = "tico-runner-SHA256SUMS"
FETCH_TIMEOUT_S = 30
MAX_BINARY_BYTES = 64 << 20
FALLBACK = "TICO_RUNNER_ENGINE_FALLBACK"
CHECK_EVERY_S = 300           # a Python runner waiting on the binary looks for it this often
RETRY_EVERY_S = 3600          # and starts another download or build this often

# What this process runs, for readiness (`engine`): a Python runner says why it is not on the Rust runner.
STATUS = {"name": "python", "build": "", "note": ""}
_WAIT = {"on": False, "checked": 0.0, "started": 0.0}


def report():
    return {key: value for key, value in STATUS.items() if value}


def stay(note, waiting=False):
    """Stay on the Python runner, saying why in the log and in readiness."""
    STATUS.update(name="python", build="", note=note[:300])
    _WAIT["on"] = waiting
    log(f"Tico runner: {note}; running the Python runner")


def wanted(config, env):
    """(True, "") for the Rust runner, the default, or (False, why) for the Python one."""
    if env.get(FALLBACK):
        return False, str(env[FALLBACK])
    choice = str(env.get("TICO_RUNNER_ENGINE") or "").strip().lower()
    if choice:
        return (True, "") if choice != "python" else (False, "TICO_RUNNER_ENGINE=python")
    if str((config or {}).get("engine") or "").strip().lower() == "python":
        return False, '"engine": "python" in runner.json'
    return True, ""


def _ask(binary, flag):
    """The last word `binary flag` prints, or "" when it fails (a binary from before --build-id fails)."""
    try:
        out = subprocess.run([str(binary), flag], capture_output=True, text=True, timeout=10, stdin=subprocess.DEVNULL)
    except (OSError, subprocess.SubprocessError):
        return ""
    words = out.stdout.split() if out.returncode == 0 else []
    return words[-1] if words else ""


def version_of(binary):
    return _ask(binary, "--version")


def source_id(root):
    """The source fingerprint runner-rs/build.rs stamps into the binary, or "" when this tree has no runner-rs:
    the first 16 hex digits of the SHA-256 of `path \0 length \0 bytes` for every file of runner-rs/build.rs,
    Cargo.toml, Cargo.lock, runner-rs/src/** and runner/harnesses/*.toml, sorted by path from `root`."""
    root = Path(root)
    if not (root / "runner-rs" / "src").is_dir():
        return ""
    paths = [root / "runner-rs" / name for name in ("build.rs", "Cargo.toml", "Cargo.lock")]
    paths += [p for p in (root / "runner-rs" / "src").rglob("*")]
    paths += list((root / "runner" / "harnesses").glob("*.toml"))
    digest = hashlib.sha256()
    for name, path in sorted((p.relative_to(root).as_posix(), p) for p in paths if p.is_file()):
        data = path.read_bytes()
        digest.update(f"{name}\0{len(data)}\0".encode())
        digest.update(data)
    return digest.hexdigest()[:16]


def current(binary, root):
    """Why `binary` cannot run this checkout, or "" when it can. The fingerprint applies to $TICO_RUNNER_BIN too:
    the image builds it from the tree it ships, so there it always matches."""
    if not binary.is_file() or not os.access(binary, os.X_OK):
        return f"{binary} is missing"
    found = version_of(binary)
    if found != RUNNER_VERSION:
        return f"{binary} is version {found or 'unknown'}, this checkout is {RUNNER_VERSION}"
    wanted = source_id(root)
    if wanted and _ask(binary, "--build-id") != wanted:
        return f"{binary} was built from other runner-rs sources"
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
        if not current(crate / "target" / "release" / "tico-runner", root):
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


def asset(system=sys.platform, machine=None):
    """This computer's release asset name ("tico-runner-macos-arm64.gz"), or "" when no release builds one."""
    name = {"darwin": "macos", "linux": "linux"}.get(system)
    arch = {"arm64": "arm64", "aarch64": "arm64", "x86_64": "x86_64", "amd64": "x86_64"}.get(
        (machine or platform.machine()).lower())
    return f"tico-runner-{name}-{arch}.gz" if name and arch else ""


def dist(root):
    """Where a downloaded binary for this tree lives: one folder per source fingerprint, so a rollback finds its own."""
    return Path(root) / "runner-rs" / "target" / "dist" / (source_id(root) or "none") / "tico-runner"


def candidates(env, root):
    given = str(env.get("TICO_RUNNER_BIN") or "").strip()
    return [*([Path(given)] if given else []), Path(root) / "runner-rs" / "target" / "release" / "tico-runner", dist(root)]


def ready(env, root):
    """The first current binary, or None."""
    return next((binary for binary in candidates(env, root) if not current(binary, root)), None)


def _get(url, limit):
    with urllib.request.urlopen(url, timeout=FETCH_TIMEOUT_S) as reply:
        data = reply.read(limit + 1)
    if len(data) > limit:
        raise ValueError(f"{url} is larger than {limit} bytes")
    return data


def fetch(root, env, release=None):
    """Download this release's binary, checked against the release's checksums, into `dist(root)`. Only a checkout on
    a release tag has one to download. True when it is there and current."""
    if release is None:
        from .release_update import checkout_release
        release = checkout_release(root)
    name = asset()
    if not (release and name and source_id(root)):
        return False
    base = f"{(env.get('TICO_RUNNER_RELEASES') or RELEASES).rstrip('/')}/download/v{release.lstrip('v')}/"
    target = dist(root)
    try:
        sums = _get(base + SUMS, 1 << 16).decode()
        want = next((line.split()[0] for line in sums.splitlines() if line.split()[1:] in ([name], ["*" + name])), "")
        if not want:
            raise ValueError(f"{name} is not in this release")
        data = _get(base + name, MAX_BINARY_BYTES)
        if hashlib.sha256(data).hexdigest() != want:
            raise ValueError(f"{name} does not match its checksum")
        binary = gzip.decompress(data)
        target.parent.mkdir(parents=True, exist_ok=True)
        part = target.with_name(f".tico-runner.{os.getpid()}")
        part.write_bytes(binary)
        part.chmod(0o755)
        os.replace(part, target)
    except (OSError, ValueError, EOFError, zlib.error) as exc:
        log(f"Tico runner: could not download the Rust runner for {release} ({exc})")
        return False
    problem = current(target, root)
    if problem:
        log(f"Tico runner: the downloaded Rust runner does not fit this checkout ({problem})")
        return False
    log(f"Tico runner: downloaded the Rust runner for {release}")
    return True


def prepare(root, env):
    """Download, else build, this checkout's binary, once at a time. True when one is current."""
    crate = Path(root) / "runner-rs"
    if not crate.is_dir():
        return False
    (crate / "target").mkdir(parents=True, exist_ok=True)
    with open(crate / "target" / "tico-runner-prepare.lock", "w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        return bool(ready(env, root) or fetch(root, env) or build(root, env))


def start_prepare(root, env):
    """Start `prepare` in the background, so this start never waits minutes on cargo. True when one was started."""
    if not (Path(root) / "runner-rs" / "src").is_dir():
        return False
    from .release_update import checkout_release
    if not (shutil.which("cargo", path=env.get("PATH")) or checkout_release(root)):
        return False
    try:
        subprocess.Popen([sys.executable, "-m", "runner.engine", "prepare"], cwd=str(root), stdin=subprocess.DEVNULL,
                         env={k: v for k, v in env.items() if k != FALLBACK}, start_new_session=True)
    except OSError as exc:
        log(f"Tico runner: could not start building the Rust runner ({exc})")
        return False
    _WAIT["started"] = time.monotonic()
    return True


def choose(config, env, root=ROOT, fetching=fetch, preparing=start_prepare):
    """The Rust binary to exec, or None to stay in Python (with the reason logged and kept for readiness)."""
    rust, why = wanted(config, env)
    if not rust:
        stay(why)
        return None
    problems = []
    for binary in candidates(env, root):
        problem = current(binary, root)
        if not problem:
            STATUS.update(name="rust", build=_ask(binary, "--build-id"), note="")
            return binary
        problems.append(problem)
    if fetching(root, env):
        STATUS.update(name="rust", build=source_id(root), note="")
        return dist(root)
    if preparing(root, env):
        stay("the Rust runner is being built; this computer switches to it once it is ready", waiting=True)
    else:
        stay(f"no Rust runner here: {problems[0]}", waiting=True)
    return None


def switch_due(env=None, root=ROOT, clock=time.monotonic):
    """True once a Python runner that was waiting on the binary can restart onto it. Looks every CHECK_EVERY_S, and
    starts another download or build every RETRY_EVERY_S."""
    if not _WAIT["on"] or clock() - _WAIT["checked"] < CHECK_EVERY_S:
        return False
    _WAIT["checked"] = clock()
    env = dict(os.environ if env is None else env)
    if ready(env, root):
        return True
    if clock() - _WAIT["started"] >= RETRY_EVERY_S:
        start_prepare(root, env)
    return False


def maybe_exec(config, argv, env=None, execv=os.execve):
    """Hand this process to the Rust runner when it is chosen; return only when staying in Python."""
    env = dict(os.environ if env is None else env)
    os.environ.pop(FALLBACK, None)            # this start's word only: a later restart chooses again
    try:
        binary = choose(config, env)
        if binary is None:
            return
        env.pop(FALLBACK, None)
        env.setdefault("TICO_ROOT", str(ROOT))
        env.setdefault("TICO_RUNNER_PYTHON", sys.executable)
        env["TICO_RUNNER_PYTHON_ARGV"] = json.dumps([sys.executable, "-m", "runner", *argv])
        log(f"Tico runner: running the Rust runner ({binary})")
        execv(str(binary), [str(binary), *argv], env)
    except Exception as exc:  # noqa: BLE001 - the switch never takes the computer down
        stay(f"could not start the Rust runner ({exc})")


def main(argv=None):
    """`python -m runner.engine prepare`: get this checkout's Rust runner now (scripts/tico install, a background build)."""
    args = sys.argv[1:] if argv is None else argv
    if args != ["prepare"]:
        print("usage: python -m runner.engine prepare", file=sys.stderr)
        return 2
    env = dict(os.environ)
    binary = ready(env, ROOT) if prepare(ROOT, env) else None
    print(f"Rust runner ready: {binary}" if binary else
          "No Rust runner for this checkout yet; the runner starts on Python and switches once one is built")
    return 0


if __name__ == "__main__":
    sys.exit(main())
