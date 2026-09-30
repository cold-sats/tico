/* The Files card on a bot's page (docs/files.md): what the bot created, revised or delivered, newest
   activity first, as a plain list of icon and name. Three rows; "Show all" opens the rest inline, a
   page at a time. A stored file opens in Tico's own viewer (deps.openFile), a linked document at its
   provider in a new tab (the provider decides who may open it). Adding a link, promoting and removing
   are the API and the bot's own tools (PATCH /api/v2/files/{id}), not buttons here.
   ui/app/bot-page.js calls window.botFiles.mount(host, deps) once per bot page; deps keeps this file free
   of the page's globals (get, esc, openFile). */
(function () {
  const FILE_ICONS = {document: 'article', spreadsheet: 'view_list', slides: 'view_kanban', image: 'auto_awesome',
    data: 'api', design: 'link', link: 'link', file: 'article'};
  const SHORT = 3, PAGE = 20;

  const css = `
.bot-files{margin:0 0 var(--s3,12px)}
.bot-files .bf-row{display:grid;grid-template-columns:auto minmax(0,1fr);gap:0 10px;align-items:center;padding:8px 0;border-top:1px solid var(--line)}
.bot-files .bf-row:first-of-type{border-top:0}
.bot-files .bf-icon{font-size:20px;width:20px;height:20px;color:var(--muted)}
.bot-files .bf-name{min-width:0;display:block;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;font-weight:500}
.bot-files a.bf-name:hover{text-decoration:underline}
.bot-files .bf-foot{display:flex;gap:10px;align-items:center;padding-top:8px;border-top:1px solid var(--line)}
.bot-files .bf-err{color:var(--fail);font-size:12.5px}`;

  const httpsOnly = url => { try { return new URL(url).protocol === 'https:' ? url : ''; } catch { return ''; } };

  function mount(host, deps) {
    if (!host) return;
    if (!document.getElementById('bot-files-style')) {
      const style = document.createElement('style');
      style.id = 'bot-files-style';
      style.textContent = css;
      document.head.append(style);
    }
    const {slug, get, esc, openFile} = deps;
    const state = {rows: [], total: 0, cursor: null, expanded: false, error: ''};
    const base = `/v2/bots/${encodeURIComponent(slug)}/files`;

    async function load(more) {
      try {
        const limit = state.expanded ? PAGE : SHORT;
        const page = await get(`${base}?limit=${limit}` + (more && state.cursor ? `&cursor=${encodeURIComponent(state.cursor)}` : ''));
        if (!host.isConnected) return;
        const rows = page.files || [];
        state.rows = more ? state.rows.concat(rows) : rows;
        state.total = page.total || 0; state.cursor = page.next_cursor; state.error = '';
      } catch (e) { state.error = e.message || 'Could not load the files.'; }
      render();
    }

    function row(f) {
      const link = f.locator === 'remote_link';
      const url = link ? httpsOnly(f.open?.url) : f.open?.url;
      const icon = `<span class="nav-icon bf-icon" aria-hidden="true">${FILE_ICONS[f.kind] || FILE_ICONS.file}</span>`;
      const name = esc(f.title);
      // A file that never synced has nothing to open: its name is plain text.
      const label = !url ? `<span class="bf-name" title="${esc(f.title)}">${name}</span>` : link
        ? `<a class="bf-name" href="${esc(url)}" target="_blank" rel="noopener noreferrer" data-bf-open="external" title="${esc(f.title)}">${name}</a>`
        : `<a class="bf-name" href="${esc(url)}" data-bf-open="tico" data-bf-id="${esc(f.id)}" data-bf-file="${esc(f.name || f.title)}" title="${esc(f.title)}">${name}</a>`;
      return `<div class="bf-row" data-file="${esc(f.id)}">${icon}${label}</div>`;
    }

    function render() {
      const shown = state.expanded ? state.rows : state.rows.slice(0, SHORT);
      const hasMore = state.expanded && state.cursor;
      host.hidden = false;
      host.innerHTML = `<header><h2>Files</h2></header>
        ${state.error ? `<div class="bf-err" role="alert">${esc(state.error)}</div>` : ''}
        ${shown.length ? shown.map(row).join('') : state.error ? '' : '<div class="empty">No files yet.</div>'}
        ${state.total > SHORT || hasMore ? `<div class="bf-foot">${state.expanded
          ? `${hasMore ? '<button class="ghost" type="button" data-bf-more>Show more</button>' : ''}<button class="ghost" type="button" data-bf-less>Show less</button>`
          : `<button class="ghost" type="button" data-bf-all>Show all ${state.total}</button>`}</div>` : ''}`;
    }

    host.onclick = async event => {
      const hit = selector => event.target.closest(selector);
      const stored = hit('[data-bf-open=tico]');
      if (stored) { event.preventDefault(); openFile(stored.dataset.bfId, stored.dataset.bfFile); return; }
      try {
        if (hit('[data-bf-all]')) { state.expanded = true; await load(); }
        else if (hit('[data-bf-less]')) { state.expanded = false; state.rows = state.rows.slice(0, SHORT); await load(); }
        else if (hit('[data-bf-more]')) { await load(true); }
      } catch (e) { state.error = e.message || 'Could not load the files.'; render(); }
    };
    load();
    const timer = setInterval(() => { if (!host.isConnected) clearInterval(timer); else load(); }, 60000);
  }

  window.botFiles = {mount};
})();
