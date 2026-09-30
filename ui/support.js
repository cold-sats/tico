/* Contact support (backend/support.py, docs/support.md): the form on the Help page, "Your requests" beneath it, and a small
   notice when the Tico team replies. Nothing is sent until Send is pressed. Everything a ticket says, from either side, is
   text: it is escaped here and never rendered as HTML. */
(function () {
  const API_BASE = () => (typeof API === 'string' ? API : '/api') + '/v2';
  const escape = s => String(s ?? '').replace(/[&<>"']/g, c => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[c]));
  const say = (msg, isErr) => (typeof toast === 'function' ? toast(msg, isErr) : undefined);
  const STATUS = {open: ['Open', 'waiting'], answered: ['Answered', 'ok'], closed: ['Closed', ''], gone: ['Removed', '']};
  const POLL_MS = 5 * 60 * 1000;

  let state = {enabled: null, tickets: [], unread: 0};
  let toasted = 0, timer = null, stopped = false;

  async function call(method, path, body) {
    const r = await fetch(API_BASE() + path, {
      method, cache: 'no-store',
      headers: body === undefined ? {} : {'Content-Type': 'application/json', 'Idempotency-Key': (crypto.randomUUID ? crypto.randomUUID() : String(Date.now()))},
      body: body === undefined ? undefined : JSON.stringify(body)});
    const data = await r.json().catch(() => ({}));
    if (!r.ok) {
      const detail = data && data.error && (data.error.detail || data.error.message);
      throw Object.assign(new Error(detail || (typeof data.detail === 'string' ? data.detail : '') || 'Could not do that.'), {status: r.status});
    }
    return data;
  }

  function css() {
    if (document.getElementById('support-css')) return;
    const style = document.createElement('style');
    style.id = 'support-css';
    style.textContent = `
      #help-open[data-support-unread]{position:relative}
      #help-open[data-support-unread]::after{content:"";position:absolute;top:-2px;right:-2px;width:9px;height:9px;border-radius:50%;background:var(--accent);border:2px solid var(--surface)}
      .support-modal{width:min(560px,calc(100vw - 32px))}
      .support-modal .tmodal-body{display:grid;gap:12px}
      .support-modal label{display:grid;gap:4px;font-size:12.5px;color:var(--muted)}
      .support-modal textarea,.support-modal input[type=email]{width:100%;box-sizing:border-box;padding:8px 10px;border:1px solid var(--line);border-radius:8px;background:var(--surface);color:var(--ink)}
      .support-modal textarea{min-height:140px;resize:vertical}
      .support-modal .support-check{display:flex;align-items:center;gap:8px;color:var(--ink);font-size:13px}
      .support-sent{margin:0;font-size:12px;line-height:1.45;color:var(--muted);overflow-wrap:anywhere}
      .support-row{display:flex;gap:8px;align-items:center;justify-content:flex-end}
      .support-mine{max-width:960px;margin:20px auto 0}
      .support-mine h2{font-size:15px;margin:0 0 8px}
      .support-ticket{border:1px solid var(--line);border-radius:10px;background:var(--surface);margin:0 0 8px;padding:0}
      .support-ticket>summary{display:flex;gap:10px;align-items:center;padding:10px 12px;cursor:pointer;list-style:none}
      .support-ticket>summary::-webkit-details-marker{display:none}
      .support-ticket .support-line{flex:1;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
      .support-ticket .support-when{color:var(--muted);font-size:12px;white-space:nowrap}
      .support-ticket .support-dot{width:8px;height:8px;border-radius:50%;background:var(--accent);flex:none}
      .support-thread{display:grid;gap:10px;padding:0 12px 12px}
      .support-msg{white-space:pre-wrap;overflow-wrap:anywhere;padding:8px 10px;border-radius:8px;background:var(--surface2);font-size:13.5px}
      .support-msg.staff{border-left:3px solid var(--accent)}
      .support-msg .support-who{display:block;font-size:11px;color:var(--muted);margin-bottom:2px}
      .support-write{display:grid;gap:8px}
      .support-write textarea{width:100%;box-sizing:border-box;min-height:64px;padding:8px 10px;border:1px solid var(--line);border-radius:8px;background:var(--surface);color:var(--ink);resize:vertical}`;
    document.head.appendChild(style);
  }

  const when = iso => { const d = new Date(iso); return isNaN(d) ? '' : d.toLocaleString(undefined, {month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit'}); };
  const summary = m => { const one = String(m).replace(/\s+/g, ' ').trim(); return one.length > 90 ? one.slice(0, 89) + '…' : one; };

  function mark() {
    const link = document.getElementById('help-open');
    if (!link) return;
    if (state.unread > 0) link.setAttribute('data-support-unread', String(state.unread));
    else link.removeAttribute('data-support-unread');
  }

  // Redraw the list on the Help page after a refresh, unless the person is in the middle of writing back.
  function repaint() {
    const page = document.getElementById('help-page');
    if (!page || !page.querySelector('#support-mine')) return;
    if ([...page.querySelectorAll('#support-mine textarea')].some(t => t.value)) return;
    renderList(page);
  }

  function accept(data) {
    state = {enabled: data.enabled !== false, tickets: data.tickets || [], unread: data.unread || 0};
    mark();
    repaint();
    if (state.unread > toasted) say('Tico support replied.');
    toasted = state.unread;
    return state;
  }

  async function refresh() {
    if (stopped) return state;
    try {
      const data = await call('POST', '/support/tickets/refresh');
      return accept(data);
    } catch (e) {
      if (e.status === 401 || e.status === 403 || e.status === 409) stopped = true;
      return state;
    }
  }

  function schedule() {
    clearTimeout(timer);
    if (stopped) return;
    timer = setTimeout(async () => {
      if (!document.hidden && state.tickets.some(t => t.status !== 'closed' && t.status !== 'gone')) await refresh();
      schedule();
    }, POLL_MS);
  }

  // ---------------------------------------------------------------- the form
  async function openForm(onSent) {
    let form;
    try { form = await call('GET', '/support/compose'); } catch (e) { say(e.message, true); return; }
    const dialog = document.createElement('dialog');
    dialog.className = 'tmodal support-modal';
    dialog.setAttribute('aria-label', 'Contact support');
    dialog.innerHTML = `<div class="tmodal-head"><span class="who">Contact support</span><span class="spacer"></span><button type="button" class="ghost tmodal-x" data-close aria-label="Close">✕</button></div>
      <form class="tmodal-body" novalidate>
        <label>Message<textarea name="message" maxlength="${Number(form.max) || 4000}" required autofocus></textarea></label>
        <label>Email for a reply<input type="email" name="email" autocomplete="email" value="${escape(form.email)}"></label>
        <label class="support-check"><input type="checkbox" name="ids" checked> Include version and install ID</label>
        <p class="support-sent" data-sent aria-live="polite"></p>
        <p class="err" data-error hidden></p>
        <div class="support-row"><button type="button" class="ghost" data-close>Cancel</button><button type="submit" class="primary">Send</button></div>
      </form>`;
    document.body.appendChild(dialog);
    const f = dialog.querySelector('form'), sent = dialog.querySelector('[data-sent]'), err = dialog.querySelector('[data-error]');
    const line = () => {
      const parts = ['message'];
      if (f.email.value.trim()) parts.push('email ' + f.email.value.trim());
      if (f.ids.checked) {
        if (form.version) parts.push('version ' + form.version);
        parts.push('install ID ' + form.install_id);
      }
      sent.textContent = 'Sends to ' + form.to + ': ' + parts.join(', ') + '.';
    };
    line();
    f.addEventListener('input', line);
    dialog.querySelectorAll('[data-close]').forEach(b => b.onclick = () => dialog.close());
    dialog.onclose = () => dialog.remove();
    f.onsubmit = async ev => {
      ev.preventDefault();
      err.hidden = true;
      if (!f.message.value.trim()) { err.textContent = 'Write a message.'; err.hidden = false; return; }
      const submit = f.querySelector('[type=submit]');
      submit.disabled = true;
      try {
        const ticket = await call('POST', '/support/tickets', {message: f.message.value, email: f.email.value.trim(), include_ids: f.ids.checked});
        dialog.close();
        say('Sent.');
        state.tickets = [ticket, ...state.tickets];
        onSent && onSent(ticket);
        schedule();
      } catch (e) {
        err.textContent = e.message; err.hidden = false; submit.disabled = false;
      }
    };
    dialog.showModal();
    f.message.focus();
  }

  // ---------------------------------------------------------------- your requests
  function ticketHTML(t) {
    const [label, tone] = STATUS[t.status] || [t.status, ''];
    const thread = [`<div class="support-msg"><span class="support-who">You, ${escape(when(t.created))}</span>${escape(t.message)}</div>`]
      .concat((t.messages || []).map(m => `<div class="support-msg ${m.from === 'staff' ? 'staff' : ''}"><span class="support-who">${m.from === 'staff' ? 'Tico support' : 'You'}, ${escape(when(m.created))}</span>${escape(m.body)}</div>`));
    const write = t.status === 'closed' || t.status === 'gone' ? '' :
      `<form class="support-write" data-write><textarea maxlength="4000" placeholder="Write back" aria-label="Write back"></textarea><div class="support-row"><button type="button" class="ghost danger" data-delete>Delete</button><button type="submit" class="ghost">Send</button></div></form>`;
    return `<details class="support-ticket" data-ticket="${escape(t.id)}" data-status="${escape(t.status)}">
      <summary>${t.unread ? '<span class="support-dot" aria-label="New reply"></span>' : ''}<span class="support-line">${escape(summary(t.message))}</span><span class="pill ${tone}">${escape(label)}</span><span class="support-when">${escape(when(t.created))}</span></summary>
      <div class="support-thread">${thread.join('')}${write || `<div class="support-row"><button type="button" class="ghost danger" data-delete>Delete</button></div>`}</div></details>`;
  }

  function renderList(root) {
    const host = root.querySelector('#support-mine');
    if (!host) return;
    if (!state.tickets.length) { host.hidden = true; return; }
    host.hidden = false;
    const open = new Set([...host.querySelectorAll('details[open]')].map(d => d.dataset.ticket));
    host.querySelector('[data-list]').innerHTML = state.tickets.map(ticketHTML).join('');
    host.querySelectorAll('details').forEach(d => { if (open.has(d.dataset.ticket)) d.open = true; });
  }

  function wire(root) {
    const host = root.querySelector('#support-mine');
    // Opening a request (the person's own click) reads it.
    host.addEventListener('click', async e => {
      const summary = e.target.closest('summary');
      const d = summary && summary.parentElement;
      if (!d || !d.matches('details.support-ticket') || d.open) return;       // open is still the old state here
      const t = state.tickets.find(x => x.id === d.dataset.ticket);
      if (!t || !t.unread) return;
      try {
        const next = await call('POST', `/support/tickets/${encodeURIComponent(t.id)}/read`);
        Object.assign(t, next);
        state.unread = state.tickets.reduce((n, x) => n + (x.unread || 0), 0);
        toasted = Math.min(toasted, state.unread);
        mark();
        d.querySelector('.support-dot')?.remove();
      } catch (_) { /* the dot stays until the next look */ }
    });
    host.addEventListener('submit', async e => {
      const form = e.target.closest('[data-write]');
      if (!form) return;
      e.preventDefault();
      const text = form.querySelector('textarea').value;
      if (!text.trim()) return;
      const id = form.closest('[data-ticket]').dataset.ticket;
      try {
        const next = await call('POST', `/support/tickets/${encodeURIComponent(id)}/messages`, {message: text});
        state.tickets = state.tickets.map(x => x.id === id ? next : x);
        renderList(root);
        root.querySelector(`[data-ticket="${CSS.escape(id)}"]`).open = true;
        say('Sent.');
      } catch (err) { say(err.message, true); }
    });
    host.addEventListener('click', async e => {
      const button = e.target.closest('[data-delete]');
      if (!button) return;
      const id = button.closest('[data-ticket]').dataset.ticket;
      if (!confirm('Delete this request?')) return;
      try {
        await call('DELETE', `/support/tickets/${encodeURIComponent(id)}`);
        state.tickets = state.tickets.filter(x => x.id !== id);
        renderList(root);
      } catch (err) { say(err.message, true); }
    });
  }

  // The one hook the Help page calls after it draws itself (ui/app/help.js, pageHelp).
  window.supportHelp = async function supportHelp(page) {
    css();
    if (!page || page.querySelector('#support-mine')) return;
    const first = state.enabled === null;
    if (first) {
      try { accept(await call('GET', '/support/tickets')); } catch (_) { state.enabled = false; }
    }
    if (!state.enabled) return;
    const actions = page.querySelector('.help-actions');
    if (actions) {
      const button = document.createElement('button');
      button.type = 'button'; button.className = 'ghost'; button.dataset.supportOpen = '';
      button.textContent = 'Contact support';
      actions.appendChild(button);
      button.onclick = () => openForm(() => { renderList(page); const d = page.querySelector('details.support-ticket'); if (d) d.open = true; });
    }
    const section = document.createElement('section');
    section.id = 'support-mine'; section.className = 'support-mine'; section.hidden = true;
    section.innerHTML = '<h2>Your requests</h2><div data-list></div>';
    const anchor = page.querySelector('.help-foot');
    if (anchor) anchor.before(section); else page.appendChild(section);
    wire(page);
    renderList(page);
    const latest = await refresh();
    if (document.body.contains(section)) renderList(page);
    schedule();
    return latest;
  };

  // A reply reaches a person on any page: ask now and then, only while something is open.
  window.supportPoll = refresh;
  const start = async () => {
    css();
    if (typeof S === 'undefined' || !S.me) return setTimeout(start, 2000);
    if (state.enabled === null) {
      try { accept(await call('GET', '/support/tickets')); } catch (_) { stopped = true; return; }
    }
    if (state.enabled && state.tickets.some(t => t.status !== 'closed' && t.status !== 'gone')) await refresh();
    schedule();
  };
  window.addEventListener('load', () => setTimeout(start, 3000));
})();
