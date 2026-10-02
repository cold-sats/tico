"""Server defaults stay independent of computer-local provider credentials."""
import json

from backend.tests.test_api import api, assign, claim, get, headers, post, put, ready, runner  # noqa: F401


def group_assignment(api, target, profile):
    return put(api, 'subscriptions', {'scope': 'group', 'target': target, 'profile': profile})


def group_tree(api):
    parent = post(api, 'groups', {'name': 'Engineering'})
    child = post(api, 'groups', {'name': 'Product', 'parent': parent['id'], 'add': {'bots': ['ops']}})
    return parent['id'], child['id']


def test_resolution_bot_nearest_group_then_computer(api):
    parent, child = group_tree(api)
    assert get(api, 'bots/ops/subscription')['source'] == 'computer'
    group_assignment(api, parent, 'one')
    assert get(api, 'bots/ops/subscription')['source'] == 'group:Engineering'
    group_assignment(api, child, 'two')
    assert get(api, 'bots/ops/subscription')['profile'] == 'two'
    put(api, 'subscriptions', {'scope': 'bot', 'target': 'ops', 'profile': 'three'})
    assert get(api, 'bots/ops/subscription')['source'] == 'bot'
    put(api, 'subscriptions', {'scope': 'bot', 'target': 'ops', 'profile': None})
    assert get(api, 'bots/ops/subscription')['profile'] == 'two'
    group_assignment(api, child, None)
    assert get(api, 'bots/ops/subscription')['profile'] == 'one'
    group_assignment(api, parent, None)
    assert get(api, 'bots/ops/subscription')['profile'] is None


def test_heartbeat_profiles_claim_and_old_computer(api):
    r = runner(api)
    assign(api, r, 'ops')
    put(api, 'subscriptions', {'scope': 'bot', 'target': 'ops', 'profile': 'engineering'})
    ready(api, r, ['ops'])
    assert get(api, 'bots/ops/subscription')['signed_in'] is None
    assert get(api, 'bots/ops/subscription')['problem'] == 'Update Test Mac to use subscriptions'
    post(api, 'chat/ops', {'text': 'Wait for the assigned subscription'})
    assert claim(api, r) is None
    body = {'version': 'test', 'platform': 'test', 'readiness': {'ops': True},
            'profiles': [{'name': 'engineering', 'runtimes': {'fake': {'signed_in': True}}}]}
    post(api, 'runners/heartbeat', body, token=r['token'])
    listed = get(api, 'subscriptions')['profiles_by_computer']
    assert listed[0]['profiles'] == body['profiles']
    sub = get(api, 'bots/ops/subscription')
    assert sub['signed_in'] is True and sub['computer']['runner_id'] == r['runner_id']
    assignment = get(api, 'runners/assignments', r['token'])[0]
    assert assignment['profile'] == 'engineering'
    post(api, 'chat/ops', {'text': 'Check the current delivery'})
    work = claim(api, r)
    assert work['profile'] == 'engineering'
    post(api, 'attempts/' + work['id'] + '/started', {'thread_id': 'thread'}, token=r['token'])
    post(api, 'attempts/' + work['id'] + '/complete', {'outcome': 'completed', 'last_seq': 0}, token=r['token'])
    post(api, 'chat/ops', {'text': 'Wait while this subscription is unavailable'})
    # A complete replacement report removes profiles; a missing report from an old runner doesn't.
    post(api, 'runners/heartbeat', {**body, 'profiles': []}, token=r['token'])
    sub = get(api, 'bots/ops/subscription')
    assert sub['signed_in'] is False and sub['problem'] == "Subscription engineering isn't on Test Mac"
    assert claim(api, r) is None
    signed_out = {**body, 'profiles': [{'name': 'engineering', 'runtimes': {'fake': {'signed_in': False}}}]}
    post(api, 'runners/heartbeat', signed_out, token=r['token'])
    assert claim(api, r) is None
    assert get(api, 'bots/ops/subscription')['problem'] == "Subscription engineering isn't signed in on Test Mac"
    health = get(api, 'health')
    assert any(check['id'] == 'subscriptions' for check in health['checks'])
    ready(api, r, ['ops'])
    assert get(api, 'bots/ops/subscription')['signed_in'] is None
    assert get(api, 'bots/ops/subscription')['problem'] == 'Update Test Mac to use subscriptions'


def test_assignment_permissions_and_named_login(api):
    parent, _ = group_tree(api)
    put(api, 'subscriptions', {'scope': 'group', 'target': parent, 'profile': 'one'}, token='cara-test', expected=403)
    put(api, 'subscriptions', {'scope': 'bot', 'target': 'ops', 'profile': 'one'}, token='cara-test', expected=403)
    put(api, 'subscriptions', {'scope': 'bot', 'target': 'missing', 'profile': 'one'}, expected=404)
    r = runner(api)
    ready(api, r, [])
    login = post(api, f"runners/{r['runner_id']}/logins", {'runtime': 'codex', 'profile': 'engineering'})
    assert login['profile'] == 'engineering'
    pending = get(api, 'runner-logins', r['token'])['logins']
    assert pending[0]['profile'] == 'engineering'


def test_manager_template_starts_with_all_read(api):
    from pathlib import Path
    api.app.state.store.settings.catalog_dir = Path(__file__).resolve().parents[2] / 'templates/catalog'
    post(api, 'bots', {'slug': 'engineering-manager', 'display_name': 'Engineering Manager',
                      'template': 'engineering-manager', 'model': 'hermes-profile'})
    with api.app.state.store.read() as c:
        config = json.loads(c.execute("SELECT config_json FROM bot_config WHERE bot='engineering-manager'").fetchone()[0])
    assert config['repo_access_mode'] == 'all' and config['repo_all_access'] == 'read'


def test_botops_assignment_and_signin_use_requester_rights_by_default():
    from backend.botops_act import default_delegable
    assert default_delegable('PUT', 'subscriptions')
    assert default_delegable('POST', 'runners/computer-a/logins', {'runtime': 'codex', 'profile': 'engineering'})
    assert default_delegable('GET', 'runners/computer-a/logins/login-a')
    assert not default_delegable('GET', 'runner-logins')


def test_computer_default_is_reported_and_deleted_groups_lose_assignment(api):
    r = runner(api)
    assign(api, r, 'ops')
    post(api, 'runners/heartbeat', {'version': 'test', 'platform': 'test', 'readiness': {
        'schema_version': 1, 'bots': {'ops': {'ready': True, 'profile': 'local', 'sign_in': 'ready'}}}}, token=r['token'])
    sub = get(api, 'bots/ops/subscription')
    assert sub['source'] == 'computer' and sub['profile'] == 'local' and sub['signed_in'] is True
    parent, _ = group_tree(api)
    group_assignment(api, parent, 'engineering')
    response = api.delete('/api/v2/groups/' + parent, headers=headers())
    assert response.status_code == 200, response.text
    assert not get(api, 'subscriptions')['assignments']


def test_subscriptions_migrations_are_repeatable_and_follow_repositories(api):
    from backend import hubdb as H
    assert H.MIGRATIONS[-1] == H.SUBSCRIPTIONS_SCHEMA
    with api.app.state.store.transaction() as c:
        H._apply(c, H.SUBSCRIPTIONS_SCHEMA)
        assert c.execute('SELECT 1 FROM cloud_migrations WHERE version=52').fetchone()
        assert c.execute('PRAGMA user_version').fetchone()[0] == len(H.MIGRATIONS)


def test_member_template_keeps_team_repository_default(api):
    from pathlib import Path
    api.app.state.store.settings.catalog_dir = Path(__file__).resolve().parents[2] / 'templates/catalog'
    post(api, 'bots', {'slug': 'member-manager', 'display_name': 'Engineering Manager',
                      'template': 'engineering-manager', 'model': 'hermes-profile'}, token='cara-test')
    with api.app.state.store.read() as c:
        config = json.loads(c.execute("SELECT config_json FROM bot_config WHERE bot='member-manager'").fetchone()[0])
    assert config['repo_access_mode'] == 'own'


def test_member_coowner_cannot_override_subscription(api):
    post(api, 'bots/cpo/owners', {'owners': ['cara'], 'expected_revision': 1})
    put(api, 'subscriptions', {'scope': 'bot', 'target': 'cpo', 'profile': 'one'}, token='cara-test', expected=403)


def test_bad_profiles_do_not_reject_heartbeat_and_unchanged_reports_do_not_write(api):
    r = runner(api)
    body = {'version': 'test', 'platform': 'test', 'readiness': {}, 'profiles': [
        {'name': 'Acme_Main'}, {'name': 'a' * 81}, {'name': 'valid', 'runtimes': {}}]}
    post(api, 'runners/heartbeat', body, token=r['token'])
    assert get(api, 'subscriptions')['profiles_by_computer'][0]['profiles'] == [{'name': 'valid', 'runtimes': {}}]
    from backend.subscriptions import record
    with api.app.state.store.transaction() as c:
        before = c.total_changes
        record(c, r['runner_id'], body['profiles'])
        assert c.total_changes == before


def test_subscription_computers_use_computer_visibility(api):
    r = runner(api)
    with api.app.state.store.transaction() as c:
        c.execute('UPDATE runners SET accepts_member_bots=0 WHERE id=?', (r['runner_id'],))
    assert get(api, 'subscriptions', 'cara-test')['profiles_by_computer'] == []
    assert get(api, 'computers', 'cara-test')['computers'] == []
    assign(api, r, 'ops')
    ready(api, r, ['ops'])
    post(api, 'chat/ops', {'text': 'Inspect subscriptions'})
    token = claim(api, r)['token']
    assert [row['runner_id'] for row in get(api, 'subscriptions', token)['profiles_by_computer']] == [r['runner_id']]
    with api.app.state.store.transaction() as c:
        c.execute("INSERT INTO subscription_assignments VALUES('bot','missing','one',NULL,NULL)")
    assert not get(api, 'subscriptions')['assignments']


def test_computer_operator_can_assign_and_member_sees_own_subscription_problem(api):
    from backend.tests.test_api import as_member
    as_member(api, 'ben@acme.example')
    r = runner(api, operator='ben', label='Member Computer')
    assign(api, r, 'cpo')
    put(api, 'subscriptions', {'scope': 'bot', 'target': 'cpo', 'profile': 'one'}, token='ben-test')
    ready(api, r, ['cpo'])
    health = get(api, 'health', 'ben-test')
    check = next(x for x in health['checks'] if x['id'] == 'subscriptions')
    assert 'cpo: Update Member Computer to use subscriptions' in check['summary']
    put(api, 'subscriptions', {'scope': 'bot', 'target': 'cpo', 'profile': '../bad'}, expected=422)


def test_actual_profile_is_kept_with_completion_and_usage(api):
    r = runner(api)
    assign(api, r, 'ops')
    ready(api, r, ['ops'])
    post(api, 'chat/ops', {'text': 'Record the actual subscription'})
    work = claim(api, r)
    post(api, 'attempts/' + work['id'] + '/started', {'thread_id': 'thread'}, token=r['token'])
    post(api, 'attempts/' + work['id'] + '/complete', {'outcome': 'completed', 'last_seq': 0,
         'profile_used': 'local', 'usage': {'input_tokens': 1, 'runtime': 'fake',
                                                   'profile_used': 'local'}}, token=r['token'])
    with api.app.state.store.read() as c:
        result = json.loads(c.execute('SELECT result_json FROM attempts WHERE id=?', (work['id'],)).fetchone()[0])
    assert result['profile_used'] == result['usage']['profile_used'] == 'local'


def test_bot_computer_visibility_only_restricts_subscriptions(api):
    own, shared = runner(api), runner(api, label='Shared Computer')
    assign(api, own, 'ops')
    ready(api, own, ['ops'])
    post(api, 'chat/ops', {'text': 'Inspect computers'})
    token = claim(api, own)['token']
    assert {row['id'] for row in get(api, 'computers', token)['computers']} == {own['runner_id'], shared['runner_id']}
    assert [row['runner_id'] for row in get(api, 'subscriptions', token)['profiles_by_computer']] == [own['runner_id']]
    assert {row['id'] for row in get(api, 'fleet/check')['computers']} == {own['runner_id'], shared['runner_id']}


def test_server_rejection_blocks_only_matching_profile(api):
    from backend.execution import Execution
    r = runner(api)
    body = {'version': 'test', 'platform': 'test', 'readiness': {'schema_version': 1,
        'runtimes': {'codex': {'installed': True, 'authenticated': 'ready'}},
        'bots': {'ops': {'ready': True, 'runtime': 'codex', 'profile': 'one'},
                 'cpo': {'ready': True, 'runtime': 'codex', 'profile': 'two'}}}}
    post(api, 'runners/heartbeat', body, token=r['token'])
    with api.app.state.store.transaction() as c:
        Execution.mark_rejected(c, r['runner_id'], 'codex', 'Unauthorized', 'one')
        report = json.loads(c.execute('SELECT readiness_json FROM runners WHERE id=?', (r['runner_id'],)).fetchone()[0])
    assert report['bots']['ops']['ready'] is False
    assert report['bots']['cpo']['ready'] is True
    assert report['runtimes']['codex']['authenticated'] == 'ready'
