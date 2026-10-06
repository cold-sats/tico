/* ui/app/task-stats.js — Task stats: how tasks moved through their statuses or steps over time
   Classic script: its globals are shared with the other files under ui/app/, loaded in the order index.html lists them. */
'use strict';

// Read from the status and step changes the hub already records (`/v2/tasks/flow`); nothing is
// snapshotted. A tile picks the stage charted by day; the filters narrow every number at once.
const FLOW_STAGES = [['created', 'New'], ['doing', 'Started'], ['waiting', 'Waiting'], ['review', 'In review'],
  ['ready', 'Ready'], ['done', 'Done'], ['closed', 'Closed'], ['declined', 'Declined'], ['open', 'Reopened']];
const FLOW_ALWAYS = ['created', 'doing', 'waiting', 'done', 'closed'];
const FLOW_SPAN_WORD = {open: 'Before start', doing: 'Started', waiting: 'Waiting', review: 'In review',
  ready: 'Ready', done: 'Done, before close', declined: 'Declined'};
const flowHours = h => h == null ? '' : h < 1 ? `${Math.max(1, Math.round(h * 60))}m`
  : h < 48 ? `${h.toFixed(h < 10 ? 1 : 0)}h` : `${(h / 24).toFixed(1)}d`;
const flowDay = day => new Date(day + 'T12:00:00').toLocaleDateString(undefined, {month: 'short', day: 'numeric'});
const flowLabelKey = l => typeof l === 'string' ? l : l?.key || l?.name || '';
let FLOW_ST = null;

function taskStatsOpen(tasks) {
  let d = $('#task-stats-dialog');
  if (!d) {
    d = document.createElement('dialog');
    d.id = 'task-stats-dialog'; d.className = 'tmodal task-stats'; d.setAttribute('aria-label', 'Task stats');
    document.body.appendChild(d);
    d.addEventListener('close', () => { FLOW_ST = null; });
  }
  const owners = tasks?.filters?.owner || [];
  const labels = [...new Set((tasks?.labels || []).map(flowLabelKey).filter(Boolean))];
  const st = FLOW_ST = {days: 30, type: tasks?.type && tasks.type !== 'general' ? tasks.type : '',
    owner: owners.length === 1 ? owners[0] : '', kind: '', label: '', recurring: '', stage: 'done', data: null, seq: 0};
  try {
    const saved = JSON.parse(localStorage.getItem('tico.tasks.stats') || '{}');
    if ([7, 30, 90].includes(saved.days)) st.days = saved.days;
    if (saved.stage) st.stage = saved.stage;
  } catch {}
  const types = (TASK_TYPES || []).filter(t => t.id !== 'general');
  d.innerHTML = `<div class="tmodal-head"><strong class="who">Task stats</strong><span class="spacer"></span>
      <button class="ghost tmodal-x" type="button" data-close aria-label="Close">✕</button></div>
    <div class="flow-filters">
      <div class="flow-days" data-flow-days role="group" aria-label="Range">${[7, 30, 90].map(n =>
        `<button type="button" data-days="${n}">${n}d</button>`).join('')}</div>
      ${types.length ? `<select data-flow="type" aria-label="Type"><option value="">Statuses</option>${types.map(t =>
        `<option value="${esc(t.id)}">${esc(t.name)}</option>`).join('')}</select>` : ''}
      <select data-flow="owner" aria-label="Owner"><option value="">Anyone</option>${taskOwnerOptions('').replace('<option value="">Who is this for?</option>', '')}</select>
      <select data-flow="kind" aria-label="Owner kind"><option value="">Bots and humans</option><option value="bot">Bots</option><option value="human">Humans</option></select>
      ${labels.length ? `<select data-flow="label" aria-label="Label"><option value="">Any label</option>${labels.map(l =>
        `<option value="${esc(l)}">${esc(l)}</option>`).join('')}</select>` : ''}
      <select data-flow="recurring" aria-label="Recurring"><option value="">Any task</option><option value="false">One-off</option><option value="true">Recurring</option></select>
    </div>
    <div class="tmodal-body" data-flow-body><div class="empty">Loading…</div></div>`;
  d.querySelector('[data-close]').onclick = () => d.close();
  for (const sel of d.querySelectorAll('select[data-flow]')) {
    const key = sel.dataset.flow;
    sel.value = st[key] || '';
    if (sel.value !== (st[key] || '')) sel.value = '';
    st[key] = sel.value;
    sel.onchange = () => { st[key] = sel.value; taskStatsLoad(); };
  }
  d.querySelector('[data-flow-days]').onclick = ev => {
    const b = ev.target.closest('[data-days]'); if (!b) return;
    st.days = Number(b.dataset.days); taskStatsRemember(); taskStatsLoad();
  };
  if (!d.open) d.showModal();
  taskStatsLoad();
}
function taskStatsRemember() {
  try { localStorage.setItem('tico.tasks.stats', JSON.stringify({days: FLOW_ST.days, stage: FLOW_ST.stage})); } catch {}
}
async function taskStatsLoad() {
  const st = FLOW_ST, d = $('#task-stats-dialog'); if (!st || !d) return;
  for (const b of d.querySelectorAll('[data-days]')) {
    const on = Number(b.dataset.days) === st.days;
    b.classList.toggle('cur', on); b.setAttribute('aria-pressed', String(on));
  }
  const q = new URLSearchParams({days: st.days, tz: -new Date().getTimezoneOffset()});
  if (st.type) q.set('type', st.type);
  if (st.owner) q.set('owner', st.owner);
  if (st.kind) q.set('owner_kind', st.kind);
  if (st.label) q.set('label', st.label);
  if (st.recurring) q.set('recurring', st.recurring);
  const seq = ++st.seq;
  const data = await v2Get('/v2/tasks/flow?' + q);
  if (FLOW_ST !== st || st.seq !== seq) return;
  st.data = data;
  taskStatsRender();
}
// Every day in the range, oldest first, with zeros where nothing happened.
function flowDays(data, days) {
  const byDay = new Map((data.days || []).map(r => [r.day, r]));
  const out = [], end = new Date();
  for (let i = days - 1; i >= 0; i--) {
    const at = new Date(end.getFullYear(), end.getMonth(), end.getDate() - i);
    const key = `${at.getFullYear()}-${String(at.getMonth() + 1).padStart(2, '0')}-${String(at.getDate()).padStart(2, '0')}`;
    out.push({day: key, ...(byDay.get(key) || {})});
  }
  return out;
}
function flowChartHTML(rows, stage, word) {
  const W = 640, H = 170, left = 30, bottom = 20, top = 8, plotH = H - top - bottom, plotW = W - left - 4;
  const max = Math.max(1, ...rows.map(r => r[stage] || 0));
  const unit = max > 20 ? 5 : 1, step = max <= 4 ? 1 : Math.ceil(max / 4 / unit) * unit;
  const ticks = []; for (let v = 0; v < max + step; v += step) ticks.push(v);
  const yMax = ticks[ticks.length - 1];
  const slot = plotW / rows.length, bw = Math.max(2, Math.min(28, slot - 2));
  const y = v => top + plotH - (v / yMax) * plotH;
  const grid = ticks.map(v => `<line class="flow-grid" x1="${left}" x2="${W - 4}" y1="${y(v)}" y2="${y(v)}"/>
    <text class="flow-axis" x="${left - 6}" y="${y(v) + 3.5}" text-anchor="end">${v}</text>`).join('');
  const bars = rows.map((r, i) => {
    const v = r[stage] || 0, x = left + i * slot + (slot - bw) / 2, h = (v / yMax) * plotH, rad = Math.min(4, bw / 2, h);
    const tip = `${flowDay(r.day)}: ${v} ${word.toLowerCase()}`;
    const mark = v ? `<path class="flow-bar" d="M${x},${top + plotH} v${-(h - rad)} q0,${-rad} ${rad},${-rad} h${bw - 2 * rad} q${rad},0 ${rad},${rad} v${h - rad} z"/>` : '';
    return `<g class="flow-col" data-tip="${esc(tip)}"><rect class="flow-hit" x="${left + i * slot}" y="${top}" width="${slot}" height="${plotH}"/>${mark}<title>${esc(tip)}</title></g>`;
  }).join('');
  const marks = [...new Set([0, Math.floor((rows.length - 1) / 2), rows.length - 1])];
  const xs = marks.map(i => `<text class="flow-axis" x="${left + i * slot + slot / 2}" y="${H - 5}" text-anchor="${i === 0 ? 'start' : i === rows.length - 1 ? 'end' : 'middle'}">${esc(flowDay(rows[i].day))}</text>`).join('');
  return `<svg class="flow-chart" viewBox="0 0 ${W} ${H}" role="img" aria-label="${esc(word)} per day">${grid}${bars}${xs}</svg>`;
}
// The stages on offer: a type's own steps when one is picked, else the statuses that matter here.
function flowStages(data, current) {
  const totals = data.totals || {};
  if ((data.steps || []).length) return [['created', 'New'], ...data.steps.map(s => ['step:' + s.id, s.name])];
  return FLOW_STAGES.filter(([k]) => FLOW_ALWAYS.includes(k) || totals[k] || k === current);
}
function taskStatsRender() {
  const st = FLOW_ST, body = $('#task-stats-dialog [data-flow-body]'); if (!st || !body) return;
  const data = st.data;
  if (!data) { body.innerHTML = '<div class="empty">Stats did not load. Try again.</div>'; return; }
  const totals = data.totals || {};
  const stages = flowStages(data, st.stage);
  if (!stages.some(([k]) => k === st.stage)) st.stage = stages.find(([k]) => k === 'done' || /^step:/.test(k))?.[0] || 'created';
  const word = (stages.find(([k]) => k === st.stage) || [])[1] || st.stage;
  const tiles = stages.map(([k, label]) => `<button type="button" class="flow-tile${k === st.stage ? ' cur' : ''}" data-stage="${esc(k)}" aria-pressed="${k === st.stage}">
      <span class="flow-tile-n tnum">${totals[k] || 0}</span><span class="flow-tile-l">${esc(label)}</span></button>`).join('');
  const spanNames = (data.steps || []).length ? stages.filter(([k]) => k !== 'created') : Object.entries(FLOW_SPAN_WORD);
  const spanRows = spanNames.map(([k, label]) => [label, (data.stages || {})[k]]).filter(([, v]) => v?.n)
    .map(([label, v]) => `<tr><td>${esc(label)}</td><td class="tnum">${flowHours(v.median_hours)}</td><td class="tnum">${flowHours(v.p90_hours)}</td><td class="tnum muted">${v.n}</td></tr>`).join('');
  // By owner: New, then Done and Closed, or for a type the picked step (its last one while New is picked).
  const stepMode = (data.steps || []).length > 0;
  const cols = stepMode ? [stages.find(([k]) => k === st.stage && k !== 'created') || stages[stages.length - 1]]
    : [['done', 'Done'], ['closed', 'Closed']];
  const peopleRows = (data.people || []).slice(0, 12).map(p => `<tr data-owner="${esc(actorSlug(p.actor) || p.actor)}" tabindex="0">
      <td>${esc(actorLabel(p.actor))}</td><td class="tnum">${p.created || 0}</td>${cols.map(([k]) => `<td class="tnum">${p[k] || 0}</td>`).join('')}</tr>`).join('');
  body.innerHTML = `<div class="flow-tiles" role="group" aria-label="Stage">${tiles}</div>
    <div class="flow-chart-head"><strong>${esc(word)} per day</strong><span class="muted tnum" data-flow-tip></span></div>
    ${flowChartHTML(flowDays(data, st.days), st.stage, word)}
    <div class="flow-tables">
      <section><h3>Time in stage</h3>${spanRows ? `<table class="flow-table"><thead><tr><th></th><th>Median</th><th>90%</th><th>Tasks</th></tr></thead><tbody>${spanRows}</tbody></table>` : '<div class="empty">No stage finished in this range.</div>'}</section>
      <section><h3>By owner</h3>${peopleRows ? `<table class="flow-table flow-people"><thead><tr><th></th><th>New</th>${cols.map(([, label]) => `<th>${esc(label)}</th>`).join('')}</tr></thead><tbody>${peopleRows}</tbody></table>` : '<div class="empty">Nothing moved in this range.</div>'}</section>
    </div>`;
  body.querySelector('.flow-tiles').onclick = ev => {
    const b = ev.target.closest('[data-stage]'); if (!b) return;
    st.stage = b.dataset.stage; taskStatsRemember(); taskStatsRender();
  };
  const tip = body.querySelector('[data-flow-tip]'), chart = body.querySelector('.flow-chart');
  chart.onpointerover = ev => { const g = ev.target.closest('.flow-col'); tip.textContent = g ? g.dataset.tip : ''; };
  chart.onpointerleave = () => { tip.textContent = ''; };
  const people = body.querySelector('.flow-people');
  if (people) {
    const pick = row => {
      const sel = $('#task-stats-dialog select[data-flow="owner"]');
      if (!row || !sel || ![...sel.options].some(o => o.value === row.dataset.owner)) return;
      sel.value = st.owner = row.dataset.owner; taskStatsLoad();
    };
    people.onclick = ev => pick(ev.target.closest('tr[data-owner]'));
    people.onkeydown = ev => { if (ev.key === 'Enter') pick(ev.target.closest('tr[data-owner]')); };
  }
}
