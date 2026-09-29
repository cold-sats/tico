"""The `hub` CLI as a bot runs it: `scripts/hub` in a subprocess, remote-only.

The command surface (docs/history/hub-v2.md §5) and the exit codes are the contract every bot's AGENT.md
depends on: 0 fine, 2 refused or a non-retryable API error, 1 anything else. The real HTTP round
trip is `backend/tests/test_runner.py`; here the API is a stub or absent.
"""
import json
import os
import subprocess
import sys
import tempfile
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from threading import Thread

from clients import hubcli

HUB = Path(__file__).resolve().parents[2] / "scripts" / "hub"
SUBCOMMANDS = ["whoami", "say", "ask", "answer", "notice", "note", "notes", "unnote", "files", "assistant", "task", "goals", "goal", "kpi", "market", "listen", "intake", "history", "routine", "approval", "status", "turns",
               "inbox", "ack", "board", "org", "fleet", "update", "updates", "grokbot", "recent", "calendar", "sql", "db", "github", "integrations", "integration", "queries", "learn",
               "decisions", "judge", "catalog", "bot"]
SUBCOMMANDS[SUBCOMMANDS.index("approval") + 1:SUBCOMMANDS.index("approval") + 1] = ["live", "batch"]
SUBCOMMANDS[1:1] = ["context", "meetings"]


def run_hub(*args, env=None):
    base = {k: v for k, v in os.environ.items() if not k.startswith("HUB_")}
    done = subprocess.run([sys.executable, str(HUB), *args], env={**base, **(env or {})},
                          capture_output=True, text=True, timeout=60)
    try:
        return done.returncode, json.loads(done.stdout)
    except ValueError:
        return done.returncode, {"_stdout": done.stdout, "_stderr": done.stderr}


class Parser(unittest.TestCase):
    def test_every_subcommand_is_still_there(self):
        text = hubcli.parser().format_help()
        self.assertIn("{" + ",".join(SUBCOMMANDS) + "}", text)

class Remote(unittest.TestCase):
    def test_human_override_is_refused_remotely_with_exit_two(self):
        code, out = run_hub("--human", "ana", "whoami",
                            env={"HUB_API_URL": "http://127.0.0.1:9", "HUB_TOKEN": "x"})
        self.assertEqual(code, 2)
        self.assertEqual(out["error"], "identity")


PAGE = {
    "service": "hub-sql", "title": "Hub database (SQL)", "kind": "sql", "summary": "Read-only SQL over the hub.",
    "writes": "never", "owner": "ana", "aliases": ["sqlite"], "access": "hub sql in a turn",
    "credentials": ["none"], "declared_as": "nothing to declare\n",
    "body": "## What it is\n\nThe hub database.\n\n## Rules\n\n- One SELECT.\n",
    "queries": [
        {"id": "queued-work", "title": "Queued work", "description": "Jobs waiting per bot.", "category": "work",
         "tags": ["jobs", "queue"], "database": "hub.sqlite",
         "sql": "SELECT bot, count(*) AS queued FROM jobs WHERE state='queued' GROUP BY bot\n", "params": []},
        {"id": "task-history", "title": "A task history", "description": "Every change to one task.", "category": "tasks",
         "tags": ["tasks"], "database": "hub.sqlite",
         "sql": "SELECT ts, actor FROM task_events WHERE task_id=:task ORDER BY ts\n",
         "params": [{"name": "task", "type": "text", "label": "Task id", "required": True}]}],
    "learnings": [{"id": "L1", "integration": "hub-sql", "actor": "bot:seo", "text": "Compare timestamps as text.",
                   "created": "2026-09-15T10:00:00Z"}],
}


class Stub(BaseHTTPRequestHandler):
    """Enough of the Tico API to see what the CLI sends: /me, one task, one refusal, one integration."""
    seen = []

    def log_message(self, *a):
        pass

    def reply(self, status, body):
        data = json.dumps(body).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        self.seen.append(("GET", self.path, self.headers.get("Authorization"), None))
        if self.path == "/api/v2/me":
            return self.reply(200, {"actor": "bot:coo", "kind": "bot", "id": "coo"})
        if self.path.startswith("/api/v2/tasks/T1"):
            return self.reply(200, {"task": {"id": "T1", "version": 3}})
        if self.path.startswith("/api/v2/goals?"):
            return self.reply(200, {"owner": "bot:coo", "goals": [{"id": "G1", "title": "Keep every bot able to do its job"}],
                                    "chain": [{"id": "G0", "title": "Grow revenue"}], "reports": [], "company": []})
        if self.path == "/api/v2/goals":
            return self.reply(200, {"owner": "bot:coo", "goals": [{"id": "G1"}], "chain": [], "reports": [], "company": []})
        if self.path == "/api/v2/goals/G1":
            return self.reply(200, {"goal": {"id": "G1", "status": "green", "kpis": []}})
        if self.path == "/api/v2/kpis/K1/readings":
            return self.reply(200, {"kpi": {"id": "K1"}, "readings": [{"value": 17.0}]})
        if self.path == "/api/v2/integrations":
            return self.reply(200, {"integrations": [
                {"service": "hub-sql", "title": "Hub database (SQL)", "kind": "sql", "summary": "Read-only SQL over the hub.",
                 "access": "hub sql in a turn", "credentials": ["none"], "declared_as": "nothing to declare\n",
                 "writes": "never", "owner": "ana", "aliases": [], "query_count": 2, "learning_count": 1},
                {"service": "slack", "title": "Slack", "kind": "api", "summary": "Channels and DMs.",
                 "access": "connectors/slack.py", "credentials": ["SLACK_BOT_TOKEN — shared"],
                 "declared_as": "env: SLACK_BOT_TOKEN\n",
                 "writes": "allowed", "owner": "ana", "aliases": [], "query_count": 0, "learning_count": 0}]})
        if self.path in ("/api/v2/integrations/hub-sql", "/api/v2/integrations/sqlite"):
            return self.reply(200, PAGE)
        if self.path.startswith("/api/v2/integrations/"):
            return self.reply(404, {"error": {"code": "not_found", "detail": "No integration named " + self.path.rsplit("/", 1)[1]}})
        self.reply(404, {"error": {"code": "not_found", "detail": "no"}})

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or b"{}")
        self.seen.append(("POST", self.path, self.headers.get("Authorization"), body))
        if self.path == "/api/v2/tasks":
            return self.reply(200, {"task": {"id": "T2", "title": body["title"], "owner": body["owner"]}})
        if self.path == "/api/v2/tasks/T1":
            return self.reply(200, {"task": {"id": "T1", "status": body.get("status"), "version": 4,
                                             "goal_id": body.get("goal_id")}})
        if self.path == "/api/v2/goals":
            return self.reply(200, {"goal": {"id": "G2", "title": body["title"], "owner": body["owner"],
                                             "parent_id": body.get("parent_id"), "status": None}})
        if self.path == "/api/v2/goals/G1/status":
            return self.reply(200, {"goal": {"id": "G1", "status": body["status"], "status_note": body["note"]}})
        if self.path == "/api/v2/goals/G1":
            return self.reply(200, {"goal": {"id": "G1", **{k: v for k, v in body.items() if v is not None}}})
        if self.path == "/api/v2/goals/G1/kpis":
            return self.reply(200, {"kpi": {"id": "K1", "goal_id": "G1", "name": body["name"], "unit": body["unit"],
                                            "target": body.get("target")}})
        if self.path == "/api/v2/kpis/K1/readings":
            return self.reply(200, {"reading": {"id": "R1", "kpi_id": "K1", "value": body["value"],
                                                "source": body["source"], "at": body.get("at")}})
        if self.path == "/api/v2/bots/coo/routines":
            return self.reply(200, {"routine": {"id": "coo:" + body["key"], "title": body["title"], "cron": body["cron"]}})
        if self.path == "/api/v2/routines/coo:audit":
            return self.reply(200, {"routine": {"id": "coo:audit", "enabled": body["enabled"]}})
        if self.path == "/api/v2/tasks/T1/files":
            return self.reply(200, {"file": {"id": "F1", "name": body["name"], "url": "/api/v2/files/F1"},
                                    "link": "https://tico.test/api/v2/files/F1"})
        if self.path == "/api/v2/integrations/hub-sql/learnings":
            if not body.get("text"):
                return self.reply(422, {"error": {"code": "validation", "detail": "text: too short"}})
            return self.reply(200, {"id": "L2", "integration": "hub-sql", "actor": "bot:coo", "text": body["text"],
                                    "created": "2026-09-15T11:00:00Z"})
        if self.path == "/api/v2/judge":
            options = list(body["questions"]["covered"]["criteria"]) if "covered" in body["questions"] else []
            answers = {qid: ({"type": "choice", "choice": options[0], "confidence": 0.77,
                              "probabilities": {o: 0.1 for o in options}} if q["type"] == "choice"
                             else {"type": "noul", "noul": 0.2}) for qid, q in body["questions"].items()}
            return self.reply(200, {"model": "judge-1.13.0", "answers": answers, "usage": {"input_tokens": 50},
                                    "ms": 190, "label": body.get("label")})
        if self.path == "/api/v2/sql":
            if "credentials" in body["sql"]:
                return self.reply(422, {"error": {"code": "sql", "detail": "access to credentials.id is prohibited"}})
            return self.reply(200, {"columns": ["bot", "state", "focus"], "ms": 3, "truncated": body.get("max_rows") == 2,
                                    "rows": [["coo", "idle", None], ["seo", "running", "Writing the brief\nfor the launch"]][:body.get("max_rows") or 2],
                                    "row_count": min(2, body.get("max_rows") or 2)})
        self.reply(422, {"error": {"code": "refused", "detail": "rule 2: not on the roster"}})


class AgainstAStub(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = HTTPServer(("127.0.0.1", 0), Stub)
        cls.thread = Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.env = {"HUB_API_URL": f"http://127.0.0.1:{cls.server.server_port}",
                   "HUB_TOKEN": "turn-token", "HUB_EMPLOYEE": "coo"}

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()

    def setUp(self):
        Stub.seen.clear()

    def test_whoami_is_the_api_identity_under_the_turn_token(self):
        code, out = run_hub("whoami", env=self.env)
        self.assertEqual(code, 0)
        self.assertEqual(out["actor"], "bot:coo")
        self.assertEqual(Stub.seen[0][2], "Bearer turn-token")

    def test_task_update_reads_the_version_first_so_a_stale_write_cannot_clobber(self):
        code, out = run_hub("task", "update", "T1", "--status", "done", "--note", "shipped", env=self.env)
        self.assertEqual(code, 0)
        self.assertEqual(out["status"], "done")
        posted = next(b for m, p, _, b in Stub.seen if m == "POST")
        self.assertEqual((posted["version"], posted["status"], posted["note"]), (3, "done", "shipped"))

    def test_a_refusal_from_the_api_exits_two(self):
        code, out = run_hub("say", "nobody", "hello", env=self.env)
        self.assertEqual(code, 2)
        self.assertEqual(out["error"], "refused")
        self.assertIn("roster", out["detail"])


CARD = """template: specialist
slug: seo
name: The Specialist
bootstrap: false
required: false
summary: Writes the blog.
owns: []
never: []
runtime: codex
"""
AGENT = "# {{bot_name}}\n\nYou are {{bot_name}} at {{company_name}} ({{app_name}}).\n\n## Owns\n- the blog\n"
NAMES = {"company_name": "Acme Ltd", "app_name": "Acme OS", "assistant_name": "Ada", "assistant_bot": "coo"}
ONBOARDING = {"names": NAMES,
              "answers": {"what_we_do": "we clean holiday homes", "customers": "owners",
                          "team_size": "nine people", "work_arrives": ["email"],
                          "never_without_person": ["refunds"]},
              "selected": {"seo": {"template": "specialist", "display_name": "Sam",
                                   "instructions": "# Sam\n\n## Owns\n- the blog\n"}},
              "completed": True}


class BotSetup(unittest.TestCase):
    """`hub catalog` and `hub bot create|check`: the three commands BotOps needs in a turn.

    The parsing is the real parser and the work is the real `clients/catalog.py`; only the API is
    a fake, so what these assert is which endpoints a command reads and what it writes to disk.
    """

    class FakeClient:
        def __init__(self, cards=None, onboarding=ONBOARDING):
            self.cards, self.record, self.seen, self.posted = cards, onboarding, [], []

        def post(self, path, body, key=None):
            self.posted.append((path, body))
            return {"routine": {"id": path.split("/")[1] + ":" + body["key"]}}

        def get(self, path, **query):
            self.seen.append(path)
            if path == "config":
                return dict(NAMES)
            if path == "onboarding":
                return json.loads(json.dumps(self.record))
            if path == "catalog" and self.cards is not None:
                return {"cards": self.cards}
            from clients.tico import APIError
            raise APIError("not_found", "No such endpoint: " + path, 404, False)

    def setUp(self):
        from clients import remotecli
        self.remotecli = remotecli
        root = Path(tempfile.mkdtemp())
        self.addCleanup(lambda: __import__("shutil").rmtree(root, ignore_errors=True))
        self.workspace, catalog = root / "work", root / "catalog"
        (catalog / "specialist").mkdir(parents=True)
        (catalog / "specialist" / "card.yaml").write_text(CARD)
        (catalog / "specialist" / "AGENT.md").write_text(AGENT)
        (catalog / "specialist" / "employee.yaml").write_text('name: CHANGE-ME\ndisplay_name: "Change Me"\nschedules: []\n')
        (catalog / "specialist" / "state.md").write_text("# State\n")
        for key, value in {"HUB_WORKSPACE": str(self.workspace), "TICO_CATALOG_DIR": str(catalog)}.items():
            os.environ[key] = value
            self.addCleanup(os.environ.pop, key, None)
        self.client = self.FakeClient()

    def run_command(self, *argv):
        return self.remotecli.bots(self.client, hubcli.parser().parse_args(list(argv)))

    def test_creating_a_bot_twice_refuses_rather_than_overwriting_its_memory(self):
        self.run_command("bot", "create", "seo", "--template", "specialist")
        with self.assertRaises(ValueError) as refused:
            self.run_command("bot", "create", "seo", "--template", "specialist")
        self.assertIn("already exists", str(refused.exception))

if __name__ == "__main__":
    unittest.main(verbosity=2)
