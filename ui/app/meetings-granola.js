/* ui/app/meetings-granola.js — The viewer's own Granola account on the Meetings page (docs/meetings.md, Granola)
   Classic script: its globals are shared with the other files under ui/app/, loaded in the order index.html lists them. */
'use strict';

// One compact row above the source strip. Connecting is a device-code sign-in: the server hands out a short code,
// the person enters it in Granola, and this page polls GET .../connect/status every `interval` seconds until it
// connects, expires or is denied. When the page opens and the account is connected it asks for one sync (fire and
// forget) and refreshes the list once the sync lands. The API-key importer (Business/Enterprise) stays one link away.
// state.granola is the last GET /v2/meetings/granola; null when the server has no such route, and then the
// Granola tile keeps opening the API-key importer as before.
const GRANOLA = '/v2/meetings/granola';
const GRANOLA_SYNC_POLL_MS = 2000, GRANOLA_SYNC_POLLS = 5;
const GRANOLA_DOTS = '<svg viewBox="0 0 24 24" width="16" height="16" fill="currentColor" aria-hidden="true" focusable="false"><circle cx="5" cy="12" r="1.8"/><circle cx="12" cy="12" r="1.8"/><circle cx="19" cy="12" r="1.8"/></svg>';

function granolaStop(state) {
  if (!state) return;
  clearTimeout(state.gTimer); clearTimeout(state.gSyncTimer);
  state.gTimer = state.gSyncTimer = 0;
}
// A sentence for screen readers; the row itself re-renders, so announcements go through one steady live region.
function granolaSay(text) {
  const live = $('#mg-live'); if (!live) return;
  live.textContent = '';
  setTimeout(() => { live.textContent = text; }, 30);
}
async function granolaStatus(state) {
  let s;
  try { s = await get(GRANOLA); } catch { s = null; }
  if (MEET !== state) return null;
  state.granola = s && typeof s.mode === 'string' ? s : null;
  granolaPaint(state);
  meetPaintTiles(state);
  return state.granola;
}
async function granolaInit(state) {
  const s = await granolaStatus(state);
  if (s?.connected && !s.needs_signin) granolaSync(state);
}
const granolaReady = s => !!(s?.connected && !s.needs_signin);

// Ask for a sync, then re-read the status a few times; once last_sync moves, reload the meeting list.
async function granolaSync(state) {
  if (state.gSyncing) return;
  const before = state.granola?.last_sync || '';
  state.gSyncing = true; state.gmsg = '';
  granolaPaint(state);
  let r;
  try { r = await post(GRANOLA + '/sync', {}); }
  catch (e) { r = null; if (MEET === state) state.gmsg = e.message; }
  if (MEET !== state) return;
  const done = changed => {
    state.gSyncing = false;
    granolaPaint(state); meetPaintTiles(state);
    if (changed && !state.editing && !state.open) meetLoad(state, false);
  };
  if (!r) return done(false);
  let tries = 0;
  const check = async () => {
    state.gSyncTimer = 0;
    const now = await granolaStatus(state);
    if (MEET !== state) return;
    const changed = !!now?.last_sync && now.last_sync !== before;
    if (changed || !granolaReady(now) || ++tries >= GRANOLA_SYNC_POLLS) return done(changed);
    state.gSyncTimer = setTimeout(check, GRANOLA_SYNC_POLL_MS);
  };
  if (r.last_sync && r.last_sync !== before && r.state !== 'running' && r.state !== 'started' && r.state !== 'queued') {
    await granolaStatus(state);
    if (MEET === state) done(true);
    return;
  }
  state.gSyncTimer = setTimeout(check, GRANOLA_SYNC_POLL_MS);
}

async function granolaConnect(state) {
  granolaStop(state);
  state.gmsg = ''; state.gflow = {phase: 'starting'};
  granolaPaint(state);
  let r;
  try { r = await post(GRANOLA + '/connect', {}); }
  catch (e) { if (MEET !== state) return; state.gflow = null; state.gmsg = e.message; granolaPaint(state, 'connect'); return; }
  if (MEET !== state) return;
  if (!r?.user_code) { state.gflow = null; state.gmsg = 'Granola did not send a code. Try again.'; granolaPaint(state, 'connect'); return; }
  const every = Math.max(0.1, Number(r.interval) || 5) * 1000;
  state.gflow = {phase: 'code', code: String(r.user_code), uri: r.verification_uri_complete || r.verification_uri || 'https://granola.ai',
    until: Date.now() + Math.max(1, Number(r.expires_in) || 600) * 1000, every};
  granolaPaint(state, 'open');
  granolaSay(`Your code is ${r.user_code.split('').join(' ')}. Enter it in Granola.`);
  state.gTimer = setTimeout(() => granolaPoll(state), every);
}
async function granolaPoll(state) {
  const flow = state.gflow;
  if (MEET !== state || flow?.phase !== 'code') return;
  let r;
  try { r = await get(GRANOLA + '/connect/status'); } catch { r = {state: 'pending'}; }
  if (MEET !== state || state.gflow !== flow) return;
  if (r.state === 'connected') {
    state.gflow = null;
    if (state.granola) Object.assign(state.granola, {connected: true, needs_signin: false, email: r.email || state.granola.email, mode: 'account'});
    granolaPaint(state, 'more');
    granolaSay('Granola connected.');
    await granolaStatus(state);
    if (MEET === state && granolaReady(state.granola)) granolaSync(state);
    return;
  }
  if (r.state === 'denied' || r.state === 'expired' || Date.now() > flow.until) {
    state.gflow = null;
    state.gmsg = r.state === 'denied' ? 'Granola access was denied.' : 'The code expired. Try again.';
    granolaPaint(state, 'connect');
    return;
  }
  state.gTimer = setTimeout(() => granolaPoll(state), flow.every);
}
function granolaCancel(state) {
  granolaStop(state);
  state.gflow = null; state.gmsg = '';
  granolaPaint(state, 'connect');
}
async function granolaDisconnect(state) {
  granolaStop(state);
  state.gSyncing = false; state.gmsg = '';
  try { await writeRequest('DELETE', GRANOLA + '/connect'); }
  catch (e) { if (MEET === state) { state.gmsg = e.message; granolaPaint(state, 'more'); } return; }
  if (MEET !== state) return;
  if (state.granola) Object.assign(state.granola, {connected: false, needs_signin: false, email: '', mode: 'off'});
  granolaPaint(state, 'connect');
  granolaSay('Granola disconnected.');
  granolaStatus(state);
}
// The Granola tile in the strip: with account sign-in available it starts (or points at) this row.
function granolaFromTile(state) {
  const s = state.granola;
  $('#meet-granola')?.scrollIntoView({block: 'nearest'});
  if (granolaReady(s) || state.gflow?.phase === 'code') granolaPaint(state, granolaReady(s) ? 'more' : 'open');
  else granolaConnect(state);
}
function granolaTileState(state) {
  const s = state.granola;
  if (!s) return null;
  if (s.connected && s.needs_signin) return {key: 'error', word: 'Sign in', when: ''};
  if (s.connected) return {key: 'on', word: 'Connected', when: s.last_sync || ''};
  return null;
}

function granolaFacts(s, syncing) {
  const n = Number(s.imported_count) || 0;
  return [s.email ? `<span class="mg-email" title="${esc(s.email)}">${esc(s.email)}</span>` : '',
    `<span>${syncing ? 'Syncing…' : s.last_sync ? 'synced ' + esc(ago(s.last_sync)) : 'not synced yet'}</span>`,
    `<span>${n} ${n === 1 ? 'note' : 'notes'}</span>`].filter(Boolean).join('');
}
function granolaPaint(state, focus) {
  const el = $('#meet-granola'); if (!el) return;
  const s = state.granola;
  el.hidden = !s;
  if (!s) { el.innerHTML = ''; return; }
  if (!$('#mg-live')) el.innerHTML = '<p class="sr-only" id="mg-live" aria-live="polite"></p><div class="mg-row" id="mg-row"></div>';
  const row = $('#mg-row');
  const flow = state.gflow, owner = S.me?.role === 'owner';
  const keyLink = owner ? '<button type="button" class="linkish mg-key" data-g="key">Use a Granola API key instead (Business/Enterprise)</button>' : '';
  const menu = items => `<div class="mg-more-wrap"><button type="button" class="mg-more" data-g="more" aria-haspopup="menu" aria-expanded="false" aria-controls="mg-menu" aria-label="Granola options">${GRANOLA_DOTS}</button>
      <div class="mg-menu" id="mg-menu" role="menu" hidden>${items}</div></div>`;
  let line, actions = '', extra = '';
  if (flow?.phase === 'code' || flow?.phase === 'starting') {
    const code = flow.phase === 'code';
    line = `<b>Granola</b><span>${code ? 'Enter this code in Granola' : 'Getting a code…'}</span>`;
    actions = `<button type="button" class="ghost" data-g="cancel">Cancel</button>`;
    if (code) extra = `<div class="mg-code-row">
        <output class="mg-code" id="mg-code" aria-label="Granola code">${esc(flow.code)}</output>
        <button type="button" class="ghost" data-g="copy" aria-label="Copy code">Copy</button>
        <a class="mg-open" href="${esc(flow.uri)}" target="_blank" rel="noopener" data-g="open">Open Granola</a>
        <span class="mg-wait muted" aria-hidden="true"><i class="dot"></i>Waiting</span></div>`;
  } else if (s.connected && s.needs_signin) {
    line = `<b>Granola</b>${s.email ? `<span class="mg-email" title="${esc(s.email)}">${esc(s.email)}</span>` : ''}<span class="mg-bad">Signed out</span>`;
    actions = `<button type="button" class="primary small" data-g="connect">Sign in to Granola again</button>${menu('<button type="button" role="menuitem" class="danger-text" data-g="disconnect">Disconnect</button>')}`;
  } else if (s.connected) {
    line = `<b>Granola</b>${granolaFacts(s, state.gSyncing)}`;
    actions = menu(`<button type="button" role="menuitem" data-g="sync"${state.gSyncing ? ' disabled' : ''}>Sync</button><button type="button" role="menuitem" class="danger-text" data-g="disconnect">Disconnect</button>`);
    if (s.plan_hint === 'free') extra = '<p class="mg-sub muted">Free plan: notes from the last 30 days</p>';
  } else {
    line = `<b>Granola</b>${s.mode === 'api_key' ? '<span>Using an API key</span>' : ''}`;
    actions = `<button type="button" class="primary small" data-g="connect">Connect Granola</button>`;
    extra = keyLink ? `<p class="mg-sub">${keyLink}</p>` : '';
  }
  const err = state.gmsg || (s.connected && !s.needs_signin && !flow ? s.last_error : '');
  row.dataset.state = flow ? 'code' : s.connected && s.needs_signin ? 'signin' : s.connected ? 'on' : 'off';
  row.innerHTML = `${meetLogo('granola', 26)}<div class="mg-body"><div class="mg-line">${line}</div>${extra}
      ${err ? `<p class="mg-err" role="alert">${esc(err)}</p>` : ''}</div><div class="mg-actions">${actions}</div>`;
  granolaWire(state, row);
  const target = focus === 'connect' ? row.querySelector('[data-g=connect]') : focus === 'open' ? row.querySelector('[data-g=open], [data-g=cancel]')
    : focus === 'more' ? row.querySelector('[data-g=more], [data-g=connect]') : null;
  target?.focus({preventScroll: true});
}
function granolaMenu(row, open) {
  const button = row.querySelector('[data-g=more]'), menu = row.querySelector('.mg-menu');
  if (!button || !menu) return;
  menu.hidden = !open;
  button.setAttribute('aria-expanded', String(open));
  if (open) menu.querySelector('button:not(:disabled)')?.focus();
}
function granolaWire(state, row) {
  row.querySelectorAll('[data-g]').forEach(b => {
    const act = b.dataset.g;
    if (act === 'open') return;
    b.onclick = event => {
      if (act === 'more') { event.stopPropagation(); granolaMenu(row, row.querySelector('.mg-menu').hidden); return; }
      if (act === 'connect') granolaConnect(state);
      else if (act === 'cancel') granolaCancel(state);
      else if (act === 'copy') void copyText(state.gflow?.code || '').then(() => toast('Code copied'), () => toast('Could not copy', true));
      else if (act === 'sync') { granolaMenu(row, false); granolaSync(state); row.querySelector('[data-g=more]')?.focus(); }
      else if (act === 'disconnect') granolaDisconnect(state);
      else if (act === 'key') window.openMeetingImporter?.('granola', 'Granola', () => meetSources(state));
    };
  });
  const menu = row.querySelector('.mg-menu');
  if (menu) menu.onkeydown = event => {
    const items = [...menu.querySelectorAll('button:not(:disabled)')], i = items.indexOf(document.activeElement);
    if (event.key === 'Escape') { event.preventDefault(); granolaMenu(row, false); row.querySelector('[data-g=more]')?.focus(); }
    else if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
      event.preventDefault();
      items[(i + (event.key === 'ArrowDown' ? 1 : -1) + items.length) % items.length]?.focus();
    }
  };
}
document.addEventListener('click', event => {
  const row = $('#mg-row');
  if (row && !event.target.closest?.('.mg-more-wrap')) granolaMenu(row, false);
});
