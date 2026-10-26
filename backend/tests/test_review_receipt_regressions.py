"""Review entry uses current CI evidence without losing real same-head failures."""
import json
from types import SimpleNamespace

import pytest

from backend import hubdb as H, test_receipts
from backend.tests.test_github import api, headers, post, PR
from backend.tests.test_review_gate import HEAD, OLD, ticket, move


def github(api, monkeypatch, checks=(), statuses=()):
    service = api.app.state.github_app
    monkeypatch.setattr(service, 'row', lambda c: {'org': 'ticoteam'})
    monkeypatch.setattr(service, 'mint', lambda *a: ('synthetic', 'later'))
    calls = []
    def fetch(method, path, **kwargs):
        calls.append((path, kwargs.get('params')))
        data = ({'head': {'sha': HEAD}} if '/pulls/' in path else
                {'check_runs': list(checks)} if path.endswith('check-runs') else list(statuses))
        return SimpleNamespace(status_code=200, json=lambda: data)
    monkeypatch.setattr(service, '_call', fetch)
    return calls


@pytest.mark.parametrize('step', ['Review 1', 'Review 2'])
@pytest.mark.parametrize('receipt', [None, f'Tests: head {HEAD}: 2 failed',
                                  f'Tests: head {OLD}: 9 passed'])
def test_fresh_all_green_opens_review_without_text_and_overrides_text_failure(api, monkeypatch, step, receipt):
    task = ticket(api, receipt)
    github(api, monkeypatch, [{'id': 1, 'name': 'python', 'conclusion': 'success'},
                              {'id': 2, 'name': 'browser', 'conclusion': 'success'}])
    response = move(api, task, step)
    assert response.status_code == 200, response.text
    child = api.post('/api/v2/tasks', headers=headers(), json={'owner': 'cmo', 'title': step + ': PR #412',
        'body': 'Check current code.', 'relations': [{'task': task['id'], 'kind': 'parent'}]})
    assert child.status_code == 200, child.text


@pytest.mark.parametrize('checks,statuses', [([], []),
    ([{'id': 1, 'name': 'python', 'conclusion': None}], []),
    ([{'id': 1, 'name': 'python', 'conclusion': 'skipped'}], []),
    ([{'id': 1, 'name': 'python', 'conclusion': 'neutral'}], [])])
def test_absent_pending_or_only_skipped_checks_still_need_passing_receipt(api, monkeypatch, checks, statuses):
    task = ticket(api)
    github(api, monkeypatch, checks, statuses)
    response = move(api, task)
    assert response.status_code == 422 and 'passing test receipt' in response.text, response.text
    assert 'manager' in response.text and 'person' in response.text
    with api.app.state.store.transaction() as c:
        H.task_comment(c, task['owner'], task['id'], f'Tests: head {HEAD}: 9 passed, 0 failed', wake=False)
    assert move(api, task).status_code == 200


@pytest.mark.parametrize('source', ['checks', 'statuses'])
def test_github_failed_attempt_still_blocks_after_green_rerun(api, monkeypatch, source):
    task = ticket(api, f'Tests: head {HEAD}: 9 passed')
    calls = github(api, monkeypatch,
        checks=[{'id': 2, 'name': 'python', 'conclusion': 'success'},
                {'id': 1, 'name': 'python', 'conclusion': 'failure'}] if source == 'checks' else [],
        statuses=[{'context': 'python', 'state': 'success'},
                  {'context': 'python', 'state': 'failure'}] if source == 'statuses' else [])
    response = move(api, task)
    assert response.status_code == 422, response.text
    assert 'same head' in response.text and 'rerun' in response.text and 'new head' in response.text
    assert all(params.get('filter') == 'all' for path, params in calls if path.endswith('check-runs'))


@pytest.mark.parametrize('pending', [False, True])
def test_success_with_skipped_companion_counts_but_pending_does_not(api, monkeypatch, pending):
    task = ticket(api)
    github(api, monkeypatch, [{'id': 1, 'name': 'python', 'conclusion': 'success'},
                             {'id': 2, 'name': 'optional', 'conclusion': None if pending else 'skipped'}])
    response = move(api, task)
    assert response.status_code == (422 if pending else 200), response.text


def test_successful_commit_status_can_supply_the_receipt(api, monkeypatch):
    task = ticket(api)
    github(api, monkeypatch, statuses=[{'context': 'tests', 'state': 'success'}])
    assert move(api, task).status_code == 200


def test_one_green_pr_does_not_supply_another_prs_receipt(api, monkeypatch):
    task = ticket(api)
    post(api, 'tasks/' + task['id'] + '/links', {'url': PR.replace('/412', '/413')})
    github(api, monkeypatch, [{'id': 1, 'name': 'python', 'conclusion': 'success'}])
    service = api.app.state.github_app
    fetch = service._call
    monkeypatch.setattr(service, '_call', lambda method, path, **kw:
        SimpleNamespace(status_code=200, json=lambda: {'head': {'sha': OLD}}) if '/pulls/413' in path else
        SimpleNamespace(status_code=200, json=lambda: {'check_runs': []}) if OLD in path and path.endswith('check-runs') else
        fetch(method, path, **kw))
    response = move(api, task)
    assert response.status_code == 422 and OLD in response.text, response.text


@pytest.mark.parametrize('text,status', [
    (f'Tests at head {HEAD}: 9 passed after fixing the earlier failure', 'passed'),
    (f'Tests at head {HEAD}: 9 passed; fixed the failure at head {OLD}', 'passed'),
    (f'Tests at head {HEAD}: 9 passed; the earlier error is now repaired', 'passed'),
    (f'Tests at head {HEAD}: 9 passed; tests at head {OLD}: 2 failed', 'passed'),
    (f'Tests at head {HEAD}: 9 passed after tests at head {OLD}: 2 failed', 'passed'),
    (f'Tests at head {HEAD}: 2 failed after fixing the earlier failure', 'failed'),
    (f'Tests at head {HEAD}: 9 passed, 1 failed; fixed an earlier failure', 'failed'),
    (f'Tests at head {HEAD}: 9 passed; 1 failed', 'failed'),
    (f'Tests completed and head {HEAD}: 9 passed', 'passed'),
    (f'Tests at head {OLD}: 2 failed. Tests at head {HEAD}: 9 passed', 'failed'),
])
def test_historical_failure_phrases_are_not_current_run_results(text, status):
    receipt = test_receipts.recognise(text)
    assert receipt['status'] == status
    if receipt['head'] == OLD:
        assert test_receipts.at_head({'id': 't', 'note': text}, HEAD)[0] != 'failed'


def test_two_heads_in_one_line_keep_their_own_outcomes():
    text = f'Tests at head {HEAD}: 9 passed; tests at head {OLD}: 2 failed'
    assert test_receipts.at_head({'id': 't', 'note': text}, HEAD)[0] == 'passed'
    assert test_receipts.at_head({'id': 't', 'note': text}, OLD)[0] == 'failed'


def test_dev505_original_note_does_not_claim_a_current_failure():
    # Exact opening sentence of the refused 03:37Z note, not the rewritten receipt.
    head = 'e06bfdf7ec6bdbd1772fb16102fee40715536e92'
    note = ('All lifecycle fixes remain built; a hosted-test fixture failure is now repaired and pushed '
            f'in PR #1542 at {head}. Review 1 remains blocked by the GitHub App sign-in refusal '
            '(original operation 46146711-bf35-46bd-8ff2-32dd8d8ab1bb); no retry/relink/bypass.')
    assert test_receipts.at_head({'id': 't', 'note': note}, head)[0] != 'failed'


@pytest.mark.parametrize('author', ['manager', 'grandmanager', 'person', 'outsider'])
def test_manager_chain_and_editing_person_can_supply_no_ci_receipt(api, author):
    task = ticket(api)
    with api.app.state.store.transaction() as c:
        for slug, parent in [('cpo', 'cmo'), ('cmo', 'boss')]:
            c.execute('UPDATE bot_config SET reports_to=? WHERE bot=?', (parent, slug))
        c.execute("INSERT INTO bots(slug,state) VALUES('boss','active')")
        c.execute("INSERT INTO bot_config(bot,config_json,operator) VALUES('boss','{}','ana')")
        if author == 'outsider':
            c.execute("UPDATE bot_config SET reports_to=NULL WHERE bot='cpo'")
        actor = {'manager': 'bot:cmo', 'grandmanager': 'bot:boss', 'person': 'human:ana', 'outsider': 'bot:cmo'}[author]
        H.task_comment(c, actor, task['id'], f'Tests: head {HEAD}: 9 passed, 0 failed', wake=False)
    response = move(api, task)
    assert response.status_code == (422 if author == 'outsider' else 200), response.text


def test_written_failure_is_not_cleared_by_a_managers_same_head_rerun(api):
    task = ticket(api, f'Tests: head {HEAD}: 2 failed')
    with api.app.state.store.transaction() as c:
        c.execute("UPDATE bot_config SET reports_to='cmo' WHERE bot='cpo'")
        H.task_comment(c, 'bot:cmo', task['id'], f'Tests: head {HEAD}: 9 passed, 0 failed', wake=False)
    response = move(api, task)
    assert response.status_code == 422 and 'failed test receipt' in response.text


def test_human_without_task_edit_rights_is_not_a_receipt_author(api):
    task = ticket(api)
    with api.app.state.store.transaction() as c:
        c.execute("INSERT INTO humans(id,name,email,teams_json) VALUES('guest','Guest','guest@example.test','[]')")
        conv = H.conversation(c, task['conversation_id'])
        H._write_message(c, 'human:guest', task['owner'], f'Tests: head {HEAD}: 9 passed', conv,
                         'say', {'task': task['id'], 'quiet': True}, None, None)
    assert move(api, task).status_code == 422


@pytest.mark.parametrize('permission', ['owner', 'mover', 'delegate'])
def test_nonparty_person_with_task_edit_rights_counts(api, permission):
    task = ticket(api)
    with api.app.state.store.transaction() as c:
        c.execute("INSERT INTO humans(id,name,email,teams_json) VALUES('editor','Editor','editor@example.test',?)",
                  (json.dumps(['leadership'] if permission == 'mover' else []),))
        if permission == 'owner':
            c.execute("INSERT OR REPLACE INTO registry_metadata VALUES('owner',?)",
                      (json.dumps({'email': 'editor@example.test'}),))
        elif permission == 'delegate':
            c.execute('INSERT INTO task_delegations(task_id,delegate,requested_by,expires) VALUES(?,?,?,?)',
                      (task['id'], 'human:editor', task['requester'], '2099-01-01T00:00:00Z'))
        H.task_comment(c, 'human:editor', task['id'], f'Tests: head {HEAD}: 9 passed', wake=False)
    response = move(api, task)
    assert response.status_code == 200, response.text
