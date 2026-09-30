/* First run, the team: what hurts and what the company uses, the starting point (a starter team, a full
   org chart, or just the built-ins), the editable team, and the screen after Create (docs/onboarding.md).
   The server does the choosing (GET/PUT /api/v2/onboarding answers `recommendations` and `full_chart`);
   this only shows it, lets a person change anything, and sends the result. Nothing is created until
   "Create my team". It shares the wizard's state (`ONB`) and the catalog cards' state (`catalogState`)
   with index.html. */
const FR_TEAMS = ['Leadership', 'Sales', 'Marketing', 'Support', 'Operations', 'Engineering'];   // backend/onboarding.py TEAMS
const FR_TEAM_OF = {basics: 'Leadership', sales: 'Sales', marketing: 'Marketing', support: 'Support',
                    operations: 'Operations', engineering: 'Engineering'};
const FR_TOOLS = [
  ['mail', 'Mail', 'Google Workspace or another inbox'], ['chat', 'Chat', 'Slack'], ['crm', 'CRM', 'HubSpot, Salesforce, a sheet'],
  ['github', 'GitHub', 'issues and pull requests'], ['meetings', 'Meetings importer', 'Fireflies, Zoom, Google Meet, Granola'],
  ['docs', 'Docs', 'Drive, Notion, a help site']];
const FR_TOOL_NAME = {web: 'Public web', mail: 'Mail', chat: 'Chat', crm: 'CRM', github: 'GitHub', meetings: 'Meetings importer',
                      docs: 'Docs', calendar: 'Calendar'};
// Where each ticked tool is connected: shown on the screen after Create, once.
const FR_TOOL_LINK = {mail: ['Mail', '#/integrations'], chat: ['Slack', 'settings:cloud'], crm: ['CRM', '#/integrations'],
                      github: ['GitHub', 'settings:cloud'], meetings: ['Meeting importers', 'settings:cloud'], docs: ['Docs', '#/docs']};
const frBlankTeam = () => ({mode: null, edited: false, order: [], defaults: {}, leads: new Set(), advice: ''});
const frOwner = () => (S.me?.id ? 'human:' + S.me.id : '');
const frHome = state => state.record.home || frOwner();
const frPeople = () => (SETTINGS_DATA.people?.length ? SETTINGS_DATA.people : (S.me?.id ? [{id: S.me.id, name: S.me.name}] : []));
const frPersonName = id => frPeople().find(p => p.id === id)?.name || id;
// The bot a card is created as: the assistant's card is named `coo` but the company's own bot is `assistantBot()`.
const frBotSlug = card => (card.template === 'assistant' ? assistantBot() : card.slug);
const frTeamOf = card => FR_TEAM_OF[card.pack] || 'Other';
const frSentence = text => { const first = String(text || '').split(/(?<=[.!?])\s/)[0]; return first.length > 190 ? first.slice(0, 189) + '…' : first; };

// ----------------------------------------------------------------- what hurts, and what the company uses
function frHave(answers) {
  const have = new Set(['hub', 'web', 'calendar', ...(answers.tools || [])]);
  const implied = {email: 'mail', slack: 'chat', crm: 'crm', tickets: 'mail'};
  for (const value of answers.work_arrives || []) { const tool = implied[String(value).replace(/^uses_/, '')]; if (tool) have.add(tool); }
  return have;
}
function frNeedsHTML(state, actions) {
  const a = state.record.answers, options = state.record.pain_options || [];
  const ticked = new Set(a.pains || []);
  // The server marks about a dozen pains as `featured`, two per team. Every card's pains still match what is said;
  // a pain ticked earlier (a returning draft) stays on the screen under its team.
  const shown = options.filter(option => option.featured || ticked.has(option.text));
  const chip = option => `<label class="onb-chip"><input type="checkbox" data-onb-pain value="${esc(option.text)}" ${ticked.has(option.text) ? 'checked' : ''}><span>${esc(option.text)}</span></label>`;
  const groups = [...FR_TEAMS, 'Other'].map(team => {
    const rows = shown.filter(option => (option.team || 'Other') === team);
    return rows.length ? `<div class="onb-pain-group" data-pain-team="${esc(team)}"><span class="onb-pain-team">${esc(team)}</span>
        <div class="onb-chips">${rows.map(chip).join('')}</div></div>` : '';
  }).join('');
  return `<div class="onb-field"><span class="k">What hurts most right now?</span>
      <div class="onb-pain-groups" id="onb-pains" role="group" aria-label="What hurts most">${groups}</div></div>
    <label class="onb-field"><span class="k">In your own words</span>
      <textarea id="onb-pains-text" maxlength="1000" placeholder="Support mail piles up over the weekend and nobody owns the follow-ups.">${esc(a.pains_text)}</textarea></label>
    <div class="onb-field"><span class="k">What do you already use?</span>
      <div class="onb-choices" id="onb-tools">${FR_TOOLS.map(([value, label, hint]) =>
        `<label title="${esc(hint)}"><input type="checkbox" data-onb-tool value="${value}" ${(a.tools || []).includes(value) ? 'checked' : ''}>${esc(label)}</label>`).join('')}</div></div>
    ${actions('Next')}`;
}
function frCollect(state, key) {
  const r = state.record;
  if (key === 'needs' && $('#onb-pains-text')) r.answers = {...r.answers,
    pains: [...document.querySelectorAll('[data-onb-pain]:checked')].map(input => input.value).slice(0, 8),
    pains_text: $('#onb-pains-text').value.trim(),
    tools: [...document.querySelectorAll('[data-onb-tool]:checked')].map(input => input.value)};
  if (key === 'team' && state.catalog.cards.length) r.selected = frSelection(state);
}

// ----------------------------------------------------------------- the team
function frEnterTeam(state) {
  const advice = JSON.stringify([state.record.recommendations, state.record.full_chart]);
  if (state.team.mode === null) {
    // A returning draft keeps its picks; a first visit starts from the starter team.
    if (Object.keys(state.record.selected || {}).some(slug => !catalogCard(state.catalog, slug)?.required)) {
      state.team = {...state.team, mode: 'custom', edited: true, advice};
    } else frApplyMode(state, 'starter');
  } else if (!state.team.edited && state.team.advice !== advice && ['starter', 'full'].includes(state.team.mode)) {
    frApplyMode(state, state.team.mode);         // the answers changed and nothing was edited: the advice follows them
  }
  state.team.advice = advice;
}
function frApplyMode(state, mode) {
  const cat = state.catalog, r = state.record, home = frHome(state);
  cat.picked = new Set(cat.cards.filter(card => card.required).map(card => card.slug));
  cat.decided = new Set();
  for (const edit of Object.values(cat.edits)) delete edit.reports_to;
  state.team = {mode, edited: false, order: [], defaults: {}, leads: new Set(),
                advice: JSON.stringify([r.recommendations, r.full_chart])};
  const chart = {};
  for (const team of r.full_chart?.teams || []) for (const m of team.members) chart[m.slug] = {...m, team: team.team};
  const add = (slug, reportsTo, lead) => {
    const card = catalogCard(cat, slug);
    if (!card || card.required) return;
    cat.picked.add(slug);
    if (!state.team.order.includes(slug)) state.team.order.push(slug);
    state.team.defaults[slug] = reportsTo || home;
    if (lead) state.team.leads.add(slug);
  };
  if (mode === 'starter') for (const rec of r.recommendations || []) add(rec.slug, home, false);
  if (mode === 'full') {
    // The best pain matches are set up first, whatever team they sit in.
    for (const rec of r.recommendations || []) add(rec.slug, chart[rec.slug]?.reports_to, !!chart[rec.slug]?.lead);
    for (const team of r.full_chart?.teams || []) for (const m of team.members) add(m.slug, m.reports_to, m.lead);
  }
}
// What a bot reports to: what the person chose, else the starting point's own answer, else the owner.
function frReports(state, slug) {
  const edit = state.catalog.edits[slug]?.reports_to;
  const wanted = edit ?? state.team.defaults[slug] ?? frHome(state);
  // A parent that was removed leaves its team to the owner rather than a bot that will not exist.
  return frParentOptions(state, slug).some(option => option.value === wanted) ? wanted : frHome(state);
}
function frDescends(state, slug, of) {
  const seen = new Set();
  for (let at = slug; at && !seen.has(at); at = frRawReports(state, at)) { if (at === of) return true; seen.add(at); }
  return false;
}
const frRawReports = (state, slug) => state.catalog.edits[slug]?.reports_to ?? state.team.defaults[slug] ?? '';
function frParentOptions(state, slug) {
  const cat = state.catalog, out = [];
  const owner = frOwner();
  for (const person of frPeople()) out.push({value: 'human:' + person.id, label: (person.name || person.id) + (('human:' + person.id) === owner ? ' (you)' : ''), group: 'People'});
  for (const card of cat.cards) {
    const bot = frBotSlug(card);
    if (card.required && cat.picked.has(card.slug)) out.push({value: bot, label: catalogName(cat, card), group: 'Built in'});
    else if (!card.required && cat.picked.has(card.slug) && card.slug !== slug && !frDescends(state, card.slug, slug))
      out.push({value: card.slug, label: catalogName(cat, card), group: 'Bots on your team'});
  }
  return out;
}
function frSelection(state) {
  const cat = state.catalog, rank = card => { const i = state.team.order.indexOf(card.slug); return i < 0 ? 999 : i; };
  const cards = cat.cards.slice().sort((a, b) => (a.required === b.required ? 0 : a.required ? -1 : 1) || rank(a) - rank(b));
  const out = {};
  for (const card of cards) {
    if (!cat.picked.has(card.slug)) continue;
    out[card.slug] = {template: card.template, display_name: catalogName(cat, card), instructions: catalogInstructions(cat, card),
                      ...(card.required ? {} : {reports_to: frReports(state, card.slug)})};
  }
  return out;
}
// Two bots that report to each other would be refused at Create; say so on the screen instead.
function frProblem(state) {
  const cat = state.catalog;
  for (const card of cat.cards) {
    if (card.required || !cat.picked.has(card.slug)) continue;
    const seen = new Set([card.slug]);
    for (let at = frReports(state, card.slug); at && !at.startsWith('human:'); at = frReports(state, at)) {
      if (seen.has(at)) return `${catalogName(cat, card)} and ${catalogName(cat, catalogCard(cat, at) || card)} report to each other. Point one of them at a person.`;
      seen.add(at);
      if (!catalogCard(cat, at) || catalogCard(cat, at).required) break;
    }
  }
  return catalogMissingMailbox(cat) ? 'Choose whose mailbox Mail Drafts reads.' : '';
}
function frPrereqHTML(state, card) {
  const have = frHave(state.record.answers);
  const rows = (card.prerequisites || []).filter(row => row.tool !== 'hub');
  if (!rows.length) return '';
  return `<span class="team-prereq" data-team-prereq="${esc(card.slug)}">${rows.map(row => {
    const name = FR_TOOL_NAME[row.tool] || row.tool, met = have.has(row.tool);
    return row.required
      ? `<span class="pill ${met ? 'ok' : 'waiting'}" title="${esc(row.why)}">${met ? '' : 'Needs '}${esc(name)}</span>`
      : `<span class="pill" title="${esc(row.why)}">${esc(name)}, optional</span>`;
  }).join('')}</span>`;
}
function frWhy(state, card) {
  const r = state.record, rec = (r.recommendations || []).find(row => row.slug === card.slug);
  if (rec) return rec.why;
  for (const team of r.full_chart?.teams || []) { const m = team.members.find(row => row.slug === card.slug); if (m) return m.why; }
  return frSentence(card.summary);
}
function frRowHTML(state, card) {
  const cat = state.catalog, slug = card.slug;
  const options = frParentOptions(state, slug), current = frReports(state, slug);
  const groups = ['People', 'Built in', 'Bots on your team'].map(group => {
    const rows = options.filter(option => option.group === group);
    return rows.length ? `<optgroup label="${esc(group)}">${rows.map(option =>
      `<option value="${esc(option.value)}" ${option.value === current ? 'selected' : ''}>${esc(option.label)}</option>`).join('')}</optgroup>` : '';
  }).join('');
  const people = card.template === 'inbox' ? catalogPeople() : [], chosen = cat.edits[slug]?.person || '';
  const mailbox = people.length ? `<label class="cat-mailbox">Whose mailbox
      <select data-cat-mailbox="${esc(slug)}" aria-label="Person whose inbox this bot reads">
        <option value="">Choose a person…</option>
        ${people.map(person => `<option value="${esc(person.id)}" ${person.id === chosen ? 'selected' : ''}>${esc(person.name || person.id)}${person.email ? ` · ${esc(person.email)}` : ''}</option>`).join('')}
      </select></label>` : '';
  return `<article class="team-bot" data-team-bot="${esc(slug)}">
    <div class="team-bot-main">
      <div class="team-bot-name"><input type="text" class="cat-name" data-cat-name="${esc(slug)}" value="${esc(catalogName(cat, card))}" maxlength="100" aria-label="Name for ${esc(card.name || slug)}">
        ${state.team.leads.has(slug) ? '<span class="pill ok" title="Leads its team">Lead</span>' : ''}</div>
      <p class="team-why" data-team-why="${esc(slug)}">${esc(frWhy(state, card))}</p>
      ${frPrereqHTML(state, card)}
      ${card.first_routine?.title ? `<p class="team-routine muted">First routine: ${esc(card.first_routine.title)}</p>` : ''}
      ${mailbox}
    </div>
    <div class="team-bot-side">
      <label class="team-reports">Reports to <select data-team-reports="${esc(slug)}" aria-label="${esc(catalogName(cat, card))} reports to">${groups}</select></label>
      <button class="ghost" type="button" data-team-remove="${esc(slug)}" aria-label="Remove ${esc(catalogName(cat, card))}">Remove</button>
    </div></article>`;
}
function frListHTML(state) {
  const cat = state.catalog;
  const picked = cat.cards.filter(card => !card.required && cat.picked.has(card.slug));
  const order = card => { const i = state.team.order.indexOf(card.slug); return i < 0 ? 999 : i; };
  const groups = [...FR_TEAMS, 'Other'].map(team => {
    const rows = picked.filter(card => frTeamOf(card) === team).sort((a, b) => order(a) - order(b));
    if (!rows.length) return '';
    const lead = rows.find(card => state.team.leads.has(card.slug));
    return `<section class="team-group" data-team-group="${esc(team)}"><h3>${esc(team)}${lead ? `<span class="muted"> · led by ${esc(catalogName(cat, lead))}</span>` : ''}</h3>
      ${rows.map(card => frRowHTML(state, card)).join('')}</section>`;
  }).join('');
  return groups || '<div class="empty" data-team-empty>No bots on your team yet.</div>';
}
function frAddHTML(state) {
  const cat = state.catalog, held = state.record.held_back || [];
  const rows = cat.cards.filter(card => !card.required && !cat.picked.has(card.slug));
  const have = frHave(state.record.answers);
  const item = card => {
    const missing = (card.prerequisites || []).filter(row => row.required && !have.has(row.tool));
    return `<div class="team-add-row" data-team-add-row="${esc(card.slug)}"><div><strong>${esc(catalogName(cat, card))}</strong>
        <p class="muted">${esc(frSentence(card.summary))}</p>${frPrereqHTML(state, card)}
        ${missing.length ? `<p class="muted" data-team-needs>Needs ${esc(missing.map(row => FR_TOOL_NAME[row.tool] || row.tool).join(' and '))}, which you did not tick.</p>` : ''}</div>
      <button class="ghost" type="button" data-team-add="${esc(card.slug)}" aria-label="Add ${esc(catalogName(cat, card))}">Add</button></div>`;
  };
  return `<details class="team-add" id="team-add"${state.team.addOpen ? ' open' : ''}><summary>Add a bot${rows.length ? ` <span class="muted">(${rows.length} more in the catalog)</span>` : ''}</summary>
    ${held.length ? `<ul class="team-held">${held.map(row => `<li class="muted" data-team-held="${esc(row.template)}">${esc(row.why)}</li>`).join('')}</ul>` : ''}
    ${rows.length ? rows.map(item).join('') : '<p class="muted">Everything in the catalog is already on your team.</p>'}</details>`;
}
function frTeamHTML(state, actions) {
  const r = state.record, starter = r.recommendations || [], teams = r.full_chart?.teams || [];
  const full = teams.reduce((n, team) => n + team.members.length, 0), mode = state.team.mode;
  const option = (value, title, text) => `<label class="team-start-opt${mode === value ? ' on' : ''}" data-team-start="${value}">
      <input type="radio" name="onb-start" value="${value}" ${mode === value ? 'checked' : ''}><span><strong>${esc(title)}</strong><small>${esc(text)}</small></span></label>`;
  return `<div class="team-start" role="radiogroup" aria-label="Starting point">
      ${option('starter', 'Starter team', `${starter.length} bot${starter.length === 1 ? '' : 's'}`)}
      ${option('full', 'Full org chart', `${full} bot${full === 1 ? '' : 's'} in ${teams.length} team${teams.length === 1 ? '' : 's'}`)}
      ${option('empty', 'Just the built-ins', 'Add bots as you go')}
    </div>
    <p class="team-builtin muted" data-team-builtin>Built in: ${esc(state.catalog.cards.filter(card => card.required).map(card => catalogName(state.catalog, card)).join(', ') || 'BotOps')}</p>
    <div id="team-list">${frListHTML(state)}</div>
    <div id="team-add-host">${frAddHTML(state)}</div>
    <p class="err" id="team-problem" role="alert" hidden></p>
    ${actions('Next')}`;
}
function frRefresh(state) {
  $('#team-list').innerHTML = frListHTML(state);
  $('#team-add-host').innerHTML = frAddHTML(state);
  const problem = frProblem(state), box = $('#team-problem');
  if (box) { box.textContent = state.team.showProblem ? problem : ''; box.hidden = !(state.team.showProblem && problem); }
}
function frTeamWire(state) {
  const host = $('#onb-step');
  const edited = () => { state.team.edited = true; state.team.mode = state.team.mode === 'empty' ? 'custom' : state.team.mode; };
  catalogWire($('#team-list'), state.catalog, () => { edited(); });     // names and the inbox's mailbox
  host.querySelectorAll('[data-team-start] input').forEach(input => input.onchange = () => {
    frApplyMode(state, input.value);
    state.team.showProblem = false;
    onbRender(state);
  });
  host.onclick = event => {
    const remove = event.target.closest('[data-team-remove]'), add = event.target.closest('[data-team-add]');
    if (!remove && !add) return;
    const slug = (remove || add).dataset.teamRemove || (remove || add).dataset.teamAdd, cat = state.catalog;
    if (remove) cat.picked.delete(slug); else { cat.picked.add(slug); if (!state.team.order.includes(slug)) state.team.order.push(slug); state.team.addOpen = true; }
    cat.decided.add(slug); edited();
    frRefresh(state);
  };
  host.onchange = event => {
    const reports = event.target.closest('[data-team-reports]');
    if (!reports) return;
    (state.catalog.edits[reports.dataset.teamReports] ||= {}).reports_to = reports.value;
    edited(); state.team.showProblem = true; frRefresh(state);
  };
  host.addEventListener('toggle', event => { if (event.target.id === 'team-add') state.team.addOpen = event.target.open; }, true);
}
// The advance from the team step: a cycle or a missing mailbox is said here, not after Create.
function frCanAdvance(state) {
  const problem = frProblem(state);
  if (!problem) return true;
  state.team.showProblem = true; frRefresh(state);
  return false;
}

// ----------------------------------------------------------------- review
function frSummaryTeamHTML(state) {
  const cat = state.catalog;
  const rows = cat.cards.filter(card => !card.required && cat.picked.has(card.slug));
  const nameOf = value => value.startsWith('human:') ? frPersonName(value.slice(6))
    : (catalogName(cat, cat.cards.find(card => frBotSlug(card) === value || card.slug === value) || {slug: value, name: value}));
  const built = cat.cards.filter(card => card.required).map(card => esc(catalogName(cat, card))).join(', ');
  return `<div><span class="k">Built in</span><span>${built || '—'}</span></div>
    <div><span class="k">Your team</span><span data-review-team>${rows.length ? rows.map(card =>
      `${esc(catalogName(cat, card))} <span class="muted">→ ${esc(nameOf(frReports(state, card.slug)))}</span>`).join('<br>') : 'Just the built-ins'}</span></div>`;
}

// ----------------------------------------------------------------- after Create
// One screen: each bot's setup, an admin to invite, an owner for each bot, and where tools are connected.
function frBotRowHTML(state, bot, botOps) {
  const card = state.catalog.cards.find(row => row.slug === bot.slug || row.template === bot.template);
  const bootstrap = bot.slug === assistantBot() || !!card?.bootstrap;
  const ready = !!bot.repository_present, active = bot.status === 'active', parked = bot.onboarding_state === 'needs_onboarding';
  const where = bootstrap ? 'Set up automatically once a computer is online.'
    : parked ? (ready ? 'Repository ready.' : 'Setting up its repository…')
    : `${esc(botOps)} is setting this up.`;
  return `<div class="onb-bot" data-onb-bot="${esc(bot.slug)}">${avatar(bot.slug, 27)}
      <div class="onb-bot-main"><strong>${esc(bot.display_name || bot.slug)}</strong>${parked ? ' <span class="pill needs" data-needs-onboarding>Needs onboarding</span>' : ''}
        <p>${where}</p>
        ${!bootstrap && !parked && bot.setup_task_id ? `<p><a href="#/task/${esc(bot.setup_task_id)}" data-onb-task="${esc(bot.slug)}">Open the setup task</a></p>` : ''}</div>
      <div class="onb-bot-actions"><span class="pill ${active ? 'ok' : ready ? 'ready' : 'waiting'}">${esc(parked && !ready ? 'setting up' : active ? 'active' : ready ? 'repository ready' : 'waiting')}</span>
        ${parked ? `<button class="primary" type="button" data-fr-start="${esc(bot.slug)}" ${ready ? '' : 'disabled title="Its repository is not ready yet"'}>Start setup</button>`
          : ready && !active && !bootstrap ? `<button class="ghost" type="button" data-onb-activate="${esc(bot.slug)}">Activate</button>` : ''}</div></div>`;
}
function frNextHTML(state) {
  const bots = (state.record.bots || []).filter(bot => bot.slug !== assistantBot() && bot.slug !== 'botops' && bot.slug !== 'librarian' && bot.slug !== 'goal-manager');
  const tools = (state.record.answers.tools || []).filter(tool => FR_TOOL_LINK[tool]);
  const owners = bots.map(bot => `<div class="fr-owner" data-fr-owner-row="${esc(bot.slug)}"><span>${esc(bot.display_name || bot.slug)}</span>
      <select data-fr-owner="${esc(bot.slug)}" aria-label="Add an owner for ${esc(bot.display_name || bot.slug)}"><option value="">Add an owner…</option>${frPeople().map(person =>
        `<option value="${esc(person.id)}">${esc(person.name || person.id)}${('human:' + person.id) === frOwner() ? ' (you)' : ''}</option>`).join('')}</select>
      <span class="muted" data-fr-owned="${esc(bot.slug)}">${esc(frPersonName(S.me?.id))} owns it</span></div>`).join('');
  return `<section class="card fr-card" id="fr-admin"><header><h2>Invite an admin</h2></header>
      <form id="fr-admin-form" class="fr-form"><label class="onb-field"><span class="k">Name</span><input name="name" autocomplete="off" placeholder="Sam Ortiz"></label>
        <label class="onb-field"><span class="k">Email</span><input name="email" type="email" autocomplete="off" required placeholder="sam@company.com"></label>
        <div class="onb-actions"><button class="primary" type="submit">Invite as admin</button><span class="muted" id="fr-admin-status" role="status"></span></div></form>
      <small class="muted">Tico sends no email: tell them.</small></section>
    <section class="card fr-card" id="fr-owners"><header><h2>Who owns each bot</h2></header>
      ${owners || '<p class="muted">No bots yet.</p>'}</section>
    <section class="card fr-card" id="fr-tools"><header><h2>Connect your tools</h2></header>
      <ul class="fr-tools">${tools.map(tool => `<li>${esc(FR_TOOL_LINK[tool][0])} <a href="${esc(FR_TOOL_LINK[tool][1])}" data-fr-link="${esc(tool)}">Open</a></li>`).join('')}
        <li>Keys and tokens <a href="#/credentials" data-fr-link="credentials">Credentials</a></li>
        <li>Everything else <a href="#/integrations" data-fr-link="integrations">Integrations</a></li></ul>
      <p class="fr-secrets" data-fr-secrets><strong>Enter secrets in those fields, never in a chat with a bot.</strong> One pasted into a chat is leaked: rotate it.</p></section>`;
}
function frWireDone(state) {
  document.querySelectorAll('[data-fr-start]').forEach(button => button.onclick = () => void frStartSetup(button.dataset.frStart, button));
}
async function frStartSetup(slug, button) {
  if (button) button.disabled = true;
  try {
    await frSendSetup(slug);
    location.hash = '#/bot/' + encodeURIComponent(slug);
  } catch (error) { toast(error.message, true); if (button) button.disabled = false; }
}
// Start setup: activate the bot when it is only planned (a starter runs nothing on its own), then say the one line that
// begins its onboarding conversation. Any first message from a person does the same.
async function frSendSetup(slug) {
  const bots = await v2Get('/v2/bots?include_archived=1');
  const bot = (bots || []).find(row => row.slug === slug);
  if (bot && bot.state === 'planned') await post(`/v2/bots/${encodeURIComponent(slug)}/definition`, {status: 'active', expected_revision: bot.revision});
  await post(`/v2/chat/${encodeURIComponent(slug)}`, {text: "Let's set you up."});
  await refresh(true);
}
function frWireNext(state) {
  const form = $('#fr-admin-form');
  if (form) form.onsubmit = async event => {
    event.preventDefault();
    const status = $('#fr-admin-status'), data = Object.fromEntries(new FormData(form));
    form.querySelector('button').disabled = true; status.textContent = 'Inviting…';
    try {
      const added = await post('/v2/access/people', {name: data.name || '', email: data.email});
      // Adding is the roster and the sign-in list; the role is a second, owner-only step.
      await post('/v2/access/people/' + encodeURIComponent(added.person), {role: 'admin'});
      status.textContent = `${added.name || data.email} is on the roster as an admin.`;
      form.reset();
      const roster = await get('/people').catch(() => null);
      if (roster?.people) { SETTINGS_DATA.people = roster.people; setPeople(roster); }
    } catch (error) { status.innerHTML = `<span class="err">${esc(error.message)}</span>`; }
    form.querySelector('button').disabled = false;
  };
  document.querySelectorAll('[data-fr-owner]').forEach(select => select.onchange = async () => {
    const slug = select.dataset.frOwner, person = select.value;
    if (!person) return;
    const note = document.querySelector(`[data-fr-owned="${cssSelectorValue(slug)}"]`);
    select.disabled = true;
    try {
      const done = await post(`/v2/bots/${encodeURIComponent(slug)}/co-owners`, {add: [person], remove: []});
      if (note) note.textContent = (done.bot_owners || []).map(o => o.name || o.id).join(', ') + ' own it';
    } catch (error) { if (note) note.innerHTML = `<span class="err">${esc(error.message)}</span>`; }
    select.value = ''; select.disabled = false;
  });
  document.querySelectorAll('[data-fr-link]').forEach(link => link.onclick = event => {
    const href = link.getAttribute('href');
    if (!href.startsWith('settings:')) return;
    event.preventDefault();
    SETTINGS_TAB = href.slice(9); location.hash = SETTINGS;
  });
}

// ----------------------------------------------------------------- the bot page and the org chart
const frNeedsSetup = e => !!e && e.onboarding_state === 'needs_onboarding';
// The org chart's mark: small, beside the name, and the same word as the bot page.
const frTreeMark = e => (frNeedsSetup(e) ? '<span class="tree-setup" title="Needs onboarding: set it up together before it does anything on its own">Setup</span>' : '');
function frBotBannerHTML(e) {
  if (!frNeedsSetup(e)) return '';
  const manager = typeof settingsCanManageBot === 'function' && settingsCanManageBot(e);
  const planned = e.status === 'planned';
  const can = e.can_chat && (!planned || manager);
  return `<section class="bot-onboard" id="bot-onboard" role="status" aria-label="Needs onboarding">
      <span class="pill needs">Needs onboarding</span>
      <p>${esc(e.display_name || e.name)} does nothing on its own until you have set it up together. It asks a few questions, drafts a first result and
        proposes its first routine, which stays off until you say yes. Sending it any message starts the same conversation.</p>
      ${can ? '<button class="primary" type="button" id="bot-start-setup">Start setup</button>'
        : `<span class="muted">${planned ? 'Waiting for an owner to place it on a computer and activate it.' : 'Ask someone who can write to it to start.'}</span>`}
    </section>`;
}
function frBotWire(slug) {
  const button = $('#bot-start-setup');
  if (button) button.onclick = async () => {
    button.disabled = true; button.textContent = 'Starting…';
    try { await frSendSetup(slug); button.textContent = 'Setup started'; showBotTab('chat'); }
    catch (error) { toast(error.message, true); button.disabled = false; button.textContent = 'Start setup'; }
  };
}
// The page follows the bot's state: the mark clears when it says a person approved its first routine.
function frBotRefresh(slug) {
  const e = S.emps.find(x => x.name === slug), host = $('#bot-onboard-host');
  if (host) { host.innerHTML = frBotBannerHTML(e); frBotWire(slug); }
}
