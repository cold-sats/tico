/* ui/app/ask-panel.js — Ask: the person's own chat bot, a tap away on every page
   Classic script: its globals are shared with the other files under ui/app/, loaded in the order index.html lists them. */
'use strict';

// Ask (docs/assistant.md). The one way in to the Assistant (the owner's CEO Bot), to BotOps behind it, and to Tico
// support. On a computer a round button at the bottom left of the page (or ⌘J) opens a panel above it; on a phone the
// Ask tab opens it as a sheet over the page, and the tab closes it again. It is the same conversation as the Assistant
// page (#/assistant, "Show chat"): GET /v2/assistant reads it and POST /v2/assistant/messages sends with the page the
// person is on (`page`), so the turn knows what "this" means. Like the Updates chat it keeps its own small state, never
// the bot pages' (chat.js V2C), and drops the Assistant page's cached copy when it sends.
// The + adds Tico support (free) or the Tico team (full management) to the conversation: both open Support
// (ui/support.js). While a request is open it is shown as in this chat, with an × that takes it out of the panel.
const ASK_HIDDEN = 'tico.ask.hidden';
const ASK_MANAGE = "We'd like Tico to fully manage our company.";
let ASK = null;
const askPhone = () => matchMedia('(max-width:760px)').matches;
const askHiddenKey = () => ASK_HIDDEN + '.' + (S.me?.id || 'me');
function askHiddenTickets() {
  try { const v = JSON.parse(localStorage.getItem(askHiddenKey()) || '[]'); return Array.isArray(v) ? v : []; } catch { return []; }
}
// The page the person is looking at: its heading, else the address.
function askPage() {
  const path = S.route || location.hash || '';
  const heading = $('#main h1, #main h2')?.textContent.trim().replace(/\s+/g, ' ') || '';
  return {path: path.slice(0, 300), title: heading.slice(0, 200)};
}
// The Assistant page is this chat already, and setup has no room for it.
const askAway = () => !S.me || S.route === ASSISTANT || document.body.classList.contains('in-setup');
function askSync() {
  const fab = $('#ask-fab'), tab = $('#mobile-ask'), panel = $('#ask-panel');
  if (!fab || !panel) return;
  const name = myChatName(), away = askAway(), open = !!ASK?.open && !away;
  fab.hidden = away;
  panel.hidden = !open;
  document.body.classList.toggle('ask-open', open);
  for (const el of [fab, tab].filter(Boolean)) {
    el.setAttribute('aria-expanded', String(open));
    el.setAttribute('aria-label', open ? 'Close ' + name : name);
  }
  fab.title = name + ' (⌘J)';
  const label = tab?.querySelector('.mobile-nav-label'); if (label) label.textContent = open ? 'Close' : 'Ask';
  panel.setAttribute('aria-label', name);
  panel.querySelector('#ask-title').textContent = name;
  if (!open) return;
  const page = askPage(), sees = panel.querySelector('[data-ask-sees]');
  sees.hidden = !page.title;
  sees.querySelector('[data-ask-sees-name]').textContent = page.title;
  sees.title = 'Sees ' + page.title;
  askMembers();
}
function askToggle(open = !ASK?.open, focus = true) {
  ASK ||= {open: false, mounted: false};
  ASK.open = open;
  askMenu(false);
  askSync();
  if (open && !ASK.mounted) { ASK.mounted = true; void askLoad(ASK); }
  // A phone keeps its keyboard down until the person taps the box.
  if (open && focus && !askPhone()) setTimeout(() => $('#ask-panel .ask-form .p-text')?.focus(), 0);
  else if (!open && focus && $('#ask-panel')?.contains(document.activeElement)) (askPhone() ? $('#mobile-ask') : $('#ask-fab'))?.focus();
}
function askMenu(open) {
  const menu = $('#ask-panel [data-ask-menu]'), add = $('#ask-add');
  if (!menu || !add) return;
  menu.hidden = !open;
  add.setAttribute('aria-expanded', String(open));
  if (open) menu.querySelector('button')?.focus();
}
// Tico support while a request is open and not taken out of the panel.
function askMembers() {
  const strip = $('#ask-panel [data-ask-members]');
  if (!strip) return;
  const hidden = askHiddenTickets(), open = (window.supportState?.().open || []).filter(t => !hidden.includes(t.id));
  strip.hidden = !open.length;
  if (!open.length) return;
  const ticket = open[0], unread = open.filter(t => t.unread).length;
  strip.dataset.ticket = ticket.id;
  strip.querySelector('[data-ask-ticket]').textContent = 'Tico support' + (unread ? ` · ${unread} new` : '');
}
function askDrop(id) {
  const ids = [...new Set([...askHiddenTickets(), id])].slice(-50);
  try { localStorage.setItem(askHiddenKey(), JSON.stringify(ids)); } catch {}
  askMembers();
}
// Support opening from the panel: on a computer the + keeps focus, so closing Support lands back there; a phone has
// room for one sheet, so Ask's gives way to Support's and focus waits on the Ask tab.
function askHandOff() {
  askMenu(false);
  if (askPhone()) { askToggle(false, false); $('#mobile-ask')?.focus(); }
  else $('#ask-add').focus();
}
function askClick(ev) {
  const t = ev.target;
  if (t.closest('[data-ask-close]')) { askToggle(false); return; }
  if (t.closest('#ask-add')) { askMenu($('#ask-panel [data-ask-menu]').hidden); return; }
  if (t.closest('#ask-support')) { askHandOff(); window.supportOpen?.(); return; }
  if (t.closest('#ask-manage')) { askHandOff(); window.supportStart?.(ASK_MANAGE); return; }
  if (t.closest('[data-ask-ticket]')) { window.supportOpen?.({ticket: $('#ask-panel [data-ask-members]').dataset.ticket}); return; }
  if (t.closest('[data-ask-drop]')) { askDrop($('#ask-panel [data-ask-members]').dataset.ticket); return; }
  const hint = t.closest('[data-ask-hint]');
  if (hint) { ev.preventDefault(); void ASK?.send?.(hint.dataset.askHint); return; }
  // A link followed from the panel: on a phone the sheet gets out of the way of the page it opens.
  const a = t.closest('a[href^="#/"]');
  if (a && askPhone() && !a.getAttribute('href').startsWith('#/support')) askToggle(false, false);
}
async function askLoad(chat) {
  const el = $('#ask-panel'), thread = el.querySelector('[data-ask-thread]'), error = el.querySelector('[data-ask-error]');
  const current = () => ASK === chat && chat.mounted;
  const fail = text => { if (!current()) return; error.textContent = text || ''; error.hidden = !text; };
  let info = null, messages = [], execution = null, rendered = '', es = null, poll = null;
  const stopStream = () => { try { es?.(); } catch { /* released */ } es = null; clearInterval(poll); poll = null; };
  chat.stop = stopStream;
  const isReply = m => m.from_actor === 'bot:' + info?.bot;
  const draw = () => {
    if (!current()) return;
    const rows = messages.slice(-30).map(m => v2MessageHTML({...m, run: null}));
    const live = execution && execution.state !== 'completed' ? execution.text : '';
    if (live) rows.push(`<div data-ask-live>${v2MessageHTML({from_actor: 'bot:' + info.bot, body: live})}</div>`);
    else if (messages.length && !isReply(messages.at(-1))) rows.push(`<p class="muted" role="status">${esc(execution?.label || 'Thinking…')}</p>`);
    const html = rows.join('') || `<div class="ask-empty">${ASSISTANT_HINTS.map(h =>
      `<button class="ghost" type="button" data-ask-hint="${esc(h)}">${esc(h)}</button>`).join('')}</div>`;
    if (html === rendered) return;
    stickScroll(thread).update(() => {
      thread.innerHTML = html;
      if (thread.querySelector('[data-action-host]')) void window.assistantChat?.cards(thread, {get, post, esc, toast, reload: snapshot});
    }, {fresh: !!rendered});
    rendered = html;
  };
  const snapshot = async () => {
    if (!info?.room_id || !current()) return;
    try {
      const d = await get(`/v2/conversations/${encodeURIComponent(info.room_id)}/snapshot`);
      if (!current()) return;
      messages = d.messages || []; execution = d.execution || null; draw(); fail('');
    } catch (e) { fail(e.message); }
  };
  const watch = () => {
    stopStream();
    if (!info?.room_id || !current()) return;
    const fallback = liveFallback(snapshot, 5000);
    if (fallback) { poll = fallback; return; }
    const cid = info.room_id, mine = d => d.conversation_id === cid && current();
    const soon = () => liveSoon('ask:' + cid, () => void snapshot(), 150);
    const offs = [liveFollow(cid), liveOn('messages', d => { if (mine(d)) soon(); }),
                  liveOn('runs', d => { if (mine(d)) soon(); }), liveOn('reset', () => { if (current()) soon(); })];
    es = () => offs.forEach(off => off());
  };
  const send = async text => {
    text = String(text || '').trim();
    const P = chat.composer;
    if (!text || !P || P.sending) return;
    P.sending = true; pillButtons(P); fail('');
    try {
      const r = await post('/v2/assistant/messages', {text, page: askPage()});
      CHAT_CACHE.delete(info.bot);                    // the Assistant page reads the conversation again when it opens
      if (!current()) return;
      for (const m of [r.message, r.reply].filter(Boolean)) if (!messages.some(x => x.id === m.id)) messages.push(m);
      if (r.message?.conversation_id && r.message.conversation_id !== info.room_id) { info.room_id = r.message.conversation_id; watch(); }
      pillAcknowledge(P, text, []); stickScroll(thread).toBottom(); draw();
      if (!es && !poll) watch();
      await snapshot();
    } catch (e) { fail(e.message); }
    finally { P.sending = false; if (current()) pillButtons(P); }
  };
  chat.send = send;
  try { info = await get('/v2/assistant'); }
  catch (e) { chat.mounted = false; if (ASK === chat) thread.innerHTML = `<div class="err">${esc(e.message)}</div>`; return; }
  if (!current()) return;
  info.name ||= myChatName();
  thread.setAttribute('aria-label', info.name + ' conversation');
  if (!info.available) {
    // Support stays a tap away in the + even then.
    if (!info.can_turn_on && !info.ceo) { thread.innerHTML = `<p class="muted">${esc(info.name)} is off. Ask the team owner to turn it on.</p>`; return; }
    window.assistantChat?.off(thread, info, {post, esc, after: () => { if (current()) void askLoad(chat); }});
    return;
  }
  messages = info.messages || []; execution = info.execution || null;
  chat.composer = makePill({mode: 'chat', files: false, label: 'Message ' + info.name, placeholder: 'Ask anything…',
                            send: (P, text) => send(text)});
  pq(chat.composer, '.p-text').maxLength = 4000;
  el.querySelector('.ask-form').replaceChildren(chat.composer.el);
  draw();
  watch();
  if (chat.open && !askPhone()) pq(chat.composer, '.p-text').focus();
}
$('#ask-fab')?.addEventListener('click', () => askToggle());
$('#mobile-ask')?.addEventListener('click', () => askToggle());
$('#ask-panel')?.addEventListener('click', askClick);
document.addEventListener('keydown', ev => {
  if ((ev.metaKey || ev.ctrlKey) && ev.key.toLowerCase() === 'j' && !askAway()) { ev.preventDefault(); askToggle(); return; }
  if (ev.key !== 'Escape' || !ASK?.open || document.querySelector('dialog[open]')) return;
  if (!$('#ask-panel [data-ask-menu]').hidden) { askMenu(false); $('#ask-add').focus(); return; }
  if ($('#ask-panel').contains(document.activeElement)) askToggle(false);
});
// "Ask to add or edit your bots" (getting started) and any other [data-ask-open] opens the panel.
document.addEventListener('click', ev => {
  if (!ev.target.closest?.('[data-ask-open]') || askAway()) return;
  ev.preventDefault(); askToggle(true);
});
// Any link to Support (a reply's "Loop in Tico support", "Talk to the Tico team") opens it over the page.
document.addEventListener('click', ev => {
  const a = ev.target.closest?.('a[href^="#/support"]');
  if (!a) return;
  ev.preventDefault();
  if (a.getAttribute('href').includes('manage')) window.supportStart?.(ASK_MANAGE); else window.supportOpen?.();
}, true);
document.addEventListener('tico:support', () => askMembers());
addEventListener('hashchange', () => setTimeout(askSync, 0));
addEventListener('resize', () => askSync());
