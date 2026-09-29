import subprocess

import pytest

from clients import doc_sources as D


def test_import_only_regular_docs_in_designated_folder(monkeypatch):
    calls = []
    def run(args, **kwargs):
        calls.append(args)
        if 'ls-tree' in args:
            out = (b'100644 blob a\tdocs/guide.md\0'
                   b'120000 blob b\tdocs/secret.md\0'
                   b'100644 blob c\tother/private.md\0'
                   b'100644 blob d\tdocs/app.py\0'
                   b'100644 blob e\tdocs-old/guide.md\0')
        elif 'rev-parse' in args:
            out = b'1234567890\n'
        elif '-s' in args:
            out = b'24\n'
        elif 'cat-file' in args:
            out = b'# Guide\nSetup instructions'
        else:
            out = b''
        return subprocess.CompletedProcess(args, 0, out, b'')
    monkeypatch.setattr(D.subprocess, 'run', run)
    docs = D.fetch({'repo': 'acme/handbook', 'folder': 'docs'}, 'today')
    assert len(docs) == 1
    assert docs[0]['path'] == 'docs/guide.md'
    assert docs[0]['docs_folder'] == 'docs'
    assert docs[0]['git_repo'] == 'https://github.com/acme/handbook'
    assert 'Setup instructions' in docs[0]['search']
    assert all('core.hooksPath=/dev/null' in call for call in calls)
    assert not any('checkout' in call for call in calls)
