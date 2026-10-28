// The redesign's shell (ui/app/redesign.js, ui/app/strategy-budget.js) against fixtures shaped per the redesign CONTRACT
// (fixtures/redesign-*.json, the Acme example). Off: the sidebar, the phone bar and the old addresses are exactly today's.
// On: the new sidebar order, Goals and Message bots gone from it, old addresses redirected, the Strategy tabs with the
// Strategy Bot beside them (a rail on a desktop, a sheet on a phone), the Budget tab's edits sending the CONTRACT's
// requests, a task cap's 409 read as its message, and no "CEO Bot" anywhere. Phone first (390×844), then desktop.
// TICO_SCREENSHOT_DIR=<dir> saves review screenshots.
const {chromium} = require('playwright');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const {html, uiFile} = require('./support/page.cjs');
const {unrouted} = require('./support/routes.cjs');
const uiDir = path.join(__dirname, '..');
const fixture = name => JSON.parse(fs.readFileSync(path.join(__dirname, 'fixtures', name), 'utf8'));
const roster = fixture('redesign-roster.json');
const CAP_409 = fixture('redesign-task-cap-409.json');

const shots = process.env.TICO_SCREENSHOT_DIR;
const shot = async (page, name) => { if (shots) await page.screenshot({animations: 'disabled', path: path.join(shots, `redesign-${name}.png`)}); };
const PHONE = {width: 390, height: 844}, DESKTOP = {width: 1440, height: 900};

// Today's rail, in order (ui/index.html before the redesign): the redesign off must leave every one where it is.
const OFF_RAIL = ['side-update', 'overview', 'welcome', 'updates', 'tasks', 'assistant', 'botops', 'goals', 'docs', 'strategy',
  'meetings', 'nav-pins', 'side-section', 'nav-inboxes-section'];
const OFF_PHONE_BAR = ['Team', 'Search', 'Tasks', 'Updates', 'Support', 'More'];
const railKeys = page => page.$$eval('#side .side-scroll > *', els => els.map(el =>
  el.dataset.nav || (el.classList.contains('nav-row') && el.querySelector(':scope > [data-nav]')?.dataset.nav) || el.id || el.className.split(' ')[0]));
const shownRail = page => page.$$eval('#side .side-scroll a.nav-link, #side .side-scroll .rd-lib a.nav-link', els =>
  [...new Set(els)].filter(el => el.checkVisibility()).map(el => {
    const c = el.cloneNode(true); c.querySelectorAll('.nav-icon, .nav-badge, svg').forEach(x => x.remove());
    return c.textContent.replace(/\s+/g, ' ').trim();
  }));

async function open(browser, {redesign = false, route = '#/updates', viewport = PHONE, capsStatus = 200, goalsDelay = 0} = {}) {
  const page = await browser.newPage({viewport, serviceWorkers: 'block'});
  const errors = [], sent = [], goals = {asked: 0};
  page.on('pageerror', e => errors.push(e.message));
  // Each goals tree the app has read: counted one task after its body is read, so the code awaiting it has run.
  await page.addInitScript(() => {
    window.__treeRead = 0;
    const fetch0 = window.fetch;
    window.fetch = (...args) => fetch0(...args).then(r => {
      if (!String(args[0]).includes('/api/v2/goals/tree')) return r;
      const text = r.text.bind(r);
      r.text = () => text().finally(() => setTimeout(() => { window.__treeRead++; }, 0));
      return r;
    });
  });
  const config = {redesign};
  await page.route('**/*', async r => {
    const req = r.request(), url = new URL(req.url()), p = url.pathname, method = req.method();
    const json = (body, status = 200) => r.fulfill({status, contentType: 'application/json', body: JSON.stringify(body)});
    if (url.origin !== 'http://tico-ui.test') return r.abort();
    if (p === '/') return r.fulfill({contentType: 'text/html', body: html});
    const file = p.startsWith('/tico/ui/') ? uiFile(p.slice(9)) : p.startsWith('/vendor/') ? path.join(uiDir, p) : '';
    if (file && fs.existsSync(file)) return r.fulfill({contentType: file.endsWith('.js') ? 'application/javascript' : file.endsWith('.css') ? 'text/css' : file.endsWith('.woff2') ? 'font/woff2' : 'application/octet-stream', body: fs.readFileSync(file)});
    if (p === '/api/v2/events') return;
    if (method !== 'GET') sent.push([method, p + url.search, req.postData() ? req.postDataJSON() : null]);
    if (p === '/api/v2/config') return json(config);
    if (p === '/api/employees') return json(roster.employees);
    if (p === '/api/me') return json({id: 'ana', name: 'Ana Silva', email: 'ana@acme.example', role: 'owner', company_role: 'owner', cloud: true, config});
    if (p === '/api/humans') return json(roster.humans);
    if (p === '/api/status') return json({active: [], employees: []});
    if (p === '/api/v2/status') return json({bots: []});
    if (p === '/api/v2/goals/tree') goals.asked++;
    if (p === '/api/v2/goals/tree') return new Promise(done => setTimeout(done, goalsDelay)).then(() => json({goals: [{id: 'g-1', title: 'Ship the Acme portal', owner: 'company', parent_id: null, status: 'green', rank: 0, kpis: []}], owners: {}, other_kpis: [], proposals: []}));
    if (p === '/api/v2/goals/needs-you') return json({items: []});
    if (p === '/api/v2/strategy') return json({current: null, bets: [], may_edit: true});
    if (p === '/api/v2/conversations') return json({conversations: []});
    if (p === '/api/v2/bots/goal-manager/routines') return json({routines: []});
    if (p === '/api/v2/listening/destinations') return json({destinations: [{key: 'leads', category: 'leads', threshold: 0.75, receiver: 'bot:release', source: 'settings'}],
      categories: [{id: 'leads', label: 'Leads'}], receivers: [{actor: 'bot:release', name: 'Release Manager'}]});
    if (p === '/api/v2/usage/limits') return json(fixture('redesign-usage-limits.json'));
    if (p === '/api/v2/task-caps') return method === 'GET' ? json(fixture('redesign-task-caps.json'), capsStatus) : json({ok: true});
    if (p.startsWith('/api/v2/usage/')) return json({ok: true});
    if (p === '/api/v2/settings/redesign') return json({enabled: !!req.postDataJSON()?.enabled});
    if (p === '/api/v2/tasks' && method === 'POST') return json(CAP_409, 409);
    if (p === '/api/v2/market/graph') return json({entities: [], edges: []});
    if (p === '/api/v2/market/entities') return json({entities: [], total: 0});
    if (p === '/api/v2/librarian/setup') return json({market: null});
    return json(unrouted(p));
  });
  await page.goto('http://tico-ui.test/' + route);
  await page.waitForFunction(() => typeof S !== 'undefined' && S.me && (S.emps || []).length);
  return {page, errors, sent, goals};
}
const hashSoon = (page, want) => page.waitForFunction(w => location.hash === w, want).then(() => true, () => false);
const noSideScroll = page => page.evaluate(() => document.documentElement.scrollWidth <= innerWidth);

(async () => {
  const browser = await chromium.launch({channel: process.env.TICO_BROWSER_CHANNEL ?? 'chrome', headless: true});
  try {
    // Off, on a phone and a desktop: the rail, the phone bar and the old addresses are today's, and nothing new shows.
    for (const viewport of [PHONE, DESKTOP]) {
      const tag = 'off ' + viewport.width;
      const {page, errors} = await open(browser, {viewport});
      await page.locator('#tree li').first().waitFor();
      assert.deepEqual(await railKeys(page), OFF_RAIL, tag + ': the rail keeps its order');
      assert.equal(await page.getAttribute('a[data-nav="strategy"]', 'href'), '#/strategy', tag + ': Strategy goes where it went');
      assert.deepEqual(await page.locator('#mobile-nav .mobile-nav-label').allInnerTexts(), OFF_PHONE_BAR, tag + ': the phone bar');
      assert.equal(await page.locator('[data-nav="automations"], [data-nav="library"], .rd-lib, #sbot, #sbot-fab').count(), 0, tag + ': nothing new');
      assert.equal(await page.locator('#tree [data-org="b:mail-sorter"]').count(), 1, tag + ': message bots keep their group');
      if (viewport === DESKTOP) {
        assert.deepEqual(await shownRail(page), ['Overview', 'Updates', 'Tasks', 'CEO Bot', 'BotOps', 'Goals', 'Docs', 'Strategy', 'Meetings'], tag + ': the rail reads as today');
        await page.evaluate(() => { location.hash = '#/goals'; });
        await page.locator('#goal-manager-panel').waitFor();
        assert.equal(await page.evaluate(() => location.hash), '#/goals', tag + ': Goals stays its own page, with its CEO Bot rail');
        await page.evaluate(() => { location.hash = '#/automations'; });
        assert.ok(await hashSoon(page, '#/updates'), tag + ': #/automations is unknown, so Updates');
        await page.evaluate(() => { location.hash = '#/settings'; });
        await page.locator('#settings-redesign').waitFor();
        assert.equal(await page.locator('[data-settings-tab="listening"]').count(), 1, tag + ': Settings keeps Listening');
        assert.equal(await page.locator('#redesign-switch').isChecked(), false, tag + ': the owner\'s switch reads off');
      }
      assert.deepEqual(errors, [], tag + ': no page errors');
      await page.close();
    }

    // On, phone first: the new rail, old addresses redirected, the Strategy tabs and the Strategy Bot as a sheet.
    {
      const tag = 'on phone';
      // The goals tree answers slowly: #/goals/g-1 is left before it arrives, as a person tapping on would.
      const {page, errors, goals} = await open(browser, {redesign: true, goalsDelay: 400});
      await page.locator('#tree li').first().waitFor();
      assert.deepEqual(await railKeys(page), ['side-update', 'overview', 'welcome', 'strategy', 'updates', 'tasks', 'assistant', 'automations',
        'library', 'rd-lib', 'botops', 'goals', 'nav-pins', 'side-section', 'nav-inboxes-section'], tag + ': the new order');
      assert.equal(await page.getAttribute('a[data-nav="automations"]', 'href'), '#/automations', tag + ': Automations');
      for (const helper of ['b:automations-bot', 'b:mail-sorter', 'b:botops', 'b:librarian', 'g:__message_bots'])
        assert.equal(await page.locator(`#tree [data-org="${helper}"]`).count(), 0, `${tag}: ${helper} is off the Team list`);
      assert.equal(await page.locator('#tree [data-org="b:eng-lead"]').count(), 1, tag + ': the Team list keeps the chart');
      assert.equal(await page.getAttribute('a[data-nav="strategy"]', 'href'), '#/strategy/market', tag + ': Strategy opens on Market');
      assert.deepEqual(await page.locator('#mobile-nav .mobile-nav-label').allInnerTexts(), OFF_PHONE_BAR, tag + ': the phone bar is the mock\'s');
      for (const [from, to] of [['#/goals', '#/strategy/goals'], ['#/goals/g-1', '#/strategy/goals/g-1'], ['#/settings/listening', '#/strategy/market/listening']]) {
        await page.evaluate(h => { location.hash = h; }, from);
        assert.ok(await hashSoon(page, to), `${tag}: ${from} lands on ${to}`);
      }
      await page.locator('[data-rdm-settings]').click();
      await page.locator('[data-listen-dest="leads"]').waitFor();
      // Every slow tree asked for has been read and acted on: the goal left behind must not open over Listening.
      await page.waitForFunction(n => window.__treeRead >= n, goals.asked);
      assert.equal(await page.evaluate(() => location.hash), '#/strategy/market/listening', tag + ': a goal left before it loaded keeps off the address');
      assert.equal(await page.locator('#goal-panel[open]').count(), 0, tag + ': and does not open');
      assert.equal(await page.locator('.mkt-views [data-market-view="listening"][aria-current="page"]').count(), 1, tag + ': Listening is a Market view');
      await page.evaluate(() => { location.hash = '#/automations'; });
      await page.locator('#au-root, #automations-root').first().waitFor({state: 'attached'});
      assert.equal(await page.locator('#side a[data-nav="automations"].cur').count(), 1, tag + ': Automations is current');
      await page.evaluate(() => { location.hash = '#/strategy/org'; });
      await page.locator('.rd-org').waitFor();
      assert.deepEqual(await page.locator('.strat-tabs a').allInnerTexts(), ['Market', 'Strategy', 'Org', 'Goals', 'Budget'], tag + ': the tabs');
      const org = await page.locator('.rd-org').innerText();
      assert.ok(org.includes('Builder'), tag + ': Org lists the chart');
      assert.ok(!org.includes('Automations Bot') && !org.includes('BotOps'), tag + ': helpers are off the Org chart');
      assert.ok(await page.locator('#sbot-fab').isVisible(), tag + ': the Strategy Bot is a button');
      assert.equal(await page.locator('#sbot').evaluate(el => el.getBoundingClientRect().top >= innerHeight), true, tag + ': its sheet is closed');
      await page.locator('#sbot-fab').click();
      await page.waitForFunction(() => Math.abs(document.querySelector('#sbot').getBoundingClientRect().bottom - innerHeight) < 2);
      assert.equal(await page.locator('#sbot h2').innerText(), 'Strategy Bot', tag + ': named Strategy Bot');
      await page.locator('#sbot .gm-form .p-text').waitFor();
      assert.deepEqual(await page.locator('#sbot .gm-form').evaluate(form => {
        const ask = form.querySelector('.ask'), pill = form.querySelector('.p-pill').getBoundingClientRect();
        const send = form.querySelector('.p-send').getBoundingClientRect();
        return [getComputedStyle(ask).borderTopWidth, pill.height <= 46, send.right <= pill.right && send.left > pill.left + pill.width / 2];
      }), ['0px', true, true], tag + ': the composer is one line, send inside on the right, no outer box');
      await shot(page, 'phone-strategy-bot');
      await page.locator('.sbot-close').click();
      await page.evaluate(() => { location.hash = '#/strategy/budget'; });
      await page.locator('[data-bd-cap]').first().waitFor();
      assert.ok(await noSideScroll(page), tag + ': no sideways scroll');
      await shot(page, 'phone-budget');
      await page.locator('[data-bd-cap="1"]').click();
      assert.ok(await page.locator('dialog.rd-sheet[open]').isVisible(), tag + ': the cap editor is a sheet');
      await shot(page, 'phone-cap-sheet');
      await page.locator('dialog.rd-sheet [data-close]').first().click();
      await page.locator('dialog[open]').waitFor({state: 'detached'});
      await page.locator('[data-bd-spend="bot:builder"]').click();
      await page.locator('dialog.rd-sheet[open] .bd-window').first().waitFor();
      assert.ok(await page.locator('dialog.rd-sheet[open] .bd-window').evaluateAll(rows => rows.every(r => r.scrollWidth <= r.clientWidth)), tag + ': the spend sheet\'s rows fit a phone');
      await shot(page, 'phone-spend-sheet');
      await page.locator('dialog.rd-sheet [data-close]').first().click();
      await page.locator('dialog[open]').waitFor({state: 'detached'});
      await page.evaluate(() => { location.hash = '#/strategy/goals'; });
      await page.locator('#goal-body').waitFor();
      assert.equal(await page.locator('#goal-manager-panel').count(), 0, tag + ': Goals has no rail of its own');
      assert.equal(await page.locator('#goal-tree .gt-sep').count(), 0, tag + ': helpers are off Goals too');
      assert.ok(!(await page.locator('body').innerText()).includes('CEO Bot'), tag + ': no "CEO Bot" anywhere');
      await page.locator('#mobile-more').click();
      await shot(page, 'phone-sidebar');
      assert.deepEqual(errors, [], tag + ': no page errors');
      await page.close();
    }

    // On, desktop: the rail reads as the mock, the Strategy Bot sits beside every tab, Budget's edits send the CONTRACT's
    // requests, and a task cap's 409 reads as its message.
    {
      const tag = 'on desktop';
      const {page, errors, sent} = await open(browser, {redesign: true, viewport: DESKTOP, route: '#/strategy/budget'});
      await page.locator('[data-bd-cap]').first().waitFor();
      const shown = await shownRail(page);
      assert.deepEqual(shown, ['Overview', 'Strategy', 'Updates', 'Tasks', 'Automations', 'Library', 'Docs', 'Meetings', 'BotOps'], tag + ': the rail, with no Strategy Bot entry');
      assert.equal(await page.locator('#tree [data-org="b:goal-manager"]').count(), 1, tag + ': the Strategy Bot stays on the Team list');
      assert.ok(!shown.includes('Goals'), tag + ': Goals left the rail');
      assert.equal(await page.locator('#nav-inboxes-section').isVisible(), false, tag + ': Message bots hidden');
      assert.equal(await page.locator('#side a[data-nav="strategy"].cur').count(), 1, tag + ': Strategy is current');
      assert.ok(await page.locator('#sbot').isVisible(), tag + ': the Strategy Bot rail');
      assert.equal(await page.locator('#sbot-fab').isVisible(), false, tag + ': no button on a desktop');
      const main = await page.locator('#main').boundingBox(), rail = await page.locator('#sbot').boundingBox();
      assert.ok(main.x + main.width <= rail.x + 1, tag + ': the page gives the rail its room');
      assert.deepEqual(await page.locator('.bd-cap').allInnerTexts(), ['10/10 · 3 rejected', '2/5 · 1 closed', '0 · blocked'], tag + ': cap counts');
      const amount = sel => page.locator(sel + ' .bd-amt').innerText();
      assert.equal(await amount('[data-bd-spend="bot:builder"]'), '$5.70 / $6 · 30m', tag + ': spend per bot, by the window that binds');
      assert.equal(await amount('[data-bd-spend="bot:goal-manager"]'), '$14 / $20 · day', tag + ': a day window binding says day');
      assert.equal(await amount('[data-bd-spend="company"]'), '$27.38 / $80 · 30m', tag + ': cents only when there are any');
      assert.equal(await amount('[data-bd-spend="bot:eng-lead"]'), '$2.50 / $3 · hour', tag + ': an hour limit not yet migrated still shows and binds');
      assert.deepEqual(await page.locator('.bd-amt').first().evaluate(el => [getComputedStyle(el).fontVariantNumeric, getComputedStyle(el).fontFamily === getComputedStyle(document.body).fontFamily]),
        ['tabular-nums', true], tag + ': tabular numerals in the body font');
      assert.ok((await page.locator('[data-bd-spend="group:eng"]').innerText()).includes('Engineering pool'), tag + ': group spend');
      assert.ok((await page.locator('[data-bd-spend="bot:release"]').innerText()).includes('Paused'), tag + ': a held bot says Paused');
      await shot(page, 'desktop-budget');

      // Edit a cap.
      await page.locator('[data-bd-cap="1"]').click();
      await page.fill('dialog[open] input[name="per_day"]', '7');
      await shot(page, 'desktop-cap-editor');
      await page.click('dialog[open] [type=submit]');
      await page.locator('dialog[open]').waitFor({state: 'detached'});
      // No cap.
      await page.locator('[data-bd-cap="2"]').click();
      await page.check('dialog[open] input[name="nocap"]');
      assert.equal(await page.locator('dialog[open] input[name="per_day"]').isDisabled(), true, tag + ': No cap turns the number off');
      await page.click('dialog[open] [type=submit]');
      await page.locator('dialog[open]').waitFor({state: 'detached'});
      // Add one: the manager choices are the ones above the sender.
      await page.click('[data-bd-add]');
      await page.selectOption('dialog[open] select[name="sender"]', 'bot:builder');
      assert.deepEqual(await page.locator('dialog[open] select[name="receiver"] option').evaluateAll(o => o.map(x => x.value)), ['bot:eng-lead', 'person:ana'], tag + ': managers above');
      await page.selectOption('dialog[open] select[name="receiver"]', 'bot:eng-lead');
      await page.fill('dialog[open] input[name="per_day"]', '4');
      await page.click('dialog[open] [type=submit]');
      await page.locator('dialog[open]').waitFor({state: 'detached'});
      // A bot's spend, then a group pool; a bad amount is refused in the editor.
      await page.locator('[data-bd-spend="bot:builder"]').click();
      assert.equal(await page.inputValue('dialog[open] input[name="per_30m_usd"]'), '6', tag + ': the editor reads the bot\'s own limit');
      assert.equal(await page.locator('dialog[open] .bd-window').count(), 4, tag + ': four windows');
      assert.equal(await page.locator('dialog[open] .bd-nolimit input[role="switch"]').count(), 4, tag + ': each with No limit');
      await shot(page, 'desktop-spend-editor');
      await page.fill('dialog[open] input[name="per_30m_usd"]', 'lots');
      await page.click('dialog[open] [type=submit]');
      assert.match(await page.locator('dialog[open] [data-error]').innerText(), /Per 30 min/, tag + ': a bad amount says which');
      await page.fill('dialog[open] input[name="per_30m_usd"]', '7.5');
      await page.check('dialog[open] input[name="monthly_usd_none"]');
      assert.equal(await page.locator('dialog[open] input[name="monthly_usd"]').isDisabled(), true, tag + ': No limit turns the amount off');
      await page.click('dialog[open] [type=submit]');
      await page.locator('dialog[open]').waitFor({state: 'detached'});
      // An hour limit not yet migrated is its own row and goes back as it was.
      await page.locator('[data-bd-spend="bot:eng-lead"]').click();
      assert.deepEqual(await page.locator('dialog[open] .bd-window > span:first-child').allInnerTexts(),
        ['Per 30 min', 'Per hour', 'Per day', 'Per week', 'Per month'], tag + ': the hour row');
      assert.equal(await page.inputValue('dialog[open] input[name="hourly_usd"]'), '3', tag + ': with its amount');
      await page.fill('dialog[open] input[name="daily_usd"]', '45');
      await page.click('dialog[open] [type=submit]');
      await page.locator('dialog[open]').waitFor({state: 'detached'});
      await page.locator('[data-bd-spend="group:eng"]').click();
      await page.fill('dialog[open] input[name="daily_usd"]', '250');
      await page.click('dialog[open] [type=submit]');
      await page.locator('dialog[open]').waitFor({state: 'detached'});
      assert.deepEqual(sent.filter(([m, p]) => p.startsWith('/api/v2/task-caps') || p.startsWith('/api/v2/usage/')), [
        ['PUT', '/api/v2/task-caps', {sender: 'bot:release', receiver: 'person:ana', per_day: 7}],
        ['DELETE', '/api/v2/task-caps?sender=bot%3Abuilder&receiver=person%3Aana', {}],
        ['PUT', '/api/v2/task-caps', {sender: 'bot:builder', receiver: 'bot:eng-lead', per_day: 4}],
        ['PUT', '/api/v2/usage/limits/builder', {per_30m_usd: 7.5, daily_usd: 30, weekly_usd: 120, monthly_usd: null}],
        ['PUT', '/api/v2/usage/limits/eng-lead', {per_30m_usd: 8, hourly_usd: 3, daily_usd: 45, weekly_usd: 180, monthly_usd: 600}],
        ['PUT', '/api/v2/usage/pools/groups/eng', {per_30m_usd: 40, daily_usd: 250, weekly_usd: 800, monthly_usd: 2500}],
      ], tag + ': the requests');

      // A task cap's 409: the message is what a person reads, in a toast's words and in the bot's chat.
      const said = await page.evaluate(() => post('/v2/tasks', {title: 'Check the Acme release'}).then(() => '', e => e.message));
      assert.equal(said, CAP_409.message, tag + ': the 409 reads as its message');
      const chat = await page.evaluate(m => {
        const div = document.createElement('div');
        div.innerHTML = v2MessageHTML({id: 'm1', from_actor: 'bot:eng-lead', body: 'Sending the review to Ana.', created: new Date().toISOString(),
          run: {id: 'r1', status: 'done', did: [{kind: 'refused', rule: 'task_cap', text: m}]}});
        return div.textContent.replace(/\s+/g, ' ');
      }, CAP_409.message);
      assert.ok(/refused ·\s*Ana takes 10 tasks a day from Engineering Lead and 10 are open\. Nothing was queued\./.test(chat), tag + ': the chat shows the refusal: ' + chat);

      for (const [hash, tab] of [['#/strategy/market/listening', 'Market'], ['#/strategy', 'Strategy'], ['#/strategy/lenses', 'Strategy'], ['#/strategy/goals', 'Goals'], ['#/strategy/org', 'Org']]) {
        await page.evaluate(h => { location.hash = h; }, hash);
        await page.waitForFunction(t => document.querySelector('.strat-tabs a.cur')?.textContent === t, tab);
        assert.ok(await page.locator('#sbot').isVisible(), `${tag}: the Strategy Bot beside ${hash}`);
        if (hash === '#/strategy/goals') await shot(page, 'desktop-goals');
        if (hash === '#/strategy') await shot(page, 'desktop-strategy-bot');
        if (hash === '#/strategy/org') await shot(page, 'desktop-org');
        if (hash === '#/strategy/market/listening') await shot(page, 'desktop-listening');
      }
      await page.evaluate(() => { location.hash = '#/tasks'; });
      await page.locator('#sbot').waitFor({state: 'detached'});
      assert.ok(!(await page.locator('body').innerText()).includes('CEO Bot'), tag + ': no "CEO Bot" anywhere');
      await page.evaluate(() => { location.hash = '#/settings'; });
      await page.locator('#redesign-switch').waitFor();
      assert.equal(await page.locator('[data-settings-tab="listening"]').count(), 0, tag + ': Listening left Settings');
      await shot(page, 'desktop-settings');
      assert.deepEqual(errors, [], tag + ': no page errors');
      await page.close();
    }

    // The owner's switch sends the setting and reloads into the chosen design.
    {
      const {page, sent} = await open(browser, {viewport: DESKTOP, route: '#/settings'});
      await page.locator('#redesign-switch').waitFor();
      await Promise.all([page.waitForEvent('load'), page.locator('#redesign-switch').check()]);
      assert.deepEqual(sent.filter(([, p]) => p === '/api/v2/settings/redesign'), [['PUT', '/api/v2/settings/redesign', {enabled: true}]], 'switch: PUT');
      await page.close();
    }

    // Caps not built on the server yet (404): Budget still draws spend and says so for caps.
    {
      const {page, errors} = await open(browser, {redesign: true, viewport: DESKTOP, route: '#/strategy/budget', capsStatus: 404});
      await page.locator('[data-bd-spend="bot:builder"]').waitFor();
      assert.equal(await page.locator('[data-bd-cap]').count(), 0, '404: no caps listed');
      assert.deepEqual(errors, [], '404: no page errors');
      await page.close();
    }
  } finally {
    await browser.close();
  }
  console.log('redesign-shell: ok');
})().catch(e => { console.error(e); process.exit(1); });
