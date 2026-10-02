"""Attachment storage contract; fake S3 only, no network or large allocations."""
import base64
import hashlib
import io
import json
import shutil
import sqlite3
import struct
import subprocess
import sys
import threading
from types import SimpleNamespace
from urllib.parse import parse_qs, urlsplit

import pytest
from botocore.exceptions import ClientError
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa

from backend.blobs import Blobs, disposition
from backend.config import Settings
from backend.file_delivery import byte_range, signed_url
from backend.file_metadata import dimensions
from backend.store import Problem
from backend.tests.test_api import api, headers, post  # noqa: F401
from backend.tests.test_files import publish, turn
from backend.tests.test_runner import live  # noqa: F401
from clients.tico import MultipartBody


class S3:
    def __init__(self):
        self.objects, self.calls, self.parts = {}, [], []
        self.offline, self.corrupt = False, False

    def put_object(self, **kw):
        self.calls.append(kw)
        if kw['Key'] in self.objects:
            raise ClientError({'Error': {'Code': 'PreconditionFailed'}}, 'PutObject')
        body = kw['Body']
        if hasattr(body, 'read'):
            chunks = []
            while chunk := body.read(64 * 1024):
                chunks.append(chunk)
            body = b''.join(chunks)
        self.objects[kw['Key']] = body + (b'bad' if self.corrupt else b'')

    def get_object(self, **kw):
        if self.offline:
            raise RuntimeError('offline')
        data = self.objects[kw['Key']]
        if 'Range' in kw:
            start, end = byte_range(kw['Range'], len(data))
            data = data[start:end + 1]
        return {'Body': io.BytesIO(data)}

    def create_multipart_upload(self, **kw):
        self.calls.append(kw)
        self.parts = []
        return {'UploadId': 'upload'}

    def upload_part(self, **kw):
        self.parts.append(kw['Body'])
        return {'ETag': str(kw['PartNumber'])}

    def complete_multipart_upload(self, **kw):
        assert kw['IfNoneMatch'] == '*'
        self.objects[kw['Key']] = b''.join(self.parts)

    def abort_multipart_upload(self, **kw):
        self.aborted = True


def test_stream_hash_and_s3_first_multipart(tmp_path):
    s3 = S3()
    storage = Blobs(Settings(db_path=tmp_path / 'hub.db', blob_bucket='private'), s3)
    class Stream(io.BytesIO):
        def read(self, size=-1):
            assert 0 < size <= 1024 * 1024
            return super().read(size)
    small = b'streamed bytes'
    digest = storage.put_stream(Stream(small), 'text/plain')
    assert digest == hashlib.sha256(small).hexdigest()
    assert hasattr(s3.calls[-1]['Body'], 'read')
    assert storage.get(digest) == small
    big = b'v' * (8 * 1024 ** 2 + 1)
    digest = storage.put_stream(Stream(big), 'video/mp4')
    assert len(s3.parts) == 2 and storage.get(digest) == big
    assert s3.calls[-1]['ContentType'] == 'video/mp4'
    assert s3.calls[-1]['CacheControl'] == 'private, max-age=31536000, immutable'
    assert not list(tmp_path.rglob('.upload-*'))
    assert not (storage.directory / storage.key(digest)).exists()
    with pytest.raises(Problem) as error:
        storage.put_stream(Stream(small), max_bytes=1)
    assert error.value.status == 413


@pytest.mark.parametrize('mime,inline', [('image/png', True), ('image/jpeg', True), ('image/gif', True),
    ('image/webp', True), ('video/mp4', True), ('video/webm', True), ('video/quicktime', True),
    ('audio/mpeg', True), ('application/pdf', True), ('text/plain', True), ('text/markdown', True),
    ('text/csv', True), ('image/svg+xml', False), ('text/html', False), ('application/octet-stream', False)])
def test_safe_disposition(mime, inline):
    assert disposition(mime) == ('inline' if inline else 'attachment')


def test_signed_url_signature_and_hour_expiry():
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pem = key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption())
    settings = SimpleNamespace(cdn_url='https://cdn.example.com', cdn_key_id='key')
    digest = hashlib.sha256(b'file').hexdigest()
    url = signed_url(settings, digest, pem, now=1000)
    parsed = urlsplit(url)
    params = parse_qs(parsed.query)
    assert params['Expires'] == ['4600'] and params['Key-Pair-Id'] == ['key']
    signature = base64.b64decode(params['Signature'][0].translate(str.maketrans('-_~', '+=/')))
    policy = json.dumps({'Statement': [{'Resource': url.split('?')[0], 'Condition': {
        'DateLessThan': {'AWS:EpochTime': 4600}}}]}, separators=(',', ':')).encode()
    key.public_key().verify(signature, policy, padding.PKCS1v15(), hashes.SHA1())
    assert parsed.path == '/' + Blobs.key(digest)


def task(api):
    return post(api, 'tasks', {'owner': 'ops', 'title': 'Review media', 'body': 'Open the file.'})['id']


def attach(api, tid, name, data):
    response = api.post(f'/api/v2/tasks/{tid}/files', files={'file': (name, data)},
                        headers=headers('ana-test'))
    assert response.status_code == 200, response.text
    return response.json()['file']['id']


def test_multipart_range_cache_etag_limits_and_legacy(api):
    tid = task(api)
    bid = attach(api, tid, 'sample.txt', b'0123456789')
    url = '/api/v2/files/' + bid
    h = headers('ana-test')
    full = api.get(url, headers=h)
    assert full.content == b'0123456789' and full.headers['cache-control'] == 'no-cache'
    assert full.headers['content-type'].startswith('text/plain')
    assert full.headers['content-disposition'].startswith('inline')
    assert full.headers['x-content-type-options'] == 'nosniff'
    assert 'sandbox' in full.headers['content-security-policy']
    for value, expected in [('bytes=2-4', b'234'), ('bytes=-3', b'789'), ('bytes=7-', b'789')]:
        response = api.get(url, headers={**h, 'Range': value})
        assert response.status_code == 206 and response.content == expected
        assert response.headers['accept-ranges'] == 'bytes'
        assert response.headers['content-range'].endswith('/10')
    for value in ('bytes=10-', 'bytes=4-2', 'bytes=-0', 'bytes=0-1,4-5'):
        response = api.get(url, headers={**h, 'Range': value})
        assert response.status_code == 416 and response.headers['content-range'] == 'bytes */10'
    assert api.get(url, headers={**h, 'If-None-Match': full.headers['etag']}).status_code == 304
    assert 'immutable' in api.get(url + '?v=1', headers=h).headers['cache-control']
    assert api.get(url + '/poster?v=1', headers=h).status_code == 404
    assert api.get(url).status_code == 401
    assert api.app.state.store.settings.upload_max_bytes == 2 * 1024 ** 3
    too_large = api.post(f'/api/v2/tasks/{tid}/files', headers={**h, 'Content-Type': 'multipart/form-data; boundary=x',
        'Content-Length': str(2 * 1024 ** 3 + 11_000_001)})
    assert too_large.status_code == 413 and '2147483648' in too_large.text
    api.app.state.store.settings.upload_max_bytes = 4
    rejected = api.post(f'/api/v2/tasks/{tid}/files', files={'file': ('large.txt', b'12345')}, headers=h)
    assert rejected.status_code == 413 and '4 bytes' in rejected.text
    legacy = post(api, f'tasks/{tid}/files', {'name': 'legacy.txt', 'content_base64': base64.b64encode(b'old bytes').decode()})
    assert api.get(legacy['file']['url'], headers=h).content == b'old bytes'
    dangerous = post(api, f'tasks/{tid}/files', {'name': 'page.html', 'text': '<script>example</script>'})
    assert api.get(dangerous['file']['url'], headers=h).headers['content-disposition'].startswith('attachment')


def test_copy_verified_and_fallback_keeps_local(api):
    bid = attach(api, task(api), 'source.txt', b'retained bytes')
    blobs = api.app.state.blobs
    with api.app.state.store.read() as c:
        digest = c.execute('SELECT digest FROM blobs WHERE id=?', (bid,)).fetchone()[0]
    s3 = S3()
    blobs.bucket, blobs._s3 = 'private', s3
    blobs.copy_local(api.app.state.store, threading.Event(), interval=0)
    assert blobs.copy_status == {'done': 1, 'total': 1, 'running': False, 'error': ''}
    with api.app.state.store.read() as c:
        assert c.execute('SELECT digest FROM blob_locations').fetchone()[0] == digest
    assert (blobs.directory / blobs.key(digest)).exists()
    s3.offline = True
    assert blobs.get(digest) == b'retained bytes'
    assert b''.join(blobs.open_range(digest, 2, 4)) == b'tai'
    with api.app.state.store.transaction() as c:
        c.execute('DELETE FROM blob_locations')
    s3.offline, s3.corrupt = False, True
    s3.objects.clear()
    blobs.copy_local(api.app.state.store, threading.Event(), interval=0)
    assert blobs.copy_status['error'] and blobs.copy_status['done'] == 0
    assert blobs.get(digest) == b'retained bytes'
    with api.app.state.store.read() as c:
        assert c.execute('SELECT COUNT(*) FROM blob_locations').fetchone()[0] == 0


def test_cdn_redirect_and_blob_version_metadata(api, monkeypatch):
    _, attempt = turn(api)
    made = publish(api, attempt, name='poster.png', text='header').json()['file']['id']
    blobs = api.app.state.blobs
    settings = api.app.state.store.settings
    settings.cdn_url, settings.cdn_key_id, blobs.bucket = 'https://cdn.example.com', 'test-key', 'private'
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pem = key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption())
    monkeypatch.setattr('backend.file_delivery.private_key', lambda *args: pem)
    with api.app.state.store.transaction() as c:
        version = c.execute('SELECT * FROM bot_file_versions WHERE file_id=?', (made,)).fetchone()
        c.execute('INSERT INTO blob_locations VALUES(?,?,?)', (version['digest'], 'private', 'now'))
        c.execute("UPDATE bot_file_versions SET width=20,height=10,media_state='ready' WHERE file_id=?", (made,))
        with pytest.raises(sqlite3.IntegrityError):
            c.execute("UPDATE bot_file_versions SET digest='changed' WHERE file_id=?", (made,))
    response = api.get('/api/v2/files/' + made + '?v=1', headers=headers('ben-test'), follow_redirects=False)
    assert response.status_code == 302 and response.headers['cache-control'] == 'private, no-store'
    assert 'Signature=' in response.headers['location']
    assert api.get('/api/v2/files/' + made + '?v=2', headers=headers('ben-test')).status_code == 404
    meta = api.get('/api/v2/files/' + made + '/meta', headers=headers('ben-test')).json()
    assert meta['width'] == 20 and meta['height'] == 10


def test_header_parsing_without_pillow(monkeypatch, tmp_path):
    from backend.file_metadata import image
    monkeypatch.setitem(sys.modules, 'PIL', None)
    png = b'\x89PNG\r\n\x1a\n' + b'\x00' * 8 + struct.pack('>II', 640, 320)
    source = tmp_path / 'source.png'
    source.write_bytes(png)
    assert image(source, tmp_path / 'thumb.jpg') == (640, 320, None)
    assert dimensions(io.BytesIO(b'GIF89a' + struct.pack('<HH', 20, 10))) == (20, 10)
    webp = b'RIFF' + b'\x00' * 4 + b'WEBPVP8X' + b'\x00' * 8 + (639).to_bytes(3, 'little') + (319).to_bytes(3, 'little')
    assert dimensions(io.BytesIO(webp)) == (640, 320)


def test_metadata_worker_images_supplied_poster_and_missing_tools(api, monkeypatch):
    Image = pytest.importorskip('PIL.Image')
    # Keep the background worker idle while exercising the same worker synchronously.
    worker = api.app.state.file_metadata
    worker.stop.set()
    worker.wake.set()
    data = io.BytesIO()
    Image.new('RGB', (800, 400), 'blue').save(data, 'PNG')
    tid = task(api)
    response = api.post(f'/api/v2/tasks/{tid}/files', files={'file': ('image.png', data.getvalue()),
                        'poster': ('poster.png', data.getvalue())}, headers=headers('ana-test'))
    assert response.status_code == 200, response.text
    bid = response.json()['file']['id']
    with api.app.state.store.read() as c:
        row = dict(c.execute('SELECT b.*,m.poster_blob_id FROM blobs b JOIN blob_media m ON b.id=m.blob_id WHERE b.id=?', (bid,)).fetchone())
    worker.process(row)
    meta = api.get('/api/v2/files/' + bid + '/meta', headers=headers('ana-test')).json()
    assert meta['width'] == 800 and meta['height'] == 400 and meta['media_state'] == 'ready'
    for kind, limit in [('poster', 800), ('thumb', 480)]:
        response = api.get(f'/api/v2/files/{bid}/{kind}?v=1', headers=headers('ana-test'))
        assert response.status_code == 200 and 'immutable' in response.headers['cache-control']
        with Image.open(io.BytesIO(response.content)) as preview:
            assert max(preview.size) <= limit
    video = attach(api, tid, 'movie.mp4', b'no tools needed')
    monkeypatch.setattr('backend.file_metadata.shutil.which', lambda _: None)
    with api.app.state.store.read() as c:
        row = dict(c.execute('SELECT * FROM blobs WHERE id=?', (video,)).fetchone())
    worker.process(row)
    assert api.get('/api/v2/files/' + video + '/meta', headers=headers('ana-test')).json()['media_state'] == 'none'


def test_multipart_client_replay_and_bounded_reads(tmp_path):
    path = tmp_path / 'media.mp4'
    path.write_bytes(b'v' * (1024 * 1024 + 10))
    body = MultipartBody({'file': path}, {'name': 'media.mp4', 'ask': {'questions': []}})
    first, second = list(body), list(body)
    assert first == second and sum(map(len, first)) == body.size
    assert max(map(len, first)) <= 1024 * 1024


@pytest.mark.skipif(not shutil.which('ffmpeg') or not shutil.which('ffprobe'), reason='optional video tools')
def test_video_metadata_with_tools(api, tmp_path):
    worker = api.app.state.file_metadata
    worker.stop.set()
    worker.wake.set()
    video = tmp_path / 'clip.mp4'
    subprocess.run([shutil.which('ffmpeg'), '-v', 'error', '-f', 'lavfi', '-i', 'color=c=blue:s=64x32:d=1',
                    '-c:v', 'mpeg4', str(video)], check=True)
    bid = attach(api, task(api), 'clip.mp4', video.read_bytes())
    with api.app.state.store.read() as c:
        blob = dict(c.execute('SELECT * FROM blobs WHERE id=?', (bid,)).fetchone())
    worker.process(blob)
    meta = api.get('/api/v2/files/' + bid + '/meta', headers=headers('ana-test')).json()
    assert (meta['width'], meta['height'], meta['duration_ms']) == (64, 32, 1000)
    assert meta['poster_blob_id'] and meta['media_state'] == 'ready'


def test_client_streams_real_http_upload(api, live, tmp_path):
    from clients.tico import Client
    source = tmp_path / "source.txt"
    source.write_bytes(b"streaming over HTTP")
    client = Client(live, "ana-test")
    assert client.features()["task_files_multipart"]
    made = client.post_multipart(f"tasks/{task(api)}/files", {"file": source}, {"name": source.name})
    assert client.download(made["file"]["id"]) == b"streaming over HTTP"


def test_worker_fills_immutable_published_version(api):
    Image = pytest.importorskip("PIL.Image")
    worker = api.app.state.file_metadata
    worker.stop.set()
    worker.wake.set()
    _, attempt = turn(api)
    data = io.BytesIO()
    Image.new("RGB", (100, 50)).save(data, "PNG")
    made = api.post("/api/v2/files/uploads", json={"name": "photo.png", "content_base64": base64.b64encode(data.getvalue()).decode()},
                    headers=headers(attempt["token"]))
    assert made.status_code == 200, made.text
    fid = made.json()["file"]["id"]
    with api.app.state.store.read() as c:
        blob = dict(c.execute("SELECT b.* FROM blobs b JOIN bot_file_versions v ON v.blob_id=b.id WHERE v.file_id=?", (fid,)).fetchone())
    worker.process(blob)
    with api.app.state.store.read() as c:
        version = c.execute("SELECT * FROM bot_file_versions WHERE file_id=?", (fid,)).fetchone()
        assert (version["width"], version["height"], version["media_state"]) == (100, 50, "ready")
        assert version["thumb_blob_id"]


@pytest.mark.skipif(not shutil.which("pdftoppm"), reason="optional PDF tool")
def test_pdf_page_one_poster(api):
    from pypdf import PdfWriter
    worker = api.app.state.file_metadata
    worker.stop.set()
    worker.wake.set()
    data = io.BytesIO()
    writer = PdfWriter()
    writer.add_blank_page(width=300, height=200)
    writer.write(data)
    bid = attach(api, task(api), "page.pdf", data.getvalue())
    with api.app.state.store.read() as c:
        blob = dict(c.execute("SELECT * FROM blobs WHERE id=?", (bid,)).fetchone())
    worker.process(blob)
    meta = api.get("/api/v2/files/" + bid + "/meta", headers=headers("ana-test")).json()
    assert meta["media_state"] == "ready" and meta["poster_blob_id"]
    assert max(meta["width"], meta["height"]) <= 640


def test_storage_migration_preserves_old_version_and_reapplies():
    from backend.files import SCHEMA
    from backend.storage_schema import SCHEMA as STORAGE_SCHEMA
    from backend.store import H
    c = sqlite3.connect(':memory:')
    c.row_factory = sqlite3.Row
    c.executescript(SCHEMA)
    c.execute('CREATE TABLE blobs(id TEXT PRIMARY KEY)')
    c.execute("INSERT INTO blobs VALUES('blob')")
    c.execute("INSERT INTO bot_files(id,bot,scope,identity,title,kind,locator,first_activity_at,last_activity_at) "
              "VALUES('file','bot','task:task','old','Old report','document','tico_blob','then','then')")
    old = ('file', 1, 'blob', 'digest', None, 10, 'report.txt', 'text/plain', None, None, None, 'bot:bot', 'then')
    c.execute('INSERT INTO bot_file_versions VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)', old)
    H._apply(c, STORAGE_SCHEMA)
    H._apply(c, STORAGE_SCHEMA)  # hub 20 and cloud 53 both use the idempotent apply helper
    version = c.execute('SELECT * FROM bot_file_versions').fetchone()
    assert tuple(version)[:13] == old and version['media_state'] == 'pending'
    c.execute('UPDATE bot_file_versions SET width=10,height=5')
    with pytest.raises(sqlite3.IntegrityError):
        c.execute("UPDATE bot_file_versions SET blob_id='different'")
    c.close()
