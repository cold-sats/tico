"""`python -m backend.devcopy`: a dev server's copy of real data keeps the team's history but nothing that acts,
and the rehearsal it starts in refuses every runner. Synthetic databases only; a real one is never a fixture."""
import sqlite3
import stat
from contextlib import closing

import pytest

from backend import devcopy
from backend.auth import Identity
from backend.config import Settings
from backend.execution import Execution
from backend.store import H, Problem, Store

OLD = "2020-01-01T00:00:00.000000Z"


def source_db(tmp_path):
    store = Store(Settings(db_path=tmp_path / "live" / "hub.sqlite"))
    store.initialize(seed_market=False)
    now = H.now()
    with store.transaction() as c:
        c.execute("INSERT INTO humans(id,name,email) VALUES('morgan','Morgan','morgan@acme.example')")
        c.execute("INSERT INTO bots(slug,token_hash,state) VALUES('sales','botsecret','active')")
        c.execute("INSERT INTO runners(id,label,operator,token_hash,created) VALUES('r1','mac','morgan','rh',?)", (now,))
        c.execute("INSERT INTO enrollments(code_hash,operator,expires) VALUES('ch','morgan',?)", (now,))
        c.execute("INSERT INTO conversations(id) VALUES('cv')")
        for mid, at in (("old", OLD), ("new", now)):
            c.execute("INSERT INTO messages(id,conversation_id,from_actor,to_actor,kind,body,created) "
                      "VALUES(?,'cv','human:morgan','bot:sales','ask','hi',?)", (mid, at))   # the trigger queues a job
        aid = H.new_id()
        c.execute("INSERT INTO attempts(id,job_id,bot,runner_id,generation,token_hash,state,lease_until,created) "
                  "VALUES(?,'new','sales','r1',1,'at','running',?,?)", (aid, now, now))
        c.execute("INSERT INTO attempt_events(attempt_id,seq,kind,payload_json,created) VALUES(?,1,'text','{}',?)",
                  (aid, now))
        c.execute("INSERT INTO human_tokens(id,human,label,token_hash,created,created_by) VALUES('t1','morgan','cli','th',?,'morgan')", (now,))
        c.execute("INSERT INTO credentials(id,name,kind,created,updated,updated_by) VALUES('k1','gh','token',?,?,'morgan')",
                  (now, now))
        c.execute("INSERT INTO schedules(id,bot,cron) VALUES('s1','sales','* * * * *')")
    for name in ("credential.key", "slack.key"):
        (store.settings.db_path.parent / name).write_bytes(b"k" * 32)
    return store.settings.db_path


def test_a_dev_copy_keeps_history_empties_what_acts_and_refuses_runners(tmp_path):
    source = source_db(tmp_path)
    before = source.read_bytes()
    dest = tmp_path / "copy" / "hub.sqlite"
    removed = devcopy.build(source, dest, days=30)
    devcopy.write_environment(dest, 8879, "morgan@acme.example")
    assert source.read_bytes() == before                                    # the source is only read
    assert removed["jobs"] == 2 and removed["attempt_events"] == 1 and removed["messages"] == 1
    assert stat.S_IMODE(dest.stat().st_mode) == 0o600
    assert not any((dest.parent / name).exists() for name in ("credential.key", "github-app.key", "slack.key"))
    with closing(sqlite3.connect(dest)) as c:
        for table in devcopy.emptied(c):
            assert c.execute(f"SELECT count(*) FROM {table}").fetchone()[0] == 0, table
        assert c.execute("SELECT token_hash FROM bots").fetchall() == [(None,)]
        assert c.execute("SELECT id FROM messages").fetchall() == [("new",)]
        assert c.execute("PRAGMA foreign_key_check").fetchall() == []
        assert c.execute("SELECT count(*) FROM sqlite_master WHERE name='queue_bot_message'").fetchone()[0] == 1
    env = dict(line.split("=", 1) for line in (dest.parent / "server.env").read_text().splitlines()
               if "=" in line and not line.startswith("#"))
    assert (env["TICO_REHEARSAL"], env["TICO_DB"], env["TICO_PUBLIC_URL"]) == ("1", str(dest.resolve()), "http://127.0.0.1:8879")
    assert stat.S_IMODE((dest.parent / "server.env").stat().st_mode) == 0o600

    with pytest.raises(SystemExit, match="already exists"):            # never replaced without --force
        devcopy.build(source, dest)
    with pytest.raises(SystemExit, match="is the source"):
        devcopy.build(source, source, force=True)
    with closing(sqlite3.connect(dest)) as held:                         # a server holding it open
        held.execute("PRAGMA journal_mode=WAL")
        held.execute("SELECT 1 FROM bots").fetchall()
        with pytest.raises(SystemExit, match="in use"):
            devcopy.build(source, dest, force=True)

    store = Store(Settings(db_path=dest, rehearsal=True))
    execution = Execution(store, None)
    runner = Identity("runner:r1", "runner", runner_id="r1")
    for call in (lambda c: execution.claim(c, runner, None), lambda c: execution.heartbeat(c, runner, None),
                 lambda c: execution.enroll(None),
                 lambda c: execution.issue_enrollment(c, Identity("human:morgan", "owner"), None)):
        with pytest.raises(Problem) as refused:
            call(None)
        assert refused.value.code == "rehearsal"
