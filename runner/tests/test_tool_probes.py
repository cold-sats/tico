"""A computer whose bots' GitHub sign-in or browser is broken is reported, and the token never leaves the probe."""
import io
import subprocess
import urllib.error

from backend.models import StructuredReadiness
from runner import tool_probes


class Hub:
    def __init__(self, answer):
        self.answer = answer

    def post(self, path, body):
        return self.answer


def test_github_401_is_reported_without_the_token_and_outages_are_not():
    def refused(request, timeout):
        assert request.get_header("Authorization") == "token ghs_secret"
        raise urllib.error.HTTPError(request.full_url, 401, "Unauthorized", {}, io.BytesIO(b'{"message":"Bad credentials"}'))
    result = tool_probes.github(Hub({"configured": True, "token": "ghs_secret"}), ["alpha"], opener=refused)
    assert result["ok"] is False and result["error"] == "alpha: GitHub answered 401 Bad credentials"
    assert "ghs_secret" not in repr(result)
    StructuredReadiness.model_validate({"github_auth": result})

    def down(request, timeout):
        raise urllib.error.HTTPError(request.full_url, 503, "Unavailable", {}, io.BytesIO(b""))
    assert tool_probes.github(Hub({"configured": True, "token": "ghs_secret"}), ["alpha"], opener=down) is None
    assert tool_probes.github(Hub({"configured": False}), ["alpha"], opener=refused) is None


def test_a_browser_missing_libraries_is_reported(tmp_path, monkeypatch):
    monkeypatch.setenv("PLAYWRIGHT_BROWSERS_PATH", str(tmp_path))
    assert tool_probes.browser() is None                   # no browser installed: nothing to check
    chrome = tmp_path / "chromium_headless_shell-1194" / "chrome-linux" / "headless_shell"
    chrome.parent.mkdir(parents=True)
    chrome.write_text("")
    chrome.chmod(0o755)
    said = ("headless_shell: error while loading shared libraries: libglib-2.0.so.0: "
            "cannot open shared object file: No such file or directory\n")
    result = tool_probes.browser(run=lambda args, **kw: subprocess.CompletedProcess(args, 127, "", said))
    assert result["ok"] is False and "libglib-2.0.so.0" in result["error"]
    StructuredReadiness.model_validate({"browser_launch": result})
