"""Tests read the registry from a fictional company, never from a real environment's."""
import os
from pathlib import Path

os.environ["TICO_REGISTRY_DIR"] = str(Path(__file__).parent / "backend/tests/fixtures/registry")
# The update check would otherwise call GitHub from every test that reads /api/v2/config.
os.environ["TICO_UPDATE_CHECK"] = "off"
# A runner readiness call would otherwise start real containers on whoever's computer runs the suite.
os.environ["TICO_RUNNER_CONTAINER_PROBE"] = "off"
# A test that misses a stub must fail, not act in whoever's AWS account runs the suite: one already
# created a real bucket. Fake keys and no profile or config files make any real AWS call unauthorized.
for _name in ("AWS_PROFILE", "AWS_DEFAULT_PROFILE", "AWS_SESSION_TOKEN", "AWS_ROLE_ARN", "AWS_WEB_IDENTITY_TOKEN_FILE"):
    os.environ.pop(_name, None)
os.environ.update({"AWS_ACCESS_KEY_ID": "testing", "AWS_SECRET_ACCESS_KEY": "testing",
                   "AWS_CONFIG_FILE": os.devnull, "AWS_SHARED_CREDENTIALS_FILE": os.devnull,
                   "AWS_EC2_METADATA_DISABLED": "true"})


import pytest  # noqa: E402


def pytest_configure(config):
    """A test path that does not exist is an error. Under -n (on by default here) xdist drops it without a word,
    and the run ends as "no tests ran", which a reader piping the output can take for a pass."""
    if hasattr(config, "workerinput") or config.option.pyargs:
        return          # --pyargs names modules, not paths
    base = Path(config.invocation_params.dir)
    missing = [str(arg) for arg in config.args if not (base / str(arg).split("::")[0]).exists()]
    if missing:
        raise pytest.UsageError("No such test path: " + ", ".join(missing))


def pytest_sessionfinish(session, exitstatus):
    """Zero collected tests is a failure (exit 5) and says so in an error line, not only in the exit code."""
    if exitstatus == pytest.ExitCode.NO_TESTS_COLLECTED and not hasattr(session.config, "workerinput"):
        session.config.get_terminal_writer().line(
            "ERROR: no tests were collected; check the test paths and the -m / -k filters", red=True, bold=True)
