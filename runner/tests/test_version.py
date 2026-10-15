"""runner/version.py names the Rust runner's version, for scripts/tico and the Python helpers."""
import re
from pathlib import Path

from runner.version import RUNNER_VERSION

ROOT = Path(__file__).resolve().parents[2]


def test_the_version_is_the_rust_runners():
    rust = (ROOT / "runner-rs/src/runner.rs").read_text()
    assert re.search(r'pub const RUNNER_VERSION: &str = "([^"]+)";', rust).group(1) == RUNNER_VERSION
