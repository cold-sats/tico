/* ui/app/tasks-page.js — pageTasks: loading, tools, needs you, Done, render
   Classic script: its globals are shared with the other files under ui/app/, loaded in the order index.html lists them. */
'use strict';

// openId opens one task in full as soon as the list is loaded: the #/task/<id> address a bot or
// the setup progress screen links to, which is the Tasks page with that item already open.
const TASK_PREF = 'tasks.view';
function pageTasks(forced, openId = '') {
  TASKS_ST?.layoutAbort?.abort();
  const state = TASKS_ST = {bot: '', filter: 'all', label: '', view: 'foryou', tasks: [], routines: null,
    labels: [], kind: 'all', armed: 'all', open: openId, q: '', loading: true,
    doneLoaded: false, doneLoading: false, doneNext: null, loadSeq: 0};
  try {
    state.bot = localStorage.getItem('hub.board.bot') || '';
    state.filter = localStorage.getItem('hub.tasks.filter') || 'all';
    state.label = localStorage.getItem('hub.tasks.label') || '';
    state.view = forced || localStorage.getItem('hub.tasks.view2') || 'foryou';
    state.kind = localStorage.getItem('hub.recurring.kind') || 'all';
    state.armed = localStorage.getItem('hub.recurring.armed') || 'all';
  } catch { state.view = forced || 'foryou'; }
  tasksNormalise(state, forced);
  $('#main').innerHTML = `<div class="board-tools tasks-head find">
      <h1>Tasks</h1>
      <div class="task-strip"></div>
      <div class="task-find">
        <span class="nav-icon" aria-hidden="true">search</span>
        <input type="search" id="task-q" spellcheck="false" aria-label="Search tasks" placeholder="Search tasks…" autocomplete="off">
        <button type="button" id="task-filter" popovertarget="task-filter-pop" aria-label="Filter tasks" aria-expanded="false">Filter</button>
      </div>
      <button class="primary round-add" type="button" id="task-new" aria-label="New task" title="New task">+</button>
      <div class="tabs slim" id="task-view" role="group" aria-label="View"></div>
    </div>
    <div id="task-filter-pop" popover aria-label="Task filters">
      <div class="task-filter-row"><span class="lbl">Show</span><div class="tfilters" id="task-filters" role="group" aria-label="Show tasks"></div></div>
      <div class="task-filter-row"><label for="board-bot">Owner</label><select id="board-bot" aria-label="Filter by owner"></select></div>
      <div class="task-filter-row" id="task-label-row"><label for="board-label">Label</label><select id="board-label" aria-label="Filter by label"></select></div>
      <div class="task-filter-foot"><button type="button" id="task-filter-clear">Clear</button></div>
    </div>
    <div id="task-body"></div>`;
  $('#task-new').onclick = () => openTaskCreate(state.bot || '');
  const search = $('#task-q');
  search.oninput = () => {
    state.q = search.value;
    clearTimeout(state.searchTimer);
    state.searchTimer = setTimeout(() => {
      tasksRender(state);
      if (state.view === 'done' && state.q && state.doneNext != null) void tasksLoadAllDone(state);
    }, 150);
  };
  search.onkeydown = ev => {
    if (ev.key !== 'Escape') return;
    if (search.value) ev.stopPropagation();
    search.value = state.q = '';
    clearTimeout(state.searchTimer);
    tasksRender(state);
  };
  const filterPop = $('#task-filter-pop');
  const head = $('.tasks-head.find');
  const strip = head.querySelector('.task-strip');
  const viewEl = $('#task-view');
  const smallScreen = matchMedia('(max-width:760px)');
  const positionFilter = () => {
    if (smallScreen.matches) {
      filterPop.style.top = filterPop.style.left = '';
      return;
    }
    const rect = $('#task-filter').getBoundingClientRect();
    filterPop.style.top = `${Math.max(12, Math.min(rect.bottom + 6, window.innerHeight - filterPop.offsetHeight - 12))}px`;
    filterPop.style.left = `${Math.max(12, Math.min(rect.right - filterPop.offsetWidth, window.innerWidth - filterPop.offsetWidth - 12))}px`;
  };
  const layoutTools = () => {
    if (!head.isConnected) return;
    if (smallScreen.matches) {
      strip.appendChild(viewEl);
      head.appendChild(strip);
    } else {
      head.insertBefore(strip, head.querySelector('.task-find'));
      head.appendChild(viewEl);
    }
    if (filterPop.matches(':popover-open')) positionFilter();
  };
  layoutTools();
  state.layoutAbort = new AbortController();
  smallScreen.addEventListener('change', layoutTools, {signal: state.layoutAbort.signal});
  filterPop.addEventListener('toggle', ev => {
    const open = ev.newState === 'open';
    $('#task-filter')?.setAttribute('aria-expanded', String(open));
    if (open) positionFilter();
  });
  $('#task-filter-clear').onclick = () => {
    state.filter = 'all'; state.bot = ''; state.label = '';
    tasksRemember(state); tasksTools(state); tasksRender(state);
  };
  tasksTools(state); tasksRender(state);
  // the remembered view lives with the person, not the browser; the local copy is the fallback
  void (async () => {
    // Start the task request immediately. A slow preference read must never hold the board blank.
    const loading = tasksLoad(state);
    const pref = S.me?.cloud ? await v2Get('/v2/preferences/' + TASK_PREF) : null;
    if (TASKS_ST !== state) return;
    if (pref?.value && typeof pref.value === 'object') {
      for (const k of ['bot', 'filter', 'label']) if (pref.value[k] != null) state[k] = String(pref.value[k]);
      // Before `views: 2`, List and Board both showed For you, so an old choice means For you.
      if (!forced && pref.value.view) state.view = pref.value.views === 2 ? String(pref.value.view) : 'foryou';
      tasksNormalise(state, forced);
    }
    tasksTools(state);
    tasksRender(state);
    if (state.view === 'done' && !state.doneLoaded && !state.doneLoading) void tasksLoadDone(state, true);
    await loading;
  })();
}
function tasksNormalise(state, forced) {
  if (!TASK_VIEWS.some(([k]) => k === state.view)) state.view = forced || 'foryou';
  if (!TASK_FILTERS.some(([k]) => k === state.filter)) state.filter = 'all';
  if (!['all', 'cron', 'event', 'inbox'].includes(state.kind)) state.kind = 'all';
  if (!['all', 'armed', 'idle'].includes(state.armed)) state.armed = 'all';
  if (state.bot && !state.bot.startsWith('human:') && !S.emps.some(e => e.name === state.bot)) state.bot = '';
}
function tasksRemember(state) {
  try {
    localStorage.setItem('hub.board.bot', state.bot);
    localStorage.setItem('hub.tasks.filter', state.filter); localStorage.setItem('hub.tasks.label', state.label);
    localStorage.setItem('hub.tasks.view2', state.view);
  } catch {}
  if (S.me?.cloud) {
    clearTimeout(state.saveTimer);
    state.saveTimer = setTimeout(() => { void post('/v2/preferences/' + TASK_PREF,
      {value: {bot: state.bot, filter: state.filter, label: state.label, view: state.view, views: 2}}).catch(() => {}); }, 400);
  }
}
function taskOwnerOptions(selected = '') {
  const people = (S.people || []).filter(p => !p.hidden)
    .slice().sort((a, b) => String(a.name || a.id).localeCompare(String(b.name || b.id)));
  const bots = (S.emps || []).filter(e => e.status !== 'archived' && (!isHiddenBot(e.name) || [e.name, 'bot:' + e.name].includes(selected)))
    .slice().sort((a, b) => byBotOrder(a, b) || String(a.display_name || a.name).localeCompare(String(b.display_name || b.name)));
  const pick = value => value === selected ? ' selected' : '';
  return `<option value="">Who is this for?</option>
    <optgroup label="Humans">${people.map(p =>
      `<option value="human:${esc(p.id)}"${pick('human:' + p.id) || pick(p.id)}>${esc(p.name || p.id)}</option>`).join('')}</optgroup>
    <optgroup label="Bots">${bots.map(e =>
      `<option value="${esc(e.name)}"${pick(e.name) || pick('bot:' + e.name)}>${esc(e.display_name || e.name)}</option>`).join('')}</optgroup>`;
}
function taskCreateModal() {
  let d = $('#task-create');
  if (d) return d;
  d = document.createElement('dialog');
  d.id = 'task-create'; d.className = 'tmodal';
  d.addEventListener('click', ev => { if (ev.target === d) d.close(); });
  document.body.appendChild(d);
  return d;
}
function openTaskCreate(owner = '', opts = {}) {
  const d = taskCreateModal();
  const parent = opts.parent || null;
  d.innerHTML = `<div class="tmodal-head"><h2 class="tmodal-title" style="margin:0">${parent ? 'New part' : 'New task'}</h2>
      <span class="spacer"></span>
      <button class="ghost tmodal-x" type="button" data-modal-close aria-label="Close">✕</button></div>
    <div class="tmodal-body">
      <form class="task" id="task-create-form">
        ${parent ? `<p class="muted">Part of <b>${esc(parent.title)}</b></p>` : ''}
        <div class="r1" style="grid-template-columns:1fr"><input type="text" name="title" required aria-label="Title" placeholder="Email Dana the renewal brief"></div>
        <label>For <select name="owner" required aria-label="Who this task is for">${taskOwnerOptions(owner)}</select></label>
        <div class="r3">
          <label>Labels <input type="text" name="labels" list="task-label-list-new" placeholder="bug, pricing-page" aria-label="Labels, comma separated" size="18"><datalist id="task-label-list-new">${(TASKS_ST?.labels || []).map(l => `<option value="${esc(l)}">`).join('')}</datalist></label>
          <label><input type="checkbox" name="top"> Top of their queue</label>
        </div>
        <label>Serves <select name="goal" aria-label="The goal this task serves"><option value="">No goal</option></select></label>
        <textarea name="body" aria-label="Details" placeholder="Details"></textarea>
        <input type="url" name="link" inputmode="url" autocomplete="off" spellcheck="false" placeholder="Link (pull request, doc)" aria-label="Link">
        ${S.me?.cloud ? '<label class="attach">Attach files <input type="file" name="files" multiple aria-label="Task attachments"></label>' : ''}
        <div class="r3"><button class="primary" type="submit">Create task</button><span class="muted" id="task-create-msg"></span></div>
        <p class="muted hint">You close it. For a human, start the title with a verb.</p>
      </form>
    </div>`;
  $('[data-modal-close]', d).onclick = () => d.close();
  goalOptions().then(goals => {
    const sel = $('#task-create-form select[name=goal]'); if (!sel || !goals.length) return;
    sel.innerHTML = '<option value="">No goal</option>' + goals.map(g =>
      `<option value="${esc(g.id)}">${esc(g.title)} · ${esc(goalOwnerInfo(g.owner).name)}</option>`).join('');
  });
  $('#task-create-form').onsubmit = async ev => {
    ev.preventDefault();
    const form = ev.target, btn = form.querySelector('[type=submit]'), msg = $('#task-create-msg');
    const title = form.title.value.trim(), owner = form.owner.value, body = form.body.value.trim();
    if (!title || !owner) { msg.textContent = 'Choose who this is for.'; return; }
    btn.disabled = true; msg.textContent = 'Creating…';
    const payload = {title, body, owner};
    const labels = form.labels.value.split(',').map(s => s.trim().toLowerCase()).filter(Boolean);
    if (labels.length) payload.labels = labels;
    if (form.top.checked) payload.top = true;
    if (form.link.value.trim()) payload.links = [form.link.value.trim()];
    if (parent) payload.parent_id = parent.id;
    try {
      const goal = form.goal?.value || '';
      if (goal) payload.goal_id = goal;
      await cloudCompose('/v2/tasks', payload, Array.from(form.elements.files?.files || []));
      d.close();
      toast('Task created');
      if (TASKS_ST) await tasksLoad(TASKS_ST);
      await v2Refresh();
    } catch (e) { msg.innerHTML = `<span class="err">${esc(e.message)}</span>`; btn.disabled = false; }
  };
  if (!d.open) d.showModal();
  formFocus(d);
}
function formFocus(root) {
  (root.querySelector('input[name=title], textarea, select') || {}).focus?.();
}
const mergeTaskRows = (...groups) => [...new Map(groups.flat().map(task => [task.id, task])).values()];
const activeTasksPath = (offset = 0) => `/v2/tasks?lane=company&status=${ACTIVE_TASK_STATUSES}&limit=100&offset=${offset}`;
async function tasksLoad(state) {
  const seq = ++state.loadSeq;
  const reloadDone = state.doneLoaded || state.view === 'done';
  state.loading = !(state.tasks || []).some(t => !['done', 'closed'].includes(String(t.status)));
  tasksRender(state);
  const [active, rec, lab] = await Promise.all([
    v2Get(activeTasksPath()),
    v2Get('/v2/routines'), v2Get('/v2/tasks/labels')]);
  if (TASKS_ST !== state || state.loadSeq !== seq) return;
  const finished = (state.tasks || []).filter(t => ['done', 'closed'].includes(String(t.status)));
  state.tasks = mergeTaskRows(active?.tasks || [], finished);
  state.routines = rec?.routines || null;
  state.labels = lab?.labels || [];
  state.loading = false;
  tasksTools(state); tasksRender(state);

  if (state.open) {
    const id = state.open; state.open = '';
    if (!state.tasks.some(t => t.id === id)) {
      const detail = await v2Get(`/v2/tasks/${encodeURIComponent(id)}`);
      if (TASKS_ST !== state || state.loadSeq !== seq) return;
      if (detail?.task) state.tasks = mergeTaskRows(state.tasks, [detail.task]);
    }
    taskModalOpen('t' + id);
  }

  const drain = async next => {
    while (next != null && TASKS_ST === state && state.loadSeq === seq) {
      const page = await v2Get(activeTasksPath(next));
      if (!page || TASKS_ST !== state || state.loadSeq !== seq) return;
      state.tasks = mergeTaskRows(state.tasks, page.tasks || []);
      next = page.next_offset;
      tasksTools(state); tasksRender(state);
    }
  };
  await drain(active?.next_offset);
  if (reloadDone && TASKS_ST === state && state.loadSeq === seq) await tasksLoadDone(state, true);
}
async function tasksLoadDone(state, reset = false) {
  if (TASKS_ST !== state || state.doneLoading || (!reset && state.doneNext == null)) return false;
  state.doneLoading = true;
  tasksRender(state);
  const offset = reset ? 0 : state.doneNext;
  const page = await v2Get(`/v2/tasks?lane=company&status=done,closed&sort=finished&limit=${DONE_CAP}&offset=${offset}`);
  if (TASKS_ST !== state) return false;
  if (page) {
    const keep = (state.tasks || []).filter(t => !['done', 'closed'].includes(String(t.status)));
    const previous = reset ? [] : (state.tasks || []).filter(t => ['done', 'closed'].includes(String(t.status)));
    state.tasks = mergeTaskRows(keep, previous, page.tasks || []);
    state.doneNext = page.next_offset;
    state.doneLoaded = true;
  }
  state.doneLoading = false;
  tasksTools(state); tasksRender(state);
  if (page && state.view === 'done' && state.q && state.doneNext != null && !state.doneDrain) {
    void tasksLoadAllDone(state);
  }
  return !!page;
}
async function tasksLoadAllDone(state) {
  if (state.doneDrain) return;
  state.doneDrain = true;
  try {
    while (TASKS_ST === state && state.doneNext != null) {
      if (!await tasksLoadDone(state)) break;
    }
  } finally { state.doneDrain = false; }
}
function tasksTools(state) {
  const view = $('#task-view');
  if (!view) return;
  if (!view.childElementCount) view.innerHTML = TASK_VIEWS.map(([k, label]) =>
    `<button type="button" data-view="${k}" title="${label}" aria-label="${label}"><span class="nav-icon" aria-hidden="true">${TASK_VIEW_ICONS[k]}</span></button>`).join('');
  for (const button of view.querySelectorAll('[data-view]')) {
    const active = button.dataset.view === state.view;
    button.classList.toggle('cur', active);
    button.setAttribute('aria-pressed', String(active));
  }
  view.onclick = ev => {
    const b = ev.target.closest('[data-view]'); if (!b) return;
    state.view = b.dataset.view;
    tasksRemember(state); tasksTools(state); tasksRender(state);
    if (state.view === 'done' && !state.doneLoaded && !state.doneLoading) void tasksLoadDone(state, true);
  };
  const filters = $('#task-filters');
  if (!filters.childElementCount) filters.innerHTML = TASK_FILTERS.map(([k, label]) =>
    `<button type="button" class="rchip" data-filter="${k}">${label}</button>`).join('');
  for (const button of filters.querySelectorAll('[data-filter]')) {
    const active = button.dataset.filter === state.filter;
    button.classList.toggle('on', active);
    button.setAttribute('aria-pressed', String(active));
  }
  filters.onclick = ev => {
    const b = ev.target.closest('[data-filter]'); if (!b) return;
    state.filter = b.dataset.filter;
    tasksRemember(state); tasksTools(state); tasksRender(state);
  };
  const sel = $('#board-bot');
  sel.innerHTML = '<option value="">Anyone</option>' + taskOwnerOptions('').replace('<option value="">Who is this for?</option>', '');
  const known = [...sel.options].some(o => o.value === state.bot);
  sel.value = known ? state.bot : '';
  state.bot = sel.value;
  sel.onchange = () => {
    state.bot = sel.value;
    tasksRemember(state); tasksFilterCount(state); tasksRender(state);
  };
  const lab = $('#board-label');
  const labels = [...new Set([...(state.labels || []), ...(state.label ? [state.label] : [])])];
  lab.innerHTML = '<option value="">Any label</option>' + labels.map(l => `<option value="${esc(l)}"${l === state.label ? ' selected' : ''}>${esc(l)}</option>`).join('');
  $('#task-label-row').hidden = !labels.length;
  lab.onchange = () => {
    state.label = lab.value;
    tasksRemember(state); tasksFilterCount(state); tasksRender(state);
  };
  tasksFilterCount(state);
}
function tasksFilterCount(state) {
  const button = $('#task-filter');
  if (!button) return;
  const count = Number(state.filter !== 'all') + Number(!!state.bot) + Number(!!state.label);
  button.textContent = count ? `Filter · ${count}` : 'Filter';
  button.classList.toggle('active', !!count);
  button.setAttribute('aria-label', count ? `Filter tasks, ${count} active` : 'Filter tasks');
}
function companyNeedActor(task, need) {
  const me = myActor();
  const candidates = [need?.ask?.from_actor, task?.ask?.from_actor, taskRequester(task), task?.owner];
  return candidates.find(actor => actorSlug(actor) && actor !== me)
    || candidates.find(actor => actor && actor !== me)
    || me;
}
function companyNeedGroups(items) {
  const needOrder = new Map((S.v2.needs || []).map((item, index) => [String(item.id), index]));
  const needById = new Map((S.v2.needs || []).map(item => [String(item.id), item]));
  const groups = new Map();
  for (const it of items) {
    if (!it.task || it.col === 'done' || !taskNeedsMe(it.task)) continue;
    const need = needById.get(String(it.id)), actor = companyNeedActor(it.task, need);
    if (!groups.has(actor)) groups.set(actor, {actor, items: [], firstNeed: Infinity, firstRank: Infinity, updated: ''});
    const group = groups.get(actor);
    group.items.push(it);
    group.firstNeed = Math.min(group.firstNeed, needOrder.get(String(it.id)) ?? Infinity);
    group.firstRank = Math.min(group.firstRank, it.rank == null ? Infinity : Number(it.rank));
    if (String(it.updated || '') > group.updated) group.updated = String(it.updated || '');
  }
  return [...groups.values()].sort((a, b) => a.firstNeed - b.firstNeed || a.firstRank - b.firstRank
    || String(b.updated).localeCompare(String(a.updated)) || actorLabel(a.actor).localeCompare(actorLabel(b.actor)));
}
function companyNeedsHTML(items) {
  const groups = companyNeedGroups(items);
  if (!groups.length) return '<section class="card"><div class="empty">Nothing needs you. Finished work is under Done.</div></section>';
  const row = group => {
    group.items.sort((a, b) => byRank(a, b));
    const slug = actorSlug(group.actor), person = actorPerson(group.actor);
    const href = slug ? `#/bot/${encodeURIComponent(slug)}` : `#/person/${encodeURIComponent(person || S.me?.id || '')}`;
    const face = slug ? avatar(slug, 36, 'needs') : personCircle(actorLabel(group.actor), 36);
    const name = actorLabel(group.actor), count = group.items.length;
    const titles = group.items.slice(0, 3).map(it => it.title).join(' · ')
      + (count > 3 ? ` · ${count - 3} more` : '');
    return `<a class="company-need-actor" href="${esc(href)}" data-need-actor="${esc(group.actor)}" aria-label="Open chat with ${esc(name)}">
      ${face}<span class="company-need-copy"><span class="company-need-name">${esc(name)}<span class="cnt">${count} task${count === 1 ? '' : 's'}</span></span>
      <span class="company-need-titles">${esc(titles)}</span></span>
      <span class="nav-icon company-need-go" aria-hidden="true">chevron_right</span></a>`;
  };
  return `<section class="card company-needs"><header><h2>Needs you</h2></header>${groups.map(row).join('')}</section>`;
}
// Done: everything finished, newest first, a page at a time.
function tasksDoneHTML(items, state) {
  const list = items.filter(it => it.col === 'done' && !isRecurringTask(it.task)).sort(byNewest);   // routine runs live under Routines
  if (state.doneLoading && !list.length) return '<section class="card"><div class="empty">Loading finished tasks…</div></section>';
  if (!list.length) return '<section class="card"><div class="empty">Nothing finished yet.</div></section>';
  return `<section class="card"><div class="v2-group"><h3>Done <span class="muted">${list.length}</span></h3>
      ${list.map(taskRow).join('')}
      ${state.doneNext != null ? '<button class="ghost" type="button" id="board-more">Show more</button>' : ''}</div></section>`;
}
function tasksRender(state) {
  const el = $('#task-body');
  if (!el || TASKS_ST !== state) return;
  if (state.view === 'recurring') el.innerHTML = tasksRecurringHTML(state);
  else {
    const items = taskItems(state);
    el.innerHTML = state.loading && state.view !== 'done' && !items.length
      ? '<section class="card"><div class="empty">Loading tasks…</div></section>'
      : state.view === 'done' ? tasksDoneHTML(items, state)
      : state.view === 'list' ? tasksListHTML(items)
      : state.view === 'board' ? tasksBoardHTML(items) : companyNeedsHTML(items);
  }
  const more = $('#board-more');
  if (more) more.onclick = () => { void tasksLoadDone(state); };
  if (!el.dataset.routineActions) { el.dataset.routineActions = '1'; bindRoutineActions(el); }
  el.onclick = ev => {
    if (ev.target.closest('[data-new-routine],[data-edit-routine],[data-toggle-routine],[data-delete-routine]')) return;
    const chip = ev.target.closest('[data-rfilter]');
    if (chip) {
      state[chip.dataset.rfilter] = chip.dataset.val;
      try { localStorage.setItem('hub.recurring.' + chip.dataset.rfilter, state[chip.dataset.rfilter]); } catch {}
      tasksRender(state);
      return;
    }
    const exp = ev.target.closest('[data-expand-routine]');
    if (exp && !ev.target.closest('a[href^="#/task/"]')) { ev.preventDefault(); toggleRoutineOccurrences(exp); return; }
    const b = ev.target.closest('[data-open-task]'); if (!b) return;
    ev.preventDefault(); taskModalOpen(b.dataset.openTask);
  };
}
