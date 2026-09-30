/* ui/app/usage.js — Usage page: estimated model spend per bot
   Classic script: its globals are shared with the other files under ui/app/, loaded in the order index.html lists them. */
'use strict';

// ----------------------------------------------------------------- usage
// GET /api/v2/usage (backend/usage.py, docs/usage.md): tokens each run used, priced at list price. Days are UTC.
// A run on a ChatGPT or Claude sign-in is not spend: its figure is "API-equivalent" and stays apart.
const USE_RANGES = [['today', 'Today'], ['7d', '7 days'], ['30d', '30 days'], ['month', 'This month'], ['custom', 'Custom']];
let USE = null;
const useDay = date => date.toISOString().slice(0, 10);
const useAdd = (day, n) => useDay(new Date(Date.parse(day + 'T00:00:00Z') + n * 864e5));
function useSpan(range, custom) {
  const today = useDay(new Date());
  if (range === 'today') return {from: today, to: today};
  if (range === '30d') return {from: useAdd(today, -29), to: today};
  if (range === 'month') return {from: today.slice(0, 8) + '01', to: today};
  if (range === 'custom' && custom?.from && custom?.to) return {from: custom.from, to: custom.to};
  return {from: useAdd(today, -6), to: today};
}
function useMoney(n) {
  if (n == null) return '—';
  if (n > 0 && n < 0.01) return '<$0.01';
  return '$' + n.toLocaleString(undefined, n >= 100 ? {maximumFractionDigits: 0} : {minimumFractionDigits: 2, maximumFractionDigits: 2});
}
function useCount(n) {
  n = n || 0;
  if (n < 1000) return String(n);
  if (n < 1e6) return (n / 1e3).toFixed(n < 1e4 ? 1 : 0).replace(/\.0$/, '') + 'K';
  return (n / 1e6).toFixed(n < 1e7 ? 2 : 1).replace(/\.?0+$/, '') + 'M';
}
const useTokens = r => (r.input_tokens || 0) + (r.cached_tokens || 0) + (r.output_tokens || 0);
const useSpend = r => (r.est_cost_usd || 0) + (r.subscription_equiv_usd || 0);
const useRuns = n => `${n} run${n === 1 ? '' : 's'}`;
// The estimate, or a dash for tokens on a model with no list price; a subscription's figure beside it, never in it.
function useCost(r) {
  const sub = r.subscription_equiv_usd > 0 ? `<span class="use-sub">≈ ${useMoney(r.subscription_equiv_usd)} API-equivalent</span>` : '';
  const est = r.est_cost_usd == null ? '—' : r.est_cost_usd > 0 || !sub ? useMoney(r.est_cost_usd) : '';
  return (est ? `<span class="use-est">${est}</span>` : '') + sub;
}
function useSaved() {
  try { return JSON.parse(localStorage.getItem('tico.usage') || '{}') || {}; } catch { return {}; }
}
function useSave() {
  try { localStorage.setItem('tico.usage', JSON.stringify({range: USE.range, department: USE.department})); } catch {}
}

function pageUsage() {
  const saved = useSaved();
  const span = useSpan('7d');
  const state = USE = {range: USE_RANGES.some(r => r[0] === saved.range) && saved.range !== 'custom' ? saved.range : '7d',
                       department: saved.department || '', custom: {from: span.from, to: span.to}, open: '', data: null, load: 0};
  $('#main').innerHTML = `<div class="use-page">
    <div class="use-head"><h1>Usage</h1></div>
    <div class="use-bar-row">
      <div class="use-seg" role="tablist" aria-label="Range">${USE_RANGES.map(([k, label]) =>
        `<button type="button" role="tab" data-use-range="${k}" aria-selected="${k === state.range}">${label}</button>`).join('')}</div>
      <select id="use-dept" aria-label="Department" hidden></select>
      <span class="use-custom" hidden><input type="date" id="use-from" aria-label="From"><input type="date" id="use-to" aria-label="To"></span>
    </div>
    <div id="use-body" aria-live="polite"></div>
  </div>`;
  const main = $('#main');
  main.querySelector('.use-seg').onclick = ev => {
    const b = ev.target.closest('[data-use-range]'); if (!b || b.dataset.useRange === state.range) return;
    state.range = b.dataset.useRange; state.open = ''; useSave(); useLoad();
  };
  $('#use-dept').onchange = ev => { state.department = ev.target.value; state.open = ''; useSave(); useLoad(); };
  $('#use-from').onchange = $('#use-to').onchange = () => {
    state.custom = {from: $('#use-from').value, to: $('#use-to').value};
    if (state.custom.from && state.custom.to && state.custom.from <= state.custom.to) { state.open = ''; useLoad(); }
  };
  $('#use-body').onclick = ev => {
    const line = ev.target.closest('.use-line');
    if (line) return void useOpen(line.closest('.use-row').dataset.bot);
    if (ev.target.closest('[data-use-csv]')) useCsv();
  };
  useLoad();
}

const useParams = (state, extra) => {
  const {from, to} = useSpan(state.range, state.custom);
  const q = new URLSearchParams({from, to, ...extra});
  return {from, to, query: q.toString()};
};

async function useLoad() {
  const state = USE; if (!state || !$('#use-body')) return;
  const mine = ++state.load, range = useParams(state, state.department ? {department: state.department} : {});
  $('#use-body').setAttribute('aria-busy', 'true');
  // Controls first, so a switch shows at once while the numbers load.
  for (const b of $('#main').querySelectorAll('[data-use-range]')) b.setAttribute('aria-selected', String(b.dataset.useRange === state.range));
  $('#main').querySelector('.use-custom').hidden = state.range !== 'custom';
  $('#use-from').value = range.from; $('#use-to').value = range.to;
  let data;
  try { data = await get('/v2/usage?' + range.query); }
  catch (e) { if (USE === state && mine === state.load) $('#use-body').innerHTML = `<div class="err">${esc(e.message)}</div>`; return; }
  if (USE !== state || mine !== state.load) return;      // a newer switch is already loading
  state.data = data;
  const select = $('#use-dept');
  select.innerHTML = `<option value="">All departments</option>` + (data.departments || []).map(d =>
    `<option value="${esc(d)}"${d === state.department ? ' selected' : ''}>${esc(d)}</option>`).join('');
  select.hidden = !(data.departments || []).length;
  usePaint();
}

function usePaint() {
  const state = USE, data = state.data, body = $('#use-body');
  body.removeAttribute('aria-busy');
  const rows = [...(data.rows || [])].sort((a, b) => useSpend(b) - useSpend(a) || useTokens(b) - useTokens(a) || b.runs - a.runs);
  if (!rows.length) { body.innerHTML = '<div class="empty">No usage yet.</div>'; return; }
  const t = data.totals;
  const top = Math.max(...rows.map(useSpend), 0);
  body.innerHTML = `<div class="use-total"><span class="use-note">Estimated</span>
      <strong id="use-total">${t.est_cost_usd == null ? '—' : useMoney(t.est_cost_usd)}</strong> · ${useRuns(t.runs)}
      ${t.subscription_equiv_usd > 0 ? `<div class="use-sub">≈ ${useMoney(t.subscription_equiv_usd)} API-equivalent on subscriptions</div>` : ''}</div>
    <ul class="use-list">${rows.map(r => `<li class="use-row" data-bot="${esc(r.bot)}">
      <button type="button" class="use-line" aria-expanded="${state.open === r.bot}">
        <span class="use-who">${botAvatar(r.bot, 28)}<span class="use-name">${esc(r.name || r.bot)}</span></span>
        <span class="use-runs tnum">${useRuns(r.runs)}</span>
        <span class="use-tok tnum">${useCount(useTokens(r))} tokens</span>
        <span class="use-cost tnum">${useCost(r)}</span>
        <span class="use-share" role="img" aria-label="${Math.round((r.share || 0) * 100)}% of the total"><i style="width:${top ? Math.max(useSpend(r) ? 2 : 0, Math.round(100 * useSpend(r) / top)) : 0}%"></i></span>
      </button>
      <div class="use-detail" ${state.open === r.bot ? '' : 'hidden'}></div></li>`).join('')}</ul>`;
  if (state.open) void useDetail(state.open);
}

function useOpen(slug) {
  const state = USE;
  state.open = state.open === slug ? '' : slug;
  for (const row of $('#use-body').querySelectorAll('.use-row')) {
    const on = row.dataset.bot === state.open;
    row.querySelector('.use-line').setAttribute('aria-expanded', String(on));
    row.querySelector('.use-detail').hidden = !on;
  }
  if (state.open) void useDetail(slug);
}

async function useDetail(slug) {
  const state = USE, row = $('#use-body').querySelector(`.use-row[data-bot="${CSS.escape(slug)}"]`);
  if (!row) return;
  const host = row.querySelector('.use-detail');
  host.innerHTML = '<div class="muted">Loading…</div>';
  let data;
  try { data = await get('/v2/usage?' + useParams(state, {bot: slug}).query); }
  catch (e) { if (USE === state) host.innerHTML = `<div class="err">${esc(e.message)}</div>`; return; }
  if (USE !== state || state.open !== slug) return;
  state.detail = data;
  const days = data.daily || [], peak = Math.max(...days.map(useSpend), 0);
  const both = days.some(d => d.subscription_equiv_usd > 0) && days.some(d => d.est_cost_usd > 0);
  const bars = days.map(d => {
    const api = d.est_cost_usd || 0, sub = d.subscription_equiv_usd || 0;
    const h = v => peak ? (100 * v / peak).toFixed(1) : 0;
    const tip = `${d.day} · ${useMoney(api + sub || (d.est_cost_usd == null ? null : 0))} · ${useRuns(d.runs)}`;
    return `<span class="use-col" title="${esc(tip)}" data-day="${esc(d.day)}">${api ? `<i class="use-api" style="height:${h(api)}%"></i>` : ''}${sub ? `<i class="use-subs" style="height:${h(sub)}%"></i>` : ''}</span>`;
  }).join('');
  const routines = (data.routines || []).filter(r => r.runs);
  host.innerHTML = `<div class="use-chart" role="img" aria-label="Daily estimated spend, ${esc(days[0]?.day || '')} to ${esc(days[days.length - 1]?.day || '')}">${bars}</div>
    <div class="use-axis"><span>${esc(days[0]?.day || '')}</span><span>${peak ? useMoney(peak) + ' a day at most' : ''}</span><span>${esc(days[days.length - 1]?.day || '')}</span></div>
    ${both ? `<div class="use-key"><span><i class="use-api"></i>Spend</span><span><i class="use-subs"></i>API-equivalent</span></div>` : ''}
    <table class="use-routines"><thead><tr><th>Routine</th><th>Runs</th><th>Estimate</th></tr></thead><tbody>${routines.map(r =>
      `<tr><td>${esc(r.title)}</td><td class="tnum">${r.runs}</td><td class="tnum"><span class="use-cost">${useCost(r)}</span></td></tr>`).join('')
      || '<tr><td colspan="3" class="muted">No routines.</td></tr>'}</tbody></table>
    <button type="button" class="ghost" data-use-csv>Export CSV</button>`;
}

// The open bot's days as a CSV, in the units the API returns.
function useCsv() {
  const data = USE?.detail; if (!data) return;
  const head = ['day', 'runs', 'input_tokens', 'cached_tokens', 'output_tokens', 'est_cost_usd', 'subscription_equiv_usd'];
  const cell = v => v == null ? '' : String(v);
  const text = [head.join(','), ...(data.daily || []).map(d => head.map(k => cell(d[k])).join(','))].join('\n') + '\n';
  const link = document.createElement('a');
  link.href = URL.createObjectURL(new Blob([text], {type: 'text/csv'}));
  link.download = `usage-${data.bot}-${data.from}-${data.to}.csv`;
  document.body.appendChild(link); link.click(); link.remove();
  setTimeout(() => URL.revokeObjectURL(link.href), 1000);
}
