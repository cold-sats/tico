/* ui/app/settings-bots.js — Settings > Bots: model and computer pickers, filters, bulk change, catalog picker
   Classic script: its globals are shared with the other files under ui/app/, loaded in the order index.html lists them. */
'use strict';

const settingsBotName = slug => S.emps.find(e => e.name === slug)?.display_name || slug;
const settingsPerson = id => SETTINGS_DATA.people.find(person => person.id === id);
const settingsPersonName = id => settingsPerson(id)?.name || id || 'Unassigned';
let SETTINGS_KEEP_MODEL = '';
const settingsModel = id => SETTINGS_DATA.models.find(model => model.id === id);
const settingsHarness = id => (SETTINGS_DATA.harnesses || []).find(row => row.id === id);
const settingsModelName = id => settingsModel(id)?.label || id || 'Not set';
const settingsHarnessName = id => settingsHarness(id)?.label || id || '';
const settingsEffortName = effort => ({low:'low', medium:'medium', high:'high', xhigh:'xhigh', max:'max', ultra:'ultra'})[effort] || effort || '';
const settingsChoiceValue = (harness, model, effort) => [harness || '', model || '', effort || ''].join('::');
function settingsChoiceFromValue(value) {
  const parts = String(value || '').split('::');
  return {harness: parts[0] || '', model: parts[1] || '', effort: parts[2] || ''};
}
const settingsChoiceLabel = (harness, model, effort) => {
  if (!model) return 'not set';
  const left = [settingsHarnessName(harness) || harness, settingsModelName(model)].filter(Boolean).join('/');
  return effort ? `${left} · ${settingsEffortName(effort)}` : left;
};
// A bot with no model of its own follows the company default; say which one it resolves to.
function settingsDefaultLabel(e) {
  if (e.model || !e.resolved_model) return 'not set';
  const row = settingsModel(e.resolved_model);
  return `company default (${settingsChoiceLabel(e.resolved_runtime, e.resolved_model, row?.default_effort || '')})`;
}
function settingsAllChoices() {
  // Once the owner has chosen providers, only their models are offered (a bot already on another
  // one keeps its own choice in the editor).
  const enabled = SETTINGS_DATA.enabledProviders || [];
  return (SETTINGS_DATA.models || []).filter(model => !model.deprecated &&
    (!enabled.length || !model.provider || enabled.includes(model.provider) || model.id === SETTINGS_KEEP_MODEL)).flatMap(model =>
    (model.harnesses || [model.runtime]).flatMap(harness =>
      (model.efforts?.length ? model.efforts : [model.default_effort || '']).map(effort => {
        const label = settingsChoiceLabel(harness, model.id, effort);
        const search = [harness, settingsHarnessName(harness), model.id, model.label, effort, label].join(' ').toLowerCase();
        return {harness, model: model.id, effort, label, search, value: settingsChoiceValue(harness, model.id, effort)};
      })));
}
function settingsFilterChoices(query) {
  const needle = String(query || '').trim().toLowerCase();
  const choices = settingsAllChoices();
  if (!needle) return choices;
  return choices.filter(choice => needle.split(/\s+/).every(part => choice.search.includes(part)));
}
function settingsChoiceCombo(e, kind) {
  const fallback = kind === 'fallback';
  const selected = fallback ? (e.fallback || null) : e;
  const harness = fallback ? selected?.harness : (e.harness || e.runtime);
  const model = fallback ? selected?.model : e.model;
  const effort = fallback ? (selected?.reasoning_effort || selected?.effort)
    : (e.reasoning_effort || e.effort);
  const current = (fallback && !model) ? '' : settingsChoiceValue(harness, model, effort);
  const label = current ? settingsChoiceLabel(harness, model, effort) : (fallback ? 'None' : settingsDefaultLabel(e));
  const aria = fallback ? `Fallback for ${e.display_name}` : `Model and effort for ${e.display_name}`;
  return `<div class="settings-combo" data-bot-choice="${esc(e.name)}" data-kind="${kind}" data-current="${esc(current)}"
    title="${esc(label)}">
    <input type="search" autocomplete="off" spellcheck="false" value="${esc(label)}"
      aria-label="${esc(aria)}" placeholder="${fallback ? 'None' : 'Search harness or model'}"
      ${settingsCanManageBot(e) ? '' : 'disabled'}>
    <div class="settings-combo-list" role="listbox"></div>
  </div>`;
}
function settingsWireCombos(root, onPick = settingsPickChoice) {
  root.querySelectorAll('[data-bot-choice]').forEach(box => {
    const input = box.querySelector('input[type=search]');
    const list = box.querySelector('.settings-combo-list');
    if (!input || !list || input.disabled) return;
    const none = box.dataset.kind === 'fallback';
    const render = query => {
      const choices = settingsFilterChoices(query);
      const rows = (none ? [{value:'', label:'None'}] : []).concat(choices);
      list.innerHTML = rows.length
        ? rows.map(choice => `<button type="button" role="option" data-value="${esc(choice.value)}" ${choice.value === box.dataset.current ? 'aria-selected="true"' : ''}>${esc(choice.label)}</button>`).join('')
        : '<div class="settings-combo-empty">No matching harness or model</div>';
      list.querySelectorAll('[data-value]').forEach(button => {
        button.onmousedown = event => event.preventDefault();
        button.onclick = () => void onPick(box, button.dataset.value);
      });
    };
    input.onfocus = () => { box.classList.add('open'); input.select(); render(input.value === input.defaultValue ? '' : input.value); };
    input.oninput = () => { box.classList.add('open'); render(input.value); };
    input.onblur = () => { box.classList.remove('open'); input.value = input.defaultValue; };
  });
}
async function settingsPickChoice(box, value) {
  const slug = box.dataset.botChoice, e = S.emps.find(row => row.name === slug);
  const current = box.dataset.current || '';
  if (!e || value === current) return;
  const input = box.querySelector('input[type=search]');
  if (box.dataset.kind === 'fallback') {
    try {
      const choice = value ? settingsChoiceFromValue(value) : null;
      await post(`/v2/bots/${encodeURIComponent(slug)}/fallback`, {
        fallback: choice ? {harness: choice.harness, model: choice.model, effort: choice.effort} : null,
        expected_revision: e.revision});
      await loadSettings();
      toast(choice ? `${e.display_name} fallback is ${settingsChoiceLabel(choice.harness, choice.model, choice.effort)}`
        : `${e.display_name} fallback is none`);
    } catch (error) {
      if (input) input.value = input.defaultValue;
      toast(error.message, true);
    }
    return;
  }
  const choice = settingsChoiceFromValue(value);
  if (!choice.model || !choice.effort || !choice.harness) { if (input) input.value = input.defaultValue; return; }
  if (!await settingsConfirmTransition(e, 'model', settingsChoiceLabel(choice.harness, choice.model, choice.effort))) {
    if (input) input.value = input.defaultValue;
    return;
  }
  await settingsBeginTransition(box, e, {kind:'model', model:choice.model, effort:choice.effort,
    harness:choice.harness, expected_generation:e.machine?.generation || 0, expected_revision:e.revision});
}
function settingsMachineSelect(e) {
  if (e.agent) return settingsAgentCell(e);
  const current = e.machine?.runner_id || '';
  const machines = SETTINGS_DATA.machines.filter(machine => !machine.revoked_at &&
    (S.me?.role === 'owner' || machine.operator === S.me?.id));
  const unassigned = `Not assigned · ${settingsPersonName(e.operator)}`;
  const currentLabel = e.machine ? `${e.machine.label} · ${settingsPersonName(e.machine.operator)}` : unassigned;
  const seen = e.machine?.last_seen ? `last seen ${ago(e.machine.last_seen)}` : e.machine ? 'waiting for its first heartbeat' : 'register a computer first';
  return `<select class="settings-inline-select" data-bot-machine="${esc(e.name)}" data-current="${esc(current)}"
    aria-label="Machine for ${esc(e.display_name)}" title="${esc(`${currentLabel} · ${seen}`)}" ${settingsCanManageBot(e) && machines.length ? '' : 'disabled'}>
      ${current ? '' : `<option value="" selected disabled>${esc(unassigned)}</option>`}
      ${machines.map(machine => `<option value="${esc(machine.id)}" ${machine.id === current ? 'selected' : ''}>${esc(machine.label)} · ${esc(settingsPersonName(machine.operator))}</option>`).join('')}
    </select>`;
}
// A problem worth a badge on the bot's row; a bot that is fine shows nothing.
function settingsBotProblem(e) {
  if (e.status !== 'active') return '';
  if (e.agent) return !e.agent.credential ? 'no credential' : e.online ? '' : 'not reporting';
  return !e.machine ? 'no computer' : e.online && e.ready ? '' : e.online ? 'setup needed' : 'offline';
}
// Settings → Bots filters and bulk model change ("filter by computer, filter
// by model, select in bulk, and change model in bulk"). Filters are remembered per browser; the
// selection is not, and it is trimmed to what the filters show so a bulk change never reaches a
// bot the person cannot see. Bulk apply is the single-row path run once per bot, not a new route.
const SETTINGS_BOTS_FILTER_KEY = 'hub.settings.bots.filters';
const SETTINGS_BOTS_VIEW = {computer: '', model: '', effort: '', selected: new Set()};
try { Object.assign(SETTINGS_BOTS_VIEW, JSON.parse(localStorage.getItem(SETTINGS_BOTS_FILTER_KEY) || '{}'), {selected: new Set()}); } catch {}
function settingsBotsRemember() {
  const {computer, model, effort} = SETTINGS_BOTS_VIEW;
  try { localStorage.setItem(SETTINGS_BOTS_FILTER_KEY, JSON.stringify({computer, model, effort})); } catch {}
}
const settingsBotHarness = e => e.harness || e.runtime || '';
const settingsBotEffort = e => e.reasoning_effort || e.effort || '';
const settingsBotComputerKey = e => e.agent ? 'agent' : e.machine?.runner_id || 'none';
const settingsBotModelKey = e => e.agent ? 'agent' : `${settingsBotHarness(e)}::${e.model || ''}`;
const settingsBotSelectable = e => !e.agent && settingsCanManageBot(e);
function settingsBotsFilterOptions(rows) {
  const count = (map, key, label) => { const row = map.get(key) || {key, label, n: 0}; row.n++; map.set(key, row); };
  const computers = new Map(), models = new Map(), efforts = new Map();
  rows.forEach(e => {
    count(computers, settingsBotComputerKey(e), e.agent ? 'External agents'
      : e.machine ? `${e.machine.label} · ${settingsPersonName(e.machine.operator)}` : 'Unassigned');
    count(models, settingsBotModelKey(e), e.agent ? "External agent's own model"
      : settingsChoiceLabel(settingsBotHarness(e), e.model, ''));
    if (!e.agent && settingsBotEffort(e)) count(efforts, settingsBotEffort(e), settingsEffortName(settingsBotEffort(e)));
  });
  const sorted = map => [...map.values()].sort((a, b) => a.label.localeCompare(b.label));
  return {computers: sorted(computers), models: sorted(models), efforts: sorted(efforts)};
}
function settingsBotsVisible(rows) {
  const {computer, model, effort} = SETTINGS_BOTS_VIEW;
  return rows.filter(e => (!computer || settingsBotComputerKey(e) === computer)
    && (!model || settingsBotModelKey(e) === model)
    && (!effort || (!e.agent && settingsBotEffort(e) === effort)));
}
function settingsBotsFilterHTML(options, shown, total) {
  const select = (name, label, all, list) => `<select class="settings-inline-select" data-bots-filter="${name}" aria-label="Filter bots by ${label.toLowerCase()}">
      <option value="">${all}</option>${list.map(row => `<option value="${esc(row.key)}" ${row.key === SETTINGS_BOTS_VIEW[name] ? 'selected' : ''}>${esc(row.label)} (${row.n})</option>`).join('')}</select>`;
  return `<div class="settings-bots-filters">${select('computer', 'Computer', 'All computers', options.computers)}
    ${select('model', 'Model', 'All models', options.models)}${select('effort', 'Effort', 'Any effort', options.efforts)}
    <span class="settings-bots-count" data-bots-count>${shown === total ? `${total} bots` : `${shown} of ${total} bots`}</span></div>
    <div class="settings-bulk" data-bots-bulk hidden><strong data-bulk-count></strong>
      <button class="primary" type="button" data-bulk-model>Change model…</button><button class="ghost" type="button" data-bulk-clear>Clear</button></div>`;
}
function settingsBotsSyncSelection(el, visible) {
  const selectable = visible.filter(settingsBotSelectable).map(e => e.name);
  const picked = selectable.filter(slug => SETTINGS_BOTS_VIEW.selected.has(slug)).length;
  const all = el.querySelector('[data-bots-select-all]');
  if (all) { all.checked = !!selectable.length && picked === selectable.length; all.indeterminate = picked > 0 && picked < selectable.length; all.disabled = !selectable.length; }
  const bar = el.querySelector('[data-bots-bulk]');
  if (bar) { bar.hidden = !SETTINGS_BOTS_VIEW.selected.size; bar.querySelector('[data-bulk-count]').textContent = `${SETTINGS_BOTS_VIEW.selected.size} selected`; }
}
function settingsBulkModelDialog() {
  const bots = [...SETTINGS_BOTS_VIEW.selected].map(slug => S.emps.find(e => e.name === slug)).filter(Boolean);
  if (!bots.length) return;
  const dialog = document.createElement('dialog'); dialog.className = 'tmodal settings-bulk-dialog';
  dialog.setAttribute('aria-labelledby', 'bulk-model-title');
  let choice = null, running = false, ran = false;
  const paint = () => {
    const label = choice ? settingsChoiceLabel(choice.harness, choice.model, choice.effort) : '';
    dialog.innerHTML = `<div class="tmodal-head"><h2 id="bulk-model-title">Change model · ${bots.length} bot${bots.length === 1 ? '' : 's'}</h2><span class="spacer"></span><button class="ghost" type="button" data-bulk-close aria-label="Close">✕</button></div>
      <div class="transition-body">
        <div class="settings-combo" data-bot-choice="" data-kind="model" data-current="${esc(choice ? settingsChoiceValue(choice.harness, choice.model, choice.effort) : '')}">
          <input type="search" autocomplete="off" spellcheck="false" value="${esc(label)}" aria-label="Model and effort for the selected bots" placeholder="Search harness or model">
          <div class="settings-combo-list" role="listbox"></div></div>
        ${choice ? `<p>Destination: <strong>${esc(label)}</strong></p>` : ''}
        <div class="transition-progress"><strong>Each bot starts a fresh provider session.</strong>
          <p>History is kept. A bot mid-turn is skipped; retry it after.</p></div>
        <ul class="settings-bulk-list" data-bulk-list>${bots.map(e => `<li data-bulk-bot="${esc(e.name)}" data-state="pending"><span>${esc(e.display_name || e.name)}</span><span class="settings-cell-note">${esc(settingsChoiceLabel(settingsBotHarness(e), e.model, settingsBotEffort(e)))}</span></li>`).join('')}</ul>
        <p role="status" data-bulk-summary></p>
        <div class="transition-actions"><button class="primary" type="button" data-bulk-apply ${choice ? '' : 'disabled'}>Change ${bots.length} bot${bots.length === 1 ? '' : 's'}</button><button class="ghost" type="button" data-bulk-close>Cancel</button></div></div>`;
    dialog.querySelectorAll('[data-bulk-close]').forEach(button => button.onclick = () => dialog.close());
    settingsWireCombos(dialog, (box, value) => {
      const picked = settingsChoiceFromValue(value);
      if (!picked.model || !picked.effort || !picked.harness) return;
      choice = picked; paint();
    });
    dialog.querySelector('[data-bulk-apply]').onclick = () => void run(bots);
  };
  const mark = (slug, state, note) => {
    const row = dialog.querySelector(`[data-bulk-bot="${CSS.escape(slug)}"]`); if (!row) return;
    row.dataset.state = state; row.querySelector('.settings-cell-note').textContent = note;
  };
  const run = async targets => {
    if (running || !choice) return;
    running = ran = true;
    const apply = dialog.querySelector('[data-bulk-apply]'), combo = dialog.querySelector('.settings-combo input');
    apply.disabled = true; if (combo) combo.disabled = true;
    const results = {changed: 0, skipped: 0, failed: []};
    for (const e of targets) {
      mark(e.name, 'working', 'Changing…');
      const result = await settingsBulkApplyOne(e.name, choice);
      mark(e.name, result.state, result.note);
      if (result.state === 'failed') results.failed.push(e); else results[result.state]++;
    }
    running = false;
    const summary = [`${results.changed} changed`, results.skipped ? `${results.skipped} already on it` : '',
      results.failed.length ? `${results.failed.length} failed` : ''].filter(Boolean).join(' · ');
    dialog.querySelector('[data-bulk-summary]').textContent = summary;
    const actions = dialog.querySelector('.transition-actions');
    actions.innerHTML = `${results.failed.length ? '<button class="ghost" type="button" data-bulk-retry>Retry failed</button>' : ''}<button class="primary" type="button" data-bulk-close>Done</button>`;
    actions.querySelector('[data-bulk-close]').onclick = () => dialog.close();
    const retry = actions.querySelector('[data-bulk-retry]');
    if (retry) retry.onclick = () => void run(results.failed);
    await loadSettings();
  };
  // Cancel keeps the selection; once a change has run, the next bulk action starts fresh.
  dialog.onclose = () => { dialog.remove(); if (ran) { SETTINGS_BOTS_VIEW.selected.clear(); void loadSettings(); } };
  document.body.appendChild(dialog); paint(); dialog.showModal();
}
// One bot, the same request the row's Model control sends. A stale revision (someone changed
// the bot a moment ago) refreshes the bot list and tries once more; anything else is reported.
async function settingsBulkApplyOne(slug, choice) {
  for (let attempt = 0; attempt < 2; attempt++) {
    const e = S.emps.find(row => row.name === slug);
    if (!e) return {state: 'failed', note: 'This bot is no longer listed'};
    if (settingsBotHarness(e) === choice.harness && e.model === choice.model && settingsBotEffort(e) === choice.effort)
      return {state: 'skipped', note: 'Already on this model'};
    try {
      const t = await post(`/v2/bots/${encodeURIComponent(slug)}/transitions`, {kind: 'model', model: choice.model,
        effort: choice.effort, harness: choice.harness, expected_generation: e.machine?.generation || 0,
        expected_revision: e.revision});
      return t.state === 'applied' ? {state: 'changed', note: `Now ${settingsChoiceLabel(choice.harness, choice.model, choice.effort)}`}
        : {state: 'failed', note: `Change ${t.state}; open the bot's Model control to finish it`};
    } catch (error) {
      const code = error.body?.error?.code;
      if (code === 'unchanged') return {state: 'skipped', note: 'Already on this model'};
      if (code === 'version_conflict' && attempt === 0) {
        try { S.emps = namedRoster(await get('/employees')); } catch {}
        continue;
      }
      return {state: 'failed', note: error.message || 'The change failed'};
    }
  }
  return {state: 'failed', note: 'Bot settings kept changing; refresh and try again'};
}
function renderSettingsBots() {
  const el = $('#set-bots'); if (!el) return;
  const all = S.emps.slice().sort((a,b) => (a.team || '').localeCompare(b.team || '') || byBotOrder(a, b) || settingsBotName(a.name).localeCompare(settingsBotName(b.name)));
  const options = settingsBotsFilterOptions(all);
  // A remembered filter whose computer or model no longer exists would hide every bot silently.
  ['computer', 'model', 'effort'].forEach(name => {
    const list = options[{computer: 'computers', model: 'models', effort: 'efforts'}[name]];
    if (SETTINGS_BOTS_VIEW[name] && !list.some(row => row.key === SETTINGS_BOTS_VIEW[name])) SETTINGS_BOTS_VIEW[name] = '';
  });
  const rows = settingsBotsVisible(all);
  const shownSelectable = new Set(rows.filter(settingsBotSelectable).map(e => e.name));
  [...SETTINGS_BOTS_VIEW.selected].forEach(slug => { if (!shownSelectable.has(slug)) SETTINGS_BOTS_VIEW.selected.delete(slug); });
  const pick = e => settingsBotSelectable(e)
    ? `<input type="checkbox" data-bot-pick="${esc(e.name)}" aria-label="Select ${esc(e.display_name)}" ${SETTINGS_BOTS_VIEW.selected.has(e.name) ? 'checked' : ''}>`
    : `<input type="checkbox" disabled aria-label="${esc(e.display_name)} cannot be changed here" title="${e.agent ? 'An external agent uses its own model' : 'You do not operate this bot'}">`;
  const stack = e => {
    const owners = (e.bot_owners || []).length ? e.bot_owners : (e.users || []);
    const names = owners.map(o => o.name || o.id);
    return `<span class="sb-stack" title="${esc(names.join(', ') || 'No owner')}">${owners.slice(0, 3).map(o => personCircle(o.name || o.id, 22)).join('')}${owners.length > 3 ? `<span class="more">+${owners.length - 3}</span>` : ''}${owners.length ? '' : '<span class="muted">None</span>'}</span>`;
  };
  const row = e => {
    const problem = settingsBotProblem(e);
    const badges = `${isBuiltInBot(e.name) ? '<span class="pill" data-built-in>Built in</span>' : ''}${e.status && e.status !== 'active' ? `<span class="pill ${e.status === 'paused' ? 'waiting' : ''}">${esc(e.status)}</span>` : ''}`;
    const model = e.agent ? `<span class="muted" title="${esc(e.agent.model ? `profile's model · ${e.agent.model}` : "the profile's own model")}">${esc(agentKind(e.agent))}</span>` : settingsChoiceCombo(e, 'model');
    return `<tr data-settings-bot="${esc(e.name)}"><td class="settings-pick">${pick(e)}</td>
      <td class="sb-cell-name"><div class="sb-bot">${avatar(e.name, 27, stateOf(e.name))}<div class="sb-text"><div class="sb-line"><a class="sb-name" href="#/bot/${esc(e.name)}">${shownName(e)}</a>${badges}</div>${e.team || problem ? `<small>${e.team ? esc(teamLabel(e.team)) : ''}${e.team && problem ? ' · ' : ''}${problem ? `<span class="sb-problem">${esc(problem)}</span>` : ''}</small>` : ''}</div></div></td>
      <td class="sb-cell-access">${settingsAccessCell(e)}</td><td class="sb-cell-model">${model}</td>
      <td class="sb-cell-fallback">${e.agent ? '<span class="muted">-</span>' : settingsChoiceCombo(e, 'fallback')}</td>
      <td class="sb-cell-owners">${stack(e)}</td><td class="sb-cell-computer">${settingsMachineSelect(e)}</td>
      <td class="settings-row-actions">${settingsCanManageBot(e) ? `<button class="ghost" type="button" data-edit-bot="${esc(e.name)}" aria-label="Edit ${esc(e.display_name)}">Edit</button>` : ''}</td></tr>`;
  };
  el.innerHTML = !all.length ? '<div class="empty">No bots are registered.</div>' : `${settingsBotsFilterHTML(options, rows.length, all.length)}${rows.length ? `<div class="scroll"><table class="settings-bots-table"><thead><tr><th class="settings-pick"><input type="checkbox" data-bots-select-all aria-label="Select all shown bots"></th><th>Bot</th><th>Access</th><th>Model</th><th>Fallback</th><th>Owners</th><th>Computer</th><th aria-label="Actions"></th></tr></thead><tbody>
    ${rows.map(row).join('')}
    </tbody></table></div>` : '<div class="empty">No bots match these filters.</div>'}`;
  settingsBotsSyncSelection(el, rows);
  el.onclick = event => {
    if (event.target.closest('[data-bulk-model]')) { settingsBulkModelDialog(); return; }
    if (event.target.closest('[data-bulk-clear]')) { SETTINGS_BOTS_VIEW.selected.clear(); renderSettingsBots(); return; }
    const bot = event.target.closest('[data-edit-bot]');
    const credential = event.target.closest('[data-agent-credential]');
    const revoke = event.target.closest('[data-agent-revoke]');
    if (bot) settingsEditBot(bot.dataset.editBot);
    if (credential) void settingsAgentCredential(credential.dataset.agentCredential);
    if (revoke) void settingsAgentRevoke(revoke.dataset.agentRevoke);
  };
  el.onchange = event => {
    const filter = event.target.closest('[data-bots-filter]');
    if (filter) { SETTINGS_BOTS_VIEW[filter.dataset.botsFilter] = filter.value; settingsBotsRemember(); renderSettingsBots(); return; }
    const one = event.target.closest('[data-bot-pick]');
    if (one) { one.checked ? SETTINGS_BOTS_VIEW.selected.add(one.dataset.botPick) : SETTINGS_BOTS_VIEW.selected.delete(one.dataset.botPick); settingsBotsSyncSelection(el, rows); return; }
    if (event.target.closest('[data-bots-select-all]')) {
      const on = event.target.checked;
      rows.filter(settingsBotSelectable).forEach(e => on ? SETTINGS_BOTS_VIEW.selected.add(e.name) : SETTINGS_BOTS_VIEW.selected.delete(e.name));
      el.querySelectorAll('[data-bot-pick]').forEach(box => { box.checked = on; });
      settingsBotsSyncSelection(el, rows); return;
    }
    const machine = event.target.closest('[data-bot-machine]');
    if (machine) void settingsMoveBot(machine);
  };
  settingsWireCombos(el);
  const copyAll = $('#copy-setup-prompt');
  if (copyAll) { copyAll.onclick = () => settingsCopyPrompt(); copyAll.disabled = false; }
  const add = $('#settings-add-bot');
  if (add) { add.onclick = () => settingsEditBot(); add.disabled = false; }
  const fromCatalog = $('#settings-add-catalog');
  if (fromCatalog) { fromCatalog.onclick = () => void settingsCatalogPicker(); fromCatalog.disabled = false; }
}
// The same catalog cards the first run shows, for a company that is already set up. Nothing is
// locked on here: the bots that were required at first run already exist and are filtered out.
async function settingsCatalogPicker() {
  const dialog = $('#catalog-picker'); if (!dialog) return;
  dialog.innerHTML = `<form><div class="tmodal-head"><h2 id="catalog-picker-title">Add from catalog</h2><span class="spacer"></span>
      <button class="ghost" type="button" data-catalog-close aria-label="Close">✕</button></div>
    <div class="bot-editor-body" id="catalog-picker-body"><div class="empty">Loading the catalog…</div></div></form>`;
  dialog.onclose = () => { dialog.innerHTML = ''; };
  dialog.querySelectorAll('[data-catalog-close]').forEach(button => button.onclick = () => dialog.close());
  dialog.showModal();
  let cards;
  try { cards = catalogCards(await get('/v2/catalog')); }
  catch (error) {
    const body = $('#catalog-picker-body'); if (body) body.innerHTML = `<div class="err">${esc(error.message)}</div>`;
    return;
  }
  if (!dialog.open) return;
  const have = new Set(S.emps.filter(row => row.status !== 'archived').map(row => row.name));
  const state = catalogState(cards.filter(card => !have.has(card.slug)), {lock: false});
  const body = $('#catalog-picker-body');
  body.innerHTML = `
    <div class="cat-grid" id="catalog-picker-grid">${catalogGridHTML(state)}</div>
    <div class="row" style="margin-top:16px"><button class="primary" type="submit">Add selected</button>
      <button class="ghost" type="button" data-catalog-close>Cancel</button><span class="muted" id="catalog-picker-status"></span></div>`;
  catalogWire($('#catalog-picker-grid'), state);
  dialog.querySelectorAll('[data-catalog-close]').forEach(button => button.onclick = () => dialog.close());
  const form = dialog.querySelector('form'), status = $('#catalog-picker-status');
  form.onsubmit = async event => {
    event.preventDefault();
    const submit = form.querySelector('[type=submit]');
    const chosen = state.cards.filter(card => state.picked.has(card.slug));
    if (!chosen.length) { status.innerHTML = '<span class="err">Choose at least one bot.</span>'; return; }
    if (!S.me?.id) { status.innerHTML = '<span class="err">Sign in before adding a bot.</span>'; return; }
    submit.disabled = true; status.textContent = 'Adding…';
    try {
      for (const card of chosen) {
        if (card.template === 'inbox' && !catalogPerson(state, card)) {
          status.innerHTML = '<span class="err">Choose whose mailbox the inbox bot reads.</span>';
          submit.disabled = false; return;
        }
        const person = catalogPerson(state, card);
        const slug = card.template === 'inbox' && person ? `${person.id}-inbox`
          : card.template === 'assistant' ? assistantBot() : card.slug;
        const named = catalogName(state, card);
        const display = card.template === 'inbox' && person && named === (card.name || card.slug)
          ? `${person.name || person.id} Inbox` : named;
        await post('/v2/bots', {
          slug, display_name: display, description: card.summary || '',
          template: card.template, instructions: catalogInstructions(state, card),
          reports_to: null, status: 'planned', repo: `emp-${slug}`, thread_mode: 'personal',
          model: card.model, effort: card.reasoning_effort, operator: S.me.id, owners: [S.me.id], runner_id: null});
      }
      dialog.close(); await loadSettings(); settingsShow('bots');
      toast(chosen.length === 1 ? `Added ${catalogName(state, chosen[0])}` : `Added ${chosen.length} bots`);
    } catch (error) { status.innerHTML = `<span class="err">${esc(error.message)}</span>`; submit.disabled = false; }
  };
}
