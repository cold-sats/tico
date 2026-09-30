// Offline browser regression: a Settings or Tools form keeps what a person has typed while the app's
// polls run. Types into Tools > GitHub, and into Settings > Computers (Add computer, API token), fires the
// refresh paths and asserts the values survive.
const {chromium} = require('playwright');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const {html, uiFile} = require('./support/page.cjs');
(async () => {
  const browser = await chromium.launch({headless: true, channel: process.env.TICO_BROWSER_CHANNEL === undefined ? 'chrome' : process.env.TICO_BROWSER_CHANNEL || undefined});
  try {
    const page = await browser.newPage({viewport: {width: 1440, height: 900}, serviceWorkers: 'block'});
    const errors = [];
    page.on('pageerror', e => errors.push(e.message));
    await page.route('**/*', route => {
      const req = route.request(), p = new URL(req.url()).pathname;
      const json = (body, status = 200) => route.fulfill({status, contentType: 'application/json', body: JSON.stringify(body)});
      const ui = p.match(/\/tico\/ui\/((?:app\/|styles\/)?[^/]+\.(?:js|css))$/);
      if (ui && fs.existsSync(uiFile(ui[1])))
        return route.fulfill({contentType: ui[1].endsWith('.css') ? 'text/css' : 'application/javascript', body: fs.readFileSync(uiFile(ui[1]), 'utf8')});
      if (p.endsWith('.js')) return route.fulfill({contentType: 'application/javascript', body: ''});
      if (p === '/') return route.fulfill({contentType: 'text/html', body: html});
      const config = {version: '0.1.0', app_name: 'Tico'};
      if (p === '/api/me') return json({id: 'ana', role: 'owner', name: 'Ana', email: 'ana@acme.example', cloud: true, registered: true, config});
      if (p === '/api/v2/config') return json(config);
      if (p === '/api/employees' || p === '/api/issues') return json([]);
      if (p === '/api/people') return json({people: [], teams: {}});
      if (p === '/api/status') return json({cloud: true, active: [], queued: [], recent_runs: [], keeper_alive: true, health_issues: []});
      if (p === '/api/v2/status') return json({bots: []});
      if (p === '/api/v2/needs-you') return json({items: []});
      if (p === '/api/v2/integrations') return json({integrations: []});
      if (p === '/api/v2/github/app') return json({connected: false});
      if (p === '/api/v2/operations') return json({machines: [], services: []});
      if (p === '/api/v2/me/tokens') return json({tokens: []});
      if (p === '/api/v2/slack/app') return json({configured: false});
      if (p === '/api/v2/meeting-importers') return json({importers: [], computers: []});
      if (p.endsWith('/watch')) return route.fulfill({contentType: 'text/event-stream', body: ': fixture\n\n'});
      return json({});
    });
    await page.goto('https://tico-ui.test/#/integrations');
    const org = page.locator('[data-gh-form] input[name=org]'), name = page.locator('[data-gh-form] input[name=name]');
    await org.fill('acme-inc'); await name.fill('Acme Tico'); await name.focus();
    // The app's polls, and a redraw of the same route (the Tools page rebuilt itself and wiped the form).
    await page.evaluate(async () => { await refresh(false); await refresh(true); applyConfig(await get('/v2/config')); route(); });
    await page.waitForTimeout(300);
    assert.equal(await org.inputValue(), 'acme-inc', 'Organization survives the refresh');
    assert.equal(await name.inputValue(), 'Acme Tico', 'App name survives the refresh');

    // Settings: loadSettings and a same-route redraw leave the Add computer and API token fields alone.
    await page.goto('https://tico-ui.test/#/settings');
    const machine = page.locator('#machine-label'), token = page.locator('#settings-token-form input[name=label]');
    await machine.waitFor(); await token.waitFor();
    await machine.fill('Build server'); await token.fill('CI script');
    await page.evaluate(async () => { await loadSettings(); route(); });
    await page.waitForTimeout(300);
    assert.equal(await machine.inputValue(), 'Build server', 'Computer name survives loadSettings');
    assert.equal(await token.inputValue(), 'CI script', 'Token label survives loadSettings');
    assert.deepEqual(errors, []);
    console.log('ok');
  } finally { await browser.close(); }
})().catch(e => { console.error(e); process.exit(1); });
