"""What a turn's prompt says: who spoke each room line, and whose company this is
(runner/service.py `prompt`).

A committed batch writes the person's responses into each bot's room; the label says so. The
Live voice session that also wrote into the assistant's room was retired on 2026-09-24."""
import unittest

from clients.tico import APIError
from runner.service import Runner


def live(kind, **more):
    return {"live": {"kind": kind, "session": "s1", **more}}


def attempt(message, history):
    return {"bot": "coo", "conversation": {"id": "room", "scope": "personal", "kind": "chat",
                                          "owner_actor": "human:ana"},
            "message": message, "history": history + [message], "principal": "human:ana"}


def prompt_of(runner, payload, **kw):
    """A resumed thread that last answered before this page: every line on it is new."""
    kw.setdefault("after", "before-the-page"); kw.setdefault("resumed", True)
    return runner.prompt(payload, **kw)


class PromptLabels(unittest.TestCase):
    def setUp(self):
        self.runner = Runner.__new__(Runner)

    def test_history_lines_name_a_batch_and_otherwise_the_actor(self):
        history = [
            {"id": "m1", "from_actor": "human:ana", "body": "Typed: what is Sol on?", "refs": {}},
            {"id": "m2", "from_actor": "human:ana", "body": "1. Approve the refund.",
             "refs": live("batch", batch="b1", items=["t1"])},
            # A line from the retired Live session is an ordinary line now; its own words stay out.
            {"id": "m3", "from_actor": "human:ana", "body": "What needs me today?", "refs": live("transcript")},
            {"id": "m4", "from_actor": "bot:coo", "body": "Two approvals are waiting.", "refs": live("transcript")},
        ]
        current = {"id": "m5", "from_actor": "human:ana", "body": "Now a typed follow-up", "refs": {}}
        prompt = prompt_of(self.runner, attempt(current, history))
        self.assertIn("human:ana [m1]: Typed: what is Sol on?", prompt)
        self.assertIn("human:ana (batch responses) [m2]: 1. Approve the refund.", prompt)
        self.assertIn("human:ana [m3]: What needs me today?", prompt)
        self.assertNotIn("Two approvals are waiting.", prompt)
        self.assertIn("Current message from human:ana:\nNow a typed follow-up", prompt)
        self.assertNotIn("voice", prompt)

    def test_next_run_tasks_ride_in_the_same_prompt_under_one_header(self):
        # Bot Desk finds this block in the transcript by its header and shows each task apart.
        from runner.service import NEXT_RUN_HEADER
        current = {"id": "m1", "from_actor": "human:ana", "body": "Daily check", "refs": {}}
        payload = attempt(current, [])
        payload["next_run"] = [{"id": "t9", "title": "Watch the new refund requests", "body": "Released today.",
                                "requester": "bot:product-manager", "created": "2026-09-24T10:00:00Z"}]
        prompt = prompt_of(self.runner, payload)
        self.assertIn("Current message from human:ana:\nDaily check", prompt)
        self.assertIn(NEXT_RUN_HEADER + '\n[{"id": "t9", "title": "Watch the new refund requests"', prompt)
        self.assertLess(prompt.index("Daily check"), prompt.index(NEXT_RUN_HEADER))
        self.assertNotIn(NEXT_RUN_HEADER, prompt_of(self.runner, attempt(current, [])))


    def test_quiet_notes_ride_in_the_same_prompt_under_their_own_header(self):
        from runner.service import NOTES_HEADER, NEXT_RUN_HEADER
        current = {"id": "m1", "from_actor": "human:ana", "body": "Daily report", "refs": {}}
        payload = attempt(current, [])
        payload["notes"] = [{"id": "n1", "from": "bot:spend-monitor", "sent": "2026-09-24T11:15:00Z",
                             "text": "Fees steady at 3.9%."}]
        prompt = prompt_of(self.runner, payload)
        self.assertIn(NOTES_HEADER + '\n[{"id": "n1", "from": "bot:spend-monitor"', prompt)
        self.assertLess(prompt.index("Daily report"), prompt.index(NOTES_HEADER))
        self.assertNotIn(NEXT_RUN_HEADER, prompt)


class FakeConfig:
    """The runner's client, answering only GET /api/v2/config."""

    def __init__(self, config=None, error=None):
        self.config, self.error, self.calls = config, error, 0

    def get(self, path):
        assert path == "config"
        self.calls += 1
        if self.error:
            raise self.error
        return self.config


class Naming(unittest.TestCase):
    """A bot is its company's employee: every name in the prompt comes from the environment."""

    @staticmethod
    def runner(config=None, error=None):
        service = Runner.__new__(Runner)
        service.client = FakeConfig(config, error)
        return service

    @staticmethod
    def turn():
        ask = {"id": "a1", "from_actor": "human:dana", "refs": {}, "body": "The pipeline summary, please."}
        return attempt(ask, [])

    def test_the_prompt_names_this_company_and_never_the_product(self):
        service = self.runner({"company_name": "Initech", "app_name": "Mic", "assistant_name": "Mic",
                               "assistant_bot": "coo"})
        prompt = service.prompt(self.turn())
        self.assertIn("You are coo, an AI employee at Initech.", prompt)
        self.assertIn("Mic is the company's operating system", prompt)
        self.assertNotIn("Tico", prompt)
        service.prompt(self.turn())
        self.assertEqual(service.client.calls, 1)        # read once, then kept

class RoutinePlaybooks(unittest.TestCase):
    """A routine's text is saved once; when it is an older copy of a playbook the bot has since
    edited, the turn says to follow the file and to point the routine at it (2026-09-24)."""

    SWEEP = "# Morning competitor sweep\n\nRun software/listen.py --since 24h and save every card.\n"

    def setUp(self):
        import tempfile
        from pathlib import Path
        self.repo = Path(tempfile.mkdtemp())
        (self.repo / "playbooks").mkdir()
        (self.repo / "playbooks" / "sweep.md").write_text(self.SWEEP)
        (self.repo / "playbooks" / "weekly-site-diff.md").write_text("# Weekly site diff\n\nCompare pages.\n")
        self.runner = Runner.__new__(Runner)
        self.runner.config = {"repos": {"listening": str(self.repo)}, "projects_dir": str(self.repo.parent)}

    def note(self, body, routine=True):
        return self.runner.stale_playbook_note({"bot": "listening", "task": {"body": body},
                                                "routine": {"id": "listening:sweep", "title": "t"} if routine else None})

    def test_an_older_copy_points_at_the_current_file_and_the_fix(self):
        old = "# Morning competitor sweep\n\nRun software/listen.py --since 12h and keep matching cards only.\n"
        note = self.note(old)
        self.assertIn("older copy of `playbooks/sweep.md`", note)
        self.assertIn("hub routine update listening:sweep --text 'Run playbooks/sweep.md'", note)

if __name__ == "__main__":
    unittest.main()


class SpokenTurns(unittest.TestCase):
    """2026-09-24: in voice mode the bot narrated its plan ("I'll read the workspace state...")
    before answering; a spoken message asks for a short spoken answer first."""

    def prompt(self, refs):
        runner = Runner.__new__(Runner)
        runner.names = lambda: {"app_name": "Tico", "company_name": "Acme", "assistant_name": "Tico"}
        message = {"id": "m1", "from_actor": "human:ana", "body": "Hello.", "refs": refs}
        return runner.prompt({"bot": "reputation", "conversation": {"id": "c", "kind": "chat"},
                              "message": message, "history": [message]})

    def test_a_spoken_message_asks_for_the_answer_first(self):
        self.assertIn("Spoken turn", self.prompt({"voice": True}))
        self.assertNotIn("Spoken turn", self.prompt({}))


class RequestsBecomeTasks(unittest.TestCase):
    """Ana, 2026-09-24: a request for work is filed as the bot's own tasks first."""

    def prompt(self, sender, task=None):
        runner = Runner.__new__(Runner)
        runner.names = lambda: {"app_name": "Tico", "company_name": "Acme", "assistant_name": "Tico"}
        message = {"id": "m1", "from_actor": sender, "body": "Do x, y and z.", "refs": {}}
        payload = {"bot": "seo", "conversation": {"id": "c", "kind": "chat"}, "message": message, "history": [message]}
        if task:
            payload["task"] = task
        return runner.prompt(payload)

    def test_a_person_asking_for_work_is_told_to_file_tasks_first(self):
        self.assertIn("first file each distinct ask as a hub task you own", self.prompt("human:ana"))
        self.assertNotIn("first file each distinct ask", self.prompt("bot:cmo"))
        self.assertNotIn("first file each distinct ask", self.prompt("human:ana", task={"id": "t1", "body": "x"}))


class DesignAndVideoRequests(unittest.TestCase):
    """Ana, 2026-09-25: every bot knows it can ask Design for visuals and Video Producer for video."""

    def prompt(self, bot):
        runner = Runner.__new__(Runner)
        runner.names = lambda: {"app_name": "Tico", "company_name": "Acme", "assistant_name": "Tico"}
        message = {"id": "m1", "from_actor": "human:ana", "body": "Hello.", "refs": {}}
        return runner.prompt({"bot": bot, "conversation": {"id": "c", "kind": "chat"},
                              "message": message, "history": [message]})

    def test_every_other_bot_is_told_where_visuals_and_video_come_from(self):
        text = self.prompt("cmo")
        self.assertIn("bot:designer", text)
        self.assertIn("bot:video-producer", text)
        self.assertNotIn("File a task for bot:designer", self.prompt("designer"))
