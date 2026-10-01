"""Pipeline migrations preserve every legacy status and custom task assignment."""

import sqlite3

from backend import hubdb as H


def test_general_backfill_is_idempotent_and_does_not_reassign_custom_tasks(tmp_path):
    path = tmp_path / 'legacy.db'
    c = sqlite3.connect(path, isolation_level=None)
    c.row_factory = sqlite3.Row
    for script in H.MIGRATIONS[:13]:
        H._apply(c, script)
    c.execute('PRAGMA user_version=13')
    for status in H.TASK_STATUSES:
        c.execute('INSERT INTO tasks(id,title,status,body,note) VALUES(?,?,?,?,?)',
                  (status, 'Keep this task', status, 'Keep these details', 'Keep this note'))
    H._apply(c, "ALTER TABLE tasks ADD COLUMN labels_json TEXT NOT NULL DEFAULT '[]';")
    c.execute('UPDATE tasks SET labels_json=?', ('["release","bug"]',))
    H.migrate(c)
    assert c.execute('PRAGMA user_version').fetchone()[0] == 15
    for row in c.execute('SELECT * FROM tasks'):
        assert row['type_id'] == H.GENERAL_TYPE
        assert row['step_id'] == 'general-' + row['status']
        assert row['body'] == 'Keep these details' and row['note'] == 'Keep this note'
        assert H.task_labels(H.task(c, row['id'])) == ['release', 'bug']
    custom = H.type_create(c, H.KEEPER, 'Marketing', [{'name': 'Draft', 'status': 'open'}])
    c.execute('UPDATE tasks SET type_id=?,step_id=? WHERE id=?', (custom['id'], custom['steps'][0]['id'], 'open'))
    H._set_task_tags(c, H.KEEPER, 'open', ['bug'])
    H._apply(c, H.PIPELINES_SCHEMA)
    H.migrate(c)
    assert H.task(c, 'open')['type_id'] == custom['id']
    assert H.task_labels(H.task(c, 'open')) == ['bug']
    assert H.task(c, 'open')['labels_json'] == '["release","bug"]'
    assert c.execute('SELECT count(*) FROM task_steps WHERE type_id=?', (H.GENERAL_TYPE,)).fetchone()[0] == 8
    assert c.execute('PRAGMA foreign_key_check').fetchall() == []
    c.close()
