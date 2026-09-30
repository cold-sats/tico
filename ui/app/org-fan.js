/* ui/app/org-fan.js — Mobile org switcher
   Classic script: its globals are shared with the other files under ui/app/, loaded in the order index.html lists them. */
'use strict';

// ---- Org switcher (mobile): the bots you were just at, nearest the thumb, then the ones that need you
// The bots from the shared history (the desktop Org history uses the same list), then any from this
// phone's older list (tico.org.recent) that the shared one has not seen.
function orgRecent() {
  let old = []; try { old = JSON.parse(localStorage.getItem('tico.org.recent') || '[]').filter(x => typeof x === 'string'); } catch {}
  const bots = orgHistory().filter(k => k.startsWith('b:')).map(k => k.slice(2));
  return [...bots, ...old.filter(slug => !bots.includes(slug))];
}
// Bottom up: the eight most recent (most recent lowest), then every bot that needs you, most first.
// "show the top 8 recent. Make sure they are easily clickable (bigger/spread out)".
function orgFanBots() {
  const shown = new Set(shownEmps().map(e => e.name));
  const recent = orgRecent().filter(slug => shown.has(slug)).slice(0, 8);
  const needs = [...shown].filter(slug => !recent.includes(slug))
    .map(slug => ({slug, n: needsMeCount(slug) + (stateOf(slug) === 'needs' ? 1 : 0)}))
    .filter(x => x.n > 0).sort((a, b) => b.n - a.n || botDisplayName(a.slug).localeCompare(botDisplayName(b.slug)));
  // Ten at most: eight recent, the rest waiting on you. A short screen scrolls the list.
  return [...recent.map(slug => ({slug, recent: true, n: needsMeCount(slug)})), ...needs].slice(0, 10);
}
let ORG_FAN_HIDE = 0;
function orgFanClose() {
  const fan = $('#org-fan'); if (!fan || fan.hidden) return;
  fan.classList.remove('open');
  (ORG_FAN_FROM || $('#mobile-org')).setAttribute('aria-expanded', 'false');
  fan.hidden = true;
}
// In a bot's chat on a phone, its icon left of the chat bar opens the same fan
// over the bar: the four bots most recently opened (not this one), with Search on top of the stack.
function orgFanChatBots(current) {
  const shown = new Set(shownEmps().map(e => e.name));
  return orgRecent().filter(slug => shown.has(slug) && slug !== current).slice(0, 4)
    .map(slug => ({slug, recent: true, n: needsMeCount(slug)}));
}
let ORG_FAN_FROM = null;
function orgFanOpen(opts = {}) {
  const fan = $('#org-fan');
  clearTimeout(ORG_FAN_HIDE);        // a close just before (a back navigation) must not hide it again
  const chat = !!opts.chat;
  const bots = chat ? orgFanChatBots(opts.chat) : orgFanBots();
  if (!bots.length && !chat) { searchOpen(); return; }  // nothing recent and nothing waiting: pick one
  const item = (b, i) => `<li><button class="org-fan-item" type="button" role="menuitem" data-org-bot="${esc(b.slug)}" style="--i:${i}">
      ${avatar(b.slug, 34)}<span>${empName(b.slug)}</span>${b.n ? `<span class="org-fan-badge" aria-label="${b.n} need you">${b.n}</span>` : ''}</button></li>`;
  const search = i => `<li><button class="org-fan-item org-fan-search" type="button" role="menuitem" data-org-search style="--i:${i}">
      <span class="nav-icon org-fan-search-icon" aria-hidden="true">search</span><span>Search</span></button></li>`;
  fan.querySelector('.org-fan-list').innerHTML = bots.map(item).join('') + (chat ? search(bots.length) : '');
  // Over the chat bar it rises from the bar, not from the bottom navigation.
  const at = opts.anchor?.getBoundingClientRect();
  fan.style.paddingBottom = at ? `${Math.max(0, window.innerHeight - at.top + 10)}px` : '';
  fan.hidden = false;
  ORG_FAN_FROM = opts.anchor || $('#mobile-org');
  ORG_FAN_FROM.setAttribute('aria-expanded', 'true');
  fan.classList.add('open');
}
$('#mobile-org').onclick = () => ($('#org-fan').hidden ? orgFanOpen() : orgFanClose());
$('#org-fan').addEventListener('click', ev => {
  const b = ev.target.closest('[data-org-bot]');
  if (b) location.hash = '#/bot/' + encodeURIComponent(b.dataset.orgBot);
  const find = ev.target.closest('[data-org-search]');
  orgFanClose();
  if (find) searchOpen();
});
document.addEventListener('keydown', ev => { if (ev.key === 'Escape') orgFanClose(); });
window.addEventListener('hashchange', orgFanClose);
