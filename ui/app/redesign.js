/* ui/app/redesign.js — The redesign's shell (redesign PLAN §1, wave 1): the new sidebar order, the Strategy tabs
   (Market / Strategy / Org / Goals / Budget), the Strategy Bot's panel beside them, the moved pages and the old
   addresses that lead to them. All of it waits behind the team's `redesign` setting (GET /api/v2/config, owner's
   switch in Settings > General); off, nothing here draws, moves or redirects anything.
   Classic script: its globals are shared with the other files under ui/app/, loaded in the order index.html lists them. */
'use strict';

const RD_GOALS = '#/strategy/goals', RD_ORG = '#/strategy/org', RD_BUDGET = '#/strategy/budget';
const RD_LISTENING = '#/strategy/market/listening', RD_AUTOMATIONS = '#/automations';
const rdUnder = (r, base) => r === base || r.startsWith(base + '/') || r.startsWith(base + '?');
// Where Goals lives: a Strategy tab with the redesign on, its own page otherwise.
const goalsBase = () => redesignOn() ? RD_GOALS : GOALS;

// One "?" per panel: the explanation a row would otherwise carry, on hover, focus or tap.
const helpBubble = text => `<span class="rd-help" tabindex="0" role="button" aria-label="${esc(text)}">?<span class="rd-help-pop" role="tooltip">${esc(text)}</span></span>`;

// ----------------------------------------------------------------- the sidebar
// The rail is rearranged in place, not drawn again: the links keep their own badges and handlers (sidebar.js,
// notices.js). The first arrangement is remembered so turning the setting off puts every node back.
let RD_NAV = null;          // {on, order, strategy: {href, icon}, made: [nodes]}
const RD_NAV_ICONS = {automations: 'bolt', library: 'local_library', strategy: 'flag'};
function redesignNav(on) {
  const nav = $('#side .side-scroll');
  if (!nav) return;
  const strategyLink = nav.querySelector('a[data-nav="strategy"]');
  RD_NAV ||= {on: false, order: [...nav.children], strategy: {href: strategyLink?.getAttribute('href'), icon: strategyLink?.querySelector('.nav-icon')?.textContent}, made: []};
  if (RD_NAV.on === on) return;
  RD_NAV.on = on;
  if (!on) {
    nav.append(...RD_NAV.order);
    RD_NAV.made.forEach(el => el.remove()); RD_NAV.made = [];
    if (strategyLink) { strategyLink.setAttribute('href', RD_NAV.strategy.href); strategyLink.querySelector('.nav-icon').textContent = RD_NAV.strategy.icon; }
    return;
  }
  const pick = sel => nav.querySelector(sel);
  const row = sel => pick(sel)?.closest('.nav-row') || pick(sel);
  const link = (key, href, icon, label) => {
    const a = Object.assign(document.createElement('a'), {className: 'nav-link', href, innerHTML: `<span class="nav-icon" aria-hidden="true">${icon}</span>${label}`});
    a.dataset.nav = key;
    return a;
  };
  const automations = link('automations', RD_AUTOMATIONS, RD_NAV_ICONS.automations, 'Automations');
  const library = link('library', DOCS, RD_NAV_ICONS.library, 'Library'); library.classList.add('rd-lib-head');
  const subs = document.createElement('div'); subs.className = 'rd-lib';
  subs.append(...[row('a[data-nav="docs"]'), pick('a[data-nav="meetings"]')].filter(Boolean));
  RD_NAV.made = [automations, library, subs];
  if (strategyLink) { strategyLink.setAttribute('href', MARKET_ROUTE); strategyLink.querySelector('.nav-icon').textContent = RD_NAV_ICONS.strategy; }
  const order = [pick('#side-update'), pick('a[data-nav="overview"]'), pick('#nav-welcome'), row('a[data-nav="strategy"]'),
    pick('a[data-nav="updates"]'), pick('a[data-nav="tasks"]'), pick('#nav-assistant'), automations, library, subs,
    pick('#nav-botops'), pick('a[data-nav="goals"]'), pick('#nav-pins')].filter(Boolean);
  const rest = RD_NAV.order.filter(el => !order.includes(el) && !subs.contains(el));
  nav.append(...order, ...rest);
}
// The current page's highlight for what the redesign adds or moves (sidebar.js asks, after its own checks).
function redesignNavCurrent(nav) {
  const r = S.route || '';
  if (nav === 'automations') return rdUnder(r, RD_AUTOMATIONS);
  if (nav === 'strategy') return rdUnder(r, '#/strategy');
  return false;
}

// Called by applyConfig (state.js) whenever config is read: boot, and the poll every two minutes.
let RD_SEEN = null;
window.redesignApply = function redesignApply() {
  const on = redesignOn();
  document.documentElement.classList.toggle('redesign', on);
  redesignNav(on);
  if (RD_SEEN === null || RD_SEEN === on) { RD_SEEN = on; return; }
  RD_SEEN = on;
  // Turned on or off from another tab or by the owner: names and the page follow without a reload.
  if (S.me) { void refresh(true); route(); }
};

// ----------------------------------------------------------------- routes
// Runs before the router's own list (router.js); true when it handled the address.
function redesignRoute(r) {
  // Old addresses of what moved.
  if (rdUnder(r, GOALS)) { location.replace(RD_GOALS + r.slice(GOALS.length)); return true; }
  if (r === '#/settings/listening') { location.replace(RD_LISTENING); return true; }
  if (r === '#/library') { location.replace(DOCS); return true; }
  if (rdUnder(r, RD_AUTOMATIONS)) {
    // The Automations page is its own files (ui/app/automations*.js); until they load, an empty mount point.
    if (typeof window.pageAutomations === 'function') window.pageAutomations();
    else $('#main').innerHTML = '<div id="automations-root" class="rd-automations"></div>';
    return true;
  }
  if (rdUnder(r, RD_GOALS)) { pageGoals(); return true; }
  if (rdUnder(r, RD_ORG)) { pageRdOrg(); return true; }
  if (rdUnder(r, RD_BUDGET)) { pageBudget(); return true; }
  if (rdUnder(r, RD_LISTENING)) { pageRdListening(); return true; }
  return false;
}
// After every route: leave Automations' state when off its page, and put the Strategy Bot beside the Strategy tabs.
function redesignAfterRoute() {
  if (!rdUnder(S.route || '', RD_AUTOMATIONS)) window.automationsStop?.();
  syncStrategyBot();
}

// The Strategy section's heading with the redesign's tabs. Lenses are the Strategy tab's second view.
function redesignStrategyHead(tab) {
  const on = tab === 'lenses' ? 'strategy' : tab;
  const tabs = [['market', MARKET_ROUTE, 'Market'], ['strategy', '#/strategy', 'Strategy'], ['org', RD_ORG, 'Org'],
    ['goals', RD_GOALS, 'Goals'], ['budget', RD_BUDGET, 'Budget']];
  const sub = on === 'strategy'
    ? `<a class="strat-sub" href="${tab === 'lenses' ? '#/strategy' : LENSES_ROUTE}">${tab === 'lenses' ? 'Strategy' : 'Lenses'}</a>` : '';
  return `<div class="strat-head rd-strat-head"><h1>Strategy</h1>
      <nav class="tabs slim strat-tabs" aria-label="Strategy">${tabs.map(([id, href, label]) =>
        `<a href="${href}" data-strat-tab="${id}"${on === id ? ' class="cur" aria-current="page"' : ''}>${label}</a>`).join('')}</nav>
      <span class="spacer"></span>${sub}<div class="strat-actions" id="strat-actions"></div></div>`;
}

// Org: who reports to whom, as the sidebar's tree has it, until the org chart (wave 6) replaces it.
function pageRdOrg() {
  const main = $('#main');
  main.classList.add('strategy-layout', 'rd-org-layout');
  const by = orgTreeWithHelpers(orgTreeByParent()), seen = new Set();   // helpers are off the chart (sidebar.js)
  const name = n => n.kind === 'group' ? n.name : n.kind === 'person' ? (n.person?.name || n.id) : (n.display_name || n.name);
  const key = n => n.kind === 'group' ? 'g:' + n.id : n.kind === 'person' ? 'p:' + n.id : n.kind === 'bot' ? 'b:' + n.name : 's:' + n.id;
  const href = n => n.kind === 'person' ? `#/person/${encodeURIComponent(n.id)}` : n.kind === 'bot' ? `#/bot/${encodeURIComponent(n.name)}` : '';
  const rows = (parent, depth) => (by[parent] || []).filter(n => n.kind !== 'seat').map(n => {
    const k = key(n);
    if (seen.has(k) || depth > 12) return '';
    seen.add(k);
    const label = href(n) ? `<a href="${href(n)}">${esc(name(n))}</a>` : `<span>${esc(name(n))}</span>`;
    return `<li class="rd-org-row rd-org-${n.kind}" style="--depth:${depth}">${label}</li>` + rows(k, depth + 1);
  }).join('');
  const list = rows('', 0);
  main.innerHTML = strategyHeadHtml('org') + (list ? `<ul class="rd-org">${list}</ul>` : '<p class="muted rd-empty">No one on the chart yet.</p>');
}

// Market > Listening: Settings > Listening's destinations, moved here.
function pageRdListening() {
  window.marketStop?.();
  const main = $('#main');
  main.classList.add('strategy-layout', 'rd-listen-layout');
  main.innerHTML = strategyHeadHtml('market') + `<section class="card rd-listen"><div id="set-listening">${skelRows(2, {card: true, dot: false})}</div></section>`;
  marketViewSwitch('listening');
  void renderSettingsListening();
}

// ----------------------------------------------------------------- the Strategy Bot's panel
// Beside every Strategy tab: a right rail on a desktop, a sheet behind a button on a phone. It stays mounted while
// the tabs change, so a conversation and a half-typed message survive a switch; leaving Strategy stops it.
let SBOT = null;            // {el, fab, rail}
function syncStrategyBot() {
  const want = redesignOn() && rdUnder((S.route || '').split('?')[0], '#/strategy');
  if (!want) {
    if (SBOT) { SBOT.rail.stop?.(); SBOT.el.remove(); SBOT.fab.remove(); SBOT = null; }
    return;
  }
  $('#main').classList.add('sbot-open');
  if (SBOT?.el.isConnected) return;
  const name = ceoBotName();
  const el = document.createElement('aside');
  el.id = 'sbot'; el.className = 'sbot'; el.setAttribute('aria-label', name);
  el.innerHTML = `<header class="sbot-head"><span class="nav-icon" aria-hidden="true">auto_awesome</span><h2>${esc(name)}</h2>
      <button class="sbot-close" type="button" aria-label="Close">✕</button></header><div class="sbot-body"></div>`;
  const fab = document.createElement('button');
  fab.type = 'button'; fab.id = 'sbot-fab'; fab.className = 'sbot-fab'; fab.setAttribute('aria-controls', 'sbot');
  fab.innerHTML = `<span class="nav-icon" aria-hidden="true">auto_awesome</span><span>${esc(name)}</span>`;
  document.body.append(el, fab);
  const rail = {host: el.querySelector('.sbot-body')};
  SBOT = {el, fab, rail};
  fab.onclick = () => { el.classList.add('open'); el.querySelector('.p-text')?.focus(); };
  el.querySelector('.sbot-close').onclick = () => el.classList.remove('open');
  void goalManagerMount(null, rail);
}

// ----------------------------------------------------------------- Settings > General
// The owner's switch. A reload draws the whole app again in the chosen design.
function redesignSettingHtml() {
  return `<div class="rd-setting-row"><label class="rd-switch"><input type="checkbox" role="switch" class="people-switch" id="redesign-switch"${redesignOn() ? ' checked' : ''}>
    <span>New design</span></label>${helpBubble('Strategy tabs, Budget, Automations and the new sidebar. Off keeps today’s app.')}
    <span class="err" id="redesign-switch-err" role="alert" hidden></span></div>`;
}
document.addEventListener('change', async ev => {
  const box = ev.target.closest?.('#redesign-switch');
  if (!box) return;
  const err = $('#redesign-switch-err');
  box.disabled = true; err.hidden = true;
  try { await put('/v2/settings/redesign', {enabled: box.checked}); location.reload(); }
  catch (e) { box.checked = !box.checked; box.disabled = false; err.textContent = e.message; err.hidden = false; }
});
