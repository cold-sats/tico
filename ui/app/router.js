/* ui/app/router.js — route(): hash routes to pages
   Classic script: its globals are shared with the other files under ui/app/, loaded in the order index.html lists them. */
'use strict';

let LAST_ROUTE = '';
function route() {
  GOAL_MANAGER_STOP?.();
  const from = LAST_ROUTE;
  S.route = LAST_ROUTE = location.hash || UPDATES;
  const botOf = r => r.startsWith('#/bot/') ? r.slice(6).split('/')[0] : '';
  const botHere = botOf(S.route);
  document.body.classList.toggle('bot-page', !!botHere);   // a phone gives the bot page the whole screen
  window.TicoObservability?.route(S.route);
  document.body.classList.remove('mobile-composer-focus');
  $('#main').classList.remove('chat-layout', 'bot-chat-layout', 'mail-layout', 'messaging-layout', 'docs-layout', 'market-layout');
  if (!(S.route === '#/market' || S.route.startsWith('#/market?') || S.route.startsWith('#/market/'))) window.marketStop?.();
  taskChatStop(); $('#task-modal')?.close();
  if (!S.route.startsWith(DOCS)) DOC_LOAD++;
  // Leaving Mail abandons its fetches, its debounced search (which would set the hash back) and
  // its accumulated page, so returning re-reads the server instead of drawing a stale list.
  if (!S.route.startsWith(MAIL)) { MAIL_LOAD++; clearTimeout(MAIL_SEARCH); mailForget(); }
  if (!S.route.startsWith(MESSAGING)) { MESSAGING_LOAD++; MESSAGING_LIST = null; }
  convStop(); meetStop(); onbStop(); TASKS_ST = null; // page-local work never outlives its page
  if (S.route !== '#/usage') USE = null;
  if (UPD && !(S.route === UPDATES || S.route.startsWith(UPDATES + '?'))) { UPD.io?.disconnect(); void updFlush(UPD); UPD = null; }
  if (!S.route.startsWith('#/bot/')) botStopped();
  renderTree();
  if (S.route === OVERVIEW || S.route === NOTES || S.route === RECORDINGS || S.route.startsWith(RECORDINGS + '?')) {
    // Old links land on Meetings, keeping a deep link to one meeting.
    const id = new URLSearchParams(S.route.split('?')[1] || '').get('recording');
    location.hash = MEETINGS + (id ? '?meeting=' + encodeURIComponent(id) : ''); return;
  }
  else if (S.route === '#/inbox' || S.route.startsWith('#/inbox?')) { location.hash = MAIL; return; }
  else if (S.route === WELCOME) pageWelcome();
  else if (S.route === '#/tags') pageTags();
  else if (S.route.startsWith('#/tag/')) pageTag(decodeURIComponent(S.route.slice(6)));
  else if (S.route.startsWith('#/task/')) pageTasks('', decodeURIComponent(S.route.slice(7)));
  else if (S.route === CHAT) { location.hash = TASKS; return; }
  else if (S.route === MEETINGS || S.route.startsWith(MEETINGS + '?')) pageNotes();
  else if (S.route.startsWith('#/bot/')) { const [slug, tab] = S.route.slice(6).split('/'); pageBot(slug, tab); }
  else if (S.route.startsWith('#/person/')) {
    const parts = S.route.slice(9).split('/').map(decodeURIComponent);
    pagePerson(parts[0], parts[1]);
  }
  else if ([TASKS, BOARD, ISSUES, RECURRING].includes(S.route)) {
    pageTasks(S.route === BOARD ? 'board' : S.route === ISSUES ? 'list' : S.route === RECURRING ? 'recurring' : '');
  }
  else if (S.route === UPDATES || S.route.startsWith(UPDATES + '?')) pageUpdates();
  else if (S.route === GOALS || S.route.startsWith(GOALS + '/') || S.route.startsWith(GOALS + '?')) pageGoals();
  else if (S.route === SETTINGS) pageSettings();
  else if (S.route === HELP) pageHelp();
  else if (S.route === '#/getting-started') { location.replace(TASKS); return; }   // the checklist is gone
  else if (S.route === '#/health') { SETTINGS_TAB = 'health'; location.replace(SETTINGS); return; }   // Health moved into Settings
  else if (S.route === CREDENTIALS) pageCredentials();
  else if (S.route === SQL_PAGE) pageSql();
  else if (S.route === MAIL || S.route.startsWith(MAIL + '?')) pageMail();
  else if (S.route === MESSAGING || S.route.startsWith(MESSAGING + '?')) pageMessaging();
  else if (S.route === '#/changelog') pageChangelog();
  else if (S.route === '#/market' || S.route.startsWith('#/market?') || S.route.startsWith('#/market/')) pageMarket();
  else if ((S.route === DOCS || S.route.startsWith(DOCS + '/') || S.route.startsWith(DOCS + '?')) && new URLSearchParams(S.route.split('?')[1] || '').get('collection') === 'market') {
    const id = S.route.startsWith(DOCS + '/') ? S.route.slice(DOCS.length + 1).split('?')[0] : '';
    location.hash = '#/market' + (id ? '?note=' + encodeURIComponent(id) : '');
    return;
  }
  else if (S.route === DOCS || S.route.startsWith(DOCS + '/') || S.route.startsWith(DOCS + '?')) pageCompanyDocs();
  else if (S.route === INTEGRATIONS || S.route.startsWith(INTEGRATIONS + '/')) pageIntegrations();
  else if (S.route === '#/runs') pageRuns();
  else if (S.route === '#/usage') pageUsage();
  else location.hash = UPDATES;         // unknown or empty routes land on Updates, home
  window.syncLibrarianRail?.();
  $('#main').scrollTop = 0;
}
window.addEventListener('hashchange', route);
