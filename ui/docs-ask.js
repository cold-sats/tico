/* Ask AI on the Docs page (docs/librarian.md): a right-side drawer on a desktop, a full-screen sheet on a
   phone. Type a question and matching docs, internal and linked, show at once from the search that comes
   back with POST /api/v2/docs/ask; the Librarian's answer then streams in from the conversation it
   went to (GET /api/v2/conversations/{id}/watch), with clickable citations. Only the person who asked
   can read that conversation.

   window.openDocsAsk(question?) opens it; with a question it asks it straight away.

   The Librarian cites [Internal doc · Title](doc:<id>) and [Linked · host](https://...). `doc:<id>` is
   turned into the Docs page route here and nowhere else (docHref). Its text is bot text: it only ever
   reaches the page through safeMd, the sanitizing renderer, never as raw HTML. Globals used from
   index.html: get, post, esc, safeMd, API, toast. */
(function () {
  const css = `
.dask-backdrop{position:fixed;inset:0;z-index:1500;background:rgba(10,14,18,.4)}
.dask{position:fixed;top:0;right:0;bottom:0;z-index:1501;width:min(460px,100vw);display:flex;flex-direction:column;background:var(--surface);color:var(--ink);border-left:1px solid var(--line);box-shadow:-12px 0 40px rgba(0,0,0,.25);animation:dask-in .18s ease-out}
@keyframes dask-in{from{transform:translateX(24px);opacity:0}to{transform:none;opacity:1}}
@media (prefers-reduced-motion:reduce){.dask{animation:none}.dask-think i{animation:none}}
.dask-head{display:flex;align-items:center;gap:10px;padding:14px 16px;border-bottom:1px solid var(--line)}
.dask-head .nav-icon{font-size:20px;color:var(--accent)}
.dask-head h2{font-size:15px}
.dask-head small{display:block;color:var(--muted);font-size:12px;font-weight:400}
.dask-head .spacer{flex:1}
.dask-new{font-size:12.5px;padding:4px 10px}
.dask-close{background:none;border:0;border-radius:6px;padding:6px 9px;font-size:16px;cursor:pointer;color:var(--muted)}
.dask-close:hover{background:var(--surface2);color:var(--ink)}
.dask-body{flex:1 1 auto;min-height:0;overflow-y:auto;padding:14px 16px;display:flex;flex-direction:column;gap:16px}
.dask-empty{color:var(--muted);font-size:13.5px}
.dask-hints{display:flex;flex-wrap:wrap;gap:6px;margin-top:10px}
.dask-hints button{font-size:12.5px}
.dask-body>section{display:flex;flex-direction:column;gap:8px}
.dask-q{align-self:flex-end;max-width:92%;background:var(--surface2);border:1px solid var(--line);border-radius:10px;border-bottom-right-radius:3px;padding:8px 12px;overflow-wrap:anywhere;white-space:pre-wrap}
.dask-label{font-size:11.5px;text-transform:uppercase;letter-spacing:.05em;color:var(--muted);margin:0 0 6px}
.dask-results{list-style:none;margin:0;padding:0;display:flex;flex-direction:column;gap:6px}
.dask-results li{border:1px solid var(--line);border-radius:8px;padding:8px 10px;background:var(--bg)}
.dask-results a{font-weight:600;overflow-wrap:anywhere}
.dask-results .dask-line{display:flex;align-items:center;gap:8px;flex-wrap:wrap}
.dask-results p{margin:3px 0 0;font-size:12.5px;color:var(--muted);overflow-wrap:anywhere}
.dask-badge{flex:none;font-size:11px;padding:1px 7px;border-radius:10px;background:var(--idle-bg);color:var(--muted);white-space:nowrap}
.dask-badge.internal{background:var(--ok-bg);color:var(--ok)}
.dask-badge.linked{background:var(--run-bg);color:var(--run)}
.dask-a{line-height:1.5;overflow-wrap:anywhere}
.dask-a p{margin:0 0 8px}.dask-a p:last-child{margin-bottom:0}
.dask-a ul,.dask-a ol{margin:4px 0 8px;padding-left:20px}
.dask-a a{text-decoration:underline;text-underline-offset:2px}
.dask-a a.dask-cite{display:inline-block;font-size:12px;line-height:1.35;padding:0 7px;border-radius:10px;border:1px solid var(--line);background:var(--bg);text-decoration:none;color:var(--accent);vertical-align:baseline}
.dask-a a.dask-cite:hover{background:var(--surface2)}
.dask-a code{font-family:var(--mono);font-size:12.5px}
.dask-think{color:var(--muted);font-size:13px}
.dask-think i{display:inline-block;width:5px;height:5px;margin-left:3px;border-radius:50%;background:currentColor;animation:dask-dot 1.2s infinite ease-in-out}
.dask-think i:nth-child(3){animation-delay:.15s}.dask-think i:nth-child(4){animation-delay:.3s}
@keyframes dask-dot{0%,80%,100%{opacity:.25}40%{opacity:1}}
.dask-err{color:var(--fail);font-size:13px}
.dask-form{display:flex;gap:8px;align-items:flex-end;padding:12px 16px calc(12px + env(safe-area-inset-bottom));border-top:1px solid var(--line);background:var(--surface)}
.dask-form textarea{flex:1 1 auto;min-width:0;min-height:44px;max-height:160px;resize:vertical;font-size:16px;padding:8px 10px;border:1px solid var(--line);border-radius:8px;background:var(--bg)}
.dask-form textarea:focus{outline:2px solid var(--accent);outline-offset:0}
.dask-form .primary{min-height:44px}
.dask-off{display:flex;flex-direction:column;gap:10px;align-items:flex-start}
@media (max-width:760px){
  .dask{inset:0;width:auto;border-left:0;box-shadow:none;height:100dvh}
  .dask-backdrop{display:none}
}`;

  // What the page keeps between opening and closing the panel: the conversation, so a follow-up has context,
  // and what was asked and answered, so closing it does not lose the thread.
  const session = {conversationId: '', turns: []};
  let panel = null, opener = null, es = null, poll = null, busy = false;

  const docHref = id => '#/docs/' + encodeURIComponent(id);
  const KINDS = {website: 'Website', google_drive: 'Google Drive', google_doc: 'Google Doc', notion: 'Notion', github: 'GitHub', other: 'Link'};
  const clean = text => String(text || '').replace(/<\/?(?:b|mark|em|strong)>/gi, '');
  const host = url => { try { return new URL(url).host; } catch { return url; } };

  function style() {
    if (document.getElementById('dask-style')) return;
    const el = document.createElement('style');
    el.id = 'dask-style';
    el.textContent = css;
    document.head.appendChild(el);
  }

  // The Librarian's markdown, sanitized. `doc:<id>` becomes the docs route first; afterwards each citation
  // is a chip, an in-app link opens in place (and closes the panel), everything else opens in a new tab.
  function answerHtml(text) {
    return safeMd(String(text || '').replace(/\]\(doc:([^)\s]+)\)/g, (_, id) => '](' + docHref(id) + ')'));
  }
  function decorate(root) {
    root.querySelectorAll('a').forEach(a => {
      const href = a.getAttribute('href') || '';
      if (/^(Internal doc|Linked) · /.test(a.textContent)) a.classList.add('dask-cite');
      if (href.startsWith('#/')) { a.removeAttribute('target'); a.addEventListener('click', () => close(false)); }
    });
  }

  function resultsHtml(results) {
    if (!results?.length) return '<p class="dask-empty" data-no-results>No matching docs, so the Librarian will look further.</p>';
    return `<ul class="dask-results" data-results>${results.map(r => r.type === 'linked'
      ? `<li data-type="linked"><div class="dask-line"><span class="dask-badge linked">Linked · ${esc(KINDS[r.kind] || 'Link')}</span><a href="${esc(r.url)}" target="_blank" rel="noopener noreferrer">${esc(r.title || host(r.url))}</a></div>${
          r.description ? `<p>${esc(r.description)}</p>` : `<p>${esc(host(r.url))}</p>`}</li>`
      : `<li data-type="internal"><div class="dask-line"><span class="dask-badge internal">Internal doc</span><a href="${esc(docHref(r.id))}" data-close>${esc(r.title || r.path)}</a></div>${
          r.excerpt ? `<p>${esc(clean(r.excerpt))}</p>` : ''}</li>`).join('')}</ul>`;
  }

  function turnHtml(t, i) {
    const state = t.error ? `<p class="dask-err" role="alert">${esc(t.error)}</p>`
      : t.answer != null ? '' : `<p class="dask-think" data-thinking role="status">The Librarian is reading the docs<i></i><i></i><i></i></p>`;
    return `<section data-turn="${i}"><div class="dask-q">${esc(t.question)}</div>
      ${t.results ? `<h3 class="dask-label">Matching docs</h3>${resultsHtml(t.results)}` : ''}
      ${(t.answer ?? t.live) ? `<h3 class="dask-label">Librarian</h3><div class="dask-a md" data-answer aria-live="polite">${answerHtml(t.answer ?? t.live)}</div>` : ''}
      ${state}</section>`;
  }

  function draw() {
    if (!panel) return;
    const body = panel.querySelector('.dask-body');
    const atEnd = body.scrollHeight - body.scrollTop - body.clientHeight < 80;
    body.innerHTML = session.turns.length ? session.turns.map(turnHtml).join('')
      : `<div class="dask-empty">
          <div class="dask-hints">${['How do we handle a refund?', 'Who owns onboarding?', 'Where is the pricing?'].map(h => `<button class="ghost" type="button" data-hint="${esc(h)}">${esc(h)}</button>`).join('')}</div></div>`;
    decorate(body);
    body.querySelectorAll('a[data-close]').forEach(a => a.addEventListener('click', () => close(false)));
    body.querySelectorAll('[data-hint]').forEach(b => { b.onclick = () => ask(b.dataset.hint); });
    if (atEnd || busy) body.scrollTop = body.scrollHeight;
    const button = panel.querySelector('.dask-form button');
    if (button) button.disabled = busy;
  }

  function stop() {
    try { es?.close(); } catch { /* already closed */ }
    es = null;
    clearInterval(poll); poll = null;
  }

  // The answer is the Librarian's message in reply to this question; while it works, what it has written
  // so far is the run's text. Anything else in the conversation (an earlier turn) is not this answer.
  function follow(turn) {
    const apply = snapshot => {
      const reply = (snapshot.messages || []).find(m => m.in_reply_to === turn.messageId && m.from_actor === 'bot:librarian');
      if (reply) { turn.answer = reply.body || ''; busy = false; stop(); }
      else if (snapshot.execution && snapshot.execution.state !== 'completed' && snapshot.execution.text) turn.live = snapshot.execution.text;
      draw();
    };
    const url = `${API}/v2/conversations/${encodeURIComponent(turn.conversationId)}/`;
    const fallback = () => {
      if (poll) return;
      poll = setInterval(async () => { try { apply(await get('/v2/conversations/' + encodeURIComponent(turn.conversationId) + '/snapshot')); } catch { /* try again */ } }, 2500);
    };
    if (typeof EventSource === 'undefined') return fallback();
    es = new EventSource(url + 'watch');
    es.addEventListener('snapshot', ev => { let d; try { d = JSON.parse(ev.data); } catch { return; } apply(d); });
    es.addEventListener('expired', () => { stop(); fallback(); });
    // The browser reconnects by itself and gets a whole snapshot; if it cannot, poll for it.
    es.addEventListener('error', () => { if (es && es.readyState === 2) { stop(); fallback(); } });
  }

  async function ask(question) {
    question = String(question || '').trim();
    if (!question || busy || !panel) return;
    busy = true;
    const turn = {question, results: null, answer: null, live: '', error: '', conversationId: session.conversationId, messageId: ''};
    session.turns.push(turn);
    draw();
    try {
      // The first question of a page session, and the first after New chat, opens a new conversation, so what
      // the Librarian remembers is what the thread on screen shows; follow-ups continue it.
      const sent = await post('/v2/docs/ask', {question, ...(session.conversationId ? {conversation_id: session.conversationId} : {new_conversation: true})});
      session.conversationId = turn.conversationId = sent.conversation_id;
      turn.messageId = sent.message_id;
      turn.results = sent.results || [];
      draw();
      follow(turn);
    } catch (e) {
      busy = false;
      const code = e?.body?.error?.code;
      if (code === 'conversation') session.conversationId = '';
      turn.error = code === 'librarian_off' ? 'The Librarian is off.' : (e && e.message) || 'That did not go through.';
      draw();
      if (code === 'librarian_off') offNotice();
    }
  }

  async function offNotice() {
    let info;
    try { info = await get('/v2/librarian'); } catch { return; }
    if (!panel || info.available) return;
    const note = document.createElement('div');
    note.className = 'dask-off';
    note.dataset.off = '';
    note.innerHTML = `<p><strong>The Librarian is ${info.state === 'missing' ? 'not set up yet' : esc(info.state)}.</strong> ${info.can_turn_on
      ? 'Turning it on adds it to a computer and it starts answering.' : 'Ask the owner of this company to turn it on.'}</p>
      ${info.can_turn_on ? '<button class="primary" type="button" data-turn-on>Turn on the Librarian</button><span class="dask-empty" data-turn-status role="status"></span>' : ''}`;
    panel.querySelector('.dask-body').append(note);
    const on = note.querySelector('[data-turn-on]');
    if (on) on.onclick = async () => {
      on.disabled = true;
      const status = note.querySelector('[data-turn-status]');
      try {
        const r = await post('/v2/librarian/turn-on', {});
        if (r.state === 'active') { note.remove(); session.turns.pop(); draw(); toast?.('The Librarian is on'); }
        else status.textContent = 'It is set up, but needs a computer with a model before it can answer (Settings).';
      } catch (e) { on.disabled = false; status.textContent = e.message; }
    };
  }

  function close(returnFocus = true) {
    if (!panel) return;
    stop();
    busy = false;
    document.removeEventListener('keydown', onKey, true);
    panel.previousElementSibling?.remove();          // the backdrop
    panel.remove();
    panel = null;
    if (returnFocus) opener?.focus?.();
  }
  function onKey(ev) {
    if (ev.key === 'Escape' && panel) { ev.stopPropagation(); close(); }
  }

  function open(question) {
    style();
    if (!panel) {
      opener = document.activeElement;
      const backdrop = document.createElement('div');
      backdrop.className = 'dask-backdrop';
      backdrop.onclick = () => close();
      panel = document.createElement('aside');
      panel.className = 'dask';
      panel.setAttribute('role', 'dialog');
      panel.setAttribute('aria-modal', 'true');
      panel.setAttribute('aria-labelledby', 'dask-title');
      panel.dataset.docsAsk = '';
      panel.innerHTML = `<header class="dask-head"><span class="nav-icon" aria-hidden="true">auto_awesome</span>
          <div><h2 id="dask-title">Ask AI</h2></div><span class="spacer"></span>
          <button class="ghost dask-new" type="button" data-new-chat>New chat</button>
          <button class="dask-close" type="button" aria-label="Close Ask AI">✕</button></header>
        <div class="dask-body"></div>
        <form class="dask-form"><textarea rows="2" maxlength="4000" aria-label="Your question" placeholder="Ask about your docs…" required></textarea>
        <button class="primary" type="submit">Ask</button></form>`;
      document.body.append(backdrop, panel);
      panel.querySelector('.dask-close').onclick = () => close();
      panel.querySelector('[data-new-chat]').onclick = () => {
        if (busy) return;
        stop(); session.conversationId = ''; session.turns = []; draw(); panel.querySelector('textarea').focus();
      };
      const box = panel.querySelector('textarea');
      box.onkeydown = ev => { if (ev.key === 'Enter' && !ev.shiftKey && !ev.isComposing) { ev.preventDefault(); panel.querySelector('form').requestSubmit(); } };
      panel.querySelector('form').onsubmit = ev => {
        ev.preventDefault();
        const text = box.value;
        if (text.trim() && !busy) { box.value = ''; ask(text); }
      };
      document.addEventListener('keydown', onKey, true);
      // Follow-ups keep their conversation; a turn that was still running when the panel closed is picked up again.
      const last = session.turns.at(-1);
      draw();
      if (last && last.answer == null && !last.error && last.messageId) { busy = true; draw(); follow(last); }
    }
    panel.querySelector('textarea').focus();
    if (question && question.trim()) ask(question);
  }

  window.openDocsAsk = open;
  // The old entry point, until every page that called it says openDocsAsk.
  window.openDocsChat = () => open();
})();
