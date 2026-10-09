/* Support uses the existing ticket transport and the app's right rail. Drafts stay on this page's account in memory;
   an attachment is an immutable server preview, never silently replaced when Send is pressed. */
'use strict';
(function () {
  'use strict';
  const API_BASE = () => (typeof API === 'string' ? API : '/api') + '/v2';
  const escape = s => String(s ?? '').replace(/[&<>"']/g, c => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[c]));
  const say = (msg, error) => typeof toast === 'function' && toast(msg, error);
  const uid = () => crypto.randomUUID();
  const browserFailures = [];
  function browserFailure(kind, event) {
    // No error message, rejection value, URLs, stack text or user input enters diagnostics.
    let file = '';
    try { file = new URL(event?.filename || '', location.href).pathname.split('/').pop(); } catch (_) {}
    const item = {kind, at: new Date().toISOString(), file: /^[A-Za-z0-9_-]+\.js$/.test(file) ? file : '',
      line: Math.max(0, Math.min(10000000, event?.lineno || 0)), column: Math.max(0, Math.min(10000000, event?.colno || 0)), count: 1};
    const prior = browserFailures.find(x => x.kind === item.kind && x.file === item.file && x.line === item.line && x.column === item.column);
    if (prior) { prior.at = item.at; prior.count = Math.min(1000000, prior.count + 1); }
    else { browserFailures.push(item); if (browserFailures.length > 20) browserFailures.shift(); }
  }
  window.addEventListener('error', e => browserFailure('error', e));
  window.addEventListener('unhandledrejection', () => browserFailure('unhandledrejection'));
  const capture = () => browserFailures.length
    ? call('POST', '/support/diagnostics/capture', {browser: browserFailures})
    : call('GET', '/support/diagnostics');
  const statuses = {open: 'Open', answered: 'Answered', closed: 'Closed', gone: 'Removed'};
  let state = {enabled: null, tickets: [], unread: 0}, selected = '', rail = null, timer, busyRefresh = null;
  let owner = '', toasted = 0, compose = null, drafts = new Map(), editor = null;
  const when = iso => { const d = new Date(iso); return isNaN(d) ? '' : d.toLocaleString(undefined, {month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit'}); };
  const draft = () => {
    if (!drafts.has(selected)) drafts.set(selected, {message: '', email: compose?.email || '', ids: true, diag: !selected, bundle: null, key: uid()});
    return drafts.get(selected);
  };
  const current = () => state.tickets.find(t => t.id === selected);
  async function call(method, path, body, key) {
    const r = await fetch(API_BASE() + path, {method, cache: 'no-store',
      headers: body === undefined ? {} : {'Content-Type': 'application/json', 'Idempotency-Key': key || uid()},
      body: body === undefined ? undefined : JSON.stringify(body)});
    const data = await r.json().catch(() => ({}));
    if (!r.ok) throw Object.assign(new Error(data.error?.detail || data.error?.message || (typeof data.detail === 'string' ? data.detail : '') || 'Could not reach support. Try again.'), {status: r.status});
    return data;
  }
  function mark() {
    const link = document.getElementById('help-open');
    if (state.unread) link?.setAttribute('data-support-unread', state.unread);
    else link?.removeAttribute('data-support-unread');
  }
  function accept(data) {
    state = {enabled: data.enabled !== false, tickets: data.tickets || [], unread: data.unread || 0};
    if (state.unread > toasted) say('Tico support replied.');
    toasted = state.unread;
    mark();
    if (rail?.isConnected) { renderTickets(); renderThread(); }
  }
  function note(message, error = false) {
    const el = rail?.querySelector('[data-connection]');
    if (el) { el.textContent = message; el.classList.toggle('err', error); }
  }
  async function refresh() {
    if (busyRefresh) return busyRefresh;
    busyRefresh = (async () => {
      try {
        const data = await call('POST', '/support/tickets/refresh');
        accept(data);
        note(data.refresh_failed ? 'Could not check replies. Try Refresh.' : 'Checked ' + new Date().toLocaleTimeString([], {hour: 'numeric', minute: '2-digit'}), !!data.refresh_failed);
      } catch (e) { note(e.message, true); }
      finally { busyRefresh = null; }
      return state;
    })();
    return busyRefresh;
  }
  function schedule() {
    clearTimeout(timer);
    if (!state.enabled) return;
    timer = setTimeout(async () => {
      if (!document.hidden && state.tickets.some(t => !['closed', 'gone'].includes(t.status))) await refresh();
      schedule();
    }, rail?.isConnected ? 30000 : 300000);
  }
  async function readVisible() {
    const t = current();
    if (document.hidden || !rail?.isConnected || !t?.unread) return;
    // Reading follows an explicit choice of thread, not a background fetch.
    try {
      const next = await call('POST', `/support/tickets/${encodeURIComponent(t.id)}/read`);
      state.tickets = state.tickets.map(x => x.id === next.id ? next : x);
      state.unread = state.tickets.reduce((n, x) => n + (x.unread || 0), 0);
      toasted = state.unread; mark(); renderTickets(); renderThread();
    } catch (_) { /* unread remains until the next explicit read */ }
  }
  function renderTickets() {
    const select = rail.querySelector('[data-requests]');
    select.innerHTML = '<option value="">New request</option>' + state.tickets.map(t => `<option value="${escape(t.id)}">${t.unread ? '● ' : ''}${escape((t.message || '').replace(/\s+/g, ' ').slice(0, 65))} · ${escape(statuses[t.status] || t.status)}</option>`).join('');
    select.value = selected;
  }
  function renderThread() {
    const host = rail.querySelector('[data-thread]'), t = current();
    const bottom = host.scrollHeight - host.scrollTop - host.clientHeight < 40, top = host.scrollTop;
    const text = (body, author, at, diag) => `<div class="support-msg ${author === 'Support' ? 'staff' : ''}"><span class="support-who">${escape(author)}${at ? ', ' + escape(when(at)) : ''}</span><div>${escape(body)}</div>${diag ? '<small class="support-sent">Diagnostics attached</small>' : ''}</div>`;
    const html = t ? text(t.message, 'You', t.created, t.sent?.diagnostics) + (t.messages || []).map(m => text(m.body, m.from === 'staff' ? 'Support' : 'You', m.created, m.has_diagnostics)).join('')
      : '<p class="support-empty">Tell us what happened and what you expected. Recent redacted diagnostics are attached by default; you can review, edit, or remove them.</p>';
    if (host.innerHTML !== html) { host.innerHTML = html; host.scrollTop = bottom ? host.scrollHeight : top; }
    const closed = t && ['closed', 'gone'].includes(t.status);
    rail.querySelector('[data-compose]').hidden = !!closed;
    rail.querySelector('[data-closed]').hidden = !closed;
    rail.querySelector('[data-delete]').hidden = !t;
    rail.querySelector('[data-read]').hidden = !t?.unread;
    rail.querySelector('[data-status]').textContent = t ? statuses[t.status] || t.status : 'New request';
  }
  function renderComposer() {
    const d = draft(), form = rail.querySelector('[data-compose]');
    form.innerHTML = `<label class="sr-only" for="support-message">Message to support</label>
      <textarea id="support-message" name="message" maxlength="4000" placeholder="${selected ? 'Write back…' : 'How can we help?'}" required>${escape(d.message)}</textarea>
      <div class="support-diag"><label><input name="diag" type="checkbox" ${d.diag ? 'checked' : ''}> @diagnostics</label><button class="ghost" type="button" data-preview>Review and edit</button></div>
      ${!selected ? `<details class="support-options"><summary>Reply email and install details</summary><label>Email for a reply<input name="email" type="email" value="${escape(d.email)}" autocomplete="email"></label><label class="support-check"><input name="ids" type="checkbox" ${d.ids ? 'checked' : ''}> Include version and install ID</label></details>` : ''}
      <p class="support-sent" data-sent></p><p class="err" data-error role="alert" hidden></p>
      <div class="support-row"><button class="primary" type="submit">Send</button></div>`;
    form.oninput = () => {
      d.message = form.elements.message.value;
      if (!selected) { d.email = form.elements.email.value; d.ids = form.elements.ids.checked; }
      d.diag = form.elements.diag.checked;
      d.key = uid(); updateSent();
    };
    form.querySelector('[data-preview]').onclick = () => openEditor(d);
    form.onsubmit = async e => {
      e.preventDefault();
      const err = form.querySelector('[data-error]'), submit = form.querySelector('[type=submit]');
      err.hidden = true;
      if (!d.message.trim()) { err.textContent = 'Write a message.'; err.hidden = false; return; }
      if (submit.disabled) return;
      const locked = [...form.querySelectorAll('input, textarea, button'), ...rail.querySelectorAll('[data-requests], [data-new], [data-delete]')];
      locked.forEach(el => { el.disabled = true; });
      const thread = selected;
      try {
        if (d.diag && !d.bundle) { d.bundle = await capture(); updateSent(); }
        const body = {message: d.message, diagnostics: d.diag ? d.bundle.id : ''};
        if (!thread) Object.assign(body, {email: d.email.trim(), include_ids: d.ids});
        const next = await call('POST', thread ? `/support/tickets/${encodeURIComponent(thread)}/messages` : '/support/tickets', body, d.key);
        state.tickets = [next, ...state.tickets.filter(t => t.id !== next.id)];
        drafts.delete(thread); selected = next.id;
        if (rail?.isConnected) { renderTickets(); renderThread(); renderComposer(); }
        locked.forEach(el => { el.disabled = false; });
        say(d.diag ? 'Sent with diagnostics.' : 'Sent.'); schedule();
      } catch (error) { err.textContent = error.message; err.hidden = false; locked.forEach(el => { el.disabled = false; }); }
    };
    updateSent();
  }
  function updateSent() {
    if (!rail?.isConnected) return;
    const d = draft(), parts = ['message'];
    if (!selected && d.email.trim()) parts.push('email ' + d.email.trim());
    if (!selected && d.ids) parts.push('version ' + (compose?.version || 'unknown'), 'install ID ' + compose?.install_id);
    if (d.diag) parts.push('redacted diagnostics' + (d.bundle ? ' (' + Math.max(1, Math.ceil(d.bundle.bytes / 1024)) + ' KB)' : ''));
    rail.querySelector('[data-sent]').textContent = 'Sends to ' + compose?.to + ': ' + parts.join(', ') + '.';
  }
  async function openEditor(d) {
    if (editor) return;
    const dialog = document.createElement('dialog'); editor = dialog;
    dialog.className = 'tmodal support-modal'; dialog.setAttribute('aria-label', 'Review and edit diagnostics');
    dialog.innerHTML = `<div class="tmodal-head"><strong>Review and edit diagnostics</strong><span class="spacer"></span><button type="button" class="ghost" data-close aria-label="Close">✕</button></div>
      <div class="tmodal-body"><p>Remove sections or edit the JSON below. Secrets are redacted again before you attach it. Nothing is sent to support here.</p>
      <div data-sections class="support-sections"></div><label for="support-json">Exact attachment</label><textarea id="support-json" class="support-json" spellcheck="false" aria-label="Diagnostics JSON"></textarea>
      <p class="support-sent" data-result role="status">Loading diagnostics…</p><p class="err" data-error role="alert" hidden></p>
      <div class="support-row"><button class="ghost" type="button" data-refresh>Refresh capture</button><button class="ghost" type="button" data-save>Check edits</button><button class="primary" type="button" data-use disabled>Use diagnostics</button></div></div>`;
    document.body.appendChild(dialog); dialog.showModal();
    const area = dialog.querySelector('textarea'), err = dialog.querySelector('[data-error]'), result = dialog.querySelector('[data-result]'), use = dialog.querySelector('[data-use]');
    let base = d.bundle, checked = null, loading = false;
    const fail = e => { err.textContent = e.message; err.hidden = false; };
    const invalidate = () => { checked = null; use.disabled = true; result.textContent = 'Check edits to see the final redacted attachment.'; };
    area.oninput = invalidate;
    const show = bundle => {
      base = checked = bundle; area.value = bundle.text; use.disabled = false;
      result.textContent = 'This is the exact attachment (' + Math.ceil(bundle.bytes / 1024) + ' KB).';
      const data = JSON.parse(bundle.text), sections = dialog.querySelector('[data-sections]');
      sections.innerHTML = Object.keys(data).filter(k => !['format', 'created', 'capture'].includes(k)).map(k => `<label><input type="checkbox" data-section="${escape(k)}" checked> ${escape(k)}</label>`).join('');
      sections.onchange = e => {
        const key = e.target.dataset.section;
        if (!key) return;
        try { const value = JSON.parse(area.value); if (e.target.checked) value[key] = data[key]; else delete value[key]; area.value = JSON.stringify(value, null, 2); invalidate(); }
        catch (_) { fail(new Error('Fix the JSON before changing sections.')); e.target.checked = !e.target.checked; }
      };
    };
    const load = async () => {
      if (loading) return;
      loading = true; err.hidden = true; use.disabled = true;
      try { show(await capture()); }
      catch (e) { fail(e); }
      finally { loading = false; }
    };
    dialog.querySelector('[data-refresh]').onclick = () => {
      if (area.value && !confirm('Replace this capture and its edits with current diagnostics?')) return;
      void load();
    };
    dialog.querySelector('[data-save]').onclick = async () => {
      if (loading || !base) return;
      err.hidden = true; loading = true; use.disabled = true;
      try {
        const input = area.value;
        JSON.parse(input);
        const value = await call('POST', '/support/diagnostics', {id: base.id, text: input});
        // An in-flight validation must not overwrite text the user continued editing.
        if (area.value !== input) { invalidate(); return; }
        show(value); result.textContent = 'Edits checked and redacted. Review the final text, then use this attachment.';
      } catch (e) { fail(e); }
      finally { loading = false; }
    };
    use.onclick = () => {
      if (!checked || loading) return;
      d.bundle = checked; d.diag = true; d.key = uid();
      if (rail?.isConnected) { rail.querySelector('[name=diag]').checked = true; updateSent(); }
      dialog.close();
    };
    dialog.querySelector('[data-close]').onclick = () => dialog.close();
    dialog.onclose = () => { editor = null; dialog.remove(); };
    if (base) show(base); else await load();
  }
  window.supportLeave = () => { editor?.close(); rail = null; schedule(); };
  window.supportHelp = async page => {
    const actor = typeof S === 'undefined' ? '' : S.me?.id;
    if (owner !== actor) { if (owner) browserFailures.length = 0; owner = actor; drafts = new Map(); selected = ''; compose = null; state = {enabled: null, tickets: [], unread: 0}; }
    try {
      accept(await call('GET', '/support/tickets'));
      if (!state.enabled || !page.isConnected) { page.querySelector('.help-support-link')?.remove(); return; }
      compose = await call('GET', '/support/compose');
      if (!page.isConnected) return;
      const main = page.parentElement; main.classList.add('help-layout');
      rail = document.createElement('aside'); rail.id = 'support-rail'; rail.className = 'support-rail'; rail.setAttribute('aria-label', 'Support');
      rail.innerHTML = `<div class="rail-sec"><div class="support-head"><h2>Support</h2><span class="spacer"></span><button type="button" class="ghost" data-new>New request</button></div><p class="support-sent">Replies appear here. You can leave and come back.</p>
        <label class="sr-only" for="support-requests">Your requests</label><select id="support-requests" data-requests aria-label="Your requests"></select>
        <div class="support-head"><small data-status></small><span class="spacer"></span><button class="ghost" data-read type="button">Mark read</button><button class="ghost danger" data-delete type="button">Delete</button></div></div>
        <div class="support-thread" data-thread aria-label="Support conversation"></div>
        <p class="support-sent" data-closed hidden>This request is closed. Start a new request if you need more help.</p>
        <form class="support-write rail-sec" data-compose novalidate></form>
        <div class="support-connection"><small data-connection role="status"></small><button class="ghost" type="button" data-refresh>Refresh</button></div>`;
      main.appendChild(rail);
      main.insertAdjacentHTML('beforeend', railEdgeHTML('right', 'Resize support panel', 'support-rail'));
      const choose = id => { selected = id; renderTickets(); renderThread(); renderComposer(); void readVisible(); };
      rail.querySelector('[data-requests]').onchange = e => choose(e.target.value);
      rail.querySelector('[data-new]').onclick = () => choose('');
      rail.querySelector('[data-refresh]').onclick = refresh;
      rail.querySelector('[data-read]').onclick = readVisible;
      rail.querySelector('[data-delete]').onclick = async () => {
        const id = selected;
        if (!id || !confirm('Delete this request and its diagnostics?')) return;
        try { await call('DELETE', `/support/tickets/${encodeURIComponent(id)}`); state.tickets = state.tickets.filter(t => t.id !== id); drafts.delete(id); choose(''); }
        catch (e) { say(e.message, true); }
      };
      if (selected && !current()) selected = '';
      if (!selected && !drafts.has('') && state.tickets.length) selected = (state.tickets.find(t => t.unread) || state.tickets[0]).id;
      renderTickets(); renderThread(); renderComposer();
      await refresh(); schedule();
    } catch (e) { if (page.isConnected) { const p = document.createElement('p'); p.className = 'err'; p.textContent = e.message; page.appendChild(p); } }
  };
  window.supportPoll = refresh;
  document.addEventListener('visibilitychange', () => { if (!document.hidden && state.enabled) { void refresh(); schedule(); } });
  window.addEventListener('load', () => setTimeout(async () => {
    if (typeof S === 'undefined' || !S.me || state.enabled !== null) return;
    try { accept(await call('GET', '/support/tickets')); schedule(); } catch (_) { /* Help offers a retry */ }
  }, 3000));
})();
