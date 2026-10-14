"""Approvals and asks nobody will act on leave Needs you: the task ended, a newer request replaced them, or they aged."""
from backend import approval_expiry
from backend import hubdb as H
from backend.tests.test_hubdb import ANA, CMO, HubCase

MERGE = {"repo": "acme/site", "pr": 12}


class Withdrawn(HubCase):
    def pending(self):
        return [a["id"] for a in H.approvals(self.conn, pending=True)]

    def test_closing_or_finishing_a_task_withdraws_its_approvals_and_tells_the_bot_quietly(self):
        row = H.task_create(self.conn, ANA, "Ship the site fix", "Merge it.", CMO, lint=False)
        appr = H.approval_request(self.conn, CMO, "merge", MERGE, task_id=row["id"])
        H.task_update(self.conn, CMO, row["id"], status="done", note="shipped")
        after = H.approval(self.conn, appr["id"])
        self.assertEqual((after["decision"], after["decided_by"]), ("withdrawn", H.KEEPER))
        self.assertEqual(self.pending(), [])
        told = self.conn.execute("SELECT body, refs_json FROM messages WHERE to_actor=? AND body LIKE 'Withdrawn:%'",
                                 (CMO,)).fetchall()
        self.assertEqual(len(told), 1)
        self.assertIn('"quiet": true', told[0]["refs_json"])
        self.refused("duplicate", H.approval_decide, self.conn, ANA, appr["id"], "approved")

    def test_a_newer_request_for_the_same_target_or_one_naming_it_replaces_the_older(self):
        row = H.task_create(self.conn, ANA, "Release", "Cut it.", CMO, lint=False)
        post = {"url": "https://acme.example/notes", "content_sha256": "a" * 64}
        first = H.approval_request(self.conn, CMO, "publish", post, task_id=row["id"])
        recut = H.approval_request(self.conn, CMO, "publish", {**post, "content_sha256": "b" * 64}, task_id=row["id"])
        other = H.approval_request(self.conn, CMO, "publish", {"url": "https://acme.example/blog",
                                                               "content_sha256": "c" * 64}, task_id=row["id"])
        loose = H.approval_request(self.conn, CMO, "spend", {"amount": 5, "account": "ads", "what": "a test"})
        named = H.approval_request(self.conn, CMO, "spend", {"amount": 6, "account": "ads", "what": "a test"},
                                   supersedes=loose["id"])
        self.assertEqual(H.approval(self.conn, first["id"])["decision"], "withdrawn")
        self.assertEqual(H.approval(self.conn, loose["id"])["decision"], "withdrawn")
        self.assertEqual(sorted(self.pending()), sorted([recut["id"], other["id"], named["id"]]))

    def test_an_approval_undecided_for_fourteen_days_is_withdrawn_and_may_be_asked_again(self):
        appr = H.approval_request(self.conn, CMO, "merge", MERGE)
        later = H.shift(appr["created"], days=H.APPROVAL_STALE_DAYS, minutes=1)
        self.assertEqual(approval_expiry.sweep(self.conn, H.shift(appr["created"], days=13))["stale"], [])
        self.assertEqual(approval_expiry.sweep(self.conn, later)["stale"], [appr["id"]])
        self.assertEqual(H.approval_request(self.conn, CMO, "merge", MERGE)["decision"], None)

    def test_an_ask_left_open_on_a_task_that_already_ended_leaves_needs_you(self):
        row = H.task_create(self.conn, ANA, "Pick a launch date", "Which week?", CMO, lint=False)
        ask = H.task_ask(self.conn, CMO, row["id"], "Which week works, the 3rd or the 10th?")
        # A task that ended before asks were superseded on its end: only the sweep catches its open ask.
        self.conn.execute("UPDATE tasks SET status='closed' WHERE id=?", (row["id"],))
        self.assertEqual(approval_expiry.sweep(self.conn)["asks"], [ask["id"]])
        self.assertTrue(H.message(self.conn, ask["id"])["superseded_at"])
