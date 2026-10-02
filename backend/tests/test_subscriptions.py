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
    assert claim(api, r)['profile'] == 'engineering'
    # A complete replacement report removes profiles; a missing report from an old runner doesn't.
    post(api, 'runners/heartbeat', {**body, 'profiles': []}, token=r['token'])
    sub = get(api, 'bots/ops/subscription')
    assert sub['signed_in'] is False and sub['problem'] == 'profile engineering not on this computer'
    health = get(api, 'health')
    assert any(check['id'] == 'subscriptions' for check in health['checks'])
    ready(api, r, ['ops'])
    assert get(api, 'bots/ops/subscription')['signed_in'] is None


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
