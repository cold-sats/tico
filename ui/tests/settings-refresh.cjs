// Regression: the 30 s refresh must not rebuild Settings, which snapped the page back to Devices
// and threw away what the owner was typing in Cloud services. Fixtures only.
const {chromium} = require('playwright');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const html = fs.readFileSync(path.join(__dirname, '../index.html'), 'utf8');
(async () => {
  const browser = await chromium.launch({channel: process.env.TICO_BROWSER_CHANNEL ?? 'chrome', headless: true});
  try {
    const page = await browser.newPage({viewport: {width: 1300, height: 900}, serviceWorkers: 'block'});
    const errors = [];
    page.on('pageerror', e => errors.push(e.message));
    let polls = 0;
    await page.route('**/*', route => {
      const url = new URL(route.request().url()), p = url.pathname;
      const json = body => route.fulfill({contentType: 'application/json', body: JSON.stringify(body)});
      if (url.origin !== 'https://tico-ui.test') return route.abort();
      const ui = p.match(/\/tico\/ui\/([^/]+\.js)$/);
      if (ui && fs.existsSync(path.join(__dirname, '..', ui[1])))
        return route.fulfill({contentType: 'application/javascript', body: fs.readFileSync(path.join(__dirname, '..', ui[1]), 'utf8')});
      if (p === '/') return route.fulfill({contentType: 'text/html', body: html});
      if (p === '/api/me') return json({id: 'ana', role: 'owner', name: 'Ana', email: 'ana@example.test', cloud: true});
      if (p === '/api/status') { polls++; return json({cloud: true, active: [], queued: [], recent_runs: [], schedules: []}); }
      if (p === '/api/v2/github/app') return json({connected: false});
      if (p === '/api/people') return json({people: [{id: 'ana', name: 'Ana'}]});
      if (p === '/api/employees' || p === '/api/issues') return json([]);
      return json({});
    });
    await page.clock.install();
    await page.goto('https://tico-ui.test/#/settings');
    await page.locator('[data-settings-tab="cloud"]').click();
    const org = page.locator('#set-github input[name="org"]');
    await org.fill('Acme');
    const before = polls;
    await page.clock.runFor(95000);
    assert.ok(polls > before, 'the refresh ran');
    assert.equal(await page.locator('[data-settings-tab="cloud"]').getAttribute('aria-selected'), 'true');
    assert.equal(await page.locator('#settings-cloud').isVisible(), true);
    assert.equal(await page.locator('#settings-devices').isVisible(), false);
    assert.equal(await org.inputValue(), 'Acme', 'typing survives the refresh');
    // Any redraw of the same route (a refresh that ends in route()) must keep the page as it is.
    await page.evaluate(() => route());
    assert.equal(await page.locator('[data-settings-tab="cloud"]').getAttribute('aria-selected'), 'true');
    assert.equal(await org.inputValue(), 'Acme', 'typing survives a redraw of the route');
    await page.locator('#set-github button[type="submit"]').click({trial: true});
    await page.reload();
    assert.equal(await page.locator('[data-settings-tab="cloud"]').getAttribute('aria-selected'), 'true', 'a reload keeps the tab');
    assert.deepEqual(errors, []);
    console.log('PASS: Settings keeps its tab and form input across the periodic refresh.');
  } finally { await browser.close(); }
})().catch(error => { console.error(error); process.exitCode = 1; });
