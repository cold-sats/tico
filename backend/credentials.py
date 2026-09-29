"""Encrypted company credentials with explicit human and run-bound bot grants."""
import hashlib
import hmac
import json
import os
from typing import Literal

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from fastapi import Request
from pydantic import ConfigDict, Field, SecretStr

from .auth import validate_identity
from .models import Contract, ID
from .bot_access import owner_ids
from .store import H, Problem, encode

CONTEXT = {'application': 'tico-credentials'}


def administrator(c, who, admins):
    """`admins` is the environment's TICO_CREDENTIAL_ADMINS list, which defaults to its owner."""
    if who.role not in ('owner', 'human'):
        return False
    row = c.execute('SELECT email FROM humans WHERE id=?', (H.actor_id(who.actor),)).fetchone()
    return bool(row and (row['email'] or '').lower() in set(admins))


def require_admin(c, who, admins):
    if not administrator(c, who, admins):
        raise Problem('forbidden', 'Only a credential administrator may authorize this change', 403)


def effective_grant(c, credential, subject):
    return c.execute('SELECT g.* FROM credential_grants g LEFT JOIN credential_grants p ON p.id=g.parent_id '
                     "LEFT JOIN bot_config bc ON g.subject='bot:'||bc.bot "
                     'WHERE g.credential_id=? AND g.subject=? AND g.revoked IS NULL '
                     "AND (g.parent_id IS NULL OR (p.revoked IS NULL AND p.id IS NOT NULL AND p.subject='human:'||bc.operator))",
                     (credential, subject)).fetchone()


def permitted(c, who, credential, admins):
    return administrator(c, who, admins) or (who.role in ('human', 'owner', 'bot')
                                             and effective_grant(c, credential, who.actor) is not None)


def can_open(c, who, admins):
    return administrator(c, who, admins) or (who.role in ('human', 'owner') and any(
        effective_grant(c, row[0], who.actor) for row in c.execute(
            'SELECT credential_id FROM credential_grants WHERE subject=? AND revoked IS NULL', (who.actor,))))


class CredentialWrite(Contract):
    # Password spaces are significant. SecretStr prevents repr/debug output from exposing it.
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=False)
    name: str = Field(min_length=1, max_length=150)
    username: str = Field(default='', max_length=250)
    kind: Literal['api_key', 'password', 'token', 'file', 'connection'] = 'api_key'
    env: str = Field(default='', max_length=100, pattern=r'^$|^[A-Z_][A-Z0-9_]*$')
    secret: SecretStr | None = Field(default=None, max_length=100_000)
    source: str = Field(default='', max_length=500)
    expected_revision: int | None = Field(default=None, ge=1)
    # BotOps adding a credential a person asked for in chat, as that person (backend/app.py
    # delegated_identity). Only create and grant take it; reveal, update and revoke never do.
    on_behalf_of: ID | None = None


class CredentialGrant(Contract):
    subject: ID
    on_behalf_of: ID | None = None


class CredentialCipher:
    def __init__(self, key_id, kms=None):
        self.key_id, self.kms = key_id, kms
        self.cached = None

    def key(self, c):
        if not self.key_id:
            raise Problem('vault_unavailable', 'Credential encryption is not configured', 503)
        if self.cached is not None:
            return self.cached
        try:
            if self.kms is None:
                import boto3
                self.kms = boto3.client('kms')
            row = c.execute("SELECT * FROM credential_keys WHERE id='v1'").fetchone()
            if row:
                if row['kms_key'] != self.key_id:
                    raise ValueError('Unexpected wrapping key')
                key = self.kms.decrypt(KeyId=self.key_id, CiphertextBlob=row['wrapped_key'],
                                       EncryptionContext=CONTEXT)['Plaintext']
            else:
                generated = self.kms.generate_data_key(KeyId=self.key_id, KeySpec='AES_256', EncryptionContext=CONTEXT)
                key = generated['Plaintext']
                c.execute('INSERT INTO credential_keys VALUES(?,?,?)', ('v1', self.key_id, generated['CiphertextBlob']))
            if len(key) != 32:
                raise ValueError('Invalid data key')
            # No secret or data key is persisted outside the KMS-encrypted DB record.
            # Cache only keys already persisted by a previous transaction. A new key must
            # not survive in memory if the surrounding creation transaction rolls back.
            if row:
                self.cached = key
            return key
        except Problem:
            raise
        except Exception:
            raise Problem('vault_unavailable', 'Credential encryption is temporarily unavailable', 503) from None

    def encrypt(self, c, cid, secret):
        nonce = os.urandom(12)
        return AESGCM(self.key(c)).encrypt(nonce, secret.encode(), ('tico-credential:v1:' + cid).encode()), nonce

    def decrypt(self, c, row):
        try:
            return AESGCM(self.key(c)).decrypt(row['nonce'], row['ciphertext'],
                                             ('tico-credential:v1:' + row['id']).encode()).decode()
        except Problem:
            raise
        except Exception:
            raise Problem('vault_unavailable', 'This credential could not be decrypted', 503) from None


class Vault:
    def __init__(self, store, cipher=None):
        self.store = store
        self.cipher = cipher or CredentialCipher(store.settings.credential_kms_key)

    @property
    def admins(self):
        return self.store.settings.credential_admins

    def change(self, who, operation, key, body, authorize, fn):
        if not key or len(key) > 200:
            raise Problem('idempotency_key', 'Provide an Idempotency-Key', 422)
        with self.store.transaction() as c:
            validate_identity(c, who)
            authorize(c, who)
            # Keyed fingerprint: neither a plaintext secret nor an offline password-guessing
            # hash enters the mutation receipt. Responses here contain only metadata.
            payload = body.model_dump()
            if isinstance(payload.get('secret'), SecretStr):
                payload['secret'] = payload['secret'].get_secret_value()
            fingerprint = hmac.new(self.cipher.key(c), b'tico-request:v1:' + encode(payload).encode(), hashlib.sha256).hexdigest()
            old = c.execute('SELECT request_hash,response_json FROM idempotency WHERE actor=? AND operation=? AND key=?',
                            (who.actor, operation, key)).fetchone()
            if old:
                if not hmac.compare_digest(old['request_hash'], fingerprint):
                    raise Problem('idempotency_conflict', 'This request key was already used for different content', 409)
                return json.loads(old['response_json'])
            result = fn(c)
            c.execute('INSERT INTO idempotency VALUES(?,?,?,?,?,?)',
                      (who.actor, operation, key, fingerprint, encode(result), H.now()))
            return result

    @staticmethod
    def row(c, cid):
        row = c.execute('SELECT * FROM credentials WHERE id=?', (cid,)).fetchone()
        if not row:
            raise Problem('not_found', 'Credential not found', 404)
        return row

    @staticmethod
    def brief(row):
        return {k: row[k] for k in ('id', 'name', 'username', 'kind', 'env', 'preview', 'source', 'revision', 'created', 'updated')} | {
            'stored': row['ciphertext'] is not None}

    def write(self, c, who, body, cid=None):
        require_admin(c, who, self.admins)
        old = self.row(c, cid) if cid else None
        if old and body.expected_revision != old['revision']:
            raise Problem('version_conflict', 'Credential changed; refresh before saving', 409)
        if not old and body.expected_revision is not None:
            raise Problem('version_conflict', 'New credentials have no previous revision', 409)
        cid, now = cid or H.new_id(), H.now()
        ciphertext, nonce, preview = (old['ciphertext'], old['nonce'], old['preview']) if old else (None, None, '')
        secret = body.secret.get_secret_value() if body.secret is not None else None
        if secret is not None:
            if not secret:
                raise Problem('credential', 'Enter a nonempty password or key', 422)
            ciphertext, nonce = self.cipher.encrypt(c, cid, secret)
            preview = secret[:3] + '…' + secret[-3:] if body.kind in ('api_key', 'token') and len(secret) >= 12 else '••••••'
        if old and body.kind != old['kind'] and secret is None:
            # A password must never retain a previous API-key preview after a kind change.
            preview = '••••••' if ciphertext is not None else ''
        name = body.name.strip()
        if not name:
            raise Problem('credential', 'Enter a credential name', 422)
        c.execute('INSERT INTO credentials(id,name,username,kind,env,preview,ciphertext,nonce,source,created,updated,updated_by) '
                  'VALUES(?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET name=excluded.name,username=excluded.username,'
                  'kind=excluded.kind,env=excluded.env,preview=excluded.preview,ciphertext=excluded.ciphertext,nonce=excluded.nonce,'
                  'source=excluded.source,revision=credentials.revision+1,updated=excluded.updated,updated_by=excluded.updated_by',
                  (cid,name,body.username,body.kind,body.env,preview,ciphertext,nonce,body.source,now,now,who.actor))
        H.event(c,who.actor,'credential.updated' if old else 'credential.created',cid,{'secret_changed':secret is not None})
        return self.brief(self.row(c,cid))

    def grant_authority(self, c, who, cid, subject):
        if administrator(c, who, self.admins):
            return None
        parent = effective_grant(c,cid,who.actor) if who.role in ('human','owner') else None
        bot = c.execute('SELECT operator,bot_owners_json FROM bot_config WHERE bot=?', (H.actor_id(subject),)).fetchone() if subject.startswith('bot:') else None
        # A bot's owners (its creator and co-owners, and its operator) attach credentials they hold themselves.
        if not parent or not bot or (bot['operator'] != H.actor_id(who.actor)
                                     and H.actor_id(who.actor) not in owner_ids(bot['bot_owners_json'])):
            raise Problem('forbidden', 'You may attach granted credentials only to bots you manage', 403)
        return parent['id']

    def grant(self, c, who, cid, subject):
        self.row(c,cid)
        parent = self.grant_authority(c,who,cid,subject)
        if subject.startswith('human:'):
            exists=c.execute('SELECT 1 FROM humans WHERE id=?',(H.actor_id(subject),)).fetchone()
        elif subject.startswith('bot:'):
            exists=c.execute('SELECT 1 FROM bots WHERE slug=?',(H.actor_id(subject),)).fetchone()
        else:
            exists=None
        if not exists:
            raise Problem('subject','Choose a registered person or bot',422)
        old=effective_grant(c,cid,subject)
        if old and (parent is not None or old['parent_id'] is None):
            return {'id':old['id'],'subject':subject}
        # Replace expired delegated rows, or promote a delegated grant to direct admin authorization.
        c.execute('UPDATE credential_grants SET revoked=?,revoked_by=? WHERE credential_id=? AND subject=? AND revoked IS NULL',
                  (H.now(),who.actor,cid,subject))
        gid=H.new_id()
        c.execute('INSERT INTO credential_grants(id,credential_id,subject,granted_by,parent_id,created) VALUES(?,?,?,?,?,?)',
                  (gid,cid,subject,who.actor,parent,H.now()))
        H.event(c,who.actor,'credential.granted',cid,{'grant':gid,'subject':subject,'parent':parent})
        return {'id':gid,'subject':subject}

    def reveal(self,c,who,cid):
        validate_identity(c,who)
        if not permitted(c,who,cid,self.admins):
            raise Problem('forbidden','You do not have access to this credential',403)
        row=self.row(c,cid)
        if row['ciphertext'] is None:
            raise Problem('not_connected','This connection has no stored password or key',409)
        value=self.cipher.decrypt(c,row)
        H.event(c,who.actor,'credential.revealed',cid,{'attempt':who.attempt_id or None})
        return {'id':cid,'value':value}


def install_credentials(app,store,delegate=None,propose=None):
    vault=app.state.vault=Vault(store)

    def acting(request, body, message_id=None):
        """For "Add to credentials" / "Do this for me": the caller, or the person
        whose message to BotOps asked for this, checked with that person's own rights."""
        who = request.state.identity
        message_id = message_id or getattr(body, 'on_behalf_of', None)
        if not message_id:
            return who
        if delegate is None:
            raise Problem('forbidden', 'Delegated credential changes are not enabled', 403)
        with store.transaction() as c:
            person = delegate(c, who, message_id)
            H.event(c, who.actor, 'credential.change_delegated', request.url.path,
                    {'on_behalf_of': person.actor, 'message_id': message_id})
        return person

    @app.get('/api/v2/credentials')
    def inventory(request:Request,on_behalf_of:str=''):
        # Metadata only (names, bot key names, grants; never a secret), so BotOps can find the
        # credential a person asked it to grant (no manual steps).
        who=acting(request,None,on_behalf_of) if on_behalf_of else request.state.identity
        with store.read() as c:
            if who.role not in ('human','owner') or not can_open(c,who,vault.admins):
                raise Problem('forbidden','A credential administrator must grant you access',403)
            admin=administrator(c,who,vault.admins)
            rows=[]
            for row in c.execute('SELECT * FROM credentials ORDER BY lower(name),id'):
                if not permitted(c,who,row['id'],vault.admins):continue
                item=vault.brief(row)
                item['grants']=[dict(g) for g in c.execute('SELECT id,subject,granted_by,parent_id,created FROM credential_grants WHERE credential_id=? AND revoked IS NULL',(row['id'],))
                                if effective_grant(c,row['id'],g['subject']) and (admin or g['subject']==who.actor or g['granted_by']==who.actor)]
                rows.append(item)
            people=[dict(r) for r in c.execute('SELECT id,name,email FROM humans ORDER BY name')] if admin else []
            bots=[dict(r) for r in c.execute('SELECT b.slug AS id,b.display_name AS name,bc.operator FROM bots b JOIN bot_config bc ON bc.bot=b.slug ORDER BY b.display_name')
                  if admin or r['operator']==H.actor_id(who.actor)]
            return {'credentials':rows,'can_manage':admin,'people':people,'bots':bots,'configured':bool(store.settings.credential_kms_key)}

    @app.post('/api/v2/credentials')
    def create(request:Request,body:CredentialWrite):
        who=acting(request,body)
        return vault.change(who,request.url.path,request.headers.get('idempotency-key'),body,
                            lambda c,w:require_admin(c,w,vault.admins),
                            lambda c:vault.write(c,who,body))

    @app.post('/api/v2/credentials/{cid}')
    def update(request:Request,cid:str,body:CredentialWrite):
        # On a person's behalf only the name and bot key name may change: never the secret.
        if body.on_behalf_of and body.secret is not None:
            raise Problem('forbidden', 'A stored secret is changed only by a credential administrator', 403)
        who=acting(request,body)
        return vault.change(who,request.url.path,request.headers.get('idempotency-key'),body,
                            lambda c,w:require_admin(c,w,vault.admins),
                            lambda c:vault.write(c,who,body,cid))

    @app.post('/api/v2/credentials/{cid}/grants')
    def grant(request:Request,cid:str,body:CredentialGrant):
        who=acting(request,body)
        if who.via=='botops' and not who.confirmed and propose:
            # Giving a bot a stored credential is a tool registration on a shared or another bot's secret:
            # through BotOps it is always the requester's own click.
            with store.transaction() as c:
                validate_identity(c,who)
                vault.grant_authority(c,who,cid,body.subject)
                name=vault.row(c,cid)['name']
                return propose(c,who,'POST',request.url.path,{'subject':body.subject},
                               f"Give {body.subject} the stored credential {name}")
        return vault.change(who,request.url.path,request.headers.get('idempotency-key'),body,
                            lambda c,w:vault.grant_authority(c,w,cid,body.subject),lambda c:vault.grant(c,who,cid,body.subject))

    @app.post('/api/v2/credentials/{cid}/grants/{gid}/revoke')
    def revoke(request:Request,cid:str,gid:str):
        who=request.state.identity
        with store.transaction() as c:
            validate_identity(c,who)
            require_admin(c,who,vault.admins)
            row=c.execute('SELECT subject FROM credential_grants WHERE id=? AND credential_id=?',(gid,cid)).fetchone()
            if not row:raise Problem('not_found','Grant not found',404)
            c.execute('UPDATE credential_grants SET revoked=coalesce(revoked,?),revoked_by=? WHERE id=?',(H.now(),who.actor,gid))
            H.event(c,who.actor,'credential.revoked',cid,{'grant':gid,'subject':row['subject']})
            return {'ok':True}

    @app.post('/api/v2/credentials/{cid}/reveal')
    def reveal(request:Request,cid:str):
        with store.transaction() as c:
            return vault.reveal(c,request.state.identity,cid)

    @app.get('/api/v2/credential-runtime')
    def runtime(request:Request):
        who=request.state.identity
        if who.role!='bot':raise Problem('forbidden','An active bot run is required',403)
        with store.transaction() as c:
            validate_identity(c,who)
            values=[]
            for row in c.execute('SELECT * FROM credentials ORDER BY id'):
                if row['ciphertext'] is not None and effective_grant(c,row['id'],who.actor):
                    values.append({'id':row['id'],'name':row['name'],'env':row['env'],'kind':row['kind'],**vault.reveal(c,who,row['id'])})
            return {'credentials':values}
