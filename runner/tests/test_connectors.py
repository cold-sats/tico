"""Mail push from the connector worker: fake CLI and fake cloud, no Google and no hub token."""

import unittest

from runner.connectors import ConnectorPublisher
from runner.outage import Outage


def exported(**overrides):
    row = {"id": "m-plain", "msg_id": "m-plain", "mailbox": "ana@acme.example",
           "thread_id": "t-plain", "epoch": 1_783_368_400, "date": "2026-09-02T09:30:00-07:00",
           "from_addr": "person@customer.example",
           "from_header": "Real Person <person@customer.example>",
           "to": ["ana@acme.example"], "cc": [], "subject": "Pricing question",
           "snippet": "How does", "labels": ["INBOX", "UNREAD"], "body": "How does pricing work?",
           "body_truncated": False, "attachments": [], "list_id": "",
           "is_internal": False, "has_unsubscribe": False, "deleted_at": None}
    row.update(overrides)
    return row


class FakeClient:
    def __init__(self, mailboxes):
        self.mailboxes, self.published = mailboxes, []

    def get(self, path):
        assert path == "connectors/mail/targets"
        return {"mailboxes": self.mailboxes, "batch": 100, "retention_days": 180}

    def post(self, path, body):
        assert path == "connectors/mail/messages"
        self.published.append(body)
        return {"accepted": len(body.get("messages") or []) + len(body.get("deleted") or [])}


class FakeMail:
    def __init__(self, inbox):
        self.inbox, self.calls = {key: list(rows) for key, rows in inbox.items()}, []

    def __call__(self, args):
        self.calls.append(list(args))
        mailbox = args[args.index("--mailbox") + 1] if "--mailbox" in args else ""
        if args[:2] == ["sync", "export"]:
            rows = list(self.inbox.get(mailbox) or [])
            return {"ok": True, "count": len(rows), "messages": rows}
        if args[:2] == ["sync", "ack"]:
            ids, rest = [], args[2:]
            while rest and not rest[0].startswith("--"):
                ids.append(rest.pop(0))
            kept = [row for row in self.inbox.get(mailbox) or []
                    if (row.get("msg_id") or row.get("id")) not in ids]
            self.inbox[mailbox] = kept
            return {"ok": True, "acked": len(ids)}
        return {"ok": True, "mailbox": mailbox, "mode": "history", "fetched": 1, "history_id": "hist-1"}


def publisher(mailboxes, inbox, **config):
    return ConnectorPublisher({"url": "http://localhost:8765", "token": "test",
                               "projects_dir": "/tmp", "mail_sync_seconds": 0, **config},
                              client=FakeClient(mailboxes), mail=FakeMail(inbox))


class MailTick(unittest.TestCase):
    def test_failed_mailbox_stays_local_and_does_not_stop_the_tick(self):
        worker = publisher([{"address": "ben@acme.example", "message_count": 1}],
                           {"ben@acme.example": [exported()]})

        def boom(args):
            raise RuntimeError("provider detail must remain local")

        worker.run_mail = boom
        lines = []
        worker.mailboxes["ben@acme.example"] = Outage(
            "Tico connectors", "mail sync failed for ben@acme.example",
            "still failing", "working again", out=lines.append)
        assert worker.mail_tick() == 0
        assert worker.client.published == []
        assert lines == ["Tico connectors: mail sync failed for ben@acme.example (RuntimeError); retrying"]


if __name__ == "__main__":
    unittest.main()
