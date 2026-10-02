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
// The full task (#task-modal, a modal dialog) and the side peek (#task-peek, a dialog shown beside the list) draw the
// same content and wire the same clicks.
function taskDialogWire(d) {
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
  d.addEventListener('close', () => { if (!TASK_CHAT || TASK_CHAT.dialog === d) taskChatStop(); taskFilePreviewReset(); });
}
function taskModal() {
  let d = $('#task-modal');
  if (d) return d;
  d = document.createElement('dialog'); d.id = 'task-modal'; d.className = 'tmodal';
  d.addEventListener('click', ev => { if (ev.target === d) d.close(); });
  taskDialogWire(d);
  document.body.appendChild(d);
  return d;
}
// `d` is the full modal unless a caller passes the peek.
async function taskModalOpen(key, d) {
  const state = TASKS_ST; if (!state) return;
  let it = (state.tasks || []).map(taskItem).find(x => x.key === key)
    || [...S.issues.map(issueItem)].find(x => x.key === key);
  if (!it && /^t/.test(key)) {
    const detail = await v2Get(`/v2/tasks/${encodeURIComponent(key.slice(1))}`);
    if (detail?.task) it = taskItem(detail.task);
  }
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
  taskModalShow(it.task, d);
}
// The one way a hub task opens in full: from the board, from a link, from a chat card. In the peek it opens beside the list.
async function taskModalShow(task, d = taskModal()) {
  if (!d) d = taskModal();
  const peek = !!d.dataset.peek;
  taskChatStop();
  taskFilePreviewReset();
  if (d.dataset.task !== String(task.id)) { d.propsErrs = null; d.focusProp = ''; d.liveTask = null; }
  // never draw an older copy of the task over the newer one a save returned
  else if (d.liveTask && Number(task.version) < Number(d.liveTask.version)) task = d.liveTask;
  const seq = d.drawSeq = (d.drawSeq || 0) + 1;
  const typing = d.contains(document.activeElement) && document.activeElement.matches('.task-chat textarea');
  if (peek && TASKS_ST && TASKS_ST.peek !== 't' + task.id && tasksById(TASKS_ST).has(String(task.id))) {
    taskPeekOpen(TASKS_ST, 't' + task.id); return;           // a parent or subtask opened from the peek: the list follows it
  }
  d.dataset.task = task.id;
  d.innerHTML = hubModalHTML(task, taskItem(task), {peek});
  taskModalBind(d, task);
  taskPropFocus(d);
  if (!d.open) {
    // The peek sits beside the list: opening it leaves the focus on the row, so ↑/↓ keep moving through the list.
    const was = document.activeElement;
    if (peek && matchMedia('(max-width:760px)').matches) d.showModal();     // a phone's sheet covers the list: modal
    else if (peek) { d.show(); if (was && was !== document.body && was.isConnected) was.focus({preventScroll: true}); }
    else d.showModal();
  }
  d.scrollTop = 0;
  // the list knows the task; the detail adds its parts, its parent and the comments
  const [detail] = await Promise.all([v2Get(`/v2/tasks/${encodeURIComponent(task.id)}`), taskTypesLoad().catch(() => TASK_TYPES)]);
  if (!detail?.task || !d.open || String(d.dataset.task) !== String(task.id) || d.drawSeq !== seq) return;
  await taskMenuSettled(d);                 // never pull a menu out from under the pointer
  if (!d.open || String(d.dataset.task) !== String(task.id) || d.drawSeq !== seq) return;
  if (d.liveTask && Number(detail.task.version) < Number(d.liveTask.version)) return;   // a save landed since this was asked for
  const full = {...detail.task, children: detail.children || [], parent: detail.parent || null};
  // the redraw keeps the focus where it was (a header button, the title, a property)
  const a = d.contains(document.activeElement) ? document.activeElement : null;
  const keep = !a ? '' : a.matches('[data-modal-close]') ? '[data-modal-close]' : a.matches('[data-task-more]') ? '[data-task-more]' : a.matches('.tmodal-title') ? '.tmodal-title'
    : a.dataset.prop ? `[data-prop="${CSS.escape(a.dataset.prop)}"]` : '';
  d.innerHTML = hubModalHTML(full, taskItem(full), {peek});
  taskModalBind(d, full, true);
  if (keep) $(keep, d)?.focus({preventScroll: true});
  taskPropFocus(d); d.focusProp = '';
  void taskRailLoad(d, full, detail);
  void taskChatLoad(task.id, d, detail);
  if (typing) { const box = $('.task-chat textarea', d); box?.focus(); box?.setSelectionRange(box.value.length, box.value.length); }
}
// After a property saves, the redrawn row gets the focus back.
function taskPropFocus(d) {
  if (d.focusProp) $(`[data-prop="${CSS.escape(d.focusProp)}"]`, d)?.focus({preventScroll: true});
}
// `full`: the task as GET /v2/tasks/{id} answers it (list rows leave out what the rail's Code section needs).
function taskModalBind(d, task, full = false) {
  d.taskAttachments = task.attachments || [];
  d.dataset.version = String(task.version ?? '');
  if (!d.liveTask || String(d.liveTask.id) !== String(task.id) || Number(task.version) >= Number(d.liveTask.version)) d.liveTask = task;
  if (d.taskRail?.id !== String(task.id)) d.taskRail = {id: String(task.id), open: new Set()};
  if (full) d.taskRail.full = task;
  taskRailPaint(d, task); taskRailBind(d, task);
  $('[data-modal-close]', d).onclick = () => d.dataset.peek && TASKS_ST ? taskPeekClose(TASKS_ST) : d.close();
  void taskGoalTitle(d);
  // Each change goes through the dialog's queue (taskSave), one at a time, each with the latest version.
  const change = (body, then, field) => taskSaveQueued(d, String(task.id), body, then, field);
  taskPropsBind(d, task, change);
  d.querySelectorAll('[data-drop-label]').forEach(b => b.onclick = () => change(cur => ({labels: (cur.labels || []).filter(l => l !== b.dataset.dropLabel)}), undefined, 'tags'));
  const link = $('[data-modal-link]', d);
  const addLink = $('[data-link-add]', d);
  if (addLink && link) {
    addLink.onclick = () => { link.hidden = !link.hidden; if (!link.hidden) link.querySelector('input').focus(); };
    link.querySelector('input').onkeydown = ev => { if (ev.key === 'Escape') { ev.preventDefault(); ev.stopPropagation(); link.hidden = true; addLink.focus(); } };
  }
  if (link) link.onsubmit = async ev => {
    ev.preventDefault();
    const url = link.querySelector('input').value.trim(); if (!url) return;
    try {
      await post(`/v2/tasks/${encodeURIComponent(task.id)}/links`, {url});
      const data = await get(`/v2/tasks/${encodeURIComponent(task.id)}`);
      if (TASKS_ST) void tasksLoad(TASKS_ST);
      taskModalShow(data.task, d);
    } catch (e) { toast(e.message, true); }
  };
  d.querySelectorAll('[data-drop-link]').forEach(b => b.onclick = async () => {
    try {
      await post(`/v2/tasks/${encodeURIComponent(task.id)}/links`, {remove: b.dataset.dropLink});
      const data = await get(`/v2/tasks/${encodeURIComponent(task.id)}`);
      taskModalShow(data.task, d);
    } catch (e) { toast(e.message, true); }
  });
  d.querySelectorAll('[data-open-task]').forEach(b => b.onclick = ev => { ev.preventDefault(); void taskModalOpen(b.dataset.openTask, d); });
}
// ---- saving a task's properties. One save at a time per dialog, each with the version the last one returned, so a
// quick second edit never trips over the first. The dialog redraws at once with the task the server sent back; the
// list reloads behind it. A refused save shows its reason (under the properties) until that property next saves.
function taskSaveQueued(d, id, body, then, field) {
  field = field || d.focusProp || (typeof body === 'function' ? 'task' : Object.keys(body).find(k => k !== 'note')) || 'task';
  d.saving = (d.saving || 0) + 1;
  const run = () => taskSave(d, id, body, then, field).finally(() => { d.saving--; });
  return (d.saveQueue = (d.saveQueue || Promise.resolve()).then(run, run));
}
async function taskSave(d, id, body, then, field) {
  const here = () => d.open && String(d.dataset.task) === id;
  let cur = d.liveTask && String(d.liveTask.id) === id ? d.liveTask : null;
  if (!cur) cur = (await v2Get(`/v2/tasks/${encodeURIComponent(id)}`))?.task;
  if (!cur) { toast('That task could not be loaded.', true); return false; }
  if (typeof body === 'function') { body = body(cur); if (!body) return true; }
  if (!d.propsErrs || d.propsErrs.id !== id) d.propsErrs = {id, map: new Map()};
  const errs = d.propsErrs.map;
  try {
    const outcome = body.close ? 'closed' : pipelineActionStatus(cur, body);
    if ((outcome === 'done' || outcome === 'closed') && outcome !== cur.status) {
      const note = await taskOutcomeNote(cur, outcome === 'closed' ? {close: true} : body);
      if (note === null) return false;
      if (note) body = {...body, note};
    }
    const state = d.dataset.peek && TASKS_ST, key = 't' + id;
    const at = state ? tasksVisibleKeys().indexOf(key) : -1;
    const data = await post(`/v2/tasks/${encodeURIComponent(id)}`, {version: cur.version, ...body});
    errs.delete(field);
    if (data.task && String(d.liveTask?.id) === id) d.liveTask = data.task;
    if (here() && then !== false && data.task) void taskModalShow(data.task, d);       // the server's answer, at once
    if (BOT) {
      if (isKeeper(BOT.slug)) void loadBotTasksV2(BOT.slug);
      void loadBotChatTasks(BOT.slug);
    }
    // The list reloads behind it. If the task left the view (done, closed, handed on, declined), the list and the
    // peek move on to the next row.
    if (TASKS_ST) void tasksLoad(TASKS_ST).then(() => { if (state && TASKS_ST === state && state.peek === key) tasksAfterFinish(state, key, at); });
    return true;
  } catch (e) {
    if (!here()) { toast(e.message, true); return false; }
    errs.set(field, e.status === 409 ? 'Changed elsewhere. Showing the latest.' : `Not saved: ${e.message || 'refused'}`);
    const fresh = await v2Get(`/v2/tasks/${encodeURIComponent(id)}`);
    if (fresh?.task && here()) {
      d.liveTask = fresh.task;
      void taskModalShow(fresh.task, d);
      if (TASKS_ST) void tasksLoad(TASKS_ST);
    } else taskPropsMsgPaint(d);
    return false;
  }
}
// ---- comments: one flat list of what was said and what changed, then a box. Not a chat.
// `taskChatStop` and `taskChatLoad` keep their names: the router and the chat cards call them.
let TASK_CHAT = null;
const TASK_DRAFTS = new Map();         // an unsent comment, per task, kept across redraws until it is sent or cleared
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
const TASK_EVENT_WORDS = {step: id => id ? `moved it to ${pipelineStepName(id)}` : 'cleared the step', type: id => `set the type to ${TASK_TYPES.find(type => type.id === id)?.name || id}`, status: s => `moved it to ${STATUS_WORD[s] || s}`, owner: v => `handed it to ${actorLabel(v)}`,
  lane: v => `moved it to the ${v === 'company' ? 'team' : v} lane`, labels: v => { try { const l = JSON.parse(v || '[]'); return l.length ? `set the tags: ${l.join(', ')}` : 'removed the tags'; } catch { return 'changed the tags'; } },
  blocked_by: v => v ? 'marked it blocked' : 'cleared the block', parent_id: v => v ? 'filed it under a parent task' : 'took it out of its parent',
  link: v => v ? `linked ${v}` : 'removed a link', due: v => v ? `set the due date to ${fmt(v)}` : 'cleared the due date',
  lint: v => `noted: ${v}`, note: () => 'left a note'};
function commentLineHTML(x, i, all) {
  if (x.kind === 'event') {
    if (x.field === 'status' && x.old == null) return '';           // created: the header says so
    // A step move already names where the task went; its status change would say it twice.
    if (x.field === 'status' && all?.some(y => y.kind === 'event' && y.field === 'step' && y.new && y.ts === x.ts)) return '';
    const say = TASK_EVENT_WORDS[x.field] ? TASK_EVENT_WORDS[x.field](x.new) : `changed ${x.field}`;
    return `<div class="tcomment sys"><span class="tcomment-who">${commentAuthor(x.actor, x.via)}</span> <span class="muted">${esc(say)}${x.note && x.field !== 'note' ? ` — ${esc(clipLine(x.note, 200))}` : ''}</span>
      <time class="muted tnum" title="${esc(fmt(x.ts))}">${esc(ago(x.ts))}</time></div>`;
  }
  const m = x.message;
  const kind = m.kind === 'ask' ? '<span class="pill needs">question</span>' : m.kind === 'answer' ? '<span class="pill">answer</span>' : '';
  return `<div class="tcomment${String(m.from_actor || '').startsWith('bot:') ? ' bot' : ''}"><div class="tcomment-head"><span class="tcomment-who">${commentAuthor(m.from_actor, m.refs?.via)}</span>${kind}
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
    const box = $('textarea', host);
    box.value = TASK_DRAFTS.get(String(state.id)) || '';
    box.oninput = () => { if (box.value) TASK_DRAFTS.set(String(state.id), box.value); else TASK_DRAFTS.delete(String(state.id)); };
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
    box.value = ''; TASK_DRAFTS.delete(String(state.id)); state.sending = false;
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
// Where the peek's task sits in the list ("3 / 16"); j/k and ↑/↓ move.
function taskPeekPos(id) {
  if (!TASKS_ST || typeof tasksVisibleKeys !== 'function') return '';
  const keys = tasksVisibleKeys(), i = keys.indexOf('t' + id);
  return i < 0 ? '' : `${i + 1} / ${keys.length}`;
}
// The task in full or in the peek. The header: its status (icon and name, as everywhere else), its owner, its age,
// a "…" menu and ✕. Then the title, who added it and when, the properties, the details, Code, Subtasks, Comments.
function hubModalHTML(t, it, opts = {}) {
  const askToYou = taskAskToPerson(t);
  const finished = taskFinished(t);
  // What it waits on: a question to you reads as one; any other waiting note is a quiet line. A blocker is a property.
  const waitText = clipLine(t.blocker?.title && !askToYou ? '' : taskWaitLine(t), 400);
  const waitLabel = askToYou ? needsWho(t) : t.status === 'waiting' ? 'Waiting on' : '';
  const original = taskBody(t).trim() === String(t.title || '').trim() ? '' : taskBody(t);   // a quick subtask's details are its title
  const note = String(t.note || '');
  const statusWord = taskStatusLabel(t);
  const mover = canMove();
  const links = (t.links || []).filter(l => l.kind !== 'pr' && l.kind !== 'worktree');   // those are Code, in the rail
  const files = (t.attachments || []);
  const pos = opts.peek ? taskPeekPos(t.id) : '';
  return `<div class="tmodal-head">${taskStatusIcon(t)}<span class="pill tstatus">${esc(statusWord)}</span>${t.blocked_by && !finished
      ? `<span class="tchip-blocked" title="Blocked by ${esc(t.blocker?.title || 'another task')}">blocked</span>` : ''}
      <span class="tmodal-owner">${actorFace(t.owner, 18)}<span class="who">${esc(actorLabel(t.owner))}</span></span>
      <span class="spacer"></span>${pos ? `<span class="peek-pos tnum" title="J / K or ↑ / ↓ move to the next or previous task">${esc(pos)}</span>` : ''}
      <span class="muted tnum tmodal-age" title="Updated ${esc(fmt(it.updated))}">${esc(ago(it.updated))}</span>
      <button class="ghost peek-btn" type="button" data-task-more aria-haspopup="menu" aria-label="More actions" title="More">${PROP_ICON.more}</button>
      <button class="ghost tmodal-x" type="button" data-modal-close aria-label="Close" title="Close (Esc)">✕</button></div>
    <h2 class="tmodal-title"${opts.peek ? ' tabindex="-1"' : ''}>${esc(t.title)}</h2>
    <div class="muted tmeta">${esc(taskSourceLine(t))} · ${esc(ago(t.created))}${t.goal_id ? ` · <a href="#/goals/${encodeURIComponent(t.goal_id)}" class="task-goal" data-goal-title="${esc(t.goal_id)}">serves a goal</a>` : ''}</div>
    <div class="tmodal-body task-layout">
      <div class="tmodal-main">
      ${waitLabel && waitText ? (askToYou ? `<div class="task-ask"><div class="lbl">${esc(waitLabel)}</div><div class="task-ask-body">${esc(waitText)}</div></div>`
        : `<p class="task-wait"><span class="lbl">${esc(waitLabel)}</span> ${esc(waitText)}</p>`) : ''}
      ${original ? (waitText ? `<details class="task-orig"><summary>Original request</summary><div class="tdesc md">${safeMd(original)}</div></details>`
        : `<div class="tdesc md">${safeMd(original)}</div>`) : (waitText ? '' : '<p class="muted tdesc">No details.</p>')}
      ${note && note.replace(/\s+/g, ' ').trim() !== waitText ? `<details class="task-orig"><summary>Progress</summary><div class="tdesc md">${safeMd(note)}</div></details>` : ''}
      ${(t.acceptance_criteria || []).length ? `<section class="tsec"><h3 class="rail-h">Done looks like</h3><ul class="tcriteria">${t.acceptance_criteria.map(a => `<li>${esc(a)}</li>`).join('')}</ul></section>` : ''}
      <section class="tsec task-links"><h3 class="rail-h">Links &amp; files<button type="button" class="prop-add" data-link-add aria-label="Add a link" title="Add a link">${TL_ICON.plus}</button></h3>
        ${links.length || files.length ? `<div class="tlinks">${links.map(l => `<span class="tlink ${esc(l.kind)} ${esc(l.state || '')}"><a href="${esc(l.url)}" target="_blank" rel="noopener">${esc(l.title || l.url)}</a>${l.state && l.state !== 'open' ? ` · ${esc(l.state)}` : ''}${mover ? `<button type="button" class="x" data-drop-link="${esc(l.id)}" aria-label="Remove link">×</button>` : ''}</span>`).join('')}
          ${files.map(f => `<span class="tlink file"><button class="linkish" type="button" data-preview-file="${esc(f.id)}" data-preview-name="${esc(f.name)}" aria-label="View ${esc(f.name)}">${esc(f.name)}</button><a href="${API}/v2/files/${encodeURIComponent(f.id)}" download aria-label="Download ${esc(f.name)}">↓</a></span>`).join('')}</div>` : ''}
        <form class="inline task-link-add" data-modal-link hidden><input type="url" inputmode="url" autocomplete="off" spellcheck="false" placeholder="https://…" aria-label="Add a link"></form></section>
      <div class="task-file-preview" data-task-file-preview hidden></div>
      </div>
      <aside class="task-side" aria-label="Details">
        <section class="task-props" data-task-props aria-label="Properties">${taskPropsHTML(t, opts)}</section>
        <div class="task-rail" data-task-rail hidden></div>
      </aside>
      <section class="task-chat" aria-label="Comments"><p class="muted" role="status">Loading comments…</p></section>
    </div>`;
}
