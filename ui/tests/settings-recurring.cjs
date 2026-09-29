// Offline regression for Settings > Recurring: every routine on every bot in one
// list, with search and filters by bot, computer (including "My computer"), kind and state. Fixtures only.
const {chromium} = require('playwright');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const html = fs.readFileSync(path.join(__dirname, '../index.html'), 'utf8');
const inAnHour = new Date(Date.now() + 3600e3).toISOString();
const mine = {runner_id: 'r-mine', label: 'Ana Mac', operator: 'ana'};
const theirs = {runner_id: 'r-ben', label: 'Ben Mac', operator: 'ben'};
const bots = [
  {name: 'cmo', display_name: 'AI CMO', host: 'keeper', status: 'active', can_chat: true, machine: mine},
  {name: 'seo', display_name: 'AI SEO', host: 'keeper', status: 'active', can_chat: true, machine: theirs},
];
const schedules = [
  {id: 'cmo:plan', employee: 'cmo', title: 'Weekday content plan', kind: 'cron', cron: '0 8 * * 1-5', on: '', enabled: true, active: true, next: inAnHour},
  {id: 'cmo:quotes', employee: 'cmo', title: 'Pull quotes from recordings', kind: 'event', cron: '', on: 'recording.ready', enabled: true, active: true, next: null},
  {id: 'seo:crawl', employee: 'seo', title: 'Weekly crawl', kind: 'cron', cron: '0 9 * * 1', on: '', enabled: false, active: false, next: null},
];
(async () => {
  const browser = await chromium.launch({channel: process.env.TICO_BROWSER_CHANNEL ?? 'chrome', headless: true});
  try {
    const page = await browser.newPage({viewport: {width: 1300, height: 900}, serviceWorkers: 'block'});
    const errors = [];
    page.on('pageerror', e => errors.push(e.message));
    await page.route('**/*', route => {
      const url = new URL(route.request().url()), p = url.pathname;
      const json = body => route.fulfill({contentType: 'application/json', body: JSON.stringify(body)});
      if (url.origin !== 'https://tico-ui.test') return route.abort();
      const ui = p.match(/\/tico\/ui\/([^/]+\.js)$/);
      if (ui && fs.existsSync(path.join(__dirname, '..', ui[1])))
        return route.fulfill({contentType: 'application/javascript', body: fs.readFileSync(path.join(__dirname, '..', ui[1]), 'utf8')});
      if (p === '/') return route.fulfill({contentType: 'text/html', body: html});
      if (p === '/api/me') return json({id: 'ana', role: 'owner', name: 'Ana', email: 'ana@example.test', cloud: true});
      if (p === '/api/people') return json({people: [{id: 'ana', name: 'Ana'}, {id: 'ben', name: 'Ben'}]});
      if (p === '/api/employees') return json(bots);
      if (p === '/api/issues') return json([]);
      if (p === '/api/status') return json({cloud: true, active: [], queued: [], recent_runs: [], schedules});
      if (p === '/api/v2/status') return json({bots: []});
      if (p === '/api/v2/operations') return json({machines: [], services: [], agents: []});
      if (p === '/api/v2/models') return json({models: []});
      return json({});
    });
    await page.goto('https://tico-ui.test/#/settings');
    await page.locator('[data-settings-tab="recurring"]').click();
    const card = page.locator('#set-recurring');
    await card.locator('.rblock').first().waitFor();
    const titles = async () => (await card.locator('.rblock .ttl').allInnerTexts()).map(t => t.replace(/\s*paused$/i, '').trim());
    assert.equal((await titles()).length, 3, 'every routine on every bot');
    assert.match(await card.locator('[data-recurring-count]').innerText(), /3 routines/);
    await card.locator('select[data-recurring-filter="computer"]').selectOption('mine');
    assert.deepEqual((await titles()).sort(), ['Pull quotes from recordings', 'Weekday content plan'], 'My computer = bots on my Mac');
    await card.locator('select[data-recurring-filter="kind"]').selectOption('event');
    assert.deepEqual(await titles(), ['Pull quotes from recordings']);
    await card.locator('select[data-recurring-filter="kind"]').selectOption('all');
    await card.locator('select[data-recurring-filter="computer"]').selectOption('');
    await card.locator('input[data-recurring-filter="q"]').fill('crawl');
    assert.deepEqual(await titles(), ['Weekly crawl'], 'search');
    await card.locator('input[data-recurring-filter="q"]').fill('');
    await card.locator('select[data-recurring-filter="armed"]').selectOption('idle');
    assert.deepEqual(await titles(), ['Weekly crawl'], 'not armed');
    assert.deepEqual(errors, []);
    console.log('PASS: Settings > Recurring lists every routine; search, bot, computer (incl. My computer), kind and state filters.');
  } finally { await browser.close(); }
})().catch(error => { console.error(error); process.exitCode = 1; });
