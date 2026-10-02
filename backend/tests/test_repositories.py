"""Repository contracts: migrations, sync, scoped grants and mixed computers."""
import hashlib
import hmac
import json
import uuid

from backend import hubdb as H, repositories as R
from backend.store import Store
from backend.tests.test_github_app import api, gh, auth, connect, runner_token, turn_token, put_extras  # noqa: F401


def put(api, path, body, token='owner-test'):
    response = api.put('/api/v2/' + path, json=body, headers={**auth(token), 'Idempotency-Key': uuid.uuid4().hex})
    assert response.status_code == 200, response.text
    return response.json()


def catalog(api, gh):
    connect(api)
    gh.repositories = [{'full_name': 'Acme/' + name, 'default_branch': 'main'}
                       for name in ('product', 'docs', 'bot-sales', 'emp-cpo')]
    response = api.post('/api/v2/repositories/refresh', headers=auth())
    assert response.status_code == 200, response.text
    return response.json()


def test_sync_bot_repos_setup_overrides_and_unreachable(api, gh):
    gh.setup_files['/repos/Acme/product/contents/tico.json'] = {'setup': 'npm ci'}
    gh.setup_files['/repos/Acme/docs/contents/conductor.json'] = {'scripts': {'setup': 'make setup'}}
    rows = {r['full_name']: r for r in catalog(api, gh)['repositories']}
    assert rows['Acme/bot-sales']['bot_repo'] and rows['Acme/emp-cpo']['bot_repo']
    assert not rows['Acme/product']['bot_repo']
    assert rows['Acme/product']['setup_command'] is None
    assert not any('/contents/' in call[1] for call in gh.calls)
    for name in ('product', 'docs'):
        put(api, 'repositories/Acme/' + name, {'enabled': True})
    rows = {r['full_name']: r for r in api.post('/api/v2/repositories/refresh', headers=auth()).json()['repositories']}
    assert rows['Acme/product']['setup_command'] == 'npm ci'
    assert rows['Acme/docs']['setup_source'] == 'conductor.json'
    updated = put(api, 'repositories/Acme/product', {'enabled': True, 'setup_command': 'make install'})
    assert updated['full_name'] == 'Acme/product' and updated['enabled']
    assert updated['setup_command'] == 'make install' and updated['setup_source'] == 'settings'
    gh.repositories = [r for r in gh.repositories if r['full_name'] != 'Acme/docs']
    response = api.post('/api/v2/repositories/refresh', headers=auth()).json()
    assert response == api.get('/api/v2/repositories', headers=auth('person-test')).json()
    rows = {r['full_name']: r for r in response['repositories']}
    assert not rows['Acme/docs']['reachable']
    assert rows['Acme/product']['setup_command'] == 'make install'
    assert rows['Acme/product']['setup_source'] == 'settings'
    assert api.get('/api/v2/repositories', headers=auth('person-test')).status_code == 200
    assert api.get('/api/v2/bots/cpo/repositories', headers=auth('person-test')).status_code == 200
    assert api.put('/api/v2/repositories/Acme/product', json={'enabled': False}, headers=auth('person-test')).status_code == 403


def test_modes_mixed_scopes_alias_and_default(api, gh):
    catalog(api, gh)
    runner_token(api, 'cpo')
    for name in ('product', 'docs'):
        put(api, 'repositories/Acme/' + name, {'enabled': True})
    data = put(api, 'bots/cpo/repositories', {'mode': 'all', 'all_access': 'read'})
    assert {r['full_name']: r['access'] for r in data['effective']} == {
        'Acme/emp-cpo': 'write', 'Acme/product': 'read', 'Acme/docs': 'read'}
    token = turn_token(api).json()
    assert len(token['tokens']) == 2
    bodies = [r[2] for r in gh.of('/access_tokens')[-2:]]
    assert bodies[0]['repositories'] == ['emp-cpo']
    assert bodies[0]['permissions']['contents'] == 'write'
    assert bodies[1]['repositories'] == ['docs', 'product']
    assert bodies[1]['permissions'] == {'contents': 'read', 'metadata': 'read'}
    specific = api.post('/api/v2/github/token', json={'bot': 'cpo', 'repository': 'Acme/product'}, headers=auth('runner-test'))
    assert specific.status_code == 200 and specific.json()['tokens'][0]['access'] == 'read'
    assert api.post('/api/v2/github/token', json={'bot': 'cpo', 'repository': 'Acme/secret'}, headers=auth('runner-test')).status_code == 403
    put(api, 'bots/cpo/repositories', {'mode': 'chosen', 'chosen': [
        {'full_name': 'Acme/docs', 'access': 'read'}, {'full_name': 'Acme/product', 'access': 'write'}]})
    assert api.get('/api/v2/bots/cpo/github-repos', headers=auth()).json()['repositories'] == ['Acme/product']
    assert put_extras(api, 'cpo', ['legacy']).status_code == 200
    assert api.get('/api/v2/bots/cpo/repositories', headers=auth()).json()['chosen'] == [
        {'full_name': 'Acme/docs', 'access': 'read'}, {'full_name': 'Acme/legacy', 'access': 'write'},
        {'full_name': 'Acme/product', 'access': 'write'}]
    put(api, 'bots/cpo/repositories', {'mode': 'own'})
    assert turn_token(api).json()['repositories'] == ['Acme/emp-cpo']
    put(api, 'repositories/settings', {'new_bot_default': 'all'})
    with api.app_state.store.transaction() as c:
        c.execute("INSERT INTO bots(slug,display_name,created) VALUES('new-test','Sam',?)", (H.now(),))
        c.execute("INSERT INTO bot_config(bot,config_json,team,operator,repo) VALUES('new-test','{}','t','ana','bot-new-test')")
        assert json.loads(c.execute("SELECT config_json FROM bot_config WHERE bot='new-test'").fetchone()[0])['repo_access_mode'] == 'all'


def test_upgrade_migrates_existing_extras_once(api, gh):
    connect(api)
    runner_token(api, 'cpo')
    store = api.app_state.store
    with store.transaction() as c:
        c.execute('DELETE FROM cloud_migrations WHERE version=50')
        c.execute("DELETE FROM registry_metadata WHERE key='repositories-access-migrated'")
        R.save_metadata(c, 'github-extra-repos', {'cpo': ['Acme/product', 'Acme/docs'], 'oldie': ['Acme/archive']})
    Store(store.settings).initialize(seed_market=False)
    with store.transaction() as c:
        data = R.access(c, 'cpo', 'Acme')
        assert data['mode'] == 'chosen'
        assert {r['full_name']: r['access'] for r in data['chosen']} == {'Acme/product': 'write', 'Acme/docs': 'write'}
        assert R.access(c, 'oldie', 'Acme')['mode'] == 'chosen'
        assert R.access(c, 'cmo', 'Acme')['mode'] == 'own'
        assert c.execute('SELECT count(*) FROM repositories WHERE enabled=1').fetchone()[0] == 3
    assert set(turn_token(api).json()['repositories']) == {'Acme/emp-cpo', 'Acme/product', 'Acme/docs'}
    with store.transaction() as c:
        R.set_access(c, 'cpo', R.RepoAccessUpdate(mode='own'), 'Acme', 'human:ana')
        R.migrate(c)
        assert R.access(c, 'cpo', 'Acme')['mode'] == 'own'
        assert c.execute('PRAGMA user_version').fetchone()[0] == len(H.MIGRATIONS)


def test_computer_union_token_and_old_heartbeat(api, gh):
    catalog(api, gh)
    runner_token(api, 'cpo')
    runner_token(api, 'cmo')
    for name in ('product', 'docs'):
        put(api, 'repositories/Acme/' + name, {'enabled': True})
    put(api, 'bots/cpo/repositories', {'mode': 'all', 'all_access': 'read'})
    put(api, 'bots/cmo/repositories', {'mode': 'chosen', 'chosen': [{'full_name': 'Acme/product', 'access': 'write'}]})
    path = '/api/v2/runners/me/repositories'
    response = api.get(path, headers=auth('runner-test'))
    assert response.status_code == 200, response.text
    rows = {r['full_name']: r for r in response.json()['repositories']}
    assert set(rows) == {'Acme/product', 'Acme/docs'}
    assert set(rows['Acme/product']['bots']) == {'cpo', 'cmo'}
    assert rows['Acme/product']['access'] == 'write' and rows['Acme/docs']['access'] == 'read'
    response = api.post(path + '/token', headers=auth('runner-test'))
    assert response.status_code == 200, response.text
    assert gh.of('/access_tokens')[-1][2] == {'repositories': ['docs', 'product'], 'permissions': {'contents': 'read', 'metadata': 'read'}}
    assert api.get(path, headers=auth()).status_code == 403
    body = {'version': '0.2.23', 'platform': 'mac', 'readiness': {}}
    assert api.post('/api/v2/runners/heartbeat', json=body, headers={**auth('runner-test'), 'Idempotency-Key': uuid.uuid4().hex}).status_code == 200
    with api.app_state.store.read() as c:
        assert R.metadata(c, 'computer-repositories:r1')['repositories'] == 'unknown'
    operations = api.get('/api/v2/operations', headers=auth()).json()
    assert next(r for r in operations['computers'] if r['id'] == 'r1')['repositories'] == 'unknown'
    body['repositories'] = [{'full_name': 'Acme/product', 'state': 'cloned', 'size_mb': 12}]
    assert api.post('/api/v2/runners/heartbeat', json=body, headers={**auth('runner-test'), 'Idempotency-Key': uuid.uuid4().hex}).status_code == 200
    with api.app_state.store.read() as c:
        assert R.metadata(c, 'computer-repositories:r1')['repositories'][0]['size_mb'] == 12
    operations = api.get('/api/v2/operations', headers=auth()).json()
    assert next(r for r in operations['computers'] if r['id'] == 'r1')['repositories'][0]['state'] == 'cloned'
    put(api, 'bots/cpo/repositories', {'mode': 'own'})
    put(api, 'bots/cmo/repositories', {'mode': 'own'})
    count = len(gh.of('/access_tokens'))
    assert api.post(path + '/token', headers=auth('runner-test')).json()['token'] is None
    assert len(gh.of('/access_tokens')) == count


def test_installation_webhook_refreshes_with_app_secret(api, gh):
    catalog(api, gh)
    gh.repositories.append({'full_name': 'Acme/new-product', 'default_branch': 'develop'})
    body = json.dumps({'action': 'added', 'installation': {'id': 77}}).encode()
    signature = 'sha256=' + hmac.new(b'whs', body, hashlib.sha256).hexdigest()
    response = api.post('/api/v2/github/webhook', content=body, headers={
        'X-GitHub-Event': 'installation_repositories', 'X-Hub-Signature-256': signature})
    assert response.status_code == 200, response.text
    api.app_state.github_app.repository_worker.join(timeout=5)
    assert 'Acme/new-product' in {r['full_name'] for r in api.get('/api/v2/repositories', headers=auth()).json()['repositories']}


def test_mcp_and_cli_repository_commands_use_routes(api, gh, monkeypatch):
    from clients import hubcli, remotecli
    from backend.tests.test_mcp import call
    catalog(api, gh)
    error, data = call(api, 'hub_repo_list', token='owner-test')
    assert not error and len(data['repositories']) == 4
    error, data = call(api, 'hub_repo_update', {'full_name': 'Acme/product', 'enabled': True}, token='owner-test')
    assert not error and data['enabled']
    error, data = call(api, 'hub_bot_repos_set', {'bot': 'cpo', 'mode': 'chosen', 'chosen': [
        {'full_name': 'Acme/product', 'access': 'read'}]}, token='owner-test')
    assert not error and data['chosen'][0]['access'] == 'read'
    error, data = call(api, 'hub_bot_repos_get', {'bot': 'cpo'}, token='owner-test')
    assert not error and data['mode'] == 'chosen'

    class Client:
        def __init__(self, *args, **kwargs):
            pass

        def get(self, path):
            if path == 'me':
                return {'role': 'owner'}
            return {'path': path}

        def call(self, method, path, body=None, **kwargs):
            return {'method': method, 'path': path, 'body': body}

    monkeypatch.setattr(remotecli, 'Client', Client)
    monkeypatch.setenv('HUB_API_URL', 'https://example.com')
    def run(*args):
        return remotecli.run(hubcli.parser().parse_args(args))
    assert run('repo', 'list')['path'] == 'repositories'
    assert run('repo', 'tick', 'example/product')['body'] == {'enabled': True}
    assert run('repo', 'untick', 'example/product')['body'] == {'enabled': False}
    assert run('bot', 'repos', 'sales')['path'] == 'bots/sales/repositories'
    assert run('bot', 'repos', 'sales', '--all')['body'] == {'mode': 'all'}
    assert run('bot', 'repos', 'sales', '--own')['body'] == {'mode': 'own'}
    assert run('bot', 'repos', 'sales', '--chosen', 'example/docs:read', 'example/product')['body'] == {
        'mode': 'chosen', 'chosen': [{'full_name': 'example/docs', 'access': 'read'}, {'full_name': 'example/product', 'access': 'write'}]}


def test_chosen_unticked_grants_survive_settings_saves_and_reticking(api, gh):
    catalog(api, gh)
    put(api, 'repositories/Acme/docs', {'enabled': True})
    chosen = [{'full_name': 'Acme/docs', 'access': 'read'}]
    put(api, 'bots/cpo/repositories', {'mode': 'chosen', 'chosen': chosen})
    put(api, 'repositories/Acme/docs', {'enabled': False})
    for mode in ('own', 'all', 'chosen'):
        response = put(api, 'bots/cpo/repositories', {'mode': mode, 'all_access': 'read', 'chosen': chosen})
        assert response['chosen'] == chosen
        assert response['effective'] == [{'full_name': 'Acme/emp-cpo', 'access': 'write'}]
    put(api, 'repositories/Acme/docs', {'enabled': True})
    assert chosen[0] in api.get('/api/v2/bots/cpo/repositories', headers=auth()).json()['effective']
    assert api.put('/api/v2/bots/cpo/repositories', json={'mode': 'chosen', 'chosen': [
        {'full_name': 'Acme/unlisted', 'access': 'read'}]}, headers=auth()).status_code == 422



def test_computer_release_is_separate_from_runner_software(api):
    runner_token(api, 'cpo')
    with api.app_state.store.transaction() as c:
        from backend import runner_versions
        from backend.models import Heartbeat
        runner_versions.record(c, 'r1', Heartbeat(version='0.5.4', platform='test', release='0.3.2'))
        c.execute("UPDATE runners SET version='0.5.4' WHERE id='r1'")
    for path in ('computers', 'operations'):
        data = api.get('/api/v2/' + path, headers=auth()).json()
        computer = next(r for r in data['computers'] if r['id'] == 'r1')
        assert computer['release'] == '0.3.2' and computer['version'] == '0.5.4'
def test_missing_repo_does_not_take_own_or_computer_tokens_down(api, gh):
    from backend.tests.test_github_app import token_health
    catalog(api, gh)
    runner_token(api, 'cpo')
    for name in ('product', 'docs'):
        put(api, 'repositories/Acme/' + name, {'enabled': True})
    put(api, 'bots/cpo/repositories', {'mode': 'all'})
    gh.missing.add('docs')
    token = turn_token(api)
    assert token.status_code == 200, token.text
    assert set(token.json()['repositories']) == {'Acme/emp-cpo', 'Acme/product'}
    assert gh.of('/access_tokens')[-1][2]['repositories'] == ['emp-cpo', 'product']
    assert token_health(api)
    with api.app_state.store.read() as c:
        detail = json.loads(c.execute("SELECT detail_json FROM service_health WHERE service='github:token'").fetchone()[0])
        assert 'Acme/docs is not reachable' in detail['message']
    calls = len(gh.calls)
    assert turn_token(api).status_code == 200
    assert len(gh.calls) == calls  # confirmed missing names do not trigger repeated GitHub diagnosis
    effective = api.get('/api/v2/bots/cpo/repositories', headers=auth()).json()['effective']
    assert 'Acme/docs' not in {r['full_name'] for r in effective}
    # A newly missing repo during a computer request gets the same scoped retry.
    gh.missing.add('product')
    response = api.post('/api/v2/runners/me/repositories/token', headers=auth('runner-test'))
    assert response.status_code == 200, response.text
    assert response.json()['repositories'] == [] and response.json()['token'] is None
    assert turn_token(api).json()['repositories'] == ['Acme/emp-cpo']
    assert token_health(api)  # a successful own-repo token must not turn missing grants green


def test_all_excludes_bot_repositories_but_explicit_chosen_keeps_them(api, gh):
    catalog(api, gh)
    runner_token(api, 'cpo')
    put(api, 'repositories/Acme/bot-sales', {'enabled': True})
    data = put(api, 'bots/cpo/repositories', {'mode': 'all'})
    assert data['effective'] == [{'full_name': 'Acme/emp-cpo', 'access': 'write'}]
    assert api.get('/api/v2/runners/me/repositories', headers=auth('runner-test')).json()['repositories'] == []
    put(api, 'bots/cpo/repositories', {'mode': 'chosen', 'chosen': [{'full_name': 'Acme/bot-sales'}]})
    assert 'Acme/bot-sales' in turn_token(api).json()['repositories']


def test_member_manager_cannot_retick_team_repos_or_choose_bot_instructions(api, gh):
    catalog(api, gh)
    put(api, 'bots/cpo/repositories', {'mode': 'chosen', 'chosen': []})
    with api.app_state.store.transaction() as c:
        person = api.app_state.store.settings.test_identities['person-test'].actor.split(':', 1)[1]
        c.execute("UPDATE bot_config SET operator=? WHERE bot='cpo'", (person,))
    assert api.get('/api/v2/bots/cpo/github-repos', headers=auth('person-test')).status_code == 200
    refused = put_extras(api, 'cpo', ['docs'], 'person-test')
    assert refused.status_code == 422 and 'tick it' in refused.text
    put(api, 'repositories/Acme/docs', {'enabled': True})
    assert put_extras(api, 'cpo', ['docs'], 'person-test').status_code == 200
    put(api, 'repositories/Acme/bot-sales', {'enabled': True})
    assert put_extras(api, 'cpo', ['bot-sales'], 'person-test').status_code == 403
    with api.app_state.store.read() as c:
        assert c.execute("SELECT enabled FROM repositories WHERE full_name='Acme/docs'").fetchone()[0] == 1
        assert c.execute("SELECT enabled FROM repositories WHERE full_name='Acme/product'").fetchone()[0] == 0


def test_legacy_round_trip_preserves_modes_and_read_grants(api, gh):
    catalog(api, gh)
    chosen = [{'full_name': 'Acme/docs', 'access': 'read'}]
    for mode in ('own', 'all', 'chosen'):
        put(api, 'bots/cpo/repositories', {'mode': mode, 'all_access': 'read', 'chosen': chosen})
        old = api.get('/api/v2/bots/cpo/github-repos', headers=auth()).json()['repositories']
        assert put_extras(api, 'cpo', old).status_code == 200
        result = api.get('/api/v2/bots/cpo/repositories', headers=auth()).json()
        assert (result['mode'], result['chosen'], result['all_access']) == (mode, chosen, 'read')
        if mode != 'chosen':
            assert put_extras(api, 'cpo', ['product']).status_code == 409


def test_not_installed_or_transient_sync_keeps_reachability_and_retries_soon(api, gh, monkeypatch):
    from unittest.mock import Mock
    catalog(api, gh)
    service = api.app_state.github_app
    with api.app_state.store.transaction() as c:
        c.execute("DELETE FROM registry_metadata WHERE key='repositories-synced'")
        R.save_metadata(c, 'repositories-reachability-verified', {})
        c.execute('UPDATE repositories SET reachable=0')  # bad flags left by an older server
    put(api, 'repositories/Acme/docs', {'enabled': True})
    put(api, 'bots/cpo/repositories', {'mode': 'all'})
    monkeypatch.setattr(service, 'installation', lambda **kw: None)
    assert R.sync(service) == 'not_installed'
    with api.app_state.store.read() as c:
        assert 'Acme/docs' in {r['full_name'] for r in R.access(c, 'cpo', 'Acme')['effective']}
        assert not R.metadata(c, 'repositories-synced')
    R.daily(service)
    service.repository_worker.join(timeout=5)
    attempted = service.repository_sync_attempt
    assert attempted > 0
    worker = Mock()
    monkeypatch.setattr(R, 'queue_sync', worker)
    monkeypatch.setattr(R.time, 'time', lambda: attempted + 299)
    R.daily(service)
    assert not worker.called
    monkeypatch.setattr(R.time, 'time', lambda: attempted + 301)
    R.daily(service)
    worker.assert_called_once_with(service)


def test_webhook_acknowledges_slow_sync_and_coalesces_burst(api, gh, monkeypatch):
    import threading
    catalog(api, gh)
    entered, release = threading.Event(), threading.Event()
    calls = []
    def slow(service):
        calls.append(1)
        entered.set()
        assert release.wait(5)
        return 'synced'
    monkeypatch.setattr(R, 'sync', slow)
    body = json.dumps({'action': 'added', 'installation': {'id': 77}}).encode()
    signature = 'sha256=' + hmac.new(b'whs', body, hashlib.sha256).hexdigest()
    try:
        for _ in range(4):
            response = api.post('/api/v2/github/webhook', content=body, headers={
                'X-GitHub-Event': 'installation_repositories', 'X-Hub-Signature-256': signature})
            assert response.status_code == 200
            assert entered.wait(1)
        assert len(calls) == 1
        assert api.get('/api/v2/repositories', headers=auth()).status_code == 200
        worker = api.app_state.github_app.repository_worker
    finally:
        release.set()
        worker.join(timeout=5)
    assert len(calls) == 2


def test_setup_error_keeps_prior_command_and_other_repositories_sync(api, gh, monkeypatch):
    import httpx
    catalog(api, gh)
    for name in ('product', 'docs'):
        put(api, 'repositories/Acme/' + name, {'enabled': True})
    gh.setup_files['/repos/Acme/product/contents/tico.json'] = {'setup': 'make first'}
    R.sync(api.app_state.github_app)
    original = api.app_state.github_app._call
    def failing(method, path, **kw):
        if path == '/repos/Acme/product/contents/tico.json':
            return httpx.Response(503)
        return original(method, path, **kw)
    monkeypatch.setattr(api.app_state.github_app, '_call', failing)
    gh.setup_files['/repos/Acme/docs/contents/tico.json'] = {'setup': 'make docs'}
    R.sync(api.app_state.github_app)
    rows = {r['full_name']: r for r in api.get('/api/v2/repositories', headers=auth()).json()['repositories']}
    assert rows['Acme/product']['setup_command'] == 'make first'
    assert rows['Acme/docs']['setup_command'] == 'make docs'


def test_built_in_repository_grants_are_owner_only_and_hidden_bots_stay_hidden(api, gh):
    from backend.tests.test_api import restrict
    catalog(api, gh)
    who = api.app_state.store.settings.test_identities['person-test']
    api.app_state.auth.bot_admins.add(who.email.lower())
    response = api.put('/api/v2/bots/botops/repositories', json={'mode': 'all'}, headers=auth('person-test'))
    assert response.status_code == 403 and 'Owner' in response.text
    api.app_state.auth.bot_admins.remove(who.email.lower())
    with api.app_state.store.transaction() as c:
        restrict(c, 'cpo', people=[])
    assert api.get('/api/v2/bots/cpo/repositories', headers=auth('person-test')).status_code == 403
    assert api.get('/api/v2/bots/cpo/repositories', headers=auth()).status_code == 200


def test_heartbeat_keeps_omitted_clone_report_and_revoke_cleans_it(api, gh):
    catalog(api, gh)
    runner_token(api, 'cpo')
    body = {'version': '0.3.1', 'platform': 'mac', 'readiness': {},
            'repositories': [{'full_name': 'Acme/product', 'state': 'cloned', 'size_mb': 12}]}
    path = '/api/v2/runners/heartbeat'
    assert api.post(path, json=body, headers={**auth('runner-test'), 'Idempotency-Key': uuid.uuid4().hex}).status_code == 200
    del body['repositories']
    assert api.post(path, json=body, headers={**auth('runner-test'), 'Idempotency-Key': uuid.uuid4().hex}).status_code == 200
    with api.app_state.store.read() as c:
        assert R.metadata(c, 'computer-repositories:r1')['repositories'][0]['state'] == 'cloned'
    assert api.post('/api/v2/runners/r1/revoke', json={}, headers={**auth(), 'Idempotency-Key': uuid.uuid4().hex}).status_code == 200
    with api.app_state.store.read() as c:
        assert not R.metadata(c, 'computer-repositories:r1')


def test_transient_background_failure_preserves_flags_and_uses_short_backoff(api, gh, monkeypatch):
    from backend.store import Problem
    from unittest.mock import Mock
    catalog(api, gh)
    service = api.app_state.github_app
    with service.store.transaction() as c:
        c.execute("DELETE FROM registry_metadata WHERE key='repositories-synced'")
    def unavailable(**kw):
        raise Problem('github_unreachable', 'GitHub could not be reached', 502)
    monkeypatch.setattr(service, 'installation', unavailable)
    R.daily(service)
    service.repository_worker.join(timeout=5)
    attempted = service.repository_sync_attempt
    assert service.repository_sync_failures == 1
    with service.store.read() as c:
        assert all(r[0] for r in c.execute('SELECT reachable FROM repositories'))
        assert not R.metadata(c, 'repositories-synced')
    queued = Mock()
    monkeypatch.setattr(R, 'queue_sync', queued)
    monkeypatch.setattr(R.time, 'time', lambda: attempted + 301)
    R.daily(service)
    queued.assert_called_once_with(service)
    queued.reset_mock()
    service.repository_sync_failures = 2
    R.daily(service)
    assert not queued.called
    monkeypatch.setattr(R.time, 'time', lambda: attempted + 3601)
    R.daily(service)
    queued.assert_called_once_with(service)


def test_missing_marks_expire_and_success_clears_them(api, gh, monkeypatch):
    catalog(api, gh)
    runner_token(api, 'cpo')
    put(api, 'repositories/Acme/docs', {'enabled': True})
    put(api, 'bots/cpo/repositories', {'mode': 'all'})
    gh.missing.add('docs')
    assert turn_token(api).status_code == 200
    with api.app_state.store.read() as c:
        stamp = R.metadata(c, 'repositories-confirmed-missing')['acme/docs']
    gh.missing.remove('docs')
    monkeypatch.setattr(R.time, 'time', lambda: stamp + 301)
    assert 'Acme/docs' in turn_token(api).json()['repositories']
    with api.app_state.store.read() as c:
        assert not R.metadata(c, 'repositories-confirmed-missing')
        assert c.execute("SELECT reachable FROM repositories WHERE full_name='Acme/docs'").fetchone()[0]


def test_own_repo_is_retried_without_refresh_and_create_clears_mark(api, gh):
    connect(api, administration='true')
    runner_token(api, 'cpo')
    gh.missing.add('emp-cpo')
    assert turn_token(api).status_code == 409
    gh.missing.remove('emp-cpo')
    assert turn_token(api).status_code == 200
    with api.app_state.store.read() as c:
        assert not R.metadata(c, 'repositories-confirmed-missing')
    service = api.app_state.github_app
    for empty in (True, False):
        with service.store.transaction() as c:
            R.save_metadata(c, 'repositories-confirmed-missing', {'acme/bot-sample': R.time.time()})
            c.execute("INSERT OR REPLACE INTO repositories(id,full_name,reachable,updated) VALUES('sample','Acme/bot-sample',0,?)", (H.now(),))
        assert service.create_repo('sample', 'example/template', empty=empty)['repository'] == 'Acme/bot-sample'
        with service.store.read() as c:
            assert not R.metadata(c, 'repositories-confirmed-missing')
            assert c.execute("SELECT reachable FROM repositories WHERE id='sample'").fetchone()[0]


def test_malformed_setup_preserves_command_but_removed_files_clear_it(api, gh):
    import base64
    import httpx
    catalog(api, gh)
    put(api, 'repositories/Acme/product', {'enabled': True})
    gh.setup_files['/repos/Acme/product/contents/tico.json'] = {'setup': 'make first'}
    service = api.app_state.github_app
    R.sync(service)
    original = service._call
    def malformed(method, path, **kwargs):
        if path == '/repos/Acme/product/contents/tico.json':
            return httpx.Response(200, json={'content': base64.b64encode(b'{broken').decode()})
        return original(method, path, **kwargs)
    service._call = malformed
    R.sync(service)
    with service.store.read() as c:
        assert c.execute("SELECT setup_command FROM repositories WHERE full_name='Acme/product'").fetchone()[0] == 'make first'
    service._call = original
    gh.setup_files.clear()
    R.sync(service)
    with service.store.read() as c:
        assert c.execute("SELECT setup_command FROM repositories WHERE full_name='Acme/product'").fetchone()[0] is None


def test_daily_does_not_queue_followup_and_shutdown_stops_worker(api, gh, monkeypatch):
    import threading
    catalog(api, gh)
    service = api.app_state.github_app
    entered, release = threading.Event(), threading.Event()
    calls = []
    def slow(service):
        calls.append(1)
        entered.set()
        assert release.wait(timeout=5)
        return 'not_installed'
    monkeypatch.setattr(R, 'sync', slow)
    with service.store.transaction() as c:
        c.execute("DELETE FROM registry_metadata WHERE key='repositories-synced'")
    R.daily(service)
    assert entered.wait(timeout=5)
    try:
        for _ in range(5):
            R.daily(service)
        assert not service.repository_sync_wanted
        R.queue_sync(service, refresh=True)
        service.repository_stop.set()
    finally:
        release.set()
        R.stop_sync(service)
    assert not service.repository_worker.is_alive()
    assert calls == [1]
    assert not service.repository_running


def test_missing_own_repo_does_not_repeat_probes_for_other_grants(api, gh, monkeypatch):
    catalog(api, gh)
    runner_token(api, 'cpo')
    for name in ('product', 'docs'):
        put(api, 'repositories/Acme/' + name, {'enabled': True})
    put(api, 'bots/cpo/repositories', {'mode': 'all'})
    gh.missing.add('emp-cpo')
    first = turn_token(api)
    assert first.status_code == 200
    assert set(first.json()['repositories']) == {'Acme/product', 'Acme/docs'}
    probe_count = len([c for c in gh.calls if c[1].count('/') == 3 and c[1].startswith('/repos/')])
    with api.app_state.store.read() as c:
        stamp = R.metadata(c, 'repositories-confirmed-missing')['acme/emp-cpo']
    for _ in range(3):
        assert turn_token(api).status_code == 200
    assert len([c for c in gh.calls if c[1].count('/') == 3 and c[1].startswith('/repos/')]) == probe_count
    with api.app_state.store.read() as c:
        assert R.metadata(c, 'repositories-confirmed-missing')['acme/emp-cpo'] == stamp
    gh.missing.remove('emp-cpo')
    assert 'Acme/emp-cpo' in turn_token(api).json()['repositories']


def test_legacy_changes_preserve_grants_and_cannot_upgrade_bot_repo(api, gh):
    import pytest
    from backend.store import Problem
    catalog(api, gh)
    for name in ('bot-sales', 'docs', 'product'):
        put(api, 'repositories/Acme/' + name, {'enabled': True})
    chosen = [{'full_name': 'Acme/bot-sales', 'access': 'read'}, {'full_name': 'Acme/docs', 'access': 'read'}]
    put(api, 'bots/cpo/repositories', {'mode': 'chosen', 'chosen': chosen})
    assert put_extras(api, 'cpo', ['bot-sales', 'product']).status_code == 200
    assert api.get('/api/v2/bots/cpo/repositories', headers=auth()).json()['chosen'] == chosen + [{'full_name': 'Acme/product', 'access': 'write'}]
    with api.app_state.store.transaction() as c:
        with pytest.raises(Problem) as caught:
            R.set_access(c, 'cpo', R.RepoAccessUpdate(mode='chosen', chosen=[R.Grant(full_name='Acme/bot-sales')]),
                         'Acme', 'human:sam', legacy=True, team_list=False)
        assert caught.value.status == 403
        assert {r['full_name']: r['access'] for r in R.access(c, 'cpo', 'Acme')['chosen']} == {
            'Acme/bot-sales': 'read', 'Acme/docs': 'read', 'Acme/product': 'write'}


def test_setup_command_limit_applies_to_settings_and_repo_files(api, gh):
    catalog(api, gh)
    put(api, 'repositories/Acme/product', {'enabled': True})
    for command in ('x' * 4097, 'é' * 2049, 'a\n' * 2049, 'a\0' * 2049):
        response = api.put('/api/v2/repositories/Acme/product', json={'setup_command': command}, headers=auth())
        assert response.status_code == 422
    put(api, 'repositories/Acme/product', {'setup_command': 'a\n' * 2048})
    # A new oversize file cannot replace the last usable command.
    with api.app_state.store.transaction() as c:
        c.execute("UPDATE repositories SET setup_command='make previous',setup_source='tico.json' WHERE full_name='Acme/product'")
    gh.setup_files['/repos/Acme/product/contents/tico.json'] = {'setup': 'x' * 4097}
    R.sync(api.app_state.github_app)
    with api.app_state.store.read() as c:
        assert c.execute("SELECT setup_command FROM repositories WHERE full_name='Acme/product'").fetchone()[0] == 'make previous'
