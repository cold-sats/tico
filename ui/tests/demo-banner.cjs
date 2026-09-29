// Offline browser regression: a demo server says `demo: true` in its config and the page then carries a
// "Demo - sample data" strip that has no way to be closed; any other server shows nothing of the kind.
const {chromium} = require('playwright');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const html = fs.readFileSync(path.join(__dirname, '../index.html'), 'utf8');
(async () => {
  const browser = await chromium.launch({headless: true, channel: process.env.TICO_BROWSER_CHANNEL === undefined ? 'chrome' : process.env.TICO_BROWSER_CHANNEL || undefined});
  try {
    const visit = async (demo, viewport) => {
      const page = await browser.newPage({viewport, serviceWorkers: 'block'});
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
        if (p === '/api/v2/config') return json({app_name: 'Tico', company_name: 'Acme', demo});
        if (p === '/api/me') return json({id: 'ana', role: 'owner', name: 'Ana', email: 'ana@acme.example', cloud: true, registered: true, config: {app_name: 'Tico', company_name: 'Acme', demo}});
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
      const banner = page.locator('#demo-banner');
      const shown = await banner.isVisible();
      const text = shown ? (await banner.innerText()).replace(/\s+/g, ' ') : '';
      const closable = await banner.locator('button, a, [role="button"]').count();
      const title = await page.title();
      const box = shown ? await banner.boundingBox() : null;
      const sideTop = await page.locator('#side').evaluate(el => el.getBoundingClientRect().top);
      assert.deepEqual(errors, []);
      await page.close();
      return {shown, text, closable, title, box, sideTop};
    };
    for (const viewport of [{width: 1440, height: 900}, {width: 390, height: 844}]) {
      const demo = await visit(true, viewport);
      assert.equal(demo.shown, true, 'a demo shows its banner');
      assert.match(demo.text, /^Demo — sample data/);
      assert.equal(demo.closable, 0, 'the banner cannot be closed');
      assert.match(demo.title, /^Demo/);
      assert.equal(demo.box.y, 0);
      assert.ok(demo.box.width >= viewport.width - 1, 'the strip spans the page');
      if (viewport.width > 760) assert.equal(demo.sideTop, demo.box.height, 'the page starts below the strip');
      const real = await visit(false, viewport);
      assert.equal(real.shown, false, 'a real install shows no banner');
    }
    console.log('PASS: demo servers carry a permanent "Demo - sample data" banner; real ones never do.');
  } finally { await browser.close(); }
})().catch(error => { console.error(error); process.exitCode = 1; });
