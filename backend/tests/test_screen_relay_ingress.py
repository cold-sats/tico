"""The pilot's actual Caddy ingress forwards only the screen sockets and hides private control."""
import contextlib
import os
from pathlib import Path
import subprocess

import httpx
import pytest

from backend.tests.test_screen_relay_contract import Service, service  # noqa: F401

pytestmark = pytest.mark.slow


@pytest.mark.parametrize("service", ["rust"], indirect=True)
def test_same_origin_proxy_preserves_socket_paths_and_refuses_private_control(service, tmp_path):
    binary = os.environ.get("TICO_CADDY_BIN", "")
    assert binary and Path(binary).is_file(), "Set TICO_CADDY_BIN to a Caddy 2 executable"
    reserved = Service.bind()
    port = reserved.getsockname()[1]
    reserved.close()
    origin = f"http://127.0.0.1:{port}"
    root = Path(__file__).resolve().parents[2]
    with (tmp_path / "caddy.log").open("w") as log:
        process = subprocess.Popen([binary, "run", "--config", str(root / "relay-rs/Caddyfile"), "--adapter", "caddyfile"],
            stdout=log, stderr=log, env={**os.environ, "TICO_SCREEN_LISTEN": origin,
                "TICO_SCREEN_RELAY_UPSTREAM": service.relay_url.removeprefix("http://"),
                "TICO_SCREEN_PYTHON_UPSTREAM": service.origin.removeprefix("http://"),
                "XDG_CONFIG_HOME": str(tmp_path / "config"), "XDG_DATA_HOME": str(tmp_path / "data")})
        try:
            def healthy():
                with contextlib.suppress(httpx.HTTPError):
                    return httpx.get(origin + "/healthz", timeout=.5).status_code == 200
                return False
            Service.eventually(healthy)
            with httpx.Client(base_url=origin, timeout=3) as client:
                for path in ("/control/v1/hello", "/_tico/screen/v1/authorize"):
                    assert client.post(path, json={}).status_code == 403
                assert client.get("/api/v2/tasks").status_code == 401
            r = service.computer()
            opened = service.opened(r)
            direct = service.relay_url
            service.relay_url = origin
            try:
                with service.websocket(opened["ws_path"], origin=service.origin) as browser:
                    with service.websocket(service.runner_path(opened), token=r["token"]) as runner:
                        browser.send(b"same public path"); assert runner.recv(timeout=5) == b"same public path"
                        runner.send(b"same bearer"); assert browser.recv(timeout=5) == b"same bearer"
            finally:
                service.relay_url = direct
        finally:
            process.terminate()
            try:
                process.wait(5)
            except subprocess.TimeoutExpired:
                process.kill(); process.wait(5)
