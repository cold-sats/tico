"""What stays Python after the Python bot-turn engine (runner/service.py) goes must not need it."""
import re
import subprocess
import sys
from pathlib import Path

from runner.version import RUNNER_VERSION

ROOT = Path(__file__).resolve().parents[2]


def test_helpers_load_without_the_engine():
    code = ("import runner.__main__, runner.connectors, runner.close_calls, runner.importers.service, runner.catalog_job, "
            "runner.freshness, runner.repositories, runner.worktrees, runner.git_credentials, runner.credential_socket, "
            "runner.release_update, runner.engine; import sys; assert 'runner.service' not in sys.modules, 'loaded'")
    done = subprocess.run([sys.executable, "-c", code], cwd=ROOT, capture_output=True, text=True, timeout=60)
    assert done.returncode == 0, done.stderr


def test_the_version_is_the_rust_runners():
    rust = (ROOT / "runner-rs/src/runner.rs").read_text()
    assert re.search(r'pub const RUNNER_VERSION: &str = "([^"]+)";', rust).group(1) == RUNNER_VERSION
