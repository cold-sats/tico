// Findings from the v0.3.2 page sweep, kept fixed. Market follows the light theme (no dark room); Tools names bots by
// their display names and credentials in words; the Assistant bot is never called by the product's name; "Add tags" in a
// task's properties reads whole; Meetings shows Granola once (its row, no tile beside it) and its filters are not cut off.
// Fixtures only, no network.
const {chromium} = require('playwright');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const {html, uiFile} = require('./support/page.cjs');

const ago = minutes => new Date(Date.now() - minutes * 6e4).toISOString();
// The product's name doubling as the assistant's (an older demo): the UI says "Assistant".
const CONFIG = {app_name: 'Tico', assistant_name: 'Tico', assistant_bot: 'coo', company_name: 'Acme'};
const BOTS = [{name: 'coo', display_name: 'Tico', host: 'keeper', status: 'active', can_chat: true, org_parent: ''},
  {name: 'sales', display_name: 'Account Executive', host: 'keeper', status: 'active', can_chat: true, org_parent: 'p:ana'}];
const TOOLS = [
  {service: 'close-crm', title: 'Close CRM', kind: 'api', writes: 'never', status: 'not_configured', bots: [],
    credentials: ['CLOSE_API_KEY in secrets/close-calls.env on one runner computer']},
  {service: 'github', title: 'GitHub', kind: 'cli', writes: 'approval', status: 'ready', bots: ['coo', 'sales'],
    credentials: ['none to manage — a short-lived GitHub App token per bot']},
  {service: 'postgres', title: 'PostgreSQL', kind: 'sql', writes: 'never', status: 'not_configured', bots: [],
    credentials: ['DB_<NAME>_URL — the read-only connection string']},
];
const meeting = (id, title, minutes) => ({id, title, source: 'zoom', kind: 'meeting', status: 'done', started: ago(minutes), created: ago(minutes),
  duration_ms: 1800000, participants: [{name: 'Ana Rivera'}, {name: 'Bartholomew Okafor-Whitfield'}], outbox: {doc: [], task: [], feature: []}});

async function open(browser, viewport, theme = 'dark') {
  const phone = viewport.width < 760;
  const context = await browser.newContext({viewport, serviceWorkers: 'block', colorScheme: theme, hasTouch: phone, isMobile: phone});
  await context.addInitScript(t => { try { localStorage.setItem('tico.theme', t); } catch {} }, theme);
  const page = await context.newPage();
  const errors = [];
  page.on('pageerror', error => errors.push(error.message));
  await page.route('**/*', route => {
    const url = new URL(route.request().url()), p = url.pathname;
    const json = body => route.fulfill({contentType: 'application/json', body: JSON.stringify(body)});
    if (url.origin !== 'https://tico-ui.test') return route.abort();
    const vendor = p.match(/^\/vendor\/((?:fonts\/)?[\w.-]+)$/);
    if (vendor && fs.existsSync(uiFile('vendor/' + vendor[1]))) return route.fulfill({path: uiFile('vendor/' + vendor[1])});
    const ui = p.match(/\/tico\/ui\/((?:app\/|styles\/)?[^/]+\.(?:js|css))$/);
    if (ui && fs.existsSync(uiFile(ui[1]))) return route.fulfill({contentType: ui[1].endsWith('.css') ? 'text/css' : 'application/javascript', body: fs.readFileSync(uiFile(ui[1]), 'utf8')});
    if (p === '/') return route.fulfill({contentType: 'text/html', body: html});
    if (p === '/api/me') return json({id: 'ana', role: 'owner', name: 'Ana Rivera', email: 'ana@acme.example', cloud: true, credential_access: false, config: CONFIG});
    if (p === '/api/v2/config') return json(CONFIG);
    if (p === '/api/humans') return json({people: [{id: 'ana', name: 'Ana Rivera', org_parent: ''}]});
    if (p === '/api/employees') return json(BOTS);
    if (p === '/api/issues') return json([]);
    if (p === '/api/status') return json({cloud: true, active: [], queued: [], recent_runs: [], keeper_alive: true, health_issues: [], schedules: []});
    if (p === '/api/v2/status') return json({bots: []});
    if (p === '/api/v2/updates') return json({updates: [], missed: [], unread: 0, next_before: null, today: {}});
    if (p === '/api/v2/tasks') return json({tasks: []});
    if (p === '/api/v2/tools') return json({integrations: TOOLS});
    if (p === '/api/v2/assistant') return json({available: true, state: 'active', bot: 'coo', name: 'Tico', room_id: 'room1', messages: [], has_more: false, next_before: null, execution: null, actions: {}, pending: []});
    if (p === '/api/v2/conversations/room1/snapshot') return json({messages: [], execution: null, has_more: false, next_before: null});
    if (p === '/api/v2/market/entities') return json({entities: [{id: 'company/rival', type: 'company', name: 'Rival', status: 'active', tier: 'core'},
      {id: 'company/self', type: 'company', name: 'Acme', status: 'active', tier: 'core'}]});
    if (p === '/api/v2/market/entities/company/rival') return json({entity: {id: 'company/rival', type: 'company', name: 'Rival', summary: 'Sells to studios.'}, edges: [], evidence: []});
    if (p === '/api/v2/market/edges') return json({edges: [{from: 'company/rival', to: 'company/self', type: 'competes_with'}]});
    if (p === '/api/meetings/sources') return json({sources: [{id: 'import', name: 'Import', status: 'available'}]});
    if (p === '/api/v2/meetings') return json({meetings: [meeting('m1', 'Renewal call with Dana', 300), meeting('m2', 'Pricing review', 900)], pending_count: 0});
    if (p === '/api/v2/meeting-importers') return json({computers: [], importers: []});
    if (p === '/api/v2/meetings/granola') return json({mode: 'account', connected: true, email: 'ana@acme.example', plan_hint: null, last_sync: ago(3),
      last_error: null, imported_count: 12, skipped: 0, needs_signin: false, syncing: false});
    if (p === '/api/v2/setup/getting-started') return json({items: [], done: 0, total: 0, complete: true, dismissed: true, tour_seen: true, cards_dismissed: []});
    if (p.endsWith('/watch')) return route.fulfill({contentType: 'text/event-stream', body: ': fixture\n\n'});
    return json({});
  });
  return {page, errors, context};
}
const go = (page, hash) => page.evaluate(h => { location.hash = h; }, hash);
const rgb = s => (s.match(/\d+(\.\d+)?/g) || []).slice(0, 3).map(Number);
const light = s => { const [r, g, b] = rgb(s); return (r + g + b) / 3 > 160; };

(async () => {
  const browser = await chromium.launch({headless: true, channel: process.env.TICO_BROWSER_CHANNEL === undefined ? 'chrome' : process.env.TICO_BROWSER_CHANNEL || undefined});
  try {
    // 2. Market in the light theme: light surfaces and dark words, the graph's canvas too.
    {
      const {page, errors, context} = await open(browser, {width: 1440, height: 900}, 'light');
      await page.goto('https://tico-ui.test/#/market');
      await page.locator('.market-shell .market-list').waitFor();
      const look = await page.evaluate(() => {
        const css = el => getComputedStyle(document.querySelector(el));
        return {shell: css('.market-shell').backgroundColor, ink: css('.market-shell').color, list: css('.market-list').backgroundColor,
          graph: css('.market-graph').backgroundColor};
      });
      assert(light(look.shell) && light(look.list) && light(look.graph), 'Market follows the light theme: ' + JSON.stringify(look));
      assert(!light(look.ink), 'dark words on it');
      await page.waitForTimeout(300);
      const corner = await page.locator('.market-graph canvas').evaluate(c => [...c.getContext('2d').getImageData(2, 2, 1, 1).data].slice(0, 3));
      assert(corner.reduce((a, b) => a + b) / 3 > 160, 'the graph is drawn on the light background: ' + corner);
      assert.deepEqual(errors, []);
      await context.close();
    }

    // 3 and 4. Tools: bots by display name (the Assistant as "Assistant"), credentials in words; the Assistant page too.
    {
      const {page, errors, context} = await open(browser, {width: 1440, height: 900});
      await page.goto('https://tico-ui.test/#/integrations');
      await page.locator('.int-list tbody tr').first().waitFor();
      const row = service => page.locator('.int-list tbody tr', {has: page.locator(`[data-int-cred="${service}"]`)});
      assert.deepEqual(await row('github').locator('td:nth-child(3) a').allInnerTexts(), ['Assistant', 'Account Executive']);
      assert.equal((await row('close-crm').locator('.int-creds').innerText()).trim(), 'API key');
      assert.equal(await row('close-crm').locator('.int-creds [title]').getAttribute('title'), 'CLOSE_API_KEY', 'the variable stays one hover away');
      assert.equal((await row('postgres').locator('.int-creds').innerText()).trim(), 'Connection string');
      assert.equal((await row('github').locator('.int-creds').innerText()).trim(), 'None needed');
      assert.doesNotMatch(await page.locator('.int-list').innerText(), /\bcoo\b|CLOSE_API_KEY|DB_<NAME>_URL/);
      await go(page, '#/assistant');
      await page.locator('#bot-top h1').waitFor();
      assert.equal((await page.locator('#bot-top h1').innerText()).trim(), 'Assistant');
      assert.doesNotMatch(await page.locator('#bot-top').innerText(), /Tico/, 'the product is not the bot');
      assert.deepEqual(errors, []);
      await context.close();
    }

    // 5. A task's tags row with none: "Add tags" whole, at the peek's width.
    {
      const {page, context} = await open(browser, {width: 1440, height: 900});
      await page.goto('https://tico-ui.test/#/updates');
      await page.locator('#main').waitFor();
      const fits = await page.evaluate(() => {
        const host = document.createElement('div');
        host.className = 'task-props'; host.style.width = '472px';
        host.innerHTML = '<div class="props"><div class="prop" data-prop-row="tags"><span class="prop-k">Tags</span><span class="prop-vwrap"><span class="prop-tags tlabels">'
          + '<button type="button" class="prop-v empty" data-prop="tags"><span class="prop-txt">Add tags</span></button></span></span></div></div>';
        document.querySelector('#main').append(host);
        const txt = host.querySelector('.prop-txt'), button = host.querySelector('.prop-v'), key = host.querySelector('.prop-k');
        return {cut: txt.scrollWidth > txt.clientWidth, lined: Math.abs(button.getBoundingClientRect().left + 6 - (key.getBoundingClientRect().right + 6)) <= 1};
      });
      assert.equal(fits.cut, false, '"Add tags" is not cut to "Add t…"');
      assert(fits.lined, 'it lines up with the other values');
      await context.close();
    }

    // 14. Meetings: Granola once (its row), and the filters never cut off, on a desktop and a phone.
    for (const viewport of [{width: 1440, height: 900}, {width: 390, height: 844}]) {
      const {page, errors, context} = await open(browser, viewport);
      await page.goto('https://tico-ui.test/#/meetings');
      await page.locator('#mg-row').waitFor();
      await page.locator('#notes-filters:not([hidden])').waitFor();
      await page.locator('#meet-sources .meet-tile').first().waitFor();
      assert.equal(await page.locator('#meet-sources [data-msrc=granola]').count(), 0, 'no Granola tile beside its row');
      const clipped = await page.evaluate(() => {
        const bar = document.querySelector('#notes-filters').getBoundingClientRect();
        return [...document.querySelectorAll('#notes-filters select')].filter(s => { const r = s.getBoundingClientRect(); return r.right > bar.right + 1 || r.left < bar.left - 1; }).map(s => s.id);
      });
      assert.deepEqual(clipped, [], viewport.width + ': every filter in view');
      assert(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), 'no sideways scroll');
      assert.deepEqual(errors, []);
      await context.close();
    }
  } finally {
    await browser.close();
  }
})().catch(e => { console.error(e); process.exit(1); });
