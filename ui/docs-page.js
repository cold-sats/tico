/* Full company library page, distinct from employee-specific documents. */
let DOC_LIBRARY = null;
let DOC_QUERY = '';
let DOC_COLLECTION = 'docs';
let DOC_BROWSER_SCROLL = 0;
const docsHref = (id = '', section = '') => { const q = new URLSearchParams(); if (DOC_COLLECTION === 'notes') q.set('collection', 'notes'); if (section) q.set('section', section); return '#/docs' + (id ? '/' + id : '') + (q.size ? '?' + q.toString() : ''); };
let DOC_LOAD = 0;
let DOC_POLL = null;
window.pageCompanyDocs = async function pageCompanyDocs() {
  clearInterval(DOC_POLL);
  $('#main').classList.add('docs-layout');
  if ($('#docs-browser')) DOC_BROWSER_SCROLL = $('#docs-browser').scrollTop;
  const requested = new URLSearchParams(S.route.split('?')[1] || '').get('collection');
  const collection = requested === 'notes' ? 'notes' : 'docs';
  if (collection !== DOC_COLLECTION) { DOC_QUERY = ''; DOC_BROWSER_SCROLL = 0; }
  DOC_COLLECTION = collection;
  const load = ++DOC_LOAD;
  const selected = S.route.startsWith(DOCS + '/') ? S.route.slice(DOCS.length + 1).split('?')[0] : '';
  const section = new URLSearchParams(S.route.split('?')[1] || '').get('section');
  const libraryName = collection === 'notes' ? 'Bot Notes' : 'current documentation';
  $('#main').innerHTML = `<div class="docs-heading"><h1>Docs</h1>
    <nav class="docs-collections" aria-label="Documentation library"><a href="#/docs" ${collection === 'docs' ? 'aria-current="page"' : ''}>Current docs</a><a href="#/docs?collection=notes" ${collection === 'notes' ? 'aria-current="page"' : ''}>Bot Notes</a></nav>
    <div class="docs-search-field"><span class="nav-icon" aria-hidden="true">search</span><input id="docs-search" class="docs-search" type="search" aria-label="Search ${libraryName}" placeholder="Search ${libraryName}…" value="${esc(DOC_QUERY)}"></div>
    <button class="primary docs-ask" id="docs-ask" type="button" aria-label="Ask AI about docs"><span class="nav-icon" aria-hidden="true">auto_awesome</span><span class="docs-ask-word">Ask AI</span></button>
    <button class="docs-settings" id="docs-settings" type="button" popovertarget="docs-settings-menu" aria-label="Docs settings" aria-expanded="false" title="Docs settings"><span class="nav-icon" aria-hidden="true">settings</span></button></div>
    <div id="docs-settings-menu" popover aria-label="Docs settings"><button id="docs-changes" type="button" disabled>Proposed changes</button>
      <button id="docs-sync" type="button" disabled>Refresh sources</button>${S.me?.cloud && S.me?.role === 'owner' ? '<button id="docs-sources" type="button">Link repository</button>' : ''}</div>
    <p class="docs-feedback" id="docs-feedback" role="status" hidden></p>
    <div class="docs-workspace${selected ? ' has-selection' : ''}"><aside class="docs-browser" aria-label="Document categories" id="docs-browser"><div class="empty">Loading library…</div></aside>
    <article class="docs-reader" id="docs-reader">${selected ? `<a class="docs-back" href="${docsHref()}">← Back to documents</a>` : '<div class="empty">Choose a document to read it here.</div>'}</article></div>`;
  $('#docs-ask').onclick = () => openDocsChat({collection});
  const menu = $('#docs-settings-menu'), settings = $('#docs-settings'), feedback = $('#docs-feedback');
  const showFeedback = message => { feedback.textContent = message; feedback.hidden = !message; };
  const setSyncState = next => {
    settings.classList.toggle('working', !!next.sync?.running);
    settings.classList.toggle('attention', !next.sync?.running && !!(next.errors?.length || next.sync?.error));
    settings.setAttribute('aria-label', next.sync?.running ? 'Docs settings, refreshing sources'
      : next.errors?.length || next.sync?.error ? 'Docs settings, source issue' : 'Docs settings');
  };
  menu.addEventListener('toggle', event => {
    const open = event.newState === 'open';
    settings.setAttribute('aria-expanded', String(open));
    if (open) {
      const rect = settings.getBoundingClientRect();
      menu.style.top = `${Math.min(rect.bottom + 6, innerHeight - menu.offsetHeight - 12)}px`;
      menu.style.left = `${Math.max(12, Math.min(rect.right - menu.offsetWidth, innerWidth - menu.offsetWidth - 12))}px`;
    }
  });
  if ($('#docs-sources')) $('#docs-sources').onclick = () => { menu.hidePopover(); openDocsSources(); };
  try {
    DOC_LIBRARY = await get('/company-docs?collection=' + collection);
    if (load !== DOC_LOAD || !S.route.startsWith(DOCS)) return;
    const data = DOC_LIBRARY;
    DOC_POLL = setInterval(async () => {
      if (!S.route.startsWith(DOCS)) { clearInterval(DOC_POLL); return; }
      if (document.querySelector('dialog[open]') || document.activeElement?.id === 'docs-search') return;
      try {
        const next = await get('/company-docs?collection=' + collection);
        if (load !== DOC_LOAD || !S.route.startsWith(DOCS)) return;
        if (next.updated !== data.updated || next.sync.error !== data.sync.error ||
            next.errors.join('\n') !== data.errors.join('\n')) {
          const scroll = $('#main').scrollTop;
          await pageCompanyDocs(); $('#main').scrollTop = scroll;
        } else {
          setSyncState(next);
          if (next.sync.running) showFeedback('Refreshing sources…');
          else if (feedback.textContent === 'Refreshing sources…') showFeedback('');
        }
      } catch { /* existing readable snapshot remains available */ }
    }, 30000);
    setSyncState(data);
    if (data.sync.running) showFeedback('Refreshing sources…');
    if (data.errors.length || data.sync.error) {
      const warning = document.createElement('details'); warning.className = 'docs-import-errors';
      warning.innerHTML = `<summary>${data.errors.length || 1} source import problems — some documents may be unavailable or older</summary><pre>${esc(data.errors.join('\n') || data.sync.error)}</pre>`;
      feedback.after(warning);
    }
    const renderList = () => {
      const q = DOC_QUERY.toLowerCase().trim();
      const results = DocsSearch.search(data.documents, q, '');
      const rows = results.map(r => r.doc);
      if (q) {
        $('#docs-browser').innerHTML = results.map(({doc:d, excerpt}) => `<a class="docs-item docs-search-result ${d.id === selected ? 'selected' : ''}" href="${docsHref(d.id)}"><strong>${esc(d.title)}</strong><small>${esc(d.category)}</small><span>${esc(excerpt)}</span></a>`).join('') || '<p class="empty">No matching documents. Try fewer words.</p>';
        return;
      }
      const roots = ['External', 'Internal', 'Proposed', 'Notes'];
      $('#docs-browser').innerHTML = roots.map(root => {
        const items = rows.filter(d => d.category.startsWith(root + ' /'));
        if (!items.length) return '';
        const categories = [...new Set(items.map(d => d.category))];
        return `<details open data-doc-group="${root}"><summary>${root} <span class="muted">${items.length}</span></summary>${categories.map(category => `<details open data-doc-group="${esc(category)}"><summary>${esc(category.split(' / ')[1])} <span class="muted">${items.filter(d => d.category === category).length}</span></summary>
          ${items.filter(d => d.category === category).map(d => `<a class="docs-item ${d.id === selected ? 'selected' : ''}" ${d.id === selected ? 'aria-current="page"' : ''} href="${docsHref(d.id)}">${esc(d.title)}${d.status === 'Import unavailable' ? ' · unavailable' : ''}</a>`).join('')}</details>`).join('')}</details>`;
      }).join('') || '<p class="empty">No matching documents.</p>';
      $('#docs-browser').querySelectorAll('details').forEach(el => {
        const key = 'docs.collapse.' + el.dataset.docGroup;
        try { if (!q) el.open = localStorage.getItem(key) !== '1'; } catch {}
        el.ontoggle = () => { try { if (!q) localStorage.setItem(key, el.open ? '0' : '1'); } catch {} };
      });
    };
    renderList();
    const browser = $('#docs-browser');
    browser.scrollTop = DOC_BROWSER_SCROLL;
    browser.onscroll = () => { DOC_BROWSER_SCROLL = browser.scrollTop; };
    browser.onclick = event => { if (event.target.closest('.docs-item')) DOC_BROWSER_SCROLL = browser.scrollTop; };
    $('#docs-search').oninput = event => {
      DOC_QUERY = event.target.value;
      DOC_BROWSER_SCROLL = 0; browser.scrollTop = 0;
      $('.docs-workspace').classList.toggle('searching', !!selected && !!DOC_QUERY.trim());
      renderList();
    };
    $('#docs-search').onkeydown = event => {
      if (event.key === 'Enter') { const first = $('#docs-browser a'); if (first) first.click(); }
      if (event.key === 'Escape') { DOC_QUERY = ''; DOC_BROWSER_SCROLL = 0; browser.scrollTop = 0; event.target.value = ''; $('.docs-workspace').classList.remove('searching'); renderList(); }
    };
    $('#docs-sync').onclick = async () => {
      menu.hidePopover();
      const button = $('#docs-sync'); button.disabled = true;
      try { const refresh = await post('/company-docs/refresh', {}); showFeedback(refresh.queued && S.me?.cloud ? 'Refresh requested. Doc Updater will publish the updated library here.' : 'Refreshing sources…'); settings.classList.add('working'); }
      catch (e) { showFeedback(e.message); settings.classList.add('attention'); }
      button.disabled = false;
    };
    $('#docs-sync').disabled = false;
    $('#docs-changes').disabled = false;
    $('#docs-changes').textContent = `Proposed changes${data.proposals.length ? ` (${data.proposals.length})` : ''}`;
    $('#docs-changes').onclick = () => {
      menu.hidePopover();
      const dialog = document.createElement('dialog'); dialog.className = 'tmodal docs-proposals';
      dialog.innerHTML = `<div class="tmodal-head"><h2>Proposed changes</h2><span class="spacer"></span><button class="ghost" aria-label="Close proposed changes">✕</button></div>
        <div class="docs-proposals-body">${data.proposals.map(pr => `<section class="card"><h3><a href="${esc(pr.url)}" target="_blank" rel="noopener">${esc(pr.title)} ↗</a></h3>
        <p class="muted">${esc(pr.repo)} · #${pr.number} · ${pr.draft ? 'Draft' : 'Open'} — not merged</p><details><summary>Change description</summary>${safeMd(pr.body)}</details>
        ${(pr.documents || []).map(d => `<p><a href="${docsHref(d.id)}" data-read-proposal>Read proposed document: ${esc(d.title)}</a></p>`).join('')}
        ${pr.files.map(f => `<details><summary>${esc(f.path)} · ${esc(f.status)}</summary><pre>${esc(f.patch || 'GitHub did not return an inline diff. Open the PR for the complete change.')}</pre><a href="${esc(f.url)}" target="_blank" rel="noopener">Open full file ↗</a></details>`).join('')}</section>`).join('') || '<p>No open documentation PRs were found in the last source check.</p>'}
        <p class="muted">Diff previews may be shortened by GitHub. The PR is the complete review record.</p></div>`;
      document.body.appendChild(dialog); dialog.showModal();
      dialog.querySelectorAll('.docs-proposals-body > section').forEach((el,i) => attachDocReview(el,data.proposals[i]));
      dialog.querySelector('button').onclick = () => dialog.close();
      dialog.querySelectorAll('[data-read-proposal]').forEach(a => a.onclick = () => dialog.close());
      dialog.onclose = () => dialog.remove();
    };
    if (selected) {
      const doc = await get('/company-docs/' + encodeURIComponent(selected));
      if (load !== DOC_LOAD || !S.route.startsWith(DOCS)) return;
      if (doc.collection === 'notes' && collection !== 'notes') { location.hash = '#/docs/' + doc.id + '?collection=notes'; return; }
      if (doc.collection === 'market') { location.hash = '#/market?note=' + encodeURIComponent(doc.id); return; }
      $('#docs-reader').innerHTML = `<a class="docs-back" href="${docsHref()}">← Back to documents</a><header class="docs-reader-head"><div><p class="muted">${esc(doc.category)} · ${esc(doc.status)}</p><h2>${esc(doc.title)}</h2>
        <p class="muted">${doc.fetched ? 'Imported ' + fmt(doc.fetched) : 'Awaiting import'}${doc.rendered_commit ? ' · Revision ' + esc(doc.rendered_commit.slice(0, 8)) : ''}${doc.url ? ` · <a href="${esc(doc.url)}" target="_blank" rel="noopener">Original source ↗</a>` : ''}</p></div>
        <button class="chat-btn" id="ask-this-doc">${ICON_CHAT} Ask this doc</button></header>
        ${doc.collection === 'notes' ? '<p class="hint">Reference material. This is excluded from current documentation search and should not be treated as company policy.</p>' : ''}
        ${doc.proposal ? '<p class="hint">Proposed document — this has not been merged into current company guidance.</p>' : ''}
        <div class="md docs-content">${doc.content ? safeMd(doc.content, {documentImages: true}) : '<p>This document could not be imported. See the source error above or open the original.</p>'}</div>`;
      $('#docs-reader').scrollTop = 0;
      $('#ask-this-doc').onclick = () => openDocsChat({docId:doc.id,collection,title:doc.title});
      const headings = [...$('#docs-reader').querySelectorAll('.docs-content h1,.docs-content h2,.docs-content h3')];
      const usedIds = new Set();
      headings.forEach(h => {
        let id = h.id || h.textContent.toLowerCase().trim().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '') || 'section';
        const base = id; let n = 2; while (usedIds.has(id)) id = base + '-' + n++;
        usedIds.add(id); h.id = id;
      });
      const tocHeadings = headings.filter(h => h.tagName !== 'H1');
      if (tocHeadings.length) {
        const toc = document.createElement('details'); toc.className = 'docs-toc'; toc.open = true;
        toc.innerHTML = '<summary>On this page</summary>' + tocHeadings.map(h => `<a href="${docsHref(doc.id, h.id)}" class="toc-${h.tagName.toLowerCase()}">${esc(h.textContent)}</a>`).join('');
        $('#docs-reader .docs-reader-head').after(toc);
      }
      if (section) requestAnimationFrame(() => {
        const target = headings.find(h => h.id === section); if (target) target.scrollIntoView({block:'start'});
      });
      // Keep links to other imported docs inside the reader.
      $('#docs-reader').querySelectorAll('.docs-content a[href]').forEach(a => {
        const target = data.documents.find(d => d.url === a.href.split('#')[0]);
        if (target) {
          const fragment = new URL(a.href).hash.slice(1);
          a.href = docsHref(target.id, fragment ? decodeURIComponent(fragment) : '');
          a.removeAttribute('target');
        }
      });
    }
  } catch (e) { if (load === DOC_LOAD) { showFeedback('Could not load the library: ' + e.message); $('#docs-browser').innerHTML = ''; } }
};
