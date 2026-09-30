/* ui/app/notices.js — New-version pill, usage notice, onboarding nav, native hooks
   Classic script: its globals are shared with the other files under ui/app/, loaded in the order index.html lists them. */
'use strict';

// A tab left open through an update keeps running the old UI. The config poll already runs, so the
// version this page loaded with is compared to the server's on every answer. A banner offers the
// reload; it never reloads by itself, since the person may be typing.
let LOADED_VERSION = '';
function noticeUpdatedServer() {
  const v = String(S.config.version || '');
  if (!v) return;
  if (!LOADED_VERSION) LOADED_VERSION = v;
  const bar = $('#stale-banner');
  if (!bar) return;
  bar.hidden = v === LOADED_VERSION;
  if (!bar.hidden) bar.firstElementChild.textContent = `${appName()} was updated to ${nvVersion(v)}. Reload to get the new version.`;
}
document.addEventListener('click', ev => { if (ev.target.closest('#stale-reload')) location.reload(); });
// The anonymous usage count (PRIVACY.md): the owner sees this once, and nothing is counted before they have.
let usageNoticeShown = false;
function renderUsageNotice() {
  const bar = $('#usage-notice');
  if (!bar) return;
  bar.hidden = !S.config.usage_count_notice;
  if (!bar.hidden && !usageNoticeShown) { usageNoticeShown = true; post('/v2/system/usage-count/notice', {state: 'shown'}).catch(() => {}); }
}
document.addEventListener('click', ev => {
  if (!ev.target.closest('#usage-notice-x')) return;
  S.config.usage_count_notice = false; renderUsageNotice();
  post('/v2/system/usage-count/notice', {state: 'dismissed'}).catch(() => {});
});
// "Finish setup" tops the nav while the owner has an unfinished first run, and disappears the
// moment the server stops asking for one. Everyone else never sees it.
function renderOnboardingNav() {
  const link = $('#nav-welcome');
  if (link) link.hidden = !S.config.onboarding_needed;
}
// "New version" in the sidebar: quiet, only when the server says a newer release exists. Anyone
// may read the changelog; only the owner may start an update. Dismissal is per person and version.
const NV_KEY = 'tico.new-version.dismissed';
const nvDismissedKey = () => NV_KEY + ':' + (S.me?.id || S.me?.email || '');
const nvDismissed = v => { try { return localStorage.getItem(nvDismissedKey()) === v; } catch { return false; } };
let nvBusy = false;
function nvVersion(v) { return /^\d/.test(v) ? 'v' + v : v; }
function renderNewVersion() {
  const wrap = $('#new-version-wrap');
  if (!wrap) return;
  const u = S.config.update;
  const show = !!(u && u.available && u.latest && !nvDismissed(u.latest)) || nvBusy;
  wrap.hidden = !show;
  if (!show) { setNewVersionPop(false); return; }
  $('#new-version-label').textContent = 'New version ' + nvVersion(u.latest);
  if (!nvBusy) nvRenderPop();
}
function setNewVersionPop(open) {
  const pop = $('#new-version-pop'), btn = $('#new-version');
  if (!pop) return;
  pop.hidden = !open;
  btn.setAttribute('aria-expanded', String(open));
}
function nvRenderPop() {
  const u = S.config.update, pop = $('#new-version-pop');
  const owner = S.me?.role === 'owner';
  const safeUrl = /^https:\/\//.test(u.url || '') ? u.url : '';
  pop.innerHTML = `<p><strong>Update available.</strong> ${esc(appName())} ${esc(nvVersion(u.latest))} is out. You are on ${esc(nvVersion(u.current))}.</p>
    <div class="nv-actions">${safeUrl ? `<a class="ghost btnlike" id="nv-changelog" href="${esc(safeUrl)}" target="_blank" rel="noopener noreferrer">View changelog</a>` : ''}${owner ? '<button class="primary" id="nv-update" type="button">Update now</button>' : ''}</div>
    <div id="nv-out"></div>
    <button class="nv-dismiss" id="nv-dismiss" type="button">Dismiss for this version</button>`;
}
function nvOut(html) { const el = $('#nv-out'); if (el) el.innerHTML = html; }
async function nvStart() {
  const u = S.config.update, from = u.current;
  nvBusy = true;
  nvOut('<p class="nv-status" role="status">Updating…</p>');
  try {
    await post('/v2/system/update', {version: u.latest});
  } catch (e) {
    nvBusy = false;
    const command = e.body?.error?.command;
    if (e.status === 409 && command) {
      nvOut(`<p class="nv-status">Update from the server:</p><div class="nv-cmd"><code>${esc(command)}</code><button class="ghost" id="nv-copy" type="button" data-command="${esc(command)}">Copy</button></div>`);
    } else nvOut(`<p class="nv-status err">${esc(e.message)}</p>`);
    return;
  }
  // The server restarts under us; a failed poll is part of the update, not an error.
  const deadline = Date.now() + 10 * 60000;
  while (Date.now() < deadline) {
    await new Promise(r => setTimeout(r, 2000));
    let st = null;
    try { st = await get('/v2/system/update'); } catch { nvOut('<p class="nv-status" role="status">Updating…</p>'); continue; }
    if (st.state === 'healthy') {
      let cfg = null; try { cfg = await get('/v2/config'); } catch {}
      if (cfg && cfg.version && cfg.version !== from) { nvOut('<p class="nv-status" role="status">Updated, reloading</p>'); setTimeout(() => location.reload(), 600); return; }
      continue;
    }
    if (st.state === 'rolled_back') { nvBusy = false; nvOut(`<p class="nv-status err">Rolled back — still on ${esc(nvVersion(st.from || from))}</p>`); return; }
    if (st.state === 'failed') { nvBusy = false; nvOut(`<p class="nv-status err">Update failed${st.message ? ': ' + esc(st.message) : ''}</p>`); return; }
    nvOut('<p class="nv-status" role="status">Updating…</p>');
  }
  nvBusy = false;
  nvOut('<p class="nv-status err">The update is taking longer than expected. Check the server.</p>');
}
document.addEventListener('click', ev => {
  const t = ev.target;
  if (t.closest('#new-version')) { setNewVersionPop($('#new-version-pop').hidden); return; }
  if (t.closest('#nv-update')) { if (!nvBusy) void nvStart(); return; }
  const copy = t.closest('#nv-copy');
  if (copy) { navigator.clipboard?.writeText(copy.dataset.command).then(() => { copy.textContent = 'Copied'; }, () => {}); return; }
  if (t.closest('#nv-dismiss')) {
    try { localStorage.setItem(nvDismissedKey(), S.config.update.latest); } catch {}
    renderNewVersion();
    return;
  }
  if (!t.closest('#new-version-wrap')) setNewVersionPop(false);
});
setInterval(() => { if (!document.hidden && !nvBusy && S.me) get('/v2/config').then(c => applyConfig(c)).catch(() => {}); }, 30000);  // with the app's poll: a release the server just learned of shows within a poll, not an hour
// The main assistant is shown under the environment's assistant name, never its slug.
// The built-in assistant reads as what it is. An assistant named after the company (the old default) is just "Assistant".
const assistantShownName = () => {
  const name = String(assistantName() || '').trim(), company = String(S.config.company_name || '').trim().toLowerCase();
  return !name || name.toLowerCase() === company ? 'Assistant' : name;
};
const namedRoster = rows => rows.map(e => e.name === assistantBot() ? {...e, display_name: assistantShownName()} : e);
// Small compatibility hook for separately loaded UI modules. It exposes only deployment mode,
// never identity or credentials.
window.ticoIsCloud = () => !!S.me?.cloud;
// Modules loaded on their own still need the environment's names for anything a person reads.
window.ticoAppName = () => appName();
window.ticoAssistantName = () => assistantName();
