/* ui/app/task-modal.js — The task modal, its file preview and its comment thread
   Classic script: its globals are shared with the other files under ui/app/, loaded in the order index.html lists them. */
'use strict';

// ---- the task modal: one item, in full, with what you can do to it
let TASK_FILE_PREVIEW = null;
function taskFilePreviewReset() {
  if (!TASK_FILE_PREVIEW) return;
  TASK_FILE_PREVIEW.abort.abort();
  if (TASK_FILE_PREVIEW.url) URL.revokeObjectURL(TASK_FILE_PREVIEW.url);
  TASK_FILE_PREVIEW = null;
}
function taskFilePreviewKind(file) {
  const name = String(file.name || '').toLowerCase();
  if (/\.(md|markdown)$/.test(name)) return ['markdown', 'text/plain'];
  if (/\.csv$/.test(name) || /^text\/csv\b/i.test(file.mime || '')) return ['csv', 'text/csv'];
  if (/\.(txt|text|json|log|yaml|yml)$/.test(name)) return ['text', 'text/plain'];
  if (/\.(png|jpe?g|gif|webp)$/.test(name)) return ['image', /\.png$/.test(name) ? 'image/png' : /\.gif$/.test(name) ? 'image/gif' : /\.webp$/.test(name) ? 'image/webp' : 'image/jpeg'];
  if (/\.pdf$/.test(name)) return ['pdf', 'application/pdf'];
  if (/\.(mp4|webm|mov)$/.test(name)) return ['video', /\.webm$/.test(name) ? 'video/webm' : /\.mov$/.test(name) ? 'video/quicktime' : 'video/mp4'];
  if (/\.(mp3|m4a|wav|ogg)$/.test(name)) return ['audio', /\.wav$/.test(name) ? 'audio/wav' : /\.ogg$/.test(name) ? 'audio/ogg' : /\.m4a$/.test(name) ? 'audio/mp4' : 'audio/mpeg'];
  return [null, null];
}
async function taskFilePreviewOpen(file, dialog) {
  const box = $('[data-task-file-preview]', dialog);
  if (!box || !file.id) return;
  taskFilePreviewReset();
  const path = `${API}/v2/files/${encodeURIComponent(file.id)}`;
  box.hidden = false;
  box.innerHTML = `<div class="task-file-preview-head"><strong>${esc(file.name || 'Attachment')}</strong><span class="spacer"></span><a href="${path}" download>Download</a><button type="button" class="ghost" data-close-file-preview aria-label="Close attachment preview">✕</button></div><div data-task-file-content role="status">Loading preview…</div>`;
  const state = TASK_FILE_PREVIEW = {abort: new AbortController(), url: null};
  try {
    const response = await fetch(path, {cache: 'no-store', signal: state.abort.signal});
    if (!response.ok) throw new Error(response.status === 403 ? 'You do not have access to this file.' : `Preview unavailable (${response.status}).`);
    const encodedName = response.headers.get('Content-Disposition')?.match(/filename\*=UTF-8''([^;]+)/i)?.[1];
    if (encodedName) { try { file = {...file, name: decodeURIComponent(encodedName)}; } catch {} }
    const [kind, type] = taskFilePreviewKind(file);
    if (TASK_FILE_PREVIEW !== state || !box.isConnected || !dialog.open) return;
    $('.task-file-preview-head strong', box).textContent = file.name || 'Attachment';
    if (!kind) { $('[data-task-file-content]', box).textContent = 'This file cannot be shown here. Download it to open it.'; return; }
    const blob = await response.blob();
    if (TASK_FILE_PREVIEW !== state || !box.isConnected || !dialog.open) return;
    const content = $('[data-task-file-content]', box);
    if (kind === 'markdown' || kind === 'text' || kind === 'csv') {
      const raw = await blob.text();
      if (TASK_FILE_PREVIEW !== state || !box.isConnected || !dialog.open) return;
      if (kind === 'csv') { content.replaceChildren(csvView(raw)); return; }
      content.innerHTML = kind === 'markdown' ? `<div class="md">${safeMd(raw)}</div>` : `<pre>${esc(raw)}</pre>`;
      return;
    }
    state.url = URL.createObjectURL(new Blob([blob], {type}));
    const src = esc(state.url);
    content.innerHTML = kind === 'image' ? `<img src="${src}" alt="${esc(file.name || 'Attachment')}">`
      : kind === 'video' ? `<video src="${src}" controls playsinline preload="metadata"></video>`
      : kind === 'audio' ? `<audio src="${src}" controls preload="metadata"></audio>`
      : `<iframe src="${src}" sandbox title="${esc(file.name || 'PDF attachment')}"></iframe>`;
  } catch (error) {
    if (TASK_FILE_PREVIEW === state && !state.abort.signal.aborted && box.isConnected) {
      $('[data-task-file-content]', box).innerHTML = `<span class="err">${esc(error.message)}</span>`;
    }
  }
}
function taskModal() {
  let d = $('#task-modal');
  if (d) return d;
  d = document.createElement('dialog'); d.id = 'task-modal'; d.className = 'tmodal';
  d.addEventListener('click', ev => { if (ev.target === d) d.close(); });
  d.addEventListener('click', ev => {
    const close = ev.target.closest('[data-close-file-preview]');
    if (close) { taskFilePreviewReset(); $('[data-task-file-preview]', d).hidden = true; return; }
    const button = ev.target.closest('[data-preview-file]');
    if (button) {
      const file = (d.taskAttachments || []).find(f => f.id === button.dataset.previewFile)
        || {id: button.dataset.previewFile, name: button.dataset.previewName};
      void taskFilePreviewOpen(file, d); return;
    }
    const anchor = ev.target.closest('a[href]');
    if (!anchor || anchor.hasAttribute('download')) return;
    const url = new URL(anchor.href, location.href);
    const match = url.origin === location.origin && url.pathname.match(/^\/api\/v2\/files\/([^/]+)$/);
    if (!match) return;
    ev.preventDefault();
    const id = decodeURIComponent(match[1]);
    const file = (d.taskAttachments || []).find(f => f.id === id)
      || {id, name: anchor.textContent.trim()};
    void taskFilePreviewOpen(file, d);
  });
  d.addEventListener('issue-acted', () => d.close());
  d.addEventListener('close', () => { taskChatStop(); taskFilePreviewReset(); });
  document.body.appendChild(d);
  return d;
}
function taskModalOpen(key) {
  const state = TASKS_ST; if (!state) return;
  const it = (state.tasks || []).map(taskItem).find(x => x.key === key)
    || [...S.issues.map(issueItem)].find(x => x.key === key);
  if (!it) return;
  if (it.kind === 'schedule') {
    const d = taskModal();
    d.innerHTML = `<h2>${esc(it.title)}</h2><p>Scheduled for ${esc(fmt(it.schedule.next))}</p><button data-modal-close>Close</button>`;
    $('[data-modal-close]', d).onclick = () => d.close();
    if (!d.open) d.showModal();
    return;
  }
  if (it.kind === 'issue') {
    taskChatStop();
    const d = taskModal();
    d.innerHTML = issueModalHTML(it.issue);
    $('[data-modal-close]', d).onclick = () => d.close();
    d.querySelectorAll('[data-modal-issue]').forEach(b => {
      b.onclick = () => issueComposer($('.issue-compose', d), it.issue.number, b.dataset.modalIssue);
    });
    if (!d.open) d.showModal();
    return;
  }
  taskModalShow(it.task);
}
// The one way a hub task opens in full: from the board, from a link, from a chat card.
async function taskModalShow(task) {
  taskChatStop();
  taskFilePreviewReset();
  const d = taskModal();
  d.dataset.task = task.id;
  d.innerHTML = hubModalHTML(task, taskItem(task));
  taskModalBind(d, task);
  if (!d.open) d.showModal();
  d.scrollTop = 0;
  // the list knows the task; the detail adds its parts, its parent and the comments
  const detail = await v2Get(`/v2/tasks/${encodeURIComponent(task.id)}`);
  if (!detail?.task || !d.open || d.dataset.task !== task.id) return;
  const full = {...detail.task, children: detail.children || [], parent: detail.parent || null};
  d.innerHTML = hubModalHTML(full, taskItem(full));
  taskModalBind(d, full);
  void taskChatLoad(task.id, d, detail);
}
function taskModalBind(d, task) {
  d.taskAttachments = task.attachments || [];
  $('[data-modal-close]', d).onclick = () => d.close();
  void taskGoalTitle(d);
  d.querySelectorAll('[data-modal-task]').forEach(b => {
    b.onclick = async () => {
      if (await v2TaskAct(b, task.id, {version: task.version, ...(b.dataset.modalCloseTask ? {close: true} : {status: b.dataset.modalTask})})) {
        d.close();
        if (TASKS_ST) await tasksLoad(TASKS_ST);
      }
    };
  });
  const change = async (body, then) => {
    try {
      if (body.status === 'done') {
        const note = await taskOutcomeNote(task, body);
        if (note === null) return false;
        if (note) body = {...body, note};
      }
      const data = await post(`/v2/tasks/${encodeURIComponent(task.id)}`, {version: task.version, ...body});
      if (TASKS_ST) await tasksLoad(TASKS_ST);
      if (BOT) {
        if (isKeeper(BOT.slug)) void loadBotTasksV2(BOT.slug);
        void loadBotChatTasks(BOT.slug);
      }
      if (then !== false && d.open && d.dataset.task === task.id) taskModalShow(data.task);
      return true;
    } catch (e) { toast(e.message, true); return false; }
  };
  d.querySelectorAll('[data-modal-status]').forEach(sel => sel.onchange = async () => {
    if (!await change({status: sel.value})) sel.value = task.status;
  });
  d.querySelectorAll('[data-modal-blocked]').forEach(sel => sel.onchange = () => change({blocked_by: sel.value}));
  d.querySelectorAll('[data-modal-parent]').forEach(sel => sel.onchange = () => change({parent_id: sel.value}));
  const labels = $('[data-modal-labels]', d);
  if (labels) labels.onsubmit = ev => {
    ev.preventDefault();
    const raw = labels.querySelector('input').value;
    const list = [...(task.labels || []), ...raw.split(',').map(s => s.trim().toLowerCase()).filter(Boolean)];
    void change({labels: [...new Set(list)]});
  };
  d.querySelectorAll('[data-drop-label]').forEach(b => b.onclick = () => change({labels: (task.labels || []).filter(l => l !== b.dataset.dropLabel)}));
  const link = $('[data-modal-link]', d);
  if (link) link.onsubmit = async ev => {
    ev.preventDefault();
    const url = link.querySelector('input').value.trim(); if (!url) return;
    try {
      await post(`/v2/tasks/${encodeURIComponent(task.id)}/links`, {url});
      const data = await get(`/v2/tasks/${encodeURIComponent(task.id)}`);
      if (TASKS_ST) void tasksLoad(TASKS_ST);
      taskModalShow(data.task);
    } catch (e) { toast(e.message, true); }
  };
  d.querySelectorAll('[data-drop-link]').forEach(b => b.onclick = async () => {
    try {
      await post(`/v2/tasks/${encodeURIComponent(task.id)}/links`, {remove: b.dataset.dropLink});
      const data = await get(`/v2/tasks/${encodeURIComponent(task.id)}`);
      taskModalShow(data.task);
    } catch (e) { toast(e.message, true); }
  });
  d.querySelectorAll('[data-open-task]').forEach(b => b.onclick = ev => { ev.preventDefault(); taskModalOpen(b.dataset.openTask); });
  d.querySelectorAll('[data-modal-child]').forEach(b => b.onclick = () => { d.close(); openTaskCreate(task.owner, {parent: task}); });
}
// ---- comments: one flat list of what was said and what changed, then a box. Not a chat.
// `taskChatStop` and `taskChatLoad` keep their names: the router and the chat cards call them.
let TASK_CHAT = null;
function taskChatStop() {
  if (TASK_CHAT) clearInterval(TASK_CHAT.poll);
  TASK_CHAT = null;
}
function taskChatCurrent(state) { return TASK_CHAT === state && state.dialog.open; }
const commentAuthor = (a, via) => {
  const pid = actorPerson(a);
  // The Assistant acted for this person (docs/assistant.md): "<name> (via Assistant)".
  const by = via === 'assistant' ? ' (via Assistant)' : '';
  if (pid) return `${personCircle(personDisplay(pid), 16)}<span class="who">${esc((pid === S.me?.id ? 'You' : personDisplay(pid)) + by)}</span>`;
  if (a === 'keeper') return `<span class="who">${esc(assistantName())}</span>`;
  const slug = actorSlug(a);
  return `${slug ? avatar(slug, 16, stateOf(slug)) : ''}<span class="who">${esc(actorLabel(a))}</span>`;
};
const TASK_EVENT_WORDS = {status: s => `moved it to ${STATUS_WORD[s] || s}`, owner: v => `handed it to ${actorLabel(v)}`,
  lane: v => `moved it to the ${v === 'company' ? 'team' : v} lane`, labels: v => { try { const l = JSON.parse(v || '[]'); return l.length ? `set the labels: ${l.join(', ')}` : 'removed the labels'; } catch { return 'changed the labels'; } },
  blocked_by: v => v ? 'marked it blocked' : 'cleared the block', parent_id: v => v ? 'filed it under a parent task' : 'took it out of its parent',
  link: v => v ? `linked ${v}` : 'removed a link', due: v => v ? `set the due date to ${fmt(v)}` : 'cleared the due date',
  lint: v => `noted: ${v}`, note: () => 'left a note'};
function commentLineHTML(x) {
  if (x.kind === 'event') {
    if (x.field === 'status' && x.old == null) return '';           // created: the header says so
    const say = TASK_EVENT_WORDS[x.field] ? TASK_EVENT_WORDS[x.field](x.new) : `changed ${x.field}`;
    return `<div class="tcomment sys"><span class="tcomment-who">${commentAuthor(x.actor, x.via)}</span> <span class="muted">${esc(say)}${x.note && x.field !== 'note' ? ` — ${esc(clipLine(x.note, 200))}` : ''}</span>
      <time class="muted tnum" title="${esc(fmt(x.ts))}">${esc(ago(x.ts))}</time></div>`;
  }
  const m = x.message;
  const kind = m.kind === 'ask' ? '<span class="pill needs">question</span>' : m.kind === 'answer' ? '<span class="pill">answer</span>' : '';
  return `<div class="tcomment"><div class="tcomment-head"><span class="tcomment-who">${commentAuthor(m.from_actor, m.refs?.via)}</span>${kind}
      ${m.refs?.quiet ? '<span class="muted" title="Saved for the bot\'s next run on this task">saved</span>' : ''}
      <span class="spacer"></span><time class="muted tnum" title="${esc(fmt(m.created))}">${esc(ago(m.created))}</time></div>
    <div class="md">${safeMd(m.body || '')}</div>
    ${S.me?.cloud ? (m.refs?.attachments || []).map(f => `<span class="tlink file"><button class="linkish" type="button" data-preview-file="${esc(f.id)}" data-preview-name="${esc(f.name)}" aria-label="View ${esc(f.name)}">${esc(f.name)}</button><a href="${API}/v2/files/${encodeURIComponent(f.id)}" download aria-label="Download ${esc(f.name)}">↓</a></span>`).join(' ') : ''}</div>`;
}
function taskCommentsRender(state, data) {
  const host = state.host;
  const lines = [
    ...(data.comments || data.messages || []).filter(m => ['say', 'ask', 'answer'].includes(m.kind)).map(m => ({kind: 'comment', ts: m.created, message: m})),
    ...(data.events || []).map(e => ({kind: 'event', ts: e.ts, ...e})),
  ].sort((a, b) => String(a.ts).localeCompare(String(b.ts)));
  if (!$('form', host)) {
    host.innerHTML = `<h3>Comments</h3>
      <div class="task-comments" role="log" aria-live="polite"></div>
      <form><textarea rows="3" maxlength="4000" required aria-label="Add a comment" placeholder="Add a comment…"></textarea>
        <div class="row"><button class="primary" type="submit">Comment</button><span class="muted" data-task-chat-status role="status"></span></div></form>`;
    $('form', host).onsubmit = ev => { ev.preventDefault(); void taskCommentSend(state); };
  }
  const html = lines.map(commentLineHTML).join('') || '<p class="muted">Nothing said yet.</p>';
  if (html !== state.rendered) {
    const thread = $('.task-comments', host);
    const atEnd = !state.rendered || thread.scrollTop + thread.clientHeight >= thread.scrollHeight - 40;
    thread.innerHTML = html;
    if (atEnd) thread.scrollTop = thread.scrollHeight;
    state.rendered = html;
  }
}
async function taskChatRead(state) {
  if (!taskChatCurrent(state) || state.sending || state.reading) return;
  state.reading = true;
  try {
    const data = await get(state.path);
    if (taskChatCurrent(state) && !state.sending) taskCommentsRender(state, data);
  } catch (e) {
    if (!taskChatCurrent(state)) return;
    if ([400, 403, 404].includes(e.status)) {state.stopped = true; clearInterval(state.poll);}
    const status = $('[data-task-chat-status]', state.host);
    if (status) status.textContent = `Unable to refresh: ${e.message}`;
    else state.host.innerHTML = `<p class="err" role="status">Comments unavailable: ${esc(e.message)}</p>`;
  } finally { state.reading = false; }
}
async function taskChatLoad(id, dialog, data = null) {
  const state = TASK_CHAT = {dialog, host: $('.task-chat', dialog),
    path: `/v2/tasks/${encodeURIComponent(id)}`, id, poll: 0, sending: false, reading: false};
  if (data) taskCommentsRender(state, data); else await taskChatRead(state);
  if (taskChatCurrent(state) && !state.stopped) state.poll = setInterval(() => {
    if (!document.hidden) void taskChatRead(state);
  }, 8000);
}
async function taskCommentSend(state) {
  if (!taskChatCurrent(state) || state.sending) return;
  const box = $('textarea', state.host), text = box.value.trim();
  if (!text) { box.focus(); return; }
  state.sending = true;
  const button = $('button', state.host), status = $('[data-task-chat-status]', state.host);
  button.disabled = box.disabled = true; button.textContent = 'Sending…'; status.textContent = '';
  try {
    const data = await post(`/v2/tasks/${encodeURIComponent(state.id)}/comments`, {text});
    if (!taskChatCurrent(state)) return;
    box.value = ''; state.sending = false;
    await taskChatRead(state);
    status.textContent = data.woke ? '' : 'Saved. The bot reads it on its next run on this task.';
  } catch (e) {
    if (taskChatCurrent(state)) status.textContent = `Not saved: ${e.message}`;
  } finally {
    state.sending = false;
    if (taskChatCurrent(state)) { button.disabled = box.disabled = false; button.textContent = 'Comment'; }
  }
}
async function taskChatSend(state) { return taskCommentSend(state); }
function issueModalHTML(i) {
  const running = new Set((S.status?.active || []).map(a => a.issue));
  const tag = boardTag(i, running);
  return `<div class="tmodal-head">${avatar(i.owner, 22, stateOf(i.owner))}<span class="who">${empName(i.owner)}</span>
      <span class="mono muted">#${esc(i.number)}</span>${statusPill(i)}${i.priority && i.priority !== 'p2' ? prioPill(i) : ''}
      ${tag ? `<span class="tag">${esc(tag)}</span>` : ''}${isRecurringIssue(i) ? '<span class="gl" title="a routine">⟳</span>' : ''}
      <span class="spacer"></span><span class="muted tnum">${esc(ago(i.state === 'CLOSED' ? i.closedAt : i.updatedAt))}</span>
      <button class="ghost tmodal-x" type="button" data-modal-close aria-label="Close">✕</button></div>
    <h2 class="tmodal-title">${esc(i.title)}</h2>
    <div class="tmodal-body">${i.needs_human ? needsYouBlock([i])
      : i.body ? `<div class="q">${esc(i.body)}</div>` : i.last_comment ? `<div class="q">${esc(i.last_comment)}</div>` : '<div class="muted">No details yet.</div>'}
      <div class="issue-actions">
        ${i.state === 'OPEN' ? `<button class="linkish" type="button" data-modal-issue="comment">Comment</button>
          <button class="linkish danger" type="button" data-modal-issue="close">Close</button>` : '<span class="muted">Closed</span>'}
        <a class="github" href="${esc(i.url)}" target="_blank" rel="noopener">GitHub ↗</a></div>
      <div class="issue-compose" hidden></div></div>`;
}
function taskPickOptions(exclude, selected = '') {
  const open = (TASKS_ST?.tasks || []).filter(t => !['done', 'closed'].includes(String(t.status)) && t.id !== exclude)
    .slice().sort((a, b) => String(a.title).localeCompare(String(b.title)));
  return `<option value="">—</option>` + open.map(t =>
    `<option value="${esc(t.id)}"${t.id === selected ? ' selected' : ''}>${esc(clipLine(t.title, 70))} · ${esc(actorLabel(t.owner))}</option>`).join('');
}
function hubModalHTML(t, it) {
  const open = !['done', 'closed'].includes(String(t.status || ''));
  const askToYou = taskAskToPerson(t);
  const waitText = clipLine(taskWaitLine(t), 400);
  const waitLabel = askToYou ? needsWho(t) : t.blocker ? 'Blocked by' : (t.status === 'waiting' ? 'Waiting on' : '');
  const original = taskBody(t);
  const note = String(t.note || '');
  const statusWord = askToYou ? needsWho(t) : (STATUS_WORD[t.status] || t.status || '');
  const mover = canMove();
  const statuses = ['open', 'doing', 'waiting', 'done', 'declined'];
  const links = (t.links || []);
  const files = (t.attachments || []);
  return `<div class="tmodal-head">${it.slug ? avatar(it.slug, 22, stateOf(it.slug)) : personCircle(actorLabel(t.owner), 22)}
      <span class="who">${esc(actorLabel(t.owner))}</span>
      <span class="pill ${askToYou ? 'needs' : t.status === 'waiting' ? 'waiting' : (V2_PILL[t.status] ?? '')}">${esc(statusWord)}</span>
      <span class="spacer"></span><span class="muted tnum">${esc(ago(it.updated))}</span>
      <button class="ghost tmodal-x" type="button" data-modal-close aria-label="Close">✕</button></div>
    <h2 class="tmodal-title">${esc(t.title)}</h2>
    <div class="tmodal-body">
      <div class="muted tmeta">${esc(taskSourceLine(t))} ${esc(ago(t.created))}${t.due ? ` · due ${esc(fmt(t.due))}` : ''}${t.parent ? ` · part of <button class="linkish" type="button" data-open-task="t${esc(t.parent.id)}">${esc(clipLine(t.parent.title, 60))}</button>` : ''}${t.goal_id ? ` · <a href="#/goals/${encodeURIComponent(t.goal_id)}" class="task-goal" data-goal-title="${esc(t.goal_id)}">serves a goal</a>` : ''}</div>
      ${waitLabel && waitText ? `<div class="task-ask"><div class="lbl">${esc(waitLabel)}</div><div class="task-ask-body">${esc(waitText)}</div></div>` : ''}
      ${original ? (waitText ? `<details class="task-orig"><summary>Original request</summary><div class="q md">${safeMd(original)}</div></details>`
        : `<div class="q md">${safeMd(original)}</div>`) : (waitText ? '' : '<div class="muted">No details.</div>')}
      ${note && note.replace(/\s+/g, ' ').trim() !== waitText ? `<details class="task-orig"><summary>Progress</summary><div class="q md">${safeMd(note)}</div></details>` : ''}
      ${(t.acceptance_criteria || []).length ? `<div class="tsection"><div class="lbl">Done looks like</div><ul class="tcriteria">${t.acceptance_criteria.map(a => `<li>${esc(a)}</li>`).join('')}</ul></div>` : ''}
      <div class="tsection trow2">
        <div><div class="lbl">Labels</div><div class="tlabels">${(t.labels || []).map(l => `<span class="tlabel">${esc(l)}${mover ? `<button type="button" class="x" data-drop-label="${esc(l)}" aria-label="Remove ${esc(l)}">×</button>` : ''}</span>`).join('') || '<span class="muted">none</span>'}
          ${mover ? `<form class="inline" data-modal-labels><input type="text" list="task-label-list" placeholder="add a label" aria-label="Add a label" size="12"><datalist id="task-label-list">${(TASKS_ST?.labels || []).map(l => `<option value="${esc(l)}">`).join('')}</datalist></form>` : ''}</div></div>
        <div><div class="lbl">Links &amp; files</div><div class="tlinks">${links.map(l => `<span class="tlink ${esc(l.kind)} ${esc(l.state || '')}"><a href="${esc(l.url)}" target="_blank" rel="noopener">${esc(l.title || l.url)}</a>${l.state && l.state !== 'open' ? ` · ${esc(l.state)}` : ''}${mover ? `<button type="button" class="x" data-drop-link="${esc(l.id)}" aria-label="Remove link">×</button>` : ''}</span>`).join('')}
          ${files.map(f => `<span class="tlink file"><button class="linkish" type="button" data-preview-file="${esc(f.id)}" data-preview-name="${esc(f.name)}" aria-label="View ${esc(f.name)}">${esc(f.name)}</button><a href="${API}/v2/files/${encodeURIComponent(f.id)}" download aria-label="Download ${esc(f.name)}">↓</a></span>`).join('')}
          ${!links.length && !files.length ? '<span class="muted">none</span>' : ''}
          <form class="inline" data-modal-link><input type="url" inputmode="url" autocomplete="off" spellcheck="false" placeholder="https://…" aria-label="Add a link" size="22"></form></div></div>
      </div>
      <div class="task-file-preview" data-task-file-preview hidden></div>
      ${(t.children || []).length || t.parts?.total ? `<div class="tsection"><div class="lbl">Parts ${t.parts?.total ? `<span class="muted">${t.parts.done} of ${t.parts.total} done</span>` : ''}</div>
        <div class="tchildren">${(t.children || []).map(k => `<button class="trow-btn small" type="button" data-open-task="t${esc(k.id)}"><span class="trow-who">${actorSlug(k.owner) ? avatar(actorSlug(k.owner), 16, stateOf(actorSlug(k.owner))) : personCircle(actorLabel(k.owner), 16)}</span><span class="ttl">${esc(k.title)}</span><span class="pill ${V2_PILL[k.status] ?? ''}">${esc(STATUS_WORD[k.status] || k.status)}</span></button>`).join('')}</div></div>` : ''}
      ${mover && open ? `<div class="tsection tcontrols">
        <label>Status <select data-modal-status aria-label="Status">${statuses.map(s => `<option value="${s}"${s === t.status ? ' selected' : ''}>${esc(STATUS_WORD[s] || s)}</option>`).join('')}</select></label>
        <label>Blocked by <select data-modal-blocked aria-label="Blocked by">${taskPickOptions(t.id, t.blocked_by || '')}</select></label>
        <label>Part of <select data-modal-parent aria-label="Parent task">${taskPickOptions(t.id, t.parent_id || '')}</select></label>
        <button class="ghost" type="button" data-modal-child>Add a part</button>
      </div>` : ''}
      <div class="issue-actions">
        ${open ? `<button class="linkish" type="button" data-modal-task="done">Done</button>
          <button class="linkish danger" type="button" data-modal-task="closed" data-modal-close-task="1">Close</button>` : '<span class="muted">Finished</span>'}
      </div>
      <section class="task-chat" aria-label="Comments"><p class="muted" role="status">Loading comments…</p></section>
    </div>`;
}
