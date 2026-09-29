// Offline browser regression: "Sign out" in the account menu appears only for a session an identity
// proxy vouches for (Cloudflare Access, the AWS load balancer), and it goes to /api/v2/logout.
const {chromium} = require('playwright');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const html = fs.readFileSync(path.join(__dirname, '../index.html'), 'utf8');
(async () => {
  const browser = await chromium.launch({headless: true, channel: process.env.TICO_BROWSER_CHANNEL === undefined ? 'chrome' : process.env.TICO_BROWSER_CHANNEL || undefined});
  try {
    const visit = async proxySession => {
      const page = await browser.newPage({viewport: {width: 1440, height: 900}, serviceWorkers: 'block'});
      const errors = [];
      page.on('pageerror', e => errors.push(e.message));
      await page.route('**/*', route => {
        const p = new URL(route.request().url()).pathname;
        const json = body => route.fulfill({contentType: 'application/json', body: JSON.stringify(body)});
        const ui = p.match(/\/tico\/ui\/([^/]+\.js)$/);
        if (ui && fs.existsSync(path.join(__dirname, '..', ui[1])))
          return route.fulfill({contentType: 'application/javascript', body: fs.readFileSync(path.join(__dirname, '..', ui[1]), 'utf8')});
        if (p.endsWith('.js')) return route.fulfill({contentType: 'application/javascript', body: ''});
        if (p === '/') return route.fulfill({contentType: 'text/html', body: html});
        if (p === '/api/me') return json({id: 'ana', role: 'owner', name: 'Ana', email: 'ana@acme.example', cloud: true, registered: true, proxy_session: proxySession});
        if (p === '/api/employees' || p === '/api/issues') return json([]);
        if (p === '/api/people') return json({people: [], teams: {}});
        if (p === '/api/status') return json({cloud: true, active: [], queued: [], recent_runs: [], keeper_alive: true, health_issues: []});
        if (p === '/api/v2/status') return json({bots: []});
        if (p === '/api/v2/needs-you') return json({items: []});
        if (p.endsWith('/watch')) return route.fulfill({contentType: 'text/event-stream', body: ': fixture\n\n'});
        return json({});
      });
      await page.goto('https://tico-ui.test/#/help');
      await page.waitForFunction(() => !document.querySelector('#account .account-email')?.textContent.includes('Signing in'));
      await page.locator('#account').click();
      const link = page.locator('#sign-out');
      const shown = await link.isVisible();
      const href = await link.getAttribute('href');
      const label = shown ? (await link.innerText()).replace(/\s+/g, ' ').trim() : '';
      assert.deepEqual(errors, []);
      await page.close();
      return {shown, href, label};
    };
    const proxied = await visit(true);
    assert.equal(proxied.shown, true, 'a proxy session can sign out');
    assert.equal(proxied.href, '/api/v2/logout');
    assert.match(proxied.label, /Sign out$/);
    assert.equal((await visit(false)).shown, false, 'a bearer or local session has nothing to sign out of');
    console.log('PASS: Sign out is in the account menu for proxy sessions only and links to /api/v2/logout.');
  } finally { await browser.close(); }
})().catch(error => { console.error(error); process.exitCode = 1; });
