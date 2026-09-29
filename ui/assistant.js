/* The Assistant tab on your own person page (docs/assistant.md): your private chat with the company's
   assistant. It answers lookups at once (what is waiting on you, search, "open X", how do I ...) and
   hands everything else to the assistant bot, which acts as you and never more. Anything with a side
   effect that matters arrives as a Confirm / Cancel card; only your click runs it.
   index.html calls window.assistantChat.mount(host, deps) when the tab opens and
   window.assistantChat.prefill(text) from search ("Ask the Assistant..."); deps keeps this file
   free of the page's globals (get, post, esc, me). */
(function () {
  const css = `
.asst{display:flex;flex-direction:column;gap:10px;min-height:0}
.asst-log{display:flex;flex-direction:column;gap:2px;min-height:220px;max-height:min(62vh,640px);overflow-y:auto;padding:4px 2px 8px}
.asst-msg{max-width:min(78ch,92%);border-radius:10px;padding:8px 12px;margin:4px 0;overflow-wrap:anywhere;line-height:1.45}
.asst-msg.you{align-self:flex-end;background:var(--surface2);border:1px solid var(--line);border-bottom-right-radius:3px}
.asst-msg.bot{align-self:flex-start;padding-left:0;padding-right:0}
.asst-msg p{margin:0 0 6px}.asst-msg p:last-child{margin-bottom:0}
.asst-msg ul{margin:4px 0 6px;padding-left:20px}
.asst-msg a{text-decoration:underline;text-underline-offset:2px}
.asst-msg .asst-h{display:block;margin:6px 0 2px;font-weight:600}
.asst-card{align-self:flex-start;width:min(560px,100%);border:1px solid var(--line);border-radius:10px;padding:10px 12px;margin:6px 0;background:var(--surface)}
.asst-card b{display:block;margin-bottom:2px}
.asst-body{margin:4px 0;padding-left:18px;font-size:13px;overflow-wrap:anywhere}
.asst-card code{display:block;font-size:12px;color:var(--muted);overflow-wrap:anywhere;margin:2px 0 8px}
.asst-card .asst-row{display:flex;gap:8px;flex-wrap:wrap;align-items:center}
.asst-state{font-size:12.5px;color:var(--muted)}
.asst-think{align-self:flex-start;color:var(--muted);font-size:13px;padding:6px 0}
.asst-think i{display:inline-block;width:5px;height:5px;margin-left:3px;border-radius:50%;background:currentColor;animation:asst-dot 1.2s infinite ease-in-out}
.asst-think i:nth-child(3){animation-delay:.15s}.asst-think i:nth-child(4){animation-delay:.3s}
@keyframes asst-dot{0%,80%,100%{opacity:.25}40%{opacity:1}}
@media (prefers-reduced-motion:reduce){.asst-think i{animation:none}}
.asst-form{display:flex;gap:8px;align-items:flex-end}
.asst-form textarea{flex:1 1 auto;min-width:0;min-height:44px;max-height:180px;resize:vertical;font-size:16px}
.asst-hints{display:flex;gap:6px;flex-wrap:wrap}
.asst-hints button{font-size:12.5px}
.asst-off{padding:14px 0}
.asst-err{color:var(--fail);font-size:12.5px}
@media (max-width:760px){
  .asst-log{max-height:none;min-height:0;flex:1 1 auto;padding-bottom:4px}
  .asst-msg{max-width:100%}
  .asst-form{position:sticky;bottom:0;padding:8px 0 calc(8px + env(safe-area-inset-bottom));background:var(--bg)}
  .asst-form .primary{min-height:44px}
}`;

  let draft = '';             // what search handed over: the box opens with it
  let live = null;            // the mounted chat, if any

  function style() {
    if (document.getElementById('asst-style')) return;
    const el = document.createElement('style');
    el.id = 'asst-style';
    el.textContent = css;
    document.head.appendChild(el);
  }

  // Text to safe HTML: everything escaped first, then only links, bold, code and bullets put back.
  // A link is an in-app route (#/...) that opens in place, or https that opens in a new tab.
  function render(text, esc) {
    const inline = s => esc(s)
      .replace(/\[([^\]]+)\]\((#\/[^)\s]*)\)/g, (_, t, h) => `<a href="${h}">${t}</a>`)
      .replace(/\[([^\]]+)\]\((https:\/\/[^)\s]+)\)/g, (_, t, h) => `<a href="${h}" target="_blank" rel="noopener noreferrer">${t}</a>`)
      .replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>')
      .replace(/`([^`]+)`/g, '<code>$1</code>');
    const out = [];
    let list = null;
    for (const line of String(text || '').split('\n')) {
      const bullet = line.match(/^\s*[-*]\s+(.*)$/);
      if (bullet) { if (!list) { list = []; out.push(list); } list.push(inline(bullet[1])); continue; }
      list = null;
      if (line.trim()) out.push(inline(line));
    }
    return out.map(part => Array.isArray(part) ? `<ul>${part.map(li => `<li>${li}</li>`).join('')}</ul>` : `<p>${part}</p>`).join('');
  }

  function mount(host, deps) {
    if (!host) return;
    style();
    const {get, post, esc, me, toast} = deps;
    const mine = 'human:' + me.id;
    const state = {data: null, thinking: false, timer: null, sending: false, gone: false};
    host.innerHTML = '<div class="asst" data-assistant><p class="asst-state">Loading…</p></div>';
    const root = host.firstElementChild;

    function stop() { clearTimeout(state.timer); state.timer = null; }
    live = {
      prefill(text) { const box = root.querySelector('textarea'); if (box) { box.value = text; box.focus(); } else draft = text; },
      stop() { state.gone = true; stop(); },
    };

    async function load() {
      try { state.data = await get('/v2/assistant'); } catch (e) { root.innerHTML = `<p class="asst-err">${esc(e.message)}</p>`; return; }
      const run = state.data.execution;
      state.thinking = !!run && ['queued', 'leased', 'running', 'input', 'uncertain'].includes(run.state);
      draw();
      stop();
      if (state.thinking && !state.gone && document.body.contains(root)) state.timer = setTimeout(load, 1500);
    }

    function messageHtml(m) {
      const cardId = m.refs?.action;
      if (cardId) return cardHtml(state.data.actions?.[cardId], m);
      const you = m.from_actor === mine;
      return `<div class="asst-msg ${you ? 'you' : 'bot'}" data-from="${you ? 'me' : 'assistant'}">${render(m.body, esc)}</div>`;
    }

    function cardHtml(action, m) {
      if (!action) return `<div class="asst-msg bot">${render(m.body, esc)}</div>`;
      const done = {done: 'Done.', failed: 'It did not go through' + (action.result?.error ? ': ' + action.result.error : '.'),
        cancelled: 'Cancelled.', expired: 'Expired: ask again.', running: 'Running…'}[action.status];
      const shown = v => { const t = typeof v === 'string' ? v : JSON.stringify(v); return t.length > 300 ? t.slice(0, 300) + '…' : t; };
      // What will really happen comes from the server; the assistant's own words are only its summary.
      const changes = action.diff?.length
        ? `<ul class="asst-body" aria-label="Changes">${action.diff.map(d => `<li><strong>${esc(d.field)}</strong>: ${esc(shown(d.old ?? ''))} → ${esc(shown(d.new))}</li>`).join('')}</ul>`
        : Object.keys(action.body || {}).length
          ? `<ul class="asst-body" aria-label="Details">${Object.entries(action.body).map(([k, v]) => `<li><strong>${esc(k)}</strong>: ${esc(shown(v))}</li>`).join('')}</ul>` : '';
      return `<div class="asst-card" data-action="${esc(action.id)}" data-status="${esc(action.status)}">
        <b data-what>${esc(action.description || action.method + ' ' + action.path)}</b>
        <span class="asst-state">${esc(action.proposed_via === 'assistant' ? 'The assistant says: ' : '')}“${esc(action.summary)}”</span>
        ${changes}
        <code>${esc(action.method)} ${esc(action.path)}</code>
        ${action.status === 'pending'
          ? `<div class="asst-row"><button class="primary" type="button" data-confirm>Confirm</button>
              <button class="ghost" type="button" data-cancel>Cancel</button>
              <span class="asst-state">Runs as you, only when you confirm.</span></div>`
          : `<div class="asst-state">${esc(done || action.status)}</div>`}</div>`;
    }

    function draw() {
      const d = state.data;
      if (!d.available) {
        root.innerHTML = `<div class="asst-off"><p><strong>The ${esc(d.name)} is off.</strong> ${d.can_turn_on
          ? `Turn it on to get a private assistant that finds things in ${esc(document.title || 'Tico')} and does them for you.`
          : `Ask the owner of this company to turn it on.`}</p>
          ${d.can_turn_on ? '<button class="primary" type="button" data-turn-on>Turn on the Assistant</button> <span class="asst-state" data-turn-status></span>' : ''}</div>`;
        const on = root.querySelector('[data-turn-on]');
        if (on) on.onclick = async () => {
          on.disabled = true;
          try { const r = await post('/v2/assistant/turn-on', {}); if (r.state !== 'active') root.querySelector('[data-turn-status]').textContent = 'Restored, but it needs a computer before it can answer (Settings).'; else await load(); }
          catch (e) { on.disabled = false; root.querySelector('[data-turn-status]').innerHTML = `<span class="asst-err">${esc(e.message)}</span>`; }
        };
        return;
      }
      const box = root.querySelector('textarea');
      const kept = box ? box.value : draft;
      draft = '';
      const hints = d.messages.length ? '' : `<div class="asst-hints" aria-label="Things to ask">${
        ["What's waiting on me?", 'Find the launch plan', 'How do I add a bot?'].map(t => `<button class="ghost" type="button" data-hint="${esc(t)}">${esc(t)}</button>`).join('')}</div>`;
      root.innerHTML = `<div class="asst-log" role="log" aria-live="polite" aria-label="Assistant chat">${
        d.messages.length ? d.messages.map(messageHtml).join('') : `<p class="asst-state">Ask for anything in ${esc(document.title || 'Tico')}: what is waiting on you, find a doc or a meeting, make a task, hand work to a bot, or ask how something works.</p>`}${
        state.thinking ? `<div class="asst-think" data-thinking role="status">${esc(d.name)} is thinking<i></i><i></i><i></i></div>` : ''}</div>
        ${hints}
        <form class="asst-form" data-form><textarea rows="2" maxlength="8000" placeholder="Ask the ${esc(d.name)}…" aria-label="Message to the ${esc(d.name)}"></textarea>
        <button class="primary" type="submit"${state.sending ? ' disabled' : ''}>Send</button></form>`;
      const log = root.querySelector('.asst-log');
      log.scrollTop = log.scrollHeight;
      const area = root.querySelector('textarea');
      area.value = kept;
      if (kept) area.focus();
      area.onkeydown = ev => { if (ev.key === 'Enter' && !ev.shiftKey && !ev.isComposing) { ev.preventDefault(); root.querySelector('[data-form]').requestSubmit(); } };
      root.querySelector('[data-form]').onsubmit = ev => { ev.preventDefault(); send(area.value); };
      root.querySelectorAll('[data-hint]').forEach(b => b.onclick = () => send(b.dataset.hint));
      root.querySelectorAll('.asst-card').forEach(card => {
        const id = card.dataset.action;
        const yes = card.querySelector('[data-confirm]'), no = card.querySelector('[data-cancel]');
        if (yes) yes.onclick = () => decide(card, id, 'confirm');
        if (no) no.onclick = () => decide(card, id, 'cancel');
      });
    }

    async function decide(card, id, verb) {
      card.querySelectorAll('button').forEach(b => { b.disabled = true; });
      try { await post(`/v2/assistant/actions/${encodeURIComponent(id)}/${verb}`, {}); }
      catch (e) { toast?.(e.message, true); }
      await load();
    }

    async function send(text) {
      text = String(text || '').trim();
      if (!text || state.sending) return;
      state.sending = true;
      const d = state.data;
      // Your words show at once; the answer follows (at once for a lookup, in a moment for the bot).
      d.messages = [...d.messages, {id: 'pending', from_actor: mine, body: text, refs: {}}];
      state.thinking = true;
      draw();
      try {
        const r = await post('/v2/assistant/messages', {text});
        state.thinking = !r.fast;
      } catch (e) {
        state.thinking = false;
        toast?.(e.message, true);
      } finally { state.sending = false; }
      await load();
    }

    void load();
  }

  // Settings > Bots, owner only: when the company has no Assistant (archived at setup, or never added),
  // one button restores it or adds it from the catalog, and every person's Assistant tab starts working.
  async function settingsStrip(host, deps) {
    if (!host) return;
    style();
    const {get, post, esc, toast, after} = deps;
    let info;
    try { info = await get('/v2/assistant'); } catch { host.innerHTML = ''; return; }
    if (info.available || !info.can_turn_on) { host.innerHTML = ''; return; }
    host.innerHTML = `<section class="card" data-assistant-off><header><h2>The Assistant is off</h2></header>
      <p>Everyone gets a private Assistant on their own page once it is on. It ${info.state === 'archived' ? 'was set aside when this company was set up; turning it on brings it back with its history.' : 'has not been added to this company yet; turning it on adds it from the catalog.'}</p>
      <div class="asst-row"><button class="primary" type="button" data-turn-on>Turn on Assistant</button><span class="asst-state" data-turn-status role="status"></span></div></section>`;
    const button = host.querySelector('[data-turn-on]'), status = host.querySelector('[data-turn-status]');
    button.onclick = async () => {
      button.disabled = true; status.textContent = 'Turning it on…';
      try {
        const r = await post('/v2/assistant/turn-on', {});
        status.textContent = r.state === 'active' ? 'On.' : 'Restored, but it needs a computer before it can answer: add one under Computers.';
        toast?.(r.state === 'active' ? 'The Assistant is on' : 'The Assistant is restored and waiting for a computer');
        await after?.();
        if (r.state === 'active') host.innerHTML = '';
      } catch (e) { button.disabled = false; status.innerHTML = `<span class="asst-err">${esc(e.message)}</span>`; }
    };
  }

  window.assistantChat = {
    mount,
    settingsStrip,
    render,
    prefill(text) { if (live) live.prefill(text); else draft = text; },
    stop() { live?.stop(); live = null; },
  };
})();
