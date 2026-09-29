"""The org chart is edited in place: a person or a bot moves under another person or bot, and
the one rule is that you may edit yourself and whatever reports up to you (backend/people.py
`manages`, Ana 2026-09-18)."""
import json

from backend.store import encode
from backend.tests.test_api import api, get, post  # noqa: F401


def roster(api, people):
    with api.app.state.store.transaction() as c:
        c.execute("UPDATE registry_metadata SET value_json=? WHERE key='people'", (encode({"people": people}),))


def revision(api, bot):
    with api.app.state.store.read() as c:
        return c.execute("SELECT revision FROM bot_config WHERE bot=?", (bot,)).fetchone()[0]


def tree(api, token="ana-test"):
    view = get(api, "org", token=token)
    people = {p["id"]: p["org_parent"] for p in view["people"]}
    bots = {b["id"]: b["org_parent"] for b in view["bots"]}
    return people, bots


def test_people_and_bots_move_under_people_and_bots_and_only_managers_move_them(api):
    roster(api, [{"id": "ana", "email": "ana@acme.example", "name": "Ana", "primary_for": ["*"]},
                 {"id": "ben", "email": "ben@acme.example", "name": "Ben", "reports_to": "ana", "primary_for": ["cpo", "product-design"]},
                 {"id": "cara", "email": "cara@acme.example", "name": "Cara", "reports_to": "ana"}])
    # Ben moves Cara under himself: Cara reports to Ana, so Ben may not.
    post(api, "people/cara", {"reports_to": "ben"}, token="ben-test", expected=403)
    post(api, "people/cara", {"reports_to": "ben"})                     # the owner may
    people, _ = tree(api)
    assert people["cara"] == "p:ben"
    # Now Cara is Ben's: Ben may edit his profile, and put a bot under him.
    post(api, "people/cara", {"goals": "Ship the mobile app"}, token="ben-test")
    post(api, "bots/cpo/definition", {"reports_to": "human:cara", "expected_revision": revision(api, "cpo")}, token="ben-test")
    _, bots = tree(api)
    assert bots["cpo"] == "p:cara"
    # A bot under a person is that person's to talk to; Cara may not touch Ben.
    post(api, "chat/cpo", {"text": "Hello"}, token="cara-test")
    post(api, "people/ben", {"goals": "Mine now"}, token="cara-test", expected=403)
    post(api, "people/cara", {"goals": "My own goals"}, token="cara-test")     # yourself, always
    # Nobody moves under their own report, and nobody reports to themselves.
    post(api, "people/ben", {"reports_to": "cara"}, expected=422)
    post(api, "people/ben", {"reports_to": "ben"}, expected=422)
    post(api, "people/ben", {"reports_to": "nobody"}, expected=404)
    # A bot moves back under a bot; a circle is refused as before.
    post(api, "bots/cpo/definition", {"reports_to": "coo", "expected_revision": revision(api, "cpo")})
    _, bots = tree(api)
    assert bots["cpo"] == "b:coo"
    post(api, "bots/coo/definition", {"reports_to": "cpo", "expected_revision": revision(api, "coo")}, expected=422)


def test_removing_a_bot_takes_it_off_the_chart_and_hands_on_its_work(api):
    # #535: remove = archive. cpo roots a team; product-design reports to it and succeeds it.
    with api.app.state.store.transaction() as c:
        c.execute("UPDATE registry_metadata SET value_json=? WHERE key='people'", (encode({
            "people": [{"id": "ana", "email": "ana@acme.example", "primary_for": ["*"], "bot": "cpo"}],
            "teams": {"engineering": {"root": "cpo"}}}),))
    post(api, "bots/product-design/definition", {"reports_to": "cpo", "expected_revision": revision(api, "product-design")})
    post(api, "bots/ops/definition", {"reports_to": "cpo", "expected_revision": revision(api, "ops")})
    task = post(api, "tasks", {"owner": "cpo", "title": "Watch deploys", "body": "Daily."})
    post(api, "bots/cpo/routines", {"key": "watch", "title": "Watch", "cron": "0 7 * * *", "text": "Watch."})
    post(api, "bots/coo/archive", {"expected_revision": revision(api, "coo")}, expected=409)      # the assistant stays
    post(api, "bots/cpo/archive", {"successor": "product-design", "expected_revision": revision(api, "cpo")},
         token="cara-test", expected=403)
    post(api, "bots/cpo/archive", {"successor": "product-design", "expected_revision": revision(api, "cpo")})
    _, bots = tree(api)
    assert "cpo" not in bots
    assert bots["ops"] == "b:product-design"                                  # its reports move to the heir
    with api.app.state.store.read() as c:
        assert c.execute("SELECT state FROM bots WHERE slug='cpo'").fetchone()[0] == "archived"
        assert c.execute("SELECT reports_to,team FROM bot_config WHERE bot='product-design'").fetchone()[:] == (None, "engineering")
        assert c.execute("SELECT owner FROM tasks WHERE id=?", (task["id"],)).fetchone()[0] == "bot:product-design"
        assert c.execute("SELECT COUNT(*) FROM schedules WHERE bot='cpo' AND deleted_at IS NULL").fetchone()[0] == 0
        roster = json.loads(c.execute("SELECT value_json FROM registry_metadata WHERE key='people'").fetchone()[0])
        assert roster["people"][0]["bot"] is None                            # notes fall back to the COO


def test_botops_applies_a_persons_bot_change_as_that_person(api):
    # Ana, 2026-09-25: "i told you to set scribe's reports to to ben and move it there".
    from backend.store import H
    from backend.tests.test_api import setup_attempt
    roster(api, [{"id": "ana", "email": "ana@acme.example", "name": "Ana", "primary_for": ["*"]},
                 {"id": "ben", "email": "ben@acme.example", "name": "Ben", "reports_to": "ana"},
                 {"id": "cara", "email": "cara@acme.example", "name": "Cara", "reports_to": "ana"}])
    with api.app.state.store.transaction() as c:
        c.execute("INSERT INTO bots(slug,display_name,state) VALUES('botops','BotOps','active')")
        c.execute("INSERT INTO bot_config(bot,config_json,operator) VALUES('botops',?, 'ana')",
                  (encode({"name": "botops", "runtime": "fake", "status": "active"}),))
    _, _, botops = setup_attempt(api, "botops")
    _, _, ops = setup_attempt(api, "ops")
    ask = post(api, "chat/botops", {"text": "Move ops under Ben"})
    mid = ask.get("message", ask)["id"]
    body = lambda bot, **kw: {"reports_to": "human:ben", "expected_revision": revision(api, bot), **kw}
    # Without the person's message BotOps is refused, as before; another bot may not cite one.
    post(api, "bots/ops/definition", body("ops"), token=botops["token"], expected=403)
    post(api, "bots/ops/definition", body("ops", on_behalf_of=mid), token=ops["token"], expected=403)
    post(api, "bots/ops/definition", body("ops", on_behalf_of=mid), token=botops["token"])
    _, bots = tree(api)
    assert bots["ops"] == "p:ben"
    with api.app.state.store.read() as c:
        event = c.execute("SELECT actor,detail_json FROM events WHERE action='bot.definition_delegated'").fetchone()
        assert event["actor"] == "bot:botops" and json.loads(event["detail_json"])["on_behalf_of"] == "human:ana"
    # The person's own limits hold: Cara may not move a bot he does not manage.
    theirs = post(api, "chat/botops", {"text": "Move ops under me"})     # rewritten as Cara's below
    theirs = theirs.get("message", theirs)["id"]
    with api.app.state.store.transaction() as c:
        c.execute("UPDATE messages SET from_actor='human:cara' WHERE id=?", (theirs,))
    post(api, "bots/ops/definition", body("ops", reports_to="human:cara", on_behalf_of=theirs),
         token=botops["token"], expected=403)
    # A message to another bot, or one older than a week, is not a request to BotOps.
    other = post(api, "chat/cpo", {"text": "Move ops under Cara"})
    post(api, "bots/ops/definition", body("ops", on_behalf_of=other.get("message", other)["id"]), token=botops["token"], expected=403)
    with api.app.state.store.transaction() as c:
        c.execute("UPDATE messages SET created=? WHERE id=?", (H.shift(H.now(), days=-8), mid))
    post(api, "bots/ops/definition", body("ops", reports_to="coo", on_behalf_of=mid), token=botops["token"], expected=403)


def test_a_temp_bot_is_a_flag_not_a_word_in_its_name(api):
    # Ana, 2026-09-25: "Project X" bots become "X" with a structured temp flag, no end date.
    post(api, "bots/ops/definition", {"display_name": "Market Atlas", "temp": True, "expected_revision": revision(api, "ops")})
    row = next(b for b in get(api, "bots") if b["slug"] == "ops")
    assert row["temp"] is True and row["display_name"] == "Market Atlas"
    employee = next(e for e in api.get("/api/employees", headers={"Authorization": "Bearer ana-test"}).json() if e["name"] == "ops")
    assert employee["temp"] is True
    post(api, "bots/ops/definition", {"temp": False, "expected_revision": revision(api, "ops")})
    assert next(e for e in api.get("/api/employees", headers={"Authorization": "Bearer ana-test"}).json() if e["name"] == "ops")["temp"] is False


def test_botops_changes_a_bots_model_for_the_person_who_asked(api):
    # Ana, 2026-09-25: "get it live on opus 5.5 medium" — a model/effort change is a transition.
    with api.app.state.store.transaction() as c:
        c.execute("INSERT INTO bots(slug,display_name,state) VALUES('botops','BotOps','active')")
        c.execute("INSERT INTO bot_config(bot,config_json,operator) VALUES('botops',?, 'ana')",
                  (encode({"name": "botops", "runtime": "fake", "status": "active"}),))
    from backend.tests.test_api import setup_attempt
    _, _, botops = setup_attempt(api, "botops")
    ask = post(api, "chat/botops", {"text": "Put ops on Opus 5.5, medium"})
    body = {"kind": "model", "model": "claude-opus-5-5", "effort": "medium", "expected_revision": revision(api, "ops")}
    post(api, "bots/ops/transitions", body, token=botops["token"], expected=403)
    done = post(api, "bots/ops/transitions", {**body, "on_behalf_of": ask.get("message", ask)["id"]}, token=botops["token"])
    assert done
    with api.app.state.store.read() as c:
        event = c.execute("SELECT detail_json FROM events WHERE action='bot.transition_delegated'").fetchone()
        assert json.loads(event["detail_json"])["on_behalf_of"] == "human:ana"


def test_botops_archives_a_bot_for_the_person_who_asked(api):
    # Ana, 2026-09-25: "yes go ahead" — fold AI SDR and Sales Enablement into Sales Operations.
    with api.app.state.store.transaction() as c:
        c.execute("INSERT INTO bots(slug,display_name,state) VALUES('botops','BotOps','active')")
        c.execute("INSERT INTO bot_config(bot,config_json,operator) VALUES('botops',?, 'ana')",
                  (encode({"name": "botops", "runtime": "fake", "status": "active"}),))
    from backend.tests.test_api import setup_attempt
    _, _, botops = setup_attempt(api, "botops")
    task = post(api, "tasks", {"owner": "finance", "title": "Warmup check", "body": "Weekly."})
    ask = post(api, "chat/botops", {"text": "Fold finance into ops"})
    body = {"successor": "ops", "expected_revision": revision(api, "finance")}
    post(api, "bots/finance/archive", body, token=botops["token"], expected=403)
    post(api, "bots/finance/archive", {**body, "on_behalf_of": ask.get("message", ask)["id"]}, token=botops["token"])
    with api.app.state.store.read() as c:
        assert c.execute("SELECT state FROM bots WHERE slug='finance'").fetchone()[0] == "archived"
        assert c.execute("SELECT owner FROM tasks WHERE id=?", (task["id"],)).fetchone()[0] == "bot:ops"
        event = c.execute("SELECT detail_json FROM events WHERE action='bot.archive_delegated'").fetchone()
        assert json.loads(event["detail_json"])["on_behalf_of"] == "human:ana"


def test_a_persons_title_and_description_are_editable(api):
    """Ana, 2026-09-25: the line under a person's name and their description could not be edited."""
    row = post(api, "people/cara", {"title": "Frontend engineer",
                                       "about": "Frontend across the web app, mobile app and admin dashboard."})
    assert row["title"] == "Frontend engineer" and row["about"].startswith("Frontend across")
    with api.app.state.store.read() as c:
        stored = json.loads(c.execute("SELECT value_json FROM registry_metadata WHERE key='people'").fetchone()[0])
    person = next(p for p in stored["people"] if p["id"] == "cara")
    assert person["title"] == "Frontend engineer" and person["about"].endswith("admin dashboard.")
    post(api, "people/ben", {"about": "Not mine to change"}, token="cara-test", expected=403)


def test_botops_closes_a_persons_task_for_them(api):
    # Purge the tasks that don't really need him.
    with api.app.state.store.transaction() as c:
        c.execute("INSERT INTO bots(slug,display_name,state) VALUES('botops','BotOps','active')")
        c.execute("INSERT INTO bot_config(bot,config_json,operator) VALUES('botops',?, 'ana')",
                  (encode({"name": "botops", "runtime": "fake", "status": "active"}),))
    from backend.tests.test_api import setup_attempt
    _, _, botops = setup_attempt(api, "botops")
    _, _, ops = setup_attempt(api, "ops")
    task = post(api, "tasks", {"owner": "ana", "title": "Review an old card", "body": "Imported."})
    ask = post(api, "chat/botops", {"text": "Purge the tasks that don't need me"})
    mid = ask.get("message", ask)["id"]
    def version():
        with api.app.state.store.read() as c:
            return c.execute("SELECT version FROM tasks WHERE id=?", (task["id"],)).fetchone()[0]
    post(api, "tasks/" + task["id"], {"version": version(), "status": "done", "note": "x"}, token=botops["token"], expected=403)
    post(api, "tasks/" + task["id"], {"version": version(), "status": "done", "note": "x", "on_behalf_of": mid},
         token=ops["token"], expected=403)
    post(api, "tasks/" + task["id"], {"version": version(), "status": "done", "note": "Not needed.", "on_behalf_of": mid},
         token=botops["token"])
    with api.app.state.store.read() as c:
        assert c.execute("SELECT status FROM tasks WHERE id=?", (task["id"],)).fetchone()[0] == "closed"   # his own task: done closes it
        event = c.execute("SELECT actor,detail_json FROM events WHERE action='task.update_delegated'").fetchone()
        assert event["actor"] == "bot:botops" and json.loads(event["detail_json"])["on_behalf_of"] == "human:ana"


def test_a_task_a_bot_filed_for_itself_closes_when_done(api):
    from backend.tests.test_api import setup_attempt
    _, _, ops = setup_attempt(api, "ops")
    mine = post(api, "tasks", {"owner": "ops", "title": "Acme the notes", "body": "Mine."}, token=ops["token"])
    theirs = post(api, "tasks", {"owner": "ops", "title": "Review the notes", "body": "From Ana."})
    def state(tid):
        with api.app.state.store.read() as c:
            return c.execute("SELECT status,version FROM tasks WHERE id=?", (tid,)).fetchone()
    post(api, "tasks/" + mine["id"], {"version": state(mine["id"])[1], "status": "done", "note": "Done."}, token=ops["token"])
    post(api, "tasks/" + theirs["id"], {"version": state(theirs["id"])[1], "status": "done", "note": "Done."}, token=ops["token"])
    assert state(mine["id"])[0] == "closed"
    assert state(theirs["id"])[0] == "done"          # someone else asked: they review and close



def test_the_owner_takes_someone_who_left_off_the_chart_and_botops_may_do_it_on_his_word(api):
    # Ana, 2026-09-27: "Marta Marcus and Nora don't work here, remove them from org".
    from backend.tests.test_api import setup_attempt
    roster(api, [{"id": "ana", "email": "ana@acme.example", "name": "Ana", "primary_for": ["*"]},
                 {"id": "ben", "email": "ben@acme.example", "name": "Ben", "reports_to": "ana"},
                 {"id": "cara", "email": "cara@acme.example", "name": "Cara", "reports_to": "ben"},
                 {"id": "marta", "email": "marta@acme.example", "name": "Marta", "reports_to": "cara"},
                 {"id": "kai", "email": "kai@acme.example", "name": "Kai", "reports_to": "marta"}])
    post(api, "people/marta", {"left": True}, token="ben-test", expected=403)   # not the owner
    post(api, "people/marta", {"left": True})
    people, _ = tree(api)
    assert "marta" not in people and people["kai"] == "p:cara"      # her report moves up
    post(api, "people/marta", {"left": True})                           # again: nothing to do
    # BotOps, citing Ana's message to it.
    with api.app.state.store.transaction() as c:
        c.execute("INSERT INTO bots(slug,display_name,state) VALUES('botops','BotOps','active')")
        c.execute("INSERT INTO bot_config(bot,config_json,operator) VALUES('botops',?, 'ana')",
                  (encode({"name": "botops", "runtime": "fake", "status": "active"}),))
    _, _, botops = setup_attempt(api, "botops")
    post(api, "people/cara", {"left": True}, botops["token"], expected=403)
    ask = post(api, "chat/botops", {"text": "Cara doesn't work here, remove him from org"})
    mid = ask.get("message", ask)["id"]
    post(api, "people/cara", {"left": True, "on_behalf_of": mid}, botops["token"])
    people, _ = tree(api)
    assert "cara" not in people and people["kai"] == "p:ben"
    with api.app.state.store.read() as c:
        assert c.execute("SELECT count(*) FROM events WHERE action='person.update_delegated' AND target='cara'").fetchone()[0] == 1


def test_a_bot_reporting_to_a_bot_that_is_not_there_hangs_under_the_owner(api):
    """An assistant a company chose not to have leaves BotOps' `reports_to` dangling: the bot stays
    on the chart, under the owner."""
    roster(api, [{"id": "ana", "email": "ana@acme.example", "name": "Ana", "primary_for": ["*"]},
                 {"id": "ben", "email": "ben@acme.example", "name": "Ben", "reports_to": "ana"}])
    with api.app.state.store.transaction() as c:
        c.execute("UPDATE registry_metadata SET value_json=json_set(value_json,'$.default_user','ana') WHERE key='people'")
        c.execute("UPDATE bot_config SET reports_to='gone-assistant' WHERE bot='ops'")
    _, bots = tree(api)
    assert bots["ops"] == "p:ana"


def test_work_nobody_was_named_for_goes_to_botops_when_there_is_no_assistant(api):
    from backend.views import default_bot
    settings = api.app.state.store.settings
    with api.app.state.store.transaction() as c:
        assert default_bot(c, settings) == "coo"
        c.execute("INSERT INTO bots(slug,display_name,state) VALUES('botops','BotOps','active')")
        c.execute("UPDATE bots SET state='planned' WHERE slug='coo'")
        assert default_bot(c, settings) == "botops"
        c.execute("UPDATE bots SET state='archived' WHERE slug='coo'")
        assert default_bot(c, settings) == "botops"
