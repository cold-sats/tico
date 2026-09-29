#!/usr/bin/env python3
"""Unit tests for the people roster (backend/people.py).

The documents are inline, in the shape `registry/people.yaml` and `registry/employees.yaml` use.
"""
import unittest

from backend import people as P

DOC = {
    "default_user": "ana",
    "teams": {"marketing": {"root": "cmo"}, "product": {"root": "cpo"},
              "human-ops": {"root": "human-ops"}, "sales": {"root": "sales"}},
    "people": [
        {"id": "ana", "name": "Ana Rivera", "email": "Ana@Acme.example", "title": "Founder",
         "team": "leadership", "primary_for": ["marketing"], "bot": None},
        {"id": "ben", "name": "Ben", "email": "ben@acme.example", "title": "Product",
         "team": "product", "primary_for": ["product"], "bot": None},
        {"id": "lena", "name": "Lena", "email": "lena@acme.example", "title": "Success",
         "team": "success", "primary_for": ["human-ops"], "bot": "success"},
        {"id": "priya", "name": "Priya", "email": "priya@acme.example", "title": "Sales",
         "team": "sales", "primary_for": ["sales", "lead-research"], "bot": "sales"},
        {"id": "omar", "name": "Omar", "email": "omar@acme.example", "title": "Sales",
         "team": "sales", "primary_for": [], "bot": "sales"},
    ],
}
OWNER = {"id": "ana", "email": "ana@acme.example"}
EMPLOYEES = {
    "cmo": {"name": "cmo", "reports_to": None},
    "seo": {"name": "seo", "reports_to": "cmo"},
    "listening": {"name": "listening", "reports_to": "cmo"},
    "cpo": {"name": "cpo", "reports_to": None},
    "bug-triage": {"name": "bug-triage", "reports_to": "cpo"},
    "sales": {"name": "sales", "reports_to": None},
    "lead-research": {"name": "lead-research", "reports_to": "sales"},
    "human-ops": {"name": "human-ops", "reports_to": None},
    "success": {"name": "success", "reports_to": "human-ops"},
    "coach": {"name": "coach", "reports_to": None},
    "loop-a": {"name": "loop-a", "reports_to": "loop-b"},
    "loop-b": {"name": "loop-b", "reports_to": "loop-a"},
}


class Load(unittest.TestCase):
    def test_the_roster_is_normalised(self):
        roster = P.load(DOC)
        self.assertEqual(roster["default_user"], "ana")
        self.assertEqual(roster["teams"]["marketing"], {"root": "cmo"})
        ana = P.person("ana", roster)
        self.assertEqual(ana["email"], "ana@acme.example")          # lowercased
        self.assertEqual(ana["primary_for"], ["marketing"])
        self.assertIsNone(ana["bot"])
        self.assertEqual(P.person("lena", roster)["bot"], "success")

    def test_a_person_can_be_found_by_verified_email(self):
        roster = P.load(DOC)
        self.assertEqual(P.person_by_email("BEN@ACME.EXAMPLE", roster)["id"], "ben")
        self.assertIsNone(P.person_by_email("unknown@acme.example", roster))

class Primary(unittest.TestCase):
    ROSTER = P.load(DOC)

    def test_only_an_assigned_person_may_chat(self):
        self.assertTrue(P.may_chat("ana@acme.example", "seo", self.ROSTER, EMPLOYEES))
        self.assertFalse(P.may_chat("ben@acme.example", "seo", self.ROSTER, EMPLOYEES))
        self.assertTrue(P.may_chat("ben@acme.example", "bug-triage", self.ROSTER, EMPLOYEES))
        self.assertFalse(P.may_chat("unknown@acme.example", "bug-triage", self.ROSTER, EMPLOYEES))

class OrgMail(unittest.TestCase):
    def setUp(self):
        self.roster = P.load({
            "people": [
                {"id": "ana", "email": "ana@acme.example", "inbox_bot": "inbox"},
                {"id": "priya", "email": "priya@acme.example", "reports_to": "ana"},
                {"id": "omar", "email": "omar@acme.example", "reports_to": "priya"},
                {"id": "ghost", "reports_to": "ana"},
            ]
        })

    def test_a_cycle_or_self_report_does_not_loop(self):
        roster = P.load({"people": [
            {"id": "a", "email": "a@acme.example", "reports_to": "b"},
            {"id": "b", "email": "b@acme.example", "reports_to": "a"},
        ]})
        self.assertEqual(P.mailboxes_below("a", roster), ["a@acme.example", "b@acme.example"])

if __name__ == "__main__":
    unittest.main(verbosity=2)
