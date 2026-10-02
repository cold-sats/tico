'use strict';

let TASK_TYPES = [];
let TASK_TYPES_LOADING = null;
const PIPELINE_STATUSES = ['open', 'doing', 'waiting', 'review', 'ready', 'done', 'closed', 'declined'];
const pipelineTypeId = task => task.type_id || task.type?.id || 'general';
const pipelineType = task => TASK_TYPES.find(type => type.id === pipelineTypeId(task));
const pipelineSelectedType = state => TASK_TYPES.find(type => type.id === state?.type);
const pipelineActionStatus = (task, body) => body.status || pipelineType(task)?.steps.find(step => step.id === body.step)?.status;
const pipelineStepName = id => TASK_TYPES.flatMap(type => type.steps).find(step => step.id === id)?.name || id;
async function taskTypesLoad() {
  if (!S.me?.cloud) return TASK_TYPES;
  if (!TASK_TYPES_LOADING) TASK_TYPES_LOADING = get('/v2/task-types').then(data => {
    TASK_TYPES = data.types || [];
    return TASK_TYPES;
  }).finally(() => { TASK_TYPES_LOADING = null; });
  return TASK_TYPES_LOADING;
}
function taskPipelineState(state) {
  state.type = '';
  if (!S.me?.cloud) return;
  try { state.type = localStorage.getItem('tico.tasks.type') || ''; } catch {}
}
function taskPipelineRemember(state) {
  try { localStorage.setItem('tico.tasks.type', state.type || ''); } catch {}
}
// The type is one of the Tasks page's filter chips (ui/app/task-list.js); a chosen type turns the board into its steps.
function taskPipelineMatches(task, state) {
  return !state.type || pipelineTypeId(task) === state.type;
}
function taskPipelineBoard(items, state) {
  const type = pipelineSelectedType(state);
  if (!type) return null;
  const columns = type.steps.map(step => ({id: step.id, name: step.name,
    items: items.filter(item => item.task.step_id === step.id)}));
  const unmapped = items.filter(item => !type.steps.some(step => step.id === item.task.step_id));
  for (const status of PIPELINE_STATUSES) {
    const list = unmapped.filter(item => item.task.status === status);
    if (list.length) columns.push({id: 'status-' + status, name: STATUS_WORD[status] || status, items: list});
  }
  const STEP_KIND = {open: 'starting', doing: 'doing', waiting: 'waiting', review: 'review', ready: 'review', done: 'done', closed: 'closed', declined: 'needs'};
  for (const column of columns) {
    column.items.sort((a, b) => (a.task.step_rank ?? Infinity) - (b.task.step_rank ?? Infinity)
      || String(a.task.created).localeCompare(String(b.task.created)) || String(a.task.id).localeCompare(String(b.task.id)));
    const step = type.steps.find(step => step.id === column.id);
    column.kind = STEP_KIND[step?.status || column.id.replace(/^status-/, '')] || '';
  }
  return boardColumnsHTML(columns) + (state.doneNext != null ? '<button class="ghost tl-more" type="button" id="board-more">Show more</button>' : '');
}
// A task's Type and Step are rows in its properties (ui/app/task-props.js).
async function taskPipelineCreate(form, selected = '') {
  try { await taskTypesLoad(); } catch { return; }
  if (!form.isConnected || TASK_TYPES.length < 2 || form.elements.type) return;
  const row = document.createElement('label'); row.textContent = 'Type ';
  const select = document.createElement('select'); select.name = 'type'; select.setAttribute('aria-label', 'Type');
  select.innerHTML = TASK_TYPES.map(type => `<option value="${esc(type.id)}">${esc(type.name)}</option>`).join('');
  select.value = TASK_TYPES.some(type => type.id === selected) ? selected : 'general';
  row.append(select); form.querySelector('label').after(row);
}
function taskPipelineCreatePayload(form, payload) {
  if (form.elements.type?.value) payload.type = form.elements.type.value;
}

function taskTypesSettingsMount() {
  if (!S.me?.cloud || $('#settings-types')) return;
  const button = document.createElement('button'); button.type = 'button'; button.dataset.settingsTab = 'types';
  button.setAttribute('role', 'tab'); button.setAttribute('aria-controls', 'settings-types'); button.textContent = 'Types';
  $('#settings-tabs').append(button);
  const pane = document.createElement('div'); pane.className = 'settings-pane'; pane.id = 'settings-types';
  pane.setAttribute('role', 'tabpanel'); pane.hidden = true;
  pane.innerHTML = '<section class="card"><header><h2>Types</h2></header><div id="set-types"></div></section>';
  $('#settings-tabs').after(pane);
}
function taskTypesSettingsShow(tab) {
  const pane = $('#settings-types');
  if (pane) { pane.hidden = tab !== 'types'; if (tab === 'types') void renderTaskTypes(); }
}
async function renderTaskTypes() {
  const host = $('#set-types'); if (!host) return;
  host.textContent = 'Loading…';
  try {
    await taskTypesLoad();
    if (!host.isConnected) return;
    const mover = canMove();
    host.innerHTML = TASK_TYPES.map(type => `<div class="task-type-row"><strong>${esc(type.name)}</strong>
      <div>${type.steps.map(step => `<span class="tlabel">${esc(step.name)}</span>`).join(' ')}</div>
      ${mover && type.id !== 'general' ? `<button class="ghost" type="button" data-edit-type="${esc(type.id)}">Edit</button>` : ''}</div>`).join('')
      + (mover ? '<button class="primary" type="button" data-new-type>New type</button>' : '');
    host.querySelectorAll('[data-edit-type]').forEach(button => button.onclick = () => taskTypeEditor(TASK_TYPES.find(type => type.id === button.dataset.editType)));
    const add = host.querySelector('[data-new-type]'); if (add) add.onclick = () => taskTypeEditor();
  } catch (error) { host.textContent = error.message; }
}
// What every bot may do with the type's tasks beyond its own (docs/tasks.md, "Types bots work on").
const TYPE_BOTS = [['parties', 'Only the bots on each task'], ['read', 'Every bot reads and comments on all of them'],
  ['work', 'Every bot reads and works on all of them']];
function taskTypeEditor(type = null) {
  const dialog = document.createElement('dialog'); dialog.className = 'tmodal task-type-editor';
  dialog.setAttribute('aria-label', type ? 'Edit type' : 'New type');
  dialog.innerHTML = `<div class="tmodal-head"><h2>${type ? 'Edit type' : 'New type'}</h2><span class="spacer"></span><button class="ghost" type="button" data-close aria-label="Close">✕</button></div>
    <form class="tmodal-body"><label>Name <input name="typeName" required value="${esc(type?.name || '')}" aria-label="Type name"></label>
    <div data-steps></div><button class="ghost" type="button" data-add-step>Add step</button>
    <label>Bots <select name="typeBots" aria-label="What bots may do">${TYPE_BOTS.map(([value, words]) => `<option value="${value}"${(type?.bots || 'parties') === value ? ' selected' : ''}>${esc(words)}</option>`).join('')}</select></label>
    <div class="row"><button class="primary" type="submit">Save</button>${type ? '<button class="ghost danger" type="button" data-delete-type>Delete</button>' : ''}</div>
    <p data-error class="err" role="status"></p></form>`;
  document.body.append(dialog); dialog.showModal();
  dialog.addEventListener('close', () => dialog.remove());
  dialog.querySelector('[data-close]').onclick = () => dialog.close();
  const rows = dialog.querySelector('[data-steps]');
  const addStep = step => {
    const row = document.createElement('div'); row.className = 'task-step-edit'; row.dataset.stepId = step?.id || '';
    row.innerHTML = `<input required aria-label="Step name" value="${esc(step?.name || '')}" placeholder="Step name">
      <select aria-label="Step status">${PIPELINE_STATUSES.map(status => `<option value="${status}"${step?.status === status ? ' selected' : ''}>${esc(STATUS_WORD[status] || status)}</option>`).join('')}</select>
      <button class="ghost" type="button" data-up aria-label="Move step up">↑</button><button class="ghost" type="button" data-down aria-label="Move step down">↓</button>
      <button class="ghost danger" type="button" data-remove aria-label="Remove step">×</button>`;
    row.querySelector('[data-up]').onclick = () => { if (row.previousElementSibling) rows.insertBefore(row, row.previousElementSibling); };
    row.querySelector('[data-down]').onclick = () => { if (row.nextElementSibling) rows.insertBefore(row.nextElementSibling, row); };
    row.querySelector('[data-remove]').onclick = () => row.remove();
    rows.append(row);
  };
  (type?.steps || [{name: 'Open', status: 'open'}]).forEach(addStep);
  dialog.querySelector('[data-add-step]').onclick = () => addStep();
  const saved = async body => {
    const submit = dialog.querySelector('[type=submit]'); submit.disabled = true;
    try {
      await post('/v2/task-types' + (type ? '/' + encodeURIComponent(type.id) : ''), body);
      dialog.close(); await renderTaskTypes();
      if (TASKS_ST && $('#task-filter')) await tasksLoad(TASKS_ST);
    } catch (error) { dialog.querySelector('[data-error]').textContent = error.message; submit.disabled = false; }
  };
  dialog.querySelector('form').onsubmit = event => {
    event.preventDefault();
    const steps = [...rows.children].map((row, position) => ({...(row.dataset.stepId ? {id: row.dataset.stepId} : {}),
      name: row.querySelector('input').value, status: row.querySelector('select').value, position}));
    void saved({name: dialog.querySelector('[name=typeName]').value, steps, bots: dialog.querySelector('[name=typeBots]').value});
  };
  const remove = dialog.querySelector('[data-delete-type]');
  if (remove) remove.onclick = async () => {
    remove.disabled = true;
    try { await post('/v2/task-types/' + encodeURIComponent(type.id) + '/delete'); dialog.close(); await renderTaskTypes(); }
    catch (error) { dialog.querySelector('[data-error]').textContent = error.message; remove.disabled = false; }
  };
  dialog.querySelector('[name=typeName]').focus();
}
