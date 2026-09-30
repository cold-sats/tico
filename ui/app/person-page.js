/* ui/app/person-page.js — The human page (team tree): profile, tasks, Slack
   Classic script: its globals are shared with the other files under ui/app/, loaded in the order index.html lists them. */
'use strict';

// ----------------------------------------------------------------- human page (team tree)
const PERSON_TABS = ['profile', 'slack'];
// The Assistant tab is first, and only on your own page: your private chat with the assistant (ui/assistant.js).
const personTabs = p => S.me?.id === p.id ? ['assistant', ...PERSON_TABS] : PERSON_TABS;
const PERSON_TAB_LABELS = {assistant: 'Assistant', profile: 'Profile', slack: 'Slack'};
function personCanEdit(p) {
  return S.me?.role === 'owner' || S.me?.id === p.id;
}
function fieldEditor(label, value, {placeholder, rows, save}) {
  const current = String(value || '');
  return `<section class="card"><header><h2>${esc(label)}</h2>
      ${save ? `<button class="linkish" type="button" data-edit>Edit</button>` : ''}</header>
    <div data-view><p>${current ? esc(current).replace(/\n/g, '<br>') : '<span class="muted">None set.</span>'}</p></div>
    ${save ? `<form data-edit-form hidden><textarea rows="${rows || 5}" placeholder="${esc(placeholder || '')}">${esc(current)}</textarea>
      <div class="row"><button class="primary" type="submit">Save</button>
        <button class="ghost" type="button" data-cancel>Cancel</button>
        <span class="muted" data-status></span></div></form>` : ''}</section>`;
}
function bindFieldEditor(root, onSave) {
  const view = root.querySelector('[data-view]');
  const form = root.querySelector('[data-edit-form]');
  if (!form) return;
  const area = form.querySelector('textarea');
  root.querySelector('[data-edit]').onclick = () => { form.hidden = false; view.hidden = true; area.focus(); };
  form.querySelector('[data-cancel]').onclick = () => { form.hidden = true; view.hidden = false; };
  form.onsubmit = async ev => {
    ev.preventDefault();
    const status = form.querySelector('[data-status]');
    form.querySelectorAll('button').forEach(b => b.disabled = true);
    status.textContent = 'Saving…';
    try {
      await onSave(area.value);
      form.hidden = true; view.hidden = false;
    } catch (e) { status.innerHTML = `<span class="err">${esc(e.message)}</span>`; }
    finally { form.querySelectorAll('button').forEach(b => b.disabled = false); if (form.hidden) status.textContent = ''; }
  };
}
function pagePerson(id, tab) {
  const p = (S.people || []).find(row => row.id === id && !row.hidden);
  if (!p) { $('#main').innerHTML = `<div class="empty">Unknown human.</div>`; return; }
  orgHistoryVisit('p:' + p.id);
  const tabs = personTabs(p);
  tab = tabs.includes(tab) ? tab : 'profile';
  const reports = (S.people || []).filter(row => row.reports_to === p.id && !row.hidden);
  const bots = (p.bots || []).map(slug => S.emps.find(e => e.name === slug)).filter(Boolean);
  const under = shownEmps().filter(e => e.org_parent === 'p:' + p.id);
  const boss = (S.people || []).find(row => row.id === p.reports_to);
  const edit = personCanEdit(p);
  const about = goalParts(p.about || '');
  $('#main').innerHTML = `<div class="bothead">${personAvatar(p, 52)}
    <div class="botid"><h1>${esc(p.name || p.id)}</h1>
      <ul class="goal-lines head-goals" id="head-goals" aria-label="Goals"></ul>
      ${String(p.goals || '').trim() ? `<div class="role" id="head-standing">${esc(String(p.goals).trim())}</div>` : ''}
    </div></div>
  <div class="tabs bottabs" id="ptabs" role="tablist">
    ${tabs.map(t => `<button data-pt="${t}" role="tab" class="${t === tab ? 'cur' : ''}">${PERSON_TAB_LABELS[t]}</button>`).join('')}
  </div>
  ${tabs.includes('assistant') ? `<div id="pane-assistant" ${tab === 'assistant' ? '' : 'hidden'}>
    <section class="card conv"><header><h2>Assistant</h2></header>
      <div id="assistant-chat"></div></section></div>` : ''}
  <div id="pane-profile" ${tab === 'profile' ? '' : 'hidden'}>
    <section class="card"><header><h2>Contact</h2></header>
      <dl class="bot-setup">
        ${boss ? `<dt>Reports to</dt><dd><a href="#/person/${encodeURIComponent(boss.id)}">${personAvatar(boss, 18)} ${esc(boss.name)}</a></dd>` : ''}
        ${p.email ? `<dt>Email</dt><dd><a href="mailto:${esc(p.email)}">${esc(p.email)}</a></dd>` : ''}
        ${p.slack ? `<dt>Slack</dt><dd>@${esc(p.slack)}</dd>` : ''}
        ${p.phone ? `<dt>Phone</dt><dd><a href="tel:${esc(p.phone)}">${esc(p.phone)}</a></dd>` : ''}
        ${p.bot ? `<dt>Notes go to</dt><dd>${empChip(p.bot)}</dd>` : ''}
      </dl></section>
    ${p.title || p.team || p.about || edit ? `<section class="card" id="person-about"><header><h2>About</h2>
        ${edit ? '<button class="linkish person-edit-btn" type="button" id="person-edit">Edit</button>' : ''}</header>
      <div id="person-id">${p.title || p.team ? `<div class="meta">${esc([...new Set([p.title, p.team ? teamLabel(p.team) : ''].filter(Boolean))].join(' · '))}</div>` : ''}
        ${p.about ? `<div class="role">${esc(about.lead)}${about.rest ? `<span id="goal-rest" hidden> ${esc(about.rest)}</span> <button class="linkish" type="button" id="goal-more" aria-expanded="false">more</button>` : ''}</div>`
          : edit && !p.title ? '<div class="muted">No title or description yet.</div>' : ''}</div></section>` : ''}
    <section class="card tasks" id="person-tasks-card"><header><h2>Tasks</h2>
        <button class="ghost" type="button" id="person-task-add" aria-haspopup="dialog">+ Add task</button></header>
      <div id="person-tasks">Loading…</div></section>
    ${fieldEditor('Goals', p.goals, {placeholder: 'What they are trying to get done.', save: edit})}
    ${fieldEditor('Notes', p.notes, {placeholder: 'Working notes about this human. Visible to humans who can open this profile.', rows: 8, save: edit})}
    ${reports.length ? `<section class="card"><header><h2>Reports</h2></header>
      <div>${reports.map(row => `<a class="chip" href="#/person/${encodeURIComponent(row.id)}">${personAvatar(row, 20)}<span>${esc(firstName(row.name) || row.id)}</span></a>`).join('')}</div></section>` : ''}
    ${(bots.length || under.length) ? `<section class="card"><header><h2>Bots</h2></header>
      <div>${[...new Map([...bots, ...under].map(e => [e.name, e])).values()].map(e => `<a class="chip" href="#/bot/${esc(e.name)}">${avatar(e.name, 20, stateOf(e.name))}<span>${shownName(e)}</span>${runtimeTag(e)}</a>`).join('')}</div></section>` : ''}
  </div>
  <div id="pane-pslack" ${tab === 'slack' ? '' : 'hidden'}>
    <section class="card conv"><header><h2>Tico in Slack</h2></header>
      <div id="person-slack">Loading…</div></section>
  </div>`;
  void headGoalsLoad('human:' + p.id);
  $('#ptabs').onclick = ev => {
    const b = ev.target.closest('[data-pt]'); if (!b) return;
    location.hash = `#/person/${encodeURIComponent(p.id)}${b.dataset.pt === 'profile' ? '' : '/' + b.dataset.pt}`;
  };
  const more = $('#goal-more');
  if (more) more.onclick = () => {
    const rest = $('#goal-rest'), open = rest.hidden;
    rest.hidden = !open; more.textContent = open ? 'less' : 'more'; more.setAttribute('aria-expanded', String(open));
  };
  const cards = $('#pane-profile').querySelectorAll('section.card');
  const goalsCard = [...cards].find(el => el.querySelector('h2')?.textContent === 'Goals');
  const notesCard = [...cards].find(el => el.querySelector('h2')?.textContent === 'Notes');
  if (goalsCard) bindFieldEditor(goalsCard, async text => {
    const row = await post(`/v2/people/${encodeURIComponent(p.id)}`, {goals: text});
    p.goals = row.goals; pagePerson(p.id, 'profile');
  });
  if (notesCard) bindFieldEditor(notesCard, async text => {
    const row = await post(`/v2/people/${encodeURIComponent(p.id)}`, {notes: text});
    p.notes = row.notes; pagePerson(p.id, 'profile');
  });
  // The top of a human's page is their name and goal; the title and
  // description are the About card's, edited in place there.
  const editHead = $('#person-edit');
  if (editHead) editHead.onclick = () => {
    const host = $('#person-id');
    editHead.hidden = true;
    host.innerHTML = `<form class="task person-head-form">
        <input type="text" name="title" maxlength="120" aria-label="Title" placeholder="Title, e.g. Frontend engineer" value="${esc(p.title || '')}">
        <textarea name="about" rows="3" maxlength="2000" aria-label="Description" placeholder="What they do, in a sentence or two.">${esc(p.about || '')}</textarea>
        <div class="row"><button class="primary" type="submit">Save</button><button class="ghost" type="button" data-cancel>Cancel</button>
          <span class="muted" data-status></span></div></form>`;
    const form = host.querySelector('form');
    form.about.focus();
    form.querySelector('[data-cancel]').onclick = () => pagePerson(p.id, tab);
    form.onsubmit = async ev => {
      ev.preventDefault();
      form.querySelectorAll('button').forEach(b => b.disabled = true);
      form.querySelector('[data-status]').textContent = 'Saving…';
      try {
        const row = await post(`/v2/people/${encodeURIComponent(p.id)}`, {title: form.title.value, about: form.about.value});
        p.title = row.title; p.about = row.about;
        pagePerson(p.id, tab);
      } catch (e) {
        form.querySelector('[data-status]').innerHTML = `<span class="err">${esc(e.message)}</span>`;
        form.querySelectorAll('button').forEach(b => b.disabled = false);
      }
    };
  };
  $('#person-task-add').onclick = () => personTaskModal(p);
  void personTasksLoad(p);
  if (tab === 'slack') personSlackLoad(p);
  if (tab === 'assistant') window.assistantChat?.mount($('#assistant-chat'), {get, post, esc, toast, me: S.me});
  else window.assistantChat?.stop();
}
// The human's tasks: what they own, active first, finished behind a toggle. The rows are
// the same as a keeper bot's (v2TaskRow), so Done/Close and the chat button work unchanged;
// v2TaskAct reloads this list after acting while the card is on the page.
let PERSON_TASKS = null;
async function personTasksLoad(p) {
  PERSON_TASKS = p.id;
  const box = $('#person-tasks'); if (!box) return;
  const owner = 'human:' + p.id;
  const d = await v2Get(`/v2/tasks?owner=${encodeURIComponent(owner)}&status=all`);
  if (!$('#person-tasks') || PERSON_TASKS !== p.id) return;
  const all = d?.tasks || [];
  const active = all.filter(t => V2_ACTIVE.includes(String(t.status)));
  const finished = all.filter(t => !V2_ACTIVE.includes(String(t.status)));
  const first = firstName(p.name) || p.id;
  // A human's open task is to do, not "doing" the way a bot's is the moment it is assigned.
  const groups = (list, kinds) => kinds.map(([k, label]) => {
    const rows = list.filter(t => String(t.status) === k);
    return rows.length ? `<div class="v2-group"><h3>${label} <span class="muted">${rows.length}</span></h3>${rows.map(t => v2TaskRow(t, '')).join('')}</div>` : '';
  }).join('');
  $('#person-tasks').innerHTML = (active.length ? groups(active, [['open', 'To do'], ['doing', 'Doing'], ['waiting', 'Waiting']])
      : `<div class="empty">No active tasks. <a href="#" data-person-task-add>Give ${esc(first)} a task</a>.</div>`)
    + (finished.length ? `<details class="person-tasks-done"><summary class="muted">Finished <span class="cnt">${finished.length}</span></summary>${
        groups(finished, [['done', 'Done'], ['declined', 'Declined'], ['closed', 'Closed']])}</details>` : '');
  const link = $('#person-tasks [data-person-task-add]');
  if (link) link.onclick = ev => { ev.preventDefault(); personTaskModal(p); };
}
function personTasksReload() {
  const p = PERSON_TASKS && (S.people || []).find(row => row.id === PERSON_TASKS);
  if (p && $('#person-tasks')) void personTasksLoad(p);
}
// "+ Add task" on a human's page: the give-a-task form in a modal, assigned to them, added by you.
function personTaskModal(p) {
  let d = $('#person-task-modal');
  if (!d) {
    d = document.createElement('dialog'); d.id = 'person-task-modal'; d.className = 'tmodal';
    d.setAttribute('aria-labelledby', 'person-task-title');
    d.addEventListener('click', ev => { if (ev.target === d) d.close(); });
    document.body.appendChild(d);
  }
  d.innerHTML = `<div class="tmodal-head"><span class="who">Give a task</span><span class="spacer"></span>
      <span>assigned to ${esc(firstName(p.name) || p.id)}, added by you</span>
      <button class="ghost tmodal-x" type="button" data-modal-close aria-label="Close">✕</button></div>
    <div class="tmodal-body">
      <form class="task" id="person-task">
        <div class="r1" style="grid-template-columns:1fr"><input type="text" name="title" required aria-label="Title" placeholder="Start with a verb: Email, Ask, Send…"></div>
        <textarea name="body" required aria-label="Details" placeholder="The ask in the first line, then any details."></textarea>
        <div class="r3"><button class="primary" type="submit">Create task</button>
          <button class="ghost" type="button" data-modal-close>Cancel</button><span class="muted" id="person-task-msg"></span></div>
      </form></div>`;
  d.querySelectorAll('[data-modal-close]').forEach(b => b.onclick = () => d.close());
  const form = $('#person-task', d);
  form.onsubmit = async ev => {
    ev.preventDefault();
    const btn = form.querySelector('[type=submit]'), msg = $('#person-task-msg', d);
    const title = form.title.value.trim(), body = form.body.value.trim();
    if (!title) return;
    btn.disabled = true; msg.textContent = 'Creating…';
    try {
      await cloudCompose('/v2/tasks', {title, body, owner: 'human:' + p.id}, []);
      toast(`Task for ${p.name || p.id} created`);
      d.close();
      await v2Refresh();
      personTasksReload();
    } catch (e) { msg.innerHTML = `<span class="err">${esc(e.message)}</span>`; btn.disabled = false; }
  };
  if (!d.open) d.showModal();
  form.title.focus();
}
async function personSlackLoad(p) {
  const el = $('#person-slack'); if (!el) return;
  try {
    const d = await get(`/v2/people/${encodeURIComponent(p.id)}/slack`);
    const threads = d.threads || [];
    if (!threads.length) {
      el.innerHTML = '<div class="empty">No Tico Slack DMs yet. When a bot messages them in Slack (through Tico), the thread lands here, including their replies.</div>';
      return;
    }
    el.innerHTML = threads.map(t => {
      const msgs = t.messages || [];
      return `<div class="conv-bots-one"><div class="conv-run-head">${avatar(t.bot, 20, stateOf(t.bot))}
          <a href="#/bot/${esc(t.bot)}">${esc(t.display_name || t.bot)}</a>
          <span class="spacer" style="flex:1"></span><span class="tnum">${esc(ago(t.last_message_at))}</span></div>
        ${msgs.map(m => `<div class="bubble ${String(m.from_actor || '').startsWith('bot:') ? 'bot reply' : 'you'}">
            <span class="who">${esc(actorLabel(m.from_actor))}</span>
            <div class="md">${safeMd(m.body || '')}</div></div>`).join('') || '<div class="empty">No messages yet.</div>'}
        </div>`;
    }).join('');
  } catch (e) {
    el.innerHTML = `<div class="err">${esc(e.message)}</div>`;
  }
}
