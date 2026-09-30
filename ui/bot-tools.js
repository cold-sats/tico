/* The Tools row at the top of a bot's page: what the bot uses, at a glance (docs/creating-bots.md,
   "What people see about a bot's tools"). One small round icon per tool, the service's logo when
   ui/tool-icons.js has it and the name's first two letters otherwise; a red dot marks a tool with a
   problem. Hover or focus opens a popover with the details, a tap opens it as a sheet on a phone, a
   click pins it, Escape closes it. More than eight tools show "+N", which opens the whole list.
   ui/app/bot-page.js calls window.botTools.mount(host, deps) once per bot page; deps keeps this file free of
   the page's globals (get, esc). Nothing here reads a secret: the server sends names, never values. */
(function () {
  const MAX_ICONS = 8;
  const HOVER_MS = 120, LEAVE_MS = 180;
  const PHONE = window.matchMedia ? window.matchMedia('(max-width: 760px)') : {matches: false};

  const css = `
.bot-tools{position:relative;flex:none;margin:0 0 var(--s3,12px)}
.bot-tools .bt-row{display:flex;flex-wrap:wrap;align-items:center;gap:6px}
.bot-tools .bt-icon,.bot-tools .bt-more{position:relative;flex:none;width:30px;height:30px;padding:0;border:1px solid var(--line);border-radius:50%;background:var(--surface);color:var(--ink);display:inline-grid;place-items:center;cursor:pointer;line-height:1}
.bot-tools .bt-icon:hover,.bot-tools .bt-more:hover,.bot-tools [aria-expanded=true]{border-color:var(--accent)}
.bot-tools .bt-icon:focus-visible,.bot-tools .bt-more:focus-visible{outline:2px solid var(--accent);outline-offset:2px}
.bot-tools .bt-icon svg,.bt-pop .bt-icon-static svg{width:16px;height:16px}
.bot-tools .bt-icon.bt-tint,.bt-pop .bt-tint{border-color:transparent;background:color-mix(in srgb,hsl(var(--h) 60% 50%) 20%,var(--surface));color:color-mix(in srgb,hsl(var(--h) 65% 42%) 72%,var(--ink))}
.tool-initials{font-size:11.5px;font-weight:600;letter-spacing:.01em}
.bot-tools .bt-dot{position:absolute;right:-2px;bottom:-2px;width:9px;height:9px;border-radius:50%;background:var(--fail);border:2px solid var(--bg)}
.bot-tools .bt-more{width:auto;min-width:30px;padding:0 8px;border-radius:15px;font-size:12px;font-weight:600;color:var(--muted)}
.bt-pop{position:fixed;z-index:70;width:min(320px,calc(100vw - 16px));max-height:min(70vh,520px);overflow:auto;padding:12px 14px;border:1px solid var(--line);border-radius:10px;background:var(--surface);color:var(--ink);box-shadow:0 8px 28px rgba(0,0,0,.18);font-size:13px;line-height:1.45}
.bt-pop[hidden],.bt-scrim[hidden]{display:none}
.bt-pop .bt-head{display:flex;align-items:center;gap:9px;margin-bottom:8px}
.bt-pop .bt-icon-static{flex:none;width:30px;height:30px;border-radius:50%;background:var(--surface2);display:inline-grid;place-items:center}
.bt-pop .bt-name{flex:1;min-width:0;font-weight:600;font-size:14px;overflow-wrap:anywhere}
.bt-pop dl{margin:0;display:grid;grid-template-columns:auto minmax(0,1fr);gap:4px 12px}
.bt-pop dt{color:var(--muted);font-size:12px;padding-top:1px}
.bt-pop dd{margin:0;min-width:0;overflow-wrap:anywhere}
.bt-pop .pill{margin:0 4px 2px 0}
.bt-pop .bt-problem{color:var(--fail)}
.bt-pop .bt-close{display:none;float:right;margin:-4px -6px 0 6px;padding:2px 9px;font-size:15px}
.bt-pop .bt-item{padding:10px 0;border-top:1px solid var(--line)}
.bt-pop .bt-head+.bt-item{border-top:0;padding-top:0}
.bt-pop .bt-item:last-child{padding-bottom:0}
.bt-pop .bt-title{display:block;font-weight:600;margin:0 0 6px}
.bt-scrim{position:fixed;inset:0;z-index:69;background:rgba(0,0,0,.32);cursor:pointer}
@media (max-width:760px){
  .bt-pop{left:0;right:0;bottom:0;top:auto;width:auto;max-height:72dvh;border-radius:14px 14px 0 0;padding:14px 16px calc(14px + env(safe-area-inset-bottom));font-size:14px}
  .bt-pop .bt-close{display:inline-block}
  .bot-tools .bt-icon,.bot-tools .bt-more{width:36px;height:36px}
  .bot-tools .bt-more{width:auto;min-width:36px;border-radius:18px}
  .bot-tools .bt-row{gap:8px}
}`;

  const STATUS = {ready: ['ok', 'Ready'], problem: ['fail', 'Needs attention'], unknown: ['', 'Not checked']};
  const label = key => String(key).replace(/[_-]+/g, ' ').replace(/^./, c => c.toUpperCase());
  const asList = value => (Array.isArray(value) ? value : [value]).map(String).filter(Boolean);

  function summary(tool) {
    const [, word] = STATUS[tool.status] || STATUS.unknown;
    const status = tool.status === 'problem' && tool.problem ? tool.problem : word;
    return [tool.name, tool.identity, status].filter(Boolean).join(', ');
  }

  function mount(host, deps) {
    if (!host) return;
    if (!document.getElementById('bot-tools-style')) {
      const style = document.createElement('style');
      style.id = 'bot-tools-style';
      style.textContent = css;
      document.head.append(style);
    }
    const {slug, get, esc} = deps;
    const icons = window.toolIcons || {markup: () => '', hue: () => 0};
    const state = {tools: [], open: null, pinned: false, timer: 0};
    host.replaceChildren();
    host.classList.add('bot-tools');
    const row = document.createElement('div');
    row.className = 'bt-row';
    row.setAttribute('role', 'group');
    row.setAttribute('aria-label', 'Tools this bot uses');
    const scrim = document.createElement('div');
    scrim.className = 'bt-scrim';
    scrim.hidden = true;
    const pop = document.createElement('div');
    pop.className = 'bt-pop';
    pop.id = 'bot-tools-pop-' + Math.random().toString(36).slice(2, 8);
    pop.setAttribute('role', 'dialog');
    pop.hidden = true;
    host.append(row, scrim, pop);       // `fixed`, so the pane's own scrolling never clips it

    const tint = tool => (icons.has && icons.has(tool.logo_key) ? '' : ` bt-tint" style="--h:${icons.hue(tool.name)}`);
    const statusPill = tool => { const [kind, word] = STATUS[tool.status] || STATUS.unknown; return `<span class="pill ${kind}">${esc(word)}</span>`; };

    function detail(tool) {
      const rows = [];
      const identityLabel = tool.id === 'model' ? 'Runs on' : tool.id === 'repo' ? 'Repository' : 'Acts as';
      if (tool.identity) rows.push([identityLabel, tool.url && tool.id === 'repo'
        ? `<a href="${esc(tool.url)}" target="_blank" rel="noopener noreferrer">${esc(tool.identity)}</a>` : esc(tool.identity)]);
      if (tool.can?.length && tool.id !== 'model') rows.push(['Can', tool.can.map(v => `<span class="pill">${esc(v)}</span>`).join('')]);
      for (const [key, value] of Object.entries(tool.scope || {})) {
        if (tool.id === 'repo' && key === 'repo') continue;
        rows.push([label(key), esc(asList(value).join(', '))]);
      }
      if (tool.mcp) rows.push(['mcp', `<code>${esc(tool.mcp.host)}</code> <span class="muted">${esc(tool.mcp.transport)}</span>`]);
      if (tool.env) rows.push(['Credential', `<code>${esc(tool.env)}</code>`]);
      if (tool.note) rows.push(['Note', esc(tool.note)]);
      const status = tool.status === 'problem' && tool.problem
        ? `<span class="bt-problem">${esc(tool.problem)}</span>`
        : `${statusPill(tool)}${tool.detail ? ` <span class="muted">${esc(tool.detail)}</span>` : ''}`;
      rows.push(['Status', status]);
      return `<dl>${rows.map(([k, v]) => `<dt>${esc(k)}</dt><dd>${v}</dd>`).join('')}</dl>`;
    }

    const head = tool => `<div class="bt-head"><span class="bt-icon-static${tint(tool)}">${icons.markup(tool)}</span>
      <span class="bt-name">${esc(tool.name)}</span>${tool.status === 'problem' ? statusPill(tool) : ''}</div>`;

    function render() {
      const tools = state.tools;
      host.hidden = !tools.length;
      const shown = tools.length > MAX_ICONS ? tools.slice(0, MAX_ICONS) : tools;
      row.innerHTML = shown.map(tool => `<button type="button" class="bt-icon${tint(tool)}" data-tool="${esc(tool.id)}"
          aria-label="${esc(summary(tool))}" aria-haspopup="dialog" aria-expanded="false">${icons.markup(tool)}${tool.status === 'problem' ? '<span class="bt-dot" aria-hidden="true"></span>' : ''}</button>`).join('')
        + (tools.length > shown.length ? `<button type="button" class="bt-more" data-tool="*" aria-haspopup="dialog" aria-expanded="false"
          aria-label="Show all ${tools.length} tools">+${tools.length - shown.length}</button>` : '');
      if (state.open && !row.querySelector(`[data-tool="${CSS.escape(state.open)}"]`)) close();
      else if (state.open) show(state.open, state.pinned);
    }

    function content(id) {
      if (id === '*') return {name: 'All tools', html: `<div class="bt-head"><span class="bt-name">All ${state.tools.length} tools</span></div>`
        + state.tools.map(tool => `<div class="bt-item"><span class="bt-title">${esc(tool.name)}</span>${detail(tool)}</div>`).join('')};
      const tool = state.tools.find(t => t.id === id);
      return tool ? {name: tool.name, html: head(tool) + detail(tool)} : null;
    }

    function place(button) {
      if (PHONE.matches) { pop.style.left = pop.style.top = ''; return; }
      const box = button.getBoundingClientRect();
      const width = pop.offsetWidth;
      const left = Math.max(8, Math.min(box.left, window.innerWidth - width - 8));
      const below = box.bottom + 8;
      const top = below + pop.offsetHeight > window.innerHeight - 8 ? Math.max(8, box.top - 8 - pop.offsetHeight) : below;
      pop.style.left = left + 'px';
      pop.style.top = top + 'px';
    }

    function show(id, pinned) {
      const button = row.querySelector(`[data-tool="${CSS.escape(id)}"]`);
      const view = content(id);
      if (!button || !view) return close();
      clearTimeout(state.timer);
      row.querySelectorAll('[aria-expanded=true]').forEach(b => { b.setAttribute('aria-expanded', 'false'); b.removeAttribute('aria-describedby'); });
      state.open = id;
      state.pinned = pinned;
      pop.setAttribute('aria-label', view.name);
      pop.innerHTML = `<button type="button" class="ghost bt-close" data-bt-close aria-label="Close">✕</button>${view.html}`;
      pop.hidden = false;
      scrim.hidden = !(PHONE.matches);
      button.setAttribute('aria-expanded', 'true');
      button.setAttribute('aria-describedby', pop.id);
      place(button);
    }

    function close(returnFocus) {
      clearTimeout(state.timer);
      const button = state.open && row.querySelector(`[data-tool="${CSS.escape(state.open)}"]`);
      row.querySelectorAll('[aria-expanded=true]').forEach(b => { b.setAttribute('aria-expanded', 'false'); b.removeAttribute('aria-describedby'); });
      state.open = null;
      state.pinned = false;
      pop.hidden = true;
      scrim.hidden = true;
      if (returnFocus && button) button.focus();
    }

    const later = (fn, ms) => { clearTimeout(state.timer); state.timer = setTimeout(fn, ms); };
    const buttonOf = event => event.target.closest?.('[data-tool]');

    row.addEventListener('pointerenter', event => {
      const button = event.pointerType === 'mouse' ? buttonOf(event) : null;
      if (button && !state.pinned) later(() => show(button.dataset.tool, false), HOVER_MS);
    }, true);
    row.addEventListener('pointerleave', event => { if (event.pointerType === 'mouse' && buttonOf(event) && !state.pinned) later(close, LEAVE_MS); }, true);
    pop.addEventListener('pointerenter', () => clearTimeout(state.timer));
    pop.addEventListener('pointerleave', event => { if (event.pointerType === 'mouse' && !state.pinned) later(close, LEAVE_MS); });
    row.addEventListener('focusin', event => {
      const button = buttonOf(event);
      if (button && !state.pinned && event.target.matches(':focus-visible')) show(button.dataset.tool, false);
    });
    row.addEventListener('focusout', event => {
      if (!state.pinned && !row.contains(event.relatedTarget) && !pop.contains(event.relatedTarget)) later(close, 60);
    });
    row.addEventListener('click', event => {
      const button = buttonOf(event);
      if (!button) return;
      if (state.open === button.dataset.tool && state.pinned) close();
      else show(button.dataset.tool, true);
    });
    pop.addEventListener('click', event => { if (event.target.closest('[data-bt-close]')) close(true); });
    scrim.addEventListener('click', () => close());
    // Page-wide listeners go when the bot page is replaced (the host leaves the document).
    const listeners = [];
    const listen = (target, name, handler, capture) => {
      const wrapped = event => { if (host.isConnected) handler(event); else dispose(); };
      target.addEventListener(name, wrapped, capture);
      listeners.push(() => target.removeEventListener(name, wrapped, capture));
    };
    const dispose = () => { listeners.splice(0).forEach(off => off()); clearInterval(timer); clearTimeout(state.timer); };
    listen(document, 'pointerdown', event => { if (state.open && !row.contains(event.target) && !pop.contains(event.target)) close(); });
    listen(document, 'keydown', event => { if (event.key === 'Escape' && state.open) { event.stopPropagation(); close(true); } }, true);
    listen(window, 'scroll', event => { if (state.open && !pop.contains(event.target)) close(); }, true);
    listen(window, 'resize', () => { if (state.open) close(); });

    async function load() {
      try {
        const page = await get(`/v2/bots/${encodeURIComponent(slug)}/tools`);
        if (!host.isConnected) return;
        state.tools = Array.isArray(page.tools) ? page.tools : [];
      } catch (e) { if (!host.isConnected) return; state.tools = state.tools || []; }
      render();
    }

    load();
    const timer = setInterval(() => { if (!host.isConnected) dispose(); else if (!state.open) load(); }, 60000);
  }

  window.botTools = {mount, summary};
})();
