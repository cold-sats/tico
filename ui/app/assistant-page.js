/* ui/app/assistant-page.js — The Assistant page: your private chat with the assistant
   Classic script: its globals are shared with the other files under ui/app/, loaded in the order index.html lists them. */
'use strict';

// ----------------------------------------------------------------- the Assistant page (docs/assistant.md)
// #/assistant is the same thread and composer as a bot's chat (ui/app/chat.js, ui/app/pill.js) under a one-line
// header. GET /v2/assistant gives your own Assistant room with its messages; a message goes to
// /v2/assistant/messages, which answers a lookup at once and hands the rest to a turn of the assistant bot, shown
// live like any bot's reply. Proposals are Confirm / Cancel cards (ui/assistant.js). The room takes text only, so
// the composer has no attach button.
const ASSISTANT_HINTS = ["What's waiting on me?", 'Find the launch plan', 'How do I add a bot?'];
let ASSISTANT_PILL = null, ASSISTANT_DRAFT = '', ASSISTANT_LOAD = 0;
// "Ask the Assistant…" in search: the words go into the box, now if the page is open, else when it opens.
function assistantPrefill(text) {
  const box = ASSISTANT_PILL?.el?.isConnected ? pq(ASSISTANT_PILL, '.p-text') : null;
  if (!box) { ASSISTANT_DRAFT = text; return; }
  box.value = text;
  box.dispatchEvent(new Event('input'));
  box.focus();
}
function assistantPill() {
  const slug = assistantBot();
  if (ASSISTANT_PILL?.slug === slug) return ASSISTANT_PILL;
  if (ASSISTANT_PILL) PILLS.delete(ASSISTANT_PILL);
  return ASSISTANT_PILL = pillRestore(makePill({mode: 'chat', slug, files: false, send: assistantSend,
    label: 'Message the Assistant', placeholder: 'Ask anything…'}));
}
const assistantEmptyHTML = () => `<div class="asst-empty"><div class="asst-hints" aria-label="Suggestions">${
  ASSISTANT_HINTS.map(t => `<button class="ghost" type="button" data-hint="${esc(t)}">${esc(t)}</button>`).join('')}</div></div>`;
async function pageAssistant() {
  const slug = assistantBot(), load = ++ASSISTANT_LOAD;
  $('#main').classList.add('chat-layout', 'bot-chat-layout');
  $('#main').innerHTML = `
  <div class="bot-top asst-top"><div class="bot-ident">${avatar(slug, 36, stateOf(slug))}
    <div class="botid"><h1>${esc(assistantName())}</h1></div></div></div>
  <div class="bot-work" id="bot-work"><div id="pane-chat">
    <section class="card conv" id="conv">
      <div class="conv-older" id="conv-older"></div>
      <div id="conv-thread" data-assistant><div class="empty">Loading…</div></div>
      <button type="button" class="conv-jump" id="conv-jump" hidden></button>
    </section>
    <div id="conv-paused" class="conv-paused" role="status" hidden></div>
    <div id="chat-composer"></div>
  </div></div>`;
  let d;
  try { d = await get('/v2/assistant'); }
  catch (e) {
    if (load === ASSISTANT_LOAD && $('#conv-thread')) $('#conv-thread').innerHTML = `<div class="err">${esc(e.message)}</div>`;
    return;
  }
  if (load !== ASSISTANT_LOAD || S.route !== ASSISTANT) return;
  if (!d.available) {
    window.assistantChat?.off($('#conv-thread'), d, {post, esc, after: () => { if (S.route === ASSISTANT) pageAssistant(); }});
    return;
  }
  const P = assistantPill(), thread = $('#conv-thread');
  $('#chat-composer').append(P.el);
  if (ASSISTANT_DRAFT) { assistantPrefill(ASSISTANT_DRAFT); ASSISTANT_DRAFT = ''; }
  bindChatSwipe(thread);
  thread.addEventListener('click', ev => { const b = ev.target.closest('[data-hint]'); if (b) assistantSend(P, b.dataset.hint); });
  void v2ChatLoad(slug, {conv: {id: d.room_id}, messages: d.messages, execution: d.execution, nextBefore: d.next_before,
                         empty: assistantEmptyHTML()});
}
async function assistantSend(P, text) {
  text = String(text || '').trim();
  if (!text || P.sending) return;
  P.sending = true;
  const btn = pq(P, '.p-send'), state = V2C;
  btn.disabled = true; pillBtnSay(btn, 'Sending…');
  try {
    const r = await post('/v2/assistant/messages', {text});
    pillAcknowledge(P, text, []);
    if (state && V2C === state) {
      // Your words show at once; a lookup's answer comes with them, a bot turn streams in like any reply.
      for (const m of [r.message, r.reply].filter(Boolean)) { state.messages.push(m); state.mine.push(m); }
      state.followLatest = true;
      if (!r.fast) { state.live = {text: ''}; state.execution = null; state.sentAt = Date.now(); }
      v2ChatRender(state);
      if (!r.fast) v2ChatStream(state);
    }
  } catch (e) { toast(e.message, true); }
  finally { P.sending = false; pillBtnSay(btn, ''); pillLabel(P); pillButtons(P); }
}
