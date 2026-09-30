"""A bot's remote MCP servers (docs/connect-tools.md): the entry is validated, the credential placeholder is filled
only from what the bot was granted, every harness that can take the server gets it next to the hub's own and the
operator's global servers stay out, and one that cannot is named in the bot's readiness warnings.

No network beyond a loopback socket, no runtime started."""
import http.server
import json
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

from clients import access_entry, mcp_servers
from runner.hosts import base
from runner.hosts.claude import ClaudeHost
from runner.hosts.codex import CodexHost, mcp_disable_config
from runner.hosts.gemini import GeminiHost
from runner.hosts.grok import GrokHost
from runner.service import Runner

JIRA = {"service": "jira", "can": ["read", "write"], "env": "JIRA_API_TOKEN",
        "mcp": {"url": "https://mcp.atlassian.com/v2/mcp", "transport": "http",
                "headers": {"Authorization": "Bearer ${JIRA_API_TOKEN}"}}}
LINEAR_SSE = {"service": "linear", "can": ["read"], "env": "LINEAR_API_KEY",
              "mcp": {"url": "https://mcp.linear.app/sse", "transport": "sse", "headers": {"Authorization": "Bearer ${LINEAR_API_KEY}"}}}
BASIC = {"service": "wiki", "can": ["read"], "env": "WIKI_AUTH",
         "mcp": {"url": "https://wiki.acme.example/mcp", "headers": {"Authorization": "Basic ${WIKI_AUTH}", "X-Key": "${WIKI_AUTH}"}}}
RUN_ENV = {"JIRA_API_TOKEN": "tok-jira-123", "LINEAR_API_KEY": "tok-linear-456", "WIKI_AUTH": "dXNlcjpwdw==",
           "HUB_API_URL": "https://hub.acme.example", "HUB_TOKEN": "t0k", "HUB_BOT": "atlas", "PATH": "/bin"}


class Validation(unittest.TestCase):
    def clean(self, mcp, env="JIRA_API_TOKEN"):
        return access_entry.clean({"service": "jira", "can": ["read"], "env": env, "mcp": mcp})

    def test_an_mcp_entry_is_kept_in_order_with_its_placeholder(self):
        entry = access_entry.clean(JIRA)
        self.assertEqual(list(entry), ["service", "mcp", "can", "env"])
        self.assertEqual(entry["mcp"]["headers"], {"Authorization": "Bearer ${JIRA_API_TOKEN}"})
        self.assertIn("headers: {Authorization: 'Bearer ${JIRA_API_TOKEN}'}", access_entry.to_yaml(entry))

    def test_https_only_except_loopback_and_a_known_transport(self):
        for bad in ({"url": "http://mcp.acme.example/mcp"}, {"url": "ftp://x.example"}, {"url": "https://u:pw@x.example/mcp"},
                    {"url": "https://x.example/mcp", "transport": "websocket"}, {"url": ""}, {"transport": "http"},
                    {"url": "https://x.example", "extra": 1}):
            with self.assertRaises(access_entry.EntryError, msg=bad):
                self.clean(bad)
        self.assertEqual(self.clean({"url": "http://localhost:8080/mcp"})["mcp"], {"url": "http://localhost:8080/mcp", "transport": "http"})
        self.assertEqual(self.clean({"url": "http://127.0.0.1:9/mcp", "transport": "SSE"})["mcp"]["transport"], "sse")

    def test_a_header_holds_no_value_and_no_variable_but_the_entrys_own(self):
        url = "https://x.example/mcp"
        for headers in ({"Authorization": "Bearer abcdefghijklmnopqrstuvwx"}, {"Authorization": "${HOME}"},
                        {"Authorization": "Bearer ${OTHER_TOKEN}"}, {"Authorization": "Bearer $JIRA_API_TOKEN"},
                        {"Host": "evil.example"}, {"Bad Name": "x"}):
            with self.assertRaises(access_entry.EntryError, msg=headers):
                self.clean({"url": url, "headers": headers})
        with self.assertRaises(access_entry.EntryError) as caught:          # a secret says so, for the register route's code
            self.clean({"url": url, "headers": {"Authorization": "Bearer abcdefghijklmnopqrstuvwx"}})
        self.assertEqual(caught.exception.code, "secret")
        with self.assertRaises(access_entry.EntryError):                    # a placeholder needs `env` to name
            self.clean({"url": url, "headers": {"Authorization": "Bearer ${JIRA_API_TOKEN}"}}, env="")
        with self.assertRaises(access_entry.EntryError):                    # and none in the address
            self.clean({"url": "https://x.example/mcp?key=${JIRA_API_TOKEN}"})


class Substitution(unittest.TestCase):
    def test_a_server_needs_its_variable_in_the_run_and_is_named_when_it_is_not(self):
        servers, problems = mcp_servers.servers_for_run([JIRA, LINEAR_SSE], {"JIRA_API_TOKEN": "tok"})
        self.assertEqual([s["name"] for s in servers], ["jira"])
        self.assertEqual(servers[0]["headers"], {"Authorization": "Bearer ${JIRA_API_TOKEN}"})      # still the placeholder
        self.assertEqual(len(problems), 1)
        self.assertIn("linear", problems[0])
        self.assertIn("LINEAR_API_KEY is not granted", problems[0])
        self.assertNotIn("tok", json.dumps(problems))

    def test_an_invalid_block_is_skipped_not_passed(self):
        bad = {**JIRA, "mcp": {"url": "http://evil.example/mcp", "headers": JIRA["mcp"]["headers"]}}
        self.assertEqual(mcp_servers.servers_for_run([bad], RUN_ENV), ([], []))
        self.assertIn("not valid", mcp_servers.problem_of(bad))

    def test_the_runners_own_environment_is_not_the_bots_to_use(self):
        # OPENAI_API_KEY-style variables live in the runner's process; only the bot's secrets, a profile and its grants count.
        with tempfile.TemporaryDirectory() as tmp:
            secrets = Path(tmp) / "secrets"
            secrets.mkdir()
            (secrets / "atlas.env").write_text("JIRA_API_TOKEN=tok-own\n")
            runner = Runner.__new__(Runner)
            runner.config = {"projects_dir": tmp}
            runner.vault_names = {"a1": {"LINEAR_API_KEY"}}
            attempt = {"id": "a1", "bot": "atlas", "config": {}}
            env = {"JIRA_API_TOKEN": "tok-own", "LINEAR_API_KEY": "tok-vault", "WIKI_AUTH": "from-the-runners-process"}
            self.assertEqual(runner.granted_environment(attempt, env), {"JIRA_API_TOKEN": "tok-own", "LINEAR_API_KEY": "tok-vault"})
            servers, problems = mcp_servers.servers_for_run([JIRA, LINEAR_SSE, BASIC], runner.granted_environment(attempt, env))
            self.assertEqual([s["name"] for s in servers], ["jira", "linear"])
            self.assertIn("WIKI_AUTH is not granted", problems[0])


class HostConfigs(unittest.TestCase):
    def settings(self, tools, runtime, harness=""):
        servers, _ = mcp_servers.servers_for_run(tools, RUN_ENV)
        return base.settings("/tmp/emp-atlas", env=RUN_ENV, mcp_servers=mcp_servers.supported(servers, runtime, harness))

    def test_codex_reads_the_variable_itself_and_the_operators_servers_stay_disabled(self):
        home = tempfile.TemporaryDirectory()
        self.addCleanup(home.cleanup)
        (Path(home.name) / "config.toml").write_text('[mcp_servers.jira]\ncommand = "npx"\n[mcp_servers.posthog]\nurl = "https://mcp.posthog.com"\n')
        host = CodexHost(env=RUN_ENV, env_mode="config", config=mcp_disable_config(home.name))
        params = host._thread_params(self.settings([JIRA, BASIC, LINEAR_SSE], "codex"))
        servers = params["config"]["mcp_servers"]
        self.assertEqual(servers["posthog"], {"startup_timeout_ms": 1})             # the operator's own: still switched off
        self.assertEqual(servers["jira"], {"command": "/usr/bin/true", "args": []})    # (a clash is not merged into)
        self.assertEqual(servers["tico_jira"], {"url": "https://mcp.atlassian.com/v2/mcp", "bearer_token_env_var": "JIRA_API_TOKEN"})
        self.assertEqual(servers["wiki"]["env_http_headers"], {"X-Key": "WIKI_AUTH"})   # exactly ${VAR}: read from the environment
        self.assertEqual(servers["wiki"]["http_headers"], {"Authorization": "Basic dXNlcjpwdw=="})   # any other shape is filled in
        self.assertNotIn("linear", servers)                                          # Codex takes streamable HTTP only
        self.assertNotIn("tok-jira-123", json.dumps(servers["tico_jira"]))
        self.assertEqual(servers["hub"]["env"]["HUB_TOKEN"], "t0k")

    def test_codex_without_the_bots_variables_in_its_process_fills_the_header_in(self):
        host = CodexHost(env=None, env_mode="config", config={})
        servers = host._thread_params(self.settings([JIRA], "codex"))["config"]["mcp_servers"]
        self.assertEqual(servers["jira"], {"url": "https://mcp.atlassian.com/v2/mcp", "http_headers": {"Authorization": "Bearer tok-jira-123"}})

    def test_claude_gets_them_beside_the_hub_with_placeholders_not_values(self):
        host = ClaudeHost(bot="atlas", spawn=lambda *a, **k: None)
        settings = self.settings([JIRA, LINEAR_SSE], "claude")
        tid = host.start_thread("atlas", settings)
        argv = host._argv(tid, host._threads[tid], None)
        config = json.loads(argv[argv.index("--mcp-config") + 1])["mcpServers"]
        self.assertEqual(sorted(config), ["hub", "jira", "linear"])
        self.assertEqual(config["jira"], {"type": "http", "url": "https://mcp.atlassian.com/v2/mcp",
                                          "headers": {"Authorization": "Bearer ${JIRA_API_TOKEN}"}})
        self.assertEqual(config["linear"]["type"], "sse")
        self.assertNotIn("tok-jira-123", " ".join(argv))
        self.assertNotIn("--strict-mcp-config", argv)                               # the bot repo's own .mcp.json stays

    def test_claude_with_no_declared_server_is_unchanged(self):
        host = ClaudeHost(bot="atlas", spawn=lambda *a, **k: None)
        tid = host.start_thread("atlas", base.settings("/tmp/emp-atlas", env=RUN_ENV))
        argv = host._argv(tid, host._threads[tid], None)
        self.assertEqual(list(json.loads(argv[argv.index("--mcp-config") + 1])["mcpServers"]), ["hub"])

    def test_gemini_and_grok_take_both_transports(self):
        settings = self.settings([JIRA, LINEAR_SSE], "gemini")
        servers = GeminiHost(bot="atlas", home="/tmp/nowhere")._settings("gemini-3.8-flash", "high", settings["mcp_servers"])["mcpServers"]
        self.assertEqual(servers["jira"]["httpUrl"], "https://mcp.atlassian.com/v2/mcp")
        self.assertEqual(servers["linear"]["url"], "https://mcp.linear.app/sse")
        self.assertEqual(servers["jira"]["headers"], {"Authorization": "Bearer ${JIRA_API_TOKEN}"})   # the CLI expands it: no value on disk
        acp = GrokHost._mcp(self.settings([JIRA, LINEAR_SSE], "grok"))
        self.assertEqual([(s["type"], s["name"]) for s in acp], [("http", "jira"), ("sse", "linear")])
        self.assertEqual(acp[0]["headers"], [{"name": "Authorization", "value": "Bearer tok-jira-123"}])
        self.assertEqual(GrokHost._mcp(base.settings("/tmp/x", env=RUN_ENV)), [])

    def test_a_harness_that_cannot_take_them_gets_none(self):
        servers, _ = mcp_servers.servers_for_run([JIRA, LINEAR_SSE], RUN_ENV)
        for runtime in ("cursor", "pi"):
            self.assertEqual(mcp_servers.supported(servers, runtime), [])
        self.assertEqual(mcp_servers.supported(servers, "gemini", "antigravity"), [])
        self.assertEqual([s["name"] for s in mcp_servers.supported(servers, "codex")], ["jira"])


class Readiness(unittest.TestCase):
    MANIFEST = ("name: atlas\ntools:\n  - service: jira\n    can: [read]\n    env: JIRA_API_TOKEN\n"
                "    mcp: {url: 'https://mcp.atlassian.com/v2/mcp', transport: http, headers: {Authorization: 'Bearer ${JIRA_API_TOKEN}'}}\n"
                "  - service: linear\n    can: [read]\n    env: LINEAR_API_KEY\n"
                "    mcp: {url: 'https://mcp.linear.app/sse', transport: sse}\n"
                "  - service: broken\n    can: [read]\n    mcp: {url: 'http://plain.example/mcp'}\n")

    def report(self, runtime, harness=None):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        bot = Path(tmp.name) / "bot-atlas"
        bot.mkdir()
        (bot / "AGENT.md").write_text("# Atlas\n")
        (bot / "bot.yaml").write_text(self.MANIFEST)
        (Path(tmp.name) / "secrets").mkdir()
        (Path(tmp.name) / "secrets" / "atlas.env").write_text("JIRA_API_TOKEN=tok\n")
        runner = Runner.__new__(Runner)
        runner.config = {"url": "https://acme.test", "token": "t", "runner_id": "r1", "projects_dir": tmp.name}
        runner._names = None
        config = {"runtime": runtime, "model": "m", **({"harness": harness} if harness else {})}
        entries = [{"bot": "atlas", "runner_id": "r1", "state": "active", "config": config}]
        runtimes = {runtime: {"installed": True, "authenticated": "ready", "detail": "", "models": [], "version": "1", "controls": []}}
        with mock.patch.object(Runner, "mcp_reach", return_value="reachable"):
            return runner.readiness(entries, runner.preflight(entries, runtimes), runtimes)["bots"]["atlas"]

    def test_the_row_carries_the_block_and_the_check_but_not_a_value(self):
        row = self.report("claude")
        jira = next(t for t in row["tools"] if t["service"] == "jira")
        self.assertEqual(jira["mcp"], {"url": "https://mcp.atlassian.com/v2/mcp", "transport": "http",
                                       "headers": {"Authorization": "Bearer ${JIRA_API_TOKEN}"}, "status": "reachable"})
        self.assertNotIn("tok", json.dumps(row).replace("tokens", ""))
        broken = next(t for t in row["tools"] if t["service"] == "broken")
        self.assertIn("https", broken["problem"])
        self.assertNotIn("mcp", broken)
        self.assertEqual(row.get("warnings", []), [])

    def test_a_harness_that_cannot_take_a_server_is_a_warning_naming_the_tool(self):
        warnings = self.report("cursor")["warnings"]
        self.assertEqual(len([w for w in warnings if "MCP server is not passed" in w]), 2)
        self.assertTrue(any(w.startswith("jira:") and "Cursor cannot use it" in w for w in warnings))
        pi = self.report("pi")["warnings"]
        self.assertTrue(any("pi has no MCP support" in w for w in pi))
        codex = self.report("codex")["warnings"]                   # takes jira (http); not linear (sse)
        self.assertEqual([w.split(":")[0] for w in codex if "MCP" in w], ["linear"])
        self.assertTrue(any("takes http servers, not sse" in w for w in codex))
        self.assertFalse([w for w in self.report("gemini", "antigravity")["warnings"] if "jira" not in w and "linear" not in w])


class Reachability(unittest.TestCase):
    def serve(self, status):
        seen = []

        class Handler(http.server.BaseHTTPRequestHandler):
            def do_POST(self):
                seen.append((self.headers.get("Authorization"), self.rfile.read(int(self.headers.get("content-length") or 0))))
                self.send_response(status)
                self.end_headers()

            def do_GET(self):
                seen.append((self.headers.get("Authorization"), b""))
                self.send_response(status)
                self.end_headers()

            def log_message(self, *args):
                pass
        server = http.server.HTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        return "http://127.0.0.1:%d/mcp" % server.server_port, seen

    def test_reachable_auth_failed_and_unreachable(self):
        for status, expected in ((200, "reachable"), (400, "reachable"), (401, "auth_failed"), (403, "auth_failed"),
                                 (404, "unreachable"), (503, "unreachable")):
            url, seen = self.serve(status)
            self.assertEqual(mcp_servers.reachability(url, "http", {"Authorization": "Bearer x"}, timeout=3), expected, status)
            self.assertEqual(seen[0][0], "Bearer x")
            self.assertIn(b'"initialize"', seen[0][1])
        url, _ = self.serve(200)
        self.assertEqual(mcp_servers.reachability(url, "sse", {}, timeout=3), "reachable")
        self.assertEqual(mcp_servers.reachability("http://127.0.0.1:9/mcp", "http", {}, timeout=1), "unreachable")


if __name__ == "__main__":
    unittest.main()
