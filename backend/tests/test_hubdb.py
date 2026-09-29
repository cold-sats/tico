"""hub.db's write layer: one passing and one refusing case for every rule in docs/history/hub-v2.md §4.

Every test runs against a fresh database in a temp directory with a small fake registry, so
nothing here reads `registry/` or the real `runtime/hub.db`.
"""
import json
import tempfile
import unittest
import os
from unittest import mock
from pathlib import Path

from backend import hubdb as H

EMPLOYEES = {
    "coo": {"display_name": "COO", "status": "active", "host": "keeper", "runtime": "codex",
            "model": "gpt-6-astra", "reasoning_effort": "medium", "dir": "/tmp/emp-coo"},
    "cmo": {"display_name": "CMO", "status": "active", "host": "keeper", "runtime": "codex"},
    "seo": {"display_name": "SEO", "status": "active", "runtime": "grok"},
    "analytics": {"display_name": "Analytics", "status": "active"},
    "legal": {"display_name": "Legal", "status": "active"},
    "game": {"display_name": "Project Game", "status": "planned"},
    "coach": {"display_name": "Coach", "status": "paused"},
}
PEOPLE = {"people": [
    {"id": "ana", "name": "Ana Rivera", "email": "ana@acme.example", "team": "leadership",
     "primary_for": ["marketing"]},
    {"id": "ben", "name": "Ben", "email": "ben@acme.example", "team": "product",
     "primary_for": ["product"]}]}

ANA = H.human_actor("ana")
CMO = H.bot_actor("cmo")
SEO = H.bot_actor("seo")
COO = H.bot_actor("coo")
ANALYTICS = H.bot_actor("analytics")


class HubCase(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        self.conn = H.connect(Path(self.dir.name) / "hub.db")
        self.addCleanup(self.conn.close)
        H.sync_registry(self.conn, EMPLOYEES, PEOPLE)

    def refused(self, rule, fn, *a, **kw):
        with self.assertRaises(H.Refused) as got:
            fn(*a, **kw)
        self.assertEqual(got.exception.rule, rule, got.exception.detail)
        return got.exception


# ----------------------------------------------------------------------------- schema, connect
class Schema(HubCase):
    def test_every_table_and_index_in_the_contract_exists(self):
        names = {r["name"] for r in self.conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")}
        self.assertLessEqual({"bots", "humans", "conversations", "messages", "tasks",
                              "task_events", "approvals", "bot_status", "bot_status_history",
                              "schedules", "turns", "deltas", "rate_limits", "refusals",
                              "events"}, names)
        indexes = {r["name"] for r in self.conn.execute(
            "SELECT name FROM sqlite_master WHERE type='index'")}
        self.assertLessEqual({"messages_to_delivered", "messages_conversation",
                              "tasks_owner_status", "tasks_requester_status", "events_ts"},
                             indexes)

class RegistrySync(HubCase):
    def test_sync_is_idempotent_and_keeps_tokens_threads_and_quarantine(self):
        token = H.issue_token(self.conn, "cmo")
        self.conn.execute("UPDATE bots SET thread_id='t-1' WHERE slug='cmo'")
        H.quarantine(self.conn, "seo", "test")
        H.sync_registry(self.conn, EMPLOYEES, PEOPLE)
        H.sync_registry(self.conn, EMPLOYEES, PEOPLE)
        self.assertEqual(len(H.bots(self.conn)), len(EMPLOYEES))
        self.assertEqual(len(H.humans(self.conn)), len(PEOPLE["people"]))
        self.assertEqual(H.bot(self.conn, "cmo")["thread_id"], "t-1")
        self.assertEqual(H.verify_bot(self.conn, "cmo", token)["slug"], "cmo")
        self.assertEqual(H.bot(self.conn, "seo")["state"], "quarantined")

class Tokens(HubCase):
    def test_a_wrong_or_rotated_token_is_refused(self):
        first = H.issue_token(self.conn, "cmo")
        self.refused("identity", H.verify_bot, self.conn, "cmo", "nope")
        H.issue_token(self.conn, "cmo")                     # the keeper rotates on resume
        self.refused("identity", H.verify_bot, self.conn, "cmo", first)
        self.refused("identity", H.verify_bot, self.conn, "seo", first)   # never issued one


# ----------------------------------------------------------------------------- rule 1
class Rule1Identity(HubCase):
    def test_a_bot_may_not_write_another_bots_status(self):
        self.refused("identity", H.status_set, self.conn, CMO, "seo", state="blocked")

    def test_an_actor_the_roster_does_not_know_writes_nothing(self):
        self.refused("identity", H.say, self.conn, "bot:ghost", ANA, "hello")
        self.refused("identity", H.say, self.conn, "someone@example.com", ANA, "hello")

    def test_only_the_addressee_answers_an_ask(self):
        ask = H.say(self.conn, CMO, SEO, "how many posts shipped?", kind="ask")
        self.assertEqual(H.answer(self.conn, SEO, ask["id"], "four")["to_actor"], CMO)
        self.refused("identity", H.answer, self.conn, ANALYTICS, ask["id"], "four")

# ----------------------------------------------------------------------------- rule 2
class Rule2Reach(HubCase):
    def test_planned_paused_and_off_roster_targets_are_refused(self):
        self.refused("reach", H.say, self.conn, CMO, "game", "hello")
        self.refused("reach", H.say, self.conn, CMO, "coach", "hello")
        self.refused("reach", H.say, self.conn, CMO, "press@competitor.com", "hello")


# ----------------------------------------------------------------------------- rule 3
class Rule3Caps(HubCase):
    def test_twenty_messages_an_hour_pass_and_the_twenty_first_is_capped(self):
        conv = H.open_conversation(self.conn, CMO, [CMO, SEO], subject="the blog")
        for i in range(H.CAP_PER_HOUR):
            H.say(self.conn, CMO, SEO, f"line {i}", conversation_id=conv["id"])
        self.refused("cap", H.say, self.conn, CMO, SEO, "one more", conversation_id=conv["id"])

    def test_notices_and_a_persons_messages_do_not_count_toward_the_loop_cap(self):
        # 2026-09-27: a bot's room with Ana hit the cap on routine notices and his own messages.
        conv = H.open_conversation(self.conn, CMO, [CMO, SEO, ANA], subject="the room")
        for i in range(H.CAP_PER_HOUR):
            H.say(self.conn, H.KEEPER, CMO, f"New task {i}", kind="notice", conversation_id=conv["id"])
            H.say(self.conn, ANA, CMO, f"note {i}", conversation_id=conv["id"])
        H.say(self.conn, CMO, SEO, "still room to talk", conversation_id=conv["id"])

    def test_an_ask_chain_reaches_depth_three_and_stops(self):
        first = H.say(self.conn, CMO, SEO, "what is the traffic?", kind="ask")
        self.assertEqual(first["refs"]["depth"], 1)
        second = H.say(self.conn, SEO, ANALYTICS, "what is the traffic?", kind="ask")
        self.assertEqual(second["refs"]["depth"], 2)
        third = H.say(self.conn, ANALYTICS, COO, "what is the traffic?", kind="ask")
        self.assertEqual(third["refs"]["depth"], 3)
        self.refused("depth", H.say, self.conn, COO, "legal", "and you?", kind="ask")

    def test_a_bot_cannot_reset_the_depth_it_declares(self):
        H.say(self.conn, CMO, SEO, "what is the traffic?", kind="ask")
        self.refused("depth", H.say, self.conn, SEO, ANALYTICS, "onwards", kind="ask",
                     refs={"depth": 9})


# ----------------------------------------------------------------------------- rule 4
class Rule4Unsolicited(HubCase):
    def test_three_unsolicited_notices_a_day_pass_and_the_fourth_does_not(self):
        for i in range(H.UNSOLICITED_PER_DAY):
            H.notice(self.conn, CMO, ANA, f"Read the {i} draft when you have a minute.")
        self.refused("unsolicited", H.notice, self.conn, CMO, ANA, "Read one more draft.")

    def test_unrelated_reply_reference_does_not_bypass_the_cap(self):
        outgoing = H.say(self.conn, CMO, ANA, "First update")
        for i in range(1, H.UNSOLICITED_PER_DAY):
            H.say(self.conn, CMO, ANA, f"Update {i}", conversation_id=outgoing["conversation_id"])
        other = H.say(self.conn, ANA, SEO, "Different conversation")
        self.refused("unsolicited", H.say, self.conn, CMO, ANA, "Another update",
                     conversation_id=outgoing["conversation_id"], in_reply_to=other["id"])


# ----------------------------------------------------------------------------- rule 5
class Rule5Tasks(HubCase):
    def open_task(self, requester=CMO, owner=SEO, title="Write the September brief"):
        return H.task_create(self.conn, requester, title, "One page on what we ship.", owner)

    def test_anyone_may_open_a_task_for_an_active_owner_and_it_starts_open(self):
        row = self.open_task()
        self.assertEqual((row["status"], row["owner"], row["requester"]), ("open", SEO, CMO))
        self.assertEqual(H.tasks(self.conn, owner=SEO, status="open")[0]["id"], row["id"])

    def test_the_done_list_is_most_recently_done_first_whenever_it_was_closed(self):
        # Ana, 2026-09-26: "my done list should be sorted by most recently done at top".
        early, late = self.open_task(title="Done first"), self.open_task(title="Done second")
        self.conn.execute("UPDATE tasks SET status='closed', done_at=?, closed_at=? WHERE id=?",
                          ("2026-09-20T10:00:00Z", "2026-09-26T10:00:00Z", early["id"]))
        self.conn.execute("UPDATE tasks SET status='done', done_at=?, closed_at=NULL WHERE id=?",
                          ("2026-09-25T10:00:00Z", late["id"]))
        rows = H.tasks(self.conn, status=["done", "closed"], order="finished")
        self.assertEqual([r["id"] for r in rows][:2], [late["id"], early["id"]])

    def test_a_bot_says_what_its_own_task_waits_on_but_not_on_someone_elses(self):
        # A bot told to "file the blocker first" was then refused for setting it.
        mine = H.task_create(self.conn, SEO, "Load the verified sites", "After the rollout.", SEO)
        other = H.task_create(self.conn, CMO, "Roll out the fix", "Production rollout.", CMO)
        row = H.task_update(self.conn, SEO, mine["id"], blocked_by=other["id"])
        self.assertEqual(row["blocked_by"], other["id"])
        H.task_update(self.conn, SEO, mine["id"], status="waiting", note="Waiting on the rollout.")
        self.refused("blocked_by", H.task_update, self.conn, SEO, mine["id"], blocked_by=mine["id"])
        self.refused("identity", H.task_update, self.conn, SEO, mine["id"], labels=["sites"])
        self.refused("identity", H.task_update, self.conn, SEO, other["id"], blocked_by=mine["id"])

    def test_a_task_for_a_paused_owner_is_refused(self):
        self.refused("reach", H.task_create, self.conn, CMO, "Write the brief", "body", "coach")

    def test_the_owner_moves_it_but_may_not_close_it(self):
        row = self.open_task()
        self.assertEqual(H.task_update(self.conn, SEO, row["id"], status="doing")["status"], "doing")
        self.assertEqual(H.task_update(self.conn, SEO, row["id"], status="done",
                                       note="posted")["status"], "done")
        self.refused("close", H.task_close, self.conn, SEO, row["id"])
        self.refused("close", H.task_update, self.conn, SEO, row["id"], status="closed")

    def test_the_requester_closes_it_and_the_owner_is_woken(self):
        row = self.open_task()
        H.task_update(self.conn, SEO, row["id"], status="done", note="posted")
        closed = H.task_close(self.conn, CMO, row["id"], note="reads well")
        self.assertEqual((closed["status"], closed["closed_by"]), ("closed", CMO))
        woken = [m for m in H.messages(self.conn, row["conversation_id"])
                 if m["to_actor"] == SEO and m["body"].startswith("Closed:")]
        self.assertEqual(len(woken), 1)

    def stale(self, row):
        self.conn.execute("UPDATE tasks SET updated=? WHERE id=?", (H.shift(H.now(), days=-2), row["id"]))

    def closed_notices(self, row, to):
        return [m for m in H.messages(self.conn, row["conversation_id"])
                if m["to_actor"] == to and m["body"].startswith(("Closed:", "Child closed:"))]

    def test_human_must_record_result_before_finishing_or_closing_bot_request(self):
        decision = H.task_create(self.conn, CMO, "Decide whether to release the draft", "Review it.", ANA)
        self.refused("lint", H.task_update, self.conn, ANA, decision["id"], status="done")
        self.refused("lint", H.task_close, self.conn, ANA, decision["id"])
        self.assertEqual(H.task(self.conn, decision["id"])["status"], "open")
        result = H.task_update(self.conn, ANA, decision["id"], status="done",
                               note="Keep the draft on hold; do not publish it.")
        self.assertEqual(result["status"], "done")
        told = [m for m in H.messages(self.conn, decision["conversation_id"])
                if m["to_actor"] == CMO and m["body"].startswith("Finished:")]
        self.assertEqual(len(told), 1)
        self.assertIn("Keep the draft on hold", told[0]["body"])

    def test_a_decline_returns_to_the_requester_with_the_reason(self):
        row = self.open_task()
        H.task_update(self.conn, SEO, row["id"], status="declined", note="the page is already live")
        back = [m for m in H.messages(self.conn, row["conversation_id"]) if m["to_actor"] == CMO]
        self.assertIn("the page is already live", back[-1]["body"])
        self.assertEqual(H.needs_you(self.conn, CMO)["declined"][0]["id"], row["id"])

    def test_the_owner_gets_one_question_and_no_more(self):
        row = self.open_task()
        self.assertTrue(H.task_ask(self.conn, SEO, row["id"], "which quarter?"))
        self.refused("one-question", H.task_ask, self.conn, SEO, row["id"], "and which channel?")

    def test_the_same_requester_owner_and_title_twice_is_a_duplicate(self):
        self.open_task()
        self.refused("duplicate", self.open_task)
        row = H.tasks(self.conn, requester=CMO)[0]
        H.task_close(self.conn, CMO, row["id"])
        self.assertTrue(self.open_task())               # once it is closed, asking again is fine

    def test_auto_close_takes_a_bot_requesters_done_task_after_three_days(self):
        row = self.open_task()
        H.task_update(self.conn, SEO, row["id"], status="done", note="posted")
        self.assertEqual(H.auto_close_done(self.conn, H.now()), [])
        later = H.shift(H.now(), days=H.AUTO_CLOSE_DAYS + 1)
        closed = H.auto_close_done(self.conn, later)
        self.assertEqual([c["id"] for c in closed], [row["id"]])
        self.assertEqual(H.task(self.conn, row["id"])["closed_by"], H.KEEPER)
        self.assertEqual(H.auto_close_done(self.conn, later), [])

# ----------------------------------------------------------------------------- rule 6
class Rule6Approvals(HubCase):
    SEND = {"to": "ops@acme.com", "cc": "", "subject": "Your September invoice",
            "body_sha256": "a" * 64, "mailbox": "ana@acme.example"}

    def test_an_exact_payload_is_requested_decided_and_spent_once(self):
        appr = H.approval_request(self.conn, CMO, "send", self.SEND)
        self.assertEqual(appr["payload_hash"], H.payload_hash(self.SEND))
        self.assertIsNone(appr["decision"])
        decided = H.approval_decide(self.conn, ANA, appr["id"], "approved", note="go")
        self.assertEqual((decided["decision"], decided["decided_by"]), ("approved", ANA))
        self.assertTrue(H.approval_consume(self.conn, CMO, appr["id"])["consumed_at"])
        self.refused("consumed", H.approval_consume, self.conn, CMO, appr["id"])

    def test_only_a_human_decides_and_only_once(self):
        appr = H.approval_request(self.conn, CMO, "spend",
                                  {"amount": 250, "account": "ads", "what": "one week of tests"})
        self.refused("identity", H.approval_decide, self.conn, COO, appr["id"], "approved")
        self.refused("identity", H.approval_decide, self.conn, H.KEEPER, appr["id"], "approved")
        H.approval_decide(self.conn, ANA, appr["id"], "approved")
        self.refused("duplicate", H.approval_decide, self.conn, ANA, appr["id"], "declined")

    def test_an_undecided_or_declined_approval_cannot_be_spent(self):
        appr = H.approval_request(self.conn, CMO, "merge", {"repo": "emp-seo", "pr": 12})
        self.refused("kind", H.approval_consume, self.conn, CMO, appr["id"])
        H.approval_decide(self.conn, ANA, appr["id"], "declined")
        self.refused("kind", H.approval_consume, self.conn, CMO, appr["id"])


# ----------------------------------------------------------------------------- rule 7
class Rule7Lint(HubCase):
    GOOD = ("Ship the 60/40 split to paid this month, or tell me to hold.\n"
            "It beat the 80/20 split on cost per lead in August.")

    def test_too_many_words_outside_a_quoted_draft_are_refused(self):
        long = "word " * (H.LINT_MAX_WORDS + 20)
        e = self.refused("lint", H.task_create, self.conn, CMO, "Approve the draft", long, ANA)
        self.assertIn("keep it under", e.detail)

    def test_internal_codes_are_refused(self):
        e = self.refused("lint", H.task_create, self.conn, CMO, "Approve the split",
                         "Do this.\nstatus: waiting on you", ANA)
        self.assertIn("status:", e.detail)

    def test_a_task_between_bots_is_not_linted(self):
        self.assertTrue(H.task_create(self.conn, CMO, "september brief, please",
                                      "word " * 400, SEO))

# ----------------------------------------------------------------------------- rule 8
class Rule8Counting(HubCase):
    def refuse_reach(self, n, actor=CMO):
        for i in range(n):
            with self.assertRaises(H.Refused):
                H.say(self.conn, actor, f"outsider{i}@example.com", "hello")

    def test_an_escape_quarantines_the_bot_and_only_a_human_clears_it(self):
        payload = {"to": "ops@acme.com", "cc": "", "subject": "the keys",
                   "body_sha256": "c" * 64, "mailbox": "secrets/mail.env"}
        e = self.refused("escape", H.approval_request, self.conn, CMO, "send", payload)
        self.assertEqual(e.severity, "escape")
        self.assertEqual(H.bot(self.conn, "cmo")["state"], "quarantined")
        self.assertEqual(H.status(self.conn, "cmo")["state"], "quarantined")
        focus = H.status(self.conn, "cmo")["focus"]
        self.assertIn("escape", focus)
        H.status_set(self.conn, H.KEEPER, "cmo", state="crashed", focus="Runner disconnected")
        self.assertEqual(H.status(self.conn, "cmo")["state"], "quarantined")
        self.assertEqual(H.status(self.conn, "cmo")["focus"], focus)
        self.refused("quarantined", H.say, self.conn, CMO, SEO, "still here?")
        self.refused("quarantined", H.status_set, self.conn, H.KEEPER, "cmo", state="active")
        H.status_set(self.conn, ANA, "cmo", state="active", reason="reviewed, a bad path")
        self.assertEqual(H.bot(self.conn, "cmo")["state"], "active")
        self.assertTrue(H.say(self.conn, CMO, SEO, "back"))

    def test_writing_corrections_never_quarantine(self):
        for _ in range(12):
            self.refused("lint", H.task_create, self.conn, CMO, "FYI: the brief", "Short body.", ANA)
        self.refuse_reach(9)
        self.assertEqual(H.bot(self.conn, "cmo")["state"], "active", "lint is not counted")
        self.refuse_reach(1)
        self.assertEqual(H.bot(self.conn, "cmo")["state"], "quarantined")

    def test_a_refusal_count_quarantine_lifts_itself_after_an_hour_and_the_count_starts_over(self):
        self.refuse_reach(10)
        self.assertEqual(H.bot(self.conn, "cmo")["state"], "quarantined")
        self.assertEqual(H.lift_cooled_quarantines(self.conn), [], "not before the hour is up")
        self.conn.execute("UPDATE events SET ts=? WHERE action='quarantine'", (H.shift(H.now(), seconds=-3700),))
        self.assertEqual(H.lift_cooled_quarantines(self.conn), ["cmo"])
        self.assertEqual(H.bot(self.conn, "cmo")["state"], "active")
        self.refuse_reach(1)
        self.assertEqual(H.bot(self.conn, "cmo")["state"], "active", "the count started over")

    def test_botops_refusals_go_to_a_person_when_the_company_has_no_assistant(self):
        self.conn.execute("INSERT INTO bots(slug,display_name,state) VALUES('botops','BotOps','active')")
        self.conn.execute("UPDATE bots SET state='archived' WHERE slug='coo'")
        self.refuse_reach(3, actor=H.bot_actor("botops"))
        review = self.conn.execute("SELECT owner FROM tasks WHERE title=?",
                                   ("Review botops's refused writes",)).fetchone()
        self.assertEqual(review["owner"], H.human_actor(H.default_human(self.conn)))

    def test_botops_refusals_go_to_the_assistant_when_there_is_one(self):
        self.conn.execute("INSERT INTO bots(slug,display_name,state) VALUES('botops','BotOps','active')")
        self.refuse_reach(3, actor=H.bot_actor("botops"))
        review = self.conn.execute("SELECT owner FROM tasks WHERE title=?",
                                   ("Review botops's refused writes",)).fetchone()
        self.assertEqual(review["owner"], COO)

    def test_botops_lifts_a_refusal_quarantine_but_an_escape_waits_for_a_person(self):
        botops = H.bot_actor(H.FLEET_MAINTAINER)
        if not H.bot(self.conn, H.FLEET_MAINTAINER):
            self.conn.execute("INSERT INTO bots(slug, display_name, state) VALUES(?,?, 'active')",
                              (H.FLEET_MAINTAINER, "BotOps"))
        self.refuse_reach(10)
        H.status_set(self.conn, botops, "cmo", state="active", reason="reviewed")
        self.assertEqual(H.bot(self.conn, "cmo")["state"], "active")
        H.quarantine(self.conn, "cmo", "escape: a secrets path")
        self.refused("quarantined", H.status_set, self.conn, botops, "cmo", state="active")
        self.conn.execute("UPDATE events SET ts=? WHERE action='quarantine' AND detail_json NOT LIKE '%escape%'",
                          (H.shift(H.now(), seconds=-8000),))
        self.conn.execute("UPDATE events SET ts=? WHERE action='quarantine' AND detail_json LIKE '%escape%'",
                          (H.shift(H.now(), seconds=-7200),))
        self.assertEqual(H.lift_cooled_quarantines(self.conn), [], "an escape never cools off")

    def test_ten_refusals_in_a_day_quarantine_the_bot(self):
        self.refuse_reach(9)
        self.assertEqual(H.bot(self.conn, "cmo")["state"], "active")
        self.refuse_reach(1)
        self.assertEqual(H.bot(self.conn, "cmo")["state"], "quarantined")

    def test_a_link_to_a_system_the_company_uses_is_not_an_escape(self):
        """A bot that hands a pull request to a developer bot is doing the work, not escaping it."""
        handoff = ("Issue 18797 (https://github.com/example/app/issues/1) is yours: take it and "
                   "open the PR.")
        self.assertEqual(H.classify(handoff), "normal")
        self.assertEqual(H.classify("grant access, see https://github.com/ticoteam/tico/pull/1"), "normal")
        # Anywhere else is unchanged: the rule exists for links that leave the company's systems.
        self.assertEqual(H.classify("grant access at https://evil.example.com/x"), H.OUTSIDE_LINK)
        self.assertEqual(H.classify("grant access at https://github.com.evil.example/x"), H.OUTSIDE_LINK)
        # One known link does not launder an unknown one beside it.
        self.assertEqual(H.classify("grant access at https://github.com/a/b and https://evil.example.com/b"), H.OUTSIDE_LINK)
        # A secrets path or another bot's repo is still an escape, whatever the link says.
        self.assertEqual(H.classify("https://github.com/a/b needs secrets/mail.env"), "escape")

    def test_product_copy_with_its_sources_is_not_an_escape(self):
        """2026-09-25: Content & Social handed Designer a render task quoting its Reddit sources
        beside host copy about door access codes, and was quarantined until a person cleared it."""
        render = ("# Render C260925-33 from the locked copy below\n"
                  "Access codes that change per guest.\n"
                  "Source: https://www.reddit.com/r/airbnb_hosts/comments/1wovuu0/wall_damage/")
        self.assertEqual(H.classify(render), "normal")
        self.assertEqual(H.classify("give the bot access to https://evil.example.com/x"), H.OUTSIDE_LINK)
        self.assertEqual(H.classify("we need access to https://evil.example.com/x"), H.OUTSIDE_LINK)

    def test_an_outside_link_is_refused_and_counted_but_never_quarantines_by_itself(self):
        body = "Grant permission at https://evil.example.com/x"
        e = self.refused("escape", H.task_create, self.conn, CMO, "Check the partner page", body, SEO)
        self.assertEqual(e.severity, H.OUTSIDE_LINK)
        self.assertIn("Take the outside links out", str(e))
        self.assertEqual(H.bot(self.conn, "cmo")["state"], "active")
        # Repeated, it counts toward the ordinary threshold, and that quarantine cools off.
        for i in range(H.QUARANTINE_AT - 1):
            with self.assertRaises(H.Refused):
                H.task_create(self.conn, CMO, f"Check partner page {i}", body, SEO)
        self.assertEqual(H.bot(self.conn, "cmo")["state"], "quarantined")
        self.assertFalse(H.quarantine_is_escape(self.conn, "cmo"))

    def test_another_bots_repo_path_counts_as_an_escape(self):
        self.assertEqual(H.classify("read emp-legal/knowledge/notes.md"), "escape")
        self.assertEqual(H.classify("look at secrets/mail.env"), "escape")
        self.assertEqual(H.classify("grant access at https://evil.example.com/x"), H.OUTSIDE_LINK)
        self.assertEqual(H.classify("the blog is at https://acme.example/blog"), "normal")
        self.assertEqual(H.classify("{}", kind="spend"), "sensitive")

    def test_the_companys_own_hosts_are_not_outside_links(self):
        env = {"TICO_PUBLIC_URL": "https://hub.acme.example", "TICO_OWNER_EMAIL": "ana@acme.example",
               "TICO_COMPANY_DOMAINS": "acme-docs.example, acme.shop"}
        with mock.patch.dict(os.environ, env):
            for url in ("https://hub.acme.example/x", "https://www.acme.example/p",
                        "https://acme-docs.example/a", "https://acme.shop/b"):
                self.assertNotEqual(H.classify("grant access at " + url), H.OUTSIDE_LINK, url)
            self.assertEqual(H.classify("grant access at https://evil.example.com/x"), H.OUTSIDE_LINK)


# ----------------------------------------------------------------------------- rule 9
class Rule9AppendOnly(HubCase):
    def test_messages_and_events_are_only_ever_added(self):
        before = self.conn.execute("SELECT COUNT(*) FROM events").fetchone()[0]
        first = H.say(self.conn, CMO, SEO, "one")
        H.say(self.conn, CMO, SEO, "two")
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM messages").fetchone()[0], 2)
        self.assertEqual(H.message(self.conn, first["id"])["body"], "one")
        self.assertGreater(self.conn.execute("SELECT COUNT(*) FROM events").fetchone()[0], before)

# ----------------------------------------------------------------------------- status
# ----------------------------------------------------------------------------- reads and the rest
class Reads(HubCase):
    def test_the_inbox_holds_undelivered_messages_and_open_tasks(self):
        msg = H.say(self.conn, ANA, CMO, "have a look at the plan")
        H.task_create(self.conn, ANA, "Write the brief", "One page.", CMO)
        box = H.inbox(self.conn, CMO)
        self.assertEqual([m["id"] for m in box["messages"]][0], msg["id"])
        self.assertEqual([t["title"] for t in box["tasks"]], ["Write the brief"])
        H.mark_delivered(self.conn, H.KEEPER, msg["id"])
        H.mark_read(self.conn, CMO, msg["id"])
        self.assertNotIn(msg["id"], [m["id"] for m in H.inbox(self.conn, CMO)["messages"]])

    def test_needs_you_holds_my_tasks_pending_approvals_and_declines(self):
        H.task_create(self.conn, CMO, "Approve the September split",
                      "Say yes or change it. It beat the old split on cost per lead.", ANA)
        H.approval_request(self.conn, CMO, "spend",
                           {"amount": 250, "account": "ads", "what": "one week of tests"})
        mine = H.needs_you(self.conn, "ana")
        self.assertEqual([t["title"] for t in mine["tasks"]], ["Approve the September split"])
        self.assertEqual(len(mine["approvals"]), 1)

class APersonsReplyAnswersWhatWasAsked(HubCase):
    """Answering one question at a time cost a run per question and left nowhere to say
    anything else. Writing back to the bot is the answer now, however many were open.
    (Ben, 2026-09-21.)"""

    def test_writing_back_closes_every_question_that_bot_had_open(self):
        a = H.say(self.conn, CMO, ANA, "ship now or wait for the split?", kind="ask")
        b = H.say(self.conn, CMO, ANA, "is 7% the right warning level?", kind="ask")
        reply = H.say(self.conn, ANA, CMO, "ship now, and 7% is right. also re-check Aug 13.")
        got = H.answers_to(self.conn, [a["id"], b["id"]])
        self.assertEqual(set(got), {a["id"], b["id"]}, "both close on the one reply")
        self.assertEqual(got[a["id"]]["id"], reply["id"])
        self.assertIn("re-check Aug 13", got[b["id"]]["body"], "the whole reply is the answer")

if __name__ == "__main__":
    unittest.main()


class ChatsWith(HubCase):
    def test_a_quiet_chat_is_found_however_many_newer_conversations_there_are(self):
        """2026-09-25: the bot page found its chat among the newest conversations only, so a quiet
        bot's history showed as "Nothing yet"."""
        me = H.human_actor("ana")
        self.conn.execute("INSERT INTO conversations (id, kind, subject, task_id, participants_json, created, "
                          "last_message_at, closed_at) VALUES ('old-chat', 'chat', '', NULL, ?, '2026-01-01T00:00:00Z', "
                          "'2026-01-01T00:00:00Z', NULL)", (H._dump([me, CMO]),))
        for n in range(600):
            self.conn.execute("INSERT INTO conversations (id, kind, subject, task_id, participants_json, created, "
                              "last_message_at, closed_at) VALUES (?, 'task', '', NULL, ?, '2026-09-01T00:00:00Z', "
                              "'2026-09-01T00:00:00Z', NULL)", (f"c{n}", H._dump([me, SEO])))
        self.assertNotIn("old-chat", [c["id"] for c in H.conversations_for(self.conn, me)])
        self.assertEqual([c["id"] for c in H.chats_with(self.conn, me, CMO)], ["old-chat"])
        self.assertEqual(H.chats_with(self.conn, me, SEO), [], "task threads are not chats")
        self.assertEqual(H.chats_with(self.conn, H.human_actor("ben"), CMO), [], "only my own chats")
