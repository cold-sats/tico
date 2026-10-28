/* ui/app/redesign-library.js — Library › Connections (redesign PLAN §1 decision 14, wave 7): the team's tools from
   GET /api/v2/tools, one row each with its write level, laid out like Automations' list. A row opens the tool's own
   page (integrationDetail, ui/app/integrations.js) beside the list on a computer, as its own screen on a phone.
   Shown, not live: no add button, no grant editing, no write of any kind from here.
   Classic script: its globals are shared with the other files under ui/app/, loaded in the order index.html lists them. */
'use strict';

const RD_CONNECTIONS = '#/library/connections';
const LC_KIND_ICONS = {api: 'api', sql: 'inventory_2', browser: 'travel_explore', mail: 'mail', cli: 'code', mcp: 'link'};
const LC_WRITES = {never: ['Read only', 'ok'], approval: ['Approval', 'waiting'], allowed: ['Writes', '']};
let LC = null;              // {rows, error, service, root}
const lcPhone = () => matchMedia('(max-width:760px)').matches;
const lcHref = service => RD_CONNECTIONS + (service ? '/' + encodeURIComponent(service) : '');

// In use (a bot has it), then what is available, then removed tools whose learnings are kept.
function lcGrouped(rows) {
  const used = rows.filter(r => r.status !== 'removed' && (r.bots || []).length);
  const removed = rows.filter(r => r.status === 'removed');
  const free = rows.filter(r => !used.includes(r) && !removed.includes(r));
  return [['In use', used], ['Available', free], ['Removed', removed]].filter(([, xs]) => xs.length);
}

async function pageRdConnections() {
  const service = decodeURIComponent(S.route.slice(RD_CONNECTIONS.length + 1).split('?')[0] || '');
  $('#main').classList.add('lc-layout');
  if (!LC || !document.body.contains(LC.root)) {
    $('#main').innerHTML = `<div class="lc" id="lc-root">
      <header class="lc-ph"><h1>Connections</h1>${helpBubble('Write level: what bots may change there. Read only, with approval, or freely.')}</header>
      <div class="lc-body"><aside class="lc-list" aria-label="Connections"><div class="lc-scroll"><p class="muted lc-pad">Loading…</p></div></aside>
        <section class="lc-pane" aria-live="polite"><div id="int-detail"></div></section></div></div>`;
    LC = {rows: null, error: '', service: null, root: $('#lc-root')};
    const state = LC;
    try { state.rows = (await get('/v2/tools')).integrations || []; }
    catch (e) { state.rows = []; state.error = e.message; }
    if (LC !== state) return;
  }
  // A computer opens on the first connection; a phone opens on the list.
  if (!service && !lcPhone() && LC.rows.length) { location.replace(lcHref(lcGrouped(LC.rows)[0][1][0].service)); return; }
  LC.root.dataset.screen = service ? 'detail' : 'list';
  lcDrawList(service);
  if (service === LC.service) return;
  LC.service = service;
  const detail = $('#int-detail');
  if (!service) { detail.innerHTML = ''; return; }
  detail.innerHTML = '<p class="muted">Loading…</p>';
  $('.lc-pane').scrollTop = 0;
  const back = `<a class="lc-back" href="${RD_CONNECTIONS}" aria-label="Back"><span class="nav-icon" aria-hidden="true">chevron_left</span></a>`;
  await integrationDetail(service, ++INT_LOAD, {base: RD_CONNECTIONS, head: back, readOnly: true});
}

function lcDrawList(service) {
  const box = LC.root.querySelector('.lc-scroll');
  if (LC.error) { box.innerHTML = `<p class="err lc-pad">${esc(LC.error)}</p>`; return; }
  box.innerHTML = lcGrouped(LC.rows).map(([label, xs]) => `<div class="lc-gh"><span>${esc(label)}</span><span>${xs.length}</span></div>` + xs.map(r => {
    const [word, tone] = LC_WRITES[r.writes] || [r.writes || '', ''];
    const kind = INTEGRATION_KIND[r.kind] || r.kind || '';
    return `<a class="lc-row${r.service === service ? ' sel' : ''}" href="${lcHref(r.service)}" data-service="${esc(r.service)}"${r.service === service ? ' aria-current="page"' : ''} title="${esc(r.summary || r.title)}">
      <span class="nav-icon" aria-hidden="true">${LC_KIND_ICONS[r.kind] || 'api'}</span>
      <span class="lc-nm">${esc(r.title || r.service)} <span class="muted">· ${esc(kind)}</span></span>
      <span class="pill ${tone}" title="Writes: ${esc(r.writes || '')}">${esc(word)}</span></a>`;
  }).join('')).join('') || '<p class="muted lc-pad">No connections yet.</p>';
}
// Leaving the page drops its list, so coming back reads the hub again.
function rdConnectionsStop() { LC = null; }
