/* The Docs page (docs/docs.md): internal docs, written or imported in Tico with history and locks,
   and linked docs, which are only links. Search covers both. Ask the Librarian is ui/docs-ask.js. */
let DOC_DATA = {docs: [], linked: []};
let DOC_QUERY = '';
let DOC_LOAD = 0;
let DOC_BROWSER_SCROLL = 0;
const docsHref = (id = '', extra = {}) => {
  const q = new URLSearchParams(extra);
  return '#/docs' + (id ? '/' + encodeURIComponent(id) : '') + (q.size ? '?' + q.toString() : '');
};
const docsIsAdmin = () => S.me?.role === 'owner' || !!S.me?.bot_admin;
const docsDir = path => path.includes('/') ? path.slice(0, path.lastIndexOf('/')) : '';
const docsLockMark = () => `<span class="docs-lock" title="Locked" aria-label="Locked">${DocsSearch.LOCK}</span>`;

async function docsLoadAll(archived = false) {
  const docs = [];
  let cursor = '';
  do {
    const page = await get('/v2/docs?limit=500' + (archived ? '&archived=true' : '') + (cursor ? '&cursor=' + encodeURIComponent(cursor) : ''));
    docs.push(...(page.docs || []));
    cursor = page.next_cursor || '';
  } while (cursor && docs.length < 5000);
  const linked = archived ? [] : (await get('/v2/linked-docs')).linked || [];
  return {docs, linked};
}

window.pageCompanyDocs = async function pageCompanyDocs() {
  $('#main').classList.add('docs-layout');
  if ($('#docs-browser')) DOC_BROWSER_SCROLL = $('#docs-browser').scrollTop;
  const [pathPart, queryPart = ''] = S.route.split('?');
  const params = new URLSearchParams(queryPart);
  if (params.get('collection') === 'notes') { location.hash = '#/docs'; return; }
  const selected = pathPart.startsWith(DOCS + '/') ? decodeURIComponent(pathPart.slice(DOCS.length + 1)) : '';
  const creating = selected === 'new', editing = !creating && params.get('edit') === '1';
  const load = ++DOC_LOAD;
  const admin = docsIsAdmin(), archived = params.get('archived') === '1';
  const mineId = S.me?.id ? 'human:' + S.me.id : '';
  const current = () => load === DOC_LOAD && S.route.startsWith(DOCS);

  $('#main').innerHTML = `<div class="docs-heading"><h1>Docs</h1>
    <div class="docs-search-field"><span class="nav-icon" aria-hidden="true">search</span><input id="docs-search" class="docs-search" type="search" aria-label="Search docs" placeholder="Search internal and linked docs…" value="${esc(DOC_QUERY)}" autocomplete="off"></div>
    <button class="primary docs-ask" id="docs-ask" type="button" data-librarian-open aria-label="Ask the Librarian"><span class="nav-icon" aria-hidden="true">auto_awesome</span><span class="docs-ask-word">Ask the Librarian</span></button>
    <div class="docs-actions"><a class="docs-new" href="${docsHref('', archived ? {} : {archived: 1})}">${archived ? 'Active' : 'Archived'}</a><a class="docs-new" id="docs-new" href="${docsHref('new')}" role="button">New doc</a>
      <button class="docs-settings" id="docs-more" type="button" popovertarget="docs-menu" aria-label="More" aria-expanded="false" title="More"><span class="nav-icon" aria-hidden="true">more_horiz</span></button></div></div>
    <div id="docs-menu" popover aria-label="Docs actions"><button id="docs-import" type="button">Import a file…</button><button id="docs-link" type="button">Add a link…</button></div>
    <p class="docs-feedback" id="docs-feedback" role="status" hidden></p>
    <div class="docs-workspace${selected ? ' has-selection' : ''}"><aside class="docs-browser" aria-label="Docs" id="docs-browser"><div class="empty">Loading docs…</div></aside>
    <article class="docs-reader" id="docs-reader">${selected ? `<a class="docs-back" href="${docsHref()}">← Back to docs</a>` : ''}</article></div>`;
  const feedback = $('#docs-feedback'), menu = $('#docs-menu'), more = $('#docs-more');
  const say = message => { feedback.textContent = message || ''; feedback.hidden = !message; };
  const reload = () => { if (S.route.startsWith(DOCS)) pageCompanyDocs(); };
  menu.addEventListener('toggle', event => {
    more.setAttribute('aria-expanded', String(event.newState === 'open'));
    if (event.newState === 'open') {
      const rect = more.getBoundingClientRect();
      menu.style.top = `${Math.min(rect.bottom + 6, innerHeight - menu.offsetHeight - 12)}px`;
      menu.style.left = `${Math.max(12, Math.min(rect.right - menu.offsetWidth, innerWidth - menu.offsetWidth - 12))}px`;
    }
  });
  const openImport = () => DocsEditor.importDialog({onDone: doc => { location.hash = docsHref(doc.id); }});
  const openLink = link => DocsEditor.linkDialog({link, onDone: reload});
  $('#docs-import').onclick = () => { menu.hidePopover(); openImport(); };
  $('#docs-link').onclick = () => { menu.hidePopover(); openLink(null); };
  // The Librarian's panel (ui/docs-ask.js) registers this; without it the button says so.
  $('#docs-ask').onclick = () => {
    if (typeof window.openDocsAsk === 'function') window.openDocsAsk();
    else say('The Librarian is not available on this install yet.');
  };

  try { DOC_DATA = await docsLoadAll(archived); }
  catch (error) { if (current()) { say('Could not load docs: ' + error.message); $('#docs-browser').innerHTML = ''; } return; }
  if (!current()) return;
  const {docs, linked} = DOC_DATA;
  const browser = $('#docs-browser');
  if (params.get('import') === '1') { history.replaceState(null, '', location.pathname + location.search + docsHref()); openImport(); }

  // ---------------------------------------------------------------- the list
  const canEditLink = link => admin || (!!mineId && link.added_by === mineId);
  const docItem = d => `<a class="docs-item${d.id === selected ? ' selected' : ''}" ${d.id === selected ? 'aria-current="page"' : ''} href="${docsHref(d.id, archived ? {archived: 1} : {})}" title="${esc(d.path)}"><span>${esc(d.title)}</span>${d.locked ? docsLockMark() : ''}</a>`;
  const linkRow = link => {
    const kind = DocsSearch.kind(link.kind);
    return `<div class="docs-link"><a class="docs-link-main" href="${esc(link.url)}" target="_blank" rel="noopener noreferrer" title="Opens ${esc(link.url)}">
        <span class="docs-kind" data-kind="${esc(link.kind)}">${kind.icon}</span>
        <span class="docs-link-text"><strong>${esc(link.title)}</strong><small>${esc(link.host)} · ${esc(kind.label)}</small>${link.description ? `<span>${esc(link.description)}</span>` : ''}</span>
        <span class="docs-ext" aria-hidden="true">↗</span></a>
      ${canEditLink(link) ? `<button class="docs-link-edit" type="button" data-link-edit="${esc(link.id)}" aria-label="Edit ${esc(link.title)}">Edit</button>` : ''}</div>`;
  };
  const renderList = () => {
    const folders = new Map();
    for (const d of docs) { const dir = docsDir(d.path); if (!folders.has(dir)) folders.set(dir, []); folders.get(dir).push(d); }
    const dirs = [...folders.keys()].filter(Boolean).sort((a, b) => a.localeCompare(b));
    const internal = docs.length
      ? [...(folders.get('') || []).map(docItem),
         ...dirs.map(dir => `<details open data-docs-folder="${esc(dir)}"><summary>${esc(dir)} <span class="muted">${folders.get(dir).length}</span></summary>${folders.get(dir).map(docItem).join('')}</details>`)].join('')
      : `<div class="docs-empty-note"><p>No docs yet.</p>
          <div class="docs-empty-actions"><a class="docs-new" href="${docsHref('new')}" role="button">Write a doc</a><button class="ghost" type="button" data-docs-import>Import a file</button></div></div>`;
    const links = linked.length ? linked.map(linkRow).join('')
      : `<div class="docs-empty-note"><p>Point Tico at where your other docs live: a help site, a Drive folder, a Notion page or a repository. Tico stores only the link.</p>
          <div class="docs-empty-actions"><button class="ghost" type="button" data-docs-link>Add a link</button></div></div>`;
    browser.innerHTML = `<section class="docs-section" aria-labelledby="docs-h-internal"><header class="docs-section-head"><h2 id="docs-h-internal">${archived ? 'Archived docs' : 'Internal docs'} <span class="muted">${docs.length}</span></h2>
        <a class="docs-mini" href="${docsHref('new')}" role="button" aria-label="New doc">+ New</a></header>${internal}</section>
      <section class="docs-section" aria-labelledby="docs-h-linked"><header class="docs-section-head"><h2 id="docs-h-linked">Linked docs <span class="muted">${linked.length}</span></h2>
        <button class="docs-mini" type="button" data-docs-link aria-label="Add a link">+ Add link</button></header>${links}</section>`;
    browser.querySelectorAll('details[data-docs-folder]').forEach(el => {
      const key = 'docs.collapse.' + el.dataset.docsFolder;
      try { el.open = localStorage.getItem(key) !== '1'; } catch { /* the folder stays open */ }
      el.ontoggle = () => { try { localStorage.setItem(key, el.open ? '0' : '1'); } catch { /* not remembered */ } };
    });
  };
  const renderResults = ({results}) => {
    browser.innerHTML = `<div class="docs-results" aria-label="Search results">${results.map(r => r.type === 'internal'
      ? `<a class="docs-item docs-result${r.id === selected ? ' selected' : ''}" href="${docsHref(r.id)}"><span class="docs-badge internal">Internal</span><strong>${esc(r.title)}</strong><small>${esc(r.path)}</small>${r.excerpt ? `<span class="docs-excerpt">${esc(r.excerpt)}</span>` : ''}</a>`
      : `<a class="docs-item docs-result" href="${esc(r.url)}" target="_blank" rel="noopener noreferrer"><span class="docs-badge linked">Linked · ${esc(DocsSearch.kind(r.kind).label)}</span><strong>${esc(r.title)} <span aria-hidden="true">↗</span></strong><small>${esc(DocsSearch.hostOf(r.url))}</small>${r.description ? `<span class="docs-excerpt">${esc(r.description)}</span>` : ''}</a>`).join('')
      || '<p class="empty">No docs match. Try fewer words, or ask AI.</p>'}</div>`;
  };
  const showBrowser = () => {
    $('.docs-workspace').classList.toggle('searching', !!selected && !!DOC_QUERY.trim());
    if (!DocsSearch.terms(DOC_QUERY).length) { renderList(); browser.scrollTop = DOC_BROWSER_SCROLL; return; }
    if (archived) {
      const terms = DocsSearch.terms(DOC_QUERY);
      browser.innerHTML = docs.filter(d => terms.every(word => (d.title + ' ' + d.path).toLowerCase().includes(word))).map(docItem).join('') || '<p class="empty">No archived docs match.</p>';
      return;
    }
    DocsSearch.run(get, DOC_QUERY).then(found => { if (!found.stale && current()) renderResults(found); })
      .catch(error => { if (current()) say('Search failed: ' + error.message); });
  };
  browser.onclick = event => {
    if (event.target.closest('[data-docs-import]')) openImport();
    const add = event.target.closest('[data-docs-link]'); if (add) openLink(null);
    const edit = event.target.closest('[data-link-edit]');
    if (edit) openLink(linked.find(l => l.id === edit.dataset.linkEdit));
    if (event.target.closest('.docs-item')) DOC_BROWSER_SCROLL = browser.scrollTop;
  };
  browser.onscroll = () => { if (!DOC_QUERY.trim()) DOC_BROWSER_SCROLL = browser.scrollTop; };
  let timer = 0;
  const search = $('#docs-search');
  search.oninput = () => { DOC_QUERY = search.value; clearTimeout(timer); timer = setTimeout(showBrowser, 180); };
  search.onkeydown = event => {
    if (event.key === 'Enter') { clearTimeout(timer); const first = browser.querySelector('.docs-result'); if (first) first.click(); else showBrowser(); }
    if (event.key === 'Escape') { DOC_QUERY = ''; search.value = ''; showBrowser(); }
  };
  showBrowser();

  // ---------------------------------------------------------------- the reader
  const reader = $('#docs-reader');
  const back = `<a class="docs-back" href="${docsHref('', archived ? {archived: 1} : {})}">← Back to docs</a>`;
  if (!selected) {
    reader.innerHTML = docs.length || linked.length
      ? '<div class="docs-welcome"><p class="muted">Pick a doc, or search.</p></div>'
      : '<div class="docs-welcome"><h2>Your team\'s docs, in one place</h2><p class="muted">Write what your team and your bots should know, import files, and link the docs that live elsewhere. Search covers all of it.</p></div>';
    return;
  }
  if (creating) {
    const folder = params.get('folder') || '';
    reader.innerHTML = back + '<header class="docs-reader-head"><div class="docs-reader-title"><h2>New doc</h2></div></header>';
    reader.append(DocsEditor.editor({folder, onSaved: doc => { location.hash = docsHref(doc.id); }, onCancel: () => { location.hash = docsHref(); }}));
    reader.querySelector('input[name=title]').focus();
    return;
  }
  let doc;
  try { doc = (await get('/v2/docs/' + encodeURIComponent(selected))).doc; }
  catch (error) {
    if (!current()) return;
    reader.innerHTML = back + `<div class="empty">${error.status === 404 ? 'That doc does not exist, or it was archived.' : esc(error.message)}</div>`;
    return;
  }
  if (!current()) return;
  const canChange = admin || !doc.locked;
  const meta = `Version ${doc.version} · Updated ${esc(ago(doc.updated))} by ${esc(doc.updated_by_name || doc.updated_by)}`;
  if (editing && canChange) {
    reader.innerHTML = back + `<header class="docs-reader-head"><div class="docs-reader-title"><p class="muted docs-crumb">${esc(doc.path)}</p><h2>Edit ${esc(doc.title)}</h2><p class="muted">${meta}</p></div></header>`;
    reader.append(DocsEditor.editor({doc, onSaved: saved => { location.hash = docsHref(saved.id); }, onCancel: () => { location.hash = docsHref(doc.id); },
      onReload: () => { location.hash = docsHref(doc.id); }}));
    return;
  }
  reader.innerHTML = `${back}<header class="docs-reader-head"><div class="docs-reader-title"><p class="muted docs-crumb">${esc(doc.path.split('/').join(' / '))}</p>
      <h2>${esc(doc.title)}${doc.locked ? ` <span class="docs-lock-badge">${DocsSearch.LOCK}Locked</span>` : ''}</h2>
      <p class="muted" title="${esc(fmt(doc.updated))}">${meta}</p></div>
      <div class="docs-tools"><a class="docs-tool primary-tool" id="doc-edit" role="button" href="${docsHref(doc.id, {edit: 1})}"${canChange ? '' : ' aria-disabled="true" tabindex="-1" title="Locked: only an owner or bot administrator can change this doc"'}>Edit</a>
        <button class="docs-tool" id="doc-history" type="button">History</button>
        ${admin ? `<button class="docs-tool" id="doc-lock" type="button" aria-pressed="${doc.locked}">${doc.locked ? 'Unlock' : 'Lock'}</button>` : ''}
        ${canChange ? `<button class="docs-tool docs-danger" id="doc-archive" type="button">${doc.archived ? 'Restore' : 'Archive'}</button>` : ''}</div></header>
    ${doc.locked ? `<p class="hint docs-locked-note">${canChange ? 'This doc is locked: only owners and bot administrators can change it.' : 'This doc is locked. Only an owner or bot administrator can change it.'}</p>` : ''}
    <div class="md docs-content">${doc.body.trim() ? safeMd(doc.body, {documentImages: true}) : '<p class="muted">This doc is empty. Choose Edit to write it.</p>'}</div>`;
  $('#docs-reader').scrollTop = 0;
  const editLink = $('#doc-edit');
  if (!canChange) editLink.onclick = event => event.preventDefault();
  $('#doc-history').onclick = () => DocsEditor.history(doc, {canRestore: canChange, onRestored: saved => { location.hash === docsHref(saved.id) ? reload() : location.hash = docsHref(saved.id); }});
  $('#doc-lock')?.addEventListener('click', async event => {
    event.target.disabled = true;
    try { await writeRequest('PATCH', '/v2/docs/' + encodeURIComponent(doc.id), {version: doc.version, locked: !doc.locked}); reload(); }
    catch (error) { say(error.message); event.target.disabled = false; }
  });
  $('#doc-archive')?.addEventListener('click', async event => {
    event.target.disabled = true;
    try {
      if (doc.archived) {
        const saved = await post(`/v2/docs/${encodeURIComponent(doc.id)}/restore`, {version: doc.version});
        location.hash = docsHref(saved.doc.id); toast('Doc restored');
      } else {
        const saved = await writeRequest('PATCH', '/v2/docs/' + encodeURIComponent(doc.id), {version: doc.version, archived: true, note: 'Archived'});
        location.hash = docsHref(); docsArchiveUndo(saved.doc);
      }
    }
    catch (error) { say(error.message); event.target.disabled = false; }
  });

  // On this page: headings get anchors, and a contents list when there is enough to navigate.
  const content = reader.querySelector('.docs-content');
  const lead = content.firstElementChild;                        // the title already heads the page
  if (lead?.tagName === 'H1' && lead.textContent.trim().toLowerCase() === doc.title.trim().toLowerCase()) lead.remove();
  const headings = [...content.querySelectorAll('h1,h2,h3')], used = new Set();
  headings.forEach(h => {
    const base = h.id || h.textContent.toLowerCase().trim().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '') || 'section';
    let id = base, n = 2; while (used.has(id)) id = base + '-' + n++;
    used.add(id); h.id = id;
  });
  const outline = headings.filter(h => h.tagName !== 'H1');
  if (outline.length > 2) {
    const toc = document.createElement('details'); toc.className = 'docs-toc'; toc.open = true;
    toc.innerHTML = '<summary>On this page</summary>' + outline.map(h => `<a href="${docsHref(doc.id, {section: h.id})}" class="toc-${h.tagName.toLowerCase()}">${esc(h.textContent)}</a>`).join('');
    content.before(toc);
  }
  const section = params.get('section');
  if (section) requestAnimationFrame(() => headings.find(h => h.id === section)?.scrollIntoView({block: 'start'}));
  // A relative link to another doc's .md file stays in the page.
  content.querySelectorAll('a[href]').forEach(a => {
    const raw = a.getAttribute('href') || '';
    if (/^[a-z][a-z0-9+.-]*:|^[#/]/i.test(raw) || !/\.(md|markdown)(#.*)?$/i.test(raw)) return;
    const [file, fragment = ''] = raw.split('#');
    const parts = [...docsDir(doc.path).split('/').filter(Boolean)];
    for (const part of file.split('/')) { if (part === '..') parts.pop(); else if (part && part !== '.') parts.push(part); }
    const target = docs.find(d => d.path.toLowerCase() === parts.join('/').toLowerCase());
    if (target) { a.setAttribute('href', docsHref(target.id, fragment ? {section: decodeURIComponent(fragment)} : {})); a.removeAttribute('target'); }
  });
};
window.addEventListener('tico-docs-changed', () => { if (typeof S !== 'undefined' && S.route?.startsWith(DOCS)) window.pageCompanyDocs(); });

function docsArchiveUndo(doc) {
  const notice = document.createElement('div'); notice.className = 'toast docs-archive-undo'; notice.setAttribute('role', 'status'); notice.append('Doc archived. ');
  const button = document.createElement('button'); button.type = 'button'; button.className = 'ghost'; button.textContent = 'Undo';
  button.onclick = async () => {
    button.disabled = true;
    try {
      const saved = await post(`/v2/docs/${encodeURIComponent(doc.id)}/restore`, {version: doc.version});
      notice.remove(); location.hash = docsHref(saved.doc.id); toast('Doc restored');
    } catch (error) { toast(error.message, true); button.disabled = false; }
  };
  notice.append(button); document.body.append(notice); setTimeout(() => notice.remove(), 15000);
}
