"""The cloudflared profile's route: HQ_DOMAIN to HQ, a 404 for the rest, readable by cloudflared's own user."""

import re
import stat
from pathlib import Path

import pytest
import yaml

from hq import tunnel


def test_the_route_names_the_domain_and_ends_in_a_404_readable_by_everyone(tmp_path):
    path = tunnel.prepare({"HQ_DOMAIN": "hq.example.test", "HQ_TUNNEL_DIR": str(tmp_path)})
    assert path.read_text() == ("ingress:\n  - hostname: hq.example.test\n    service: http://hq:8770\n"
                                "  - service: http_status:404\n")
    assert stat.S_IMODE(path.stat().st_mode) == 0o644 and stat.S_IMODE(tmp_path.stat().st_mode) == 0o755
    assert not list(tmp_path.glob("*.new"))
    # Written again at every start: a changed HQ_DOMAIN follows, and no domain leaves only the 404.
    tunnel.prepare({"HQ_DOMAIN": "", "HQ_TUNNEL_DIR": str(tmp_path)})
    assert path.read_text() == "ingress:\n  - service: http_status:404\n"


def test_a_bad_domain_stops_hq_and_no_volume_writes_nothing(tmp_path):
    for bad in ("hq.example.test\n  - service: x", "https://hq.example.test", ".hq.example.test", "hq example"):
        with pytest.raises(SystemExit) as refused:
            tunnel.prepare({"HQ_DOMAIN": bad, "HQ_TUNNEL_DIR": str(tmp_path)})
        assert "HQ_DOMAIN" in str(refused.value)
    assert not list(tmp_path.iterdir())
    assert tunnel.prepare({"HQ_DOMAIN": "hq.example.test", "HQ_TUNNEL_DIR": str(tmp_path / "absent")}) is None


def test_the_backup_runs_as_the_hq_image_user_that_owns_the_database():
    hq_dir = Path(__file__).resolve().parent.parent
    compose = yaml.safe_load((hq_dir / "compose.yaml").read_text())
    image_user = re.search(r"^USER (\S+)", (hq_dir / "Dockerfile").read_text(), re.M).group(1)
    assert compose["services"]["backup"]["user"] == image_user == "10005:10005"
