"""Where the mail connector keeps things: the Mac layout by default, named places on a Linux runner."""
import os
import subprocess
from pathlib import Path

from connectors.mail import locations

HUB = Path("/Users/x/tico-work/tico")
ROOT = Path(__file__).resolve().parents[3]


def test_a_mac_keeps_everything_beside_the_checkout():
    projects, runtime = locations({}, HUB)
    assert projects == Path("/Users/x/tico-work")
    assert runtime == projects / "runtime" / "mail"


def test_a_linux_runner_names_its_places():
    env = {"TICO_PROJECTS_DIR": "/home/runner/workspace"}
    assert locations(env, HUB) == (Path("/home/runner/workspace"), Path("/home/runner/workspace/runtime/mail"))
    env["TICO_MAIL_RUNTIME_DIR"] = "/var/lib/mail"
    assert locations(env, HUB)[1] == Path("/var/lib/mail")


def venv_of(env):
    """The venv scripts/mail.sh would use, read by running it with a python that only says so."""
    fake = ROOT / "scripts/mail.sh"
    text = fake.read_text().split('if [ ! -x')[0] + 'echo "$VENV"\n'
    done = subprocess.run(["bash", "-c", text.replace('"$(dirname "$0")/.."', '"' + str(ROOT) + '"')],
                          capture_output=True, text=True, env={"PATH": os.environ["PATH"], **env})
    return done.stdout.strip()

