"""Every lint rule, twice: a body that trips it and a body that does not.

Pure - no CLI, no Gmail, no policy file. `ids()` collects the rule ids a body produces, so a
rule that stops firing fails a test rather than quietly letting a bad draft through.
"""

import sys, unittest
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import fake                                                          # noqa: E402,F401

from connectors.mail import lint as ln, zone                         # noqa: E402

TZ = zone("America/Los_Angeles")
NOW = datetime(2026, 9, 2, 10, 0, tzinfo=TZ)                # Wednesday 2026-09-02, 10:00 PT
CTA = ("https://acme.example/rentals?utm_source=influencer&utm_medium=email"
       "&utm_campaign=ava-reyes")
ALLOWANCE = {"urls": {"required_pattern":
                      r"^https://acme\.example/rentals\?utm_source=influencer"
                      r"&utm_medium=email&utm_campaign=[a-z0-9][a-z0-9-]*$",
                      "forbidden": ["calendly.com", "acme.example/demo", "go.acme.example"]}}

CLEAN = """Hi Ava,

I'm Ana, the founder of Acme. We're the AI property manager: pricing, guest messaging and
turnovers for 3.9% instead of the 30% a manager charges.

I'd like to work with you. What is your rate for posts/collaborations?

Ana
Founder, Acme
"""


def lint(body, **kw):
    kw.setdefault("subject", "Ava, 6 months of Acme on us")
    kw.setdefault("now", NOW)
    kw.setdefault("signature_names", ["ana"])
    return ln.run(body, **kw)


def ids(res):
    return [x["id"] for x in res["findings"]]


class Clean(unittest.TestCase):
    def test_the_shipped_outreach_shape_passes(self):
        res = lint(CLEAN + f"\nHere's the product: {CTA}\n\nAna\n",
                   to=["ava@creator.example"], slug="influencer", allowance=ALLOWANCE)
        self.assertTrue(res.ok, ids(res))
        self.assertEqual(res["findings"], [])

class House(unittest.TestCase):
    """What used to be one company's wording is policy: phrases, hosts and signature names."""

    def test_L001_phrases_come_from_the_policy(self):
        self.assertNotIn("L001", ids(lint(CLEAN + "\nOur crew is great.\n\nAna\n")))
        res = lint(CLEAN + "\nOur crew is great.\n\nAna\n", forbidden_phrases=["our crew"])
        self.assertIn("L001", ids(res))

    def test_L010_hosts_are_the_internal_domains(self):
        body = CLEAN + "\nSee https://www.corp.example/x\n\nAna\n"
        self.assertIn("L010", ids(lint(body)))
        self.assertNotIn("L010", ids(lint(body, internal_domains=("corp.example",))))

    def test_L055_the_signature_names_come_from_the_policy(self):
        body = CLEAN.replace("Ana\nFounder, Acme", "Ben\nFounder, Acme")
        self.assertIn("L055", ids(lint(body)))
        self.assertNotIn("L055", ids(lint(body, signature_names=["ben"])))
        self.assertNotIn("L055", ids(lint(body, signature_names=[])))     # none configured: not checked


class Content(unittest.TestCase):
    def test_L030_secret_shapes(self):
        for bad in ("xoxb-123", "AKIAIOSFODNN7", "sk-abc123", "ghp_abc", "-----BEGIN KEY"):
            self.assertIn("L030", ids(lint(CLEAN + f"\n{bad}\n\nAna\n")), bad)
        self.assertNotIn("L030", ids(lint(CLEAN)))

    def test_L040_internal_leakage(self):
        for bad in ("s3://acme-tico-hub/x", "runtime/mail/mail.db", "emp-influencer",
                    "see AGENT.md"):
            self.assertIn("L040", ids(lint(CLEAN + f"\n{bad}\n\nAna\n")), bad)
        self.assertNotIn("L040", ids(lint(CLEAN)))

if __name__ == "__main__":
    unittest.main()
