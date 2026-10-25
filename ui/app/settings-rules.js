/* ui/app/settings-rules.js — Settings > Rules: what wakes a bot
   Classic script: its globals are shared with the other files under ui/app/, loaded in the order index.html lists them. */
'use strict';

// Every wake rule (backend/rules.py): the built-ins, read-only, and the table rows by scope. Each row reads
// WHEN <event> [AND <conditions>] THEN <outcome>, with its 7-day runs and no-op rate. A row the viewer may change
// (`can_change`, which the server also enforces) has a switch and Edit. Writes carry the row's revision, so a row
// someone else changed answers 409 instead of being overwritten.
let RULES = null, RULES_AT = 0, RULES_Q = '', RULES_SCOPE = '', RULES_TASK = '', RULES_TASK_TITLE = '';
const RULES_BUSY = new Set();
const RULE_SCOPES = [['builtin', 'Built-in'], ['team', 'Team'], ['type', 'Type'], ['department', 'Department'], ['bot', 'Bot'], ['task', 'Task']];
const RULE_BUILTIN_GROUPS = {always: 'Always wakes', awaited: 'Awaited', filter: 'Waits', batch: 'Batched', wake: 'Wakes', system: 'System'};
const RULE_OUTCOMES = {wake: 'wake the bot', note: 'leave a note for its next run', batch: 'batch it', ignore: 'drop it', ask: 'ask a person', action: 'do an action'};
const RULE_ACTIONS = {close: 'close the task', move_step: 'move the step', set_wait: 'set a wait', relate: 'relate tasks', note: 'add a note'};
const RULE_ACTORS = {human: 'a person', bot: 'a bot', keeper: 'Tico'};
const RULE_ROLES = {owner: 'owns the task', requester: 'requested the task', other: 'neither owns nor requested it'};
// The always-wake events (backend/rules.py FLOOR_EVENTS): the server refuses a row that makes one wait.
const RULE_FLOOR = new Set(['person_message', 'ask', 'answer', 'approval', 'needs_action', 'reply', 'verdict']);

// An event's words come from its built-in row, so a new event the backend adds reads right with no UI change.
function ruleEventWords(event) {
  if (event === '*') return 'anything else';
  const rank = {always: 0, wake: 1, batch: 2, awaited: 3};
  const found = (RULES?.rules || []).filter(r => r.built_in && r.event === event && r.group in rank)
    .sort((a, b) => rank[a.group] - rank[b.group])[0];
  return found?.words || event.replace(/_/g, ' ');
}
const ruleList = v => (Array.isArray(v) ? v : [v]).filter(Boolean);
function ruleWhenWords(when) {
  const out = [];
  if (when.actor) out.push('it comes from ' + ruleList(when.actor).map(a => RULE_ACTORS[a] || a).join(' or '));
  if (when.role) out.push('the bot ' + ruleList(when.role).map(r => RULE_ROLES[r] || r).join(' or '));
  if (when.step) out.push('the task is at ' + ruleList(when.step).join(' or '));
  if (when.state) out.push('the task is ' + ruleList(when.state).join(' or '));
  if (when.tag) out.push('the task is tagged ' + ruleList(when.tag).join(' and '));
  return out;
}
function ruleThenWords(r) {
  return r.then === 'action' ? (RULE_ACTIONS[r.params?.action] || 'do an action') : (RULE_OUTCOMES[r.then] || r.then);
}
function ruleScopeWords(r) {
  const id = r.scope_id;
  if (r.scope_kind === 'team') return 'Team';
  if (r.scope_kind === 'bot') return 'Bot · ' + empName(id);
  if (r.scope_kind === 'type') return 'Type · ' + (TASK_TYPES.find(t => t.id === id)?.name || id);
  if (r.scope_kind === 'department') return 'Department · ' + ((SYSTEM_ROUTINES?.task_rule_departments || []).find(d => d.id === id)?.name || id);
  if (r.scope_kind === 'task') return 'Task · ' + (id === RULES_TASK && RULES_TASK_TITLE ? RULES_TASK_TITLE : id.slice(0, 8));
  return '';
}
function ruleUsageHTML(r) {
  const rate = r.no_op_rate_7d == null ? '' : ` · <span data-rule-noop>${Math.round(r.no_op_rate_7d * 100)}% no-op</span>`;
  return `<span class="tnum${r.runs_7d ? '' : ' muted'}" title="Last 7 days" data-rule-usage>${r.runs_7d} run${r.runs_7d === 1 ? '' : 's'}${rate}</span>`;
}
function ruleRowHTML(r) {
  const busy = RULES_BUSY.has(r.id);
  const and = r.built_in ? [] : ruleWhenWords(r.when || {});
  const when = r.built_in ? r.words : ruleEventWords(r.event);
  const text = `<b>WHEN</b> ${esc(when)}${and.map(w => ` <b class="sysr-and">AND</b> ${esc(w)}`).join('')} <b>THEN</b> ${esc(ruleThenWords(r))}`;
  const ctl = r.can_change ? `<label class="sysr-switch">${peopleSwitch('data-rule-on', r.enabled, busy, 'Rule on')}<span>${r.enabled ? 'On' : 'Off'}</span></label>
      <button type="button" class="ghost" data-rule-edit${busy ? ' disabled' : ''}>Edit</button>`
    : r.built_in ? '' : `<span class="sysr-state">${r.enabled ? 'On' : 'Off'}</span>`;
  return `<div class="wr-row${r.enabled === false ? ' wr-off' : ''}" data-rule="${esc(r.id)}">
    <div class="wr-text" data-rule-text>${text}${r.note ? `<span class="muted wr-note">${esc(r.note)}</span>` : ''}</div>
    ${r.built_in ? '' : `<span class="pill wr-scope" data-rule-scope>${esc(ruleScopeWords(r))}</span>`}
    <span class="wr-usage">${ruleUsageHTML(r)}</span>
    <div class="wr-ctl">${ctl}<p class="settings-cell-note" role="status" data-rule-status></p></div>
  </div>`;
}
function ruleMatches(r) {
  if (RULES_TASK && r.built_in) return false;   // read for their words only
  if (RULES_SCOPE && r.scope_kind !== RULES_SCOPE) return false;
  if (!RULES_Q) return true;
  return searchIncludes([r.words, r.event, ruleEventWords(r.event), ruleThenWords(r), ruleScopeWords(r), r.note, ...ruleWhenWords(r.when || {})], RULES_Q);
}
function ruleGroupsHTML() {
  const rows = (RULES?.rules || []).filter(ruleMatches);
  if (!rows.length) return `<div class="empty" data-rules-none>${RULES_TASK ? 'No rules for this task. The team, type, bot and built-in rules decide.' : 'No rule matches.'}</div>`;
  return RULE_SCOPES.map(([kind, label]) => {
    const mine = rows.filter(r => r.scope_kind === kind);
    if (!mine.length) return '';
    const body = kind === 'builtin'
      ? Object.entries(RULE_BUILTIN_GROUPS).map(([g, name]) => {
        const sub = mine.filter(r => r.group === g);
        return sub.length ? `<h4 class="wr-sub">${esc(name)}</h4>${sub.map(ruleRowHTML).join('')}` : '';
      }).join('')
      : mine.map(ruleRowHTML).join('');
    // The built-ins are long and fixed, so they start folded unless a search is narrowing them.
    const open = kind !== 'builtin' || RULES_Q || RULES_SCOPE === 'builtin';
    return `<details class="wr-group" data-rule-group="${kind}"${open ? ' open' : ''}><summary><span>${esc(label)}</span><span class="cnt">${mine.length}</span></summary>${body}</details>`;
  }).join('');
}
const rulesMayAdd = () => !!RULES_TASK || settingsIsAdmin() || canMove() || (S.emps || []).some(settingsCanManageBot);
function rulesHTML() {
  const opt = (v, label) => `<option value="${esc(v)}"${v === RULES_SCOPE ? ' selected' : ''}>${esc(label)}</option>`;
  const task = RULES_TASK ? `<div class="wr-filter" data-rules-task><span>Rules for <strong>${esc(RULES_TASK_TITLE || RULES_TASK.slice(0, 8))}</strong></span>
      <a href="#/task/${encodeURIComponent(RULES_TASK)}">Open task</a><a href="#/settings/rules" data-rules-all>All rules</a></div>` : '';
  return `${task}<div class="settings-bots-filters">${rulesMayAdd() ? '<button type="button" class="primary" data-rule-new>Add rule</button>' : ''}
      <input class="settings-filter-search" type="search" autocomplete="off" data-rules-search value="${esc(RULES_Q)}" placeholder="Search rules" aria-label="Search rules">
      ${RULES_TASK ? '' : `<select class="settings-inline-select" data-rules-scope aria-label="Scope">${opt('', 'All scopes')}${RULE_SCOPES.map(([k, v]) => opt(k, v)).join('')}</select>`}</div>
    <!-- Suggestions (propose_demotions): rules whose runs are mostly no-ops, each offered as a one-click change, land here. -->
    <div class="wr-suggest" data-rules-suggestions hidden></div>
    <div class="wr-list" data-rules-list>${ruleGroupsHTML()}</div>`;
}
function rulesPaint() {
  const el = $('#set-rules'); if (!el || !RULES) return;
  const list = el.querySelector('[data-rules-list]');
  if (list && el.dataset.rulesTask === RULES_TASK) list.innerHTML = ruleGroupsHTML();
  else { el.innerHTML = rulesHTML(); el.dataset.rulesTask = RULES_TASK; }
  rulesBind(el);
}
// The listing is paged (`more`); the built-ins come on the first page only, so later pages add table rows.
async function rulesLoad() {
  const scope = RULES_TASK ? `&scope_kind=task&scope_id=${encodeURIComponent(RULES_TASK)}` : '';
  let offset = 0, out = null;
  for (let page = 0; page < 5; page++) {
    const data = await get(`/v2/rules?limit=200&offset=${offset}${scope}`);
    data.rules ||= [];
    if (!out) out = data; else out.rules.push(...data.rules);
    if (!data.more) break;
    offset += 200;
  }
  // A task's own listing has no built-ins, and the event words come from them; read them once.
  if (RULES_TASK && !out.rules.some(r => r.built_in)) {
    const builtins = RULES?.rules?.filter(r => r.built_in) || (await get('/v2/rules?scope_kind=builtin')).rules || [];
    out.rules = [...builtins, ...out.rules];
  }
  return out;
}
async function renderSettingsRules(force) {
  const el = $('#set-rules'); if (!el) return;
  const task = RULES_TASK;
  if (RULES && el.dataset.rulesTask === task && !force && Date.now() - RULES_AT < 60000) { rulesPaint(); return; }
  RULES_AT = Date.now();
  if (task && !RULES_TASK_TITLE) get('/v2/tasks/' + encodeURIComponent(task)).then(t => {
    RULES_TASK_TITLE = (t.task || t).title || '';
    if (RULES_TASK === task && RULES) { delete el.dataset.rulesTask; rulesPaint(); }   // the heading names it too
  }).catch(() => {});
  // The type names are read alongside, so a type row never shows a bare id; the department names come with the
  // routines above (renderSystemRoutines repaints this list when they land).
  const types = taskTypesLoad({cached: true}).catch(() => {});
  try { const data = await rulesLoad(); await types; if (RULES_TASK !== task) return; RULES = data; }
  catch (e) { if (!RULES) el.innerHTML = `<div class="empty">Couldn't load the rules: ${esc(e.message || 'try again')}</div>`; return; }
  if (RULES_BUSY.size || formBusy(el.querySelector('[data-rules-list]'))) return;
  rulesPaint();
  settingsReveal('#set-rules-card');
}
function ruleReplace(rule) {
  if (!RULES || !rule) return;
  const at = RULES.rules.findIndex(r => r.id === rule.id);
  // A write answers the row without its 7-day figures; keep the ones read last.
  const kept = at >= 0 ? RULES.rules[at] : {runs_7d: 0, no_op_rate_7d: null, can_change: true};
  const next = {...kept, ...rule, runs_7d: kept.runs_7d, no_op_7d: kept.no_op_7d, no_op_rate_7d: kept.no_op_rate_7d, can_change: kept.can_change ?? true};
  if (at >= 0) RULES.rules[at] = next; else RULES.rules.push(next);
}
async function ruleToggle(id, on) {
  const r = RULES.rules.find(x => x.id === id); if (!r) return;
  RULES_BUSY.add(id); rulesPaint();
  let note = '', failed = false;
  try { ruleReplace((await post('/v2/rules/' + encodeURIComponent(id), {expected_revision: r.revision, on})).rule); note = 'Saved'; }
  catch (e) { note = e.message || 'Try again'; failed = true; if (e.status === 409) void renderSettingsRules(true); }
  finally { RULES_BUSY.delete(id); }
  rulesPaint();
  const box = $(`[data-rule="${CSS.escape(id)}"] [data-rule-status]`);
  if (box) { box.textContent = note; box.classList.toggle('err', failed); }
}
function rulesBind(el) {
  const add = el.querySelector('[data-rule-new]');
  if (add) add.onclick = () => ruleEditor(null);
  const search = el.querySelector('[data-rules-search]');
  if (search) search.oninput = () => { RULES_Q = search.value; el.querySelector('[data-rules-list]').innerHTML = ruleGroupsHTML(); };
  const scope = el.querySelector('[data-rules-scope]');
  if (scope) scope.onchange = () => { RULES_SCOPE = scope.value; el.querySelector('[data-rules-list]').innerHTML = ruleGroupsHTML(); };
  const list = el.querySelector('[data-rules-list]');
  list.onchange = ev => {
    const row = ev.target.closest('[data-rule]');
    if (row && ev.target.matches('[data-rule-on]')) void ruleToggle(row.dataset.rule, ev.target.checked);
  };
  list.onclick = ev => {
    const edit = ev.target.closest('[data-rule-edit]'); if (!edit || edit.disabled) return;
    ruleEditor(RULES.rules.find(r => r.id === edit.closest('[data-rule]').dataset.rule));
  };
}

// The scopes a viewer may add a row in, as far as the page knows; the server has the last word and its refusal
// shows in the form.
function ruleScopeChoices() {
  const out = [];
  if (settingsIsAdmin()) out.push(['team', 'Team']);
  if (canMove()) out.push(['type', 'Task type']);
  if ((SYSTEM_ROUTINES?.task_rule_departments || []).length) out.push(['department', 'Department']);
  if ((S.emps || []).some(settingsCanManageBot)) out.push(['bot', 'Bot']);
  out.push(['task', 'Task']);
  return out;
}
function ruleTargetHTML(kind, value) {
  const opt = (v, label) => `<option value="${esc(v)}"${v === value ? ' selected' : ''}>${esc(label)}</option>`;
  const pick = options => `<label>Which<select name="scope_id" required><option value="">Choose</option>${options}</select></label>`;
  if (kind === 'type') return pick(TASK_TYPES.map(t => opt(t.id, t.name)).join(''));
  if (kind === 'department') return pick((SYSTEM_ROUTINES?.task_rule_departments || []).map(d => opt(d.id, d.name)).join(''));
  if (kind === 'bot') return pick((S.emps || []).filter(settingsCanManageBot).map(e => opt(e.name, empName(e.name))).sort().join(''));
  if (kind === 'task') return `<label>Task ID<input name="scope_id" required maxlength="120" value="${esc(value || RULES_TASK)}"></label>`;
  return '';
}
function ruleEditor(rule) {
  const dialog = document.createElement('dialog');
  dialog.className = 'tmodal task-rule-dialog';
  const when = rule?.when || {}, first = v => ruleList(v)[0] || '';
  const opt = (v, label, cur) => `<option value="${esc(v)}"${v === cur ? ' selected' : ''}>${esc(label)}</option>`;
  const scopes = ruleScopeChoices();
  const kind = rule?.scope_kind || (RULES_TASK ? 'task' : scopes[0]?.[0] || 'task');
  const events = ['*', ...(RULES?.events || [])].map(e => opt(e, (RULE_FLOOR.has(e) ? 'Always: ' : '') + ruleEventWords(e), rule?.event || 'comment')).join('');
  dialog.innerHTML = `<form class="task-rule-form" data-rule-form><header><h2>${rule ? 'Edit rule' : 'Add rule'}</h2><button type="button" class="ghost" data-close>Cancel</button></header>
    ${rule ? `<p class="muted">${esc(ruleScopeWords(rule))}</p>` : `<label>Scope<select name="scope_kind" data-rule-kind>${scopes.map(([k, v]) => opt(k, v, kind)).join('')}</select></label>
    <div data-rule-target>${ruleTargetHTML(kind, '')}</div>`}
    <label>WHEN<select name="event">${events}</select></label>
    <div class="wr-when">
      <label>From<select name="actor">${opt('', 'Anyone', first(when.actor))}${Object.entries(RULE_ACTORS).map(([k, v]) => opt(k, v, first(when.actor))).join('')}</select></label>
      <label>Bot's role<select name="role">${opt('', 'Any', first(when.role))}${Object.keys(RULE_ROLES).map(k => opt(k, k[0].toUpperCase() + k.slice(1), first(when.role))).join('')}</select></label>
      <label>Status<select name="state">${opt('', 'Any', first(when.state))}${PIPELINE_STATUSES.map(s => opt(s, s[0].toUpperCase() + s.slice(1), first(when.state))).join('')}</select></label>
      <label>Step<input name="step" maxlength="80" value="${esc(first(when.step))}"></label>
      <label>Tag<input name="tag" maxlength="80" value="${esc(first(when.tag))}"></label>
    </div>
    <label>THEN<select name="then" data-rule-then>${Object.entries(RULE_OUTCOMES).map(([k, v]) => opt(k, v[0].toUpperCase() + v.slice(1), rule?.then || 'note')).join('')}</select></label>
    <label data-rule-action${(rule?.then || 'note') === 'action' ? '' : ' hidden'}>Action<select name="action">${Object.entries(RULE_ACTIONS).map(([k, v]) => opt(k, v[0].toUpperCase() + v.slice(1), rule?.params?.action || 'close')).join('')}</select></label>
    <label>Note<input name="note" maxlength="500" value="${esc(rule?.note || '')}"></label>
    <label><input type="checkbox" name="on"${rule?.enabled === false ? '' : ' checked'}> On</label>
    <p class="err" role="status" data-rule-error></p>
    <footer>${rule ? '<button type="button" class="ghost danger" data-rule-delete>Delete</button>' : ''}<button type="submit" class="primary">Save rule</button></footer></form>`;
  const form = dialog.querySelector('form'), error = dialog.querySelector('[data-rule-error]');
  dialog.querySelector('[data-close]').onclick = () => dialog.close();
  dialog.addEventListener('close', () => dialog.remove());
  form.elements.then.onchange = () => { dialog.querySelector('[data-rule-action]').hidden = form.elements.then.value !== 'action'; };
  if (form.elements.scope_kind) form.elements.scope_kind.onchange = () => { dialog.querySelector('[data-rule-target]').innerHTML = ruleTargetHTML(form.elements.scope_kind.value, ''); };
  const done = () => { dialog.close(); rulesPaint(); };
  form.onsubmit = async ev => {
    ev.preventDefault(); const button = form.querySelector('[type="submit"]'); button.disabled = true; error.textContent = '';
    const v = new FormData(form), cond = {};
    for (const key of ['actor', 'role', 'state', 'step', 'tag']) if (String(v.get(key) || '').trim()) cond[key] = String(v.get(key)).trim();
    const then = v.get('then');
    // Only the action row reads params; any other outcome clears what an earlier action left.
    const body = {event: v.get('event'), then, when: cond, params: then === 'action' ? {action: v.get('action')} : {}, note: v.get('note') || '', on: v.has('on')};
    try {
      if (rule) ruleReplace((await post('/v2/rules/' + encodeURIComponent(rule.id), {...body, expected_revision: rule.revision})).rule);
      else {
        const scope_kind = v.get('scope_kind') || 'task';
        ruleReplace({...(await post('/v2/rules', {...body, scope_kind, scope_id: scope_kind === 'team' ? '' : String(v.get('scope_id') || '').trim()})).rule, can_change: true});
      }
      done();
    } catch (e) { error.textContent = e.message || 'Could not save the rule'; }
    finally { button.disabled = false; }
  };
  const del = dialog.querySelector('[data-rule-delete]');
  if (del) del.onclick = async () => {
    if (!confirm('Delete this rule?')) return;
    del.disabled = true; error.textContent = '';
    try {
      await post('/v2/rules/' + encodeURIComponent(rule.id) + '/delete', {expected_revision: rule.revision});
      RULES.rules = RULES.rules.filter(r => r.id !== rule.id); done();
    } catch (e) { error.textContent = e.message || 'Could not delete the rule'; del.disabled = false; }
  };
  document.body.appendChild(dialog); dialog.showModal(); form.elements.event.focus();
}
