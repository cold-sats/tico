// Offline regression: notices the hub writes for bots ("New task from human:riley: ...") reach people
// with names, never raw actor ids, in the bot feed, task notes and request lines. Fixtures only.
const {chromium} = require('playwright');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const html = fs.readFileSync(path.join(__dirname, '../index.html'), 'utf8');

(async () => {
  const browser = await chromium.launch({channel: process.env.TICO_BROWSER_CHANNEL ?? 'chrome', headless: true});
  try {
    const context = await browser.newContext({viewport: {width: 1200, height: 900}, serviceWorkers: 'block'});
    await context.route('**/*', async route => {
      const url = new URL(route.request().url()), p = url.pathname;
      const json = body => route.fulfill({status: 200, contentType: 'application/json', body: JSON.stringify(body)});
      if (url.origin !== 'http://tico-ui.test') return route.abort();
      if (p === '/') return route.fulfill({contentType: 'text/html', body: html});
      const ui = p.match(/\/tico\/ui\/([^/]+\.js)$/);
      if (ui && fs.existsSync(path.join(__dirname, '..', ui[1]))) return route.fulfill({contentType: 'application/javascript', body: fs.readFileSync(path.join(__dirname, '..', ui[1]), 'utf8')});
      if (p.startsWith('/vendor/fonts/') && p.endsWith('.woff2')) return route.fulfill({contentType: 'font/woff2', body: fs.readFileSync(path.join(__dirname, '..', p))});
      if (p === '/api/me') return json({id: 'ana', name: 'Ana', email: 'ana@acme.example', role: 'owner', cloud: true});
      if (p === '/api/people') return json({people: [{id: 'ana', name: 'Ana'}, {id: 'riley', name: 'Riley Stone'}]});
      if (p === '/api/employees') return json([{name: 'botops', display_name: 'BotOps', host: 'keeper', status: 'active', can_chat: true, team: '', operator: 'ana'}]);
      if (p === '/api/issues') return json([]);
      if (p === '/api/status') return json({cloud: true, active: [], queued: [], recent_runs: [], schedules: []});
      if (p === '/api/v2/status') return json({bots: []});
      if (p === '/api/v2/updates/unread') return json({unread: 0});
      if (p.endsWith('/watch')) return route.fulfill({contentType: 'text/event-stream', body: ': fixture\n\n'});
      return json({});
    });
    const errors = [];
    const page = await context.newPage();
    page.on('pageerror', e => errors.push(e.message));
    await page.goto('http://tico-ui.test/#/help');
    await page.waitForFunction(() => S.people?.some(p => p.id === 'riley') && S.emps?.length);
    const lines = await page.evaluate(() => [
      v2MessageHTML({kind: 'notice', body: 'New task from human:riley: Build a bot: answer support', created: new Date().toISOString()}),
      v2MessageHTML({kind: 'notice', body: 'New task from human:ana: Sort the inbox', created: new Date().toISOString()}),
      v2MessageHTML({kind: 'notice', body: 'New task from bot:botops: Review', created: new Date().toISOString()}),
    ].map(row => { const el = document.createElement('div'); el.innerHTML = row; return el.textContent; }));
    assert.match(lines[0], /New task from Riley Stone: Build a bot: answer support/);
    assert.match(lines[1], /New task from you: Sort the inbox/);
    assert.match(lines[2], /New task from BotOps: Review/);
    for (const line of lines) assert.doesNotMatch(line, /\b(human|bot):\w/);
    assert.deepEqual(errors, []);
    console.log('PASS: feed lines name people and bots, never raw actor ids.');
  } finally { await browser.close(); }
})().catch(e => { console.error(e); process.exitCode = 1; });
