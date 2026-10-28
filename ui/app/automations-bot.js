/* ui/app/automations-bot.js — The Automations Bot beside the flow (its own screen on a phone): the viewer's chat with
   it, and its proposals as cards
   Classic script: its globals are shared with the other files under ui/app/, loaded in the order index.html lists them.
   The chat is the bot's ordinary room (POST /v2/chat/automations-bot, the conversation's snapshot and live events, as
   the CEO Bot's chat on Goals). A message names the open automation in refs.automation. A proposal is a pending
   version (GET .../versions?status=pending); Turn on restores it (POST .../versions/{n}/restore), Discard deletes it. */
'use strict';

function auBotMount(host) {
  host.innerHTML = `<div class="au-bh"><a class="au-icon au-back" href="${AUTOMATIONS}" data-bot-back aria-label="Back"><span class="nav-icon" aria-hidden="true">chevron_left</span></a>
      <span class="au-bav nav-icon" aria-hidden="true">assistant</span><h2>Automations Bot</h2></div>
    <div class="au-bm" role="log" aria-label="Automations Bot conversation" tabindex="0"><div class="au-msgs"></div><div class="au-props"></div></div>
    <p class="err au-berr" role="alert" hidden></p><div class="au-bf"></div>`;
  const B = AU.bot = {conv: null, messages: [], execution: null, props: [], propsKey: '', sending: false, stopped: false,
                      es: null, poll: 0, lastReply: undefined, rendered: ''};
  const state = AU;
  const live = () => !B.stopped && AU === state && host.isConnected;
  const thread = host.querySelector('.au-bm'), msgs = host.querySelector('.au-msgs'), props = host.querySelector('.au-props');
  const errEl = host.querySelector('.au-berr');
  const fail = text => { if (!live()) return; errEl.textContent = text || ''; errEl.hidden = !text; };
  const isReply = m => m.from_actor === 'bot:' + AU_BOT;
  const stopStream = () => { try { B.es?.(); } catch { /* released */ } B.es = null; clearInterval(B.poll); B.poll = 0; };
  let composer = null;
  state.botStop = () => { B.stopped = true; stopStream(); if (composer) PILLS.delete(composer); };

  const draw = () => {
    if (!live()) return;
    const rows = B.messages.map(m => v2MessageHTML({...m, run: null}));
    const running = B.execution && B.execution.state !== 'completed' ? B.execution.text : '';
    if (running) rows.push(v2MessageHTML({from_actor: 'bot:' + AU_BOT, body: running}));
    else if (B.messages.length && !isReply(B.messages.at(-1))) rows.push(`<p class="muted" role="status">${esc(B.execution?.label || 'Waiting for reply…')}</p>`);
    const html = rows.join('');
    if (html === B.rendered) return;
    stickScroll(thread).update(() => { msgs.innerHTML = html; }, {fresh: !!B.rendered});
    B.rendered = html;
  };
  const apply = async data => {
    if (!live()) return;
    B.messages = data.messages || [];
    B.execution = data.execution || null;
    draw();
    const reply = B.messages.filter(isReply).at(-1)?.id;
    // A new reply may come with a proposal (or, from New, a new automation): read them again.
    if (B.lastReply !== undefined && reply !== B.lastReply) {
      B.propsKey = '';
      void auBotProposals();
      if (!AU.cur) { await auLoadList(state); if (live()) auDrawList(); }
    }
    B.lastReply = reply ?? null;
  };
  const snapshot = B.snapshot = async () => {
    if (!B.conv || !live()) return;
    try { await apply(await get(`/v2/conversations/${encodeURIComponent(B.conv.id)}/snapshot`)); fail(''); }
    catch (e) { fail(e.message); }
  };
  const watch = () => {
    stopStream();
    if (!B.conv || !live()) return;
    const fallback = liveFallback(snapshot, 5000);
    if (fallback) { B.poll = fallback; return; }
    const cid = B.conv.id, mine = d => d.conversation_id === cid && live();
    const soon = () => liveSoon('au:' + cid, () => void snapshot(), 150);
    const offs = [liveFollow(cid), liveOn('messages', d => { if (mine(d)) soon(); }),
                  liveOn('runs', d => { if (mine(d)) soon(); }), liveOn('reset', () => { if (live()) soon(); })];
    B.es = () => offs.forEach(off => off());
  };
  const send = async (P, text) => {
    if (!text || B.sending) return;
    B.sending = P.sending = true; pillButtons(P); fail('');
    const scope = sessionScope(pq(P, '.p-text'));
    try {
      const out = await cloudCompose('/v2/chat/' + AU_BOT, {text, refs: AU.cur ? {automation: AU.cur.id} : {}});
      pillAcknowledge(P, text, [], scope);
      if (!live()) return;
      const fresh = out.conversation && out.conversation.id !== B.conv?.id;
      B.conv = out.conversation || B.conv;
      if (out.message && !B.messages.some(m => m.id === out.message.id)) B.messages.push(out.message);
      if (B.lastReply === undefined) B.lastReply = B.messages.filter(isReply).at(-1)?.id ?? null;
      stickScroll(thread).toBottom(); draw();
      if (fresh || !B.es) watch();
      await snapshot();
    } catch (e) { fail(e.message); }
    finally { B.sending = P.sending = false; if (live()) pillButtons(P); }
  };
  composer = makePill({mode: 'chat', files: false, label: 'Message to the Automations Bot', placeholder: 'Ask Automations Bot', send});
  pq(composer, '.p-text').maxLength = 4000;
  host.querySelector('.au-bf').append(composer.el);
  props.addEventListener('click', e => { const b = e.target.closest('[data-prop]'); if (b) void auPropAct(b); });
  void (async () => {
    try {
      const list = await get('/v2/conversations?chat_with=' + AU_BOT);
      if (!live() || B.conv) return;
      B.conv = (list.conversations || []).find(c => String(c.kind || 'chat') === 'chat' && !c.task_id && !c.closed_at) || null;
      if (B.conv) { await snapshot(); watch(); } else draw();
    } catch (e) { fail(e.message); }
  })();
}

// After each route: the phone's Back, and the open automation's proposals.
function auBotSync() {
  if (!AU?.bot) return;
  const back = AU.root.querySelector('[data-bot-back]');
  if (back) back.href = AU.id ? auHref(AU.id) : AUTOMATIONS;
  void auBotProposals();
}
async function auBotProposals() {
  const B = AU?.bot, a = AU?.cur, state = AU;
  if (!B) return;
  const key = a ? a.id + '@' + a.version : '';
  if (B.propsKey === key) return;
  B.propsKey = key;
  if (!a) { B.props = []; auPropsDraw(); return; }
  let rows = [];
  try { rows = (await get(auApi(a.id) + '/versions?status=pending')).versions || []; } catch { /* no cards */ }
  if (AU !== state || B.propsKey !== key) return;
  // Settled cards stay (On, Discarded) until the automation changes; fresh pending ones join them.
  const kept = B.props.filter(p => p.state && p.automation === a.id);
  B.props = [...kept, ...rows.filter(v => !kept.some(k => k.n === v.n)).map(v => ({...v, automation: a.id, diff: false}))];
  auPropsDraw();
}

// A flow as lines, for the diff: the trigger, then each step, paths indented under their fork.
function auFlowLines(flow) {
  const out = [];
  const t = flow?.trigger || {};
  out.push(`trigger ${AU_TRIGGER_WORDS[t.type] || t.type || ''} · ${auSource(t)}`.trim());
  for (const c of t.filters || []) out.push('  filter ' + auCondText(c));
  const walk = (steps, pad) => (steps || []).forEach(s => {
    const off = s.enabled === false ? ' (off)' : '';
    if (s.type === 'filter') (s.rules || []).forEach(r => out.push(`${pad}filter ${auCondsText(r.when, r.match)} → ${(r.then || []).map(x => AU_ACTIONS[x] || x).join(', ')}${off}`));
    else if (s.type === 'decide') {
      out.push(`${pad}decide ${s.set ? auSetWords(s.set) : 'custom'} · ${s.level || 'medium'}${off}`);
      if (!s.set) Object.entries(s.questions || {}).forEach(([q, d]) => out.push(`${pad}  question ${q} · ${(AU_QTYPES.find(([k]) => k === d.type) || [, d.type])[1]}`));
    } else if (s.type === 'llm') out.push(`${pad}llm as ${auActorName(s.as)}: ${s.prompt || ''}${off}`);
    else if (s.type === 'bot_turn') out.push(`${pad}bot turn ${auActorName(s.bot)}: ${s.prompt || ''}${off}`);
    else if (s.type === 'find') out.push(`${pad}find ${AU_FIND[s.source] || s.source} ${s.query || ''}${off}`.trim());
    else if (s.type === 'action') out.push(`${pad}${AU_ACTIONS[s.do] || s.do}${auActionArgs(s) ? ' ' + auActionArgs(s) : ''}${off}`);
    else if (s.type === 'paths') {
      (s.paths || []).forEach(p => { out.push(`${pad}path ${p.name} · ${auCondsText(p.when, p.match) || 'no condition'}`); walk(p.steps, pad + '  '); });
      out.push(`${pad}path Otherwise`); walk(s.otherwise?.steps, pad + '  ');
    }
  });
  walk(flow?.steps, '');
  return out;
}
// The changed lines between two flows (a longest-common-subsequence diff): "+ added", "- removed".
function auDiff(before, after) {
  const a = auFlowLines(before), b = auFlowLines(after), n = a.length, m = b.length;
  const L = Array.from({length: n + 1}, () => new Array(m + 1).fill(0));
  for (let i = n - 1; i >= 0; i--) for (let j = m - 1; j >= 0; j--) L[i][j] = a[i] === b[j] ? L[i + 1][j + 1] + 1 : Math.max(L[i + 1][j], L[i][j + 1]);
  const out = [];
  let i = 0, j = 0;
  while (i < n || j < m) {
    if (i < n && j < m && a[i] === b[j]) { i++; j++; }
    else if (j < m && (i >= n || L[i][j + 1] >= L[i + 1][j])) out.push('+ ' + b[j++].trim());
    else out.push('- ' + a[i++].trim());
  }
  return out;
}
function auPropsDraw() {
  const box = AU?.root?.querySelector('.au-props'), a = AU?.cur;
  if (!box) return;
  box.innerHTML = (AU.bot?.props || []).map(p => {
    const lines = a ? auDiff(a, p.flow || {}) : [];
    const summary = p.summary || lines.slice(0, 2).join(' · ') || 'No changes';
    const pill = p.state === 'on' ? '<span class="pill ok">On</span>' : p.state === 'discarded' ? '<span class="pill">Discarded</span>' : '';
    return `<div class="au-prop" data-n="${esc(p.n)}">
      <div class="au-prop-t"><strong>${esc(a?.name || '')} · v${esc(p.n)}</strong>${pill}</div>
      <div class="au-prop-x">${esc(summary)}</div>
      ${p.diff ? `<pre class="au-diff">${p.state === 'on' ? '' : lines.map(l => `<span class="${l[0] === '+' ? 'add' : 'del'}">${esc(l)}</span>`).join('\n') || 'No changes'}</pre>` : ''}
      ${p.state ? '' : `<div class="au-prop-b"><button class="ghost" type="button" data-prop="diff" aria-expanded="${!!p.diff}">View diff</button>
        ${a?.can_edit ? `<button class="primary" type="button" data-prop="on">Turn on</button><button class="linkish" type="button" data-prop="discard">Discard</button>` : ''}</div>`}
    </div>`;
  }).join('');
}
async function auPropAct(button) {
  const n = +button.closest('[data-n]').dataset.n, act = button.dataset.prop, a = AU.cur, state = AU;
  const p = AU.bot.props.find(x => x.n === n);
  if (!p || !a) return;
  if (act === 'diff') { p.diff = !p.diff; auPropsDraw(); return; }
  button.disabled = true;
  try {
    if (act === 'on') {
      const out = auNormal(await post(`${auApi(a.id)}/versions/${n}/restore`, {}));
      if (AU !== state) return;
      p.state = 'on'; p.diff = false;
      AU.bot.propsKey = out.id + '@' + out.version;   // the new current version: no need to read the proposals again
      auAdopt(out);
      toast(`${out.name} v${out.version} is on`);
    } else if (act === 'discard') {
      await writeRequest('DELETE', `${auApi(a.id)}/versions/${n}`);
      if (AU !== state) return;
      p.state = 'discarded'; p.diff = false;
    }
    auPropsDraw();
  } catch (e) { toast(e.message, true); if (button.isConnected) button.disabled = false; }
}
