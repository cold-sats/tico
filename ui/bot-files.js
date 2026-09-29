/* The Files card on a bot's page (docs/files.md): what the bot created, revised or delivered, newest
   activity first. Three rows and the total; "Show all" opens the rest inline, a page at a time.
   A stored file opens in Tico's own viewer, a linked document at its provider (which decides who
   may open it). Owners and bot administrators can add a link, promote a file to bot-wide and remove it.
   index.html calls window.botFiles.mount(host, deps) once per bot page; deps keeps this file free
   of the page's globals (get, write, esc). */
(function () {
  const FILE_ICONS = {document: 'article', spreadsheet: 'view_list', slides: 'view_kanban', image: 'auto_awesome',
    data: 'api', design: 'link', link: 'link', file: 'article'};
  const SHORT = 3, PAGE = 20;

  const css = `
.bot-files{margin:0 0 var(--s3,12px)}
.bot-files .bf-row{display:grid;grid-template-columns:auto minmax(0,1fr) auto;gap:2px 10px;align-items:center;padding:8px 0;border-top:1px solid var(--line)}
.bot-files .bf-row:first-of-type{border-top:0}
.bot-files .bf-icon{grid-row:1/3;font-size:20px;width:20px;height:20px;color:var(--muted)}
.bot-files .bf-title{min-width:0;display:flex;gap:6px;align-items:center;font-weight:500}
.bot-files .bf-title span.bf-name{overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.bot-files .bf-meta{grid-column:2/4;font-size:12.5px;color:var(--muted);display:flex;flex-wrap:wrap;gap:2px 8px;align-items:center}
.bot-files .bf-actions{display:flex;gap:6px;align-items:center;flex-wrap:wrap;justify-content:flex-end}
.bot-files .bf-open{font-weight:500}
.bot-files .bf-warn{color:var(--wait)}
.bot-files .bf-foot{display:flex;gap:10px;align-items:center;padding-top:8px;border-top:1px solid var(--line)}
.bot-files form.bf-add{display:flex;gap:6px;flex-wrap:wrap;margin:0 0 8px}
.bot-files form.bf-add input{flex:1 1 200px;min-width:0;font-size:16px}
.bot-files .bf-err{color:var(--fail);font-size:12.5px}
@media (max-width:760px){.bot-files .bf-row{grid-template-columns:auto minmax(0,1fr)}.bot-files .bf-actions{grid-column:2;justify-content:flex-start}.bot-files .bf-meta{grid-column:2}}`;

  const plural = (n, word) => `${n} ${word}${n === 1 ? '' : 's'}`;
  function since(iso, now = Date.now()) {
    const s = Math.max(0, (now - new Date(iso)) / 1000);
    if (s < 60) return 'just now';
    if (s < 3600) return plural(Math.round(s / 60), 'minute') + ' ago';
    if (s < 86400) return plural(Math.round(s / 3600), 'hour') + ' ago';
    return plural(Math.round(s / 86400), 'day') + ' ago';
  }
  const httpsOnly = url => { try { return new URL(url).protocol === 'https:' ? url : ''; } catch { return ''; } };

  function mount(host, deps) {
    if (!host) return;
    if (!document.getElementById('bot-files-style')) {
      const style = document.createElement('style');
      style.id = 'bot-files-style';
      style.textContent = css;
      document.head.append(style);
    }
    const {slug, get, write, esc} = deps;
    const state = {rows: [], total: 0, cursor: null, expanded: false, canManage: false, adding: false, error: ''};
    const base = `/v2/bots/${encodeURIComponent(slug)}/files`;

    async function load(more) {
      try {
        const limit = state.expanded ? PAGE : SHORT;
        const page = await get(`${base}?limit=${limit}` + (more && state.cursor ? `&cursor=${encodeURIComponent(state.cursor)}` : ''));
        if (!host.isConnected) return;
        const rows = page.files || [];
        state.rows = more ? state.rows.concat(rows) : rows;
        state.total = page.total || 0; state.cursor = page.next_cursor; state.canManage = page.can_manage; state.error = '';
      } catch (e) { state.error = e.message || 'Could not load the files.'; }
      render();
    }

    function row(f) {
      const link = f.locator === 'remote_link';
      const url = link ? httpsOnly(f.open?.url) : f.open?.url;
      const open = !url ? '' : link
        ? `<a class="bf-open" href="${esc(url)}" target="_blank" rel="noopener noreferrer" data-bf-open="external" title="${esc(f.note)}">Open in ${esc(f.provider_label || 'browser')}</a>`
        : `<a class="bf-open" href="${esc(url)}" data-bf-open="tico">Open</a>`;
      const github = f.github_url ? `<a href="${esc(f.github_url)}" target="_blank" rel="noopener noreferrer">View on GitHub</a>` : '';
      const who = f.actor_name ? ` by ${esc(f.actor_name)}` : '';
      const task = f.task_title ? ` · ${esc(f.task_title)}` : '';
      const controls = state.canManage ? `${f.scope !== 'bot' ? `<button class="ghost" type="button" data-bf-promote="${esc(f.id)}" title="Everyone who can see this bot will see it">Promote to bot-wide</button>` : ''}
        <button class="ghost" type="button" data-bf-remove="${esc(f.id)}" title="Removes it from the list; the file is kept">Remove</button>` : '';
      return `<div class="bf-row" data-file="${esc(f.id)}">
        <span class="nav-icon bf-icon" aria-hidden="true">${FILE_ICONS[f.kind] || FILE_ICONS.file}</span>
        <div class="bf-title"><span class="bf-name" title="${esc(f.title)}">${esc(f.title)}</span>${f.working ? '<span class="pill in-progress" data-bf-working>Working</span>' : ''}${!f.synced ? '<span class="pill waiting" data-bf-unsynced>not synced</span>' : ''}</div>
        <div class="bf-actions">${open}${controls}</div>
        <div class="bf-meta"><span>Edited ${esc(since(f.last_activity_at))}${who}${task}</span>${github}${link && f.note ? `<span>${esc(f.note)}</span>` : ''}</div></div>`;
    }

    function render() {
      const shown = state.expanded ? state.rows : state.rows.slice(0, SHORT);
      const hasMore = state.expanded && state.cursor;
      host.hidden = false;
      host.innerHTML = `<header><h2>Files <span class="cnt" data-bf-total>${state.total}</span></h2>
          <span class="sub">what it created or delivered, newest first</span>
          ${state.canManage ? '<button class="linkish" type="button" data-bf-add>Add link</button>' : ''}</header>
        ${state.adding ? `<form class="bf-add" data-bf-form><input type="url" name="url" placeholder="https://docs.google.com/…" required aria-label="Link">
          <input type="text" name="title" placeholder="Title" aria-label="Title" maxlength="300"><button class="primary" type="submit">Add</button>
          <button class="ghost" type="button" data-bf-cancel>Cancel</button></form>` : ''}
        ${state.error ? `<div class="bf-err" role="alert">${esc(state.error)}</div>` : ''}
        ${shown.length ? shown.map(row).join('') : state.error ? '' : '<div class="empty">Nothing yet. Reports and documents it makes will be listed here.</div>'}
        ${state.total > SHORT || hasMore ? `<div class="bf-foot">${state.expanded
          ? `${hasMore ? '<button class="ghost" type="button" data-bf-more>Show more</button>' : ''}<button class="ghost" type="button" data-bf-less>Show less</button>`
          : `<button class="ghost" type="button" data-bf-all>Show all ${state.total}</button>`}</div>` : ''}`;
    }

    host.onclick = async event => {
      const hit = selector => event.target.closest(selector);
      try {
        if (hit('[data-bf-all]')) { state.expanded = true; await load(); }
        else if (hit('[data-bf-less]')) { state.expanded = false; state.rows = state.rows.slice(0, SHORT); await load(); }
        else if (hit('[data-bf-more]')) { await load(true); }
        else if (hit('[data-bf-add]')) { state.adding = true; render(); host.querySelector('[name=url]')?.focus(); }
        else if (hit('[data-bf-cancel]')) { state.adding = false; render(); }
        else if (hit('[data-bf-promote]')) { await write('PATCH', `/v2/files/${hit('[data-bf-promote]').dataset.bfPromote}`, {promote: true}); await load(); }
        else if (hit('[data-bf-remove]')) { await write('PATCH', `/v2/files/${hit('[data-bf-remove]').dataset.bfRemove}`, {archived: true}); await load(); }
      } catch (e) { state.error = e.message || 'That did not save.'; render(); }
    };
    host.onsubmit = async event => {
      event.preventDefault();
      const form = event.target.closest('[data-bf-form]');
      if (!form) return;
      try {
        await write('POST', '/v2/files/links', {bot: slug, url: form.url.value.trim(), title: form.title.value.trim()});
        state.adding = false;
        await load();
      } catch (e) { state.error = e.message || 'That link was not accepted.'; render(); }
    };
    load();
    const timer = setInterval(() => { if (!host.isConnected) clearInterval(timer); else if (!state.adding) load(); }, 60000);
  }

  window.botFiles = {mount, since};
})();
