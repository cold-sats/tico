/* Strategy: how the team means to win (backend/strategy.py). A summary and a vision, the choices the team lives by (the
   framework names them: Bets, Guiding policy, Strategies...), each with the goals that serve it and their colours, then
   the framework's sections. The owner edits the draft in place and publishes numbered versions with a note; everyone
   else reads the latest published version. Market (ui/market-page.js) is the section's second tab. */
'use strict';
let STRAT = null;          // the open page: {data, load, editChoice, editSection, publishing}
let STRAT_LOAD = 0;
const isStrategyRoute = r => r === '#/strategy' || r.startsWith('#/strategy?');
const STRAT_STATUS = {proposed: 'Proposed', active: 'Active', retired: 'Retired'};

// The heading and the two tabs, the same on both, so switching tabs never moves them.
window.strategyHeadHtml = function strategyHeadHtml(tab) {
  const link = (id, href, label) => `<a href="${href}" data-strat-tab="${id}"${tab === id ? ' class="cur" aria-current="page"' : ''}>${label}</a>`;
  return `<div class="strat-head"><h1>Strategy</h1>
      <nav class="tabs slim strat-tabs" aria-label="Strategy">${link('strategy', '#/strategy', 'Strategy')}${link('market', MARKET_ROUTE, 'Market')}</nav>
      <span class="spacer"></span><div class="strat-actions" id="strat-actions"></div></div>`;
};

window.strategyStop = function strategyStop() {
  STRAT_LOAD++;
  STRAT = null;
  const dlg = document.getElementById('strat-versions');
  if (dlg?.open) dlg.close();
};

window.pageStrategy = async function pageStrategy() {
  const load = ++STRAT_LOAD;
  const main = $('#main');
  main.classList.add('strategy-layout');
  main.innerHTML = strategyHeadHtml('strategy') + `<div id="strat-body" class="strat-body">${skelRows(6, {dot: false})}</div>`;
  let data;
  try { data = await get('/v2/strategy', {fresh: true}); }
  catch (error) {
    if (load === STRAT_LOAD && $('#strat-body')) $('#strat-body').innerHTML = `<p class="err">${esc(error.message || 'Could not load the strategy')}</p>`;
    return;
  }
  if (load !== STRAT_LOAD) return;
  STRAT = {data, load, editChoice: '', editSection: '', publishing: false};
  strategyRender();
  // #/strategy?choice=<id> (a goal's choice link) scrolls to that choice.
  const choice = new URLSearchParams(S.route.split('?')[1] || '').get('choice');
  const row = choice && document.querySelector(`[data-choice="${CSS.escape(choice)}"]`);
  if (row) { row.scrollIntoView({block: 'center'}); row.classList.add('strat-flash'); }
};

// Only the owner writes; the server may say otherwise (may_edit) and is the one that enforces it.
const strategyMayEdit = data => data?.may_edit ?? S.me?.role === 'owner';
const stratText = s => String(s ?? '').trim();
const stratRank = (a, b) => (a.rank ?? 1e9) - (b.rank ?? 1e9);
function strategyBlank(version, choices = []) {
  return !version || (!stratText(version.summary) && !stratText(version.vision)
    && !Object.values(version.sections || {}).some(stratText) && !choices.length);
}
function strategyFramework(data, id) {
  const all = data.frameworks || [];
  return all.find(f => f.id === id) || all.find(f => f.id === 'plain') || all[0] || {id: id || 'plain', name: 'Plain', choices_label: 'Bets', sections: []};
}
// What the reader sees: the owner the draft and the live choices; everyone else the latest published version and its
// snapshot of the choices.
function strategyView(data) {
  const owner = strategyMayEdit(data);
  const version = owner ? data.draft || data.current : data.current;
  const choices = (owner ? data.choices : version?.choices) || [];
  const fw = strategyFramework(data, version?.framework);
  return {owner, version, choices: choices.slice().sort(stratRank), fw, label: fw.choices_label || data.label || 'Bets'};
}
// Whether the draft says anything the latest published version does not: its words, its framework, or its choices.
function strategyDiffers(data) {
  const a = data.draft, b = data.current;
  if (!b) return !strategyBlank(a, data.choices || []);
  if (!a) return false;
  if ((a.framework || '') !== (b.framework || '') || stratText(a.summary) !== stratText(b.summary) || stratText(a.vision) !== stratText(b.vision)) return true;
  const keys = new Set([...Object.keys(a.sections || {}), ...Object.keys(b.sections || {})]);
  for (const key of keys) if (stratText(a.sections?.[key]) !== stratText(b.sections?.[key])) return true;
  const sig = list => (list || []).slice().sort(stratRank)
    .map(c => [c.id, stratText(c.statement), stratText(c.why), stratText(c.rules_out), c.status].join('\u0001')).join('\u0002');
  return sig(data.choices) !== sig(b.choices);
}

function strategyStatusHtml(data, view) {
  if (!view.owner) return '';
  const d = data.draft, by = d?.updated_by ? ` · ${esc(goalActorName(d.updated_by))}${d.updated ? ' ' + esc(ago(d.updated)) : ''}` : '';
  if (data.current && strategyDiffers(data)) return `<p class="strat-status" data-strat-status>Draft differs from v${esc(data.current.n)}${by}</p>`;
  if (!data.current && !strategyBlank(d, data.choices || [])) return `<p class="strat-status" data-strat-status>Not published${by}</p>`;
  return '';
}

function strategyActionsHtml(data, view) {
  const versions = data.current ? '<button class="ghost" type="button" data-strat-versions>Versions</button>' : '';
  if (!view.owner) return versions;
  const frameworks = data.frameworks || [];
  const picker = frameworks.length > 1 ? `<label class="strat-fw"><span class="sr-only">Framework</span><select data-strat-framework aria-label="Framework">${frameworks.map(f =>
    `<option value="${esc(f.id)}"${f.id === view.fw.id ? ' selected' : ''}>${esc(f.name)}</option>`).join('')}</select></label>` : '';
  const can = strategyDiffers(data);
  return `${picker}${versions}<button class="primary" type="button" data-strat-publish${can ? '' : ' disabled title="Nothing new to publish"'}>Publish</button>`;
}

function strategyPublishHtml() {
  return `<form class="strat-publish" data-strat-publish-form novalidate>
      <input type="text" name="note" maxlength="200" autocomplete="off" placeholder="What changed" aria-label="What changed" required>
      <button class="primary" type="submit">Publish</button><button class="ghost" type="button" data-strat-publish-cancel>Cancel</button></form>`;
}

// Summary and vision: the owner's are fields that save when left, or on Enter.
function strategyFieldHtml(key, title, value, owner, placeholder) {
  const body = owner
    ? `<textarea class="strat-field" data-strat-field="${key}" rows="2" maxlength="400" placeholder="${esc(placeholder)}" aria-label="${esc(title)}">${esc(value || '')}</textarea>`
    : value ? `<p class="strat-text">${esc(value)}</p>` : '';
  if (!body) return '';
  return `<section class="strat-sec strat-${key}" id="strat-sec-${key}"><h2 class="strat-k">${esc(title)}</h2>${body}</section>`;
}

function strategyGoalsHtml(goals) {
  if (!goals?.length) return '';
  return `<ul class="strat-goals" aria-label="Goals">${goals.map(g =>
    `<li><a href="${GOALS}/${encodeURIComponent(g.id)}">${gdot(g.colour)}<span>${esc(g.title)}</span></a></li>`).join('')}</ul>`;
}

function strategyChoiceFormHtml(c = {}) {
  const status = c.status || 'active';
  return `<form class="strat-choice-form" data-choice-form="${esc(c.id || 'new')}" novalidate>
      <label class="goal-f"><span>Statement</span><input type="text" name="statement" maxlength="300" autocomplete="off" value="${esc(c.statement || '')}" required></label>
      <label class="goal-f"><span>Why</span><textarea name="why" rows="2" maxlength="1000">${esc(c.why || '')}</textarea></label>
      <label class="goal-f"><span>Rules out</span><textarea name="rules_out" rows="2" maxlength="1000">${esc(c.rules_out || '')}</textarea></label>
      <label class="goal-f strat-choice-status"><span>Status</span><select name="status">${Object.entries(STRAT_STATUS).map(([v, label]) =>
        `<option value="${v}"${v === status ? ' selected' : ''}>${label}</option>`).join('')}</select></label>
      <div class="goal-actions"><button class="primary" type="submit">Save</button><button class="ghost" type="button" data-choice-cancel>Cancel</button></div></form>`;
}

function strategyChoiceHtml(c, n, view, data, live) {
  if (view.owner && STRAT?.editChoice === c.id) return `<li class="strat-choice" data-choice="${esc(c.id)}">${strategyChoiceFormHtml(c)}</li>`;
  const move = view.owner && c.status !== 'retired' ? `<button class="ghost strat-mini" type="button" data-choice-up${n === 0 ? ' disabled' : ''} aria-label="Move up" title="Move up">↑</button>
      <button class="ghost strat-mini" type="button" data-choice-down${n === live - 1 ? ' disabled' : ''} aria-label="Move down" title="Move down">↓</button>` : '';
  const tools = view.owner ? `<span class="strat-choice-tools">${move}<button class="ghost strat-mini" type="button" data-choice-edit>Edit</button></span>` : '';
  return `<li class="strat-choice strat-${esc(c.status || 'active')}" data-choice="${esc(c.id)}">
      <div class="strat-choice-top">${c.status === 'retired' ? '' : `<span class="strat-choice-n tnum" aria-hidden="true">${n + 1}</span>`}<span class="strat-choice-st">${esc(c.statement)}</span>
        <span class="pill strat-pill ${esc(c.status || 'active')}">${STRAT_STATUS[c.status] || 'Active'}</span>${tools}</div>
      ${stratText(c.why) ? `<p class="strat-choice-line"><span class="strat-choice-k">Why</span>${esc(c.why)}</p>` : ''}
      ${stratText(c.rules_out) ? `<p class="strat-choice-line"><span class="strat-choice-k">Rules out</span>${esc(c.rules_out)}</p>` : ''}
      ${strategyGoalsHtml((data.goals_by_choice || {})[c.id])}</li>`;
}

function strategyChoicesHtml(data, view) {
  const live = view.choices.filter(c => c.status !== 'retired'), retired = view.choices.filter(c => c.status === 'retired');
  if (!view.owner && !view.choices.length) return '';
  const adding = view.owner && STRAT?.editChoice === 'new';
  return `<section class="strat-sec strat-choices-sec" id="strat-sec-choices" aria-labelledby="strat-choices-h">
      <div class="strat-sec-head"><h2 class="strat-k" id="strat-choices-h">${esc(view.label)}</h2><span class="cnt tnum">${live.length || ''}</span>
        ${view.owner && !adding ? '<button class="ghost strat-mini" type="button" data-choice-add>Add</button>' : ''}</div>
      ${live.length ? `<ol class="strat-choices">${live.map((c, n) => strategyChoiceHtml(c, n, view, data, live.length)).join('')}</ol>`
        : adding ? '' : `<p class="muted strat-empty">None yet</p>`}
      ${adding ? `<div class="strat-choice strat-choice-new">${strategyChoiceFormHtml()}</div>` : ''}
      ${retired.length ? `<details class="strat-retired"><summary>Retired <span class="cnt tnum">${retired.length}</span></summary>
        <ol class="strat-choices">${retired.map((c, n) => strategyChoiceHtml(c, n, view, data, retired.length)).join('')}</ol></details>` : ''}
    </section>`;
}

function strategySectionsHtml(view) {
  const sections = view.version?.sections || {};
  return view.fw.sections.map(sec => {
    const text = sections[sec.key] || '';
    const editing = view.owner && STRAT?.editSection === sec.key;
    if (!view.owner && !stratText(text)) return '';
    const body = editing
      ? `<form class="strat-sec-form" data-section-form="${esc(sec.key)}" novalidate>
          <textarea name="text" rows="8" aria-label="${esc(sec.title)}" placeholder="${esc(sec.prompt || '')}">${esc(text)}</textarea>
          <div class="goal-actions"><button class="primary" type="submit">Save</button><button class="ghost" type="button" data-section-cancel>Cancel</button></div></form>`
      : stratText(text) ? `<div class="md strat-md">${safeMd(text)}</div>` : '<p class="muted strat-empty">Not written</p>';
    return `<section class="strat-sec" id="strat-sec-${esc(sec.key)}" data-section="${esc(sec.key)}">
        <div class="strat-sec-head"><h2 class="strat-k">${esc(sec.title)}</h2>${view.owner && !editing ? `<button class="ghost strat-mini" type="button" data-section-edit>${stratText(text) ? 'Edit' : 'Write'}</button>` : ''}</div>
        ${body}</section>`;
  }).join('');
}

function strategyTocHtml(data, view) {
  const has = key => view.owner || stratText(view.version?.[key]);
  const rows = [...(has('summary') ? [['summary', 'Summary']] : []), ...(has('vision') ? [['vision', 'Vision']] : []),
    ...(view.owner || view.choices.length ? [['choices', view.label]] : []),
    ...view.fw.sections.filter(sec => view.owner || stratText(view.version?.sections?.[sec.key])).map(sec => [sec.key, sec.title])];
  const v = data.current;
  return `<nav class="strat-toc" aria-label="Contents">${rows.map(([key, title]) =>
      `<button type="button" class="strat-toc-link" data-strat-go="${esc(key)}">${esc(title)}</button>`).join('')}
      ${v ? `<p class="strat-toc-v muted">v${esc(v.n)}${v.published ? ` · <time datetime="${esc(v.published)}" title="${esc(fmt(v.published))}">${esc(ago(v.published))}</time>` : ''}</p>` : ''}</nav>`;
}

function strategyRender() {
  const body = $('#strat-body');
  if (!body || !STRAT) return;
  const data = STRAT.data, view = strategyView(data);
  $('#strat-actions').innerHTML = strategyActionsHtml(data, view);
  const blank = !data.current && strategyBlank(data.draft, data.choices || []);
  if (!view.owner && !data.current) { body.innerHTML = '<p class="strat-none">No strategy yet.</p>'; strategyBind(); return; }
  const v = view.version || {};
  // Words typed in Summary or Vision and not yet saved survive a redraw (their save is on its way).
  const typed = [...body.querySelectorAll('[data-strat-field]')].filter(f => f.value !== f.defaultValue).map(f => [f.dataset.stratField, f.value]);
  body.innerHTML = `${STRAT.publishing ? strategyPublishHtml() : ''}${strategyStatusHtml(data, view)}
    <div class="strat-grid">${strategyTocHtml(data, view)}
      <article class="strat-doc" id="strat-doc">${blank ? '<p class="strat-none">No strategy yet.</p>' : ''}
        ${strategyFieldHtml('summary', 'Summary', v.summary, view.owner, 'What the team does, for whom, and how it wins')}
        ${strategyFieldHtml('vision', 'Vision', v.vision, view.owner, 'Where the team is going')}
        ${strategyChoicesHtml(data, view)}
        ${strategySectionsHtml(view)}
      </article></div>`;
  for (const [key, value] of typed) { const f = body.querySelector(`[data-strat-field="${key}"]`); if (f) f.value = value; }
  strategyBind();
}

// Saves, then reads the page again. `quiet` keeps the fields as they are (one may have the focus) and redraws only
// what depends on the draft: the status line and the buttons.
async function strategyWrite(run, {quiet = false, fail = 'Could not save'} = {}) {
  const state = STRAT;
  try { await run(); }
  catch (error) { toast(error.message || fail, true); return false; }
  if (STRAT !== state) return true;
  try { state.data = await get('/v2/strategy', {fresh: true}); } catch { /* the saved words stay as drawn */ }
  if (STRAT !== state) return true;
  if (quiet) {
    const view = strategyView(state.data);
    $('#strat-actions').innerHTML = strategyActionsHtml(state.data, view);
    const old = document.querySelector('[data-strat-status]'), html = strategyStatusHtml(state.data, view);
    if (old) old.outerHTML = html || '';
    else if (html) $('#strat-body .strat-grid')?.insertAdjacentHTML('beforebegin', html);
    strategyBindActions();
  } else strategyRender();
  return true;
}

const stratAutosize = el => { el.style.height = 'auto'; el.style.height = el.scrollHeight + 2 + 'px'; };

function strategyBindActions() {
  const state = STRAT, data = state.data;
  const actions = $('#strat-actions');
  const versions = actions.querySelector('[data-strat-versions]');
  if (versions) versions.onclick = () => void strategyVersionsOpen();
  const publish = actions.querySelector('[data-strat-publish]');
  if (publish) publish.onclick = () => { state.publishing = true; strategyRender(); $('[data-strat-publish-form] input')?.focus(); };
  const picker = actions.querySelector('[data-strat-framework]');
  if (picker) picker.onchange = async () => {
    const next = strategyFramework(data, picker.value), keys = new Set(next.sections.map(s => s.key));
    const now = strategyFramework(data, data.draft?.framework);
    const dropped = now.sections.filter(s => !keys.has(s.key) && stratText(data.draft?.sections?.[s.key]));
    if (dropped.length && !confirm(`${dropped.map(s => s.title).join(', ')} ${dropped.length > 1 ? 'are' : 'is'} not in ${next.name}. Earlier versions keep ${dropped.length > 1 ? 'them' : 'it'}.`)) {
      picker.value = now.id; return;
    }
    picker.disabled = true;
    await strategyWrite(() => put('/v2/strategy/draft', {framework: next.id}), {fail: 'Could not change the framework'});
  };
}

function strategyBind() {
  const state = STRAT, body = $('#strat-body');
  if (!state || !body) return;
  strategyBindActions();
  const data = state.data, view = strategyView(data);

  for (const button of body.querySelectorAll('[data-strat-go]')) button.onclick = () =>
    document.getElementById('strat-sec-' + button.dataset.stratGo)?.scrollIntoView({block: 'start', behavior: 'smooth'});

  const form = body.querySelector('[data-strat-publish-form]');
  if (form) {
    const done = () => { state.publishing = false; strategyRender(); };
    form.querySelector('[data-strat-publish-cancel]').onclick = done;
    form.onkeydown = ev => { if (ev.key === 'Escape') { ev.preventDefault(); done(); } };
    form.onsubmit = async ev => {
      ev.preventDefault();
      const note = form.elements.note.value.trim();
      if (!note) { form.elements.note.focus(); return; }
      form.querySelectorAll('button').forEach(b => { b.disabled = true; });
      let out = null;
      const ok = await strategyWrite(async () => { out = await post('/v2/strategy/publish', {note}); }, {fail: 'Could not publish'});
      if (ok) { state.publishing = false; strategyRender(); toast(`Published v${out?.n ?? out?.version?.n ?? ''}`.trim()); }
      else form.querySelectorAll('button').forEach(b => { b.disabled = false; });
    };
  }

  for (const field of body.querySelectorAll('[data-strat-field]')) {
    const key = field.dataset.stratField;
    stratAutosize(field);
    field.oninput = () => stratAutosize(field);
    // What is saved now: a quiet save reads the draft again without drawing these fields.
    const saved = () => strategyView(state.data).version?.[key] || '';
    field.onkeydown = ev => {
      if (ev.key === 'Enter' && !ev.shiftKey && !ev.isComposing) { ev.preventDefault(); field.blur(); }
      if (ev.key === 'Escape') { field.value = saved(); stratAutosize(field); field.blur(); }
    };
    field.onblur = () => {
      const text = field.value.trim();
      if (STRAT !== state || text === stratText(saved())) return;
      void strategyWrite(() => put('/v2/strategy/draft', {[key]: text}), {quiet: true});
    };
  }

  // The choices: add, edit (status included, so retiring is an edit), and move up or down.
  const add = body.querySelector('[data-choice-add]');
  if (add) add.onclick = () => { state.editChoice = 'new'; strategyRender(); $('[data-choice-form="new"] input')?.focus(); };
  for (const li of body.querySelectorAll('li[data-choice]')) {
    const id = li.dataset.choice;
    const edit = li.querySelector('[data-choice-edit]');
    if (edit) edit.onclick = () => { state.editChoice = id; strategyRender(); $(`[data-choice-form="${CSS.escape(id)}"] input`)?.focus(); };
    for (const [sel, step] of [['[data-choice-up]', -1], ['[data-choice-down]', 1]]) {
      const b = li.querySelector(sel);
      if (b) b.onclick = () => void strategyMove(id, step);
    }
  }
  const cform = body.querySelector('[data-choice-form]');
  if (cform) {
    const id = cform.dataset.choiceForm;
    const done = () => { state.editChoice = ''; strategyRender(); };
    cform.querySelector('[data-choice-cancel]').onclick = done;
    cform.onkeydown = ev => { if (ev.key === 'Escape') { ev.preventDefault(); done(); } };
    cform.onsubmit = async ev => {
      ev.preventDefault();
      const el = cform.elements, statement = el.statement.value.trim();
      if (!statement) { el.statement.focus(); return; }
      const fields = {statement, why: el.why.value.trim(), rules_out: el.rules_out.value.trim(), status: el.status.value};
      const was = (data.choices || []).find(c => c.id === id);
      const change = was ? Object.fromEntries(Object.entries(fields).filter(([k, v]) => v !== (was[k] || ''))) : fields;
      if (was && !Object.keys(change).length) { done(); return; }
      cform.querySelectorAll('button').forEach(b => { b.disabled = true; });
      state.editChoice = '';
      const ok = await strategyWrite(() => post(was ? `/v2/strategy/choices/${encodeURIComponent(id)}` : '/v2/strategy/choices', change));
      if (!ok) { state.editChoice = id; cform.querySelectorAll('button').forEach(b => { b.disabled = false; }); }
    };
  }

  // The sections, one at a time: Save, or Cmd/Ctrl+Enter; Escape leaves it as it was.
  for (const sec of body.querySelectorAll('[data-section]')) {
    const b = sec.querySelector('[data-section-edit]');
    if (b) b.onclick = () => { state.editSection = sec.dataset.section; strategyRender(); const t = $(`[data-section-form="${CSS.escape(sec.dataset.section)}"] textarea`); if (t) { stratAutosize(t); t.focus(); } };
  }
  const sform = body.querySelector('[data-section-form]');
  if (sform) {
    const key = sform.dataset.sectionForm, area = sform.elements.text;
    const done = () => { state.editSection = ''; strategyRender(); };
    stratAutosize(area);
    area.oninput = () => stratAutosize(area);
    sform.querySelector('[data-section-cancel]').onclick = done;
    sform.onkeydown = ev => {
      if (ev.key === 'Escape') { ev.preventDefault(); done(); }
      if (ev.key === 'Enter' && (ev.metaKey || ev.ctrlKey)) { ev.preventDefault(); sform.requestSubmit(); }
    };
    sform.onsubmit = async ev => {
      ev.preventDefault();
      const text = area.value.trim(), now = view.version?.sections || {};
      if (text === stratText(now[key])) { done(); return; }
      // Every section the framework has goes with it, so the server keeps the others whether it merges or replaces.
      const sections = {};
      for (const s of view.fw.sections) if (s.key === key || stratText(now[s.key])) sections[s.key] = s.key === key ? text : now[s.key];
      sform.querySelectorAll('button').forEach(b => { b.disabled = true; });
      state.editSection = '';
      const ok = await strategyWrite(() => put('/v2/strategy/draft', {sections}));
      if (!ok) { state.editSection = key; sform.querySelectorAll('button').forEach(b => { b.disabled = false; }); }
    };
  }
}

// Moving a choice renumbers the live ones 0, 1, 2… and saves only the ranks that changed.
async function strategyMove(id, step) {
  const state = STRAT;
  const live = (state.data.choices || []).filter(c => c.status !== 'retired').sort(stratRank);
  const at = live.findIndex(c => c.id === id), to = at + step;
  if (at < 0 || to < 0 || to >= live.length) return;
  [live[at], live[to]] = [live[to], live[at]];
  await strategyWrite(async () => {
    for (const [rank, c] of live.entries()) if (c.rank !== rank) await post(`/v2/strategy/choices/${encodeURIComponent(c.id)}`, {rank});
  }, {fail: 'Could not move it'});
}

// ---------------------------------------------------------------- versions
// A drawer: the published versions, newest first; one opens read-only; two are compared field by field.
function strategyVersionsDialog() {
  let dlg = document.getElementById('strat-versions');
  if (!dlg) {
    dlg = document.createElement('dialog');
    dlg.id = 'strat-versions'; dlg.className = 'tmodal gpanel strat-versions';
    dlg.setAttribute('aria-label', 'Versions');
    dlg.addEventListener('click', ev => { if (ev.target === dlg) dlg.close(); });
    document.body.appendChild(dlg);
  }
  return dlg;
}
function strategyDrawerHtml(title, inner, back = false) {
  return `<div class="tmodal-head">${back ? '<button class="ghost strat-back" type="button" data-sv-back>‹ Versions</button>' : `<h2>${esc(title)}</h2>`}<span class="spacer"></span>
      <button class="ghost tmodal-x" type="button" data-sv-close aria-label="Close">✕</button></div>
    <div class="tmodal-body strat-sv-body">${inner}</div>`;
}
async function strategyVersionsOpen() {
  const state = STRAT, dlg = strategyVersionsDialog();
  dlg.innerHTML = strategyDrawerHtml('Versions', skelRows(4, {dot: false}));
  dlg.querySelector('[data-sv-close]').onclick = () => dlg.close();
  if (!dlg.open) dlg.showModal();
  let list;
  try { list = await get('/v2/strategy/versions', {fresh: true}); }
  catch (error) { dlg.querySelector('.strat-sv-body').innerHTML = `<p class="err">${esc(error.message)}</p>`; return; }
  if (STRAT !== state || !dlg.open) return;
  const rows = (Array.isArray(list) ? list : list?.versions || []).slice().sort((a, b) => b.n - a.n);
  state.versions = rows;
  strategyVersionsList(dlg, rows);
}
function strategyVersionsList(dlg, rows) {
  const pick = (name, chosen) => `<select name="${name}" aria-label="${name === 'from' ? 'From' : 'To'}">${rows.map(v =>
    `<option value="${esc(v.n)}"${v.n === chosen ? ' selected' : ''}>v${esc(v.n)}</option>`).join('')}</select>`;
  const compare = rows.length > 1 ? `<form class="strat-sv-compare" data-sv-compare novalidate>${pick('from', rows[1].n)}<span class="muted">to</span>${pick('to', rows[0].n)}
      <button class="ghost" type="submit">Compare</button></form>` : '';
  dlg.innerHTML = strategyDrawerHtml('Versions', `${compare}${rows.length ? `<ul class="strat-sv-list">${rows.map(v =>
    `<li><button type="button" class="strat-sv-row" data-sv-open="${esc(v.n)}"><span class="strat-sv-n tnum">v${esc(v.n)}</span><span class="strat-sv-note">${esc(v.note || '')}</span>
      <span class="muted strat-sv-meta">${v.published_by ? esc(goalActorName(v.published_by)) + ' · ' : ''}<time datetime="${esc(v.published || '')}" title="${esc(fmt(v.published))}">${esc(ago(v.published))}</time></span></button></li>`).join('')}</ul>`
    : '<p class="muted">No versions yet.</p>'}`);
  dlg.querySelector('[data-sv-close]').onclick = () => dlg.close();
  for (const b of dlg.querySelectorAll('[data-sv-open]')) b.onclick = () => void strategyVersionShow(dlg, Number(b.dataset.svOpen));
  const form = dlg.querySelector('[data-sv-compare]');
  if (form) form.onsubmit = ev => { ev.preventDefault(); void strategyDiffShow(dlg, Number(form.elements.from.value), Number(form.elements.to.value)); };
}
const strategyVersionGet = n => get(`/v2/strategy/versions/${encodeURIComponent(n)}`).then(v => v?.version || v);
async function strategyDrawerLoad(dlg, run) {
  const state = STRAT;
  dlg.innerHTML = strategyDrawerHtml('', skelRows(5, {dot: false}), true);
  const wire = () => {
    dlg.querySelector('[data-sv-close]').onclick = () => dlg.close();
    dlg.querySelector('[data-sv-back]').onclick = () => strategyVersionsList(dlg, state?.versions || []);
  };
  wire();
  let html;
  try { html = await run(); } catch (error) { html = `<p class="err">${esc(error.message)}</p>`; }
  if (STRAT !== state || !dlg.open) return;
  dlg.querySelector('.strat-sv-body').innerHTML = html;
}
function strategyVersionShow(dlg, n) {
  return strategyDrawerLoad(dlg, async () => {
    const v = await strategyVersionGet(n), data = STRAT.data, fw = strategyFramework(data, v.framework);
    const label = fw.choices_label || data.label || 'Bets';
    const choices = (v.choices || []).slice().sort(stratRank).filter(c => c.status !== 'retired');
    const block = (title, inner) => inner ? `<section class="strat-sv-sec"><h3 class="strat-k">${esc(title)}</h3>${inner}</section>` : '';
    return `<div class="strat-sv-title"><b>v${esc(v.n)}</b>${v.note ? ` · ${esc(v.note)}` : ''}<div class="muted">${esc(fw.name)}${v.published_by ? ' · ' + esc(goalActorName(v.published_by)) : ''}${v.published ? ' · ' + esc(fmt(v.published)) : ''}</div></div>
      ${block('Summary', stratText(v.summary) ? `<p>${esc(v.summary)}</p>` : '')}
      ${block('Vision', stratText(v.vision) ? `<p>${esc(v.vision)}</p>` : '')}
      ${block(label, choices.length ? `<ol class="strat-sv-choices">${choices.map(c => `<li><b>${esc(c.statement)}</b>${stratText(c.why) ? `<div class="muted">${esc(c.why)}</div>` : ''}</li>`).join('')}</ol>` : '')}
      ${fw.sections.map(sec => block(sec.title, stratText(v.sections?.[sec.key]) ? `<div class="md strat-md">${safeMd(v.sections[sec.key])}</div>` : '')).join('')}`;
  });
}
// Compared in the browser from the two versions as published, field by field, then the choices added, retired and changed.
function strategyDiffShow(dlg, from, to) {
  return strategyDrawerLoad(dlg, async () => {
    const [a, b] = await Promise.all([strategyVersionGet(from), strategyVersionGet(to)]);
    const data = STRAT.data, fa = strategyFramework(data, a.framework), fb = strategyFramework(data, b.framework);
    const rows = [];
    const field = (title, was, now) => {
      if (stratText(was) === stratText(now)) return;
      rows.push(`<section class="strat-diff"><h3 class="strat-k">${esc(title)}</h3>${stratText(was) ? `<del>${esc(was)}</del>` : ''}${stratText(now) ? `<ins>${esc(now)}</ins>` : ''}</section>`);
    };
    if (fa.id !== fb.id) field('Framework', fa.name, fb.name);
    field('Summary', a.summary, b.summary);
    field('Vision', a.vision, b.vision);
    const titles = new Map([...fa.sections, ...fb.sections].map(s => [s.key, s.title]));
    for (const key of new Set([...fb.sections.map(s => s.key), ...fa.sections.map(s => s.key), ...Object.keys(a.sections || {}), ...Object.keys(b.sections || {})]))
      field(titles.get(key) || key, a.sections?.[key], b.sections?.[key]);
    const before = new Map((a.choices || []).map(c => [c.id, c])), after = new Map((b.choices || []).map(c => [c.id, c]));
    const added = [], retired = [], changed = [];
    for (const c of after.values()) {
      const was = before.get(c.id);
      if (!was) { if (c.status !== 'retired') added.push(c); continue; }
      if (c.status === 'retired' && was.status !== 'retired') retired.push(c);
      else if (['statement', 'why', 'rules_out', 'status'].some(k => stratText(c[k]) !== stratText(was[k]))) changed.push([was, c]);
    }
    for (const c of before.values()) if (!after.has(c.id) && c.status !== 'retired') retired.push(c);
    const label = fb.choices_label || data.label || 'Bets';
    const list = (title, items) => items.length ? `<section class="strat-diff"><h3 class="strat-k">${esc(label)} ${title}</h3><ul>${items.join('')}</ul></section>` : '';
    rows.push(list('added', added.map(c => `<li><ins>${esc(c.statement)}</ins></li>`)));
    rows.push(list('retired', retired.map(c => `<li><del>${esc(c.statement)}</del></li>`)));
    rows.push(list('changed', changed.map(([was, c]) => `<li>${stratText(was.statement) !== stratText(c.statement) ? `<del>${esc(was.statement)}</del><ins>${esc(c.statement)}</ins>` : `<b>${esc(c.statement)}</b>`}
      ${['why', 'rules_out', 'status'].filter(k => stratText(c[k]) !== stratText(was[k])).map(k =>
        `<div class="strat-diff-k"><span class="muted">${k === 'why' ? 'Why' : k === 'rules_out' ? 'Rules out' : 'Status'}</span>${stratText(was[k]) ? `<del>${esc(STRAT_STATUS[was[k]] && k === 'status' ? STRAT_STATUS[was[k]] : was[k])}</del>` : ''}<ins>${esc(k === 'status' ? STRAT_STATUS[c[k]] || c[k] : c[k])}</ins></div>`).join('')}</li>`)));
    const body = rows.filter(Boolean).join('');
    return `<div class="strat-sv-title"><b>v${esc(a.n)} → v${esc(b.n)}</b></div>${body || '<p class="muted">No changes.</p>'}`;
  });
}
