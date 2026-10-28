/* ui/app/strategy-budget.js — Strategy > Budget (redesign): task caps between teammates and spend per bot and group.
   Caps: GET/PUT/DELETE /api/v2/task-caps (redesign CONTRACT §1): how many tasks a day a sender may give a manager above
   it; today's count, the ones it closed before the manager acted, and the ones refused. Spend: GET /api/v2/usage/limits
   and its PUTs, by 30 minutes, day, week and month, for each bot, each group's pool and the company's. The server decides
   who may change what; a refusal shows in the editor.
   Classic script: its globals are shared with the other files under ui/app/, loaded in the order index.html lists them. */
'use strict';

let BUDGET = null;          // the open tab: {load, mode, limits, caps, capsError}
const BUDGET_PERIODS = [['per_30m_usd', 'Per 30 min'], ['daily_usd', 'Per day'], ['weekly_usd', 'Per week'], ['monthly_usd', 'Per month']];
const budgetMoney = n => '$ ' + Number(n || 0).toFixed(2);
// Teammate refs (CONTRACT): bot:<slug>, person:<id>.
const budgetName = ref => {
  const [kind, ...rest] = String(ref || '').split(':'), id = rest.join(':');
  if (kind === 'bot') return botDisplayName(id);
  if (kind === 'person' || kind === 'human') return personDisplay(id);
  return String(ref || '');
};
// "2/5 · 1 closed", "0 · blocked", "10/10 · 3 rejected".
function budgetCapText(c) {
  if (c.per_day === 0) return '0 · blocked';
  let t = `${c.count || 0}/${c.per_day}`;
  if (c.closed) t += ` · ${c.closed} closed`;
  if (c.rejected) t += ` · ${c.rejected} rejected`;
  return t;
}
const budgetCapTone = c => c.per_day === 0 ? 'fail' : (c.count || 0) >= c.per_day ? 'waiting' : '';

function pageBudget() {
  const load = (BUDGET?.load || 0) + 1, mode = BUDGET?.mode || 'both';
  BUDGET = {load, mode, limits: null, caps: [], capsError: ''};
  const main = $('#main');
  main.classList.add('strategy-layout', 'budget-layout');
  main.innerHTML = strategyHeadHtml('budget') + `<div class="bd-top">
      <div class="bd-seg" role="group" aria-label="Show">${[['tasks', 'Tasks'], ['spend', 'Spend'], ['both', 'Both']].map(([k, label]) =>
        `<button type="button" data-bd-mode="${k}" aria-pressed="${k === mode}">${label}</button>`).join('')}</div>
      <button type="button" class="ghost" data-bd-add>+ Add cap</button></div>
    <div id="bd-body" class="bd-body" data-mode="${mode}">${skelRows(5, {dot: false})}</div>`;
  main.querySelector('.bd-seg').onclick = ev => {
    const b = ev.target.closest('[data-bd-mode]'); if (!b) return;
    BUDGET.mode = b.dataset.bdMode;
    main.querySelectorAll('[data-bd-mode]').forEach(x => x.setAttribute('aria-pressed', String(x === b)));
    $('#bd-body').dataset.mode = BUDGET.mode;
  };
  main.querySelector('[data-bd-add]').onclick = () => budgetCapEdit(null);
  void budgetLoad(BUDGET);
}

async function budgetLoad(state) {
  const [limits, caps] = await Promise.allSettled([get('/v2/usage/limits', {fresh: true}), get('/v2/task-caps', {fresh: true})]);
  if (BUDGET !== state || !$('#bd-body')) return;
  state.limits = limits.status === 'fulfilled' ? limits.value : null;
  state.limitsError = limits.status === 'rejected' ? limits.reason?.message || 'Spend did not load.' : '';
  state.caps = caps.status === 'fulfilled' ? (caps.value?.caps || []) : [];
  state.capsError = caps.status === 'rejected' ? caps.reason?.message || 'Caps did not load.' : '';
  budgetRender(state);
}
const budgetReload = () => BUDGET && $('#bd-body') ? budgetLoad(BUDGET) : null;

function budgetRender(state) {
  const body = $('#bd-body');
  const caps = state.caps.length ? state.caps.map((c, i) => `<li><button type="button" class="bd-row" data-bd-cap="${i}">
      <span class="bd-name">${esc(budgetName(c.sender))} → ${esc(budgetName(c.receiver))}</span>
      <span class="pill bd-cap ${budgetCapTone(c)}">${esc(budgetCapText(c))}</span></button></li>`).join('')
    : `<li class="muted bd-none">${state.capsError ? esc(state.capsError) : 'No caps'}</li>`;
  body.innerHTML = `<section class="bd-sec bd-tasks" aria-labelledby="bd-tasks-h"><h2 id="bd-tasks-h">Task caps</h2><ul class="bd-list">${caps}</ul></section>
    <section class="bd-sec bd-spend" aria-labelledby="bd-spend-h"><h2 id="bd-spend-h">Spend</h2>${budgetSpendHtml(state)}</section>`;
  body.onclick = ev => {
    const cap = ev.target.closest('[data-bd-cap]');
    if (cap) { budgetCapEdit(state.caps[Number(cap.dataset.bdCap)]); return; }
    const spend = ev.target.closest('[data-bd-spend]');
    if (spend) budgetSpendEdit(spend.dataset.bdSpend, spend.dataset.bdName);
  };
}

// A row: the name, "$ spent / $ limit" for the 30-minute window, a bar, and Paused when the bot is held.
function budgetSpendRow(key, name, row, {pool = false} = {}) {
  const cap = row?.per_30m_usd, spent = row?.['30m_spent'] || 0, pct = cap ? Math.min(100, Math.round(spent / cap * 100)) : 0;
  const tone = row?.blocked ? 'bad' : cap && pct >= 90 ? 'warn' : '';
  const amount = cap != null ? `${budgetMoney(spent)} / ${budgetMoney(cap)}` : 'No limit';
  const may = pool ? !!BUDGET.limits?.may_edit_default : row?.may_edit !== false;
  const inner = `<span class="bd-name">${esc(name)}</span><span class="bd-amt">${amount}</span>
    <span class="bd-bar" aria-hidden="true"><i style="width:${pct}%"></i></span>${row?.blocked ? '<span class="bd-paused">Paused</span>' : ''}`;
  return `<li class="${pool ? 'bd-pool ' : ''}${tone}">${may
    ? `<button type="button" class="bd-row" data-bd-spend="${esc(key)}" data-bd-name="${esc(name)}">${inner}</button>`
    : `<div class="bd-row">${inner}</div>`}</li>`;
}
// The company's pool, then each group (its pool, then its bots), then the bots in no group.
function budgetSpendHtml(state) {
  const limits = state.limits;
  if (!limits) return `<p class="muted bd-none">${esc(state.limitsError || 'Spend did not load.')}</p>`;
  const bots = limits.bots || {}, pools = limits.pools || null, groups = pools?.groups || {};
  const groupOf = slug => (S.emps || []).find(e => e.name === slug)?.team || '';
  const rows = slugs => slugs.map(slug => budgetSpendRow('bot:' + slug, botDisplayName(slug), bots[slug])).join('');
  const slugs = Object.keys(bots).sort((a, b) => botDisplayName(a).localeCompare(botDisplayName(b)));
  let html = pools?.company ? `<ul class="bd-list">${budgetSpendRow('company', 'Company pool', pools.company, {pool: true})}</ul>` : '';
  for (const [gid, g] of Object.entries(groups).sort((a, b) => String(a[1].name).localeCompare(String(b[1].name)))) {
    const mine = slugs.filter(s => groupOf(s) === gid);
    html += `<h3 class="bd-group">${esc(g.name || gid)}</h3><ul class="bd-list">${budgetSpendRow('group:' + gid, (g.name || gid) + ' pool', g, {pool: true})}${rows(mine)}</ul>`;
  }
  const loose = slugs.filter(s => !groups[groupOf(s)]);
  if (loose.length) html += `${Object.keys(groups).length ? '<h3 class="bd-group">No group</h3>' : ''}<ul class="bd-list">${rows(loose)}</ul>`;
  return html || '<p class="muted bd-none">No bots</p>';
}

// The money editor: four windows; an empty one is no limit.
function budgetSpendEdit(key, name) {
  const limits = BUDGET?.limits || {};
  const row = key === 'company' ? limits.pools?.company : key.startsWith('group:') ? limits.pools?.groups?.[key.slice(6)] : limits.bots?.[key.slice(4)];
  const own = k => row?.['own_' + k] !== undefined ? row['own_' + k] : row?.[k];
  const body = `<div class="bd-fields">${BUDGET_PERIODS.map(([k, label]) => `<label class="bd-field"><span>${label}</span>
      <span class="bd-money">$<input name="${k}" inputmode="decimal" autocomplete="off" value="${own(k) != null ? Number(own(k)).toFixed(2) : ''}" aria-label="${label}"></span></label>`).join('')}</div>`;
  const path = key === 'company' ? '/v2/usage/pools/company' : key.startsWith('group:') ? '/v2/usage/pools/groups/' + encodeURIComponent(key.slice(6))
    : '/v2/usage/limits/' + encodeURIComponent(key.slice(4));
  const dlg = useDialog(name, body, async form => {
    const amounts = {};
    for (const [k, label] of BUDGET_PERIODS) {
      const t = String(form[k].value).trim().replace(/^\$\s*/, '');
      if (t !== '' && !/^\d+(\.\d{1,2})?$/.test(t)) throw new Error(`${label}: a dollar amount, like 4.00`);
      amounts[k] = t === '' ? null : Number(t);
    }
    await put(path, amounts);
  }, budgetReload);
  dlg.classList.add('rd-sheet');
}

// Who may be a cap's receiver: a manager above the sender on the chart (the hub refuses anyone else).
function budgetSenders() {
  const bots = (S.emps || []).filter(e => !['archived', 'planned'].includes(e.status)).map(e => ['bot:' + e.name, botDisplayName(e.name)]);
  const people = (S.people || []).filter(p => !p.hidden).map(p => ['person:' + p.id, p.name || p.id]);
  return [...bots, ...people].sort((a, b) => a[1].localeCompare(b[1]));
}
function budgetManagers(sender) {
  const ref = String(sender).replace(/^person:/, 'human:');
  return [...goalOrgPlace(ref).above].map(k => k.startsWith('p:') ? 'person:' + k.slice(2) : 'bot:' + k.slice(2));
}

// The cap editor; `cap` null adds one. "No cap" removes the row.
function budgetCapEdit(cap) {
  const senders = budgetSenders(), first = cap?.sender || senders[0]?.[0] || '';
  const managerOptions = sender => budgetManagers(sender).map(ref => `<option value="${esc(ref)}">${esc(budgetName(ref))}</option>`).join('');
  const pick = cap ? '' : `<label class="bd-field"><span>Sender</span><select name="sender">${senders.map(([ref, label]) =>
      `<option value="${esc(ref)}"${ref === first ? ' selected' : ''}>${esc(label)}</option>`).join('')}</select></label>
    <label class="bd-field"><span>Manager</span><select name="receiver">${managerOptions(first)}</select></label>`;
  const none = cap ? cap.per_day == null : false;
  const body = `${pick}<label class="bd-field"><span>Tasks per day ${helpBubble('0 = go through the manager in between.')}</span>
      <input name="per_day" inputmode="numeric" autocomplete="off" value="${cap?.per_day ?? (cap ? '' : 5)}"${none ? ' disabled' : ''} aria-label="Tasks per day"></label>
    ${cap ? `<label class="bd-field bd-switch"><span>No cap</span><input type="checkbox" role="switch" name="nocap"${none ? ' checked' : ''}></label>` : ''}`;
  const title = cap ? `${budgetName(cap.sender)} → ${budgetName(cap.receiver)}` : 'Add cap';
  const dlg = useDialog(title, body, async form => {
    const sender = cap ? cap.sender : form.sender.value, receiver = cap ? cap.receiver : form.receiver.value;
    if (!receiver) throw new Error('No manager above them to cap.');
    if (cap && form.nocap.checked) {
      await writeRequest('DELETE', `/v2/task-caps?sender=${encodeURIComponent(sender)}&receiver=${encodeURIComponent(receiver)}`);
      return;
    }
    const t = String(form.per_day.value).trim();
    if (!/^\d+$/.test(t)) throw new Error('Tasks per day: a whole number.');
    await put('/v2/task-caps', {sender, receiver, per_day: Number(t)});
  }, budgetReload);
  dlg.classList.add('rd-sheet');
  const form = dlg.querySelector('form');
  if (form.sender) form.sender.onchange = () => { form.receiver.innerHTML = managerOptions(form.sender.value); };
  if (form.nocap) form.nocap.onchange = () => { form.per_day.disabled = form.nocap.checked; };
}
