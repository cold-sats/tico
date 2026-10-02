"""CLI feature negotiation and credential-free CDN downloads."""
import hashlib
import io
from pathlib import Path
import urllib.error
from unittest.mock import Mock

import pytest

from clients import hubcli, hubtools, remotecli
from clients.tico import APIError, Client


@pytest.mark.parametrize('multipart', [False, True])
def test_task_attach_negotiates_without_read_bytes(monkeypatch, tmp_path, multipart):
    path = tmp_path / 'draft.txt'
    path.write_bytes(b'  hello\n')
    monkeypatch.setenv('HUB_API_URL', 'https://api.example.com')
    client = Mock()
    client.get.return_value = {'actor': 'human:ana'}
    client.features.return_value = {'task_files_multipart': multipart}
    monkeypatch.setattr(remotecli, 'Client', lambda *args, **kw: client)
    monkeypatch.setattr(Path, 'read_bytes', lambda _: pytest.fail('whole file read'))
    args = hubcli.parser().parse_args(['task', 'attach', 'task', str(path)])
    remotecli.run(args)
    if multipart:
        client.post_multipart.assert_called_once_with('tasks/task/files', {'file': path}, {'name': path.name}, key=None)
        client.post.assert_not_called()
    else:
        client.post.assert_called_once_with('tasks/task/files', {'name': path.name, 'text': '  hello\n'}, key=None)
        client.post_multipart.assert_not_called()


def test_old_server_refuses_large_before_open(monkeypatch, tmp_path):
    path = tmp_path / 'movie.mp4'
    with path.open('wb') as file:
        file.truncate(10_000_001)
    monkeypatch.setenv('HUB_API_URL', 'https://api.example.com')
    client = Mock()
    client.get.return_value = {'actor': 'human:ana'}
    client.features.return_value = {}
    monkeypatch.setattr(remotecli, 'Client', lambda *args, **kw: client)
    monkeypatch.setattr(Path, 'open', lambda *args: pytest.fail('large file opened'))
    args = hubcli.parser().parse_args(['task', 'attach', 'task', str(path)])
    with pytest.raises(APIError) as exc:
        remotecli.run(args)
    assert exc.value.status == 413


def test_mcp_server_does_not_read_local_paths():
    class Server:
        def post(self, *args, **kw):
            pytest.fail('server path must be refused first')
    with pytest.raises(ValueError, match='Computer'):
        hubtools.task_attach(Server(), {'id': 'task', 'name': 'draft.txt', 'path': '/private/server-file'})


def test_binary_signed_redirect_drops_bearer_and_verifies():
    data = b'cdn bytes'
    digest = hashlib.sha256(data).hexdigest()
    class Opener:
        def __init__(self):
            self.calls = []
        def open(self, request, timeout=None):
            self.calls.append(request)
            if len(self.calls) == 1:
                raise urllib.error.HTTPError(request.full_url, 302, 'Found', {
                    'Location': 'https://cdn.example.com/blobs/file?Expires=1&Signature=test&Key-Pair-Id=key',
                    'X-Content-SHA256': digest}, io.BytesIO())
            assert request.get_header('Authorization') is None
            assert request.get_header('X-tico-processing-token') is None
            return io.BytesIO(data)
    client = Client('https://api.example.com', 'private-token')
    client.opener = Opener()
    assert client.download('file') == data
    assert len(client.opener.calls) == 2


def test_multipart_retry_replays_same_parts_and_key(tmp_path, monkeypatch):
    path = tmp_path / 'draft.txt'
    path.write_bytes(b'draft')
    class Response(io.BytesIO):
        headers = {}
    class Opener:
        calls = []
        def open(self, request, timeout=None):
            self.calls.append((request, b''.join(request.data)))
            if len(self.calls) == 1:
                raise urllib.error.HTTPError(request.full_url, 503, 'Down', {}, io.BytesIO(b'{}'))
            return Response(b'{"file": "done"}')
    monkeypatch.setattr('clients.tico.time.sleep', lambda _: None)
    client = Client('https://api.example.com', 'private-token', retries=1)
    client.opener = Opener()
    assert client.post_multipart('tasks/task/files', {'file': path}, {'name': 'draft.txt'}, key='same') == {'file': 'done'}
    first, second = client.opener.calls
    assert first[1] == second[1]
    assert first[0].get_header('Idempotency-key') == second[0].get_header('Idempotency-key') == 'same'
    assert int(first[0].get_header('Content-length')) == len(first[1])
