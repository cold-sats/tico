// Offline regression for Settings > Devices: a model nobody enabled is not listed as missing in red, a
// missing one that an enabled provider or an assigned bot needs is red, and a harness whose key the
// provider refused says so with the fix. Fixtures only - no server.
const {chromium} = require('playwright');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const html = fs.readFileSync(path.join(__dirname, '../index.html'), 'utf8');

const runtime = (installed, authenticated, extra = {}) => ({installed, authenticated, ...extra});
const machine = (id, needed, runtimes) => ({id, label: id, operator: 'ana', last_seen: new Date().toISOString(), revoked_at: null,
  platform: 'linux', version: '0.2.1', bots: [], needed_runtimes: needed, readiness: {schema_version: 1, runtimes, bots: {}}});
const machines = [
  machine('Cloud box', ['codex'], {codex: runtime(true, 'ready'), claude: runtime(false, 'missing'), cursor: runtime(false, 'missing'),
    gemini: runtime(false, 'missing'), grok: runtime(false, 'missing'), pi: runtime(false, 'missing')}),
  machine('Needs claude', ['claude', 'codex'], {codex: runtime(true, 'ready'), claude: runtime(false, 'missing')}),
  machine('Bad key', ['codex'], {codex: runtime(true, 'rejected', {rejected_at: new Date().toISOString(),
    rejected_reason: 'unexpected status 401 Unauthorized: Incorrect API key provided'})}),
];

(async () => {
  const browser = await chromium.launch({channel: process.env.TICO_BROWSER_CHANNEL ?? 'chrome', headless: true});
  try {
    const context = await browser.newContext({viewport: {width: 1200, height: 1100}, serviceWorkers: 'block'});
    await context.route('**/*', async route => {
      const url = new URL(route.request().url()), p = url.pathname;
      const json = body => route.fulfill({status: 200, contentType: 'application/json', body: JSON.stringify(body)});
      if (url.origin !== 'http://tico-ui.test') return route.abort();
      if (p === '/') return route.fulfill({contentType: 'text/html', body: html});
      const ui = p.match(/\/tico\/ui\/([^/]+\.js)$/);
      if (ui && fs.existsSync(path.join(__dirname, '..', ui[1]))) return route.fulfill({contentType: 'application/javascript', body: fs.readFileSync(path.join(__dirname, '..', ui[1]), 'utf8')});
      if (p.startsWith('/vendor/fonts/') && p.endsWith('.woff2')) return route.fulfill({contentType: 'font/woff2', body: fs.readFileSync(path.join(__dirname, '..', p))});
      if (p === '/api/me') return json({id: 'ana', name: 'Ana', email: 'ana@acme.example', role: 'owner', cloud: true});
      if (p === '/api/people') return json({people: [{id: 'ana', name: 'Ana'}]});
      if (p === '/api/employees' || p === '/api/issues') return json([]);
      if (p === '/api/status') return json({cloud: true, active: [], queued: [], recent_runs: [], schedules: []});
      if (p === '/api/v2/status') return json({bots: []});
      if (p === '/api/v2/operations') return json({machines, services: [], agents: []});
      if (p === '/api/v2/updates/unread') return json({unread: 0});
      if (p.endsWith('/watch')) return route.fulfill({contentType: 'text/event-stream', body: ': fixture\n\n'});
      return json({});
    });
    const errors = [];
    const page = await context.newPage();
    page.on('pageerror', e => errors.push(e.message));
    await page.goto('http://tico-ui.test/#/settings');
    await page.locator('[data-settings-tab="devices"]').click();
    await page.locator('#set-machines .machine-card').first().waitFor();
    const card = label => page.locator('#set-machines .machine-card', {hasText: label});
    const pills = label => card(label).locator('.machine-runtime .pill').evaluateAll(els => els.map(el => [el.textContent.split(' ·')[0], el.classList.contains('fail')]));

    assert.deepEqual(await pills('Cloud box'), [['codex', false]], 'harnesses nobody enabled are not listed');
    assert.deepEqual(await pills('Needs claude'), [['codex', false], ['claude', true]], 'a needed missing one is red');
    assert.deepEqual(await pills('Bad key'), [['codex', true]]);
    assert.match(await card('Bad key').locator('[data-rejected=codex]').innerText(), /Incorrect API key provided\. Replace the key in the runner's secrets, or sign in again/);
    assert.match(await card('Bad key').innerText(), /sign-in rejected/);
    assert.equal(await card('Cloud box').locator('[data-rejected]').count(), 0);
    assert.deepEqual(errors, []);
    console.log('PASS: Devices lists only the harnesses that matter, red only when needed or rejected.');
  } finally { await browser.close(); }
})().catch(e => { console.error(e); process.exitCode = 1; });
