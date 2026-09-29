// Offline regression for Settings > Cloud services > GitHub: the connect form asks for the org and
// submits GitHub's manifest form; a connected app shows its state and can be disconnected. Fixtures only.
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
    let connected = false, posted = null, manifestQuery = null;
    const app = {connected: true, slug: 'acme-tico', org: 'Acme', installed: false, administration: true,
      install_url: 'https://github.com/apps/acme-tico/installations/new', uninstall_url: 'https://github.com/organizations/Acme/settings/installations'};
    await page.route('**/*', route => {
      const url = new URL(route.request().url()), p = url.pathname;
      const json = body => route.fulfill({contentType: 'application/json', body: JSON.stringify(body)});
      if (url.origin === 'https://github.com') { posted = route.request().postData(); return route.fulfill({contentType: 'text/html', body: 'github'}); }
      if (url.origin !== 'https://tico-ui.test') return route.abort();
      const ui = p.match(/\/tico\/ui\/([^/]+\.js)$/);
      if (ui && fs.existsSync(path.join(__dirname, '..', ui[1])))
        return route.fulfill({contentType: 'application/javascript', body: fs.readFileSync(path.join(__dirname, '..', ui[1]), 'utf8')});
      if (p === '/') return route.fulfill({contentType: 'text/html', body: html});
      if (p === '/api/me') return json({id: 'ana', role: 'owner', name: 'Ana', email: 'ana@example.test', cloud: true});
      if (p === '/api/v2/github/app/manifest') { manifestQuery = url.searchParams;
        return json({action: 'https://github.com/organizations/Acme/settings/apps/new?state=n1', state: 'n1', manifest: {name: 'Acme Tico'}}); }
      if (p === '/api/v2/github/app/disconnect') { connected = false; return json({ok: true}); }
      if (p === '/api/v2/github/app') return json(connected ? app : {connected: false});
      if (p === '/api/people') return json({people: [{id: 'ana', name: 'Ana'}]});
      if (p === '/api/employees' || p === '/api/issues') return json([]);
      if (p === '/api/status') return json({cloud: true, active: [], queued: [], recent_runs: [], schedules: []});
      return json({});
    });
    await page.goto('https://tico-ui.test/#/settings');
    await page.locator('[data-settings-tab="cloud"]').click();
    const card = page.locator('#set-github');
    await card.locator('input[name="org"]').fill('Acme');
    await card.locator('input[name="administration"]').check();
    await card.getByRole('button', {name: 'Connect GitHub'}).click();
    await page.waitForFunction(() => document.body.innerText.includes('github'));
    assert.equal(manifestQuery.get('org'), 'Acme');
    assert.equal(manifestQuery.get('administration'), 'true');
    assert.match(decodeURIComponent((posted || '').replace(/\+/g, ' ')), /manifest=\{"name":"Acme Tico"\}/, 'the manifest is posted to GitHub');
    connected = true;
    await page.goto('https://tico-ui.test/#/settings');
    await page.reload();
    await page.locator('[data-settings-tab="cloud"]').click();
    await card.getByText('Connected to').waitFor();
    assert.match(await card.innerText(), /Acme.*acme-tico.*Not installed yet/s);
    assert.equal(await card.locator('a', {hasText: 'Install on Acme'}).getAttribute('href'), app.install_url);
    page.once('dialog', d => d.accept());
    await card.getByRole('button', {name: 'Disconnect'}).click();
    await card.locator('input[name="org"]').waitFor();
    assert.deepEqual(errors, []);
    console.log('PASS: Settings > GitHub connects through the manifest form and shows and forgets the connection.');
  } finally { await browser.close(); }
})().catch(error => { console.error(error); process.exitCode = 1; });
