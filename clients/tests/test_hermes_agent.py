"""The Hermes connector (clients/hermes_agent.py) against a fake hub: pair, update, doctor, old-label
cleanup and the archived/revoked back-off. launchctl and systemctl are mocked; nothing touches the
real home directory, launchd or systemd."""
import contextlib
import io
import json
import os
import plistlib
import stat
import subprocess
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest import mock

from clients import hermes_agent as H

REAL_RUN = subprocess.run
REAL_SLEEP = __import__("time").sleep
TOKEN = "tico-agent-SECRET-0123456789abcdef"
PAIR_SECRET = "pairing-secret-0123456789abcdefghijkl"
CODE = "K7QM-4F2P"


class Hub:
    """A hub that answers only what the connector asks, and remembers every request."""

    def __init__(self):
        self.requests = []
        self.pair_states = [{"state": "approved", "bot": "scout", "token": TOKEN, "url": None}]
        self.expires_in = 600
        self.heartbeat = (200, {"server_time": "2026-09-30T10:00:00Z", "bot": "scout",
                                "waiting": {"messages": 2, "tasks": 1}})
        self.script = ""
        self.me = {"role": "bot", "actor": "bot:scout", "agent": "hermes"}
        hub = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def reply(self, status, body, text=False):
                raw = body.encode() if text else json.dumps(body).encode()
                self.send_response(status)
                self.send_header("Content-Type", "text/plain" if text else "application/json")
                self.send_header("Content-Length", str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)

            def record(self):
                length = int(self.headers.get("Content-Length") or 0)
                body = json.loads(self.rfile.read(length).decode()) if length else None
                hub.requests.append({"method": self.command, "path": self.path, "body": body,
                                     "headers": {k.lower(): v for k, v in self.headers.items()}})
                return body

            def do_POST(self):
                self.record()
                if self.path == "/api/v2/agents/pairings":
                    return self.reply(201, {"pairing_id": "p-1", "code": CODE, "secret": PAIR_SECRET,
                                            "expires_in": hub.expires_in, "poll_every": 1})
                if self.path == "/api/v2/agents/heartbeat":
                    status, body = hub.heartbeat
                    return self.reply(status, body)
                self.reply(404, {"error": {"code": "not_found", "detail": "no"}})

            def do_GET(self):
                self.record()
                if self.path == "/api/v2/agents/pairings/p-1":
                    if self.headers.get("X-Pairing-Secret") != PAIR_SECRET:
                        return self.reply(404, {"error": {"code": "not_found", "detail": "no"}})
                    state = hub.pair_states.pop(0) if len(hub.pair_states) > 1 else hub.pair_states[0]
                    state = dict(state)
                    if state.get("url") is None:
                        state.pop("url", None)
                        if state["state"] == "approved":
                            state["url"] = hub.url
                    return self.reply(200, state)
                if self.path == "/api/v2/me":
                    return self.reply(200, hub.me)
                if self.path == "/api/v2/agents/setup-script":
                    return self.reply(200, hub.script, text=True)
                self.reply(404, {"error": {"code": "not_found", "detail": "no"}})

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.url = "http://127.0.0.1:%d" % self.server.server_port
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def count(self, path):
        return sum(1 for r in self.requests if r["path"] == path)

    def close(self):
        self.server.shutdown()
        self.server.server_close()


class Fake:
    """Records launchctl/systemctl calls instead of running them."""

    def __init__(self, loaded=True):
        self.calls = []
        self.loaded = loaded

    def run(self, command, *args, **kwargs):
        if len(command) > 1 and str(command[1]).endswith("hermes_agent.py"):
            return REAL_RUN(command, *args, **kwargs)        # the freshly downloaded connector really runs
        self.calls.append(list(command))
        code = 0
        out = ""
        if command[:2] == ["launchctl", "print"] and not self.loaded:
            code = 113
        if command[:3] == ["systemctl", "--user", "is-active"]:
            out, code = ("active\n", 0) if self.loaded else ("inactive\n", 3)
        return subprocess.CompletedProcess(command, code, stdout=out, stderr="")

    def ran(self, *prefix):
        return [c for c in self.calls if c[:len(prefix)] == list(prefix)]


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(lambda: __import__("shutil").rmtree(self.tmp, ignore_errors=True))
        self.home = self.tmp / "home"
        self.config_dir = self.home / ".config" / "tico" / "agents"
        self.profile = self.home / ".hermes" / "profiles" / "scout"
        self.profile.mkdir(parents=True)
        (self.profile / "config.yaml").write_text("model:\n  default: some-model\n  provider: some\n")
        env = mock.patch.dict(os.environ, {"HOME": str(self.home), "HERMES_HOME": str(self.home / ".hermes"),
                                           "TICO_AGENT_CONFIG_DIR": str(self.config_dir),
                                           "PATH": "/usr/bin:/bin"})   # no real `hermes` for the child to run
        env.start()
        self.addCleanup(env.stop)
        patch = mock.patch.object(H, "CONFIG_DIR", self.config_dir)
        patch.start()
        self.addCleanup(patch.stop)
        self.hub = Hub()
        self.addCleanup(self.hub.close)
        self.fake = Fake()
        self.platform("darwin")

    def platform(self, name):
        for target in (mock.patch.object(H.sys, "platform", name),
                       mock.patch.object(H.subprocess, "run", self.fake.run),
                       mock.patch.object(H.shutil, "which", lambda n: "/usr/bin/" + n if n == "systemctl" else None)):
            target.start()
            self.addCleanup(target.stop)

    def run_cli(self, *argv):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = H.main(list(argv))
        self.assertNotIn(TOKEN, out.getvalue() + err.getvalue(), "the token was printed")
        return code, out.getvalue(), err.getvalue()

    def install(self, *extra):
        code, out, err = self.run_cli("install", "--profile", "scout", "--url", self.hub.url, "--bot", "scout",
                                      "--token", TOKEN, *extra)
        self.assertEqual(code, 0, err)
        return out

    def credential(self):
        return json.loads((self.config_dir / "scout.json").read_text())


class Pair(Base):
    def test_happy_path_installs_everything_and_never_prints_the_token(self):
        self.hub.pair_states = [{"state": "pending"}, {"state": "pending"},
                                {"state": "approved", "bot": "scout", "token": TOKEN}]
        with mock.patch.object(H.time, "sleep", lambda s: None):
            code, out, err = self.run_cli("pair", "--profile", "scout", "--url", self.hub.url)
        self.assertEqual(code, 0, err)
        self.assertIn("Tell BotOps", out)
        self.assertIn("connect my Hermes profile scout, code " + CODE, out)
        self.assertNotIn(PAIR_SECRET, out + err)
        # The pairing call is unauthenticated and carries the connector's own User-Agent.
        first = self.hub.requests[0]
        self.assertEqual(first["path"], "/api/v2/agents/pairings")
        self.assertNotIn("authorization", first["headers"])
        self.assertEqual(first["body"]["profile"], "scout")
        self.assertEqual(first["body"]["harness"], "hermes")
        self.assertTrue(first["headers"]["user-agent"].startswith("tico-hermes-agent/"))
        polls = [r for r in self.hub.requests if r["path"] == "/api/v2/agents/pairings/p-1"]
        self.assertEqual(len(polls), 3)
        self.assertEqual(polls[0]["headers"]["x-pairing-secret"], PAIR_SECRET)
        # What install does: .env, MCP entry, credential file, timer.
        self.assertIn("TICO_AGENT_TOKEN=" + TOKEN, (self.profile / ".env").read_text())
        self.assertEqual(stat.S_IMODE((self.profile / ".env").stat().st_mode), 0o600)
        self.assertIn("mcp_servers", (self.profile / "config.yaml").read_text())
        self.assertEqual(stat.S_IMODE((self.config_dir / "scout.json").stat().st_mode), 0o600)
        self.assertEqual(self.credential()["bot"], "scout")
        self.assertEqual(self.hub.count("/api/v2/agents/heartbeat"), 1)
        self.assertTrue((self.home / "Library/LaunchAgents/team.tico-agent.scout.plist").exists())
        self.assertTrue(self.fake.ran("launchctl", "bootstrap"))

    def test_an_expired_code_stops_cleanly_and_changes_nothing(self):
        self.hub.pair_states = [{"state": "pending"}, {"state": "expired"}]
        with mock.patch.object(H.time, "sleep", lambda s: None):
            code, out, err = self.run_cli("pair", "--profile", "scout", "--url", self.hub.url)
        self.assertEqual(code, 1)
        self.assertIn("expired", err)
        self.assertIn("run pair again", err)
        self.assertFalse((self.config_dir / "scout.json").exists())
        self.assertFalse((self.profile / ".env").exists())
        self.assertEqual(self.fake.calls, [])

    def test_waiting_past_the_deadline_is_an_expiry_too(self):
        self.hub.pair_states = [{"state": "pending"}]
        self.hub.expires_in = 1
        with mock.patch.object(H.time, "sleep", lambda s: REAL_SLEEP(0.6)):
            code, out, err = self.run_cli("pair", "--profile", "scout", "--url", self.hub.url)
        self.assertEqual(code, 1)
        self.assertIn("expired", err)

    def test_declined_is_reported_and_changes_nothing(self):
        self.hub.pair_states = [{"state": "declined"}]
        code, out, err = self.run_cli("pair", "--profile", "scout", "--url", self.hub.url)
        self.assertEqual(code, 1)
        self.assertIn("declined", err)
        self.assertFalse((self.config_dir / "scout.json").exists())

    def test_a_missing_profile_fails_before_asking_the_hub_for_a_code(self):
        code, out, err = self.run_cli("pair", "--profile", "nobody", "--url", self.hub.url)
        self.assertEqual(code, 1)
        self.assertEqual(self.hub.requests, [])


class Update(Base):
    def test_update_replaces_the_installed_copy_atomically_and_installs_again(self):
        self.install("--no-timer")
        target = self.config_dir / "hermes_agent.py"
        target.write_text("# old connector\n")
        os.chmod(target, 0o644)
        self.hub.script = Path(H.__file__).read_text().replace('VERSION = "%s"' % H.VERSION, 'VERSION = "9.9.9"')
        beats = self.hub.count("/api/v2/agents/heartbeat")
        code, out, err = self.run_cli("update", "--profile", "scout")
        self.assertEqual(code, 0, err)
        self.assertIn("9.9.9", out)
        self.assertIn('VERSION = "9.9.9"', target.read_text())
        self.assertEqual(stat.S_IMODE(target.stat().st_mode), 0o600)
        self.assertFalse(list(self.config_dir.glob("*.tmp")))
        fetch = [r for r in self.hub.requests if r["path"] == "/api/v2/agents/setup-script"][0]
        self.assertEqual(fetch["headers"]["authorization"], "Bearer " + TOKEN)
        self.assertTrue(fetch["headers"]["user-agent"].startswith("tico-hermes-agent/"))
        self.assertNotIn("python-urllib", fetch["headers"]["user-agent"].lower())
        # The new file ran the install steps again with the saved values.
        self.assertEqual(self.hub.count("/api/v2/agents/heartbeat"), beats + 1)
        self.assertEqual(self.credential()["token"], TOKEN)

    def test_a_sign_in_page_is_not_installed(self):
        self.install("--no-timer")
        target = self.config_dir / "hermes_agent.py"
        target.write_text("# current connector\n")
        self.hub.script = "<html><body>Sign in</body></html>"
        code, out, err = self.run_cli("update", "--profile", "scout")
        self.assertEqual(code, 1)
        self.assertEqual(target.read_text(), "# current connector\n")


class Doctor(Base):
    def seed_old_names(self):
        (self.profile / "SOUL.md").write_text("You are Scout.\nAlways use\nhub_say to reply.\n")
        (self.profile / "skills" / "triage").mkdir(parents=True)
        (self.profile / "skills" / "triage" / "SKILL.md").write_text("Call `hub_docs_search` then hub_message_send.\n")
        (self.profile / "cron").mkdir()
        (self.profile / "cron" / "jobs.json").write_text('{"prompt": "check hub_inbox and hub_fleet-check"}\n')
        (self.profile / "memories").mkdir()
        (self.profile / "memories" / "MEMORY.md").write_text("- a\n- mark with hub_ack, status via hub_status_set\n")

    def test_a_healthy_profile_reports_ok_and_old_tool_names_with_file_line_and_new_name(self):
        self.install()
        self.seed_old_names()
        before = {p: p.read_text() for p in self.profile.rglob("*") if p.is_file()}
        code, out, err = self.run_cli("doctor", "--profile", "scout")
        self.assertEqual(code, 0, out + err)
        for text in ("credential file", "mcp_servers.tico is in config.yaml", "TICO_AGENT_TOKEN is present",
                     "heartbeat timer", "is loaded", "last heartbeat reply", "GET /api/v2/me works"):
            self.assertIn(text, out)
        self.assertNotIn("PROBLEM", out)
        self.assertIn("SOUL.md:3: hub_say -> hub_message_send", out)
        self.assertIn("SKILL.md:1: hub_docs_search -> hub_doc_search", out)
        self.assertIn("jobs.json:1: hub_inbox -> hub_message_list", out)
        self.assertIn("jobs.json:1: hub_fleet-check -> hub_health_check", out)
        self.assertIn("MEMORY.md:2: hub_ack -> hub_message_mark_read", out)
        self.assertIn("MEMORY.md:2: hub_status_set -> hub_bot_status_set", out)
        self.assertNotIn("hub_message_send ->", out)        # current names are not flagged
        self.assertTrue(self.fake.ran("launchctl", "print"))
        after = {p: p.read_text() for p in before}
        self.assertEqual(before, after, "doctor must not edit anything")

    def test_problems_are_named_in_plain_words(self):
        self.install()
        os.chmod(self.config_dir / "scout.json", 0o644)
        (self.profile / ".env").write_text("OTHER=1\n")
        (self.profile / "config.yaml").write_text("model:\n  default: x\n")
        self.fake.loaded = False
        self.hub.me = {"role": "human", "actor": "human:x"}
        code, out, err = self.run_cli("doctor", "--profile", "scout")
        self.assertEqual(code, 1)
        self.assertIn("mode 644", out)
        self.assertIn("no mcp_servers.tico entry", out)
        self.assertIn("TICO_AGENT_TOKEN is missing", out)
        self.assertIn("not loaded", out)
        self.assertIn("GET /api/v2/me answers", out)

    def test_no_credential_file_is_one_clear_finding(self):
        code, out, err = self.run_cli("doctor", "--profile", "scout")
        self.assertEqual(code, 1)
        self.assertIn("no usable credential file", out)
        self.assertIn("run pair", out)


class OldLabels(Base):
    def old_plist(self, label, program="hermes_agent.py", profile="scout"):
        agents = self.home / "Library" / "LaunchAgents"
        agents.mkdir(parents=True, exist_ok=True)
        path = agents / (label + ".plist")
        plistlib.dump({"Label": label, "ProgramArguments": ["/usr/bin/python3", "/x/" + program, "heartbeat",
                                                            "--profile", profile]}, path.open("wb"))
        return path

    def test_install_removes_the_old_launchd_job_for_this_profile_only(self):
        old = self.old_plist("com.acme.tico-agent.scout")
        other_profile = self.old_plist("com.acme.tico-agent.other", profile="other")
        not_ours = self.old_plist("com.example.tico-agent.scout", program="backup.py")
        out = self.install()
        self.assertFalse(old.exists())
        self.assertTrue(other_profile.exists())
        self.assertTrue(not_ours.exists())
        self.assertTrue((self.home / "Library/LaunchAgents/team.tico-agent.scout.plist").exists())
        self.assertIn(["launchctl", "bootout", "gui/%d" % os.getuid(), str(old)], self.fake.calls)
        self.assertIn("removed the older launchd job com.acme.tico-agent.scout", out)

    def test_pair_and_update_clean_up_too(self):
        old = self.old_plist("com.acme.tico-agent.scout")
        self.hub.pair_states = [{"state": "approved", "bot": "scout", "token": TOKEN}]
        code, out, err = self.run_cli("pair", "--profile", "scout", "--url", self.hub.url)
        self.assertEqual(code, 0, err)
        self.assertFalse(old.exists())
        again = self.old_plist("com.acme.tico-agent.scout")
        self.assertEqual(self.run_cli("reinstall", "--profile", "scout")[0], 0)
        self.assertFalse(again.exists())

    def test_install_removes_old_systemd_units_for_this_profile(self):
        self.platform("linux")
        units = self.home / ".config" / "systemd" / "user"
        units.mkdir(parents=True)
        (units / "com.acme.tico-agent.scout.service").write_text("[Service]\nExecStart=/usr/bin/python3 /x/hermes_agent.py heartbeat --profile scout\n")
        (units / "com.acme.tico-agent.scout.timer").write_text("[Timer]\nOnBootSec=30\n")
        (units / "tico-agent-other.service").write_text("[Service]\nExecStart=/usr/bin/python3 /x/hermes_agent.py heartbeat --profile other\n")
        (units / "tico-agent-other.timer").write_text("[Timer]\n")
        self.install()
        self.assertFalse((units / "com.acme.tico-agent.scout.service").exists())
        self.assertFalse((units / "com.acme.tico-agent.scout.timer").exists())
        self.assertTrue((units / "tico-agent-other.timer").exists())
        self.assertTrue((units / "tico-agent-scout.timer").exists())
        self.assertIn(["systemctl", "--user", "disable", "--now", "com.acme.tico-agent.scout.timer"], self.fake.calls)
        self.assertNotIn(["systemctl", "--user", "disable", "--now", "tico-agent-other.timer"], self.fake.calls)


class Backoff(Base):
    ARCHIVED = (409, {"error": {"code": "bot_archived", "detail": "Bot scout is archived"}})

    def beat(self):
        return self.run_cli("heartbeat", "--profile", "scout")

    def test_archived_backs_off_to_once_an_hour_and_recovers(self):
        self.install("--no-timer")
        self.hub.heartbeat = self.ARCHIVED
        before = self.hub.count("/api/v2/agents/heartbeat")
        code, out, err = self.beat()
        self.assertEqual(code, 1)
        self.assertEqual(err.strip(), "Bot scout is archived in Tico: restore it (ask BotOps) or run uninstall")
        self.assertEqual(self.hub.count("/api/v2/agents/heartbeat"), before + 1)
        # The next minute is skipped without calling the hub.
        now = H.time.time()
        with mock.patch.object(H.time, "time", lambda: now + 60):
            self.assertEqual(self.beat()[0], 0)
        self.assertEqual(self.hub.count("/api/v2/agents/heartbeat"), before + 1)
        self.assertIn("backoff", self.credential())
        # After an hour it tries once more, still archived, and waits another hour.
        with mock.patch.object(H.time, "time", lambda: now + 3601):
            code, out, err = self.beat()
        self.assertEqual(code, 1)
        self.assertEqual(self.hub.count("/api/v2/agents/heartbeat"), before + 2)
        # Restored: the next attempt after the wait succeeds and normal service resumes.
        self.hub.heartbeat = (200, {"server_time": "t", "bot": "scout", "waiting": {"messages": 0, "tasks": 0}})
        with mock.patch.object(H.time, "time", lambda: now + 3601 + 3601):
            code, out, err = self.beat()
        self.assertEqual(code, 0, err)
        self.assertIn("answers again", out)
        self.assertNotIn("backoff", self.credential())
        self.assertEqual(self.beat()[0], 0)
        self.assertEqual(self.hub.count("/api/v2/agents/heartbeat"), before + 4)

    def test_older_servers_are_matched_by_the_word_archived(self):
        self.install("--no-timer")
        self.hub.heartbeat = (409, {"error": {"code": "conflict", "detail": "This bot is Archived"}})
        code, out, err = self.beat()
        self.assertEqual(code, 1)
        self.assertIn("Bot scout is archived in Tico", err)
        self.assertIn("backoff", self.credential())

    def test_other_409s_do_not_back_off(self):
        self.install("--no-timer")
        self.hub.heartbeat = (409, {"error": {"code": "bot_paused", "detail": "Bot is paused"}})
        code, out, err = self.beat()
        self.assertEqual(code, 1)
        self.assertIn("paused", err)
        self.assertNotIn("backoff", self.credential())

    def test_revoked_says_to_pair_again_and_backs_off(self):
        self.install("--no-timer")
        self.hub.heartbeat = (401, {"error": {"code": "unauthorized", "detail": "Invalid credential"}})
        code, out, err = self.beat()
        self.assertEqual(code, 1)
        self.assertIn("credential revoked: run pair again", err)
        self.assertIn("backoff", self.credential())
        before = self.hub.count("/api/v2/agents/heartbeat")
        self.assertEqual(self.beat()[0], 0)
        self.assertEqual(self.hub.count("/api/v2/agents/heartbeat"), before)


if __name__ == "__main__":
    unittest.main(verbosity=2)
