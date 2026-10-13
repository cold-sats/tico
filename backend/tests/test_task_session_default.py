"""Every task is its own session by default: the shared keying, and the one-time clearing of the old written default."""
import json

from backend.tests.test_api import api  # noqa: F401  (api is a fixture)
from clients import sessions


def test_task_turns_get_their_own_session_unless_the_bot_opts_out():
    assert sessions.session_key({}, "ops", "t1", "c1") == "task:t1"
    assert sessions.session_key({}, "ops", None, "c1") == sessions.BOT_THREAD          # chat keeps one thread
    assert sessions.lane({}, "ops", "t1", "c1") == "task:t1"                             # server and runner agree
    assert sessions.session_key({"session": "bot"}, "ops", "t1", "c1") == sessions.BOT_THREAD
    assert sessions.lane({"session": "bot"}, "ops", "t1", "c1") == sessions.MAIN_LANE
    assert sessions.session_key({"session": "task"}, "ops", None, "c1") == "conversation:c1"
    assert sessions.session_key({}, "botops", None, "c1") == "conversation:c1"


def test_the_old_written_bot_default_is_cleared_once(api):
    store = api.app.state.store
    def session(bot):
        with store.transaction() as c:
            return json.loads(c.execute("SELECT config_json FROM bot_config WHERE bot=?", (bot,)).fetchone()[0]).get("session", "")
    def put(bot, value):
        with store.transaction() as c:
            c.execute("UPDATE bot_config SET config_json=json_set(config_json,'$.session',?) WHERE bot=?", (value, bot))
    put("ops", "bot"), put("cpo", "task")
    with store.transaction() as c:
        c.execute("DELETE FROM registry_metadata WHERE key='task_session_default'")
    store.initialize(seed_market=False)
    assert (session("ops"), session("cpo")) == ("", "task")
    put("ops", "bot")                                     # a later explicit choice stays
    store.initialize(seed_market=False)
    assert session("ops") == "bot"
