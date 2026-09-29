"""Import designated documentation folders without executing repository code."""
import hashlib
import os
from pathlib import Path, PurePosixPath
import re
import subprocess
import tempfile
from urllib.parse import urlsplit, quote


def normalize(data):
    repo = data['repo'].strip()
    if re.fullmatch(r'[\w.-]+/[\w.-]+', repo):
        repo = 'https://github.com/' + repo
    ssh = re.fullmatch(r'git@([a-zA-Z0-9.-]+):([\w./-]+)', repo)
    parsed = urlsplit(repo)
    if not ssh and (parsed.scheme != 'https' or not parsed.hostname or parsed.username
                    or parsed.password or parsed.query or parsed.fragment or not parsed.path.strip('/')):
        raise ValueError('Use an HTTPS Git URL, git@host:org/repo.git, or GitHub owner/repo. Do not include credentials.')
    if any(ord(char) < 33 for char in repo):
        raise ValueError('The repository URL cannot contain whitespace or control characters.')
    folder = data.get('folder', 'docs').strip().strip('/')
    if data.get('folder', '').strip().startswith('/') or '\\' in folder or '..' in folder.split('/'):
        raise ValueError('Choose a folder relative to the repository root, without .. components.')
    folder = str(PurePosixPath(folder))
    if any(ord(char) < 32 for char in folder) or '.git' in folder.split('/'):
        raise ValueError('Choose a documentation folder outside .git.')
    branch = data.get('branch', '').strip()
    if branch and (branch.startswith('-') or not re.fullmatch(r'[\w./-]+', branch) or '..' in branch):
        raise ValueError('Use a branch name without spaces, options, or .. components.')
    repo = repo.rstrip('/')
    key = hashlib.sha256((repo + '\n' + branch + '\n' + folder).encode()).hexdigest()[:24]
    return {'id': key, 'repo': repo, 'folder': folder, 'branch': branch}


def configured():
    from clients import company_docs as D
    if os.environ.get('HUB_API_URL') and os.environ.get('HUB_TOKEN'):
        from clients.tico import Client
        return Client(os.environ['HUB_API_URL'], os.environ['HUB_TOKEN']).get('document-sources')['sources']
    path = D.PROJECTS / 'runtime/company-docs/sources.json'
    if not path.exists():
        return []
    import json
    return [normalize(row) for row in json.loads(path.read_text())]


def fetch(source, now):
    from clients.company_docs import markdown_doc
    source = normalize(source)
    env = {**os.environ, 'GIT_TERMINAL_PROMPT': '0', 'GIT_SSH_COMMAND': 'ssh -oBatchMode=yes'}
    def git(*args):
        result = subprocess.run(['git', '-c', 'core.hooksPath=/dev/null', '-c', 'protocol.file.allow=never',
                                 *args], capture_output=True, timeout=120, env=env)
        if result.returncode:
            raise ValueError('Cannot read linked repository; check its URL, branch and worker Git access.')
        return result.stdout
    with tempfile.TemporaryDirectory(prefix='tico-docs-') as temporary:
        root = Path(temporary) / 'repo'
        args = ['clone', '--depth=1', '--no-checkout']
        if source['branch']:
            args.extend(['--branch', source['branch']])
        git(*args, '--', source['repo'], str(root))
        revision = git('-C', str(root), 'rev-parse', 'HEAD').decode().strip()
        # Read blobs directly: no checkout filters, symlinks, hooks, or submodules execute.
        tree = git('-C', str(root), 'ls-tree', '-r', '-z', 'HEAD').split(b'\0')
        docs = []
        for entry in tree:
            if not entry:
                continue
            meta, raw_path = entry.split(b'\t', 1)
            mode, kind, sha = meta.decode().split()
            path = raw_path.decode('utf-8')
            folder = source['folder']
            if folder != '.' and not path.startswith(folder + '/'):
                continue
            if mode not in ('100644', '100755') or kind != 'blob' or not path.lower().endswith(('.md', '.mdx', '.txt', '.rst')):
                continue
            if len(docs) >= 1000:
                raise ValueError('Source exceeds 1,000 documents; choose a narrower folder.')
            size = int(git('-C', str(root), 'cat-file', '-s', sha).decode())
            if size > 1_000_000:
                raise ValueError('A document exceeds 1 MB; choose a narrower folder.')
            content = git('-C', str(root), 'cat-file', 'blob', sha).decode('utf-8')
            repo = source['repo']
            if repo.startswith('git@'):
                host, remote_path = repo[4:].split(':', 1)
                repo = 'https://' + host + '/' + remote_path
            repo = repo.removesuffix('.git')
            doc = markdown_doc(source['repo'], path, content, 'Internal / Linked documentation',
                               repo + '/blob/' + revision + '/' + quote(path),
                               fetched=now, revision=revision, source_id=source['id'],
                               git_repo=source['repo'], git_branch=source['branch'], docs_folder=folder,
                               status='Imported snapshot')
            doc['id'] = hashlib.sha256((source['id'] + ':' + path).encode()).hexdigest()[:24]
            docs.append(doc)
        if not docs:
            raise ValueError('No Markdown, MDX, text or reStructuredText documents found in the selected folder.')
        return docs
