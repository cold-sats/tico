"""The bot catalog (clients/catalog.py): a template becomes one bot's repository.

Nothing here talks to a server. The catalog is a temporary directory holding one card, which is
what `TICO_CATALOG_DIR` is for, so these tests say nothing about which bots the product ships.
"""
import os
import subprocess
import tempfile
import unittest
from datetime import date
from pathlib import Path

import yaml

from clients import catalog
from clients.routines import validate_schedules

CARD = """template: assistant
slug: coo
name: The Assistant
required: true
bootstrap: true
summary: Who people talk to.
owns:
  - the company's inbox
never:
  - sending money
runtime: codex
model: gpt-6-sol
reasoning_effort: xhigh
recommend_when:
  - always
"""

AGENT = """# {{bot_name}}

You are {{bot_name}}, the assistant at {{company_name}}. {{app_name}} is where the work lives,
and people call this company's assistant {{assistant_name}}.

## Owns
-

## Never without approval
See hub `policies/approvals.md`.
"""

MANIFEST = """name: CHANGE-ME
display_name: "Change Me"
labels: [owner:CHANGE-ME]
schedules: []
"""

NAMES = {"company_name": "Acme Ltd", "app_name": "Acme OS", "assistant_name": "Ada",
         "assistant_bot": "coo"}
ANSWERS = {"what_we_do": "we clean holiday homes", "customers": "owners of holiday homes",
           "team_size": "nine people", "work_arrives": ["email", "Slack"],
           "repetitive_work": "chasing cleaners for photos",
           "never_without_person": ["refunds", "signing a contract"]}


def fixture(root, template="assistant", card=CARD, agent=AGENT):
    """One catalog template on disk: a card, instructions, a manifest and the usual folders."""
    directory = Path(root) / template
    (directory / "playbooks").mkdir(parents=True)
    (directory / "card.yaml").write_text(card)
    (directory / "AGENT.md").write_text(agent)
    (directory / "employee.yaml").write_text(MANIFEST)
    (directory / "state.md").write_text("# State\n\nNothing yet.\n")
    (directory / ".gitignore").write_text(".env\n")
    (directory / "playbooks" / "README.md").write_text("Playbooks for {{bot_name}}.\n")
    return directory


def git(path, *argv):
    return subprocess.run(["git", "-C", str(path), *argv], capture_output=True, text=True).stdout.strip()


class Cards(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.catalog = Path(self.tmp.name) / "catalog"
        fixture(self.catalog)

    def test_a_template_name_can_never_leave_the_catalog(self):
        for name in ("../secrets", "/etc", "Assistant", ""):
            with self.assertRaises(ValueError):
                catalog.template_dir(name, self.catalog)
        with self.assertRaises(ValueError):
            catalog.template_dir("missing", self.catalog)


class Materialize(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.catalog = Path(self.tmp.name) / "catalog"
        fixture(self.catalog)
        self.workspace = Path(self.tmp.name) / "Companies/Acme"

    def make(self, slug="coo", **over):
        return catalog.materialize("assistant", slug, self.workspace, NAMES, ANSWERS,
                                   directory=self.catalog, **over)

    def test_an_existing_repository_is_never_overwritten(self):
        path = self.make()
        (path / "state.md").write_text("# State\n\nA turn happened here.\n")
        with self.assertRaises(ValueError) as caught:
            self.make()
        self.assertIn("already exists", str(caught.exception))
        self.assertIn("A turn happened here.", (path / "state.md").read_text())


STARTERS = ("chief-of-staff", "support", "sales", "meeting-notes", "inbox", "issue-triage")
PACKS = ("basics", "sales", "support", "operations", "engineering")


class StarterBots(unittest.TestCase):
    """The six starter templates (docs/starter-bots.md) carry the fields a chooser and a first
    session depend on, and none of them starts a routine before a person has approved it."""

    def test_every_starter_is_complete_and_draft_first(self):
        directory = catalog.ROOT / "templates/catalog"
        for name in STARTERS:
            folder, where = directory / name, f"template {name}"
            card = catalog.card(name, directory)
            self.assertTrue(card, where)
            self.assertIn(card.get("pack"), PACKS, where)
            for field in ("pains", "owns", "never", "approval_required"):
                self.assertTrue(card.get(field) and all(isinstance(x, str) for x in card[field]), f"{where}: {field}")
            self.assertTrue(card["recommend_when"], where)
            for need in card["prerequisites"]:
                self.assertTrue(need["tool"] and need["why"] and isinstance(need["required"], bool), where)
            self.assertTrue(any(need["required"] for need in card["prerequisites"]), where)
            self.assertTrue(4 <= len(card["onboarding"]) <= 7, where)
            self.assertTrue(all(q.get("ask") and q.get("why") for q in card["onboarding"]), where)
            first = card["first_routine"]
            self.assertTrue(first["title"] and first["cadence"] and first["output"], where)
            self.assertIs(first["draft_only"], True, where)
            self.assertTrue((folder / card["example_output"]).is_file(), where)
            agent = (folder / "AGENT.md").read_text()
            self.assertLessEqual(len(agent.splitlines()), 150, where)
            for heading in ("## Owns", "## Never without approval", "## First message: onboarding"):
                self.assertIn(heading, agent, where)
            playbooks = [p for p in (folder / "playbooks").glob("*.md") if p.name != "README.md"]
            self.assertGreaterEqual(len(playbooks), 3, where)
            self.assertTrue((folder / "playbooks/onboarding.md").is_file(), where)
            manifest = yaml.safe_load((folder / "employee.yaml").read_text())
            self.assertIs(manifest["outbound_send"], False, where)
            routines = validate_schedules(manifest["schedules"], lambda rel: (folder / rel).read_text())
            self.assertEqual(len(routines), 1, where)
            self.assertIs(routines[0]["enabled"], False, f"{where}: the first routine waits for a person's yes")
            for access in manifest["access"]:
                self.assertNotIn("send", access.get("can", []), where)

if __name__ == "__main__":
    unittest.main()
