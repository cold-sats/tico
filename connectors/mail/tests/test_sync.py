"""Local mail persist: messages / sync_state helpers, Gmail history, and `mail sync`."""

import contextlib, io, json, os, sys, tempfile, unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import fake                    # noqa: E402,F401

from connectors.mail import Failure, db, gmail as gm                 # noqa: E402
from connectors.mail import access, audit as audit_log              # noqa: E402
from connectors.mail import __main__ as cli                          # noqa: E402


HEADERS = {"From": "Acme Growth <hello@acme.io>", "To": "ana@acme.example",
           "Subject": "Grow your rentals", "Date": "Tue, 02 Sep 2026 09:00:00 -0700",
           "List-Unsubscribe": "<https://acme.io/u/1>"}
PLAIN = {"From": "Real Person <person@customer.example>", "To": "ana@acme.example",
         "Subject": "Pricing question", "Date": "Tue, 02 Sep 2026 09:30:00 -0700"}

OLD, MID, NEW = 1788278400000, 1788364800000, 1788368400000


def corpus():
    return [
        fake.message("m-mkt", "t-mkt", HEADERS, body="Read the guide.", epoch_ms=MID),
        fake.message("m-plain", "t-plain", PLAIN, body="How does pricing work?", epoch_ms=NEW),
    ]


def norm(mid="m-plain", **extra):
    base = {"id": mid, "thread_id": "t-" + mid, "epoch": 100, "date": "2026-09-02T09:30:00-07:00",
            "from": "person@customer.example", "from_header": "Real Person <person@customer.example>",
            "to": ["ana@acme.example"], "cc": [], "subject": "Pricing question",
            "snippet": "How does", "labels": ["INBOX", "UNREAD"], "body": "How does pricing work?",
            "body_truncated": False, "attachments": [], "list_id": "", "is_internal": False,
            "unsubscribe": False}
    base.update(extra)
    return base


class MessageStore(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.conn = db.connect(Path(self.tmp.name) / "mail.db")

    def tearDown(self):
        self.tmp.cleanup()

    def test_upsert_inserts_then_is_idempotent(self):
        self.assertTrue(db.upsert_message(self.conn, "ana@acme.example", norm()))
        self.assertFalse(db.upsert_message(self.conn, "ana@acme.example", norm()))
        row = db.get_message(self.conn, "ana@acme.example", "m-plain")
        self.assertEqual(row["from_addr"], "person@customer.example")
        self.assertEqual(row["to"], ["ana@acme.example"])
        self.assertFalse(row["has_unsubscribe"])
        self.assertIsNone(row["pushed_at"])
        self.assertEqual(db.message_count(self.conn, "ana@acme.example"), 1)

if __name__ == "__main__":
    unittest.main()
