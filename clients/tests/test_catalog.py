"""The bot catalog (clients/catalog.py): a template becomes one bot's repository.

Nothing here talks to a server. The catalog is a temporary directory holding one card, which is
what `TICO_CATALOG_DIR` is for, so these tests say nothing about which bots the product ships.
"""
import functools
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


class Refresh(unittest.TestCase):
    """A built-in bot follows the release: the product's instructions and playbooks are brought up when the template
    changed, and whatever the bot improved and wrote itself stays."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.catalog = Path(self.tmp.name) / "catalog"
        self.template = fixture(self.catalog)
        (self.template / "playbooks" / "fleet.md").write_text("Check the fleet for {{company_name}}.\n")
        self.path = catalog.materialize("assistant", "coo", Path(self.tmp.name) / "ws", NAMES, ANSWERS, directory=self.catalog)

    def refresh(self):
        return catalog.refresh("assistant", self.path, NAMES, directory=self.catalog)

    def test_an_unchanged_template_leaves_what_the_bot_improved(self):
        (self.path / "playbooks" / "fleet.md").write_text("Improved by the bot.\n")
        self.assertEqual(self.refresh(), [])
        self.assertEqual((self.path / "playbooks" / "fleet.md").read_text(), "Improved by the bot.\n")

    def test_a_changed_template_file_wins_and_the_rest_stays_the_bots(self):
        (self.path / "playbooks" / "fleet.md").write_text("Improved by the bot.\n")
        (self.path / "playbooks" / "mine.md").write_text("A playbook the bot wrote.\n")
        (self.path / "state.md").write_text("# State\n\nMid-task.\n")
        (self.template / "playbooks" / "fleet.md").write_text("Check the fleet, then fix it, for {{company_name}}.\n")
        self.assertEqual(self.refresh(), ["playbooks/fleet.md"])
        self.assertEqual((self.path / "playbooks" / "fleet.md").read_text(), "Check the fleet, then fix it, for Acme Ltd.\n")
        self.assertEqual((self.path / "playbooks" / "mine.md").read_text(), "A playbook the bot wrote.\n")
        self.assertIn("Mid-task.", (self.path / "state.md").read_text())
        self.assertIn("Refresh 1 product file", git(self.path, "log", "-1", "--format=%s"))
        self.assertEqual(git(self.path, "show", "HEAD~1:playbooks/fleet.md"), "Improved by the bot.")     # kept in the history
        self.assertEqual(self.refresh(), [])                        # once

    def test_a_repository_from_before_the_stamp_is_brought_up_once(self):
        (self.path / catalog.STAMP).unlink()
        (self.path / "AGENT.md").write_text("# Drifted long ago\n")
        changed = self.refresh()
        self.assertIn("AGENT.md", changed)
        self.assertIn("Acme Ltd", (self.path / "AGENT.md").read_text())
        (self.path / "AGENT.md").write_text("# The bot's own improvement\n")
        self.assertEqual(self.refresh(), [])

    def test_a_starter_bot_is_never_refreshed(self):
        starter = Path(self.tmp.name) / "catalog" / "starter"
        fixture(self.catalog, "starter", card=CARD.replace("bootstrap: true", "bootstrap: false").replace("assistant", "starter"))
        path = catalog.materialize("starter", "st", Path(self.tmp.name) / "ws", NAMES, ANSWERS, directory=self.catalog)
        (starter / "AGENT.md").write_text("# New\n")
        self.assertEqual(catalog.refresh("starter", path, NAMES, directory=self.catalog), [])


PACKS = ("basics", "sales", "marketing", "support", "operations", "engineering")
# templates/departments.yaml: the departments onboarding offers, in order, and the extras it does not offer.
DEPARTMENTS = ("sales", "marketing", "support", "finance", "operations", "legal", "hr", "product", "engineering")
# `pack` is the older six-team grouping the chooser still reads; it follows the department.
PACK_OF = {"sales": "sales", "marketing": "marketing", "support": "support", "operations": "operations", "finance": "basics",
           "legal": "basics", "hr": "basics", "leadership": "basics", "product": "engineering", "engineering": "engineering"}
SUGGEST = ("default", "common", "niche")
# The icons the UI's subset font holds (scripts/build-icon-font.py adds every card's and department's icon to it).
ICONS = set((catalog.ROOT / "ui/vendor/fonts/icons.txt").read_text().split())
# The tags backend/onboarding.py derives from a company's answers, and the tools a prerequisite may name.
TAGS = {"always", "sells_to_businesses", "sells_to_consumers", "sells_software", "small_team", "uses_email", "uses_slack", "uses_crm",
        "uses_tickets", "has_support_inbox", "uses_github", "uses_meetings", "uses_docs", "has_pipeline", "publishes_content",
        "tracks_mentions", "has_personal_inbox"}
TOOLS = {"hub", "mail", "chat", "crm", "github", "meetings", "calendar", "docs", "web"}


@functools.lru_cache(maxsize=None)
def read_catalog(directory):
    """Every card once, by template name: the checks below look cards up a hundred times."""
    return {card["template"]: card for card in catalog.cards(directory)}


def starters(directory):
    """Every template a company can pick: all but the built-ins the platform always creates."""
    return sorted(name for name, card in read_catalog(directory).items() if not card.get("required") and not card.get("bootstrap"))


def is_helper(card):
    """A helper (`kind: helper`) serves a person, like the built-ins: no department, no head, not on the org chart."""
    return card.get("kind") == "helper"


class StarterBots(unittest.TestCase):
    """Every catalog template (docs/starter-bots.md) carries the fields a chooser and a first session depend on,
    and none of them starts a routine before a person has approved it or reaches outside the company on its own."""

    directory = catalog.ROOT / "templates/catalog"

    def test_every_template_is_complete_and_draft_first(self):
        names = starters(self.directory)
        self.assertGreaterEqual(len(names), 90)
        for name in names:
            with self.subTest(template=name):
                self.check(name)

    def test_every_department_has_its_head_and_no_pain_phrase_is_offered_twice(self):
        """templates/departments.yaml names each department's head; that card is the department's only `lead: true`, and
        its `team_templates` are the rest of the department."""
        cards = [read_catalog(self.directory)[name] for name in starters(self.directory)]
        cards = [card for card in cards if not is_helper(card)]
        document = yaml.safe_load((catalog.ROOT / "templates/departments.yaml").read_text())
        departments, extras = document["departments"], document.get("extras") or []
        self.assertEqual([row["id"] for row in departments], list(DEPARTMENTS))
        for row in departments:
            for field in ("name", "description", "goal", "question", "placeholder"):
                self.assertTrue(isinstance(row.get(field), str) and row[field].strip(), f"department {row['id']}: {field}")
            self.assertIs(row.get("software_only", False), row["id"] in ("product", "engineering"), row["id"])
        for row in departments + extras:
            self.assertIn(row["icon"], ICONS, f"department {row['id']}: icon")
            members = {card["template"]: card for card in cards if card["department"] == row["id"]}
            leads = [name for name, card in members.items() if card.get("lead") is True]
            self.assertEqual(leads, [row["head"]], f"department {row['id']} needs exactly one `lead: true` card, its head")
            self.assertEqual(sorted(members[row["head"]]["team_templates"]), sorted(set(members) - {row["head"]}),
                             f"{row['head']}: team_templates are the rest of department {row['id']}")
        known = {row["id"] for row in departments + extras}
        self.assertFalse({card["department"] for card in cards} - known, "a card names a department not in departments.yaml")
        self.assertEqual([card["template"] for card in cards if "always" in card["recommend_when"]], ["chief-of-staff"])
        phrases = [phrase.lower() for card in cards for phrase in card["pains"]]
        self.assertEqual(len(phrases), len(set(phrases)), "a pain phrase belongs to one template")

    def test_every_card_and_built_in_has_an_icon_the_ui_font_holds(self):
        for card in read_catalog(self.directory).values():
            self.assertIn(card.get("icon"), ICONS, f"template {card['template']}: icon")

    def check(self, name):
        folder, where = self.directory / name, f"template {name}"
        card = read_catalog(self.directory).get(name)
        self.assertTrue(card, where)
        self.assertIn(card.get("kind", "role"), ("role", "helper"), f"{where}: kind")
        if is_helper(card):
            for field in ("department", "pack", "lead", "team_templates", "suggest"):
                self.assertNotIn(field, card, f"{where}: a helper is in no department")
        else:
            self.assertIn(card.get("pack"), PACKS, where)
            # What the org builder groups, pictures and pre-checks by (templates/departments.yaml).
            self.assertIn(card.get("department"), PACK_OF, f"{where}: department")
            self.assertEqual(card["pack"], PACK_OF[card["department"]], f"{where}: pack follows the department")
            self.assertIn(card.get("suggest"), SUGGEST, f"{where}: suggest")
        self.assertIn(card.get("icon"), ICONS, f"{where}: icon {card.get('icon')!r} is not in ui/vendor/fonts/icons.txt")
        self.assertTrue(card.get("tags") and all(isinstance(t, str) and t == t.lower() and len(t) <= 24 for t in card["tags"]),
                        f"{where}: tags")
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
        for heading in ("## Owns", "## Never without approval", "## First message: setup"):
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
            self.assertIs(routine["enabled"], False, f"{where}: a routine is declared off and setup switches it on")
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
