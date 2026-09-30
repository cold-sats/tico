/* ui/app/sidebar.js — The org tree, message-bot nav, org history, collapsible sections
   Classic script: its globals are shared with the other files under ui/app/, loaded in the order index.html lists them. */
'use strict';

// ----------------------------------------------------------------- sidebar + heartbeat
const NAV_COLLAPSED_KEY = 'hub.nav.collapsed';
let navCollapsed = new Set(); try { navCollapsed = new Set(JSON.parse(localStorage.getItem(NAV_COLLAPSED_KEY) || '[]')); } catch {}
function renderNavSections() {
  document.querySelectorAll('[data-section-toggle]').forEach(button => {
    const key = button.dataset.sectionToggle, isCollapsed = navCollapsed.has(key);
    button.setAttribute('aria-expanded', String(!isCollapsed));
    const body = document.querySelector(`[data-section-body="${key}"]`);
    if (body) body.hidden = isCollapsed;
  });
}
document.querySelectorAll('[data-section-toggle]').forEach(button => button.onclick = () => {
  const key = button.dataset.sectionToggle;
  navCollapsed.has(key) ? navCollapsed.delete(key) : navCollapsed.add(key);
  try { localStorage.setItem(NAV_COLLAPSED_KEY, JSON.stringify([...navCollapsed])); } catch {}
  renderNavSections();
});
renderNavSections();
// The assistant and the Librarian work in the background and nobody chats with them as a bot
// (each person's private Assistant is a tab on their own page, ui/assistant.js), so search, bot pickers and a
// person's page do not list them. The org panel does, in its Helpers group, and so does Settings → Bots;
// #/bot/<slug> opens, and the Librarian stays one click away from the Docs nav row (renderLibrarians).
const isHiddenBot = slug => slug === assistantBot() || slug === 'librarian';
const shownEmps = () => (S.emps || []).filter(e => !isHiddenBot(e.name));
function orgTreeByParent() {
  const byParent = {};
  const inboxBots = new Set((S.people || []).map(p => p.inbox_bot).filter(Boolean));
  for (const g of (S.orgGroups || [])) {
    (byParent[g.org_parent || ''] ||= []).push({kind: 'group', id: g.id, name: g.name, order: g.order || 0});
  }
  for (const p of (S.people || []).filter(p => !p.hidden)) {
    (byParent[p.org_parent || ''] ||= []).push({kind: 'person', id: p.id, person: p});
  }
  // "Only bots I can read or write": a bot the caller may merely see leaves the chart, and the
  // bots under it hang from the next thing that is left.
  // The built-in helpers are listed here too (the Helpers group), the same bots the Goals page lists as helpers; a
  // bot that reports to one hangs where the helper would have (orgTreeWithHelpers).
  const kept = (S.emps || []).filter(orgMineKeep);
  const empIds = new Set(kept.filter(e => !inboxBots.has(e.name)).map(e => e.name));
  for (const e of kept) {
    if (inboxBots.has(e.name)) continue;
    let parent = e.org_parent || '';
    if (parent.startsWith('b:') && !empIds.has(parent.slice(2))) {
      const owner = e.operator || e.users?.[0]?.id;
      parent = owner ? 'p:' + owner : '';
    }
    (byParent[parent] ||= []).push({kind: 'bot', ...e});
  }
  return byParent;
}
function mePerson() {
  const id = S.me?.id, email = (S.me?.email || '').toLowerCase();
  return (S.people || []).find(p => p.id === id) ||
         (S.people || []).find(p => (p.email || '').toLowerCase() === email) || null;
}
function inboxNavPeople() {
  const bots = new Set((S.emps || []).map(e => e.name));
  return (S.people || []).filter(p => p.email && p.inbox_bot && !p.hidden && bots.has(p.inbox_bot))
    .filter(p => S.me?.role === 'owner' || mailPersonVisible(p))
    .sort((a, b) => String(a.email).localeCompare(String(b.email)));
}
let INBOX_NAV = null;
const SLACK_ICON = `<svg class="inbox-slack" viewBox="0 0 24 24" aria-hidden="true"><path fill="currentColor" d="M5.042 15.165a2.528 2.528 0 0 1-2.52 2.523A2.528 2.528 0 0 1 0 15.165a2.527 2.527 0 0 1 2.522-2.52h2.52v2.52zm1.271 0a2.527 2.527 0 0 1 2.521-2.52 2.527 2.527 0 0 1 2.521 2.52v6.313A2.528 2.528 0 0 1 8.834 24a2.528 2.528 0 0 1-2.521-2.522v-6.313zM8.834 5.042a2.528 2.528 0 0 1-2.521-2.52A2.528 2.528 0 0 1 8.834 0a2.528 2.528 0 0 1 2.521 2.522v2.52H8.834zm0 1.271a2.528 2.528 0 0 1 2.521 2.521 2.528 2.528 0 0 1-2.521 2.521H2.522A2.528 2.528 0 0 1 0 8.834a2.528 2.528 0 0 1 2.522-2.521h6.312zM18.956 8.834a2.528 2.528 0 0 1 2.522-2.521A2.528 2.528 0 0 1 24 8.834a2.528 2.528 0 0 1-2.522 2.521h-2.522V8.834zm-1.268 0a2.528 2.528 0 0 1-2.523 2.521 2.527 2.527 0 0 1-2.52-2.521V2.522A2.527 2.527 0 0 1 15.165 0a2.528 2.528 0 0 1 2.523 2.522v6.312zM15.165 18.956a2.528 2.528 0 0 1 2.523 2.522A2.528 2.528 0 0 1 15.165 24a2.527 2.527 0 0 1-2.52-2.522v-2.522h2.52zm0-1.268a2.527 2.527 0 0 1-2.52-2.523 2.526 2.526 0 0 1 2.52-2.52h6.313A2.527 2.527 0 0 1 24 15.165a2.528 2.528 0 0 1-2.522 2.523h-6.313z"/></svg>`;
function inboxNavRows() {
  const mail = inboxNavPeople().map(p => ({
    kind: 'email', label: p.email, title: p.name ? `${p.name} · ${p.email}` : p.email,
    bot: p.inbox_bot, source: 'email:' + p.email,
  }));
  const slack = [];
  for (const bot of INBOX_NAV?.bots || []) {
    for (const source of bot.sources || []) {
      if (source.kind !== 'slack') continue;
      slack.push({kind: 'slack', label: source.name, title: `${bot.name} · ${source.name}`,
                  bot: bot.bot, source: source.id});
    }
  }
  slack.sort((a, b) => a.label.localeCompare(b.label));
  return [...mail, ...slack];
}
function renderInboxNav() {
  const section = $('#nav-inboxes-section'), list = $('#inbox-list');
  if (!section || !list) return;
  if (INBOX_NAV === null) {
    INBOX_NAV = false;
    get('/v2/messaging/bots').then(data => { INBOX_NAV = data; renderInboxNav(); })
      .catch(() => { INBOX_NAV = {bots: []}; renderInboxNav(); });
  }
  const rows = inboxNavRows();
  section.hidden = !rows.length;
  const here = messagingParams();
  list.innerHTML = rows.map(row => {
    const href = `${MESSAGING}?bot=${encodeURIComponent(row.bot)}&source=${encodeURIComponent(row.source)}`;
    const on = S.route.startsWith(MESSAGING) && here.bot === row.bot && here.source === row.source;
    const icon = row.kind === 'slack' ? SLACK_ICON : `<span class="nav-icon inbox-kind" aria-hidden="true">mail</span>`;
    return `<li><a href="${href}" title="${esc(row.title)}"${on ? ' class="cur" aria-current="page"' : ''}>${icon}<span>${esc(row.label)}</span></a></li>`;
  }).join('');
}
function renderLibrarians() {
  for (const [id, slug] of [['nav-docs-librarian', 'librarian'], ['nav-market-librarian', 'market-analyst']]) {
    const el = document.getElementById(id);
    if (!el) continue;
    const bot = (S.emps || []).find(e => e.name === slug && e.status !== 'archived' && e.status !== 'retired');
    el.hidden = !bot;
    if (!bot) continue;
    const name = bot.display_name || slug;
    el.href = `#/bot/${encodeURIComponent(slug)}/more`;
    el.title = `${name} settings`;
    el.setAttribute('aria-label', `${name} settings`);
    const on = S.route.startsWith('#/bot/' + slug);
    el.classList.toggle('cur', on);
    if (on) el.setAttribute('aria-current', 'page'); else el.removeAttribute('aria-current');
  }
}
function mailPersonVisible(person) {
  if (!S.me?.mail_access || !person?.email || !person.inbox_bot ||
      !(S.emps || []).some(e => e.name === person.inbox_bot)) return false;
  if (S.me.role === 'owner') return true;
  const me = mePerson();
  if (!me) return (person.email || '').toLowerCase() === (S.me.email || '').toLowerCase();
  let current = person;
  const seen = new Set();
  while (current && !seen.has(current.id)) {
    if (current.id === me.id) return true;
    seen.add(current.id);
    current = (S.people || []).find(p => p.id === current.reports_to);
  }
  return false;
}
function defaultCollapsed() {
  const by = orgTreeByParent(), keys = new Set();
  const founder = (by[''] || []).find(n => n.kind === 'person' && !n.person?.reports_to);
  for (const k of Object.keys(by)) {
    if (!k || !by[k].length) continue;
    if (k.startsWith('g:')) continue;
    if (founder && k === 'p:' + founder.id) continue;
    keys.add(k);
  }
  return keys;
}
let collapsed = new Set(), collapsedFor = null, collapsedSaved = false;
function collapsedStorageKey() {
  return 'hub.collapsed.v3.' + (mePerson()?.id || S.me?.id || '');
}
function ensureCollapsed() {
  const id = mePerson()?.id || S.me?.id || '';
  if (id !== collapsedFor) {
    collapsedFor = id;
    collapsedSaved = false;
    try {
      const saved = id && localStorage.getItem(collapsedStorageKey());
      if (saved) { collapsed = new Set(JSON.parse(saved)); collapsedSaved = true; return; }
    } catch {}
    collapsed = defaultCollapsed();
    return;
  }
  if (!collapsedSaved) collapsed = defaultCollapsed();
}
function saveCollapsed() {
  collapsedSaved = true;
  const id = mePerson()?.id || S.me?.id || '';
  if (!id) return;
  try { localStorage.setItem(collapsedStorageKey(), JSON.stringify([...collapsed])); } catch {}
}
function setPeople(data) {
  if (!data) return;
  if (Array.isArray(data.people)) S.people = data.people;
  if (data.org_groups) S.orgGroups = data.org_groups;
}
// Rearranging the org chart: drag a person or a bot onto another person or bot. The owner may
// move anyone; anyone else may move what reports up to them, and only under themselves or their
// own reports — the server holds that rule (backend/people.py `manages`), the client just offers
// the handles for what it knows is yours.
function orgMine() {
  const mine = new Set();
  if (S.me?.role === 'owner') return null;                       // everything
  const me = mePerson()?.id || S.me?.id; if (!me) return mine;
  const byParent = orgTreeByParent();
  const walk = key => { for (const c of byParent[key] || []) { const k = c.kind === 'person' ? 'p:' + c.id : c.kind === 'bot' ? 'b:' + c.name : 'g:' + c.id; mine.add(k); walk(k); } };
  mine.add('p:' + me); walk('p:' + me);
  return mine;
}
function orgMayMove(key) { const mine = orgMine(); return mine === null || mine.has(key); }
function orgDragWire(tree, byParent) {
  if (!tree) return;
  let dragging = null;
  tree.addEventListener('dragstart', ev => {
    const node = ev.target.closest('[data-org][draggable="true"]'); if (!node) return;
    dragging = node.dataset.org; ev.dataTransfer.effectAllowed = 'move'; ev.dataTransfer.setData('text/plain', dragging);
    node.classList.add('dragging');
  });
  tree.addEventListener('dragend', ev => { ev.target.closest?.('[data-org]')?.classList.remove('dragging'); tree.querySelectorAll('.drop-target').forEach(n => n.classList.remove('drop-target')); dragging = null; });
  tree.addEventListener('dragover', ev => {
    const target = ev.target.closest('[data-org]'); if (!target || !dragging || target.dataset.org === dragging) return;
    if (dragging.startsWith('p:') && !target.dataset.org.startsWith('p:')) return;   // a person reports to a person
    if (target.hasAttribute('data-helper')) return;                                     // helpers are not on the chart
    ev.preventDefault(); ev.dataTransfer.dropEffect = 'move';
    tree.querySelectorAll('.drop-target').forEach(n => n.classList.remove('drop-target')); target.classList.add('drop-target');
  });
  tree.addEventListener('dragleave', ev => { ev.target.closest?.('[data-org]')?.classList.remove('drop-target'); });
  tree.addEventListener('drop', async ev => {
    const target = ev.target.closest('[data-org]'); if (!target || !dragging || target.hasAttribute('data-helper')) return;
    ev.preventDefault();
    const from = dragging, to = target.dataset.org; dragging = null;
    target.classList.remove('drop-target');
    if (from === to) return;
    try {
      if (from.startsWith('p:')) {
        if (!to.startsWith('p:')) return;
        await post(`/v2/humans/${encodeURIComponent(from.slice(2))}`, {reports_to: to.slice(2)});
      } else {
        const slug = from.slice(2), e = S.emps.find(x => x.name === slug);
        if (!e) return;
        const reports_to = to.startsWith('p:') ? 'human:' + to.slice(2) : to.slice(2);
        await post(`/v2/bots/${encodeURIComponent(slug)}/definition`, {reports_to, expected_revision: e.revision});
      }
      await refresh(true);
      renderTree();
    } catch (e) { toast(e.message, true); }
  });
}
// The org list has no hover card on bots. What a bot's row says is its badge:
// a subtle ring spins around it while the bot works, and it looks like a quiet alert when the bot
// needs you — the count of tasks waiting on you, or a small ! when the need is not a task.
function treeBadge(n, st) {
  const working = st === 'running';
  if (n) return `<span class="cnt needs${working ? ' working' : ''}" role="img" aria-label="${n} need${n === 1 ? 's' : ''} you${working ? ', working' : ''}">${n}</span>`;
  if (st === 'needs') return `<span class="tree-alert${working ? ' working' : ''}" role="img" aria-label="Needs you">!</span>`;
  return working ? '<span class="tree-spin" role="img" aria-label="Working"></span>' : '';
}
// "next to org see a history icon that when pressed, sorts my bots and people by
// most recently viewed. With most recent on top" (he works with a couple of bots at a time). Every
// bot and person page opened is remembered on this device; the toggle stays as he left it.
// The list follows him between desktop and phone. It is saved with his account
// (preference org.history, stamped with when it last changed) and cached on each device; the newer
// copy wins when a page loads or a tab comes back to the front.
const ORG_HISTORY_KEY = 'tico.org.history', ORG_HISTORY_ON_KEY = 'tico.org.history.on';
const ORG_HISTORY_AT_KEY = 'tico.org.history.at', ORG_HISTORY_PREF = 'org.history';
function orgHistory() {
  try { return JSON.parse(localStorage.getItem(ORG_HISTORY_KEY) || '[]').filter(x => typeof x === 'string'); } catch { return []; }
}
function orgHistoryAt() { try { return Number(localStorage.getItem(ORG_HISTORY_AT_KEY)) || 0; } catch { return 0; } }
function orgHistoryStore(items, at) {
  try { localStorage.setItem(ORG_HISTORY_KEY, JSON.stringify(items.slice(0, 100))); localStorage.setItem(ORG_HISTORY_AT_KEY, String(at)); } catch {}
}
let orgHistoryTimer = null;
function orgHistorySave() {
  if (!S.me?.cloud) return;
  clearTimeout(orgHistoryTimer);
  orgHistoryTimer = setTimeout(() => { void post('/v2/preferences/' + ORG_HISTORY_PREF,
    {value: {items: orgHistory(), at: orgHistoryAt()}}).catch(() => {}); }, 800);
}
// "Only bots I can read or write" (the person icon beside the clock): hides the bots the caller may only
// see. Kept like the history: on this device at once, and with the account as preference org.mine,
// stamped with when it last changed, the newer copy winning.
const ORG_MINE_KEY = 'tico.org.mine', ORG_MINE_AT_KEY = 'tico.org.mine.at', ORG_MINE_PREF = 'org.mine';
function orgMineOn() { try { return localStorage.getItem(ORG_MINE_KEY) === '1'; } catch { return false; } }
function orgMineAt() { try { return Number(localStorage.getItem(ORG_MINE_AT_KEY)) || 0; } catch { return 0; } }
function orgMineStore(on, at) { try { localStorage.setItem(ORG_MINE_KEY, on ? '1' : '0'); localStorage.setItem(ORG_MINE_AT_KEY, String(at)); } catch {} }
const orgMineKeep = e => !orgMineOn() || !e.my_access || e.my_access.read || e.my_access.write;
let orgMineTimer = null;
function orgMineSave() {
  if (!S.me?.cloud) return;
  clearTimeout(orgMineTimer);
  orgMineTimer = setTimeout(() => { void post('/v2/preferences/' + ORG_MINE_PREF,
    {value: {on: orgMineOn(), at: orgMineAt()}}).catch(() => {}); }, 800);
}
async function orgMineSync() {
  if (!S.me?.cloud) return;
  const v = (await v2Get('/v2/preferences/' + ORG_MINE_PREF))?.value;
  const at = Number(v?.at) || 0;
  if (v && typeof v.on === 'boolean' && at > orgMineAt()) { orgMineStore(v.on, at); renderTree(); }
  else if (at < orgMineAt()) orgMineSave();
}
async function orgHistorySync() {
  void orgMineSync();
  if (!S.me?.cloud) return;
  const v = (await v2Get('/v2/preferences/' + ORG_HISTORY_PREF))?.value;
  const items = Array.isArray(v?.items) ? v.items.filter(x => typeof x === 'string') : null;
  if (items && (Number(v.at) || 0) > orgHistoryAt()) {
    const local = orgHistory();
    orgHistoryStore([...items, ...local.filter(k => !items.includes(k))], Number(v.at));
    renderTree();
  } else if (orgHistory().length && (Number(v?.at) || 0) < orgHistoryAt()) orgHistorySave();
}
document.addEventListener('visibilitychange', () => { if (!document.hidden) void orgHistorySync(); });
function orgHistoryVisit(key) {
  const seen = orgHistory(); if (seen[0] === key) return;
  orgHistoryStore([key, ...seen.filter(x => x !== key)], Date.now());
  orgHistorySave();
  if (orgHistoryOn()) renderTree();                      // the one just opened moves to the top
}
function orgHistoryOn() { try { return localStorage.getItem(ORG_HISTORY_ON_KEY) === '1'; } catch { return false; } }
$('#org-mine').onclick = () => {
  orgMineStore(!orgMineOn(), Date.now());
  orgMineSave();
  renderTree();
};
$('#org-history').onclick = () => {
  try { localStorage.setItem(ORG_HISTORY_ON_KEY, orgHistoryOn() ? '0' : '1'); } catch {}
  if (orgHistoryOn() && navCollapsed.delete('organisation')) {
    try { localStorage.setItem(NAV_COLLAPSED_KEY, JSON.stringify([...navCollapsed])); } catch {}
    renderNavSections();
  }
  renderTree();
};
// Helpers (the built-ins, and bots made from a `kind: helper` card such as the Inbox Manager) serve people rather than
// hold a place on the org chart, so the sidebar lists them in a Helpers group of their own after it. Only the grouping
// changes: `reports_to` is untouched, and a bot that reports to a helper hangs where the helper would have.
const HELPERS_GROUP = '__helpers';
const isHelperBot = e => isBuiltInBot(e.name) || !!e.helper;
// The order helpers are listed in, here and on the Goals page: the Assistant, then the other built-ins, then the rest.
const HELPER_ORDER = ['botops', 'librarian', 'goal-manager', 'inbox'];
const helperRank = e => e.name === assistantBot() ? -1 : HELPER_ORDER.includes(e.name) ? HELPER_ORDER.indexOf(e.name) : 99;
function orgTreeWithHelpers(byParent) {
  const out = {}, helpers = [], bot = {}, parentOf = {};
  for (const [parent, kids] of Object.entries(byParent)) for (const n of kids) if (n.kind === 'bot') { bot['b:' + n.name] = n; parentOf['b:' + n.name] = parent; }
  const lift = parent => {
    for (let hops = 0; bot[parent] && isHelperBot(bot[parent]) && hops < 5; hops++) parent = parentOf[parent] || '';
    return parent;
  };
  for (const [parent, kids] of Object.entries(byParent)) for (const n of kids) {
    if (n.kind === 'bot' && isHelperBot(n)) helpers.push(n);
    else (out[lift(parent)] ||= []).push(n);
  }
  if (helpers.length) {
    (out[''] ||= []).push({kind: 'group', id: HELPERS_GROUP, name: 'Built-in', helpers: true});
    out['g:' + HELPERS_GROUP] = helpers;
  }
  return out;
}
function renderTree() {
  ensureCollapsed();
  const byParent = orgTreeWithHelpers(orgTreeByParent());
  const curBot = S.route.startsWith('#/bot/') ? S.route.slice(6).split('/')[0] : null;
  const curPerson = S.route.startsWith('#/person/') ? decodeURIComponent(S.route.slice(9).split('/')[0]) : null;
  // only "needs you" surfaces through a collapsed parent; running is not something to chase
  const subtreeNeeds = key => (byParent[key] || []).some(c =>
    (c.kind === 'bot' && (stateOf(c.name) === 'needs' || needsMeCount(c.name) || subtreeNeeds('b:' + c.name))) ||
    (c.kind === 'person' && subtreeNeeds('p:' + c.id)) ||
    (c.kind === 'group' && subtreeNeeds('g:' + c.id)));
  const isTemp = e => e.kind === 'bot' && isTempBot(e);
  const nameOf = n => n.kind === 'person' ? (n.person.name || n.id) : (n.display_name || '').replace(TEMP_RE, '');
  const rec = (parent, depth) => (byParent[parent] || []).slice()
    .sort((a, b) => {
      if (!!a.helpers !== !!b.helpers) return a.helpers ? 1 : -1;        // the Helpers group comes last
      if ((a.kind === 'group') !== (b.kind === 'group')) {
        // At the team root, department labels lead. Under a person, their bots and
        // people come first and the next department (Engineering under Product) follows.
        return a.kind === 'group' ? (parent ? 1 : -1) : (parent ? -1 : 1);
      }
      if (a.kind === 'group' && b.kind === 'group') return (a.order || 0) - (b.order || 0);
      if ((a.kind === 'person') !== (b.kind === 'person')) return a.kind === 'person' ? -1 : 1;
      if (isTemp(a) !== isTemp(b)) return isTemp(a) - isTemp(b);
      if (a.kind === 'bot' && b.kind === 'bot' && isHelperBot(a) && isHelperBot(b) && helperRank(a) !== helperRank(b)) return helperRank(a) - helperRank(b);
      if (a.kind === 'bot' && b.kind === 'bot' && byBotOrder(a, b)) return byBotOrder(a, b);
      return nameOf(a).localeCompare(nameOf(b));
    })
    .map(node => row(node, depth)).join('');
  // flat: the history list, one row per bot and person, no children and nothing to drag
  const row = (node, depth, flat = false) => {
    if (node.kind === 'group') {
      const key = 'g:' + node.id, kids = byParent[key], isCol = kids && collapsed.has(key);
      if (!kids) return '';
      return `<li class="dept org-group"><div class="noderow">
        <button class="chev ${isCol ? 'col' : ''}" data-toggle="${esc(key)}" aria-label="${isCol ? 'Expand' : 'Collapse'} ${esc(node.name)}">›</button>
        <span class="dept-label" data-toggle="${esc(key)}" role="button" tabindex="0">${esc(node.name)}</span>
        ${isCol && subtreeNeeds(key) ? '<span class="dot needs" title="something inside needs attention"></span>' : ''}</div>
        <ul ${isCol ? 'hidden' : ''}>${rec(key, depth + 1)}</ul></li>`;
    }
    if (node.kind === 'person') {
      const p = node.person, key = 'p:' + p.id, kids = !flat && byParent[key], isCol = kids && collapsed.has(key);
      return `<li class="${kids ? 'dept' : ''}"><div class="noderow">
        ${kids ? `<button class="chev ${isCol ? 'col' : ''}" data-toggle="${esc(key)}" aria-label="${isCol ? 'Expand' : 'Collapse'} ${esc(p.name || p.id)}">›</button>` : ''}
        <a class="node person ${curPerson === p.id ? 'cur' : ''}" href="#/person/${encodeURIComponent(p.id)}" title="${esc(personTitle(p))}"${curPerson === p.id ? ' aria-current="page"' : ''} data-org="p:${esc(p.id)}"${!flat && orgMayMove(key) ? ' draggable="true"' : ''}>
          ${personAvatar(p, depth ? 16 : 20)}<span class="nm">${esc(firstName(p.name) || p.id)}</span>
          ${isCol && subtreeNeeds(key) ? '<span class="dot needs" title="something inside needs attention"></span>' : ''}</a>
        ${mailPersonVisible(p) ? `<a class="person-mail-link${S.route.startsWith(MESSAGING) && messagingParams().bot === p.inbox_bot ? ' cur' : ''}" href="${MESSAGING}?bot=${encodeURIComponent(p.inbox_bot)}&source=${encodeURIComponent('email:' + p.email)}" title="${esc(p.name || p.id)} has a message bot" aria-label="Open ${esc(p.name || p.id)}'s message bot">forum</a>` : ''}</div>
        ${kids ? `<ul ${isCol ? 'hidden' : ''}>${rec(key, depth + 1)}</ul>` : ''}</li>`;
    }
    const e = node, key = 'b:' + e.name, st = stateOf(e.name), n = needsMeCount(e.name), kids = !flat && byParent[key], isCol = kids && collapsed.has(key);
    const helper = isHelperBot(e);                 // not on the chart: nothing is dragged onto or out of it
    return `<li class="${kids ? 'dept' : ''}"><div class="noderow">
      ${kids ? `<button class="chev ${isCol ? 'col' : ''}" data-toggle="${esc(key)}" aria-label="${isCol ? 'Expand' : 'Collapse'} ${esc(e.display_name)}">›</button>` : ''}
      <a class="node ${e.status} ${curBot === e.name ? 'cur' : ''} ${st}" href="#/bot/${e.name}"${curBot === e.name ? ' aria-current="page"' : ''} data-org="b:${esc(e.name)}"${helper ? ' data-helper' : ''}${!flat && !helper && orgMayMove(key) ? ' draggable="true"' : ''}>
        ${avatar(e.name, depth ? 16 : 20, st)}<span class="nm">${shownName(e)}</span>${runtimeTag(e)}${frTreeMark(e)}
        ${isCol && subtreeNeeds(key) ? '<span class="dot needs" title="something inside needs attention"></span>' : ''}
        ${treeBadge(n, st)}</a></div>
      ${kids ? `<ul ${isCol ? 'hidden' : ''}>${rec(key, depth + 1)}</ul>` : ''}</li>`;
  };
  // Every bot and person, the one you opened last on top; ones you never opened follow by name.
  const history = () => {
    const seen = orgHistory(), at = n => { const i = seen.indexOf(n.kind === 'person' ? 'p:' + n.id : 'b:' + n.name); return i < 0 ? Infinity : i; };
    return Object.values(byParent).flat().filter(n => n.kind !== 'group')
      .sort((a, b) => (at(a) - at(b)) || nameOf(a).localeCompare(nameOf(b)))
      .map(node => row(node, 0, true)).join('');
  };
  renderOnboardingNav();
  renderInboxNav();
  renderLibrarians();
  const historyOn = orgHistoryOn();
  $('#org-history').setAttribute('aria-pressed', String(historyOn));
  $('#org-mine').setAttribute('aria-pressed', String(orgMineOn()));
  $('#tree').classList.toggle('history', historyOn);
  $('#tree').innerHTML = historyOn ? history() : rec('', 0);
  orgDragWire($('#tree'), byParent);
  $('#tree').onclick = ev => {
    const b = ev.target.closest('[data-toggle]'); if (!b) return;
    ev.preventDefault(); const k = b.dataset.toggle; collapsed.has(k) ? collapsed.delete(k) : collapsed.add(k);
    saveCollapsed();
    renderTree();
  };
  document.querySelectorAll('[data-nav]').forEach(a => {
    const mobilePrimary = S.route === UPDATES || S.route.startsWith(UPDATES + '?');   // Tasks lives in More on a phone now
    const isCurrent = (a.dataset.nav === 'welcome' && S.route === WELCOME) ||
      (a.dataset.nav === 'meetings' && (S.route === MEETINGS || S.route.startsWith(MEETINGS + '?'))) ||
      (a.dataset.nav === 'mail' && (S.route === MAIL || S.route.startsWith(MAIL + '?') || S.route.startsWith(MESSAGING))) ||
      (a.dataset.nav === 'tasks' && ([TASKS, BOARD, ISSUES, RECURRING].includes(S.route) || S.route.startsWith('#/task/'))) ||
      (a.dataset.nav === 'settings' && S.route === SETTINGS) ||
      (a.dataset.nav === 'help' && S.route === HELP) ||
      (a.dataset.nav === 'credentials' && S.route === CREDENTIALS) ||
      (a.dataset.nav === 'docs' && (S.route === DOCS || S.route.startsWith(DOCS + '/') || S.route.startsWith(DOCS + '?'))) ||
      (a.dataset.nav === 'market' && (S.route === '#/market' || S.route.startsWith('#/market?') || S.route.startsWith('#/market/'))) ||
      (a.dataset.nav === 'integrations' && (S.route === INTEGRATIONS || S.route.startsWith(INTEGRATIONS + '/'))) ||
      (a.dataset.nav === 'changelog' && S.route === '#/changelog') ||
      (a.dataset.nav === 'runs' && S.route === '#/runs') ||
      (a.dataset.nav === 'usage' && S.route === '#/usage') ||
      (a.dataset.nav === 'updates' && (S.route === UPDATES || S.route.startsWith(UPDATES + '?'))) ||
      (a.dataset.nav === 'goals' && (S.route === GOALS || S.route.startsWith(GOALS + '/') || S.route.startsWith(GOALS + '?'))) ||
      (a.dataset.nav === 'more' && !mobilePrimary);
    a.classList.toggle('cur', isCurrent);
    if (isCurrent) a.setAttribute('aria-current', 'page'); else a.removeAttribute('aria-current');
  });
  $('#account')?.classList.toggle('cur', !!document.querySelector('#account-menu .cur'));   // the page you are on is behind it
}
