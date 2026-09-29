import json
import os

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from backend.credentials import CredentialCipher
from backend.store import H
from backend.tests.test_api import api,post,get,runner,assign,ready,claim,headers


class FakeKMS:
    def __init__(self): self.key=os.urandom(32)
    def generate_data_key(self,**kwargs):
        assert kwargs['EncryptionContext']=={'application':'tico-credentials'}
        key=os.urandom(32);nonce=os.urandom(12)
        return {'Plaintext':key,'CiphertextBlob':nonce+AESGCM(self.key).encrypt(nonce,key,b'kms')}
    def decrypt(self,**kwargs):
        blob=kwargs['CiphertextBlob']
        return {'Plaintext':AESGCM(self.key).decrypt(blob[:12],blob[12:],b'kms')}


def setup(api):
    api.app.state.store.settings.credential_kms_key='test-key'
    api.app.state.store.settings.credential_admins=('ana@acme.example','ben@acme.example')
    api.app.state.vault.cipher=CredentialCipher('test-key',FakeKMS())


def create(api,**kwargs):
    return post(api,'credentials',{'name':'PostHog','secret':'phx-synthetic-private-987654','env':'POSTHOG_API_KEY',**kwargs})


def test_ciphertext_only_and_authorizers_and_validation_redaction(api):
    setup(api)
    row=create(api)
    assert row['preview']=='phx…654' and row['stored']
    assert 'synthetic-private' not in json.dumps(get(api,'credentials'))
    assert get(api,'credentials','ben-test')['can_manage']
    post(api,'credentials',{'name':'No','secret':'secret'},'cara-test',expected=403)
    get(api,'credentials','cara-test',expected=403)
    secret='  space-sensitive-password  '
    pw=create(api,name='Password',kind='password',username='person@acme.example',secret=secret)
    assert pw['preview']=='••••••'
    assert post(api,f"credentials/{pw['id']}/reveal",{})['value']==secret
    with api.app.state.store.read() as c:
        for table in ('credentials','idempotency','events'):
            dump=str([tuple(r) for r in c.execute(f'SELECT * FROM {table}')])
            assert secret not in dump and 'phx-synthetic-private-987654' not in dump
        data=c.execute('SELECT ciphertext,nonce FROM credentials WHERE id=?',(row['id'],)).fetchone()
        assert isinstance(data['ciphertext'],bytes) and len(data['nonce'])==12
    bad=post(api,'credentials',{'name':'Bad','secret':'do-not-echo','unexpected':'do-not-echo'},expected=422)
    assert 'do-not-echo' not in json.dumps(bad)


def test_explicit_human_grants_delegate_only_to_owned_bots_and_revoke_cascades(api):
    setup(api);row=create(api);cid=row['id']
    # Ana and Ben authorize; unrelated registered people start with no access.
    parent=post(api,f'credentials/{cid}/grants',{'subject':'human:cara'},'ben-test')
    assert len(get(api,'credentials','cara-test')['credentials'])==1
    assert post(api,f'credentials/{cid}/reveal',{},'cara-test')['value'].startswith('phx-')
    post(api,f'credentials/{cid}/grants',{'subject':'human:ben'},'cara-test',expected=403)
    post(api,f'credentials/{cid}/grants',{'subject':'bot:ops'},'cara-test',expected=403)
    with api.app.state.store.transaction() as c:
        c.execute("UPDATE bot_config SET operator='cara' WHERE bot='finance'")
    child=post(api,f'credentials/{cid}/grants',{'subject':'bot:finance'},'cara-test')
    machine=runner(api);assign(api,machine,'finance');ready(api,machine,['finance'])
    post(api,'chat/finance',{'text':'Use only the synthetic fixture'})
    attempt=claim(api,machine)
    assert attempt['credential_vault'] is True
    assert get(api,'credential-runtime',attempt['token'])['credentials'][0]['value'].startswith('phx-')
    get(api,'credential-runtime',machine['token'],expected=403)
    post(api,f'credentials/{cid}/grants/{parent["id"]}/revoke',{},'ben-test')
    assert get(api,'credential-runtime',attempt['token'])['credentials']==[]
    post(api,f'credentials/{cid}/reveal',{},'cara-test',expected=403)
    # Regranting a person does not resurrect their old delegated grants.
    post(api,f'credentials/{cid}/grants',{'subject':'human:cara'})
    assert get(api,'credential-runtime',attempt['token'])['credentials']==[]


def test_ungranted_bot_tamper_idempotency_and_stale_lease(api):
    setup(api);row=create(api);cid=row['id']
    machine=runner(api);assign(api,machine,'ops');ready(api,machine,['ops'])
    post(api,'chat/ops',{'text':'Synthetic check'})
    attempt=claim(api,machine)
    post(api,f'credentials/{cid}/reveal',{},attempt['token'],expected=403)
    post(api,f'credentials/{cid}/grants',{'subject':'bot:ops'})
    assert post(api,f'credentials/{cid}/reveal',{},attempt['token'])['value'].startswith('phx-')
    post(api,'credentials',{'name':'Retry','secret':'synthetic-one'},key='same')
    post(api,'credentials',{'name':'Retry','secret':'synthetic-two'},key='same',expected=409)
    with api.app.state.store.transaction() as c:
        c.execute('UPDATE credentials SET nonce=? WHERE id=?',(os.urandom(12),cid))
    post(api,f'credentials/{cid}/reveal',{},expected=503)
    with api.app.state.store.transaction() as c:
        c.execute('UPDATE attempts SET lease_until=? WHERE id=?',(H.shift(H.now(),seconds=-1),attempt['id']))
    get(api,'credential-runtime',attempt['token'],expected=409)


def test_operator_change_invalidates_delegated_bot_permission(api):
    from backend.credentials import effective_grant
    setup(api);cid=create(api)['id']
    post(api,f'credentials/{cid}/grants',{'subject':'human:cara'})
    with api.app.state.store.transaction() as c:
        c.execute("UPDATE bot_config SET operator='cara' WHERE bot='finance'")
    post(api,f'credentials/{cid}/grants',{'subject':'bot:finance'},'cara-test')
    with api.app.state.store.transaction() as c:
        assert effective_grant(c,cid,'bot:finance')
        c.execute("UPDATE bot_config SET operator='ana' WHERE bot='finance'")
        assert effective_grant(c,cid,'bot:finance') is None


def test_botops_adds_and_grants_a_credential_a_person_asked_for_and_nothing_more(api):
    """Ana, 2026-09-26: "Add to credentials" / "Do this for me". Checked as him, audited; BotOps
    still cannot reveal, update or revoke."""
    from backend.store import encode
    from backend.tests.test_api import setup_attempt
    setup(api)
    with api.app.state.store.transaction() as c:
        c.execute("INSERT INTO bots(slug,display_name,state) VALUES('botops','BotOps','active')")
        c.execute("INSERT INTO bot_config(bot,config_json,operator) VALUES('botops',?, 'ana')",
                  (encode({"name": "botops", "runtime": "fake", "status": "active"}),))
    _, _, botops = setup_attempt(api, 'botops')
    body = {'name': 'Gartner', 'kind': 'password', 'username': 'ana@acme.example', 'secret': 'synthetic-gartner-pass-42'}
    post(api, 'credentials', body, botops['token'], expected=403)
    ask = post(api, 'chat/botops', {'text': 'Add to credentials'})
    mid = ask.get('message', ask)['id']
    row = post(api, 'credentials', {**body, 'on_behalf_of': mid}, botops['token'])
    assert row['name'] == 'Gartner'
    post(api, f"credentials/{row['id']}/grants", {'subject': 'bot:ops', 'on_behalf_of': mid}, botops['token'])
    post(api, f"credentials/{row['id']}/reveal", {}, botops['token'], expected=403)
    post(api, f"credentials/{row['id']}", {**body, 'expected_revision': 1, 'on_behalf_of': mid}, botops['token'], expected=403)
    # Metadata only on a person's behalf: find it by name, set its bot key name; the secret never moves.
    get(api, 'credentials', botops['token'], expected=403)
    listed = get(api, f'credentials?on_behalf_of={mid}', botops['token'])['credentials']
    assert any(x['name'] == 'Gartner' for x in listed) and 'synthetic-gartner-pass-42' not in json.dumps(listed)
    meta = {k: v for k, v in body.items() if k != 'secret'}
    post(api, f"credentials/{row['id']}", {**meta, 'env': 'GARTNER_PASSWORD', 'expected_revision': 1, 'on_behalf_of': mid}, botops['token'])
    with api.app.state.store.read() as c:
        assert c.execute("SELECT count(*) FROM credential_grants WHERE credential_id=? AND subject='bot:ops' AND revoked IS NULL",
                         (row['id'],)).fetchone()[0] == 1
        assert c.execute("SELECT updated_by FROM credentials WHERE id=?", (row['id'],)).fetchone()[0] == 'human:ana'
        assert c.execute("SELECT count(*) FROM events WHERE action='credential.change_delegated' AND actor='bot:botops'").fetchone()[0] == 4
        assert c.execute("SELECT env FROM credentials WHERE id=?", (row['id'],)).fetchone()[0] == 'GARTNER_PASSWORD'
        for table in ('credentials', 'idempotency', 'events'):
            assert 'synthetic-gartner-pass-42' not in str([tuple(r) for r in c.execute(f'SELECT * FROM {table}')])
