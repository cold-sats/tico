import contextlib
import json
import sqlite3
import tempfile
import unittest
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from connectors.mail import scheduling as s, calendar as cal, Refused, Failure
from connectors.mail import __main__ as cli

NOW = datetime(2026,9,8,15,tzinfo=s.TZ)


class Workflow(unittest.TestCase):
    def setUp(self):
        self.conn=sqlite3.connect(':memory:')
        self.ctx=SimpleNamespace(slug='inbox',mailbox='ana@acme.example',conn=self.conn,
                                 dry=False,calendar=MagicMock(),gmail=MagicMock(),audit=MagicMock(),
                                 policy={'defaults':{'max_sends_per_day':20}})
        self.ctx.calendar.create_scheduling_event.return_value={'id':'event'}
        self.ctx.gmail.create_draft.return_value={'id':'draft'}
        self.ctx.gmail.send_draft.return_value={'id':'sent'}
        self.msg={'id':'accepted','from':'creator@example.org','to':['ana@acme.example'],'cc':[],
                  'date':'2030-01-01','subject':'Call','body':'Tuesday at 10 works', 'labels':[]}
        self.args=SimpleNamespace(thread='thread',category='influencer',mode='book',bd_confirmation=None,
                                  slot='2030-01-08T10:00:00-08:00',acceptance_message='accepted')
        self.stack=contextlib.ExitStack()
        self.stack.enter_context(patch.object(cli,'thread_context',return_value=([self.msg],'','','Call',[])))
        self.stack.enter_context(patch.object(s,'permission'))
        self.review=self.stack.enter_context(patch.object(s,'review_thread',return_value={'eligible':True,'accepts_slot':True}))
        self.free=self.stack.enter_context(patch.object(s,'check_free'))
        self.stack.enter_context(patch.object(s,'mailbox_lock',return_value=contextlib.nullcontext()))
        self.stack.enter_context(patch.object(cli,'modify'))
    def tearDown(self):self.stack.close();self.conn.close()

    def test_refusal_and_dry_run_never_invite(self):
        self.ctx.dry=True
        self.assertTrue(s.run(self.ctx,self.args)['would_send'])
        self.ctx.calendar.create_scheduling_event.assert_not_called()
        self.ctx.dry=False;self.review.side_effect=Refused('not accepted')
        with self.assertRaises(Refused):s.run(self.ctx,self.args)
        self.ctx.calendar.create_scheduling_event.assert_not_called()

class PermissionGrant(unittest.TestCase):
    def setUp(self):
        self.manifest={'scheduling_send':True,'outbound_send':False,'access':[
            {'service':'gmail','identity':'ana@acme.example','can':['read','draft','schedule']},
            {'service':'google-calendar','identity':'ana@acme.example','can':['read','schedule']}]}
        self.ctx=SimpleNamespace(slug='inbox',mailbox='ana@acme.example',policy={
            'scheduling':{'mailbox':'ana@acme.example','employee':'inbox'},
            'send_enabled':True,'mailboxes':{},'blocklist':{'addresses':[],'domains':[]},
            'owner_handles_personally':{'addresses':[],'domains':[]}})

    def test_kill_switch_and_personal_recipients_still_block(self):
        with patch.object(s.access,'load',return_value=self.manifest):
            self.ctx.policy['send_enabled']=False
            with self.assertRaises(Refused):s.permission(self.ctx,'influencer','x@example.org','t',None)
            self.ctx.policy['send_enabled']=True
            self.ctx.policy['owner_handles_personally']['addresses']=['x@example.org']
            with self.assertRaises(Refused):s.permission(self.ctx,'influencer','x@example.org','t',None)
