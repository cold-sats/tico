/* After the wizard: the tour, the Getting started page and the cards at the top of each section
   (docs/onboarding.md). Every tick on the checklist comes from GET /api/v2/getting-started; the
   only things kept per person are their own choices (tour seen, card closed, checklist hidden). */
let GS = null;                     // the last answer, or null when the server has no checklist to give
let GS_LOAD = 0;
let GS_SENT = null;                // the confirmation a card keeps showing after its form was sent
// "Not now" on a card lasts for this browser session; the server only keeps "don't show again".
const GS_LATER_KEY = 'tico.gs.later';
const gsLater = () => { try { return JSON.parse(sessionStorage.getItem(GS_LATER_KEY) || '[]'); } catch { return []; } };
const gsLaterAdd = section => { try { sessionStorage.setItem(GS_LATER_KEY, JSON.stringify([...new Set([...gsLater(), section])])); } catch { /* the card returns on reload */ } };

const gsCards = {
  docs: {owner: true, title: 'Where do your current docs live?'},
  market: {owner: true, title: 'Research your market'},
  tasks: {title: 'Tasks', text: 'Work you hand to a bot or a person. Every task has an owner and a status, and bots pick theirs up on their own.',
          action: ['Create a task', '#task-new']},
  updates: {title: 'Updates', text: 'Each bot posts a few bullets every day, and a fuller look on Fridays. They land here as they arrive.'},
  goals: {title: 'Goals', text: 'A goal says, in plain English, what a bot or a person is going for, with a colour for how it is going.',
          action: ['Set a first goal', '[data-goal-add]']},
  meetings: {title: 'Meetings', text: 'Import a meeting transcript and your bots pick out the tasks and follow-ups.',
             action: ['Import a transcript', '#notes-import']},
};

const gsRoute = () => {
  const r = S.route || '';
  const at = (base) => r === base || r.startsWith(base + '?') || r.startsWith(base + '/');
  if (at('#/updates')) return 'updates';
  if (['#/tasks', '#/board', '#/issues', '#/recurring'].includes(r) || r.startsWith('#/task/')) return 'tasks';
  if (at('#/goals')) return 'goals';
  if (at('#/meetings')) return 'meetings';
  if (at('#/market')) return 'market';
  if (at('#/docs')) return 'docs';
  return '';
};

async function gsRefresh() {
  if (!S.me?.cloud) return null;
  const seq = ++GS_LOAD;
  const data = await v2Get('/v2/getting-started');
  if (seq !== GS_LOAD) return GS;
  GS = data && Array.isArray(data.items) ? data : null;
  gsDraw();
  return GS;
}

function gsDraw() {
  gsNav();
  window.hlNav?.();
  gsCard();
  gsOrgCard();
  if (S.route === '#/getting-started') gsPageDraw();
}

async function gsState(change) {
  try {
    const next = await post('/v2/getting-started/state', change);
    if (GS && next) {
      GS = {...GS, tour_seen: next.tour, dismissed: next.checklist, cards_dismissed: next.cards};
      const skipped = new Set(next.skipped || []);
      GS.items = GS.items.map(item => ({...item, skipped: item.optional && !item.done && skipped.has(item.id)}));
      const settled = GS.items.filter(item => item.done || item.skipped).length;
      GS = {...GS, done: settled, complete: settled === GS.total};
    }
  } catch { /* a choice that did not save is asked again next time */ }
  gsDraw();
}

// ---------------------------------------------------------------- the rail
function gsNav() {
  const link = $('#nav-getting-started');
  if (!link) return;
  const shown = !!GS && !GS.complete && !GS.dismissed;
  link.hidden = !shown && S.route !== '#/getting-started';
  const count = $('#gs-count');
  if (count && GS) count.textContent = `${GS.done}/${GS.total}`;
}

function gsOrgCard() {
  const host = $('#gs-org-card');
  if (!host) return;
  const bot = GS?.items.find(item => item.id === 'first_bot');
  const shown = !!bot && !bot.done && GS.can_build && !GS.cards_dismissed.includes('bots');
  host.hidden = !shown;
  if (!shown) { host.innerHTML = ''; return; }
  host.innerHTML = `<p><strong>No bots of your own yet.</strong></p>
    <div class="gs-org-actions">
      <button class="ghost" type="button" data-gs-connect>Connect a bot you already have</button>
      <button class="ghost" type="button" data-gs-build>Build one with BotOps</button>
    </div>
    <button class="ghost gs-x" type="button" data-gs-dismiss="bots" aria-label="Close this">✕</button>`;
}

// ---------------------------------------------------------------- cards at the top of a section
function gsWhenReady(selector) {
  let tries = 0;
  const look = () => {
    const el = document.querySelector('#main ' + selector);
    if (el) el.click();
    else if (++tries < 30) setTimeout(look, 100);
  };
  look();
}

function gsCard() {
  const host = $('#gs-card');
  if (!host) return;
  const section = gsRoute();
  const spec = gsCards[section];
  const sent = GS_SENT && GS_SENT.section === section ? GS_SENT : null;
  // A card stays while its section is empty, and goes once the section has content.
  const empty = GS?.empty?.[section] !== false;
  const researching = section === 'market' ? gsResearchGet() : null;
  const shown = !!spec && (!!sent || !!researching || (!!GS && empty && !GS.cards_dismissed.includes(section)
    && !gsLater().includes(section) && (!spec.owner || GS.owner)));
  gsResearchWatch(!!researching && shown);
  if (!shown) { host.hidden = true; host.innerHTML = ''; host.dataset.mode = ''; return; }
  const mode = `${section}:${sent ? 'sent' : researching ? 'researching' : 'form'}`;
  if (host.dataset.mode === mode && !host.hidden) return;   // a half-typed form is left alone
  host.dataset.mode = mode;
  host.hidden = false;
  let body;
  if (sent) body = `<strong>${esc(spec.title)}</strong><p role="status">${sent.html}</p>`;
  else if (researching) body = gsResearchHtml(researching);
  else if (section === 'docs') body = gsDocsForm();
  else if (section === 'market') body = gsMarketForm();
  else body = `<strong>${esc(spec.title)}</strong><p>${esc(spec.text)}</p>${spec.action
    ? `<div class="gs-card-actions"><button class="primary" type="button" data-gs-run="${esc(spec.action[1])}">${esc(spec.action[0])}</button></div>` : ''}`;
  host.innerHTML = `<aside class="gs-card" data-gs-card="${section}" aria-label="${esc(spec.title)}">
    <div class="gs-card-body">${body}</div>
    <div class="gs-card-side">${researching ? '' : `<button class="ghost gs-x" type="button" data-gs-later="${section}" aria-label="Not now">✕</button>`}
      ${sent || researching ? '' : `<button class="ghost gs-never" type="button" data-gs-dismiss="${section}">Don't show again</button>`}</div></aside>`;
}

// One row per link: the address, and what is in it. Kind is detected from the address (backend/docs.py).
const gsLinkRow = () => `<div class="gs-link-row" data-gs-link-row>
    <label class="gs-field"><span>Link</span><input name="url" maxlength="2000" autocomplete="off" inputmode="url" placeholder="https://drive.google.com/drive/folders/…"></label>
    <label class="gs-field"><span>What is in it? (optional)</span><input name="description" maxlength="300" autocomplete="off" placeholder="Help centre articles"></label>
    <small class="gs-kind muted" data-gs-kind aria-live="polite"></small></div>`;

function gsDocsForm() {
  return `<strong>Where do your current docs live?</strong>
    <p>Paste a link to each place: your help site, a Drive folder, a Notion page, a GitHub repository, anything. Tico keeps the links and never copies what is inside them.</p>
    <form data-gs-docs>
      <div data-gs-links>${gsLinkRow()}</div>
      <button class="ghost gs-add" type="button" data-gs-add-link>Add another link</button>
      <p class="err" data-gs-error hidden></p>
      <div class="gs-card-actions"><button class="primary" type="submit">Link my docs</button></div>
      <p class="gs-alt">No docs yet? <a href="#/docs/new">Write your first internal doc</a>. Files to upload? <a href="#/docs?import=1">Import them</a>.</p>
    </form>`;
}

// One box: whatever the owner has about their market. The Librarian reads it and builds the map
// (templates/catalog/librarian/playbooks/market-setup.md); "Attach files" is the Docs import.
function gsMarketForm() {
  return `<strong>Research your market</strong>
    <form class="gs-market" data-gs-market>
      <label class="gs-field"><span>Your website, a description, or links to anything about your market</span>
        <textarea name="text" rows="3" maxlength="8000" required autocomplete="off" placeholder="https://yourcompany.com"></textarea></label>
      <p class="err" data-gs-error hidden></p>
      <div class="gs-card-actions"><button class="primary" type="submit">Start research</button>
        <a class="gs-attach" href="#/docs?import=1">Attach files</a></div>
    </form>`;
}

// ---------------------------------------------------------------- the Librarian is researching
// A notice kept in this browser, no server involved: it shows for at least two minutes and until the
// market has content, and goes for good after thirty. While it shows, the market's own data is read
// every thirty seconds (two small GETs), and the Market page is redrawn when that has changed.
// Styles for the market card and its notice live here, beside the code that draws them.
const gsStyle = document.createElement('style');
gsStyle.textContent = `.gs-market .gs-field{max-width:680px}
.gs-market textarea{min-height:76px;resize:vertical;font:inherit}
.gs-attach{align-self:center;font-size:13px}
.gs-researching{display:flex;align-items:flex-start;gap:var(--s3)}
.gs-researching p{margin:2px 0 0}
.gs-spin{flex:none;width:14px;height:14px;margin-top:3px;border-radius:50%;border:2px solid var(--line);border-top-color:var(--accent);animation:gsspin .9s linear infinite}
@keyframes gsspin{to{transform:rotate(360deg)}}
@media (prefers-reduced-motion:reduce){.gs-spin{animation:none;border-color:var(--accent)}}
.gs-page-card{margin:var(--s4) 0}
@media (max-width:600px){.gs-card[data-gs-card=market]{flex-direction:column}.gs-card[data-gs-card=market] .gs-card-body{align-self:stretch}.gs-card[data-gs-card=market] .gs-card-side{flex-direction:row;align-items:center;align-self:flex-end}}`;
document.head.appendChild(gsStyle);

const GS_RESEARCH_KEY = 'tico.market.researching';
const GS_RESEARCH_MIN = 2 * 60 * 1000, GS_RESEARCH_MAX = 30 * 60 * 1000, GS_RESEARCH_POLL = 30 * 1000;
let GS_RESEARCH = null;            // the same record in memory, for a browser that will not store it
let GS_POLL = 0;
let GS_SIG = null;

function gsResearchGet() {
  let row = GS_RESEARCH;
  try { row = JSON.parse(localStorage.getItem(GS_RESEARCH_KEY) || 'null') || row; } catch { /* the memory copy stands */ }
  const age = row ? Date.now() - Number(row.at) : NaN;
  if (row && age >= -60000 && age < GS_RESEARCH_MAX) return row;
  if (row) gsResearchSet(null);
  return null;
}

function gsResearchSet(row) {
  GS_RESEARCH = row;
  try { if (row) localStorage.setItem(GS_RESEARCH_KEY, JSON.stringify(row)); else localStorage.removeItem(GS_RESEARCH_KEY); } catch { /* memory only */ }
}

const gsResearchHtml = row => `<div class="gs-researching" data-gs-researching role="status">
    <span class="gs-spin" aria-hidden="true"></span>
    <div><strong>The Librarian is researching your market.</strong>
      <p>This usually takes 5–10 minutes.${row.task ? ` ${gsTaskLink(row.task, 'View task')}` : ''}</p></div></div>`;

function gsResearchWatch(on) {
  if (!on) { clearInterval(GS_POLL); GS_POLL = 0; GS_SIG = null; return; }
  if (!GS_POLL) GS_POLL = setInterval(() => void gsResearchTick(), GS_RESEARCH_POLL);
}

// What the market holds, in one string: how many entities, and when its newest page was written. The seed's
// pages are already there when the owner asks, so "has content" means "differs from what it was when asked".
async function gsMarketSig() {
  const [entities, pages] = await Promise.all([get('/v2/market/entities'), get('/company-docs?collection=market')]);
  const written = (pages.documents || []).filter(doc => doc.id !== 'market/weekly-delta').map(doc => String(doc.fetched || ''));
  return `${(entities.entities || []).length}|${written.reduce((a, b) => a > b ? a : b, '')}`;
}

async function gsResearchTick() {
  if (!gsResearchGet()) { gsResearchWatch(false); gsDraw(); return; }   // thirty minutes passed: the card is back
  let sig;
  try { sig = await gsMarketSig(); } catch { return; }                    // the next tick tries again
  const row = gsResearchGet();
  if (!row) return;
  const last = GS_SIG ?? row.base;
  GS_SIG = sig;
  const arrived = row.base == null ? !sig.startsWith('0|') : sig !== row.base;
  if (arrived && Date.now() - Number(row.at) >= GS_RESEARCH_MIN) {
    gsResearchSet(null);
    gsResearchWatch(false);
    await gsRefresh();                                                    // the card's own "is it empty" answer
    window.marketReload?.();
  } else if (sig !== last) window.marketReload?.();
}

async function gsSubmitMarket(form) {
  const text = form.elements.text.value.trim();
  if (!text) return gsFail(form, new Error('Add your website, a description or a link.'));
  form.querySelector('[type=submit]').disabled = true;
  try {
    const base = await gsMarketSig().catch(() => null);
    const result = await post('/v2/getting-started/market', {text});
    gsResearchSet({at: Date.now(), task: result.task_id || '', base});
    gsDraw();
  } catch (error) { gsFail(form, error); }
}

function gsFail(form, error) {
  const line = form.querySelector('[data-gs-error]');
  line.textContent = error.message || 'That did not go through.';
  line.hidden = false;
  form.querySelector('[type=submit]').disabled = false;
}

function gsSent(section, html) {
  GS_SENT = {section, html};
  gsDraw();
  void gsState({card: section});
}

const gsTaskLink = (id, text) => id ? `<a href="#/task/${esc(id)}">${text}</a>` : '';

async function gsSubmitDocs(form) {
  const links = [...form.querySelectorAll('[data-gs-link-row]')].map(row => ({
    url: row.querySelector('[name=url]').value.trim(), description: row.querySelector('[name=description]').value.trim()}))
    .filter(row => row.url);
  if (!links.length) return gsFail(form, new Error('Paste at least one link.'));
  form.querySelector('[type=submit]').disabled = true;
  try {
    const result = await post('/v2/getting-started/docs', {links});
    if (!result.linked.length) return gsFail(form, new Error(result.skipped.map(row => `${row.url}: ${row.reason}`).join(' ')));
    const skipped = result.skipped.length ? ` ${result.skipped.length} could not be added: ${result.skipped.map(row => esc(row.url)).join(', ')}.` : '';
    gsSent('docs', `Linked ${result.linked.length} ${result.linked.length === 1 ? 'doc' : 'docs'}. <a href="#/docs">Open Docs</a>.${skipped}`);
    window.dispatchEvent(new Event('tico-docs-changed'));
  } catch (error) { gsFail(form, error); }
}

// ---------------------------------------------------------------- "What should your bot do?"
function gsBotForm() {
  const dialog = document.createElement('dialog');
  dialog.className = 'tmodal gs-form';
  dialog.setAttribute('aria-labelledby', 'gs-bot-title');
  dialog.innerHTML = `<form data-gs-bot>
    <header><h2 id="gs-bot-title">What should your bot do?</h2>
      <button class="ghost tmodal-x" type="button" data-close aria-label="Close">✕</button></header>
    <label class="gs-field"><span>What should it do?</span>
      <textarea name="what" rows="4" maxlength="2000" required placeholder="Answer the support inbox every morning and flag anything urgent."></textarea></label>
    <label class="gs-field"><span>Name (optional)</span><input name="name" maxlength="80" autocomplete="off" placeholder="Help Desk"></label>
    <p role="status" data-gs-status></p>
    <div class="gs-card-actions"><button class="ghost" type="button" data-close data-gs-close>Cancel</button>
      <button class="ghost" type="button" data-gs-another hidden>Build another</button>
      <button class="primary" type="submit">Ask BotOps</button></div></form>`;
  document.body.appendChild(dialog);
  // The dialog belongs to the page it was opened on; going elsewhere (the task link, a rail item) ends it.
  const leave = () => dialog.close();
  window.addEventListener('hashchange', leave);
  dialog.addEventListener('close', () => { window.removeEventListener('hashchange', leave); dialog.remove(); });
  dialog.addEventListener('click', event => {
    if (event.target === dialog || event.target.closest('[data-close]')) dialog.close();
  });
  dialog.querySelector('form').onsubmit = async event => {
    event.preventDefault();
    const form = event.target, status = form.querySelector('[data-gs-status]');
    form.querySelector('[type=submit]').disabled = true;
    try {
      const made = await post('/v2/getting-started/bot', {what: form.what.value.trim(), name: form.name.value.trim()});
      status.innerHTML = `Sent to BotOps. ${gsTaskLink(made.task_id, 'Open the task')}`;
      form.querySelector('[type=submit]').hidden = true;
      form.querySelector('[data-gs-close]').textContent = 'Done';
      form.querySelector('[data-gs-another]').hidden = false;
      void gsRefresh();
    } catch (error) {
      status.textContent = error.message;
      form.querySelector('[type=submit]').disabled = false;
    }
  };
  dialog.querySelector('[data-gs-another]').onclick = event => {
    const form = dialog.querySelector('form');
    form.reset();
    form.querySelector('[data-gs-status]').textContent = '';
    form.querySelector('[type=submit]').hidden = false;
    form.querySelector('[type=submit]').disabled = false;
    form.querySelector('[data-gs-close]').textContent = 'Cancel';
    event.target.hidden = true;
    form.what.focus();
  };
  dialog.showModal();
  dialog.querySelector('textarea').focus();
}

// ---------------------------------------------------------------- the checklist page
function gsItemHtml(item) {
  const state = item.done ? 'done' : item.skipped ? 'skipped' : 'todo';
  const icon = item.done ? 'check_circle' : item.skipped ? 'remove_circle' : 'radio_button_unchecked';
  const login = item.login && !item.done && !item.skipped
    ? `<button class="primary" type="button" data-model-login data-runner="${esc(item.login.runner_id)}" data-runtime="${esc(item.login.runtime)}" data-machine="${esc(item.login.machine)}">Sign in</button>` : '';
  const fix = item.done || item.skipped ? '' : item.action === 'create-bot'
    ? '<button class="primary" type="button" data-gs-build>Create a bot</button>'
    : item.href ? `<a class="ghost gs-link" href="${esc(item.href)}"${item.tab ? ` data-gs-tab="${esc(item.tab)}"` : ''}>${item.id === 'first_bot' || item.id === 'bot_task' ? 'Open' : 'Fix this'}</a>` : '';
  const skip = item.optional && !item.done && !item.skipped
    ? `<button class="ghost" type="button" data-gs-skip="${esc(item.id)}">Skip</button>` : '';
  return `<li class="gs-item ${state}" data-gs-item="${esc(item.id)}" data-state="${state}">
    <span class="nav-icon gs-tick" aria-hidden="true">${icon}</span>
    <div class="gs-item-main"><strong>${esc(item.label)}</strong>${item.optional ? ' <span class="muted">optional</span>' : ''}
      ${item.why ? `<p class="muted">${esc(item.why)}</p>` : ''}</div>
    <div class="gs-item-actions">${login}${fix}${skip}</div></li>`;
}

// The market card, on the checklist page too: the form while the market is empty, the notice while it works.
function gsMarketPanel() {
  const researching = gsResearchGet();
  gsResearchWatch(!!researching);
  const body = researching ? gsResearchHtml(researching)
    : GS?.owner && GS.empty?.market !== false && !GS.cards_dismissed.includes('market') ? gsMarketForm() : '';
  return body ? `<aside class="gs-card gs-page-card" data-gs-card="market" aria-label="Research your market"><div class="gs-card-body">${body}</div></aside>` : '';
}

function gsPageDraw() {
  const host = $('#gs-page');
  if (!host) return;
  const box = host.querySelector('[data-gs-market] textarea');
  if (box && document.activeElement === box) return;      // a box being typed in is left alone
  const typed = box?.value || '';
  if (!GS) { host.innerHTML = '<div class="empty">Nothing to show yet.</div>'; return; }
  host.innerHTML = `<h1>Getting started</h1>
    <p class="muted" id="gs-progress">${GS.done} of ${GS.total} done${GS.complete ? '. All set.' : ''}</p>
    <ul class="gs-list">${GS.items.map(gsItemHtml).join('')}</ul>
    ${gsMarketPanel()}
    <div class="gs-page-actions">
      <button class="ghost" type="button" data-gs-tour>Take the tour</button>
      <button class="ghost" type="button" data-gs-hide>${GS.dismissed ? 'Show in the sidebar' : 'Hide this'}</button>
    </div>`;
  const again = host.querySelector('[data-gs-market] textarea');
  if (again && typed) again.value = typed;
}

window.pageGettingStarted = function pageGettingStarted() {
  $('#main').innerHTML = '<div class="gs-page" id="gs-page"><div class="empty">Loading…</div></div>';
  void gsRefresh().then(() => { if (!GS) gsPageDraw(); });
};

// ---------------------------------------------------------------- the tour
const GS_STEPS = [
  ['[data-nav="updates"]', 'Updates', 'Every bot posts a short update each day, and a fuller one on Fridays.'],
  ['[data-nav="tasks"]', 'Tasks', 'Work for bots and people. Give a task an owner and it gets done, or comes back with a question.'],
  ['#nav-organisation', 'Your bots', 'Your bots are listed here. Open one to chat, see its work and change its settings.'],
  ['[data-nav="docs"]', 'Docs', 'Your company docs, searchable, with questions answered from them.'],
  ['[data-nav="market"]', 'Market', 'A map of your competitors, customers and channels that a bot keeps current.'],
  ['[data-nav="meetings"]', 'Meetings', 'Import a transcript and bots pull out the tasks and follow-ups.'],
];
let GS_TOUR = null;

function gsTourStart() {
  if (GS_TOUR) return;
  const phone = drawerMedia.matches;
  if (phone) setDrawer(true, false, $('#mobile-more'));
  const steps = GS_STEPS.filter(([selector]) => {
    const el = $('#side ' + selector);
    return el && el.getClientRects().length;
  });
  if (!steps.length) { if (phone) setDrawer(false); return; }
  const root = document.createElement('div');
  root.className = 'gs-tour';
  root.setAttribute('role', 'dialog');
  root.setAttribute('aria-modal', 'true');
  root.setAttribute('aria-labelledby', 'gs-tour-title');
  root.innerHTML = `<div class="gs-tour-hole"></div><div class="gs-tour-card">
    <p class="gs-tour-count muted"></p><h2 id="gs-tour-title"></h2><p class="gs-tour-text"></p>
    <div class="gs-tour-actions"><button class="ghost" type="button" data-tour-skip>Skip</button>
      <button class="primary" type="button" data-tour-next>Next</button></div></div>`;
  document.body.appendChild(root);
  const opener = document.activeElement;
  GS_TOUR = {root, steps, at: 0, phone, opener};
  const onKey = event => {
    if (event.key === 'Escape') { event.preventDefault(); event.stopPropagation(); gsTourEnd(); }
    else if (event.key === 'Tab') {
      const buttons = [...root.querySelectorAll('button')];
      const i = buttons.indexOf(document.activeElement);
      event.preventDefault();
      buttons[(i + (event.shiftKey ? buttons.length - 1 : 1)) % buttons.length].focus();
    }
  };
  const onFocus = event => { if (!root.contains(event.target)) root.querySelector('[data-tour-next]').focus(); };
  document.addEventListener('keydown', onKey, true);
  document.addEventListener('focusin', onFocus);
  window.addEventListener('resize', gsTourPlace);
  GS_TOUR.off = () => {
    document.removeEventListener('keydown', onKey, true);
    document.removeEventListener('focusin', onFocus);
    window.removeEventListener('resize', gsTourPlace);
  };
  root.querySelector('[data-tour-skip]').onclick = () => gsTourEnd();
  root.querySelector('[data-tour-next]').onclick = () => {
    if (GS_TOUR.at === steps.length - 1) gsTourEnd(); else { GS_TOUR.at++; gsTourShow(); }
  };
  gsTourShow();
  root.querySelector('[data-tour-next]').focus();
}

function gsTourShow() {
  const {root, steps, at} = GS_TOUR;
  const [selector, title, text] = steps[at];
  root.querySelector('.gs-tour-count').textContent = `${at + 1} of ${steps.length}`;
  root.querySelector('#gs-tour-title').textContent = title;
  root.querySelector('.gs-tour-text').textContent = text;
  root.querySelector('[data-tour-next]').textContent = at === steps.length - 1 ? 'Done' : 'Next';
  $('#side ' + selector)?.scrollIntoView({block: 'nearest'});
  gsTourPlace();
}

function gsTourPlace() {
  if (!GS_TOUR) return;
  const {root, steps, at} = GS_TOUR;
  const target = $('#side ' + steps[at][0]);
  if (!target) return;
  const box = target.getBoundingClientRect(), pad = 4;
  const hole = root.querySelector('.gs-tour-hole'), card = root.querySelector('.gs-tour-card');
  Object.assign(hole.style, {left: box.left - pad + 'px', top: box.top - pad + 'px',
    width: box.width + pad * 2 + 'px', height: Math.min(box.height, innerHeight - box.top) + pad * 2 + 'px'});
  const width = card.offsetWidth, height = card.offsetHeight;
  if (GS_TOUR.phone) {
    // The list is in the drawer, so the card takes whichever end of the screen the row is not at.
    const low = box.top + box.height / 2 > innerHeight / 2;
    Object.assign(card.style, {left: '12px', right: '12px', width: 'auto', top: low ? '12px' : 'auto', bottom: low ? 'auto' : '12px'});
    return;
  }
  Object.assign(card.style, {right: 'auto', bottom: 'auto', width: '',
    left: Math.min(box.right + 16, innerWidth - width - 12) + 'px',
    top: Math.max(12, Math.min(box.top, innerHeight - height - 12)) + 'px'});
}

function gsTourEnd() {
  if (!GS_TOUR) return;
  const {root, phone, opener} = GS_TOUR;
  GS_TOUR.off();
  root.remove();
  GS_TOUR = null;
  if (phone) setDrawer(false, true);
  else if (opener && opener.isConnected) opener.focus();
  void gsState({tour: true});
}

window.gsStartTour = gsTourStart;
// The wizard's last screen: the first look around, once per person.
window.gsTourAfterSetup = async function () {
  const seen = await gsRefresh();
  if (!seen?.tour_seen) gsTourStart();
};
window.gsRoute = function () { gsCard(); gsNav(); };
window.gsBoot = function () {
  // Someone who joins later gets the same first look, once, unless the wizard is about to run.
  void gsRefresh().then(seen => {
    if (seen && !seen.tour_seen && !S.config?.onboarding_needed && S.route !== '#/welcome') gsTourStart();
  });
  setInterval(() => { if (!document.hidden && S.me?.cloud) void gsRefresh(); }, 60000);
};

// ---------------------------------------------------------------- one listener for all of it
document.addEventListener('click', event => {
  const t = event.target;
  const later = t.closest('[data-gs-later]');
  if (later) { gsLaterAdd(later.dataset.gsLater); gsDraw(); return; }
  const dismiss = t.closest('[data-gs-dismiss]');
  if (dismiss) { void gsState({card: dismiss.dataset.gsDismiss}); return; }
  const run = t.closest('[data-gs-run]');
  if (run) { gsWhenReady(run.dataset.gsRun); return; }
  const addLink = t.closest('[data-gs-add-link]');
  if (addLink) { const host = addLink.closest('form').querySelector('[data-gs-links]'); host.insertAdjacentHTML('beforeend', gsLinkRow()); host.lastElementChild.querySelector('input').focus(); return; }
  if (t.closest('[data-gs-build]')) { gsBotForm(); return; }
  if (t.closest('[data-gs-connect]')) { connectAgent(); return; }
  if (t.closest('[data-gs-tour]')) { gsTourStart(); return; }
  const skip = t.closest('[data-gs-skip]');
  if (skip) { void gsState({skip: skip.dataset.gsSkip}); return; }
  if (t.closest('[data-gs-hide]')) { void gsState({checklist: !GS?.dismissed}); return; }
  const link = t.closest('[data-gs-tab]');
  if (link) {
    event.preventDefault();
    SETTINGS_TAB = link.dataset.gsTab;
    if (location.hash === link.getAttribute('href')) route(); else location.hash = link.getAttribute('href');
  }
});
// The docs card: a detected kind under each link, more rows on request, and a pasted list of links spread over rows.
document.addEventListener('input', event => {
  const row = event.target.closest('[data-gs-link-row]');
  if (!row || event.target.name !== 'url') return;
  const kind = window.DocsSearch?.kindOf(event.target.value);
  row.querySelector('[data-gs-kind]').textContent = kind ? `Filed as ${DocsSearch.kind(kind).label}` : '';
});
document.addEventListener('paste', event => {
  const row = event.target.closest?.('[data-gs-link-row]');
  const lines = (event.clipboardData?.getData('text') || '').split(/\s*\n\s*/).map(l => l.trim()).filter(Boolean);
  if (!row || event.target.name !== 'url' || lines.length < 2) return;
  event.preventDefault();
  const host = row.parentElement;
  lines.slice(0, 20).forEach((line, i) => {
    let target = [...host.querySelectorAll('[data-gs-link-row]')][[...host.children].indexOf(row) + i];
    if (!target) { host.insertAdjacentHTML('beforeend', gsLinkRow()); target = host.lastElementChild; }
    target.querySelector('[name=url]').value = line;
    target.querySelector('[name=url]').dispatchEvent(new Event('input', {bubbles: true}));
  });
});
document.addEventListener('submit', event => {
  const docs = event.target.closest('[data-gs-docs]'), market = event.target.closest('[data-gs-market]');
  if (!docs && !market) return;
  event.preventDefault();
  if (docs) void gsSubmitDocs(docs); else void gsSubmitMarket(market);
});
