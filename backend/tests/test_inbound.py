"""Shared inbound messages: identity boundaries, non-consuming cursors and durable delivery."""
import json
import time

import httpx
import pytest

from backend import inbound
from backend.auth import Identity
from backend.store import Problem
from backend.tests.test_api import api, headers, setup_attempt  # noqa: F401
from clients import hubcli, hubtools, remotecli


@pytest.fixture(autouse=True)
def no_live_inbound(monkeypatch):
    monkeypatch.delenv('TICO_INBOUND_KEY',raising=False)
    monkeypatch.setenv('TICO_INBOUND_URL','https://hq.example.test')


def seed(api):
    svc=api.app.state.inbound
    with svc.store.transaction() as c:
        for ident in ('ibx_a','ibx_b','ibx_c'):
            inbound.save_inbox(c,{'inbox_id':ident,'kind':'email','name':ident,'address':ident+'@example.test',
                                 'state':'active','created_by':'human:ana','period_end':None,'cancel_pending':0})
    return svc


def page(seq=1,inbox='ibx_b',ident='ses:msg:ibx_b',body='Your verification code is 123456.'):
    return {'deliveries':[{'hq_seq':seq,'delivery_id':ident,'inbox_id':inbox,'kind':'email','received_at':time.time(),
                            'from':'Login <login@example.test>','subject':'Sign in','text':body}], 'gaps':[],'cursor':seq}


def test_company_members_share_non_consuming_reads_and_waits(api):
    svc=seed(api);svc.ingest(page())
    for caller in ('ana-test','cara-test'):
        h=headers(caller)
        listed=api.get('/api/v2/inbound/messages?inbox_ids=ibx_a,ibx_b',headers=h)
        assert listed.status_code==200 and len(listed.json()['messages'])==1
        assert '123456' not in listed.json()['messages'][0].keys()
        body=api.get('/api/v2/inbound/messages/ses:msg:ibx_b',headers=h).json()
        assert body['untrusted'] and '123456' in body['text']
        assert api.get('/api/v2/inbound/messages/ses:msg:ibx_b/code',headers=h).json()['code']=='123456'
        waited=api.post('/api/v2/inbound/wait',headers=h,json={'inbox_ids':['ibx_a','ibx_b'],'after':0,'timeout':0}).json()
        assert len(waited['messages'])==1
    assert api.get('/api/v2/inbound/messages?inbox_ids=ibx_a,unknown',headers=headers()).status_code==404
    assert api.get('/api/v2/inbound/messages?inbox_ids=ibx_c',headers=headers()).json()['messages']==[]
    # A 100 KB body is paged, including multibyte text, with no markup rendering.
    text='é'*60000;svc.ingest(page(2,ident='ses:large:ibx_b',body=text))
    data=api.get('/api/v2/inbound/messages/ses:large:ibx_b',headers=headers()).json()
    assert len(data['text'].encode())<=32768 and data['next_offset']
    assert len(api.get('/api/v2/inbound/messages',headers=headers()).content)<96*1024


def test_authorization_rejects_bare_runners_support_and_non_admin_phone_writes(api):
    svc=seed(api)
    for who in (Identity('runner:x','runner'),Identity('service:x','service',scope='tasks'),
                Identity('human:tico-support','human',support='full')):
        with pytest.raises(Problem):svc.list_inboxes(who)
    assert api.post('/api/v2/inbound/inboxes',headers=headers('cara-test'),json={'kind':'sms','name':'Login'}).status_code==403
    assert api.post('/api/v2/inbound/inboxes/ibx_a/release',headers=headers('cara-test'),json={}).status_code==403
    assert api.get('/api/v2/inbound/inboxes').status_code==401
    # Current non-admin members can create email, with the creator bound to the authenticated identity.
    calls=[]
    def remote(method,path,body=None):
        calls.append(body)
        return {'inbox_id':'ibx_new','kind':'email','name':'Login','address':'agent-acme-login@tico.team',
                'state':'active','created_by':body['created_by'],'period_end':None,'cancel_pending':0}
    svc.remote=remote
    result=api.post('/api/v2/inbound/inboxes',headers=headers('cara-test'),json={'kind':'email','name':'Login'})
    assert result.status_code==200 and calls[-1]['created_by']=='human:cara'
    assert 'account_id' not in calls[-1]


def test_commit_before_ack_lost_ack_and_wait_cursor_do_not_lose_messages(api,monkeypatch):
    svc=seed(api);svc.off=False
    ack=[]
    def remote(method,path,body=None):
        if path=='inboxes':return {'inboxes':[]}
        if path=='pull':return page() if body['cursor']==0 else {'deliveries':[],'gaps':[],'cursor':1}
        if path=='ack':
            ack.append(body['through_hq_seq'])
            if len(ack)==1:raise Problem('inbound_unavailable','Lost ack',503)
            return {'ok':True}
    svc.remote=remote
    with pytest.raises(Problem):svc.sync()
    svc.sync()
    with svc.store.read() as c:
        assert c.execute('SELECT count(*) FROM inbound_messages').fetchone()[0]==1
        assert c.execute('SELECT cursor FROM inbound_sync').fetchone()[0]==1
    assert ack==[1,1]
    svc.ingest(page(2,inbox='ibx_c',ident='ses:other:ibx_c'))
    empty=api.post('/api/v2/inbound/wait',headers=headers(),json={'after':1,'inbox_ids':['ibx_b'],'timeout':0}).json()
    assert empty['messages']==[] and empty['cursor']==2
    svc.ingest(page(3,ident='ses:later:ibx_b'))
    for _ in range(2):
        got=api.post('/api/v2/inbound/wait',headers=headers(),json={'after':2,'inbox_ids':['ibx_b'],'timeout':0}).json()
        assert len(got['messages'])==1
    # No content or code is copied into the audit log.
    with svc.store.read() as c:
        events=[dict(r) for r in c.execute("SELECT * FROM events WHERE action LIKE 'inbound.%'")]
    assert '123456' not in json.dumps(events)


def test_cli_and_mcp_reach_the_same_inbound_tools(monkeypatch):
    class API:
        def get(self,path,**query):return {'path':path,'query':query}
        def post(self,path,body,key=None):return {'path':path,'body':body}
    api=API()
    monkeypatch.setattr(remotecli,"Client",lambda *a,**kw:api)
    monkeypatch.setenv("HUB_API_URL","https://hub.example.test")
    for command in [['inbound','inboxes'],['inbound','create-email','Login'],
                    ['inbound','list','--inbox-id','ibx_a','--inbox-id','ibx_b'],
                    ['inbound','search','code'],['inbound','cursor'],['inbound','wait','--after','0','--timeout','0'],
                    ['inbound','read','ses:msg:ibx_b'],['inbound','code','ses:msg:ibx_b']]:
        args=hubcli.parser().parse_args(command)
        name=remotecli.tool_name(args.fn)
        assert name in hubtools.BY_NAME
        result=remotecli.run(args)
        assert result['path'].startswith('inbound/')


def test_native_and_registered_agents_share_inboxes_but_lose_access_when_paused(api):
    svc=seed(api);svc.ingest(page())
    runner,message,attempt=setup_attempt(api)
    native=api.get('/api/v2/inbound/messages',headers=headers(attempt['token']))
    assert native.status_code==200 and len(native.json()['messages'])==1
    external=Identity('bot:ops','bot',agent='hermes')
    with svc.store.transaction() as c:
        c.execute("INSERT INTO agents(bot,harness,token_hash,created,created_by) VALUES('ops','hermes','synthetic',?,'human:ana')",
                  (inbound.H.now(),))
    assert len(svc.list_inboxes(external)['inboxes'])==3
    with svc.store.transaction() as c:c.execute("UPDATE bots SET state='paused' WHERE slug='ops'")
    with pytest.raises(Problem):svc.list_inboxes(external)
    assert api.get('/api/v2/inbound/messages',headers=headers(attempt['token'])).status_code==409
