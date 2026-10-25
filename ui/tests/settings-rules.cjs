// Settings > Rules, What wakes a bot (ui/app/settings-rules.js). Guards: who gets Add, Edit and the switch (the server's
// can_change; a member gets none); an edit and a switch send the row's revision and the row reads back what was saved;
// a rule that makes an always-wake event wait shows the server's 422 in the form, not a toast; the task filter route
// asks for that task's rows and has its way back; at phone width nothing scrolls sideways; and the Releases card's
// Release now shows only to those the server lets ask (`can_release`). Fixtures only.
const {chromium} = require('playwright');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const {html, uiFile} = require('./support/page.cjs');
const {unrouted} = require('./support/routes.cjs');

const FLOOR_422 = 'Person message always wakes the bot: a rule cannot make it wait';
const builtins = [
  {id: 'builtin:person_message', built_in: true, scope_kind: 'builtin', scope_id: '', group: 'always', event: 'person_message',
    words: 'a person messages it', then: 'wake', enabled: true, runs_7d: 14, no_op_rate_7d: 0.1},
  {id: 'builtin:comment', built_in: true, scope_kind: 'builtin', scope_id: '', group: 'wake', event: 'comment',
    words: 'a comment on its task', then: 'wake', enabled: true, runs_7d: 30, no_op_rate_7d: 0.6},
];
function fixture(role) {
  const change = role === 'owner';
  return [
    ...builtins.map(r => ({...r})),
    {id: 'r-team', scope_kind: 'team', scope_id: '', event: 'comment', when: {actor: 'bot'}, then: 'note', params: {}, note: '',
      enabled: true, revision: 3, can_change: change, runs_7d: 8, no_op_rate_7d: 0.5},
    {id: 'r-bot', scope_kind: 'bot', scope_id: 'ops', event: 'comment', when: {}, then: 'batch', params: {}, note: '',
      enabled: true, revision: 1, can_change: change, runs_7d: 0, no_op_rate_7d: null},
  ];
}
// What a bot's own listing adds (backend/rules.py profile_listing): its profile's rows, built-in and read-only.
const profileRows = [{id: 'profile_lead_blocker', scope_kind: 'bot', scope_id: 'ops', event: 'blocker', when: {}, then: 'wake', params: {},
  enabled: true, built_in: true, group: 'profile', profile: 'lead', words: 'a blocker needs it', can_change: false, runs_7d: 1, no_op_rate_7d: 0}];
const taskRow = {id: 'r-task', scope_kind: 'task', scope_id: 't-acme', event: 'comment', when: {}, then: 'ignore', params: {}, note: '',
  enabled: true, revision: 1, can_change: true, runs_7d: 2, no_op_rate_7d: 1};

async function open(browser, role, hash = '#/settings/rules', viewport = {width: 1440, height: 900}) {
  const page = await browser.newPage({viewport, serviceWorkers: 'block'});
  const errors = [], writes = [], lists = [];
  const rules = fixture(role);
  page.on('pageerror', e => errors.push(e.message));
  await page.route('**/*', route => {
    const req = route.request(), url = new URL(req.url()), p = url.pathname;
    const json = (body, status = 200) => route.fulfill({status, contentType: 'application/json', body: JSON.stringify(body)});
    if (url.origin !== 'https://tico-ui.test') return route.abort();
    const ui = p.match(/\/tico\/ui\/((?:app\/|styles\/)?[^/]+\.(?:js|css))$/);
    if (ui && fs.existsSync(uiFile(ui[1])))
      return route.fulfill({contentType: ui[1].endsWith('.css') ? 'text/css' : 'application/javascript', body: fs.readFileSync(uiFile(ui[1]), 'utf8')});
    if (p.endsWith('.js')) return route.fulfill({contentType: 'application/javascript', body: ''});
    if (p === '/') return route.fulfill({contentType: 'text/html', body: html});
    const config = {version: '0.1.0', app_name: 'Tico'};
    if (p === '/api/me') return json({id: role === 'owner' ? 'ana' : 'cara', role: role === 'owner' ? 'owner' : 'human', mover: role === 'owner',
      name: 'Ana', email: 'ana@acme.example', cloud: true, registered: true, config});
    if (p === '/api/v2/config') return json(config);
    if (p === '/api/employees') return json([{name: 'ops', display_name: 'Ops', status: 'active', can_manage: role === 'owner'}]);
    if (p === '/api/status') return json({cloud: true, active: [], queued: [], recent_runs: [], keeper_alive: true, health_issues: [], schedules: []});
    if (p === '/api/v2/status') return json({bots: []});
    if (p === '/api/v2/tasks/t-acme') return json({task: {id: 't-acme', title: 'Renew the acme.example domain'}});
    if (p === '/api/v2/release-schedule') return json({on: true, times: ['10:00'], bot: '', writer: '', zone: 'UTC', release_manager: 'ops',
      technical_writer: '', next: null, last: null, pending: 2, can_change: role === 'owner', can_release: role === 'owner'});
    if (p === '/api/v2/release/now') { writes.push({path: p, body: req.postDataJSON()}); return json({sent: true, reason: '', task: 't-rel', tickets: 2}); }
    if (p === '/api/v2/rules' && req.method() === 'GET') {
      lists.push(url.search);
      const kind = url.searchParams.get('scope_kind');
      const rows = kind === 'task' ? [{...taskRow}] : kind === 'builtin' ? builtins : kind === 'bot' ? [...profileRows, rules.find(r => r.id === 'r-bot')] : rules;
      return json({rules: rows, events: ['person_message', 'comment'], outcomes: ['wake', 'note', 'batch', 'ignore'], scopes: [], more: false});
    }
    if (p === '/api/v2/rules') {
      const body = req.postDataJSON();
      writes.push({path: p, body});
      if (body.event === 'person_message' && body.then !== 'wake') return json({error: {detail: FLOOR_422, code: 'invalid'}}, 422);
      return json({rule: {...body, id: 'r-new', revision: 1, enabled: body.on}});
    }
    const one = p.match(/^\/api\/v2\/rules\/([^/]+)$/);
    if (one) {
      const body = req.postDataJSON(), r = rules.find(x => x.id === one[1]);
      writes.push({path: p, body});
      if (body.expected_revision !== r.revision) return json({error: {detail: 'Someone else changed this rule', code: 'conflict'}}, 409);
      const {expected_revision, on, ...rest} = body;
      Object.assign(r, rest, on == null ? {} : {enabled: on}, {revision: r.revision + 1});
      const {runs_7d, no_op_rate_7d, can_change, ...answer} = r;   // a write answers the row without its figures
      return json({rule: answer});
    }
    if (p.endsWith('/watch') || p === '/api/v2/events') return route.fulfill({contentType: 'text/event-stream', body: ': fixture\n\n'});
    return json(unrouted(p));
  });
  await page.goto('https://tico-ui.test/' + hash);
  await page.locator('#set-rules [data-rules-list]').waitFor();
  return {page, errors, writes, lists};
}
const row = (page, id) => page.locator(`[data-rule="${id}"]`);

(async () => {
  const browser = await chromium.launch({headless: true, channel: process.env.TICO_BROWSER_CHANNEL === undefined ? 'chrome' : process.env.TICO_BROWSER_CHANNEL || undefined});
  try {
    {
      // A member reads the rows: no Add, no switch, no Edit; the built-ins never have controls.
      const {page, errors} = await open(browser, 'member');
      await row(page, 'r-team').waitFor();
      assert.equal(await page.locator('[data-rule-new]').count(), 0);
      assert.equal(await page.locator('#set-rules [data-rule-on], #set-rules [data-rule-edit]').count(), 0);
      await page.locator('#set-release [data-release-pending]').waitFor();
      assert.equal(await page.locator('[data-release-now]').count(), 0, 'no Release now without can_release');
      assert.deepEqual(errors, []);
      await page.close();
    }
    {
      const {page, errors, writes} = await open(browser, 'owner');
      await row(page, 'r-team').waitFor();
      assert.equal(await page.locator('[data-rule-new]').count(), 1);
      assert.equal(await row(page, 'builtin:comment').locator('[data-rule-on], [data-rule-edit]').count(), 0, 'a built-in has no controls');
      // Edit round-trip: the row's revision goes with the write and the row reads back the new outcome.
      await row(page, 'r-team').locator('[data-rule-edit]').click();
      const form = page.locator('[data-rule-form]');
      await form.locator('select[name=then]').selectOption('batch');
      await form.locator('button[type=submit]').click();
      await form.waitFor({state: 'detached'});
      assert.match(await row(page, 'r-team').locator('[data-rule-text]').innerText(), /THEN batch it$/);
      assert.equal(writes[0].path, '/api/v2/rules/r-team');
      assert.equal(writes[0].body.expected_revision, 3);
      assert.equal(writes[0].body.then, 'batch');
      // The switch sends the revision the edit answered, so a second write is not refused as stale.
      await row(page, 'r-team').locator('[data-rule-on]').uncheck({force: true});
      await page.waitForFunction(() => document.querySelector('[data-rule="r-team"] [data-rule-status]')?.textContent === 'Saved');
      assert.deepEqual(writes[1].body, {expected_revision: 4, on: false});
      assert.equal(await row(page, 'r-team').locator('[data-rule-on]').isChecked(), false);
      assert.equal(await row(page, 'r-team').locator('[data-rule-usage]').innerText(), '8 runs · 50% no-op', 'the figures survive a write');
      // A rule that makes an always-wake event wait: the server's words in the form, which stays open.
      await page.locator('[data-rule-new]').click();
      await form.locator('select[name=event]').selectOption('person_message');
      await form.locator('select[name=then]').selectOption('ignore');
      await form.locator('button[type=submit]').click();
      await page.waitForFunction(text => document.querySelector('[data-rule-error]')?.textContent === text, FLOOR_422);
      assert.equal(await form.isVisible(), true);
      assert.equal(writes[2].body.scope_kind, 'team');
      await form.locator('[data-close]').click();
      // Release now asks once and says what happened.
      await page.locator('#set-release [data-release-now]').click();
      await page.waitForFunction(() => /2 tickets/.test(document.querySelector('#set-release [data-release-status]')?.textContent || ''));
      assert.deepEqual(writes.at(-1), {path: '/api/v2/release/now', body: {}});
      assert.deepEqual(errors, []);
      await page.close();
    }
    {
      // The task modal's link: that task's rows only, named, with Open task and All rules as the ways out.
      const {page, errors, lists} = await open(browser, 'member', '#/settings/rules?task=t-acme');
      await row(page, 'r-task').waitFor();
      assert.ok(lists.some(q => q.includes('scope_kind=task') && q.includes('scope_id=t-acme')), lists.join(' | '));
      assert.equal(await page.locator('#set-rules [data-rule]').count(), 1, 'the built-ins are read for their words only');
      await page.waitForFunction(() => /Renew the acme\.example domain/.test(document.querySelector('[data-rules-filter]')?.textContent || ''));
      assert.equal(await page.locator('[data-rules-filter] a[href="#/task/t-acme"]').count(), 1);
      await page.locator('[data-rules-all]').click();
      await row(page, 'r-team').waitFor();
      assert.equal(await page.locator('[data-rules-filter]').count(), 0);
      assert.deepEqual(errors, []);
      await page.close();
    }
    {
      // A bot's rules (the profile picker's Wake rules link): its profile rows read-only under the profile, its own editable.
      const {page, errors, lists} = await open(browser, 'owner', '#/settings/rules?bot=ops');
      await row(page, 'profile_lead_blocker').waitFor();
      assert.ok(lists.some(q => q.includes('scope_kind=bot') && q.includes('scope_id=ops')), lists.join(' | '));
      assert.equal(await page.locator('[data-rule-profile="lead"]').count(), 1);
      assert.equal(await row(page, 'profile_lead_blocker').locator('[data-rule-on], [data-rule-edit]').count(), 0);
      assert.equal(await row(page, 'r-bot').locator('[data-rule-edit]').count(), 1);
      assert.equal(await page.locator('[data-rules-filter] a[href="#/bot/ops/settings"]').count(), 1);
      assert.deepEqual(errors, []);
      await page.close();
    }
    {
      // Phone width: the rows wrap; nothing in the page scrolls sideways.
      const {page, errors} = await open(browser, 'owner', '#/settings/rules', {width: 390, height: 844});
      await row(page, 'r-team').waitFor();
      const wide = await page.evaluate(() => [...document.querySelectorAll('#set-rules-card, #set-rules-card .wr-row, #set-rules-card .settings-bots-filters')]
        .filter(el => el.getBoundingClientRect().right > innerWidth + 1).map(el => el.className || el.id));
      assert.deepEqual(wide, []);
      assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1), 'no sideways scroll');
      assert.deepEqual(errors, []);
      await page.close();
    }
  } finally { await browser.close(); }
  console.log('settings-rules ok');
})().catch(error => { console.error(error); process.exit(1); });
