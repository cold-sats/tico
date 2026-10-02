/* ui/app/subscriptions.js — Subscriptions: the named AI logins on each computer (Settings > Computers), the one a
   group picks, a bot's own choice, and the line under a bot's model saying which one it will use.
   The server stores profile names only; the logins stay on the computers (runner/profiles.py).
   Classic script: its globals are shared with the other files under ui/app/, loaded in the order index.html lists them. */
'use strict';

// GET /v2/subscriptions: {profiles_by_computer: [{runner_id, label, profiles: [{name, runtimes: {codex: {signed_in}}}]}],
// assignments: [{scope, target, profile}]}. An older server answers 404 and every part here stays away.
let SUBS = null;
const SUBS_RUNTIMES = [['codex', 'Codex'], ['claude', 'Claude Code']];
async function subsLoad() {
  try { SUBS = subsNormal(await get('/v2/subscriptions')); }
  catch { SUBS = null; }
  return SUBS;
}
function subsNormal(d) {
  const computers = (d?.profiles_by_computer || []).map(c => ({runner_id: c.runner_id, label: c.label || c.runner_id,
    profiles: (c.profiles || []).map(p => {
      if (typeof p === 'string') return {name: p, runtimes: {}};
      let runtimes = p.runtimes || p.runtimes_json || {};
      if (typeof runtimes === 'string') { try { runtimes = JSON.parse(runtimes); } catch { runtimes = {}; } }
      return {name: p.name || p.profile, runtimes: runtimes || {}};
    }).filter(p => p.name)}));
  return {computers, assignments: d?.assignments || []};
}
const subsNames = () => [...new Set((SUBS?.computers || []).flatMap(c => c.profiles.map(p => p.name)))].sort((a, b) => a.localeCompare(b));
// A computer as the server names it: {runner_id, label}, or a bare runner id.
function subsComputerLabel(c) {
  if (c && typeof c === 'object') return c.label || subsComputerLabel(c.runner_id);
  return SUBS?.computers.find(x => x.runner_id === c)?.label || (SETTINGS_DATA?.machines || []).find(m => m.id === c)?.label || c || '';
}
// Subscription names are lowercase words joined by hyphens (runner/profiles.py): "Acme Research" becomes acme-research.
const subsSlug = name => String(name || '').toLowerCase().trim().replace(/[^a-z0-9]+/g, '-').replace(/^-+|-+$/g, '').slice(0, 80);
// Assignments are keyed by group id or bot slug.
const subsAssigned = (scope, target) => (SUBS?.assignments || []).find(x => x.scope === scope && x.target === target)?.profile || '';
const subsGroups = () => S.orgGroups || [];
// The subscription a group gives its bots: its own, else the nearest group above it that has one.
function subsGroupProfile(groupId) {
  const seen = new Set();
  for (let g = subsGroups().find(x => x.id === groupId); g && !seen.has(g.id); g = subsGroups().find(x => x.id === g.parent)) {
    seen.add(g.id);
    const profile = subsAssigned('group', g.id);
    if (profile) return {profile, group: g};
  }
  return {profile: '', group: subsGroups().find(x => x.id === groupId) || null};
}
// True or false as the computer reported it; null when it did not say (an older runner, a computer this person
// cannot see, or a runtime it could not check). Without a runtime: whether any runtime is signed in.
function subsSignedIn(runnerId, profile, runtime = '') {
  const p = SUBS?.computers.find(c => c.runner_id === runnerId)?.profiles.find(x => x.name === profile);
  if (!p) return null;
  if (runtime) { const v = p.runtimes?.[runtime]?.signed_in; return typeof v === 'boolean' ? v : null; }
  const all = Object.values(p.runtimes || {}).map(r => r?.signed_in);
  return all.includes(true) ? true : all.includes(false) ? false : null;
}
// The computers a group's bots sit on where its subscription is known not to be signed in (nested groups count, unless
// they or the bot pick their own). Unknown is not a gap.
function subsGroupGaps(group) {
  const profile = subsAssigned('group', group.id);
  if (!profile) return [];
  const gaps = new Set();
  for (const e of S.emps || []) {
    if (!e.team || subsAssigned('bot', e.name)) continue;
    const from = subsGroupProfile(e.team);
    if (from.group?.id !== group.id || !e.machine?.runner_id) continue;
    if (subsSignedIn(e.machine.runner_id, profile, e.resolved_runtime || '') === false) gaps.add(subsComputerLabel(e.machine.runner_id));
  }
  return [...gaps].sort();
}

// ---- Settings > Computers > Subscriptions
function subsRuntimeHTML(c, p) {
  const owner = S.me?.role === 'owner';
  const reported = Object.keys(p.runtimes || {}).length;
  const shown = reported ? SUBS_RUNTIMES.filter(([id]) => p.runtimes[id]) : SUBS_RUNTIMES;
  // Not known for any runtime: no state to show, but an owner can still sign it in.
  if (shown.every(([id]) => typeof p.runtimes?.[id]?.signed_in !== 'boolean') && reported) {
    return owner ? shown.map(([id, label]) => `<button class="ghost subs-signin" type="button" data-model-login data-runner="${esc(c.runner_id)}" data-runtime="${esc(id)}" data-profile="${esc(p.name)}" data-machine="${esc(c.label)}" aria-label="Sign in ${esc(p.name)} to ${esc(label)} on ${esc(c.label)}">Sign in to ${esc(label)}</button>`).join('') : '';
  }
  return shown.map(([id, label]) => {
    const v = reported ? p.runtimes[id]?.signed_in : false;
    if (typeof v !== 'boolean') return '';                 // not known: nothing to say
    return `<span class="subs-rt"><span class="pill ${v ? 'ok' : 'waiting'}">${esc(label)} · ${v ? 'signed in' : 'not signed in'}</span>${!v && owner
      ? `<button class="ghost subs-signin" type="button" data-model-login data-runner="${esc(c.runner_id)}" data-runtime="${esc(id)}" data-profile="${esc(p.name)}" data-machine="${esc(c.label)}" aria-label="Sign in ${esc(p.name)} to ${esc(label)} on ${esc(c.label)}">Sign in</button>` : ''}</span>`;
  }).join('');
}
function subsGroupRowHTML(g, names) {
  const own = subsAssigned('group', g.id), admin = settingsIsAdmin();
  const list = own && !names.includes(own) ? [...names, own] : names;
  // No choice of its own: it uses the nearest group above it that has one.
  const above = g.parent ? subsGroupProfile(g.parent) : {profile: ''};
  const none = above.profile ? `From ${above.group.name} (${above.profile})` : 'None';
  const gaps = subsGroupGaps(g);
  return `<li class="subs-row"><span class="subs-name">${esc(g.name)}</span>
    <select class="settings-inline-select subs-select" data-subs-group="${esc(g.id)}" aria-label="Subscription for ${esc(g.name)}"${admin ? '' : ' disabled'}>
      <option value="">${esc(none)}</option>${list.map(n => `<option value="${esc(n)}"${n === own ? ' selected' : ''}>${esc(n)}</option>`).join('')}</select>
    ${gaps.map(label => `<span class="pill fail subs-gap">Not signed in on ${esc(label)}</span>`).join('')}</li>`;
}
// A new subscription's name being typed is never wiped by a redraw; `force` redraws anyway (after the person's own
// group change). `loaded`: SUBS was just read, so it is not read again.
const subsTyping = () => formBusy($('#set-subs [data-subs-add]'));
async function renderSettingsSubs(force = false, loaded = false) {
  const card = $('#settings-subs'), el = $('#set-subs');
  if (!card || !el) return;
  if (!force && subsTyping()) return;
  if (!S.me?.cloud || !(loaded ? SUBS : await subsLoad()) || !$('#set-subs')) { card.hidden = true; return; }
  if (!force && subsTyping()) return;
  const names = subsNames(), owner = S.me?.role === 'owner';
  const machines = (SETTINGS_DATA?.machines || []).filter(m => !m.revoked_at);
  const computers = SUBS.computers.filter(c => c.profiles.length);
  const groups = names.length ? subsGroups() : [];
  const add = owner && machines.length ? `<form class="subs-add" data-subs-add novalidate>
      <input name="profile" type="text" autocomplete="off" spellcheck="false" maxlength="80" required placeholder="New subscription" aria-label="New subscription name" aria-describedby="subs-add-msg">
      <select name="runner" aria-label="Computer">${machines.map(m => `<option value="${esc(m.id)}">${esc(m.label)}</option>`).join('')}</select>
      <select name="runtime" aria-label="Sign in to">${SUBS_RUNTIMES.map(([id, label]) => `<option value="${id}">${label}</option>`).join('')}</select>
      <button class="ghost" type="submit">Sign in</button><span class="muted subs-add-msg" id="subs-add-msg" role="status"></span></form>` : '';
  if (!computers.length && !add) { card.hidden = true; return; }
  el.innerHTML = `${computers.map(c => `<div class="subs-pc"><h3 class="subs-h">${esc(c.label)}</h3><ul class="subs-list">${c.profiles.map(p =>
      `<li class="subs-row" data-subs-profile="${esc(p.name)}"><span class="subs-name">${esc(p.name)}</span>${subsRuntimeHTML(c, p)}</li>`).join('')}</ul></div>`).join('')}
    ${groups.length ? `<div class="subs-pc subs-groups"><h3 class="subs-h">Groups</h3><ul class="subs-list">${groups.map(g => subsGroupRowHTML(g, names)).join('')}</ul></div>` : ''}
    ${add}`;
  card.hidden = false;
  el.onchange = async ev => {
    const sel = ev.target.closest('[data-subs-group]'); if (!sel) return;
    sel.disabled = true;
    try {
      await put('/v2/subscriptions', {scope: 'group', target: sel.dataset.subsGroup, profile: sel.value || null});
      toast('Subscription saved');
    } catch (e) { toast(e.message, true); }
    await renderSettingsSubs(true);
  };
  el.oninput = ev => {
    const field = ev.target.closest('[data-subs-add] [name=profile]'); if (!field) return;
    const slug = subsSlug(field.value), msg = $('#subs-add-msg');
    if (msg) msg.textContent = field.value.trim() && slug !== field.value.trim() ? `Saved as ${slug}` : '';
  };
  el.onsubmit = ev => {
    const form = ev.target.closest('[data-subs-add]'); if (!form) return;
    ev.preventDefault();
    const name = subsSlug(form.elements.profile.value);
    if (!name) { $('#subs-add-msg').textContent = 'Use letters or numbers'; form.elements.profile.focus(); return; }
    $('#subs-add-msg').textContent = '';
    window.TicoModelLogin?.open({runnerId: form.elements.runner.value, runtime: form.elements.runtime.value, profile: name,
      machine: form.elements.runner.selectedOptions[0]?.textContent || ''});
    form.elements.profile.value = '';                     // handed to the sign-in; the list redraws once it reports
  };
}

// ---- the bot editor: Subscription (from its group, or its own) and the line under Model
const BOT_SUB_LINE = new Map();          // slug -> GET /v2/bots/{bot}/subscription, so a redraw paints at once
function subsSourceWords(source) {
  const s = String(source || '');
  if (s === 'bot') return 'set for this bot';
  if (s.startsWith('group:')) return `from group ${s.slice(6)}`;
  return s === 'computer' ? 'computer default' : '';
}
// {profile, source, computer: {runner_id, label} | null, signed_in: true | false | null, problem}
function subsBotLineHTML(line) {
  if (!line) return '';
  const computer = subsComputerLabel(line.computer);
  const parts = [line.profile || 'default', line.profile || line.source !== 'computer' ? subsSourceWords(line.source) : '', computer].filter(Boolean);
  // The server's own words when it has them (a profile this computer lacks, a runner too old to say).
  const warn = line.problem || (line.signed_in === false ? 'Not signed in' : '');
  return `<span class="sb-sub-text">Subscription: ${esc(parts.join(' · '))}</span>${warn ? ` <span class="pill fail sb-sub-warn">${esc(warn)}</span>` : ''}`;
}
// Owners, admins and the person whose computer the bot runs on choose a bot's subscription (backend/subscriptions.py).
const subsMayChooseForBot = e => settingsIsAdmin() || (!!e?.machine?.operator && e.machine.operator === S.me?.id);
function subsBotPaint(rows, slug) {
  const e = (S.emps || []).find(x => x.name === slug);
  const lineEl = rows.querySelector('[data-bot-sub-line]'), row = rows.querySelector('[data-bot-sub-row]');
  const line = BOT_SUB_LINE.get(slug);
  if (lineEl) { lineEl.innerHTML = subsBotLineHTML(line); lineEl.hidden = !line; }
  if (!row) return;
  if (!SUBS || !e) { row.hidden = true; return; }
  const own = subsAssigned('bot', slug), runner = e.machine?.runner_id || '';
  const from = e.team ? subsGroupProfile(e.team) : null;
  const inherit = from?.group ? `From group (${from.group.name})` : 'Computer default';
  // The bot's own computer's subscriptions first; one that is only elsewhere would fall back to its default login.
  const here = runner ? (SUBS.computers.find(c => c.runner_id === runner)?.profiles || []).map(p => p.name).sort((a, b) => a.localeCompare(b)) : subsNames();
  const elsewhere = subsNames().filter(n => !here.includes(n));
  if (own && !here.includes(own) && !elsewhere.includes(own)) elsewhere.push(own);
  const opt = n => `<option value="${esc(n)}"${n === own ? ' selected' : ''}>${esc(n)}</option>`;
  const sel = row.querySelector('select');
  sel.innerHTML = `<option value="">${esc(inherit)}</option>${runner && elsewhere.length
    ? `${here.length ? `<optgroup label="${esc(subsComputerLabel(runner))}">${here.map(opt).join('')}</optgroup>` : ''}<optgroup label="Other computers">${elsewhere.map(opt).join('')}</optgroup>`
    : here.map(opt).join('')}`;
  sel.disabled = !subsMayChooseForBot(e);
  row.hidden = false;
}
async function subsBotMount(rows, slug) {
  if (!rows || !S.me?.cloud) return;
  if (rows.dataset.subsWired !== slug) {
    rows.dataset.subsWired = slug;
    rows.addEventListener('change', async ev => {
      const sel = ev.target.closest('[data-bot-sub]'); if (!sel) return;
      sel.disabled = true;
      try { await put('/v2/subscriptions', {scope: 'bot', target: slug, profile: sel.value || null}); }
      catch (e) { toast(e.message, true); }
      BOT_SUB_LINE.delete(slug);
      await subsBotMount(rows, slug);
    });
  }
  subsBotPaint(rows, slug);
  const [, line] = await Promise.all([subsLoad(), get(`/v2/bots/${encodeURIComponent(slug)}/subscription`).catch(() => null)]);
  if (line) BOT_SUB_LINE.set(slug, line); else BOT_SUB_LINE.delete(slug);
  if (rows.isConnected) subsBotPaint(rows, slug);
}
