"""Company documentation mirror. Canonical sources remain in their existing repositories."""
import base64
import concurrent.futures
import hashlib
import html
from html.parser import HTMLParser
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import threading
import time
from datetime import datetime, timezone
from urllib.request import Request, urlopen
from urllib.parse import urljoin, urlparse, quote

HUB = Path(__file__).resolve().parents[1]
# The projects folder holds runtime/ and secrets/ beside the hub checkout; TICO_PROJECTS names
# it when this checkout is somewhere else (a worktree), the way the runner's --projects does.
PROJECTS = Path(os.environ.get('TICO_PROJECTS') or HUB.parent).expanduser()
if __package__ in (None, ''):                          # run as a script: python clients/company_docs.py
    sys.path.insert(0, str(HUB))
REGISTRY = Path(os.environ.get('TICO_REGISTRY_DIR') or HUB / 'registry')
# The repositories and site the library mirrors; each is set per company in the environment.
INTERNAL_REPO = os.environ.get('TICO_DOCS_INTERNAL_REPO') or 'acme/internal-docs'    # internal documents (Markdown)
SITE_REPO = os.environ.get('TICO_DOCS_SITE_REPO') or 'acme/website'                  # source of the public docs site
SITE_URL = (os.environ.get('TICO_DOCS_SITE_URL') or 'https://acme.example').rstrip('/')   # where that site is published
CACHE = PROJECTS / 'runtime/company-docs/index.json'
LOCK = threading.Lock()
REFRESH_LOCK = threading.Lock()
STATE = {'running': False, 'error': None}
CHECKED = 0
CHECK_LOCK = threading.Lock()


def classify_document(doc):
    """Company guidance is curated; a folder named docs is not an endorsement."""
    row = dict(doc)
    source, path = row.get('source'), row.get('path', '')
    if row.get('category', '').startswith('External /'):
        row['collection'] = 'docs'
        return row
    if row.get('proposal'):
        row['collection'] = 'proposals'
        return row
    policy = json.loads((REGISTRY / 'company-docs.json').read_text())
    category = row.get('category', 'Internal / Operations')
    if source == 'ticoteam/tico':
        category = policy['current_tico_docs'].get(path)
        if not category:
            category = policy['note_categories'].get(path)
        if not category:
            if path.startswith('docs/plans/'):
                category = 'Notes / Historical records' if any(w in path for w in ('audit', 'usage')) else 'Notes / Plans and proposals'
            elif path.startswith('docs/community-research/'):
                category = 'Notes / Research'
            elif path.startswith('policies/'):
                category = 'Notes / Bot operating rules'
            elif path in policy['technical_docs']:
                category = 'Notes / Technical reference'
            else:
                category = 'Notes / Needs review'
    elif source == INTERNAL_REPO:
        if Path(path).name.lower() in ('readme.md', 'contributing.md'):
            category = 'Notes / Library maintenance'
        elif any(part.lower() in ('archive', 'history', 'notes', 'research', 'plans') for part in Path(path).parts):
            category = 'Notes / Research' if 'research' in path.lower() else 'Notes / Historical records'
    row['category'] = category
    row['collection'] = 'notes' if category.startswith('Notes /') else 'docs'
    if row['collection'] == 'notes':
        row['status'] = 'Reference only · not current company guidance'
    return row


def source_versions():
    versions = {}
    for repo in [SITE_REPO, INTERNAL_REPO, 'ticoteam/tico']:
        versions[repo] = gh(f'repos/{repo}/commits?per_page=1')[0]['sha']
        versions[repo + ':prs'] = [(p['number'], p['head']['sha'], p['updated_at']) for p in pages(f'repos/{repo}/pulls?state=open')]
    versions['workspace'] = [(str(p.relative_to(HUB)), p.stat().st_mtime_ns) for folder in ('docs', 'policies') for p in sorted((HUB / folder).rglob('*.md'))]
    versions['classification'] = (REGISTRY / 'company-docs.json').read_text()
    return versions


def check_sources():
    """While Docs is open, check upstream changes without blocking the reader."""
    global CHECKED
    if time.monotonic() - CHECKED < 60 or not CHECK_LOCK.acquire(blocking=False):
        return
    CHECKED = time.monotonic()
    def check():
        try:
            current = source_versions()
            previous = read()
            age = (datetime.now(timezone.utc) - datetime.fromisoformat(previous['updated'])).total_seconds() if previous.get('updated') else 99999
            if age > 900 or json.dumps(current, sort_keys=True) != json.dumps(previous.get('versions'), sort_keys=True):
                refresh()
        except Exception as exc:
            STATE['error'] = str(exc)
        finally:
            CHECK_LOCK.release()
    threading.Thread(target=check, daemon=True).start()


class Article(HTMLParser):
    """Extract the complete prose article, dropping scripts and interactive page chrome."""
    tags = set('p br hr h1 h2 h3 h4 h5 h6 strong em b i del ul ol li blockquote pre code table thead tbody tr th td a img details summary div span'.split())
    void = {'br', 'hr', 'img', 'input', 'meta', 'link', 'source', 'wbr'}

    def __init__(self, url):
        super().__init__(convert_charrefs=True)
        self.url, self.depth, self.skip, self.done = url, 0, 0, False
        self.parts, self.text = [], []

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if not self.depth:
            if self.done or 'prose' not in a.get('class', '').split():
                return
            self.depth = 1
        elif tag not in self.void:
            self.depth += 1
        if tag in {'script', 'style', 'button', 'svg'}:
            self.skip += 1
        if self.skip or tag not in self.tags:
            return
        safe = []
        for k in ('href', 'src', 'alt', 'title', 'id', 'colspan', 'rowspan'):
            if k not in a:
                continue
            value = a[k]
            if k in ('href', 'src'):
                value = urljoin(self.url, value)
                if urlparse(value).scheme not in ('https', 'http'):
                    continue
            safe.append(f'{k}="{html.escape(value, quote=True)}"')
        if tag == 'a':
            safe.append('rel="noopener noreferrer"')
        self.parts.append('<' + tag + (' ' + ' '.join(safe) if safe else '') + '>')

    def handle_endtag(self, tag):
        if not self.depth or tag in self.void:
            return
        if not self.skip and tag in self.tags:
            self.parts.append('</' + tag + '>')
        if tag in {'script', 'style', 'button', 'svg'} and self.skip:
            self.skip -= 1
        self.depth -= 1
        if not self.depth:
            self.done = True

    def handle_data(self, data):
        if self.depth and not self.skip:
            self.parts.append(html.escape(data))
            self.text.append(data)


def gh(path):
    r = subprocess.run(['gh', 'api', path], capture_output=True, text=True, timeout=45)
    if r.returncode:
        raise RuntimeError('GitHub source unavailable: ' + path.split('?')[0])
    return json.loads(r.stdout)


def pages(path):
    for page in range(1, 101):
        rows = gh(path + ('&' if '?' in path else '?') + f'per_page=100&page={page}')
        yield from rows
        if len(rows) < 100:
            return
    raise RuntimeError('GitHub pagination limit reached')


def record(source, path, content, **extra):
    return {'id': hashlib.sha256((source + ':' + path).encode()).hexdigest()[:24],
            'source': source, 'path': path, 'content': content, **extra}


def markdown_doc(source, path, content, category, url, **extra):
    title = next((x.lstrip('# ').strip() for x in content.splitlines() if x.startswith('# ')), Path(path).stem)
    original = content
    def link(match):
        dest = match[3]
        if dest.startswith(('#', 'https://', 'http://', 'mailto:', 's3://')):
            return match[0]
        absolute = urljoin(url, dest)
        if match[1] == '!':
            absolute = absolute.replace('https://github.com/', 'https://raw.githubusercontent.com/').replace('/blob/', '/')
        return match[1] + '[' + match[2] + '](' + absolute + ')'
    content = re.sub(r'(!?)\[([^\]]*)\]\(([^\s)]+)\)', link, content)
    return record(source, path, content, title=title, category=category, url=url,
                  format='markdown', search=original, **extra)


def read(owner=True):
    try:
        data = json.loads(CACHE.read_text())
    except (OSError, ValueError):
        data = {'documents': [], 'proposals': [], 'errors': [], 'updated': None}
    data['documents'] = [classify_document(d) for d in data['documents']]
    if not owner:
        data['documents'] = [d for d in data['documents'] if d['category'].startswith('External /')]
        data['proposals'] = []
        data['errors'] = []
        data['versions'] = {k:v for k,v in data.get('versions', {}).items() if k == SITE_REPO}
    return {**data, 'sync': dict(STATE) if owner else {'running': STATE['running'], 'error': None}}


def document(doc_id, owner=True):
    hit = next((d for d in read(owner)['documents'] if d['id'] == doc_id), None)
    if not hit:
        raise ValueError('Document not found or unavailable to this account.')
    return hit


def catalog(owner=True, collection='docs'):
    if collection not in ('docs', 'notes'):
        raise ValueError('Choose current docs or notes.')
    if owner:
        check_sources()
    data = read(owner)
    data['collection_counts'] = {key: sum(d.get('collection') == key for d in data['documents']) for key in ('docs', 'notes')}
    data['collection'] = collection
    all_documents = data['documents']
    data['documents'] = [d for d in all_documents if d.get('collection') == collection]
    filtered_proposals = []
    for pr in data['proposals']:
        files = [f for f in pr.get('files', []) if classify_document({
            'source': pr['repo'], 'path': f['path'],
            'category': 'External / Documentation' if pr['repo'] == SITE_REPO else 'Internal / Operations'
        })['collection'] == collection]
        if files:
            draft_links = [{'id':d['id'], 'title':d['title']} for d in all_documents
                           if d.get('source') == pr['repo'] and d.get('proposal') == pr['number']]
            filtered_proposals.append({**pr, 'files': files, 'documents': draft_links})
    data['proposals'] = filtered_proposals
    data['documents'] = [{k: v for k, v in d.items() if k != 'content'} for d in data['documents']]
    return data


def pr_review(repo, number):
    if repo not in (SITE_REPO, INTERNAL_REPO, 'ticoteam/tico') or not isinstance(number, int) or number < 1:
        raise ValueError('Choose a documentation PR from this library.')
    pr = gh(f'repos/{repo}/pulls/{number}')
    files = list(pages(f'repos/{repo}/pulls/{number}/files'))
    def is_doc(path):
        if repo == INTERNAL_REPO:
            return path.endswith(('.md', '.mdx'))
        if repo == 'ticoteam/tico':
            return path.startswith('docs/') and path.endswith('.md')
        return (path.startswith('src/app/docs/') and '/_docs/' in path and path.endswith('.tsx')) or (path.startswith('src/data/docs/') and path.endswith('.ts'))
    eligible = bool(files) and all(is_doc(f['filename']) for f in files)
    return {'repo':repo, 'number':number, 'url':pr['html_url'], 'title':pr['title'], 'body':pr.get('body') or '',
            'head_sha':pr['head']['sha'], 'state':pr['state'], 'merged':pr.get('merged', False), 'draft':pr['draft'],
            'merge_eligible': eligible and pr['state'] == 'open' and not pr['draft'] and (pr['head'].get('repo') or {}).get('full_name') == repo,
            'files':[{'path':f['filename'], 'status':f['status'], 'patch':f.get('patch','')} for f in files]}


def refresh_builtin():
    if not LOCK.acquire(blocking=False):
        return
    STATE.update(running=True, error=None)
    try:
        old = read()
        docs, proposals, errors = [], [], []
        now = datetime.now(timezone.utc).isoformat()
        versions = source_versions()
        for folder, category in [('docs', 'Internal / Company'), ('policies', 'Internal / Policies')]:
            for path in sorted((HUB / folder).rglob('*.md')):
                if path.is_symlink():
                    continue
                rel = path.relative_to(HUB).as_posix()
                docs.append(markdown_doc('ticoteam/tico', rel, path.read_text(), category,
                                        'https://github.com/ticoteam/tico/blob/main/' + rel,
                                        status='Workspace copy', fetched=now))
        try:
            repo = INTERNAL_REPO
            branch = gh('repos/' + repo)['default_branch']
            tree = gh(f'repos/{repo}/git/trees/{branch}?recursive=1')
            if tree.get('truncated'):
                raise RuntimeError('Internal document tree was truncated')
            for item in tree['tree']:
                if item['type'] == 'blob' and item['path'].lower().endswith(('.md', '.mdx')):
                    blob = gh(f'repos/{repo}/git/blobs/{item["sha"]}')
                    text = base64.b64decode(blob['content']).decode()
                    docs.append(markdown_doc(repo, item['path'], text, 'Internal / Operations',
                                            f'https://github.com/{repo}/blob/{branch}/{item["path"]}', status='Current', fetched=now, revision=item['sha']))
        except Exception as exc:
            errors.append(str(exc))
            docs.extend(d for d in old['documents'] if d['source'] == INTERNAL_REPO and not d.get('proposal'))
        external = []
        tree = gh('repos/' + SITE_REPO + '/git/trees/' + versions[SITE_REPO] + '?recursive=1')
        if tree.get('truncated'):
            raise RuntimeError('External source tree truncated; retaining previous library')
        for item in tree['tree']:
            match = re.fullmatch(r'src/app/docs/([^/]+)/_docs/([^/]+)\.tsx', item['path'])
            if match:
                external.append((match[1], match[2], item['sha']))
        if not external:
            errors.append('External source checkout unavailable; keeping previous external documents.')
            docs.extend(d for d in old['documents'] if d['category'].startswith('External /'))

        def fetch_doc(item):
            audience, slug, revision = item
            path = f'/docs/{audience}/{slug}'
            url = SITE_URL + path
            try:
                prior = next((d for d in old['documents'] if d['source'] == SITE_REPO and d['path'] == path), None)
                if prior and prior.get('revision') == revision and prior.get('fetched'):
                    age = (datetime.now(timezone.utc) - datetime.fromisoformat(prior['fetched'])).total_seconds()
                    if age < 900:
                        return prior
                if audience == 'developers' and slug == 'api-reference':
                    with urlopen(SITE_URL + '/api/openapi.json', timeout=25) as response:
                        spec = json.load(response)
                    content = '# API reference\n\nComplete published OpenAPI specification.\n\n'
                    for endpoint, operations in spec.get('paths', {}).items():
                        content += '## ' + endpoint + '\n\n```json\n' + json.dumps(operations, indent=2) + '\n```\n\n'
                    content += '## Shared definitions and metadata\n\n```json\n' + json.dumps({k:v for k,v in spec.items() if k != 'paths'}, indent=2) + '\n```\n'
                    return markdown_doc(SITE_REPO, path, content, 'External / Developers', url,
                                        status='Published snapshot', fetched=now, revision=revision)
                with urlopen(Request(url, headers={'User-Agent': 'Tico-Company-Docs/1.0'}), timeout=25) as response:
                    body = response.read().decode('utf-8')
                    if urlparse(response.url).path.rstrip('/') != path:
                        raise ValueError('page redirected; no matching published article')
                parser = Article(url)
                parser.feed(body)
                text = ' '.join(parser.text)
                if not parser.done or len(text.strip()) < 10:
                    raise ValueError('complete article not found')
                title = re.search(r'<h1[^>]*>(.*?)</h1>', ''.join(parser.parts), re.S)
                title = html.unescape(re.sub('<[^>]+>', '', title[1])) if title else slug.replace('-', ' ').title()
                return record(SITE_REPO, path, ''.join(parser.parts), title=title,
                              category='External / ' + {'pm': 'PMs', 'pros': 'Pros', 'developers': 'Developers'}.get(audience, audience),
                              url=url, format='html', search=text, status='Published snapshot', fetched=now, revision=revision)
            except Exception as exc:
                errors.append(f'{path}: {exc}')
                prior = next((d for d in old['documents'] if d['source'] == SITE_REPO and d['path'] == path), None)
                return prior or record(SITE_REPO, path, '', title=slug.replace('-', ' ').title(),
                    category='External / ' + {'pm': 'PMs', 'pros': 'Pros', 'developers': 'Developers'}.get(audience, audience),
                    url=url, format='html', search='', status='Import unavailable', fetched=None)
        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
            docs.extend(pool.map(fetch_doc, external))
        for repo in [INTERNAL_REPO, 'ticoteam/tico', SITE_REPO]:
            try:
                for pr in pages(f'repos/{repo}/pulls?state=open'):
                    files = list(pages(f'repos/{repo}/pulls/{pr["number"]}/files'))
                    relevant = [f for f in files if f['filename'].endswith(('.md', '.mdx', '.tsx')) and
                                (repo == INTERNAL_REPO or f['filename'].startswith(('docs/', 'policies/', 'src/app/docs/', 'src/data/docs/')))]
                    if not relevant:
                        continue
                    eligible = bool(relevant) and len(relevant) == len(files) and all(
                        (repo == INTERNAL_REPO and f['filename'].endswith(('.md', '.mdx'))) or
                        (repo == 'ticoteam/tico' and f['filename'].startswith('docs/') and f['filename'].endswith('.md')) or
                        (repo == SITE_REPO and ((f['filename'].startswith('src/app/docs/') and '/_docs/' in f['filename'] and f['filename'].endswith('.tsx')) or
                                                       (f['filename'].startswith('src/data/docs/') and f['filename'].endswith('.ts'))))
                        for f in files)
                    proposals.append({'repo': repo, 'number': pr['number'], 'title': pr['title'], 'url': pr['html_url'],
                                      'body': pr.get('body') or '', 'draft': pr['draft'], 'state': pr['state'],
                                      'merged': pr.get('merged', False), 'head_sha': pr['head']['sha'],
                                      'head_repo': (pr['head'].get('repo') or {}).get('full_name'), 'total_files': len(files),
                                      'merge_eligible': eligible and pr['state'] == 'open' and not pr['draft'] and
                                                        (pr['head'].get('repo') or {}).get('full_name') == repo,
                                      'files': [{'path': f['filename'], 'status': f['status'], 'patch': f.get('patch', ''),
                                                 'url': f['blob_url']} for f in relevant]})
                    if repo == INTERNAL_REPO:
                        for f in relevant:
                            if f['status'] == 'removed':
                                continue
                            blob = gh(f'repos/{repo}/contents/{quote(f["filename"])}?ref={pr["head"]["sha"]}')
                            text = base64.b64decode(blob['content']).decode()
                            docs.append(markdown_doc(repo, f'PR-{pr["number"]}/' + f['filename'], text,
                                'Proposed / Internal', pr['html_url'], status=f'Proposed · PR #{pr["number"]}',
                                proposal=pr['number'], fetched=now))
            except Exception as exc:
                errors.append(str(exc))
                proposals.extend(p for p in old['proposals'] if p['repo'] == repo)
        docs.extend(d for d in old['documents'] if d.get('source_id'))
        data = {'documents': docs, 'proposals': proposals, 'errors': errors, 'updated': now, 'versions': versions}
        CACHE.parent.mkdir(parents=True, exist_ok=True)
        temp = CACHE.with_suffix('.tmp')
        temp.write_text(json.dumps(data))
        temp.replace(CACHE)
        from clients import docs_qa
        docs_qa.start_warm()
    except Exception as exc:
        STATE['error'] = str(exc)
        raise
    finally:
        STATE['running'] = False
        LOCK.release()


def refresh():
    from clients import doc_sources
    # Serialize the whole refresh, including the linked-source pass.
    if not REFRESH_LOCK.acquire(blocking=False):
        return
    try:
        builtin_error = None
        try:
            refresh_builtin()
        except Exception as exc:
            builtin_error = str(exc)
        STATE.update(running=True)
        linked = doc_sources.configured()
        data = read()
        data['documents'] = [doc for doc in data['documents'] if not doc.get('source_id')]
        data['errors'] = [error for error in data.get('errors', []) if not error.startswith('Linked source ')]
        if builtin_error:
            data['errors'].append(builtin_error)
        now = datetime.now(timezone.utc).isoformat()
        previous = read()
        for source in linked:
            try:
                data['documents'].extend(doc_sources.fetch(source, now))
            except Exception as exc:
                data['errors'].append('Linked source ' + source['repo'] + ' / ' + source['folder'] + ': ' + str(exc))
                data['documents'].extend(doc for doc in previous['documents'] if doc.get('source_id') == source['id'])
        data['updated'] = now
        data.pop('sync', None)
        CACHE.parent.mkdir(parents=True, exist_ok=True)
        temp = CACHE.with_suffix('.tmp')
        temp.write_text(json.dumps(data))
        temp.replace(CACHE)
        from clients import docs_qa
        docs_qa.start_warm()
    finally:
        STATE['running'] = False
        REFRESH_LOCK.release()


def start_refresh():
    if not STATE['running']:
        threading.Thread(target=refresh, daemon=True).start()
    return {'started': True}


def publish_cloud(data=None):
    """Publish the complete approved snapshot with the current bot attempt credential."""
    url, token = os.environ.get('HUB_API_URL'), os.environ.get('HUB_TOKEN')
    if not url or not token:
        raise RuntimeError('Cloud publication requires the scoped HUB_API_URL and HUB_TOKEN from a Doc Updater turn')
    from clients.tico import Client
    data = data or read()
    hashed = hashlib.sha256(json.dumps(data, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
    return Client(url, token, timeout=60).post('documents/catalog', {'catalog': data},
                                               key='documents-catalog:' + hashed)


if __name__ == '__main__':
    refresh()
    result = read()
    published = publish_cloud(result) if '--publish-cloud' in sys.argv[1:] else None
    print(json.dumps({'documents': len(result['documents']), 'proposals': len(result['proposals']),
                      'errors': result['errors'], 'published': published}))
