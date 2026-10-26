"""A person waives a Dev ticket's In QA step for one exact head (backend/qa_waivers.py): recorded as a waiver with its
actor, reason, head, step and time, never as a QA verdict; CI and both reviews on that head stay required."""
import json
import uuid

import pytest
from fastapi.testclient import TestClient

from backend import hubdb as H, qa_waivers
from backend.app import create_app
from backend.auth import Identity
from backend.config import Settings
from backend.store import encode
from backend.tests.test_github import SECRET, PR, hook, pr_event

HEAD, NEW = 'a' * 40, 'b' * 40
STEPS = [{'name': n, 'status': s} for n, s in (('In Progress', 'doing'), ('Review 1', 'review'), ('Review 1 Fixes', 'doing'),
         ('Review 2', 'review'), ('Review 2 Fixes', 'doing'), ('In QA', 'review'), ('QA Fixes', 'doing'),
         ('Pending Release', 'ready'), ('Done', 'done'))]


@pytest.fixture
def api(tmp_path):
    app = create_app(Settings(db_path=tmp_path / 'hub.db', github_webhook_secret=SECRET, release_commit='',
                              release_repo='ticoteam/tico', test_identities={
        'ana-test': Identity('human:ana', 'owner', 'ana@acme.example'),
        'ben-test': Identity('human:ben', 'human', 'ben@acme.example'),
        'cara-test': Identity('human:cara', 'human', 'cara@acme.example'),
        'bot-test': Identity('bot:cpo', 'bot', runner_id='r1', attempt_id='a1')}))
    with TestClient(app) as client:
        with app.state.store.transaction() as c:
            bots = {slug: {'name': slug, 'runtime': 'fake', 'status': 'active'} for slug in ('cpo', 'cmo')}
            people = [{'id': 'ana', 'email': 'ana@acme.example', 'team': 'leadership', 'primary_for': ['*']},
                      {'id': 'ben', 'email': 'ben@acme.example', 'team': 'support'},
                      {'id': 'cara', 'email': 'cara@acme.example', 'team': 'support'}]
            H.sync_registry(c, bots, {'people': people})
            c.execute("INSERT INTO registry_metadata VALUES('people',?)", (encode({'people': people}),))
            for slug, config in bots.items():
                c.execute('INSERT INTO bot_config(bot,config_json,team,operator) VALUES(?,?,?,?)',
                          (slug, encode(config), 'product', 'ana'))
            c.execute("INSERT INTO registry_metadata VALUES('onboarding',?)", (encode({'completed': '2026-01-01T00:00:00Z'}),))
            H.type_create(c, H.KEEPER, 'Dev tickets', STEPS)
        yield client


def call(api, method, path, token='ana-test', body=None):
    return api.request(method, '/api/v2/' + path, json=body,
                       headers={'Authorization': 'Bearer ' + token, 'Idempotency-Key': str(uuid.uuid4())})


def child(api, ticket, title, status='done', verdict=None, head=None):
    """A review or QA subtask with a recorded verdict, written directly: the review gate is not under test here."""
    r = call(api, 'POST', 'tasks', body={'owner': 'cmo', 'title': 'Check it', 'body': 'Check the change.',
                                        'relations': [{'task': ticket['id'], 'kind': 'parent'}]})
    assert r.status_code == 200, r.text
    with api.app.state.store.transaction() as c:
        c.execute('UPDATE tasks SET title=?, status=?, verdict=?, verdict_head=? WHERE id=?',
                  (title, status, verdict, head, r.json()['task']['id']))
    return r.json()['task']


def ticket(api, owner='cpo', step='In QA', checks=None, reviews=(('approve', HEAD), ('approve', HEAD))):
    with api.app.state.store.read() as c:
        typ = H.type_get(c, 'Dev tickets')
    r = call(api, 'POST', 'tasks', body={'owner': owner, 'title': 'Fix the checkout total', 'body': 'Fix it.',
                                        'type': typ['id'], 'step': step, 'links': [PR]})
    assert r.status_code == 200, r.text
    row = r.json()['task']
    hook(api, 'pull_request', pr_event('opened', head={'sha': HEAD}))
    with api.app.state.store.transaction() as c:
        c.execute("UPDATE task_links SET detail_json=json_set(detail_json,'$.checks',json(?)) WHERE task_id=? AND kind='pr'",
                  (json.dumps(checks or {'check:python': 'passing', 'check:browser': 'skipped'}), row['id']))
    for name, (verdict, head) in zip(('Review 1: PR #412', 'Review 2: PR #412'), reviews):
        if verdict:
            child(api, row, name, verdict=verdict, head=head)
    child(api, row, 'QA: PR #412', status='doing')
    return row


def waive(api, row, token='ana-test', head=HEAD, reason='Urgent fix, QA bot down', **more):
    return call(api, 'POST', f"tasks/{row['id']}/qa-waiver", token, {'head': head, 'reason': reason, **more})


def shown(api, row):
    return call(api, 'GET', 'tasks/' + row['id']).json()


@pytest.mark.parametrize('owner,token,actor', [('human:ben', 'ben-test', 'human:ben'),   # the ticket's owner
                                               ('cpo', 'ana-test', 'human:ana')])          # a manager
def test_owner_or_manager_waives_the_current_qa_step_on_the_exact_head(api, owner, token, actor):
    row = ticket(api, owner=owner)
    r = waive(api, row, token)
    assert r.status_code == 200, r.text
    waiver = r.json()['waiver']
    assert {k: waiver[k] for k in ('actor', 'reason', 'head', 'step', 'pr', 'current')} == {
        'actor': actor, 'reason': 'Urgent fix, QA bot down', 'head': HEAD, 'step': 'In QA', 'pr': PR, 'current': True}
    assert waiver['at']
    detail = shown(api, row)
    assert detail['task']['qa_waivers'] == [waiver]
    event = next(e for e in detail['events'] if e['field'] == 'qa_waiver')
    assert event['actor'] == actor and event['note'] == 'Urgent fix, QA bot down'
    assert json.loads(event['new']) == {'head': HEAD, 'step': 'In QA', 'pr': PR}
    # A waiver is not a verdict: nothing on the ticket or its QA subtask reads as a QA pass, and the ticket stays put.
    assert not any(e['field'] == 'verdict' for e in detail['events'])
    assert detail['task']['verdict'] is None and detail['task']['step']['name'] == 'In QA'
    qa = next(c for c in detail['children'] if c['title'].startswith('QA'))
    assert qa['verdict'] is None and qa['status'] == 'doing'
    with api.app.state.store.read() as c:
        told = c.execute("SELECT to_actor, body FROM messages WHERE json_extract(refs_json,'$.qa_waiver')=?", (HEAD,)).fetchall()
    assert [(m[0], 'not a QA pass' in m[1]) for m in told] == ([('bot:cpo', True)] if owner == 'cpo' else [])


@pytest.mark.parametrize('owner,token,why', [('human:ben', 'cara-test', 'owner or a manager'),
                                             ('cpo', 'ben-test', 'owner or a manager'),
                                             ('cpo', 'bot-test', "a person's decision")])
def test_a_non_owner_non_manager_or_a_bot_is_refused(api, owner, token, why):
    row = ticket(api, owner=owner)
    r = waive(api, row, token)
    assert r.status_code == 403 and why in r.text, r.text
    assert shown(api, row)['task']['qa_waivers'] == []


@pytest.mark.parametrize('step,asked,why', [('Review 2', None, 'not In QA'), ('Pending Release', None, 'not In QA'),
                                            ('In QA', 'Review 1', 'Review 1 is mandatory'),
                                            ('In QA', 'Review 2', 'Review 2 is mandatory'),
                                            ('In QA', 'CI', 'CI is mandatory'),
                                            ('In QA', 'Release approval', 'Release approval is mandatory'),
                                            ('In QA', 'Post Release QA', 'Only the In QA step')])
def test_only_the_current_in_qa_step_is_waivable(api, step, asked, why):
    row = ticket(api, step=step)
    r = waive(api, row, step=asked) if asked else waive(api, row)
    assert r.status_code == 422 and why in r.text, r.text
    assert shown(api, row)['task']['qa_waivers'] == []


def test_a_different_head_is_refused_and_a_new_push_voids_the_waiver(api):
    row = ticket(api)
    r = waive(api, row, head=NEW)
    assert r.status_code == 422 and 'not the current head' in r.text, r.text
    assert waive(api, row).status_code == 200
    hook(api, 'pull_request', pr_event('synchronize', head={'sha': NEW}))
    assert [w['current'] for w in shown(api, row)['task']['qa_waivers']] == [False]
    # The old head's waiver does not stand for the new head, and the new head has no review approving it.
    r = waive(api, row, head=NEW)
    assert r.status_code == 422 and 'Review 2 approved aaaaaaaaaaaa, not bbbbbbbbbbbb' in r.text, r.text
    r = waive(api, row)
    assert r.status_code == 422 and 'not the current head' in r.text, r.text


@pytest.mark.parametrize('checks,why', [({'check:python': 'failing', 'check:browser': 'passing'}, 'CI failing on'),
                                        ({'check:python': 'passing', 'check:browser': 'pending'}, 'CI still running'),
                                        ({'check:python': 'skipped'}, 'no passing hosted check')])
def test_checks_not_green_are_refused_and_named(api, checks, why):
    row = ticket(api, checks=checks)
    r = waive(api, row)
    assert r.status_code == 422 and why in r.text and 'Hosted checks stay mandatory' in r.text, r.text


@pytest.mark.parametrize('reviews,why', [((('approve', HEAD), (None, None)), 'Review 2 has no recorded verdict'),
                                         (((None, None), ('approve', HEAD)), 'Review 1 has no recorded verdict'),
                                         ((('approve', HEAD), ('changes', HEAD)), 'Review 2 asked for changes'),
                                         ((('approve', HEAD), ('approve', NEW)), 'Review 2 approved bbbbbbbbbbbb'),
                                         ((('changes', HEAD), ('approve', HEAD)), 'Review 1 asked for changes')])
def test_required_reviews_not_approving_the_head_are_refused(api, reviews, why):
    row = ticket(api, reviews=reviews)
    r = waive(api, row)
    assert r.status_code == 422 and why in r.text and 'Code reviews stay mandatory' in r.text, r.text


def test_review_1_changes_fixed_and_review_2_approving_the_head_allows_it(api):
    """Review 1 asked for changes on an earlier head; Review 1 Fixes made them and Review 2 approved this head."""
    row = ticket(api, reviews=(('changes', NEW), ('approve', HEAD)))
    assert waive(api, row).status_code == 200


def test_an_open_review_is_refused_and_a_second_waiver_for_the_head_too(api):
    row = ticket(api)
    child(api, row, 'Review 2: PR #412 delta', status='doing')
    r = waive(api, row)
    assert r.status_code == 422 and 'Review 2 is still open' in r.text, r.text
    row = ticket(api)
    with api.app.state.store.transaction() as c:
        c.execute("DELETE FROM task_links WHERE task_id<>?", (row['id'],))
    assert waive(api, row).status_code == 200
    r = waive(api, row, reason='Again')
    assert r.status_code == 422 and 'already waived' in r.text, r.text


def test_a_fresh_github_read_is_what_counts(api):
    """With the GitHub App configured, the route's fresh read stands in for the webhook-built link."""
    row = ticket(api)
    with api.app.state.store.transaction() as c:
        link = H.task_links(c, row['id'])[0]
        fresh = {link['id']: {'head_sha': HEAD, 'checks': {'check:python': 'pending'}, 'at': H.now()}}
        with pytest.raises(H.Refused, match='CI still running'):
            qa_waivers.waive(c, 'human:ana', row['id'], HEAD, 'Urgent', snapshots=fresh, manager=True)
        moved = {link['id']: {'head_sha': NEW, 'checks': {'check:python': 'passing'}, 'at': H.now()}}
        with pytest.raises(H.Refused, match='not the current head'):
            qa_waivers.waive(c, 'human:ana', row['id'], HEAD, 'Urgent', snapshots=moved, manager=True)
        failed = {link['id']: {'error': True, 'why': 'GitHub read failed: ConnectError'}}
        with pytest.raises(H.Refused, match='Cannot read the current head'):
            qa_waivers.waive(c, 'human:ana', row['id'], HEAD, 'Urgent', snapshots=failed, manager=True)
