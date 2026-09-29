"""Harness manifests and the runner's tool installer (runner/harness_tools.py).

No network: `npm` is a stub script first on PATH that "installs" a shell script per package and
answers `npm view` from a file the test controls, so the real subprocess flow runs end to end.
"""
import os
import stat
import tempfile
import textwrap
import time
import unittest
from pathlib import Path
from unittest import mock

from runner import harness_tools as H

FAKE_NPM = """#!/bin/sh
# fake npm: `install --prefix DIR pkg@version` and `view pkg version`
case "$1" in
  view) cat "$FAKE_LATEST"; exit 0 ;;
  install)
    [ -f "$FAKE_FAIL" ] && { echo "npm ERR! network" >&2; exit 1; }
    prefix="$3"
    for last; do :; done
    pkg="${last%@*}"; version="${last##*@}"
    [ "$version" = latest ] && version="$(cat "$FAKE_LATEST")"
    name="$(printf '%s' "$pkg" | sed 's|.*/||; s|-cli$||; s|-coding-agent$||')"
    case "$pkg" in @anthropic-ai/claude-code) name=claude ;; @xai-official/grok) name=grok ;;
      @earendil-works/pi-coding-agent) name=pi ;; @google/gemini-cli) name=gemini ;; esac
    mkdir -p "$prefix/node_modules/.bin"
    printf '#!/bin/sh\\necho "%s %s"\\n' "$name" "$version" > "$prefix/node_modules/.bin/$name"
    chmod +x "$prefix/node_modules/.bin/$name"
    exit 0 ;;
esac
exit 2
"""


def script(path, body):
    path.write_text("#!/bin/sh\n" + body + "\n")
    path.chmod(path.stat().st_mode | stat.S_IEXEC)


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.stubs = self.root / "stubs"
        self.stubs.mkdir()
        self.mine = self.root / "person-bin"          # where a person's own installs (Homebrew) live
        self.mine.mkdir()
        (self.root / "latest").write_text("1.0.0")
        script(self.stubs / "npm", FAKE_NPM.split("\n", 1)[1])
        env = {"PATH": f"{self.mine}:{self.stubs}:/usr/bin:/bin", "FAKE_LATEST": str(self.root / "latest"),
               "FAKE_FAIL": str(self.root / "fail"), "HOME": str(self.root)}
        patcher = mock.patch.dict(os.environ, env)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.now = 1_000_000.0
        self.switched = []
        self.tools = H.Harnesses(self.root / "tools", self.root / "state.json", clock=lambda: self.now,
                                 on_switch=lambda manifest: self.switched.append(manifest.id))
        self.addCleanup(self.tools.stop)
        self.tools.expose_path()

    def settle(self, busy=(), rounds=200):
        """Step until the worker is idle, as the runner's loop would."""
        finished = []
        for _ in range(rounds):
            finished += self.tools.step(busy)
            if self.tools.job is None:
                break
            time.sleep(0.02)
        finished += self.tools.step(busy)
        return finished

    def version(self, ident="codex"):
        path, _ = self.tools.locate(self.tools.manifests[ident])
        return self.tools.detect(self.tools.manifests[ident], path) if path else ""


class Manifests(unittest.TestCase):
    def test_the_shipped_manifests_are_valid_and_complete(self):
        found = H.load_all()
        self.assertEqual(set(found), {"codex", "claude-code", "gemini-cli", "grok", "pi", "cursor-agent"})
        self.assertEqual([m.id for m in found.values() if m.catch_all], ["pi"])
        for manifest in found.values():
            self.assertEqual(manifest.method, "script" if manifest.id == "cursor-agent" else "npm")
            self.assertTrue((H.HOSTS_DIR / f"{manifest.host}.py").is_file())
            self.assertEqual(manifest.policy, "latest")

    def test_every_provider_has_a_harness_and_the_catalog_agrees(self):
        from backend import providers
        found = H.load_all()
        for row in providers.PROVIDERS:
            owners = [m for m in found.values() if row["id"] in m.providers]
            self.assertEqual([m.id for m in owners], [row["harness"]], row["id"])
            self.assertEqual(owners[0].host, row["runtime"])
        for manifest in found.values():
            self.assertTrue(set(manifest.providers) <= set(providers.PROVIDER_BY_ID), manifest.id)

    def test_login_relay_commands_come_from_the_manifests(self):
        from backend import model_login
        from runner import login
        relayed = {m.host: m for m in H.load_all().values() if m.login}
        self.assertEqual(set(relayed), set(model_login.RUNTIMES))
        self.assertEqual({host for host, m in relayed.items() if m.login["paste_code"]},
                         set(model_login.PASTE_RUNTIMES))
        self.assertEqual(login.COMMANDS["claude"], (["auth", "login", "--claudeai"], True))
        self.assertEqual(login.COMMANDS["codex"], (["login", "--device-auth"], False))

    def test_pi_models_cover_every_catalog_model_on_the_catch_all(self):
        from backend import providers
        from runner.hosts.pi import MODELS
        pi = [row["id"] for row in providers.MODEL_CATALOG if row["runtime"] == "pi"]
        self.assertEqual(sorted(pi), sorted(MODELS))

    def valid(self, **change):
        data = {"id": "tool", "name": "Tool", "host": "codex", "executable": "tool", "providers": ["acme"],
                "install": {"method": "npm", "package": "tool-cli"}}
        data.update(change)
        return data

    def test_a_minimal_manifest_parses(self):
        manifest = H.parse(self.valid())
        self.assertEqual((manifest.id, manifest.policy, manifest.bin_relative),
                         ("tool", "latest", "node_modules/.bin/tool"))

    def test_bad_manifests_are_refused_with_the_field_named(self):
        cases = {
            "unknown field": self.valid(colour="red"),
            "id": self.valid(id="Bad Id"),
            "host": self.valid(host="nonesuch"),
            "executable": self.valid(executable="../evil"),
            "providers": self.valid(providers=[]),
            "install.method": self.valid(install={"method": "curl-bash"}),
            "install.package": self.valid(install={"method": "npm", "package": "x; rm -rf /"}),
            "install.url": self.valid(install={"method": "script", "url": "http://x", "prefix_env": "P", "bin": "b"}),
            "sha256": self.valid(install={"method": "binary", "url": "https://x/{os}-{arch}"}),
            "version.pattern": self.valid(version={"pattern": "no group"}),
            "update.pin": self.valid(update={"policy": "pinned"}),
            "auth.methods": self.valid(auth={"methods": ["telepathy"]}),
            "api_key_env": self.valid(auth={"methods": ["api-key"]}),
            "[login]": self.valid(auth={"methods": ["device-code"]}),
        }
        for needle, data in cases.items():
            with self.subTest(needle):
                with self.assertRaises(H.ManifestError) as raised:
                    H.parse(data)
                self.assertIn(needle.split(".")[-1].strip("[]").split()[0], str(raised.exception))

    def test_script_and_binary_methods_validate(self):
        script = self.valid(install={"method": "script", "url": "https://x.example/i.sh",
                                     "prefix_env": "TOOL_HOME", "bin": "bin/tool"})
        self.assertEqual(H.parse(script).bin_relative, "bin/tool")
        binary = self.valid(install={"method": "binary", "url": "https://x.example/{os}-{arch}.tgz",
                                     "sha256": {"linux-arm64": "a" * 64}})
        self.assertEqual(H.parse(binary).bin_relative, "bin/tool")
        with self.assertRaises(H.ManifestError):
            H.parse(self.valid(install={**binary["install"], "sha256": {"linux-arm64": "short"}}))

    def test_providers_hosts_and_the_catch_all_are_unique_across_manifests(self):
        with tempfile.TemporaryDirectory() as tmp:
            for ident in ("one", "two"):
                Path(tmp, f"{ident}.toml").write_text(textwrap.dedent(f"""
                    id = "{ident}"
                    name = "{ident}"
                    host = "{'codex' if ident == 'one' else 'claude'}"
                    executable = "{ident}"
                    providers = ["shared"]
                    [install]
                    method = "npm"
                    package = "{ident}"
                """))
            with self.assertRaisesRegex(H.ManifestError, "provider shared is already claimed"):
                H.load_all(tmp)


class Planning(Base):
    def test_only_the_harnesses_the_enabled_providers_need_are_planned(self):
        self.tools.want(providers=["openai"])
        self.assertEqual(self.tools.install_plan(), ["codex"])
        self.tools.want(providers=["anthropic", "google", "deepseek"])
        self.assertEqual(self.tools.install_plan(), ["claude-code", "gemini-cli", "pi"])
        self.tools.want(providers=[])
        self.assertEqual(self.tools.install_plan(), [])

    def test_kimi_deepseek_llama_and_mistral_all_want_the_catch_all(self):
        for provider in ("deepseek", "moonshot", "meta", "mistral", "openrouter"):
            self.assertEqual(self.tools.want(providers=[provider]), {"pi"}, provider)
        self.assertEqual(self.tools.want(providers=["xai"]), {"grok"})

    def test_a_bots_runtime_wants_its_harness_even_when_its_provider_is_off(self):
        self.assertEqual(self.tools.want(providers=["openai"], runtimes={"claude", ""}), {"codex", "claude-code"})

    def test_nothing_is_installed_until_it_is_wanted(self):
        self.tools.want(providers=[])
        self.settle()
        self.assertFalse((self.root / "tools").exists() and any((self.root / "tools").glob("*/current")))

    def test_a_harness_already_on_path_is_used_and_never_installed_or_touched(self):
        script(self.mine / "codex", 'echo "codex-cli 0.99.0"')
        self.tools.want(providers=["openai"])
        self.assertEqual(self.tools.install_plan(), [])
        (self.root / "latest").write_text("2.0.0")
        self.now += H.CHECK_EVERY_S * 2
        self.settle()
        self.assertFalse((self.root / "tools" / "codex").exists(), "nothing is installed beside the person's copy")
        row = self.tools.report()["codex"]
        self.assertEqual((row["installed"], row["version"], row["managed"], row["source"], row["update_available"]),
                         (True, "0.99.0", False, "path", False))
        state, message = self.tools.request("update", "codex")
        self.assertEqual(state, "failed")
        self.assertIn("outside Tico", message)
        self.assertEqual(self.tools.request("pin", "codex")[0], "failed")


class Installing(Base):
    def test_a_wanted_harness_is_installed_into_the_tools_dir_and_found_on_path(self):
        self.tools.want(providers=["openai"])
        self.settle()
        self.assertEqual(self.version(), "1.0.0")
        path, source = self.tools.locate(self.tools.manifests["codex"])
        self.assertEqual(source, "tools")
        self.assertTrue(path.startswith(str(self.root / "tools")))
        self.assertEqual(self.switched, ["codex"])
        # Only the tools directory holds it, and the PATH entry is last so anything else wins.
        self.assertTrue(os.environ["PATH"].endswith(str(self.root / "tools" / "bin")))
        self.assertEqual(self.tools.install_plan(), [])

    def test_a_failed_install_is_reported_and_retried_only_after_the_backoff(self):
        (self.root / "fail").write_text("x")
        self.tools.want(providers=["openai"])
        self.settle()
        row = self.tools.report()["codex"]
        self.assertEqual((row["installed"], row["state"]), (False, "failed"))
        self.assertIn("network", row["detail"])
        self.assertFalse(any((self.root / "tools" / "codex").glob("*")), "a failed install leaves nothing behind")
        (self.root / "fail").unlink()
        self.settle()
        self.assertEqual(self.version(), "", "still backing off")
        self.now += H.RETRY_AFTER_S + 1
        self.settle()
        self.assertEqual(self.version(), "1.0.0")
        self.assertEqual(self.tools.report()["codex"]["state"], "idle")

    def test_a_missing_npm_says_so(self):
        with mock.patch.dict(os.environ, {"PATH": f"{self.mine}:/usr/bin:/bin"}):
            os.environ["PATH"] = f"{self.mine}:/usr/bin:/bin"
            if H.shutil.which("npm"):
                self.skipTest("this machine has a real npm on the system PATH")
            self.tools.want(providers=["openai"])
            self.settle()
            self.assertIn("npm is not installed", self.tools.report()["codex"]["detail"])


class Updating(Base):
    def installed(self, providers=("openai",)):
        self.tools.want(providers=list(providers))
        self.settle()
        self.switched.clear()

    def newest(self, version):
        (self.root / "latest").write_text(version)
        self.now += H.CHECK_EVERY_S + 1

    def test_the_daily_check_finds_a_release_and_reports_it(self):
        self.installed()
        self.newest("1.1.0")
        self.tools.request("update", "nonesuch")          # nothing queued for codex: only the check runs
        self.settle(busy={"codex"})
        self.assertEqual(self.tools.state["latest"]["codex"], "1.1.0")
        self.assertTrue(self.tools.report()["codex"]["update_available"])

    def test_an_update_is_never_switched_in_while_a_turn_uses_the_harness(self):
        self.installed()
        self.newest("1.1.0")
        self.settle(busy={"codex"})
        for _ in range(10):
            self.settle(busy={"codex"})
        self.assertEqual(self.version(), "1.0.0", "a running turn keeps the version it started on")
        self.assertEqual(self.switched, [])
        row = self.tools.report()["codex"]
        self.assertEqual((row["state"], row["version"]), ("updating", "1.0.0"))
        self.assertIn("running turn", row["detail"])
        # A turn on another harness does not hold it back, and neither does an idle moment.
        self.settle(busy={"claude"})
        self.assertEqual(self.version(), "1.1.0")
        self.assertEqual(self.switched, ["codex"])
        self.assertEqual(sorted(p.name for p in (self.root / "tools" / "codex").iterdir() if not p.is_symlink()),
                         sorted({(self.root / "tools" / "codex" / "current").resolve().name}),
                         "the old copy is removed after the switch")

    def test_the_staged_copy_sits_beside_the_old_one_until_the_switch(self):
        self.installed()
        self.newest("1.1.0")
        for _ in range(10):
            self.settle(busy={"codex"})
        current = (self.root / "tools" / "codex" / "current").resolve()
        copies = [p for p in (self.root / "tools" / "codex").iterdir() if p.is_dir() and not p.is_symlink()]
        self.assertEqual(len(copies), 2)
        self.assertEqual(current.name, min(copies, key=lambda p: (p / "node_modules/.bin/codex").read_text().count("1.1.0")).name)

    def test_a_pinned_harness_is_not_updated_but_still_reports_what_is_new(self):
        self.installed()
        self.assertEqual(self.tools.request("pin", "codex")[0], "done")
        self.newest("2.0.0")
        self.settle()
        self.settle()
        self.assertEqual(self.version(), "1.0.0")
        row = self.tools.report()["codex"]
        self.assertEqual((row["pinned"], row["pin"], row["latest"], row["update_available"]),
                         (True, "1.0.0", "2.0.0", True))
        # The pin is the owner's choice on this computer and survives a restart.
        again = H.Harnesses(self.root / "tools", self.root / "state.json", clock=lambda: self.now)
        self.addCleanup(again.stop)
        self.assertEqual(again.policy(again.manifests["codex"]), ("pinned", "1.0.0"))
        self.assertEqual(self.tools.request("unpin", "codex")[0], "done")
        self.settle()
        self.assertEqual(self.version(), "2.0.0")

    def test_a_pinned_manifest_installs_the_pin_and_holds_it(self):
        pinned = H.parse({"id": "codex", "name": "Codex", "host": "codex", "executable": "codex",
                          "providers": ["openai"], "install": {"method": "npm", "package": "@openai/codex"},
                          "update": {"policy": "pinned", "pin": "0.5.0"}})
        self.tools.manifests = {"codex": pinned}
        self.tools.want(providers=["openai"])
        self.settle()
        self.assertEqual(self.version(), "0.5.0")
        self.newest("3.0.0")
        self.settle()
        self.assertEqual(self.version(), "0.5.0")

    def test_an_owner_update_waits_for_an_idle_moment_then_reports_done(self):
        self.installed()
        self.newest("1.2.0")
        state, message = self.tools.request("update", "codex", "req-1")
        self.assertEqual(state, "queued")
        self.assertEqual(self.tools.request("update", "codex", "req-2")[0], "queued")
        finished = []
        for _ in range(8):
            finished += self.settle(busy={"codex"})
        self.assertEqual(finished, [], "still waiting: a turn is running")
        self.assertEqual(self.tools.report()["codex"]["state"], "updating")
        finished = self.settle()
        self.assertEqual([(rid, state) for rid, state, _ in finished], [("req-1", "done")])
        self.assertEqual(self.version(), "1.2.0")

    def test_an_owner_update_of_a_pinned_harness_moves_the_pin(self):
        self.installed()
        self.tools.request("pin", "codex")
        self.newest("1.3.0")
        self.tools.request("update", "codex", "req-1")
        self.settle()
        self.assertEqual(self.tools.policy(self.tools.manifests["codex"]), ("pinned", "1.3.0"))

    def test_a_failed_update_keeps_the_working_version(self):
        self.installed()
        self.newest("1.4.0")
        (self.root / "fail").write_text("x")
        self.tools.request("update", "codex", "req-1")
        finished = self.settle()
        self.assertEqual([(rid, state) for rid, state, _ in finished], [("req-1", "failed")])
        self.assertEqual(self.version(), "1.0.0")
        self.assertEqual(self.tools.report()["codex"]["state"], "failed")

    def test_a_restart_finds_what_the_last_run_installed(self):
        self.installed()
        again = H.Harnesses(self.root / "tools", self.root / "state.json", clock=lambda: self.now)
        self.addCleanup(again.stop)
        self.assertEqual(again.report()["codex"]["version"], "1.0.0")
        self.assertEqual(again.install_plan({"codex"}), [])


class Reporting(Base):
    def test_the_readiness_payload_carries_the_five_facts_per_harness(self):
        self.tools.want(providers=["openai", "anthropic"])
        self.settle()
        self.settle()
        self.tools.state["latest"]["codex"] = "1.5.0"
        rows = self.tools.report({"codex": {"authenticated": "ready"}, "claude": {"authenticated": "missing"}})
        self.assertEqual(set(rows), {"codex", "claude-code", "gemini-cli", "grok", "pi", "cursor-agent"})
        codex = rows["codex"]
        self.assertEqual((codex["installed"], codex["version"], codex["pinned"], codex["authenticated"],
                          codex["update_available"], codex["wanted"], codex["managed"]),
                         (True, "1.0.0", False, "ready", True, True, True))
        self.assertEqual(rows["claude-code"]["authenticated"], "missing")
        absent = rows["grok"]
        self.assertEqual((absent["installed"], absent["authenticated"], absent["update_available"], absent["wanted"]),
                         (False, "missing", False, False))

    def test_the_report_fits_the_servers_contract(self):
        from backend.models import StructuredReadiness
        self.tools.want(providers=["openai"])
        self.settle()
        document = {"schema_version": 1, "runtimes": {}, "bots": {}, "harnesses": self.tools.report()}
        parsed = StructuredReadiness.model_validate(document)
        self.assertTrue(parsed.harnesses["codex"].installed)

    def test_tools_dir_prefers_the_environment_then_the_registration(self):
        with mock.patch.dict(os.environ, {"TICO_TOOLS_DIR": "/vol/tools"}):
            self.assertEqual(H.tools_dir({}, "/x/runner.json"), Path("/vol/tools"))
        with mock.patch.dict(os.environ):
            os.environ.pop("TICO_TOOLS_DIR", None)
            self.assertEqual(H.tools_dir({"tools_dir": "/cfg/tools"}), Path("/cfg/tools"))
            self.assertEqual(H.tools_dir({}, "/home/runner/runner.json"), Path("/home/runner/tools"))


if __name__ == "__main__":
    unittest.main()


CURSOR_SCRIPT = """#!/bin/bash
# stands in for https://cursor.com/install: everything goes under $HOME, as the real one does
set -e
v=2027.01.01-abc1234
mkdir -p "$HOME/.local/share/cursor-agent/versions/$v" "$HOME/.local/bin"
printf '#!/bin/sh\\necho %s\\n' "$v" > "$HOME/.local/share/cursor-agent/versions/$v/cursor-agent"
chmod +x "$HOME/.local/share/cursor-agent/versions/$v/cursor-agent"
ln -s "$HOME/.local/share/cursor-agent/versions/$v/cursor-agent" "$HOME/.local/bin/cursor-agent"
"""


class ScriptInstall(Base):
    """Cursor's only official install is a script that installs under $HOME."""

    def setUp(self):
        super().setUp()
        self.fetched = []

        def fetch(url):
            self.fetched.append(url)
            return CURSOR_SCRIPT.encode()
        self.tools.fetch = fetch
        manifest = self.tools.manifests["cursor-agent"]
        # The stand-in needs neither curl nor tar.
        self.tools.manifests["cursor-agent"] = H.dataclasses.replace(
            manifest, install={**manifest.install, "requires": []})

    def test_the_script_runs_with_home_inside_the_tools_dir_and_the_result_is_found_on_path(self):
        self.tools.want(providers=["cursor"])
        self.assertEqual(self.tools.install_plan(), ["cursor-agent"])
        self.settle()
        self.assertEqual(set(self.fetched), {"https://cursor.com/install"})
        row = self.tools.report()["cursor-agent"]
        self.assertEqual((row["installed"], row["version"], row["managed"]), (True, "2027.01.01-abc1234", True))
        path, source = self.tools.locate(self.tools.manifests["cursor-agent"])
        self.assertEqual(source, "tools")
        self.assertTrue(os.path.realpath(path).startswith(str(self.root.resolve() / "tools")))
        self.assertFalse((self.root / ".local").exists(), "nothing lands in the real home directory")

    def test_the_newest_release_is_read_from_the_script_itself(self):
        body = 'DOWNLOAD_URL="https://downloads.cursor.com/lab/2027.02.03-fedcba9/${OS}/${ARCH}/agent-cli-package.tar.gz"'
        self.tools.fetch = lambda url: body.encode()
        self.assertEqual(self.tools.newest(self.tools.manifests["cursor-agent"]), "2027.02.03-fedcba9")
        self.assertTrue(H.newer("2027.02.03-fedcba9", "2027.01.01-abc1234"))

    def test_an_installer_that_only_has_the_newest_release_cannot_be_pinned_to_another(self):
        with self.assertRaisesRegex(RuntimeError, "only installs the newest release"):
            self.tools.stage(self.tools.manifests["cursor-agent"], "2026.01.01-0000000")
        self.assertFalse(any((self.root / "tools" / "cursor-agent").glob("*")))


class BinaryInstall(Base):
    """A binary download is refused unless it matches the checksum the manifest pins."""

    def archive(self, version="4.5.6"):
        import hashlib
        import io
        import tarfile
        buffer = io.BytesIO()
        body = f'#!/bin/sh\necho "acme {version}"\n'.encode()
        with tarfile.open(fileobj=buffer, mode="w:gz") as bundle:
            info = tarfile.TarInfo("acme-1/acme")
            info.size, info.mode = len(body), 0o755
            bundle.addfile(info, io.BytesIO(body))
        data = buffer.getvalue()
        return data, hashlib.sha256(data).hexdigest()

    def manifest(self, digest):
        system, machine = H._platform()
        return H.parse({"id": "acme", "name": "Acme", "host": "codex", "executable": "acme", "providers": ["acme"],
                        "install": {"method": "binary", "url": "https://dl.example/{os}-{arch}/acme.tar.gz",
                                    "sha256": {f"{system}-{machine}": digest}}})

    def test_a_matching_download_is_unpacked_into_the_tools_dir(self):
        data, digest = self.archive()
        urls = []
        self.tools.fetch = lambda url: (urls.append(url), data)[1]
        self.tools.manifests = {"acme": self.manifest(digest)}
        self.tools.want(providers=["acme"])
        self.settle()
        system, machine = H._platform()
        self.assertEqual(urls[0], f"https://dl.example/{system}-{machine}/acme.tar.gz")
        self.assertEqual(self.tools.report()["acme"]["version"], "4.5.6")

    def test_a_download_that_does_not_match_its_checksum_is_refused_and_leaves_nothing(self):
        data, _ = self.archive()
        self.tools.fetch = lambda url: data
        self.tools.manifests = {"acme": self.manifest("0" * 64)}
        self.tools.want(providers=["acme"])
        self.settle()
        row = self.tools.report()["acme"]
        self.assertEqual((row["installed"], row["state"]), (False, "failed"))
        self.assertIn("checksum", row["detail"])
        self.assertFalse(any((self.root / "tools" / "acme").glob("*")))

    def test_a_platform_with_no_published_download_says_so(self):
        data, digest = self.archive()
        manifest = self.manifest(digest)
        self.tools.fetch = lambda url: data
        self.tools.manifests = {"acme": H.dataclasses.replace(
            manifest, install={**manifest.install, "sha256": {"plan9-mips": digest}})}
        self.tools.want(providers=["acme"])
        self.settle()
        self.assertIn("no download is published", self.tools.report()["acme"]["detail"])
