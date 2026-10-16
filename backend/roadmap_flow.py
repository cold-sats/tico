"""Default product and engineering pipelines over task steps and parent relations."""

PRODUCT = 'product-roadmap'
ENGINEERING = 'engineering'
TERMINAL = ('done', 'closed', 'declined')


def ensure(c):
    from . import hubdb as H
    for ident, name, manager, steps in (
        (PRODUCT, 'Product roadmap', 'product-manager', [
            ('Suggested', 'open'), ('Exploring', 'doing'), ('Spec', 'review'),
            ('Approved', 'review'), ('Building', 'doing'), ('Shipped', 'done'), ('Declined', 'declined')]),
        (ENGINEERING, 'Engineering', 'engineering-lead', [
            ('Todo', 'open'), ('Doing', 'doing'), ('Waiting', 'waiting'),
            ('In review', 'review'), ('Ready to ship', 'ready'), ('Done', 'closed'), ('Declined', 'declined')]),
    ):
        if c.execute('SELECT 1 FROM task_types WHERE id=? OR name=? COLLATE NOCASE', (ident, name)).fetchone():
            continue
        c.execute('INSERT INTO task_types(id,name,bots,manager,created,updated) VALUES(?,?,?,?,?,?)',
                  (ident, name, 'work', manager, H.now(), H.now()))
        for position, (step, status) in enumerate(steps):
            c.execute('INSERT INTO task_steps(id,type_id,name,position,status) VALUES(?,?,?,?,?)',
                      (ident + '-' + str(position), ident, step, position, status))


def sync(c, task_id):
    from . import hubdb as H
    row = H.task(c, task_id)
    if not row or row.get('type_id') != PRODUCT:
        return
    typ = H.type_get(c, PRODUCT)
    current = next((s['name'] for s in typ['steps'] if s['id'] == row['step_id']), None)
    if current not in ('Approved', 'Building', 'Shipped'):
        return
    total, unfinished = c.execute(
        "SELECT count(*),coalesce(sum(t.status NOT IN ('done','closed','declined')),0) "
        "FROM task_relations r JOIN tasks t ON t.id=r.from_task "
        "WHERE r.to_task=? AND r.kind='parent' AND t.type_id=?", (task_id, ENGINEERING)).fetchone()
    wanted = 'Building' if unfinished else 'Shipped' if total else 'Approved'
    step = next((s for s in typ['steps'] if s['name'] == wanted), None)
    if not step or current == wanted:
        return
    H._set_status(c, H.KEEPER, row, step=step['id'])
    version = ',version=version+1' if 'version' in {r[1] for r in c.execute('PRAGMA table_info(tasks)')} else ''
    c.execute('UPDATE tasks SET done_at=?' + version + ' WHERE id=?',
              (H.now() if wanted == 'Shipped' else None, task_id))
    H._recount(c, row['owner'])
    H.event(c, H.KEEPER, 'task.update', task_id, {'step': step['id']})


def changed(c, task_id):
    from . import task_relations as TR
    sync(c, task_id)
    parent = TR.parent_of(c, task_id)
    if parent:
        sync(c, parent)
