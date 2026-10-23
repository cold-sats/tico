"""Tico file hosting 1/2 (Dev 315): a company's files in Tico's bucket, handed over by Tico HQ, served from its
ticofiles.com address. Spec tests 1, 4 and 7, and the app halves of 5 and 6 (Product roadmap "Tico file hosting
through Gateway"). Fake S3 and a fake HQ only: no network."""
import io
import json
import threading
import zipfile

import boto3
import pytest
from botocore.exceptions import ClientError

from backend import tico_storage
from backend.tests.test_api import api, headers, post  # noqa: F401
from backend.tests.test_storage_delivery import S3, attach, task

SECRET = "tico-hosting-secret-access-key-01"
TOKEN = "tico-hosting-session-token-01"
KEY = "AKIATICOHOSTING0001"
ADDRESS = "https://acme.ticofiles.com"


class NoWrite(S3):
    def put_object(self, **kw):
        raise ClientError({'Error': {'Code': 'AccessDenied', 'Message': SECRET}}, 'PutObject')


class HQ:
    """Tico HQ's file-hosting endpoint: answers with `self.answer`, records what the app sent."""
    def __init__(self):
        self.answer, self.status, self.asked = {"state": "off"}, 200, []

    def __call__(self, request, timeout):
        self.asked.append((request.full_url, request.get_header("Authorization"), json.loads(request.data)))
        if self.status != 200:
            import urllib.error
            raise urllib.error.HTTPError(request.full_url, self.status, "no", {}, io.BytesIO(b'{"error":"not_found"}'))
        body = json.dumps(self.answer).encode()

        class Answer(io.BytesIO):
            status = 200

            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return False
        return Answer(body)


class Owner:
    actor = 'human:ana'


def on(state="on", **extra):
    return {"state": state, "bucket": "tico-files-us", "prefix": "c/acme", "region": "us-east-1",
            "access_key_id": KEY, "secret_access_key": SECRET, "session_token": TOKEN, "address": ADDRESS,
            "price_gb_month": 0.033, **extra}


@pytest.fixture
def tico(api, monkeypatch):
    """The Tico bucket (signed by HQ's keys and session token), the company's own bucket, the server's, and HQ."""
    made = {KEY: S3(), 'AKIAEXAMPLEGOOD0001': S3(), 'AKIAEXAMPLENOWR0001': NoWrite(), 'server': S3()}
    for s3 in made.values():
        s3.close = lambda: None

    def client(service, **options):
        if 'aws_access_key_id' not in options:
            return made['server']
        if options['aws_access_key_id'] == KEY:
            assert options['aws_secret_access_key'] == SECRET and options['aws_session_token'] == TOKEN
        return made[options['aws_access_key_id']]
    monkeypatch.setattr(boto3, 'client', client)
    monkeypatch.setenv('TICO_GATEWAY_KEY', 'gk_test_0123456789abcdef')
    monkeypatch.setenv('TICO_GATEWAY_URL', 'https://gateway.example')
    api.app.state.blobs._loop = None
    hq = HQ()
    app = api.app

    def sync(answer=None):
        if answer is not None:
            hq.answer = answer
        return tico_storage.sync(app.state.store, app.state.vault, app.state.blobs, opener=hq)
    return made, hq, sync


def download(api, fid, who='ana-test'):
    return api.get(f'/api/v2/files/{fid}', headers=headers(who))


def test_turning_it_on_stores_new_files_in_tico_storage_and_existing_files_still_open(api, tico):
    """Spec 1: new files in Tico's storage, under the company's own folder; existing files still open; visuals in
    full on its ticofiles.com address. Keys come from HQ, sealed, never shown."""
    made, hq, sync = tico
    tid = task(api)
    before = attach(api, tid, 'before.txt', b'on the server disk before')
    assert sync() == {"state": "off", "label": "Tico file hosting"}, 'not bought: nothing changes'
    assert not api.app.state.blobs.bucket and api.app.state.store.settings.visual_origin == ''

    view = sync(on())
    assert view['state'] == 'on' and view['address'] == ADDRESS and view['location'] == 'tico-files-us/c/acme'
    url, auth, body = hq.asked[-1]
    assert url == 'https://gateway.example/file-hosting' and auth == 'Bearer gk_test_0123456789abcdef'
    assert body == {"files": 1, "bytes": len(b'on the server disk before')}, 'HQ gets the total for its estimate'
    after = attach(api, tid, 'after.txt', b'in tico storage')
    bucket = made[KEY]
    assert any(k.startswith('c/acme/blobs/') and v == b'in tico storage' for k, v in bucket.objects.items())
    assert download(api, before).content == b'on the server disk before'
    assert download(api, after).content == b'in tico storage'
    assert b'on the server disk before' not in bucket.objects.values(), 'existing files move only when asked'
    api.app.state.blobs.copy_local(api.app.state.store, threading.Event(), interval=0)
    assert b'on the server disk before' not in bucket.objects.values(), 'not even by the background disk copy'

    # Visuals in full on the company's ticofiles.com address.
    settings = api.app.state.store.settings
    assert settings.visual_origin == ADDRESS
    from backend import visuals
    assert visuals.mode(settings) == 'full'

    # The owner's storage page says so; the keys are sealed and never returned or logged.
    page = api.get('/api/v2/system/storage', headers=headers())
    assert page.status_code == 200 and page.json()['tico']['state'] == 'on'
    with api.app.state.store.read() as c:
        sealed = c.execute('SELECT secret FROM tico_storage').fetchone()['secret']
        assert sealed.startswith('sealed:v1:') and SECRET not in sealed and TOKEN not in sealed
        logged = json.dumps([dict(r) for r in c.execute('SELECT * FROM events')])
    assert SECRET not in page.text + logged and TOKEN not in page.text + logged

    from backend import health
    with api.app.state.store.read() as c:
        assert health.storage_view(c, settings)['bucket'] == 'tico-files-us', 'Health names where files go now'

    # HQ saying the same again, hourly, leaves the file store alone: uploads never wait on a fresh write check.
    generation = api.app.state.blobs._generation
    assert sync()['state'] == 'on' and api.app.state.blobs._generation == generation

    # A restart reads it back from the vault.
    from backend.blobs import Blobs
    from backend import company_storage
    again = Blobs(settings)
    company_storage.startup(api.app.state.store, api.app.state.vault, again)
    assert again.bucket == 'tico-files-us' and again.s3_key('0' * 64).startswith('c/acme/blobs/')


def test_hqs_answer_is_checked_before_anything_changes(api, tico):
    made, hq, sync = tico
    for bad, field in ((on(prefix=''), 'prefix'), (on(address='https://evil.example'), 'address'),
                       (on(state='maybe'), 'state'), (on(bucket='Not A Bucket'), 'bucket')):
        sync(bad)
        assert not api.app.state.blobs.bucket, field
        assert api.app.state.store.settings.visual_origin == ''
    # Keys that can't write are refused by the same check as the owner's own bucket, and nothing switches.
    made[KEY] = NoWrite()
    made[KEY].close = lambda: None
    sync(on())
    assert not api.app.state.blobs.bucket
    with api.app.state.store.read() as c:
        assert tico_storage.row(c) is None
    # HQ without file hosting yet (404) changes nothing either.
    hq.status = 404
    assert sync(on())['state'] == 'off' and not api.app.state.blobs.bucket


def test_a_private_tasks_file_in_tico_storage_is_refused_to_a_person_without_access(api, tico):
    """Spec 7: the file, its version and its visual link are refused; the bucket is never handed out."""
    made, hq, sync = tico
    sync(on())
    task_id = post(api, "tasks", {"owner": "ops", "title": "Private chart", "body": "x", "private": True}, "ben-test")["id"]
    made_file = api.post(f"/api/v2/tasks/{task_id}/files", json={"name": "chart.html", "text": "<p>secret</p>"},
                         headers=headers("ben-test"))
    assert made_file.status_code == 200, made_file.text
    fid, number = made_file.json()["file_id"], made_file.json()["version"]
    assert any(k.startswith('c/acme/blobs/') for k in made[KEY].objects)
    comment = api.post(f"/api/v2/tasks/{task_id}/comments", json={"text": "chart", "attachments": [f"{fid}@{number}"]},
                       headers=headers("ben-test"))
    assert comment.status_code == 200, comment.text
    [item] = comment.json()["comment"]["refs"]["attachments"]
    assert item["src"].startswith(ADDRESS + "/visuals/")
    assert api.get(item["src"]).status_code == 200                      # its reader's own signed link works
    for path in (f"/api/v2/files/{fid}", f"/api/v2/files/{fid}/versions/{number}"):
        assert api.get(path, headers=headers("cara-test")).status_code in (403, 404), path
    from backend import visuals as V
    forged = V.mint(api.app.state.visual_key, "human:cara", fid, number)
    assert api.get(ADDRESS + "/visuals/" + forged).status_code == 404
    assert 'tico-files-us' not in comment.text and 'amazonaws' not in comment.text


def test_move_existing_files_copies_every_file_and_version_and_matches_the_estimate(api, tico):
    """Spec 4: every file opens, every version is kept, GB moved matches the estimate; nothing is deleted."""
    made, hq, sync = tico
    tid = task(api)
    first = attach(api, tid, 'notes.txt', b'version one')
    second = attach(api, tid, 'notes.txt', b'version two, longer')
    other = attach(api, tid, 'other.txt', b'another file')
    sync(on())
    disk = api.app.state.blobs.directory
    before = sorted(p.name for p in disk.rglob('*') if p.is_file())

    shown = api.get('/api/v2/system/storage/move', headers=headers())
    assert shown.status_code == 200, shown.text
    estimate = shown.json()['estimate']
    size = len(b'version one') + len(b'version two, longer') + len(b'another file')
    assert (estimate['files'], estimate['bytes'], estimate['to']) == (3, size, 'tico-files-us/c/acme')
    assert 'monthly' in estimate
    assert api.post('/api/v2/system/storage/move', json={'expect_bytes': size}, headers=headers('ben-test')).status_code == 403
    changed = api.post('/api/v2/system/storage/move', json={'expect_bytes': size - 1}, headers=headers())
    assert changed.status_code == 409 and 'estimate' in changed.text

    tico_storage.start_move(api.app.state.store, api.app.state.blobs, Owner(), size, wait=True)
    move = api.get('/api/v2/system/storage/move', headers=headers()).json()
    assert move['move']['state'] == 'done' and move['move']['matches'], move
    assert (move['move']['moved_files'], move['move']['moved_bytes']) == (3, size)
    assert move['estimate']['files'] == 0, 'nothing left to move'
    stored = set(made[KEY].objects.values())
    assert {b'version one', b'version two, longer', b'another file'} <= stored
    assert sorted(p.name for p in disk.rglob('*') if p.is_file()) == before, 'the source is never deleted'
    # Reads now come from Tico storage: with this disk's copies gone, every version still opens.
    for path in disk.rglob('*'):
        if path.is_file() and not path.name.startswith('.'):
            path.unlink()
    for fid, data in ((first, b'version one'), (second, b'version two, longer'), (other, b'another file')):
        assert download(api, fid).content == data


def test_a_copy_that_does_not_verify_is_not_recorded(api, tico):
    made, hq, sync = tico
    tid = task(api)
    attach(api, tid, 'a.txt', b'good bytes')
    sync(on())
    made[KEY].corrupt = True
    shown = api.get('/api/v2/system/storage/move', headers=headers()).json()['estimate']
    tico_storage.start_move(api.app.state.store, api.app.state.blobs, Owner(), shown['bytes'], wait=True)
    move = api.get('/api/v2/system/storage/move', headers=headers()).json()
    assert move['move']['state'] == 'failed' and not move['move']['matches'] and move['move']['failed'] == 1
    assert move['estimate']['files'] == 1, 'still to move'
    with api.app.state.store.read() as c:
        assert not c.execute('SELECT 1 FROM blob_locations').fetchone()


def test_stopping_offers_the_export_and_new_files_go_back_to_own_storage(api, tico):
    """Spec 5 (app half): export offered; new files to the company's own storage; Tico's files still open."""
    made, hq, sync = tico
    tid = task(api)
    sync(on())
    in_tico = attach(api, tid, 'kept.txt', b'stored in tico')
    sync(on(state='stopped'))
    assert not api.app.state.blobs.bucket, "new files go to the server's own storage again"
    attach(api, tid, 'back.txt', b'back on the disk')
    assert b'back on the disk' not in made[KEY].objects.values()
    assert download(api, in_tico).content == b'stored in tico'

    export = api.get('/api/v2/system/storage/export', headers=headers('ben-test'))
    assert export.status_code == 403, export.text
    export = api.get('/api/v2/system/storage/export', headers=headers())
    assert export.status_code == 200 and export.headers['content-type'] == 'application/zip'
    archive = zipfile.ZipFile(io.BytesIO(export.content))
    contents = {archive.read(name) for name in archive.namelist()}
    assert {b'stored in tico', b'back on the disk'} <= contents and 'manifest.json' in archive.namelist()

    # Move files back: the same move, into the company's own storage, so nothing is lost to HQ's 30-day delete.
    estimate = api.get('/api/v2/system/storage/move', headers=headers()).json()['estimate']
    assert estimate['to'] == "this server's disk" and estimate['files'] == 1
    started = api.post('/api/v2/system/storage/move', json={'expect_bytes': estimate['bytes']}, headers=headers())
    assert started.status_code == 200, started.text
    for _ in range(200):
        move = api.get('/api/v2/system/storage/move', headers=headers()).json()['move']
        if move['state'] != 'running':
            break
        threading.Event().wait(0.02)
    assert move['state'] == 'done' and move['matches'], move
    made[KEY].offline = True
    assert download(api, in_tico).content == b'stored in tico'


def test_the_owners_export_leaves_out_files_private_to_someone_else(api, tico):
    made, hq, sync = tico
    sync(on())
    secret_task = post(api, "tasks", {"owner": "ops", "title": "Cara's", "body": "x", "private": True}, "cara-test")["id"]
    r = api.post(f"/api/v2/tasks/{secret_task}/files", json={"name": "mine.txt", "text": "cara only"},
                 headers=headers("cara-test"))
    assert r.status_code == 200, r.text
    export = api.get('/api/v2/system/storage/export', headers=headers())
    assert export.status_code == 200
    archive = zipfile.ZipFile(io.BytesIO(export.content))
    assert b'cara only' not in {archive.read(n) for n in archive.namelist()}
    assert int(export.headers['x-tico-left-out']) >= 1


def test_credits_out_existing_files_open_and_uploads_follow_the_rule(api, tico):
    """Spec 6 (app half): files stay readable; new uploads go to the company's own storage, or are refused with a
    plain reason when it can't take them."""
    made, hq, sync = tico
    tid = task(api)
    sync(on())
    in_tico = attach(api, tid, 'kept.txt', b'stored in tico')
    sync(on(state='credits_out'))
    assert download(api, in_tico).content == b'stored in tico'
    own = attach(api, tid, 'own.txt', b'on the server disk now')
    assert b'on the server disk now' not in made[KEY].objects.values()
    assert download(api, own).content == b'on the server disk now'

    # With the company's own bucket refusing writes, the upload is refused with a plain reason.
    from backend import company_storage
    with api.app.state.store.transaction() as c:
        c.execute("INSERT INTO company_storage(id,bucket,prefix,region,access_key_id,secret,active,created,created_by) "
                  "VALUES('own','acme-files','','us-west-2','AKIAEXAMPLENOWR0001',?,1,'2026-10-23T00:00:00Z','human:ben')",
                  (api.app.state.vault.cipher.seal(c, 'company_storage:own', 'example-secret'),))
    company_storage.apply(api.app.state.store, api.app.state.vault, api.app.state.blobs, copy=False, checked=True)
    refused = api.post(f'/api/v2/tasks/{tid}/files', files={'file': ('late.txt', b'no room')}, headers=headers('ana-test'))
    assert refused.status_code == 503, refused.text
    assert refused.json()['error']['code'] == 'storage_paused'
    assert 'Gateway credits have run out' in refused.text and 'AccessDenied' in refused.text
    assert SECRET not in refused.text
    assert download(api, in_tico).content == b'stored in tico'

    # Credits added: HQ says on again, and new files go to Tico storage.
    sync(on())
    attach(api, tid, 'again.txt', b'tico again')
    assert b'tico again' in made[KEY].objects.values()

