/* ui/app/credentials.js — Credentials page (owner only)
   Classic script: its globals are shared with the other files under ui/app/, loaded in the order index.html lists them. */
'use strict';

// ----------------------------------------------------------------- credentials (owner only)
// Every credential the team has, masked, with whether it works: GET /api/credentials is the
// inventory with the last check; POST /api/credentials/check probes them (read-only calls).
let CRED_ST = null;
const CRED_LABEL = {ok: 'working', failed: 'failed', missing: 'missing', absent: 'not set', present: 'stored', unchecked: 'not checked', session: 'session'};
const CRED_PILL = {ok: 'ok', failed: 'fail', missing: 'fail', absent: '', present: '', unchecked: 'waiting', session: ''};
function pageCredentials() {
  location.hash = INTEGRATIONS;
}
async function credLoad() {
  let d;
  try { d = await get('/credentials'); }
  catch (e) { const el = $('#cred-list'); if (el) el.innerHTML = `<div class="empty">Could not read the credentials${e.message ? ` (${esc(e.message)})` : ''}.</div>`; return; }
  if (S.route !== CREDENTIALS) return;
  CRED_ST.rows = d.credentials || [];
  credPaint(d.summary || {});
  // never checked, or stale by more than six hours: check once, quietly
  const newest = Math.max(0, ...CRED_ST.rows.map(r => r.checked_at ? Date.parse(r.checked_at) : 0));
  if (Date.now() - newest > 6 * 3600e3) credCheck();
}
async function credCheck(ids) {
  if (!CRED_ST || CRED_ST.checking) return;
  CRED_ST.checking = true;
  const btn = $('#cred-check'); if (btn) { btn.disabled = true; btn.textContent = ids ? 'Checking…' : 'Checking all…'; }
  document.querySelectorAll('[data-cred-check]').forEach(b => { if (!ids || ids.includes(b.dataset.credCheck)) { b.disabled = true; b.textContent = '…'; } });
  try {
    const d = await post('/credentials/check', ids ? {ids} : {});
    if (S.route !== CREDENTIALS) return;
    CRED_ST.rows = d.credentials || []; credPaint(d.summary || {});
  } catch (e) { toast(`Check failed: ${e.message}`); }
  finally {
    CRED_ST.checking = false;
    const b2 = $('#cred-check'); if (b2) { b2.disabled = false; b2.textContent = 'Check all now'; }
  }
}
function credPaint(summary) {
  const rows = CRED_ST.rows || [];
  const sum = $('#cred-summary');
  if (sum) sum.innerHTML = [['ok', 'working'], ['failed', 'failed'], ['missing', 'missing'], ['present', 'stored, not checkable'], ['session', 'browser sessions']]
    .filter(([k]) => summary[k]).map(([k, label]) => `<span class="pill ${CRED_PILL[k]}">${summary[k]} ${label}</span>`).join(' ');
  const order = {failed: 0, missing: 1, unchecked: 2, ok: 3, present: 4, absent: 5, session: 6};
  const sorted = [...rows].sort((a, b) => (order[a.status] ?? 9) - (order[b.status] ?? 9) || a.name.localeCompare(b.name));
  const when = iso => iso ? `<span title="${esc(fmt(iso))}">${ago(iso)}</span>` : '<span class="muted">never</span>';
  const line = r => {
    const st = `<span class="pill ${CRED_PILL[r.status] || ''}">${CRED_LABEL[r.status] || r.status}</span>`;
    const as = esc(r.identity || r.declared_as?.[0] || '');
    const bots = (r.bots || []).map(empChip).join(' ') || '<span class="none">—</span>';
    const files = r.files || [];
    const where = (files.length > 2 ? `<span title="${esc(files.join(', '))}">${files.length} files</span>` : files.map(f => `<code>${esc(f)}</code>`).join(' '))
      + (r.masked ? ` <span class="mono muted">${esc(r.masked)}</span>` : '');
    const detail = r.status === 'failed' ? `<div class="err">${esc(r.error)}</div>`
      : r.status === 'missing' ? `<div class="muted">declared by ${r.bots.length} bot${r.bots.length === 1 ? '' : 's'}, no value on this Mac${r.missing_keys?.length ? `: <code>${r.missing_keys.map(esc).join('</code> <code>')}</code>` : ''}</div>` : '';
    const checked = r.checked_at ? `<div class="muted" style="font-size:11.5px;margin-top:3px">checked ${when(r.checked_at)}</div>` : '';
    const used = r.last_used ? `${empChip(r.last_used.employee)} <span class="muted">${when(r.last_used.finished)}</span>` : '<span class="muted">no run yet</span>';
    return `<tr class="cred ${r.status}"><td class="cred-name"><strong>${esc(r.name)}</strong><div class="muted" style="font-size:12px">${esc(r.kind)}</div>${detail}</td>
      <td class="cred-as">${as}${r.verbs?.length ? `<div class="muted" style="font-size:12px">${r.verbs.map(esc).join(', ')}</div>` : ''}</td>
      <td class="cred-bots">${bots}</td>
      <td class="cred-where">${where || '<span class="muted">—</span>'}</td>
      <td class="cred-status">${st}${checked}</td>
      <td class="cred-when tnum">${r.last_ok_at ? when(r.last_ok_at) : '<span class="muted">—</span>'}</td>
      <td class="cred-used tnum">${used}</td>
      <td class="cred-act">${r.can_check ? `<button class="ghost" type="button" data-cred-check="${esc(r.id)}">Check</button>` : ''}</td></tr>`;
  };
  const el = $('#cred-list'); if (!el) return;
  el.innerHTML = rows.length ? `<div class="scroll"><table class="cred-table"><tr><th>Credential</th><th>As</th><th>Used by</th><th>Where</th><th>Status</th><th>Last worked</th><th>Last run</th><th></th></tr>${sorted.map(line).join('')}</table></div>`
    : '<div class="empty">No credentials found on this computer.</div>';
  el.onclick = ev => { const b = ev.target.closest('[data-cred-check]'); if (b) credCheck([b.dataset.credCheck]); };
}
