/* Roadmap publication, internal requesters, ranking and company settings. */
'use strict';

function roadmapTaskHTML(t) {
  if (!('public_title' in t) || !('public_summary' in t)) return '';
  const edit = taskPropRights(t).reopen;
  return `<section class="tsec roadmap-requesters" aria-label="Requested by"><h3 class="rail-h">Requested by
      ${edit ? '<button type="button" class="prop-add" data-requester-add aria-label="Add requester">+</button>' : ''}</h3>
      <button class="ghost" type="button" data-requester-self>Request</button>
      <div data-requester-list><span class="muted">Loading…</span></div></section>
    <details class="tsec roadmap-publication"><summary>Public details</summary>
      <form data-publication class="roadmap-form">
        <div class="roadmap-fields"><label>Visibility<select name="visibility" ${edit && !t.private ? '' : 'disabled'}>
          <option value="private"${t.visibility !== 'public' ? ' selected' : ''}>Private</option>
          <option value="public"${t.visibility === 'public' ? ' selected' : ''}>Public</option></select></label>
          <label>Size<input name="size" type="number" min="0" step="any" value="${esc(t.size ?? '')}" ${edit ? '' : 'readonly'}></label></div>
        <label>Public title<input name="public_title" required maxlength="300" value="${esc(t.public_title ?? t.title)}" ${edit ? '' : 'readonly'}></label>
        <label>Public summary<textarea name="public_summary" rows="3" maxlength="8000" ${edit ? '' : 'readonly'}>${esc(t.public_summary ?? t.body ?? '')}</textarea></label>
        ${edit ? '<div><button class="primary" type="submit">Save</button></div>' : ''}
      </form></details>`;
}
function roadmapTaskBind(d, task, change) {
  const form = $('[data-publication]', d);
  if (form) form.onsubmit = async ev => {
    ev.preventDefault();
    const values = new FormData(form), size = values.get('size');
    const body = {public_title: values.get('public_title'), public_summary: values.get('public_summary')};
    if (!form.elements.visibility.disabled) body.visibility = values.get('visibility');
    body.size = size !== '' ? Number(size) : null;
    const button = $('[type=submit]', form); button.disabled = true;
    const saved = await change(body, undefined, 'publication');
    if (!saved && button.isConnected) button.disabled = false;
  };
  const add = $('[data-requester-add]', d);
  if (add) add.onclick = () => roadmapRequesterEditor(d, task);
  void roadmapRequestersLoad(d, task);
}
async function roadmapRequestersLoad(d, task, offset = 0, previous = []) {
  const host = $('[data-requester-list]', d);
  if (!host) return;
  try {
    const data = await get(`/v2/tasks/${encodeURIComponent(task.id)}/requesters?offset=${offset}`);
    if (!host.isConnected || String(d.dataset.task) !== String(task.id)) return;
    const rows = [...previous, ...(data.requesters || [])];
    const edit = taskPropRights(task).reopen;
    const self = $('[data-requester-self]', d), own = rows.find(r => r.actor === myActor()) || (data.my_requester_id ? {id: data.my_requester_id} : null);
    if (self) {
      self.disabled = false;
      self.textContent = own ? 'Remove request' : 'Request';
      self.onclick = async () => {
        self.disabled = true;
        try {
          const base = `/v2/tasks/${encodeURIComponent(task.id)}/requesters`;
          await post(base + (own ? '/' + encodeURIComponent(own.id) + '/delete' : ''), own ? {} : {actor: myActor()});
          await roadmapRequestersLoad(d, task); roadmapRankingRefresh();
        } catch (error) { toast(error.message, true); self.disabled = false; }
      };
    }
    const group = (kind, label) => {
      const items = rows.filter(r => r.kind === kind);
      if (!items.length) return '';
      return `<div class="requester-group"><h4>${label}</h4>${items.map(r => `<div class="requester-row">
        <div><strong>${esc(r.name || (r.actor ? actorLabel(r.actor) : r.email || 'Anonymous'))}</strong>${r.important ? '<span class="pill">Important</span>' : ''}
          ${r.organization ? `<span class="muted"> · ${esc(r.organization)}</span>` : ''}
          <div class="requester-contacts">${[r.email, r.phone, r.other].filter(Boolean).map(esc).join(' · ')}</div>
          ${r.note ? `<p>${esc(r.note)}</p>` : ''}<span class="muted">${esc(r.source.replace('_', ' '))}</span></div>
        ${edit ? `<div class="requester-actions"><button type="button" class="linkish" data-requester-edit="${esc(r.id)}">Edit</button>
          <button type="button" class="linkish" data-requester-remove="${esc(r.id)}">Remove</button></div>` : ''}</div>`).join('')}</div>`;
    };
    host.innerHTML = group('external', 'External') + group('teammate', 'Team') || '<span class="muted">No requests</span>';
    if (data.next_offset != null) host.insertAdjacentHTML('beforeend', '<button class="ghost" type="button" data-requester-more>Show more</button>');
    $('[data-requester-more]', host)?.addEventListener('click', () => roadmapRequestersLoad(d, task, data.next_offset, rows));
    host.querySelectorAll('[data-requester-edit]').forEach(button => button.onclick = () => roadmapRequesterEditor(d, task, rows.find(r => r.id === button.dataset.requesterEdit)));
    host.querySelectorAll('[data-requester-remove]').forEach(button => button.onclick = async () => {
      button.disabled = true;
      try {
        await post(`/v2/tasks/${encodeURIComponent(task.id)}/requesters/${encodeURIComponent(button.dataset.requesterRemove)}/delete`, {});
        await roadmapRequestersLoad(d, task); roadmapRankingRefresh();
      } catch (error) { toast(error.message, true); button.disabled = false; }
    });
  } catch (error) { if (host.isConnected) host.textContent = error.message; }
}
function roadmapRequesterEditor(parent, task, requester = null) {
  const dialog = document.createElement('dialog'); dialog.className = 'tmodal requester-editor';
  dialog.setAttribute('aria-label', requester ? 'Edit requester' : 'Add requester');
  const fields = [['name', 'Name', 200], ['email', 'Email', 320], ['phone', 'Phone', 100], ['other', 'Other contact', 500], ['organization', 'Organization', 200]];
  const actors = [...S.people.map(p => ({value: 'human:' + p.id, text: p.name || p.id})), ...S.emps.map(b => ({value: 'bot:' + b.name, text: b.display_name || b.name}))];
  dialog.innerHTML = `<div class="tmodal-head"><h2>${requester ? 'Edit requester' : 'Add requester'}</h2><span class="spacer"></span>
      <button type="button" class="ghost" data-close aria-label="Close">×</button></div>
    <form class="tmodal-body roadmap-form"><label>Requester<select name="actor" ${requester ? 'disabled' : ''}>
      <option value="">External</option>${actors.map(a => `<option value="${esc(a.value)}"${requester?.actor === a.value ? ' selected' : ''}>${esc(a.text)}</option>`).join('')}</select></label>
      <div class="roadmap-fields">${fields.map(([key, label, max]) => `<label>${label}<input name="${key}" maxlength="${max}" value="${esc(requester?.[key] || '')}"></label>`).join('')}</div>
      <label>Quote or note<textarea name="note" rows="3" maxlength="4000">${esc(requester?.note || '')}</textarea></label>
      <div class="roadmap-fields"><label>Source<select name="source">${['manual', 'public_form', 'inbox', 'meeting'].map(value => `<option value="${value}"${requester?.source === value ? ' selected' : ''}>${esc(value.replace('_', ' '))}</option>`).join('')}</select></label>
        <label class="roadmap-check"><input type="checkbox" name="important"${requester?.important ? ' checked' : ''}>Important</label></div>
      <div class="row"><button class="primary" type="submit">Save</button><span data-error class="err" role="status"></span></div></form>`;
  document.body.append(dialog); dialog.showModal();
  $('[data-close]', dialog).onclick = () => dialog.close();
  dialog.addEventListener('close', () => dialog.remove());
  $('form', dialog).onsubmit = async ev => {
    ev.preventDefault(); const form = ev.currentTarget, button = $('[type=submit]', form);
    const body = Object.fromEntries(new FormData(form));
    body.important = form.elements.important.checked;
    if (!body.actor) delete body.actor;
    button.disabled = true;
    try {
      await post(`/v2/tasks/${encodeURIComponent(task.id)}/requesters` + (requester ? '/' + encodeURIComponent(requester.id) : ''), body);
      dialog.close(); await roadmapRequestersLoad(parent, task); roadmapRankingRefresh();
    } catch (error) { $('[data-error]', dialog).textContent = error.message; button.disabled = false; }
  };
  $('input', dialog).focus();
}

function roadmapCommentMark(m, taskId) {
  if (!m.refs?.comment || m.kind !== 'say') return '';
  const publicMark = `<span class="pill">${m.public ? (m.hidden_at ? 'Hidden' : 'Public') : 'Internal'}</span>`;
  const task = TASK_CHAT?.id === taskId ? TASK_CHAT.dialog.liveTask : null;
  if (!m.public || !task || !taskPropRights(task).reopen) return publicMark;
  return publicMark + `<button type="button" class="linkish" data-public-moderate="${m.hidden_at ? 'show' : 'hide'}" data-message="${esc(m.id)}">${m.hidden_at ? 'Restore' : 'Hide'}</button>
    <button type="button" class="linkish" data-public-moderate="delete" data-message="${esc(m.id)}">Delete</button>`;
}
function roadmapCommentsBind(state) {
  const form = $('form', state.host);
  if (form && !$('[data-comment-public]', form) && state.dialog.liveTask?.visibility === 'public' && !state.dialog.liveTask?.private) {
    form.insertAdjacentHTML('beforeend', '<label class="roadmap-check"><input type="checkbox" data-comment-public>Public</label>');
  }
  state.host.querySelectorAll('[data-public-moderate]').forEach(button => button.onclick = async () => {
    button.disabled = true;
    try {
      await post(`/v2/tasks/${encodeURIComponent(state.id)}/comments/${encodeURIComponent(button.dataset.message)}/moderate`, {action: button.dataset.publicModerate});
      await taskChatRead(state);
    } catch (error) { toast(error.message, true); button.disabled = false; }
  });
}

let ROADMAP_RANKING = null;
function roadmapRankingRefresh() { if (S.route === '#/roadmap' && ROADMAP_RANKING) void roadmapRankingLoad(ROADMAP_RANKING); }
function pageRoadmap() {
  const state = ROADMAP_RANKING = {sort: 'requester_count', direction: 'desc', offset: 0, previous: [], next: null, seq: 0};
  $('#main').innerHTML = `<div class="roadmap-page"><header class="meeting-head"><h1>Roadmap</h1><div class="row">
      <a href="${TASKS}" class="ghost">Tasks</a><button class="primary" type="button" data-roadmap-new>New task</button></div></header>
    <div class="roadmap-sort"><label>Sort<select data-roadmap-sort>${[['requester_count', 'Requests'], ['external_requesters', 'External'], ['important', 'Important'], ['organization', 'Organization'], ['size', 'Size']].map(([value, name]) => `<option value="${value}">${name}</option>`).join('')}</select></label>
      <button class="ghost" type="button" data-roadmap-direction aria-label="Sort ascending">↓</button></div>
    <div data-roadmap-table></div><div class="row roadmap-pager"><button class="ghost" type="button" data-roadmap-back disabled>Previous</button>
      <button class="ghost" type="button" data-roadmap-next disabled>Next</button><span class="err" role="status" data-roadmap-error></span></div></div>`;
  $('[data-roadmap-new]').onclick = () => { void taskTypesLoad().then(() => { const manager = S.emps.find(e => e.name === 'product-manager' || e.template === 'product-manager'); const product = TASK_TYPES.find(t => t.manager === 'product-manager' || t.id === 'product-roadmap'); openTaskCreate(manager?.name || '', {type: product?.id || 'product-roadmap'}); }); };
  $('[data-roadmap-sort]').onchange = ev => { state.sort = ev.target.value; state.offset = 0; state.previous = []; void roadmapRankingLoad(state); };
  $('[data-roadmap-direction]').onclick = ev => {
    state.direction = state.direction === 'desc' ? 'asc' : 'desc'; state.offset = 0; state.previous = [];
    ev.currentTarget.textContent = state.direction === 'desc' ? '↓' : '↑';
    ev.currentTarget.setAttribute('aria-label', state.direction === 'desc' ? 'Sort ascending' : 'Sort descending');
    void roadmapRankingLoad(state);
  };
  $('[data-roadmap-back]').onclick = () => { state.offset = state.previous.pop() || 0; void roadmapRankingLoad(state); };
  $('[data-roadmap-next]').onclick = () => { if (state.next != null) { state.previous.push(state.offset); state.offset = state.next; void roadmapRankingLoad(state); } };
  void roadmapRankingLoad(state);
}
async function roadmapRankingLoad(state) {
  const seq = ++state.seq;
  try {
    const data = await get(`/v2/roadmap-tasks?sort=${state.sort}&direction=${state.direction}&offset=${state.offset}&limit=25`);
    if (ROADMAP_RANKING !== state || S.route !== '#/roadmap' || seq !== state.seq) return;
    state.next = data.next_offset;
    const columns = [['requester_count', 'Requests'], ['external_requesters', 'External'], ['internal_requesters', 'Team'], ['important_requesters', 'Important'], ['organization', 'Organization'], ['size', 'Size']];
    $('[data-roadmap-table]').innerHTML = (data.tasks || []).length ? `<table class="roadmap-table"><thead><tr><th>Task</th>${columns.map(([, label]) => `<th>${label}</th>`).join('')}</tr></thead><tbody>${data.tasks.map(t => `<tr><td>
      <button class="linkish roadmap-task" type="button" data-roadmap-task="${esc(t.id)}">${esc(t.title)}</button><div class="muted">${esc(t.step || '')} · ${t.visibility === 'public' ? 'Public' : 'Private'}</div></td>
      ${columns.map(([key, label]) => `<td data-label="${label}">${esc(t[key] ?? '—')}</td>`).join('')}</tr>`).join('')}</tbody></table>` : '<p class="muted">No roadmap tasks</p>';
    document.querySelectorAll('[data-roadmap-task]').forEach(button => button.onclick = () => taskModalOpen('t' + button.dataset.roadmapTask));
    $('[data-roadmap-back]').disabled = !state.offset;
    $('[data-roadmap-next]').disabled = state.next == null;
    $('[data-roadmap-error]').textContent = '';
  } catch (error) { if (S.route === '#/roadmap' && seq === state.seq) $('[data-roadmap-error]').textContent = error.message; }
}

async function roadmapSettingsMount() {
  const host = $('#settings-roadmaps');
  if (!host || host.dataset.loaded || !settingsIsAdmin()) return;
  host.dataset.loaded = 'loading';
  try {
    const [settings, tags] = await Promise.all([get('/v2/roadmaps/settings'), get('/v2/tags')]);
    if (!host.isConnected) return;
    host.innerHTML = `<header><h2>Public roadmaps</h2></header><form class="roadmap-form">
      <fieldset><legend>Labels</legend><div class="roadmap-labels">${(tags.tags || []).filter(t => !t.is_template).map(t => `<label class="roadmap-check"><input type="checkbox" name="label" value="${esc(t.key)}"${settings.labels.includes(t.key) ? ' checked' : ''}>${esc(t.label || t.key)}</label>`).join('') || '<span class="muted">No labels</span>'}</div></fieldset>
      <label>Allowed origins<textarea name="cors_origins" rows="3" placeholder="https://acme.example">${esc(settings.cors_origins.join('\n'))}</textarea></label>
      <label>Actions per IP / day<input type="number" name="action_limit" min="1" max="10000" required value="${settings.action_limit}"></label>
      <label class="roadmap-check"><input type="checkbox" name="bot_public_approval"${settings.bot_public_approval ? ' checked' : ''}>Approve bot public edits and replies</label>
      <div class="row"><button class="primary" type="submit">Save</button><span data-status role="status"></span></div></form>`;
    $('form', host).onsubmit = async ev => {
      ev.preventDefault(); const form = ev.currentTarget, values = new FormData(form), button = $('[type=submit]', form), status = $('[data-status]', form);
      const body = {labels: values.getAll('label'), cors_origins: String(values.get('cors_origins')).split(/[\n,]/).map(s => s.trim()).filter(Boolean),
        action_limit: Number(values.get('action_limit')), bot_public_approval: form.elements.bot_public_approval.checked};
      button.disabled = true; status.textContent = '';
      try { await post('/v2/roadmaps/settings', body); status.textContent = 'Saved'; }
      catch (error) { status.textContent = error.message; }
      finally { button.disabled = false; }
    };
    host.dataset.loaded = 'yes';
  } catch (error) { if (host.isConnected) { host.textContent = error.message; delete host.dataset.loaded; } }
}
