/* The building receives only visible identities and read-permitted status. Its renderer is lazy and page-local. */
'use strict';
let OVERVIEW_PAGE = null;
function overviewModel() {
  const groups = (S.orgGroups || []).map(g => ({id: String(g.id), name: String(g.name || g.id), parent: String(g.parent || ''), members: []}));
  const byGroup = new Map(groups.map(g => [g.id, g]));
  const shared = {id: '@shared', name: 'Shared space', parent: '', members: []};
  const support = {id: '@support', name: 'Team services', parent: '', members: []};
  const fresh = S.overviewRosterFresh !== false && S.status !== null && S.v2.on;
  const assign = (member, group, helper = false) => (helper ? support : byGroup.get(group) || shared).members.push(member);
  for (const p of S.people || []) {
    if (p.hidden || !p.id) continue;
    assign({id: 'human:' + p.id, name: p.name || p.id, type: 'human', state: 'human', focus: '',
      detail: 'Human teammate. Presence is not tracked.', href: '#/person/' + encodeURIComponent(p.id)}, p.team);
  }
  for (const e of S.emps || []) {
    if (!e.name || ['archived', 'retired'].includes(e.status || e.state) || e.my_access?.see === false || !orgBranchVisible(e)) continue;
    const readable = e.my_access?.read !== false;
    const live = readable && fresh ? S.v2.status[e.name] : null;
    const state = !readable ? 'restricted' : !fresh ? 'unknown' : ['paused', 'planned'].includes(e.status) ? e.status : live?.state || 'unknown';
    const word = state === 'restricted' ? 'Activity requires Read access.' : state === 'unknown' ? 'No current status available.' : V2_WORD[state] || statusWord(state);
    // A status note may mention work outside this person's task visibility. Do not copy free-text focus into an overview.
    assign({id: 'bot:' + e.name, name: botDisplayName(e.name) + (e.shared_from || e.is_branch ? ' · Your branch' : ''), type: 'bot',
      state, focus: '', detail: word, href: readable || e.can_chat ? '#/bot/' + encodeURIComponent(e.name) : ''},
      e.team, isBuiltInBot(e.name) || isHelperBot(e));
  }
  if (shared.members.length) groups.push(shared);
  if (support.members.length) groups.push(support);
  return {company: companyName(), groups, fresh: !!fresh, demo: !!S.config.demo,
    theme: document.documentElement.dataset.theme || 'dark'};
}
function pageOverview() {
  const main = $('#main'); main.classList.add('overview-layout');
  main.innerHTML = `<section class="overview-page" aria-label="Company overview">
    <iframe id="overview-frame" class="overview-frame" title="Interactive building of your human and bot team" src="/tico/ui/overview/index.html" allow="fullscreen"></iframe>
  </section>`;
  const frame = $('#overview-frame');
  const state = OVERVIEW_PAGE = {frame, abort: new AbortController(), ready: false, model: overviewModel()};
  window.addEventListener('message', ev => {
    if (OVERVIEW_PAGE !== state || ev.source !== frame.contentWindow || ev.origin !== location.origin) return;
    if (ev.data?.type === 'tico-overview-ready') { state.ready = true; overviewRefresh(); }
    if (ev.data?.type === 'tico-overview-open') {
      const person = overviewModel().groups.flatMap(g => g.members).find(m => m.id === ev.data.id);
      if (person?.href) location.hash = person.href;
    }
  }, {signal: state.abort.signal});
  state.theme = new MutationObserver(() => overviewRefresh());
  state.theme.observe(document.documentElement, {attributes: true, attributeFilter: ['data-theme']});
  overviewRefresh();
}
function overviewRefresh() {
  const state = OVERVIEW_PAGE; if (!state) return;
  state.model = overviewModel();
  if (state.ready) state.frame.contentWindow?.postMessage({type: 'tico-overview-data', model: state.model}, location.origin);
}
function overviewStop() {
  const state = OVERVIEW_PAGE; if (!state) return;
  state.frame.contentWindow?.postMessage({type: 'tico-overview-dispose'}, location.origin);
  state.abort.abort(); state.theme.disconnect(); state.frame.remove(); OVERVIEW_PAGE = null;
}
