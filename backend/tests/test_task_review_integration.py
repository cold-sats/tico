"""In-process release contract: streamed versions, previews, reviews and the next turn."""
import base64
import hashlib
import json
from pathlib import Path
import struct
import zlib

import pytest

from backend.tests.test_api import api, assign, claim, headers, post, ready, runner  # noqa: F401
from backend.tests.test_task_review import ask, get, task
from runner.service import Runner


def png(color):
    def chunk(kind, data):
        return struct.pack('>I', len(data)) + kind + data + struct.pack('>I', zlib.crc32(kind + data))
    return (b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('>IIBBBBB', 16, 8, 8, 2, 0, 0, 0))
            + chunk(b'IDAT', zlib.compress((b'\x00' + bytes(color) * 16) * 8)) + chunk(b'IEND', b''))


def task_row(api, tid):
    return next(row for row in get(api, 'tasks')['tasks'] if row['id'] == tid)


def test_streamed_task_versions_review_and_next_wake(api, monkeypatch):
    worker = api.app.state.file_metadata
    worker.stop.set()
    worker.wake.set()
    # Supplied posters must work on the standard server without optional video tools.
    monkeypatch.setattr('backend.file_metadata.shutil.which', lambda _: None)
    tid = task(api)
    assert task_row(api, tid)['cover'] is None
    assert task_row(api, tid)['open_asks'] == 0
    machine = runner(api)
    assign(api, machine, 'ops')
    ready(api, machine, ['ops'])
    attempt = claim(api, machine, 'ops')
    token = attempt['token']
    post(api, f"attempts/{attempt['id']}/started", {'thread_id': 'task-review'}, machine['token'])
    first_image, second_image = png((0, 0, 255)), png((255, 0, 0))
    video = Path(__file__).with_name('fixtures').joinpath('task-review.mp4').read_bytes()
    contents = {
        'image.png': (first_image, second_image),
        'video.mp4': (video, video + struct.pack('>I', 10) + b'freev2'),
        'script.md': (b'# Script v1\nFirst draft.', b'# Script v2\nRevised opening.'),
    }
    ids = {}
    for name, versions in contents.items():
        for number, data in enumerate(versions, 1):
            files = {'file': (name, data)}
            fields = {'note': f'Version {number}'}
            if name == 'video.mp4':
                files['poster'] = ('poster.png', second_image, 'image/png')
            if name == 'script.md' and number == 2:
                fields['ask'] = json.dumps(ask())
            h = headers(token)
            made = api.post(f'/api/v2/tasks/{tid}/files', data=fields, files=files, headers=h)
            assert made.status_code == 200, made.text
            result = made.json()
            assert result['version'] == number
            assert result['file']['file_id'] == result['file_id']
            assert result['file']['version'] == number
            if number == 1:
                ids[name] = result['file_id']
            assert result['file_id'] == ids[name]
            replay = api.post(f'/api/v2/tasks/{tid}/files', data=fields, files=files, headers=h)
            assert replay.json() == result
            # Exercise the real derivation code, deterministically outside the background loop.
            with api.app.state.store.read() as c:
                row = dict(c.execute('SELECT b.*,m.poster_blob_id FROM blobs b JOIN blob_media m '
                                     'ON m.blob_id=b.id WHERE b.id=?', (result['file']['id'],)).fetchone())
            worker.process(row)
    before = task_row(api, tid)
    assert before['open_asks'] == 1
    assert before['cover']['url'] == f"/api/v2/files/{ids['video.mp4']}/poster?v=2"
    assert api.get(before['cover']['url'], headers=headers()).content == second_image
    listed = {f['name']: f for f in get(api, f'tasks/{tid}/files')['files']}
    assert len(listed) == 3
    for name, versions in contents.items():
        file = listed[name]
        assert file['id'] == ids[name] and file['current_version'] == 2
        assert [v['n'] for v in file['versions']] == [2, 1]
        for v in file['versions']:
            expected = versions[v['n'] - 1]
            assert v['by'] == 'bot:ops' and v['note'] == f"Version {v['n']}"
            assert v['mime'] == file['mime'] and v['size'] == len(expected)
            assert v['sha256'] == hashlib.sha256(expected).hexdigest()
            response = api.get(v['url'], headers=headers())
            assert response.status_code == 200 and response.content == expected
            assert response.headers['cache-control'] == 'private, max-age=31536000, immutable'
            assert response.headers['etag'] == '"' + v['sha256'] + '"'
            head = api.head(v['url'], headers=headers())
            assert head.status_code == 200 and head.content == b''
            assert head.headers['content-length'] == str(len(expected))
            assert head.headers['cache-control'] == response.headers['cache-control']
            assert api.get(v['url']).status_code == 401
            if name == 'image.png':
                assert (v['width'], v['height'], v['media_state']) == (16, 8, 'ready')
                if v['thumb_url']:
                    assert api.get(v['thumb_url'], headers=headers()).status_code == 200
            elif name == 'video.mp4':
                assert v['poster_url'] and v['media_state'] == 'ready'
                poster = api.head(v['poster_url'], headers=headers())
                assert poster.status_code == 200 and poster.headers['content-length'] == str(len(second_image))
    script = listed['script.md']['versions'][0]
    assert script['ask']['by'] == 'bot:ops' and script['answers'] == []
    assert script['ask']['questions'][0]['id'] == 'verdict'
    assert script['ask']['who'] is None
    for number, data in enumerate(contents['video.mp4'], 1):
        partial = api.get(f"/api/v2/files/{ids['video.mp4']}?v={number}",
                          headers={**headers(), 'Range': 'bytes=2-12'})
        assert partial.status_code == 206 and partial.content == data[2:13]
        assert partial.headers['content-range'] == f'bytes 2-12/{len(data)}'
        assert 'immutable' in partial.headers['cache-control']
    comment = post(api, f'tasks/{tid}/comments', {'text': 'Review the second script.',
                   'attachments': [ids['script.md'] + '@2']}, token)['comment']
    attached = comment['refs']['attachments'][0]
    assert (attached['id'], attached['name'], attached['version']) == (ids['script.md'], 'script.md', 2)
    post(api, f"attempts/{attempt['id']}/complete", {'outcome': 'completed', 'text': 'Ready for review.', 'last_seq': 0}, machine['token'])
    answer = post(api, f'tasks/{tid}/answers', {
        'target': {'file': ids['script.md'], 'version': 2}, 'answers': {'verdict': ['Approve']}})
    assert answer['answer']['by'] == 'human:ana'
    assert task_row(api, tid)['open_asks'] == 0
    assert task_row(api, tid)['cover'] == before['cover']
    versions = get(api, f'tasks/{tid}/files')['files']
    script = next(f for f in versions if f['id'] == ids['script.md'])['versions'][0]
    assert script['answers'] == [answer['answer']]
    comments = get(api, f'tasks/{tid}/comments')['comments']
    question = next(m for m in comments if m['kind'] == 'ask')
    assert question['ask'] == script['ask'] and question['answers'] == script['answers']
    next_turn = claim(api, machine, 'ops')
    assert next_turn['message']['refs']['answer'] == answer['answer']
    prompt = Runner.__new__(Runner).prompt(next_turn)
    assert json.loads(next(line[8:] for line in prompt.splitlines() if line.startswith('answer: '))) == answer['answer']
    assert answer['comment']['body'] in prompt


@pytest.mark.parametrize('multi', [False, True])
def test_page_other_answer_omits_unselected_question_ids(api, multi):
    tid = task(api)
    questions = ask()
    if multi:
        questions['questions'].append({**questions['questions'][0], 'id': 'opening', 'other': False})
    comment = post(api, f'tasks/{tid}/comments', {'text': 'Review', 'ask': questions})['comment']
    target = {'comment': comment['id']}
    picked = {'opening': ['Approve']} if multi else {}
    answer = post(api, f'tasks/{tid}/answers', {'target': target, 'answers': picked, 'other': 'Change the ending.'}, 'ben-test')
    assert answer['answer']['answers'] == {'verdict': [], **picked}
    assert answer['answer']['other'] == 'Change the ending.'
    assert get(api, f'tasks/{tid}')['task']['open_asks'] == 0
    assert api.post(f'/api/v2/tasks/{tid}/answers', json={'target': target, 'answers': picked},
                    headers=headers('ben-test')).status_code == 422
    if multi:
        assert api.post(f'/api/v2/tasks/{tid}/answers', json={'target': target, 'answers': {}, 'other': 'Change it.'},
                        headers=headers('ben-test')).status_code == 422


def test_streamed_attachment_openapi_documents_both_request_shapes(api):
    document = get(api, 'openapi.json')
    content = document['paths']['/api/v2/tasks/{tid}/files']['post']['requestBody']['content']
    json_schema = content['application/json']['schema']
    assert json_schema['required'] == ['name']
    assert {'name', 'text', 'content_base64', 'note', 'ask'} == set(json_schema['properties'])
    multipart = content['multipart/form-data']['schema']
    assert multipart['required'] == ['file']
    assert {'file', 'name', 'note', 'ask', 'poster'} == set(multipart['properties'])
    assert multipart['properties']['file']['format'] == 'binary'
    assert multipart['properties']['ask']['type'] == 'string'


def test_posters_are_available_before_processing_and_legacy_previews_survive_adoption(api):
    from backend.auth import Identity
    from backend.blobs import register
    worker = api.app.state.file_metadata
    worker.stop.set()
    worker.wake.set()
    tid = task(api)
    image = png((0, 0, 255))
    blobs = api.app.state.blobs
    digest = blobs.put(image, 'image/png')
    with api.app.state.store.transaction() as c:
        old = register(c, Identity('human:ana', 'owner'), digest, len(image), 'image.png', 'image/png')
        preview = register(c, Identity('human:ana', 'owner'), digest, len(image), 'preview.png', 'image/png')
        c.execute('INSERT INTO task_assets VALUES(?,?)', (tid, old['id']))
        c.execute("INSERT INTO blob_media(blob_id,width,height,thumb_blob_id,media_state) VALUES(?,16,8,?,'ready')",
                  (old['id'], preview['id']))
    adopted = post(api, f'tasks/{tid}/files', {'name': 'image.png', 'content_base64': base64.b64encode(image).decode()})
    assert adopted['file_id'] == old['id'] and adopted['version'] == 2
    versions = get(api, f'tasks/{tid}/files')['files'][0]['versions']
    first = versions[1]
    assert (first['width'], first['height'], first['media_state']) == (16, 8, 'ready')
    assert api.get(first['thumb_url'], headers=headers()).content == image
    assert api.head(first['thumb_url'], headers=headers()).status_code == 200
    assert api.get(first['thumb_url']).status_code == 401
    assert versions[0]['media_state'] == 'pending'
    made = api.post(f'/api/v2/tasks/{tid}/files', headers=headers(), files={
        'file': ('video.mp4', Path(__file__).with_name('fixtures').joinpath('task-review.mp4').read_bytes(), 'video/mp4'),
        'poster': ('poster.png', image, 'image/png')})
    assert made.status_code == 200, made.text
    video = next(f for f in get(api, f'tasks/{tid}/files')['files'] if f['id'] == made.json()['file_id'])
    assert video['versions'][0]['media_state'] == 'pending'
    assert api.get(video['versions'][0]['poster_url'], headers=headers()).content == image
    assert api.get(task_row(api, tid)['cover']['url'], headers=headers()).content == image
