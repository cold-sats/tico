/* Settings > Health: what needs attention right now (backend/health.py). Everything shown is what
   GET /api/v2/health computed; the only local state is which page is open. The attention dot sits on
   the way into Settings, never in the main navigation. */
let HL = null;
let HL_LOAD = 0;

async function hlRefresh() {
  if (!S.me?.cloud) return null;
  const seq = ++HL_LOAD;
  const data = await v2Get('/v2/health');
  if (seq !== HL_LOAD) return HL;
  HL = data && Array.isArray(data.checks) ? data : null;
  // The sidebar's "New version" reads the same answer, so it never lags the page beside it.
  if (HL?.update && S.config) { S.config = {...S.config, update: HL.update}; window.renderNewVersion?.(); }
  hlNav();
  hlPageDraw();
  return HL;
}

// The dot follows the way in: the account button, the Settings entry and the Health tab.
window.hlNav = function hlNav() {
  const attention = HL?.attention || 0;
  document.querySelectorAll('[data-hl-alert]').forEach(dot => { dot.hidden = !attention; });
  const label = attention ? `Settings, ${attention} to look at in Health` : '';
  const setting = document.querySelector('#account-menu [data-nav="settings"]');
  if (setting) { if (label) setting.setAttribute('aria-label', label); else setting.removeAttribute('aria-label'); }
  const tab = document.querySelector('[data-settings-tab="health"]');
  if (tab) { if (attention) tab.setAttribute('aria-label', `Health, ${attention} to look at`); else tab.removeAttribute('aria-label'); }
};

const HL_ICONS = {ok: 'check_circle', warn: 'warning', bad: 'error', info: 'radio_button_unchecked', unknown: 'help'};
let HL_CHECKING = false;
let HL_CHECK_MSG = null;   // {text, error}: what the last "Check for updates" said, kept across redraws

function hlFixHtml(fix) {
  if (fix.click) return `<button class="ghost" type="button" data-hl-click="${esc(fix.click)}">${esc(fix.label)}</button>`;
  return `<a class="ghost gs-link" href="${esc(fix.href)}"${fix.tab ? ` data-gs-tab="${esc(fix.tab)}"` : ''}>${esc(fix.label)}</a>`;
}

function hlCheckHtml(check) {
  const owner = check.id === 'version' && HL?.audience === 'owner';
  const checkButton = owner
    ? `<button class="ghost" type="button" data-hl-check-updates${HL_CHECKING ? ' disabled' : ''}>${HL_CHECKING ? 'Checking…' : 'Check for updates'}</button>` : '';
  const result = owner && HL_CHECK_MSG
    ? `<p class="hl-check-result${HL_CHECK_MSG.error ? ' err' : ''}" role="status">${esc(HL_CHECK_MSG.text)}</p>` : '';
  return `<li class="hl-check ${esc(check.status)}" data-hl-check="${esc(check.id)}" data-status="${esc(check.status)}">
    <span class="nav-icon hl-icon" aria-hidden="true">${HL_ICONS[check.status] || HL_ICONS.unknown}</span>
    <div class="hl-main"><strong>${esc(check.label)}</strong><p>${esc(check.summary)}</p>${result}</div>
    <div class="hl-fixes">${check.fixes.map(hlFixHtml).join('')}${checkButton}</div></li>`;
}

function hlCredentialFix(source) {
  if (source === 'credentials') return 'Replace the model key in <a href="#/credentials">Credentials</a>';
  if (source === 'computer') return 'Update the computer-local key or sign in again';
  return 'If the key is stored in <a href="#/credentials">Credentials</a>, replace it there; otherwise update the computer-local key or sign in again';
}

function hlComputerHtml(machine) {
  const models = machine.runtimes.map(row => {
    const state = row.rejected ? `sign-in rejected${row.rejected_at ? ' ' + esc(ago(row.rejected_at)) : ''}${row.rejected_reason ? ' (' + esc(row.rejected_reason) + ')' : ''}. ${hlCredentialFix(row.credential_source)}`
      : row.ready ? 'signed in' : row.installed ? 'not signed in' : 'not installed';
    const login = row.signable
      ? ` <button class="ghost" type="button" data-model-login data-runner="${esc(machine.id)}" data-runtime="${esc(row.name)}" data-machine="${esc(machine.label)}">Sign in</button>` : '';
    // Red only when the team or an assigned bot needs it; the server sends only relevant harnesses.
    const bad = row.rejected || (!row.installed && row.needed !== false);
    return `<li data-ready="${row.ready}"${bad ? ' class="hl-model-bad"' : ''}>${esc(harnessWords(row.name))}: ${state}${login}</li>`;
  }).join('');
  return `<li class="hl-computer" data-online="${machine.online}"><span class="hl-dot ${machine.online ? 'on' : 'off'}" aria-hidden="true"></span>
    <div><strong>${esc(machine.label)}</strong> <span class="muted">${machine.online ? 'online' : 'offline'}${machine.last_seen ? ', last seen ' + esc(ago(machine.last_seen)) : ', never seen'}</span>
    ${window.runnerUpdateHtml?.(machine.update, machine.version) || ''}
    <ul class="hl-models">${models || '<li class="muted">No models reported</li>'}</ul></div></li>`;
}

function hlPageDraw() {
  const host = $('#hl-page');
  if (!host) return;
  if (!HL) { host.innerHTML = '<div class="empty">Nothing to show yet.</div>'; return; }
  const bots = list => list.map(row => `<li><a href="#/bot/${esc(row.bot)}">${esc(row.name)}</a> <span class="muted">${row.reason === 'no_computer' ? 'no computer is online' : row.computer ? esc(row.computer) + ' is offline' : 'waiting ' + esc(ago(row.oldest))}${row.queued ? ', ' + row.queued + ' waiting' : ''}</span></li>`).join('');
  // Settings' own checks that need nobody (ui/app/settings.js shows only the ones that do).
  const notes = (typeof SETTINGS_DATA !== 'undefined' && SETTINGS_DATA.issues || []).filter(issue => !needsPerson(issue));
  host.innerHTML = `<p class="muted" id="hl-summary">${HL.attention ? `${HL.attention} issue${HL.attention === 1 ? '' : 's'} to look at`
    : notes.length ? `Nothing urgent. ${notes.length} note${notes.length === 1 ? '' : 's'} below.` : 'Everything looks fine.'}</p>
    <ul class="hl-list">${HL.checks.map(hlCheckHtml).join('')}</ul>
    ${notes.length ? `<h2>Not urgent</h2><ul class="hl-notes">${notes.map(issue => `<li><strong>${esc(issue.title)}</strong> <span class="muted">${esc(issue.detail || '')}</span></li>`).join('')}</ul>` : ''}
    ${HL.computers.length ? `<h2>Computers</h2><ul class="hl-computers">${HL.computers.map(hlComputerHtml).join('')}</ul>` : ''}
    ${HL.waiting.length || HL.slow.length ? `<h2>Bots waiting</h2><ul class="hl-bots">${bots(HL.waiting)}${bots(HL.slow)}</ul>` : ''}
    ${HL.failures.length ? `<h2>Failed in the last day</h2><ul class="hl-bots">${HL.failures.map(row => `<li>${esc(botDisplayName(row.bot))} <span class="muted">${esc(ago(row.at))}</span></li>`).join('')}</ul>` : ''}`;
}

async function hlCheckUpdates() {
  if (HL_CHECKING) return;
  HL_CHECKING = true; HL_CHECK_MSG = null;
  hlPageDraw();
  try {
    // Not post(): that retries a 429 or 502 as a lost write, and here the refusal itself is the answer.
    const reply = await fetch(API + '/v2/system/update/check', {method: 'POST'});
    const notice = await reply.json().catch(() => ({}));
    if (!reply.ok) throw apiFailure(notice, reply);
    await hlRefresh();
    // An available update is already the Version line, refreshed above: say it once, not twice.
    HL_CHECK_MSG = notice?.checking ? {text: 'Still checking. Look again in a moment.'}
      : notice?.available ? null
      : {text: notice?.latest ? `You are on the latest release, ${nvVersion(notice.current)}.`
        : 'Checked. No release information came back.'};
  } catch (error) {
    HL_CHECK_MSG = {text: error.message || 'The check failed.', error: true};
  }
  HL_CHECKING = false;
  hlPageDraw();
}

window.hlMount = function hlMount() {
  const host = $('#hl-page');
  if (!host) return;
  if (HL) hlPageDraw(); else host.innerHTML = '<div class="empty">Loading…</div>';
  hlNav();
  void hlRefresh().then(() => { if (!HL) hlPageDraw(); });
};

window.hlBoot = function () {
  void hlRefresh();
  setInterval(() => { if (!document.hidden && S.me?.cloud) void hlRefresh(); }, 60000);
  document.addEventListener('visibilitychange', () => { if (!document.hidden && S.me?.cloud) void hlRefresh(); });
};

document.addEventListener('click', event => {
  if (event.target.closest('[data-hl-check-updates]')) { void hlCheckUpdates(); return; }
  const open = event.target.closest('[data-hl-click]');
  // After this click finishes: the page's outside-click handler would otherwise close the popup it opens.
  if (open) setTimeout(() => document.querySelector(open.dataset.hlClick)?.click(), 0);
});
