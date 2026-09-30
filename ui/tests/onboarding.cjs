// Offline browser regression for the first-run wizard: a company whose config
// says onboarding_needed lands on #/welcome instead of Tasks and keeps a "Finish setup" entry; the
// seven steps save a draft with PUT /api/v2/onboarding on every Next (there is no assistant to name, and an
// optional "Connect your agent" step opens connectAgent()). The company answers what hurts and what it uses;
// the server proposes a starter team or a full org chart, each editable (names, reports-to, add, remove) with
// nothing created until "Create my team", which posts /api/v2/onboarding/complete exactly once. After it: each
// starter shows "Needs onboarding" with a Start setup button that says "Let's set you up.", an admin can be
// invited, bot owners named and tools' places found; the bot page and the org chart carry the same mark.
// Settings -> Bots reuses the catalog cards. Fixtures only - no server, no network.
const {chromium} = require('playwright');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const html = fs.readFileSync(path.join(__dirname, '../index.html'), 'utf8');
// TICO_SCREENSHOT_DIR=<dir> saves screenshots of the first-run screens.
// TICO_SHOT_SCHEME=dark takes them in the dark theme.
const shots = process.env.TICO_SCREENSHOT_DIR, scheme = process.env.TICO_SHOT_SCHEME === 'dark' ? 'dark' : 'light';
const shot = (page, name) => (shots ? page.screenshot({path: path.join(shots, `${name}-${scheme}.png`)}) : null);

const CONFIG = {environment_id: 'initech', company_name: 'Initech', app_name: 'Initech Hub',
  assistant_name: 'Ace', assistant_bot: 'coo', public_url: 'https://initech.test',
  runner_url: 'https://initech.test', github_owner: 'initech-inc', local: false, release: '',
  onboarding_needed: true, version: '0.2.0', runner_compat: {version: '0.2.0', min_runner: '0.1.0'}};

const CATALOG = [
  // The server renders every card with the company's names, so the assistant's reads as Ace.
  {template: 'assistant', slug: 'coo', name: 'Ace', required: true, default: true, bootstrap: true,
   when: 'Recommended if you use Slack or send meetings to bots: it routes work nobody was named for.',
   summary: 'Your point of contact. Answers from what the other bots wrote down.',
   owns: ['the chat thread', 'routing questions'], never: ['sends mail on its own'],
   runtime: 'codex', model: 'gpt-6-sol', reasoning_effort: 'xhigh', recommend_when: [],
   instructions: '# Assistant\n\nYou are the point of contact for Initech.\n'},
  {template: 'botops', slug: 'botops', name: 'BotOps', required: true, bootstrap: true,
   summary: 'Builds and repairs the other bots.',
   owns: ['bot repositories', 'setup tasks'], never: ['spends money'],
   runtime: 'codex', model: 'gpt-6-sol', reasoning_effort: 'high', recommend_when: [],
   instructions: '# BotOps\n\nYou set up every other bot.\n'},
  {template: 'chief-of-staff', slug: 'chief-of-staff', name: 'Chief of Staff', required: false, bootstrap: false, starter: true,
   pack: 'basics', pains: ['goals stall and nobody notices'], prerequisites: [{tool: 'hub', why: 'Goals and tasks.', required: true}],
   first_routine: {title: 'Weekly company brief', cadence: 'Fridays at 15:00'},
   summary: 'Turns goals, tasks and updates into a weekly brief. Internal only.',
   owns: ['the weekly brief'], never: ['messages anyone outside the company'],
   runtime: 'codex', model: 'gpt-6-sol', reasoning_effort: 'medium', recommend_when: ['always'],
   instructions: '# Chief of Staff\n\nBrief the owner weekly.\n'},
  {template: 'support', slug: 'support', name: 'Support', required: false, bootstrap: false, starter: true, pack: 'support',
   pains: ['support inbox is overflowing', 'customers wait too long for an answer'],
   prerequisites: [{tool: 'mail', why: 'Support mail is the intake.', required: true}, {tool: 'docs', why: 'The help centre.', required: false}],
   first_routine: {title: 'Daily support triage', cadence: 'Weekdays at 09:00'},
   summary: 'Answers customers and keeps the queue short.',
   owns: ['the ticket queue'], never: ['refunds without a person'],
   runtime: 'codex', model: 'gpt-6-sol', reasoning_effort: 'high',
   recommend_when: ['has_support_inbox', 'uses_tickets', 'sells_to_consumers', 'uses_email'],
   instructions: '# Support\n\nAnswer the queue in the company voice.\n'},
  {template: 'social', slug: 'social', name: 'Social', required: false, bootstrap: false, pack: 'marketing',
   summary: 'Drafts posts and watches mentions.',
   owns: ['the posting calendar'], never: ['publishes without a person'],
   runtime: 'codex', model: 'gpt-6-sol', reasoning_effort: 'medium', recommend_when: ['uses_slack'],
   instructions: '# Social\n\nDraft, never publish.\n'},
  {template: 'bookkeeper', slug: 'bookkeeper', name: 'Bookkeeper', required: false, bootstrap: false, pack: 'operations',
   summary: 'Chases invoices and reconciles the ledger.',
   owns: ['the invoice ledger'], never: ['pays anything without a person'],
   runtime: 'codex', model: 'gpt-6-sol', reasoning_effort: 'high', recommend_when: ['sells_to_businesses', 'has_pipeline'],
   instructions: '# Bookkeeper\n\nChase, never pay.\n'},
  {template: 'inbox', slug: 'inbox', name: 'Inbox', required: false, bootstrap: false, starter: true, pack: 'basics',
   pains: ['too much email'], prerequisites: [{tool: 'mail', why: 'A mailbox to read.', required: true}],
   first_routine: {title: 'Morning mail brief', cadence: 'Weekdays at 07:30'},
   summary: 'Reads one person mailbox on a cadence.',
   owns: ['the inbox pass'], never: ['sends mail on its own'],
   runtime: 'codex', model: 'gpt-6-sol', reasoning_effort: 'medium', recommend_when: ['has_personal_inbox'],
   instructions: '# Inbox\n\nRead, never send.\n'},
];

// What Create leaves: the two starters are parked, one with its repository, one still being set up; Social is
// not a starter, so BotOps builds it.
const BOTS_AFTER = [
  {slug: 'coo', display_name: 'Ace', status: 'active', template: 'assistant', onboarding_state: '',
   setup_task_id: null, repository_present: false},
  {slug: 'botops', display_name: 'BotOps', status: 'active', template: 'botops', onboarding_state: '',
   setup_task_id: null, repository_present: true},
  {slug: 'support', display_name: 'Support desk', status: 'active', template: 'support', onboarding_state: 'needs_onboarding',
   setup_task_id: null, repository_present: true},
  {slug: 'chief-of-staff', display_name: 'Chief of Staff', status: 'planned', template: 'chief-of-staff', onboarding_state: 'needs_onboarding',
   setup_task_id: null, repository_present: false},
  {slug: 'social', display_name: 'Social', status: 'planned', template: 'social', onboarding_state: '',
   setup_task_id: 'task-social', repository_present: false},
];
// What the server proposes from the answers (backend/onboarding.py `choose` and `full_chart`, tested there).
const PAINS = [{text: 'I don\'t know what is really going on across the company', template: 'chief-of-staff', team: 'Leadership', featured: true},
               {text: 'goals stall and nobody notices', template: 'chief-of-staff', team: 'Leadership', featured: false},
               {text: 'too much email', template: 'inbox', team: 'Leadership', featured: true},
               {text: 'support inbox is overflowing', template: 'support', team: 'Support', featured: true},
               {text: 'customers wait too long for an answer', template: 'support', team: 'Support', featured: true},
               {text: 'we answer the same questions again and again', template: 'support', team: 'Support', featured: false}];
const rec = (slug, why, pain = '') => {
  const card = CATALOG.find(row => row.slug === slug);
  return {template: card.template, slug, name: card.name, why, matched_pain: pain,
          prerequisites: (card.prerequisites || []).map(row => ({...row, met: row.tool === 'hub'}))};
};
const advice = answers => {
  const said = (answers?.pains || []).includes('support inbox is overflowing');
  const ticked = new Set(answers?.tools || []);
  const support = rec('support', 'You said "support inbox is overflowing". Answers customers and keeps the queue short.', 'support inbox is overflowing');
  support.prerequisites = support.prerequisites.map(row => ({...row, met: ticked.has(row.tool)}));
  const recommendations = [...(said ? [support] : []), rec('chief-of-staff', 'Turns goals, tasks and updates into a weekly brief.')];
  const member = (slug, reports_to, lead) => ({...rec(slug, 'It fits how you described the company.'), lead, reports_to});
  return {recommendations, pain_options: PAINS, home: 'human:ana',
    held_back: ticked.has('meetings') ? [] : [{template: 'meeting-notes', name: 'Meeting Notes', needs: ['meetings'],
      why: 'It matches "meetings without follow-up" but it needs meetings, which you did not tick.'}],
    full_chart: {teams: [
      {team: 'Leadership', lead: 'chief-of-staff', members: [member('chief-of-staff', 'human:ana', true), member('inbox', 'chief-of-staff', false)]},
      {team: 'Marketing', lead: 'social', members: [member('social', 'human:ana', true)]},
      {team: 'Support', lead: 'support', members: [member('support', 'human:ana', true)]},
      {team: 'Operations', lead: 'bookkeeper', members: [member('bookkeeper', 'human:ana', true)]}], held_back: []}};
};

(async () => {
  const browser = await chromium.launch({headless: true, channel: process.env.TICO_BROWSER_CHANNEL === undefined ? 'chrome' : process.env.TICO_BROWSER_CHANNEL || undefined});
  try {
    const context = await browser.newContext({viewport: {width: 1100, height: 800}, serviceWorkers: 'block', acceptDownloads: true, colorScheme: scheme});
    const puts = [], tourPosts = [], completes = [], definitions = [], created = [], enrollments = [], chats = [], invites = [], owners = [];
    let record = {
      names: {company_name: 'Initech', app_name: 'Initech Hub', assistant_name: 'Ace'},
      answers: {what_we_do: '', customers: '', team_size: '', work_arrives: [], software_product: '',
                repetitive_work: '', never_without_person: ['send', 'spend', 'publish', 'hire'], pains: [], pains_text: '', tools: []},
      selected: {}, completed: null, bots: [],
      machine: {runners: [], enrolled: false}, needed: true,
    };
    let machine = {runners: [], enrolled: false};
    const me = {id: 'ana', name: 'Ana Rivera', role: 'owner', cloud: true,
                email: 'ana@acme.example', credential_access: false, config: CONFIG};
    const v2bots = () => BOTS_AFTER.map((bot, i) => ({slug: bot.slug, display_name: bot.display_name, state: bot.status,
      status: bot.status, revision: i + 1, team: null, operator: 'ana', repo: 'emp-' + bot.slug, onboarding_state: bot.onboarding_state}));

    await context.route('**/*', async route => {
      const request = route.request(), url = new URL(request.url()), p = url.pathname;
      const json = (body, status = 200) => route.fulfill({status, contentType: 'application/json', body: JSON.stringify(body)});
      if (p === '/') return route.fulfill({contentType: 'text/html', body: html});
      // The page's own modules come from disk: index.html shares state with them (docs-page.js
      // declares DOC_POLL, which route() clears on every navigation), so an empty stub would
      // break every route. Everything else that ends in .js still stubs out.
      const module = p.match(/\/tico\/ui\/([^/]+\.js)$/);
      if (module) {
        const file = path.join(__dirname, '..', module[1]);
        if (fs.existsSync(file)) return route.fulfill({contentType: 'application/javascript', body: fs.readFileSync(file, 'utf8')});
      }
      if (p === '/api/me') return json(me);
      if (p === '/api/v2/config') return json(CONFIG);
      if (p === '/api/status') return json({cloud: true, keeper_alive: true, health_issues: [], active: [], recent_runs: []});
      if (p === '/api/employees') return json([{name: 'coo', display_name: 'Tico', status: 'active',
        reports_to: '', description: 'the point of contact', revision: 1, users: [{id: 'ana', name: 'Ana Rivera', email: 'ana@acme.example'}]},
        // After Create the two starters are on the chart, parked.
        ...(record.completed ? BOTS_AFTER.filter(bot => bot.onboarding_state).map(bot => ({name: bot.slug, display_name: bot.display_name,
          status: bot.status, reports_to: '', description: '', revision: 5, can_chat: true, can_manage: true, onboarding_state: bot.onboarding_state,
          users: []})) : [])]);
      if (p === '/api/issues') return json([]);
      if (p === '/api/v2/catalog') return json({cards: CATALOG});
      if (p === '/api/v2/onboarding') {
        if (request.method() === 'PUT') {
          const body = request.postDataJSON();
          puts.push(body);
          record = {...record, ...body, machine};
          return json({...record, ...advice(record.answers)});
        }
        return json({...record, machine, ...advice(record.answers)});
      }
      if (p === '/api/v2/onboarding/complete') {
        completes.push(request.postDataJSON());
        record = {...record, completed: '2026-09-16T10:00:00Z', needed: false,
                  bots: BOTS_AFTER.map(bot => ({...bot})), machine};
        return json({...record, ...advice(record.answers)});
      }
      if (p === '/api/v2/getting-started/state') { tourPosts.push(request.postDataJSON()); return json({tour: true, checklist: false, cards: [], skipped: []}); }
      if (p === '/api/v2/enrollments') { enrollments.push(request.postDataJSON()); return json({code: 'enroll-code', expires: '2026-09-16T10:15:00Z'}); }
      if (p === '/api/v2/bots' && request.method() === 'POST') { created.push(request.postDataJSON()); return json({bot: {slug: request.postDataJSON().slug}}); }
      if (p === '/api/v2/bots') return json(v2bots());
      if (/^\/api\/v2\/chat\/[^/]+$/.test(p)) { chats.push([p.split('/')[4], request.postDataJSON()]); return json({message: {id: 'm1'}, conversation: {id: 'c1'}}); }
      if (p === '/api/v2/access/people') { invites.push(['add', request.postDataJSON()]); return json({person: 'sam', email: 'sam@initech.test', name: 'Sam Ortiz'}); }
      if (p === '/api/v2/access/people/sam') { invites.push(['role', request.postDataJSON()]); return json({person: 'sam'}); }
      if (/^\/api\/v2\/bots\/[^/]+\/co-owners$/.test(p)) { owners.push([p.split('/')[4], request.postDataJSON()]); return json({bot_owners: [{id: 'ana', name: 'Ana Rivera'}, {id: 'ben', name: 'Ben Cole'}], revision: 4}); }
      if (/^\/api\/v2\/bots\/[^/]+\/definition$/.test(p)) {
        definitions.push({path: p, body: request.postDataJSON()});
        return json({slug: p.split('/')[4], status: 'active', revision: 9});
      }
      if (p === '/api/v2/status') return json({bots: []});
      if (p === '/api/v2/needs-you') return json({items: []});
      if (/^\/api\/v2\/tasks\/[^/]+\/chat$/.test(p)) return json({recipient: {slug: 'botops', name: 'BotOps', can_chat: true}, messages: [], conversation: null});
      if (p === '/api/v2/tasks') return json({tasks: [{id: 'task-social', title: 'Set up Social',
        owner: 'bot:botops', status: 'in_progress', version: 1, updated: '2026-09-16T10:01:00Z',
        created: '2026-09-16T10:00:30Z', requester: 'human:ana',
        body: 'Create the repository and the first routine.'}]});
      if (p === '/api/people') return json({people: [{id: 'ana', name: 'Ana Rivera', email: 'ana@acme.example'}, {id: 'ben', name: 'Ben Cole', email: 'ben@acme.example'}]});
      if (p === '/api/v2/operations') return json({machines: [], services: [], issues: [], scheduler_enabled: true});
      if (p === '/api/v2/models') return json({models: [{id: 'gpt-6-sol', label: 'Sol', runtime: 'codex', efforts: ['high', 'xhigh'], default_effort: 'high'}]});
      if (p === '/api/v2/settings/history') return json({changes: [], transitions: []});
      if (p.endsWith('.js')) return route.fulfill({contentType: 'application/javascript', body: ''});
      if (p.endsWith('/watch')) return route.fulfill({contentType: 'text/event-stream', body: ': fixture\n\n'});
      return json({});
    });

    const page = await context.newPage();
    const errors = [];
    page.on('pageerror', e => errors.push(e.message));
    page.on('download', download => download.cancel().catch(() => {}));

    // ---- boot: a company that has never been set up opens on its first run, not on Tasks.
    await page.goto('https://tico-ui.test/');
    await page.waitForFunction(() => location.hash === '#/welcome');
    await page.locator('#onb-company').waitFor();
    assert.equal(await page.locator('#nav-welcome').evaluate(el => el.hidden), false);
    assert.match(await page.locator('#nav-welcome').textContent(), /Finish setup/);
    assert.equal(await page.locator('#onb-count').textContent(), 'Step 1 of 7');

    // ---- a: names, prefilled from config, each with one line saying what it is for. The assistant
    // works in the background and is not named here; its configured name rides along unchanged.
    assert.equal(await page.locator('#onb-company').inputValue(), 'Initech');
    assert.equal(await page.locator('#onb-app').inputValue(), 'Initech Hub');
    assert.equal(await page.locator('#onb-assistant').count(), 0);
    assert.match(await page.locator('#onb-step').textContent(), /Mac app's name is set when the Mac app is built/);
    await page.locator('#onb-next').click();
    await page.locator('#onb-what').waitFor();
    assert.equal(puts.length, 1);
    assert.deepEqual(puts[0].names, {company_name: 'Initech', app_name: 'Initech Hub', assistant_name: 'Ace'});
    // Nobody has chosen a team yet, so the first draft carries none; BotOps and the assistant are built whatever is chosen.
    assert.deepEqual(puts[0].selected, {});
    assert.deepEqual(puts[0].answers.never_without_person, ['send', 'spend', 'publish', 'hire']);

    // ---- b: about the company. The four "never" boxes start checked; one comes off here.
    assert.equal(await page.locator('#onb-count').textContent(), 'Step 2 of 7');
    assert.equal(await page.locator('[data-onb-never][value=hire]').isChecked(), true);
    await shot(page, 'desktop-1-about');
    await page.locator('#onb-what').fill('We sell a live audio app and the studio software behind it.');
    await page.locator('input[name=onb-customers][value=businesses]').check();
    await page.locator('input[name=onb-software][value=yes]').check();
    await page.locator('#onb-size').selectOption('2-10');
    await page.locator('[data-onb-never][value=hire]').uncheck();
    await page.locator('#onb-next').click();
    await page.locator('#onb-pains').waitFor();
    assert.equal(puts.length, 2);
    assert.deepEqual(puts[1].answers, {
      what_we_do: 'We sell a live audio app and the studio software behind it.',
      customers: 'businesses', software_product: 'yes', team_size: '2-10', work_arrives: [], repetitive_work: '',
      never_without_person: ['send', 'spend', 'publish'], pains: [], pains_text: '', tools: []});

    // ---- c: what hurts (chips from the starter cards, and free text) and what the company uses. Nothing leaves this computer.
    assert.equal(await page.locator('#onb-count').textContent(), 'Step 3 of 7');
    await shot(page, 'desktop-2-needs-empty');
    assert.match(await page.locator('#onb-step').evaluate(el => el.parentElement.textContent), /stays on this computer: nothing is sent anywhere/);
    // Only the featured pains show, grouped by team; the others still match what is typed.
    assert.deepEqual(await page.locator('[data-onb-pain]').evaluateAll(els => els.map(el => el.value)),
      ['I don\'t know what is really going on across the company', 'too much email', 'support inbox is overflowing', 'customers wait too long for an answer']);
    assert.deepEqual(await page.locator('[data-pain-team]').evaluateAll(els => els.map(el => el.dataset.painTeam)), ['Leadership', 'Support']);
    assert.equal(await page.locator('[data-pain-team=Support] [data-onb-pain]').count(), 2);
    await page.locator('[data-onb-pain][value="support inbox is overflowing"]').check();
    await page.locator('#onb-pains-text').fill('Weekend support mail waits until Monday.');
    await page.locator('[data-onb-tool][value=mail]').check();
    await page.locator('[data-onb-tool][value=github]').check();
    assert.deepEqual(await page.locator('[data-onb-tool]').evaluateAll(els => els.map(el => el.value)), ['mail', 'chat', 'crm', 'github', 'meetings', 'docs']);
    await shot(page, 'desktop-3-needs');
    await page.locator('#onb-next').click();
    await page.locator('[data-team-start]').first().waitFor();
    assert.equal(puts.length, 3);
    assert.deepEqual([puts[2].answers.pains, puts[2].answers.pains_text, puts[2].answers.tools],
      [['support inbox is overflowing'], 'Weekend support mail waits until Monday.', ['mail', 'github']]);

    // ---- d: your team. The starter team is the way in: the best pain match and Chief of Staff, each with why and its needs.
    assert.equal(await page.locator('#onb-count').textContent(), 'Step 4 of 7');
    assert.equal(await page.locator('[data-team-start=starter] input').isChecked(), true);
    assert.deepEqual(await page.locator('[data-team-bot]').evaluateAll(els => els.map(el => el.dataset.teamBot)), ['chief-of-staff', 'support']);
    assert.match(await page.locator('[data-team-builtin]').textContent(), /Always included: Ace, BotOps/);
    assert.equal(await page.locator('[data-team-why=support]').textContent(),
      'You said "support inbox is overflowing". Answers customers and keeps the queue short.');
    assert.match(await page.locator('[data-team-prereq=support]').textContent(), /Mail/);       // ticked: met, not "Needs Mail"
    assert.doesNotMatch(await page.locator('[data-team-prereq=support]').textContent(), /Needs/);
    assert.match(await page.locator('[data-team-bot=support]').textContent(), /First routine, off until you approve it: Daily support triage/);
    assert.equal(await page.locator('[data-team-reports=support]').inputValue(), 'human:ana');    // the company owner, by default
    assert.match(await page.locator('[data-team-start=starter]').textContent(), /2 bots: the best matches for what hurts, plus Chief of Staff/);
    // No limit and no nagging about the count: the note is only that nothing exists until Create.
    assert.doesNotMatch(await page.locator('#onb-step').textContent(), /start with a few|too many|at most|no more than/i);
    assert.match(await page.locator('#onb-step').textContent(), /Nothing exists until Create my team/);
    await shot(page, 'desktop-4-team-starter');
    // A pain with no tool to serve it is held back and said so, under Add a bot.
    await page.locator('#team-add summary').click();
    assert.match(await page.locator('[data-team-held=meeting-notes]').textContent(), /needs meetings, which you did not tick/);
    assert.equal(await page.locator('[data-team-add=inbox]').count(), 1);

    // The full org chart: every template that fits, in teams with a lead, mirroring a company.
    await page.locator('[data-team-start=full] input').check();
    assert.deepEqual(await page.locator('[data-team-group]').evaluateAll(els => els.map(el => el.dataset.teamGroup)),
      ['Leadership', 'Marketing', 'Support', 'Operations']);
    assert.match(await page.locator('[data-team-group=Leadership] h3').textContent(), /led by Chief of Staff/);
    assert.match(await page.locator('[data-team-start=full]').textContent(), /5 bots in 4 teams, a lead for each/);
    assert.equal(await page.locator('[data-team-reports=inbox]').inputValue(), 'chief-of-staff');   // a member reports to its lead
    assert.equal(await page.locator('[data-team-reports=chief-of-staff]').inputValue(), 'human:ana');
    assert.equal(await page.locator('[data-team-bot=social] .pill.ok', {hasText: 'Lead'}).count(), 1);
    await shot(page, 'desktop-5-team-full');
    // Both are fully editable: remove one, add it back, rename, and point a bot at another person or bot.
    await page.locator('[data-team-remove=bookkeeper]').click();
    assert.equal(await page.locator('[data-team-bot=bookkeeper]').count(), 0);
    await page.locator('[data-team-remove=inbox]').click();
    assert.deepEqual(await page.locator('[data-team-bot]').evaluateAll(els => els.map(el => el.dataset.teamBot)), ['chief-of-staff', 'social', 'support']);
    await page.locator('[data-team-start=starter] input').check();                  // back to the starting team: the edits reset
    assert.deepEqual(await page.locator('[data-team-bot]').evaluateAll(els => els.map(el => el.dataset.teamBot)), ['chief-of-staff', 'support']);
    await page.locator('#team-add summary').click();
    await page.locator('[data-team-add=social]').click();
    await page.locator('[data-cat-name=support]').fill('Support desk');
    await page.locator('[data-team-reports=support]').selectOption('chief-of-staff');
    await page.locator('[data-team-reports=social]').selectOption('human:ben');
    // Two bots can never report to each other: a bot's options leave out everything under it.
    assert.equal(await page.locator('[data-team-reports=chief-of-staff] option[value=support]').count(), 0);
    assert.equal(await page.locator('[data-team-reports=support] option[value=support]').count(), 0);
    assert.equal(await page.locator('[data-team-reports=support] option[value=chief-of-staff]').count(), 1);
    await page.locator('#onb-next').click();
    await page.locator('#onb-enroll').waitFor();
    assert.equal(puts.length, 4);
    // The team goes to the server in the order to set it up: the best pain match first, then Chief of Staff, then what was added.
    assert.deepEqual(Object.keys(puts[3].selected), ['coo', 'botops', 'support', 'chief-of-staff', 'social']);
    assert.equal(puts[3].selected.support.display_name, 'Support desk');
    assert.equal(puts[3].selected.support.reports_to, 'chief-of-staff');
    assert.equal(puts[3].selected.social.reports_to, 'human:ben');
    assert.equal(puts[3].selected['chief-of-staff'].reports_to, 'human:ana');
    assert.equal(puts[3].selected.botops.reports_to, undefined);       // the built-ins keep their place

    // ---- d: this Mac. The enrollment file is the Settings flow; the commands keep <slug> literal.
    assert.equal(await page.locator('#onb-count').textContent(), 'Step 5 of 7');
    assert.equal(await page.locator('#onb-machine-status').textContent(), 'No computer enrolled yet');
    // Not a Mac-only story: computers can be Macs or Linux/cloud boxes, on a subscription or an API key.
    const blurb = await page.locator('#onb-step').evaluate(el => el.parentElement.textContent);
    assert.match(blurb, /a Mac, or a Linux or cloud server/);
    assert.match(blurb, /subscription or an API key/);
    assert.doesNotMatch(blurb, /Mac you own/);
    assert.match(await page.locator('#onb-step').textContent(), /scripts\/tico -e <slug> profile add default/);
    assert.match(await page.locator('#onb-step').textContent(), /scripts\/tico -e <slug> install bot/);
    await page.locator('#onb-enroll').click();
    await page.waitForFunction(() => !/<setup-file>/.test(document.querySelector('#onb-step').textContent));
    assert.deepEqual(enrollments, [{operator: 'ana'}]);
    assert.match(await page.locator('#onb-step').textContent(), /scripts\/tico -e <slug> enroll --code-file "\$HOME\/Downloads\/tico-enrollment-ana-[a-z0-9]+\.json" --label "Ana's Mac"/);
    // A Linux or cloud server gets the installer line (compose, with the updater) with the real URL and code, and no setup file.
    await page.locator('[data-onb-kind][value=linux]').check();
    const installLine = /curl -fsSL https:\/\/github\.com\/ticoteam\/tico\/releases\/download\/v0\.2\.0\/install\.sh \| sh -s -- --runner --url https:\/\/initech\.test --code <code> --label "Ana's server"/;
    assert.match(await page.locator('#onb-step').textContent(), installLine);
    // The bare docker run stays as an alternative, pinned to the server's release and said not to update itself.
    assert.match(await page.locator('#onb-step').textContent(), /no updater, so it will not follow the server's releases/);
    assert.match(await page.locator('#onb-step').textContent(), /docker run -d --name tico-runner --restart unless-stopped -v tico-runner:\/home\/runner ghcr\.io\/ticoteam\/tico-runner:v0\.2\.0 join --url https:\/\/initech\.test --code <code>/);
    await page.locator('#onb-enroll').click();
    await page.waitForFunction(() => /--code enroll-code --label "Ana's server"/.test(document.querySelector('#onb-step').textContent));
    assert.match(await page.locator('#onb-step').textContent(), /docker exec -it tico-runner codex login --device-auth/);
    await page.locator('[data-onb-kind][value=mac]').check();
    // The Mac comes online; the next save carries the live machine through to the review.
    machine = {runners: [{id: 'runner-1', label: "Ana's Mac", online: true}, {id: 'runner-2', label: 'Cloud box', online: true}, {id: 'runner-3', label: 'Old laptop', online: false}], enrolled: true};
    await page.locator('#onb-next').click();
    await page.locator('#onb-connect').waitFor();
    assert.equal(puts.length, 5);

    // A runner that is already online is shown as ready; the Mac instructions fold away.
    await page.locator('#onb-back').click();
    await page.locator('#onb-machine-ready').waitFor();
    assert.equal(await page.locator('#onb-machine-ready').textContent(), "A computer is online and will run your bots.");
    assert.equal(await page.locator('#onb-more').evaluate(el => el.open), false);
    assert.equal(await page.locator('#onb-enroll').isVisible(), false);
    await page.locator('#onb-more summary').click();
    assert.equal(await page.locator('#onb-enroll').isVisible(), true);
    await page.locator('#onb-next').click();
    await page.locator('#onb-connect').waitFor();
    assert.equal(puts.length, 6);

    // ---- e: connect your agent. Optional: the button opens the same modal as the sidebar's plug.
    assert.equal(await page.locator('#onb-count').textContent(), 'Step 6 of 7');
    await page.locator('#onb-connect').click();
    await page.locator('dialog.connect-agent[open]').waitFor();
    await page.locator('dialog.connect-agent [data-close]').click();
    await page.waitForFunction(() => !document.querySelector('dialog.connect-agent'));
    await page.locator('#onb-next').click();
    await page.locator('#onb-finish').waitFor();
    assert.equal(puts.length, 7);

    // ---- g: review, then create exactly once.
    assert.equal(await page.locator('#onb-count').textContent(), 'Step 7 of 7');
    const review = await page.locator('#onb-step').textContent();
    assert.match(review, /Initech Hub/);
    assert.match(review, /Businesses/);
    assert.match(review, /Software is the product\s*Yes/);
    assert.match(review, /What hurts\s*support inbox is overflowing; Weekend support mail waits until Monday\./);
    assert.match(review, /Tools\s*Mail, GitHub/);
    assert.match(review, /Send anything, Spend money, Publish anything/);
    assert.match(review, /Computers\s*Ana's Mac, Cloud box online/);
    assert.match(await page.locator('[data-review-team]').textContent(), /Chief of Staff\s*→ Ana Rivera/);
    assert.match(await page.locator('[data-review-team]').textContent(), /Support desk\s*→ Chief of Staff/);
    assert.match(await page.locator('[data-review-team]').textContent(), /Social\s*→ Ben Cole/);
    assert.doesNotMatch(review, /This Mac/);
    assert.equal(await page.locator('#onb-finish').textContent(), 'Create my team');
    await page.locator('#onb-finish').click();
    await page.locator('#onb-tasks').waitFor();
    await page.evaluate(() => document.querySelector('#onb-finish')?.click());   // no second create
    assert.equal(completes.length, 1);
    assert.deepEqual(completes[0], {});

    // ---- the tour opens on the first look at the finished company, and Skip is remembered.
    await page.locator('.gs-tour[role=dialog]').waitFor();
    assert.equal(await page.locator('.gs-tour-count').textContent(), '1 of 6');
    await page.locator('[data-tour-skip]').click();
    await page.locator('.gs-tour').waitFor({state: 'detached'});
    assert.deepEqual(tourPosts, [{tour: true}]);

    // ---- after Create, one screen. Each starter is parked ("Needs onboarding") with its repository still being set up
    // on the computer until it exists; only then does Start setup work.
    assert.equal(await page.locator('#onb h1').textContent(), 'Setting up Initech');
    assert.match(await page.locator('[data-onb-bot=coo]').textContent(), /Ace\s+Set up automatically once a computer is online\./);
    assert.match(await page.locator('[data-onb-bot=botops]').textContent(), /Set up automatically once a computer is online\./);
    assert.equal(await page.locator('[data-onb-bot=coo] [data-needs-onboarding]').count(), 0);        // the built-ins work at once
    assert.match(await page.locator('[data-onb-bot=support]').textContent(), /Needs onboarding/);
    assert.match(await page.locator('[data-onb-bot=support]').textContent(), /Repository ready\. It does nothing until you set it up together\./);
    assert.match(await page.locator('[data-onb-bot=chief-of-staff]').textContent(), /Setting up its repository on your computer/);
    assert.equal(await page.locator('[data-fr-start=chief-of-staff]').isDisabled(), true);
    assert.equal(await page.locator('[data-fr-start=support]').isDisabled(), false);
    assert.match(await page.locator('[data-onb-bot=social]').textContent(), /BotOps is setting this up\./);         // not a starter: BotOps builds it
    assert.equal(await page.locator('[data-onb-bot=social] a').getAttribute('href'), '#/task/task-social');
    assert.equal(await page.locator('#onb-machine-status').textContent(), "Ana's Mac, Cloud box online");
    // Invite an admin: the roster first, then the role, both as the owner.
    await page.locator('#fr-admin-form [name=name]').fill('Sam Ortiz');
    await page.locator('#fr-admin-form [name=email]').fill('sam@initech.test');
    await page.locator('#fr-admin-form [type=submit]').click();
    await page.locator('#fr-admin-status', {hasText: 'on the roster as an admin'}).waitFor();
    assert.deepEqual(invites, [['add', {name: 'Sam Ortiz', email: 'sam@initech.test'}], ['role', {role: 'admin'}]]);
    // A human owner for each bot, added as a co-owner.
    assert.match(await page.locator('[data-fr-owned=support]').textContent(), /Ana Rivera owns it/);
    await page.locator('[data-fr-owner=support]').selectOption('ben');
    await page.locator('[data-fr-owned=support]', {hasText: 'Ben Cole own it'}).waitFor();
    assert.deepEqual(owners, [['support', {add: ['ben'], remove: []}]]);
    // Tools are connected once, in the hub's own fields, and never in a chat.
    assert.deepEqual(await page.locator('#fr-tools [data-fr-link]').evaluateAll(els => els.map(el => el.dataset.frLink)),
      ['mail', 'github', 'credentials', 'integrations']);
    assert.equal(await page.locator('[data-fr-link=credentials]').getAttribute('href'), '#/credentials');
    assert.match(await page.locator('[data-fr-secrets]').textContent(), /Enter secrets in those fields, never in a chat with a bot/);
    // What was typed survives the progress poll (only the rows are redrawn).
    await page.locator('#fr-admin-form [name=name]').fill('Half typed');
    await page.evaluate(() => onbRenderDone(ONB));
    assert.equal(await page.locator('#fr-admin-form [name=name]').inputValue(), 'Half typed');
    await shot(page, 'desktop-6-created');
    // Finishing takes the setup entry out of the sidebar and puts the names on the app; the chart marks the parked bots.
    assert.equal(await page.locator('#nav-welcome').evaluate(el => el.hidden), true);
    assert.equal(await page.title(), 'Initech Hub');
    await page.locator('#tree .node[href="#/bot/support"] .tree-setup').waitFor();
    assert.equal(await page.locator('#tree .node[href="#/bot/coo"] .tree-setup').count(), 0);
    // Start setup: one line from the person begins its onboarding conversation, and the bot page carries the mark.
    await page.locator('[data-fr-start=support]').click();
    await page.waitForFunction(() => location.hash === '#/bot/support');
    assert.deepEqual(chats, [['support', {text: "Let's set you up."}]]);
    assert.deepEqual(definitions, []);                                    // it was already active: nothing to activate first
    await page.locator('#bot-onboard').waitFor();
    await shot(page, 'desktop-7-bot-page');
    assert.match(await page.locator('#bot-onboard').textContent(), /Needs onboarding/);
    assert.match(await page.locator('#bot-onboard').textContent(), /does nothing on its own until you have set it up together/);
    // A planned starter is activated first (an owner's call), then told the same line.
    await page.goto('https://tico-ui.test/#/bot/chief-of-staff');
    await page.locator('#bot-start-setup').click();
    await page.locator('#bot-start-setup', {hasText: 'Setup started'}).waitFor();
    assert.deepEqual(definitions, [{path: '/api/v2/bots/chief-of-staff/definition', body: {status: 'active', expected_revision: 4}}]);
    assert.deepEqual(chats.at(-1), ['chief-of-staff', {text: "Let's set you up."}]);
    // The mark clears when the bot says it is set up: the page follows the bot's state.
    BOTS_AFTER.find(bot => bot.slug === 'chief-of-staff').onboarding_state = 'onboarded';
    await page.evaluate(() => refresh(true));
    await page.locator('#bot-onboard').waitFor({state: 'detached'});
    await page.locator('#tree .node[href="#/bot/chief-of-staff"] .tree-setup').waitFor({state: 'detached'});
    await page.goto('https://tico-ui.test/#/welcome');
    await page.locator('#onb-tasks').waitFor();

    // The setup task link opens the Tasks page with that task already in full.
    await page.locator('[data-onb-bot=social] a').click();
    await page.waitForFunction(() => location.hash === '#/task/task-social');
    await page.locator('#task-modal[open] .tmodal-title').waitFor();
    assert.equal(await page.locator('#task-modal .tmodal-title').textContent(), 'Set up Social');
    await page.keyboard.press('Escape');
    await page.goBack();
    await page.waitForFunction(() => location.hash === '#/welcome');
    await page.locator('#onb-tasks').waitFor();
    await page.locator('#onb-tasks').click();
    await page.waitForFunction(() => location.hash === '#/tasks');

    // ---- Settings -> Bots: the same cards, adding one bot from the catalog.
    await page.goto('https://tico-ui.test/#/settings');
    await page.locator('[data-settings-tab=devices]').click();
    await page.locator('#machine-kind').selectOption('linux');
    assert.equal(await page.locator('#machine-label').inputValue(), "Ana Rivera's server");
    await page.locator('#register-machine').click();
    await page.waitForFunction(() => /--code enroll-code --label "Ana Rivera's server"/.test(document.querySelector('#machine-enroll-status').textContent));
    assert.match(await page.locator('#machine-enroll-status').textContent(), /join --url https:\/\/initech\.test/);
    await page.locator('#machine-kind').selectOption('mac');
    await page.locator('#settings-add-catalog:not([disabled])').click();
    await page.locator('#catalog-picker-grid').waitFor();
    // The bots that already exist are not offered again, and nothing is forced on here.
    assert.deepEqual(await page.locator('#catalog-picker-grid .cat-card').evaluateAll(
      els => els.map(el => el.dataset.catCard)), ['botops', 'bookkeeper', 'inbox', 'social']);
    assert.equal(await page.locator('#catalog-picker-grid [data-cat-toggle=botops]').isDisabled(), false);
    assert.equal(await page.locator('#catalog-picker-grid [data-cat-toggle=bookkeeper]').isChecked(), false);
    await page.locator('#catalog-picker-grid [data-cat-toggle=bookkeeper]').check();
    await page.locator('#catalog-picker-grid [data-cat-name=bookkeeper]').fill('Ledger');
    await page.locator('#catalog-picker-grid [data-cat-card=bookkeeper] .cat-instructions summary').click();
    await page.locator('#catalog-picker-grid [data-cat-instructions=bookkeeper]').fill('# Ledger\n\nChase, never pay. Ask Ana.\n');
    await page.getByRole('button', {name: 'Add selected', exact: true}).click();
    await page.waitForFunction(() => !document.querySelector('#catalog-picker').open);
    assert.equal(created.length, 1);
    assert.equal(created[0].slug, 'bookkeeper');
    assert.equal(created[0].template, 'bookkeeper');
    assert.equal(created[0].display_name, 'Ledger');
    assert.equal(created[0].instructions, '# Ledger\n\nChase, never pay. Ask Ana.\n');
    assert.equal(created[0].model, 'gpt-6-sol');
    assert.equal(created[0].effort, 'high');
    assert.deepEqual(created[0].owners, ['ana']);

    // Inbox bots ask whose mailbox, then append Mailbox: so BotOps can fill {{mailbox}}.
    await page.locator('[data-settings-tab=devices]').click();
    await page.locator('#settings-add-catalog:not([disabled])').click();
    await page.locator('#catalog-picker-grid').waitFor();
    assert.equal(await page.locator('#catalog-picker-grid [data-cat-mailbox=inbox]').count(), 1);
    await page.locator('#catalog-picker-grid [data-cat-toggle=inbox]').check();
    await page.getByRole('button', {name: 'Add selected', exact: true}).click();
    assert.match(await page.locator('#catalog-picker-status').textContent(), /whose mailbox/);
    await page.locator('#catalog-picker-grid [data-cat-mailbox=inbox]').selectOption('ana');
    await page.getByRole('button', {name: 'Add selected', exact: true}).click();
    await page.waitForFunction(() => !document.querySelector('#catalog-picker').open);
    assert.equal(created.length, 2);
    assert.equal(created[1].slug, 'ana-inbox');
    assert.equal(created[1].template, 'inbox');
    assert.equal(created[1].display_name, 'Ana Rivera Inbox');
    assert.match(created[1].instructions, /Mailbox: ana@acme.example/);

    // ---- phone width: the wizard is one column and never scrolls sideways.
    record = {...record, completed: null, needed: true};
    const phone = await context.newPage();
    phone.on('pageerror', e => errors.push(e.message));
    await phone.setViewportSize({width: 390, height: 844});
    await phone.goto('https://tico-ui.test/#/welcome');
    await phone.locator('#onb-company').waitFor();
    const fits = () => phone.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth
      && document.querySelector('#main').scrollWidth <= document.querySelector('#main').clientWidth);
    assert.equal(await fits(), true);
    await phone.locator('#onb-next').click();
    await phone.locator('#onb-what').waitFor();
    assert.equal(await fits(), true);
    await shot(phone, 'phone-1-about');
    await phone.locator('#onb-next').click();
    await phone.locator('#onb-pains').waitFor();
    assert.equal(await fits(), true);
    await shot(phone, 'phone-2-needs');
    await phone.locator('#onb-next').click();
    await phone.locator('[data-team-start]').first().waitFor();
    assert.equal(await fits(), true);
    assert.equal(await phone.locator('[data-team-bot]').count(), 3);     // the draft's own team, saved on the first visit
    await phone.locator('[data-team-start=full] input').check();
    assert.equal(await fits(), true);
    await phone.locator('#team-add summary').click();
    assert.equal(await fits(), true);
    await shot(phone, 'phone-4-team-full');
    // Mail Drafts reads one person's mailbox, so the team cannot be taken further until it is chosen.
    await phone.locator('#onb-next').click();
    await phone.locator('#team-problem').waitFor();
    assert.match(await phone.locator('#team-problem').textContent(), /Choose whose mailbox Mail Drafts reads/);
    await phone.locator('[data-cat-mailbox=inbox]').selectOption('ana');
    assert.equal(await fits(), true);
    await phone.locator('#onb-next').click();
    await phone.locator('#onb-machine-ready').waitFor();
    await phone.locator('#onb-more summary').click();
    await phone.locator('#onb-enroll').waitFor();
    assert.equal(await fits(), true);

    // After Create, on a phone: the same one screen, one column.
    BOTS_AFTER.find(bot => bot.slug === 'chief-of-staff').onboarding_state = 'needs_onboarding';
    record = {...record, completed: '2026-09-16T10:00:00Z', needed: false, bots: BOTS_AFTER.map(bot => ({...bot})), machine};
    const created2 = await context.newPage();
    created2.on('pageerror', e => errors.push(e.message));
    await created2.setViewportSize({width: 390, height: 844});
    await created2.goto('https://tico-ui.test/#/welcome');
    await created2.locator('#fr-admin-form').waitFor();
    assert.equal(await created2.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth), true);
    await shot(created2, 'phone-5-created');
    await created2.locator('#fr-tools').scrollIntoViewIfNeeded();
    await shot(created2, 'phone-6-created-tools');
    await created2.goto('https://tico-ui.test/#/bot/support');
    await created2.locator('#bot-onboard').waitFor();
    assert.equal(await created2.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth), true);
    await shot(created2, 'phone-7-bot-page');

    // A viewer has no setup entry and lands on Tasks if they type the address.
    me.role = 'human';
    const viewer = await context.newPage();
    viewer.on('pageerror', e => errors.push(e.message));
    await viewer.goto('https://tico-ui.test/#/welcome');
    await viewer.waitForFunction(() => location.hash === '#/tasks');
    assert.equal(await viewer.locator('#onb-company').count(), 0);

    assert.deepEqual(errors, []);
    console.log('PASS: first-run wizard asks, proposes a starter team or a full chart, creates it once, parks each starter and starts its setup.');
  } finally { await browser.close(); }
})().catch(e => { console.error(e); process.exitCode = 1; });
