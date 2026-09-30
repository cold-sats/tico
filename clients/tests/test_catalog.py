"""The bot catalog (clients/catalog.py): a template becomes one bot's repository.

Nothing here talks to a server. The catalog is a temporary directory holding one card, which is
what `TICO_CATALOG_DIR` is for, so these tests say nothing about which bots the product ships.
"""
import json
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


PACKS = ("basics", "sales", "marketing", "support", "operations", "engineering")
# The tags backend/onboarding.py derives from a company's answers, and the tools a prerequisite may name.
TAGS = {"always", "sells_to_businesses", "sells_to_consumers", "sells_software", "small_team", "uses_email", "uses_slack", "uses_crm",
        "uses_tickets", "has_support_inbox", "uses_github", "uses_meetings", "uses_docs", "has_pipeline", "publishes_content",
        "tracks_mentions", "has_personal_inbox"}
TOOLS = {"hub", "mail", "chat", "crm", "github", "meetings", "calendar", "docs", "web"}


def starters(directory):
    """Every template a company can pick: all but the built-ins the platform always creates."""
    return sorted(card["template"] for card in catalog.cards(directory) if not card.get("required") and not card.get("bootstrap"))


class StarterBots(unittest.TestCase):
    """Every catalog template (docs/starter-bots.md) carries the fields a chooser and a first session depend on,
    and none of them starts a routine before a person has approved it or reaches outside the company on its own."""

    directory = catalog.ROOT / "templates/catalog"

    def test_every_template_is_complete_and_draft_first(self):
        names = starters(self.directory)
        self.assertGreaterEqual(len(names), 25)
        for name in names:
            with self.subTest(template=name):
                self.check(name)

    def test_every_pack_has_one_lead_and_no_pain_phrase_is_offered_twice(self):
        cards = [catalog.card(name, self.directory) for name in starters(self.directory)]
        for pack in PACKS:
            leads = [card["template"] for card in cards if card.get("pack") == pack and card.get("lead") is True]
            self.assertEqual(len(leads), 1, f"pack {pack} needs exactly one `lead: true` card, has {leads}")
        self.assertEqual([card["template"] for card in cards if card.get("pack") == "basics" and card.get("lead")], ["chief-of-staff"])
        phrases = [phrase.lower() for card in cards for phrase in card["pains"]]
        self.assertEqual(len(phrases), len(set(phrases)), "a pain phrase belongs to one template")

    def check(self, name):
        folder, where = self.directory / name, f"template {name}"
        card = catalog.card(name, self.directory)
        self.assertTrue(card, where)
        self.assertIn(card.get("pack"), PACKS, where)
        for field in ("pains", "owns", "never", "approval_required"):
            self.assertTrue(card.get(field) and all(isinstance(x, str) for x in card[field]), f"{where}: {field}")
        self.assertTrue(3 <= len(card["pains"]) <= 6 and all(len(x) <= 90 for x in card["pains"]), f"{where}: pains")
        # The first sentence of the summary is the "why" line a person reads in onboarding: concrete, and not cut short.
        summary = card["summary"]
        self.assertTrue(summary.strip(), where)
        first = summary.strip().split(". ")[0]
        self.assertTrue(40 <= len(first) <= 185, f"{where}: the first sentence of the summary is {len(first)} characters")
        self.assertNotRegex(summary, r"(?i)fits how you|\btidy\b", where)
        self.assertTrue(card["recommend_when"] and set(card["recommend_when"]) <= TAGS, f"{where}: recommend_when")
        if name != "chief-of-staff":
            self.assertNotIn("always", card["recommend_when"], f"{where}: only Chief of Staff is for every company")
        for need in card["prerequisites"]:
            self.assertTrue(need["tool"] in TOOLS and need["why"] and isinstance(need["required"], bool), where)
        self.assertTrue(any(need["required"] for need in card["prerequisites"]), where)
        self.assertTrue(4 <= len(card["onboarding"]) <= 7, where)
        self.assertTrue(all(q.get("ask") and q.get("why") for q in card["onboarding"]), where)
        first = card["first_routine"]
        self.assertTrue(first["title"] and first["cadence"] and first["output"], where)
        self.assertIs(first["draft_only"], True, where)
        self.assertTrue(any("routine" in x.lower() for x in card["approval_required"]), f"{where}: arming a routine needs a Confirm")
        example = folder / card["example_output"]
        self.assertTrue(example.is_file(), where)
        self.assertIn("Acme", example.read_text(), where)
        agent = (folder / "AGENT.md").read_text()
        self.assertLessEqual(len(agent.splitlines()), 150, where)
        self.assertTrue(agent.startswith("# {{bot_name}}"), where)
        for heading in ("## Owns", "## Never without approval", "## First message: onboarding"):
            self.assertIn(heading, agent, where)
        playbooks = [p for p in (folder / "playbooks").glob("*.md") if p.name != "README.md"]
        self.assertGreaterEqual(len(playbooks), 3, where)
        self.assertTrue((folder / "playbooks/onboarding.md").is_file(), where)
        manifest = yaml.safe_load((folder / "employee.yaml").read_text())
        self.assertEqual(manifest["name"], card["slug"], where)
        self.assertIs(manifest["outbound_send"], False, where)
        routines = validate_schedules(manifest["schedules"], lambda rel: (folder / rel).read_text())
        self.assertTrue(routines and routines[0]["title"] == first["title"], f"{where}: the first routine is the card's")
        for routine in routines:
            self.assertIs(routine["enabled"], False, f"{where}: a routine waits for a person's yes")
        for access in manifest["access"]:
            # Nothing a starter can do reaches outside the company on its own: no send, and no write to a
            # service (a person applies what it proposes, until the owner turns writing on).
            self.assertFalse({"send", "write", "modify", "delete"} & set(access.get("can", [])), where)
        allowed = json.loads((folder / ".claude/settings.json").read_text())["permissions"]["allow"]
        for entry in allowed:
            self.assertNotRegex(entry, r"^Bash\(gh (issue|pr|api) (\*|comment|edit|create|close|review|merge)", f"{where}: {entry}")
        # The last step of onboarding tells the hub a person approved the first routine.
        self.assertIn("hub bot onboarded", (folder / "playbooks/onboarding.md").read_text(), where)


if __name__ == "__main__":
    unittest.main()
