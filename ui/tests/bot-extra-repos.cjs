// Offline regression: the owner edits a bot's extra GitHub repositories in its settings dialog.
// The field appears only when GitHub is connected, loads the saved list, and saves it (with the
// definition) only when it changed. Fixtures only.
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
    let connected = true, saved = ['Acme/shared-docs'], puts = [], definitions = 0;
    const bot = {name: 'cpo', display_name: 'Product', description: '', status: 'active', repo: 'emp-cpo', revision: 1,
      operator: 'ana', users: [], thread_mode: 'personal', bot_contact: 'open'};
    await page.route('**/*', route => {
      const request = route.request(), url = new URL(request.url()), p = url.pathname;
      const json = body => route.fulfill({contentType: 'application/json', body: JSON.stringify(body)});
      if (url.origin !== 'https://tico-ui.test') return route.abort();
      const ui = p.match(/\/tico\/ui\/([^/]+\.js)$/);
      if (ui && fs.existsSync(path.join(__dirname, '..', ui[1])))
        return route.fulfill({contentType: 'application/javascript', body: fs.readFileSync(path.join(__dirname, '..', ui[1]), 'utf8')});
      if (p === '/') return route.fulfill({contentType: 'text/html', body: html});
      if (p === '/api/me') return json({id: 'ana', role: 'owner', name: 'Ana', email: 'ana@example.test', cloud: true});
      if (p === '/api/employees') return json([bot]);
      if (p === '/api/issues') return json([]);
      if (p === '/api/people') return json({people: [{id: 'ana', name: 'Ana'}]});
      if (p === '/api/status') return json({cloud: true, active: [], queued: [], recent_runs: [], schedules: []});
      if (p === '/api/v2/models') return json({models: [], harnesses: [], enabled_providers: [], default: {}});
      if (p === '/api/v2/operations') return json({machines: [], services: [], issues: [], scheduler_enabled: true});
      if (p === '/api/v2/bots/cpo/definition') { definitions++; return json({ok: true}); }
      if (p === '/api/v2/bots/cpo/github-repos') {
        if (request.method() === 'PUT') { const body = request.postDataJSON(); puts.push(body.repositories);
          saved = body.repositories.map(r => 'Acme/' + r); return json({connected: true, org: 'Acme', repositories: saved}); }
        return json({connected, org: 'Acme', repository: 'Acme/emp-cpo', repositories: saved});
      }
      return json({});
    });
    await page.goto('https://tico-ui.test/#/settings');
    await page.locator('#set-machines').waitFor();
    const open = async () => { await page.evaluate(() => settingsEditBot('cpo')); await page.locator('#bot-editor form').waitFor(); };

    await open();
    const box = page.locator('#bot-editor textarea[name="extra_repos"]');
    await box.waitFor();
    assert.equal(await box.inputValue(), 'shared-docs', 'the saved list is shown without the organization prefix');
    await page.getByRole('button', {name: 'Save bot'}).click();
    await page.waitForFunction(() => !document.querySelector('#bot-editor').open);
    assert.equal(definitions, 1);
    assert.deepEqual(puts, [], 'an unchanged list is not written again');

    await open();
    await box.waitFor();
    await box.fill('shared-docs\ndesign-system, infra');
    await page.getByRole('button', {name: 'Save bot'}).click();
    await page.waitForFunction(() => !document.querySelector('#bot-editor').open);
    assert.deepEqual(puts, [['shared-docs', 'design-system', 'infra']]);

    connected = false;
    await open();
    await page.waitForTimeout(300);
    assert.equal(await page.locator('#bot-editor [data-extra-repos]').isHidden(), true, 'hidden until GitHub is connected');
    assert.deepEqual(errors, []);
    console.log("PASS: a bot's extra GitHub repositories load, save only when changed, and hide without a connection.");
  } finally { await browser.close(); }
})().catch(error => { console.error(error); process.exitCode = 1; });
