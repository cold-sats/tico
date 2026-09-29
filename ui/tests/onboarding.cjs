// Offline browser regression for the first-run wizard: a company whose config
// says onboarding_needed lands on #/welcome instead of Tasks and keeps a "Finish setup" entry; the
// six steps save a draft with PUT /api/v2/onboarding on every Next (since 2026-09-24 there is no
// assistant to name, and an optional "Connect your agent" step opens connectAgent()); the catalog cards lock the
// two required bots on, pre-tick what the answers recommend and say why; Finish posts
// /api/v2/onboarding/complete exactly once; and the progress screen links each bot's setup task
// and offers Activate as soon as its repository exists. Settings -> Bots reuses the same cards.
// Fixtures only - no server, no network.
const {chromium} = require('playwright');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const html = fs.readFileSync(path.join(__dirname, '../index.html'), 'utf8');

const CONFIG = {environment_id: 'initech', company_name: 'Initech', app_name: 'Initech Hub',
  assistant_name: 'Ace', assistant_bot: 'coo', public_url: 'https://initech.test',
  runner_url: 'https://initech.test', github_owner: 'initech-inc', local: false, release: '',
  onboarding_needed: true, version: '0.2.0', runner_compat: {version: '0.2.0', min_runner: '0.1.0'}};

const CATALOG = [
  // The server renders every card with the company's names, so the assistant's reads as Ace.
  {template: 'assistant', slug: 'coo', name: 'Ace', required: false, default: true, bootstrap: true,
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
  {template: 'support', slug: 'support', name: 'Support', required: false, bootstrap: false,
   summary: 'Answers customers and keeps the queue short.',
   owns: ['the ticket queue'], never: ['refunds without a person'],
   runtime: 'codex', model: 'gpt-6-sol', reasoning_effort: 'high',
   recommend_when: ['has_support_inbox', 'uses_tickets', 'sells_to_consumers', 'uses_email'],
   instructions: '# Support\n\nAnswer the queue in the company voice.\n'},
  {template: 'social', slug: 'social', name: 'Social', required: false, bootstrap: false,
   summary: 'Drafts posts and watches mentions.',
   owns: ['the posting calendar'], never: ['publishes without a person'],
   runtime: 'codex', model: 'gpt-6-sol', reasoning_effort: 'medium', recommend_when: ['uses_slack'],
   instructions: '# Social\n\nDraft, never publish.\n'},
  {template: 'bookkeeper', slug: 'bookkeeper', name: 'Bookkeeper', required: false, bootstrap: false,
   summary: 'Chases invoices and reconciles the ledger.',
   owns: ['the invoice ledger'], never: ['pays anything without a person'],
   runtime: 'codex', model: 'gpt-6-sol', reasoning_effort: 'high', recommend_when: ['sells_to_businesses', 'has_pipeline'],
   instructions: '# Bookkeeper\n\nChase, never pay.\n'},
  {template: 'inbox', slug: 'inbox', name: 'Inbox', required: false, bootstrap: false,
   summary: 'Reads one person mailbox on a cadence.',
   owns: ['the inbox pass'], never: ['sends mail on its own'],
   runtime: 'codex', model: 'gpt-6-sol', reasoning_effort: 'medium', recommend_when: ['has_personal_inbox'],
   instructions: '# Inbox\n\nRead, never send.\n'},
];

const BOTS_AFTER = [
  {slug: 'coo', display_name: 'Ace', status: 'active', template: 'assistant',
   setup_task_id: null, repository_present: false},
  {slug: 'botops', display_name: 'BotOps', status: 'active', template: 'botops',
   setup_task_id: null, repository_present: true},
  {slug: 'support', display_name: 'Support desk', status: 'planned', template: 'support',
   setup_task_id: 'task-support', repository_present: true},
  {slug: 'social', display_name: 'Social', status: 'planned', template: 'social',
   setup_task_id: 'task-social', repository_present: false},
];

(async () => {
  const browser = await chromium.launch({headless: true, channel: process.env.TICO_BROWSER_CHANNEL === undefined ? 'chrome' : process.env.TICO_BROWSER_CHANNEL || undefined});
  try {
    const context = await browser.newContext({viewport: {width: 1100, height: 800}, serviceWorkers: 'block', acceptDownloads: true});
    const puts = [], tourPosts = [], completes = [], definitions = [], created = [], enrollments = [];
    let record = {
      names: {company_name: 'Initech', app_name: 'Initech Hub', assistant_name: 'Ace'},
      answers: {what_we_do: '', customers: '', team_size: '', work_arrives: [],
                repetitive_work: '', never_without_person: ['send', 'spend', 'publish', 'hire']},
      selected: {}, completed: null, bots: [],
      machine: {runners: [], enrolled: false}, needed: true,
    };
    // The server recommends against the answers, so nothing is recommended until step b is saved.
    const recommendedFor = answers => [
      ...((answers?.work_arrives || []).includes('tickets') ? ['support'] : []),
      ...(answers?.customers === 'businesses' ? ['bookkeeper'] : []),
    ];
    let machine = {runners: [], enrolled: false};
    const me = {id: 'ana', name: 'Ana Rivera', role: 'owner', cloud: true,
                email: 'ana@acme.example', credential_access: false, config: CONFIG};
    const v2bots = () => BOTS_AFTER.map((bot, i) => ({slug: bot.slug, display_name: bot.display_name,
      status: bot.status, revision: i + 1, team: null, operator: 'ana', repo: 'emp-' + bot.slug}));

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
        reports_to: '', description: 'the point of contact', revision: 1, users: [{id: 'ana', name: 'Ana Rivera', email: 'ana@acme.example'}]}]);
      if (p === '/api/issues') return json([]);
      if (p === '/api/v2/catalog') return json({cards: CATALOG});
      if (p === '/api/v2/onboarding') {
        if (request.method() === 'PUT') {
          const body = request.postDataJSON();
          puts.push(body);
          record = {...record, ...body, machine};
          return json({...record, recommended: recommendedFor(record.answers)});
        }
        return json({...record, machine, recommended: recommendedFor(record.answers)});
      }
      if (p === '/api/v2/onboarding/complete') {
        completes.push(request.postDataJSON());
        record = {...record, completed: '2026-09-16T10:00:00Z', needed: false,
                  bots: BOTS_AFTER.map(bot => ({...bot})), machine};
        return json({...record, recommended: recommendedFor(record.answers)});
      }
      if (p === '/api/v2/getting-started/state') { tourPosts.push(request.postDataJSON()); return json({tour: true, checklist: false, cards: [], skipped: []}); }
      if (p === '/api/v2/enrollments') { enrollments.push(request.postDataJSON()); return json({code: 'enroll-code', expires: '2026-09-16T10:15:00Z'}); }
      if (p === '/api/v2/bots' && request.method() === 'POST') { created.push(request.postDataJSON()); return json({bot: {slug: request.postDataJSON().slug}}); }
      if (p === '/api/v2/bots') return json(v2bots());
      if (/^\/api\/v2\/bots\/[^/]+\/definition$/.test(p)) {
        definitions.push({path: p, body: request.postDataJSON()});
        return json({slug: p.split('/')[4], status: 'active', revision: 9});
      }
      if (p === '/api/v2/status') return json({bots: []});
      if (p === '/api/v2/needs-you') return json({items: []});
      if (/^\/api\/v2\/tasks\/[^/]+\/chat$/.test(p)) return json({recipient: {slug: 'botops', name: 'BotOps', can_chat: true}, messages: [], conversation: null});
      if (p === '/api/v2/tasks') return json({tasks: [{id: 'task-support', title: 'Set up Support desk',
        owner: 'bot:botops', status: 'in_progress', version: 1, updated: '2026-09-16T10:01:00Z',
        created: '2026-09-16T10:00:30Z', requester: 'human:ana',
        body: 'Create the repository and the first routine.'}]});
      if (p === '/api/people') return json({people: [{id: 'ana', name: 'Ana Rivera', email: 'ana@acme.example'}]});
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
    assert.equal(await page.locator('#onb-count').textContent(), 'Step 1 of 6');

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
    // Nothing is recommended yet, so the first draft carries BotOps and the assistant's default.
    assert.deepEqual(Object.keys(puts[0].selected).sort(), ['botops', 'coo']);
    assert.equal(puts[0].selected.coo.display_name, 'Ace');
    assert.equal(puts[0].selected.coo.template, 'assistant');
    assert.equal(puts[0].selected.botops.instructions, '# BotOps\n\nYou set up every other bot.\n');
    assert.deepEqual(puts[0].answers.never_without_person, ['send', 'spend', 'publish', 'hire']);

    // ---- b: about the company. The four "never" boxes start checked; one comes off here.
    assert.equal(await page.locator('#onb-count').textContent(), 'Step 2 of 6');
    assert.equal(await page.locator('[data-onb-never][value=hire]').isChecked(), true);
    await page.locator('#onb-what').fill('We sell a live audio app and the studio software behind it.');
    await page.locator('input[name=onb-customers][value=businesses]').check();
    await page.locator('#onb-size').selectOption('2-10');
    await page.locator('[data-onb-arrives][value=email]').check();
    await page.locator('[data-onb-arrives][value=tickets]').check();
    await page.locator('#onb-repetitive').fill('Answering the same three questions about billing.');
    await page.locator('[data-onb-never][value=hire]').uncheck();
    await page.locator('#onb-next').click();
    await page.locator('#onb-catalog').waitFor();
    assert.equal(puts.length, 2);
    assert.deepEqual(puts[1].answers, {
      what_we_do: 'We sell a live audio app and the studio software behind it.',
      customers: 'businesses', team_size: '2-10', work_arrives: ['email', 'tickets'],
      repetitive_work: 'Answering the same three questions about billing.',
      never_without_person: ['send', 'spend', 'publish']});

    // ---- c: the catalog. Required first and locked on, recommended pre-ticked and explained.
    assert.equal(await page.locator('#onb-count').textContent(), 'Step 3 of 6');
    assert.deepEqual(await page.locator('#onb-catalog .cat-card').evaluateAll(
      els => els.map(el => el.dataset.catCard)), ['botops', 'coo', 'bookkeeper', 'support', 'inbox', 'social']);
    assert.equal(await page.locator('[data-cat-name=coo]').inputValue(), 'Ace');
    // BotOps is required and locked on; the assistant is checked to start with but is a choice.
    const required = page.locator('[data-cat-toggle=botops]');
    assert.equal(await required.isDisabled(), true);
    assert.equal(await required.isChecked(), true);
    await required.click({force: true});
    assert.equal(await required.isChecked(), true);
    assert.equal(await page.locator('[data-cat-card=botops] .pill.ok').count(), 1);
    const assistant = page.locator('[data-cat-toggle=coo]');
    assert.equal(await assistant.isDisabled(), false);
    assert.equal(await assistant.isChecked(), true);
    assert.equal(await page.locator('[data-cat-card=coo] .pill.ok').count(), 0);
    assert.match(await page.locator('[data-cat-when=coo]').textContent(), /Recommended if you use Slack or send meetings to bots/);
    await assistant.uncheck();
    assert.equal(await assistant.isChecked(), false);
    await assistant.check();
    // The answers two screens back are what recommends a card, and it arrives pre-selected.
    assert.equal(await page.locator('[data-cat-toggle=support]').isChecked(), true);
    assert.equal(await page.locator('[data-cat-reason=support]').textContent(),
      'Recommended because you keep a support queue and work arrives as tickets.');
    assert.equal(await page.locator('[data-cat-reason=social]').count(), 0);
    assert.equal(await page.locator('[data-cat-toggle=social]').isChecked(), false);
    // Business customers imply a pipeline, so two tags land on one sentence: say it once.
    assert.equal(await page.locator('[data-cat-toggle=bookkeeper]').isChecked(), true);
    assert.equal(await page.locator('[data-cat-reason=bookkeeper]').textContent(),
      'Recommended because you sell to businesses.');
    await page.locator('[data-cat-toggle=bookkeeper]').uncheck();   // advice is not a decision
    assert.match(await page.locator('[data-cat-card=support]').textContent(), /Owns the ticket queue/);
    assert.match(await page.locator('[data-cat-card=support]').textContent(), /Never refunds without a person/);
    assert.match(await page.locator('[data-cat-card=support]').textContent(), /codex · gpt-6-sol · high/);
    // Taking one on, renaming it and editing the words it is created with.
    await page.locator('[data-cat-toggle=social]').check();
    assert.equal(await page.locator('[data-cat-card=social]').evaluate(el => el.classList.contains('on')), true);
    await page.locator('[data-cat-name=support]').fill('Support desk');
    await page.locator('[data-cat-card=social] .cat-instructions summary').click();
    await page.locator('[data-cat-instructions=social]').fill('# Social\n\nDraft, never publish. Ask Ace first.\n');
    await page.locator('#onb-next').click();
    await page.locator('#onb-enroll').waitFor();
    assert.equal(puts.length, 3);
    assert.deepEqual(Object.keys(puts[2].selected).sort(), ['botops', 'coo', 'social', 'support']);
    assert.equal(puts[2].selected.support.instructions, '# Support\n\nAnswer the queue in the company voice.\n');
    assert.equal(puts[2].selected.support.display_name, 'Support desk');
    assert.equal(puts[2].selected.social.instructions, '# Social\n\nDraft, never publish. Ask Ace first.\n');
    assert.equal(puts[2].selected.social.template, 'social');

    // ---- d: this Mac. The enrollment file is the Settings flow; the commands keep <slug> literal.
    assert.equal(await page.locator('#onb-count').textContent(), 'Step 4 of 6');
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
    assert.equal(puts.length, 4);

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
    assert.equal(puts.length, 5);

    // ---- e: connect your agent. Optional: the button opens the same modal as the sidebar's plug.
    assert.equal(await page.locator('#onb-count').textContent(), 'Step 5 of 6');
    await page.locator('#onb-connect').click();
    await page.locator('dialog.connect-agent[open]').waitFor();
    await page.locator('dialog.connect-agent [data-close]').click();
    await page.waitForFunction(() => !document.querySelector('dialog.connect-agent'));
    await page.locator('#onb-next').click();
    await page.locator('#onb-finish').waitFor();
    assert.equal(puts.length, 6);

    // ---- f: review, then finish exactly once.
    assert.equal(await page.locator('#onb-count').textContent(), 'Step 6 of 6');
    const review = await page.locator('#onb-step').textContent();
    assert.match(review, /Initech Hub/);
    assert.match(review, /Ace/);
    assert.match(review, /Support desk/);
    assert.match(review, /Businesses/);
    assert.match(review, /Send anything, Spend money, Publish anything/);
    assert.match(review, /Computers\s*Ana's Mac, Cloud box online/);
    assert.doesNotMatch(review, /This Mac/);
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

    // ---- the progress screen: who builds what, the setup task, and Activate once the repo exists.
    assert.equal(await page.locator('#onb h1').textContent(), 'Setting up Initech');
    assert.match(await page.locator('[data-onb-bot=coo]').textContent(), /AceSet up automatically once a computer is online\./);
    assert.match(await page.locator('[data-onb-bot=botops]').textContent(), /Set up automatically once a computer is online\./);
    assert.match(await page.locator('[data-onb-bot=support]').textContent(), /BotOps is setting this up\./);
    assert.equal(await page.locator('[data-onb-bot=support] a').getAttribute('href'), '#/task/task-support');
    assert.equal(await page.locator('[data-onb-bot=support] [data-onb-activate]').count(), 1);
    assert.equal(await page.locator('[data-onb-bot=social] a').getAttribute('href'), '#/task/task-social');
    assert.equal(await page.locator('[data-onb-bot=social] [data-onb-activate]').count(), 0);
    assert.equal(await page.locator('#onb-machine-status').textContent(), "Ana's Mac, Cloud box online");
    // Finishing takes the setup entry out of the sidebar and puts the names on the app.
    assert.equal(await page.locator('#nav-welcome').evaluate(el => el.hidden), true);
    assert.equal(await page.title(), 'Initech Hub');
    await page.locator('[data-onb-bot=support] [data-onb-activate]').click();
    await page.waitForFunction(() => document.querySelectorAll('[data-onb-bot=support] [data-onb-activate]').length === 0);
    assert.deepEqual(definitions, [{path: '/api/v2/bots/support/definition', body: {status: 'active', expected_revision: 3}}]);

    // The setup task link opens the Tasks page with that task already in full.
    await page.locator('[data-onb-bot=support] a').click();
    await page.waitForFunction(() => location.hash === '#/task/task-support');
    await page.locator('#task-modal[open] .tmodal-title').waitFor();
    assert.equal(await page.locator('#task-modal .tmodal-title').textContent(), 'Set up Support desk');
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
      els => els.map(el => el.dataset.catCard)), ['botops', 'bookkeeper', 'inbox', 'social', 'support']);
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
    await phone.locator('#onb-next').click();
    await phone.locator('#onb-catalog').waitFor();
    assert.equal(await fits(), true);
    assert.equal(await phone.locator('#onb-catalog .cat-card').count(), 6);
    await phone.locator('#onb-next').click();
    await phone.locator('#onb-machine-ready').waitFor();
    await phone.locator('#onb-more summary').click();
    await phone.locator('#onb-enroll').waitFor();
    assert.equal(await fits(), true);

    // A viewer has no setup entry and lands on Tasks if they type the address.
    me.role = 'human';
    const viewer = await context.newPage();
    viewer.on('pageerror', e => errors.push(e.message));
    await viewer.goto('https://tico-ui.test/#/welcome');
    await viewer.waitForFunction(() => location.hash === '#/tasks');
    assert.equal(await viewer.locator('#onb-company').count(), 0);

    assert.deepEqual(errors, []);
    console.log('PASS: first-run wizard names, asks, picks, enrolls, finishes once and hands over to BotOps.');
  } finally { await browser.close(); }
})().catch(e => { console.error(e); process.exitCode = 1; });
