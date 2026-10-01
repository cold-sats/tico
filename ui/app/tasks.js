/* ui/app/tasks.js — Tasks: columns, filters, cards, rows, and the goal pickers
   Classic script: its globals are shared with the other files under ui/app/, loaded in the order index.html lists them. */
'use strict';

// ----------------------------------------------------------------- tasks (#/tasks)
// One page for every piece of work the team owes: Tico's tasks, shown as a **List**, as a
// **Board**, as **Done**, or as **Routines** (the routines themselves, one row each).
// Board and Issues used to be two sidebar entries; they are one, and the view
// is a toggle that is remembered. `#/board`, `#/issues` and `#/recurring` open the matching view.
// No priority, every task has a rank
// in its owner's queue. Labels stand in for projects. A task's thread is comments, not chat:
// one flat list with the author on every line.
// The Product lane (its board, columns and lane switch) is retired; the page
// shows team tasks only.
const COMPANY_COLS = [
  ['needs',   'Needs you', 'Waiting on a human, blocked, or declined back'],
  ['waiting', 'Waiting', 'Waiting on the dependency shown in the task'],
  ['doing',   'Doing',     'Starting or being worked on now'],
  ['scheduled', 'Scheduled', 'One-off tasks scheduled to start in the future'],
];
const STATUS_WORD = {open: 'open', doing: 'doing', waiting: 'waiting', review: 'in review', ready: 'ready to ship',
                     done: 'done', closed: 'closed', declined: 'declined'};
const BOARD_COLS = [...COMPANY_COLS, ['done', 'Done', 'Finished in the last 7 days']];   // legacy name, kept for the routine rows
// "I like my 'for you' view of tasks, but IMO it should be a person icon to the
// left of the list view. and we still want list and kanban views in the tasks menu bar." For you
// is who needs you, grouped by bot; List and Board are every open task by column.
const TASK_VIEWS = [['foryou', 'Needs you'], ['list', 'List'], ['board', 'Board'], ['recurring', 'Routines'], ['done', 'Done']];
const TASK_VIEW_ICONS = {foryou: 'person', list: 'view_list', board: 'view_kanban', recurring: 'replay', done: 'check_circle'};
const TASK_FILTERS = [['all', 'Everything'], ['mine', 'Mine'], ['asked', 'Asked by me']];
const DONE_CAP = 20;                // The Done list shows 20 at a time
const ACTIVE_TASK_STATUSES = 'open,doing,waiting,review,ready,declined';
let TASKS_ST = null;
const teamOf = slug => S.emps.find(e => e.name === slug)?.team || '';
const isRecurringIssue = i => (i.labels || []).some(l => /^type:recurring$/i.test(l)) || /_Created by dispatcher from schedule/.test(i.body || '');
const hasFiles = i => /s3:\/\//.test(i.body || '');
const canMove = () => !!S.me?.mover;
function taskAskToPerson(t) {
  return !!(t?.ask?.body && actorPerson(t.ask.to_actor));
}
function taskWaitLine(t) {
  if (t?.blocker?.title) return `Blocked by: ${t.blocker.title}`;
  const ask = String(t?.ask?.body || '').split('\n').map(s => s.trim()).find(Boolean);
  if (ask) return ask;
  return String(t?.note || '').split('\n').map(s => s.trim()).find(Boolean) || '';
}
function clipLine(s, n) {
  s = String(s || '').replace(/\s+/g, ' ').trim();
  return s.length > n ? s.slice(0, n - 1) + '…' : s;
}
// the column a task sits in
function hubColumn(t) {
  const status = String(t.status || 'open');
  if (status === 'done' || status === 'closed') return 'done';
  if (status === 'declined') return 'needs';
  if (actorPerson(t.owner) || taskAskToPerson(t)) return 'needs';
  if (status === 'waiting' || t.blocked_by) return 'waiting';
  return 'doing';
}
// the small word on a card when the column alone does not say it
const needsWho = t => {
  const pid = actorPerson(t?.ask?.to_actor) || actorPerson(t?.owner);
  return !pid || pid === S.me?.id ? 'Needs you' : `Needs ${firstName(personDisplay(pid))}`;
};
const hubTag = t => (taskAskToPerson(t) || (t.status === 'open' && actorPerson(t.owner))) && !['done', 'closed'].includes(String(t.status)) ? needsWho(t)
  : t.blocked_by && !['done', 'closed'].includes(String(t.status)) ? 'blocked'
  : ['waiting', 'declined'].includes(String(t.status || '')) ? t.status
  : t.status === 'open' && !actorPerson(t.owner) ? 'starting' : '';
// One shape for the list, the sort and the columns.
const issueItem = i => ({kind: 'issue', key: `i${i.number}`, n: i.number, title: i.title || '',
  slug: i.owner, actor: `bot:${i.owner}`, team: teamOf(i.owner), needs: !!i.needs_human,
  rank: null, updated: i.updatedAt, closed: i.state === 'CLOSED' ? i.closedAt : '', lane: 'company',
  issue: i});
const taskItem = t => {
  const slug = actorSlug(t.owner);
  return {kind: 'hub', key: `t${t.id}`, id: t.id, title: t.title || '', slug, actor: t.owner,
          team: slug ? teamOf(slug) : 'people', needs: !!actorPerson(t.owner),
          rank: t.rank == null ? null : Number(t.rank), lane: t.lane || 'company', labels: t.labels || [],
          updated: t.updated || t.created, closed: t.done_at || t.closed_at || '', task: t, col: hubColumn(t), tag: hubTag(t)};
};
// Rank is the order (no priority): ranked first, low to high, then the newest unranked.
const byRank = (a, b) => (a.rank == null ? 1 : 0) - (b.rank == null ? 1 : 0)
  || (a.rank ?? 0) - (b.rank ?? 0)
  || String(b.updated).localeCompare(String(a.updated));
const byNewest = (a, b) => String(b.closed || b.updated).localeCompare(String(a.closed || a.updated));
const searchWords = value => String(value || '').toLocaleLowerCase().replace(/\s+/g, ' ').trim();
const searchIncludes = (fields, query) => {
  const haystack = searchWords(fields.filter(Boolean).join(' '));
  return searchWords(query).split(' ').every(word => haystack.includes(word));
};
function taskMatches(it, query) {
  const person = actorPerson(it.actor);
  return searchIncludes([it.title, ...(it.labels || []), actorLabel(it.actor),
    person && personDisplay(person), it.slug && botDisplayName(it.slug), it.tag, taskWaitLine(it.task)], query);
}
function taskItems(state) {
  const me = myActor();
  return (state.tasks || []).map(taskItem).filter(it => {
    if (it.lane !== 'company') return false;
    if (state.filter === 'mine' && it.actor !== me) return false;
    if (state.filter === 'asked' && taskRequester(it.task) !== me) return false;
    if (state.bot) {
      if (state.bot.startsWith('human:')) { if (it.actor !== state.bot) return false; }
      else if (it.slug !== state.bot) return false;
    }
    if (state.label && !it.labels.includes(state.label)) return false;
    if (state.q && !taskMatches(it, state.q)) return false;
    return state.view === 'done' ? it.col === 'done' : it.col !== 'done';
  });
}
const labelChips = labels => (labels || []).map(l => `<span class="tlabel">${esc(l)}</span>`).join('');
const linkChips = t => (t.links || []).filter(l => l.kind === 'pr').map(l =>
  `<span class="tlink pr ${esc(l.state || '')}" title="${esc(l.url)}">${esc(l.title || 'PR')}${l.state && l.state !== 'open' ? ` · ${esc(l.state)}` : ''}</span>`).join('');
const partsChip = t => t.parts?.total ? `<span class="tparts" title="Parts of this task">${t.parts.done}/${t.parts.total}</span>` : '';
function taskWaitingReason(it) {
  const t = it.task;
  if (!t || (t.status !== 'waiting' && !t.blocked_by && !taskAskToPerson(t))) return '';
  const text = clipLine(plainMd(taskWaitLine(t)), 140) || 'Waiting — the reason was not recorded.';
  return `<span class="wait-why">${esc(text)}</span>`;
}
// the same item as one row of the list; a tap opens the same modal
function taskCard(it) {
  const who = it.slug ? avatar(it.slug, 16, stateOf(it.slug)) : personCircle(actorLabel(it.actor), 16);
  const from = it.task ? taskSourceLine(it.task) : '';
  const extras = it.task ? labelChips(it.labels) + linkChips(it.task) + partsChip(it.task) : '';
  return `<button class="bcard" type="button" data-open-task="${esc(it.key)}">
    <div class="bcard-top">${who}<span class="who">${esc(it.slug ? empName(it.slug) : actorLabel(it.actor))}</span><span class="spacer"></span>${it.tag && it.tag !== 'starting' ? `<span class="tag">${esc(it.tag)}</span>` : ''}</div>
    <div class="bcard-title">${esc(it.title)}${taskWaitingReason(it)}</div>
    ${extras ? `<div class="bcard-extras">${extras}</div>` : ''}
    <div class="bcard-foot">${from ? `<span class="from">${esc(from)}</span><span class="spacer"></span>` : ''}<span class="age tnum">${esc(it.kind === 'schedule' ? fmt(it.updated) : ago(it.updated))}</span></div>
  </button>`;
}
function taskBuckets(items) {
  const out = Object.fromEntries(COMPANY_COLS.map(([k]) => [k, []]));
  for (const it of items) if (out[it.col]) out[it.col].push(it);
  for (const k of Object.keys(out)) out[k].sort(k === 'scheduled' ? (a, b) => String(a.updated).localeCompare(String(b.updated)) : byRank);
  return out;
}
// Board: every open task in its column (the filters and the owner picker above still apply).
function tasksBoardHTML(items) {
  const buckets = taskBuckets(items);
  const anyWork = COMPANY_COLS.some(([k]) => buckets[k].length);   // phones skip empty columns, unless every column is empty
  return `<div class="board work">${COMPANY_COLS.map(([k, label, hint]) => {
    const list = buckets[k];
    return `<section class="bcol${anyWork && !list.length ? ' is-empty' : ''}" data-col="${k}" aria-label="${esc(label)}: ${esc(hint)}">
      <header title="${esc(hint)}"><h2>${esc(label)}</h2><span class="cnt">${list.length}</span></header>
      <div class="bcol-body">${list.map(taskCard).join('') || '<div class="empty">Nothing here</div>'}</div>
    </section>`;
  }).join('')}</div>`;
}
// List: the same tasks as rows, grouped by column.
function tasksListHTML(items) {
  const buckets = taskBuckets(items);
  const groups = COMPANY_COLS.filter(([k]) => buckets[k].length);
  if (!groups.length) return '<section class="card"><div class="empty">Nothing open. Finished work is under Done.</div></section>';
  return '<section class="card">' + groups.map(([k, label]) =>
    `<div class="v2-group" data-col="${k}"><h3>${esc(label)} <span class="muted">${buckets[k].length}</span></h3>
      ${buckets[k].map(taskRow).join('')}</div>`).join('') + '</section>';
}
// When a task was done, in the Done list's quiet right-hand column: "2h ago" today, then "Sep 26".
function doneWhen(when) {
  const t = Date.parse(when || '');
  if (!t) return '';
  return Date.now() - t < 86400000 ? ago(when) : new Date(t).toLocaleDateString(undefined, {month: 'short', day: 'numeric'});
}
function taskRow(it) {
  const when = it.col === 'done' ? (it.closed || it.updated) : it.updated;
  const who = it.kind === 'issue' ? `${avatar(it.slug, 18, stateOf(it.slug))}` : (it.slug ? avatar(it.slug, 18, stateOf(it.slug)) : personCircle(actorLabel(it.actor), 18));
  const from = it.task ? `<span class="from"> · ${esc(taskSourceLine(it.task))}</span>` : '';
  const extras = it.task ? labelChips(it.labels) + linkChips(it.task) + partsChip(it.task) : '';
  return `<button class="trow-btn" type="button" data-open-task="${esc(it.key)}">
      <span class="trow-who">${who}</span>
      <span class="ttl">${esc(it.title)}${from}${it.tag && it.tag !== 'starting' ? ` <span class="tag">${esc(it.tag)}</span>` : ''}${extras ? `<span class="trow-extras">${extras}</span>` : ''}${taskWaitingReason(it)}</span>
      <span class="muted tnum"${it.col === 'done' ? ` title="Done ${esc(fmt(when))}"` : ''}>${esc(it.kind === 'schedule' ? fmt(when) : it.col === 'done' ? doneWhen(when) : ago(when))}</span></button>`;
}
// The goal a task serves is a link with the goal's title; the row only carries the id.
const GOAL_TITLES = {};
async function taskGoalTitle(root) {
  const a = root.querySelector('a.task-goal[data-goal-title]'); if (!a) return;
  const id = a.dataset.goalTitle;
  if (!GOAL_TITLES[id]) { const r = await v2Get('/v2/goals/' + encodeURIComponent(id)); GOAL_TITLES[id] = r?.goal?.title || ''; }
  if (GOAL_TITLES[id] && a.isConnected) a.textContent = 'serves: ' + GOAL_TITLES[id];
}
// Live goals for the "Serves" pick on a new task; fetched once a page, never blocks the form.
let GOAL_OPTIONS = null;
async function goalOptions() {
  if (GOAL_OPTIONS) return GOAL_OPTIONS;
  const r = await v2Get('/v2/goals?all=1');
  GOAL_OPTIONS = (r?.goals || []).map(g => ({id: g.id, title: g.title, owner: g.owner, parent_id: g.parent_id, rank: g.rank, status: g.status}));
  return GOAL_OPTIONS;
}
