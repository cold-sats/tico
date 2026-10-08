// Offline browser regression: the sidebar is dragged wider, the width is saved with the account (preference
// ui.rails) and on the device, comes back after a reload, follows the arrow keys, and a double-click resets it.
// A phone has no edge.
const {chromium} = require('playwright');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const {html, uiFile} = require('./support/page.cjs');
(async () => {
  const browser = await chromium.launch({headless: true, channel: process.env.TICO_BROWSER_CHANNEL === undefined ? 'chrome' : process.env.TICO_BROWSER_CHANNEL || undefined});
  try {
    let pref = null;
    const ctx = await browser.newContext({viewport: {width: 1440, height: 900}, serviceWorkers: 'block'});
    const page = await ctx.newPage();
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
      const config = {version: '0.3.0', update: null, app_name: 'Tico'};
      if (p === '/api/me') return json({id: 'ana', role: 'owner', name: 'Ana', email: 'ana@acme.example', cloud: true, registered: true, config});
      if (p === '/api/v2/config') return json(config);
      if (p === '/api/v2/preferences/ui.rails') {
        if (req.method() === 'POST') pref = JSON.parse(req.postData()).value;
        return json({key: 'ui.rails', value: pref});
      }
      if (p === '/api/employees' || p === '/api/issues') return json([]);
      if (p === '/api/humans') return json({people: [], teams: {}});
      if (p === '/api/status') return json({cloud: true, active: [], queued: [], recent_runs: [], keeper_alive: true, health_issues: []});
      if (p.endsWith('/watch')) return route.fulfill({contentType: 'text/event-stream', body: ': fixture\n\n'});
      return json({});
    });
    const sideWidth = () => page.evaluate(() => document.querySelector('#side').getBoundingClientRect().width);
    const ready = () => page.waitForFunction(() => !document.querySelector('#account .account-email')?.textContent.includes('Signing in'));
    await page.goto('https://tico-ui.test/#/help');
    await ready();
    const edge = page.locator('.rail-edge[data-rail="left"]');
    assert.equal(await sideWidth(), 236);
    assert.equal(await edge.getAttribute('role'), 'separator');
    assert.equal(await edge.getAttribute('aria-valuenow'), '236');

    const box = await edge.boundingBox();
    await page.mouse.move(box.x + 4, 400);
    await page.mouse.down();
    await page.mouse.move(box.x + 104, 400, {steps: 4});
    await page.mouse.up();
    assert.equal(await sideWidth(), 336);
    const savedBy = Date.now() + 10000;                    // the account copy is written after a short pause
    while (pref?.left !== 336 && Date.now() < savedBy) await new Promise(r => setTimeout(r, 50));
    assert.equal(pref?.left, 336, 'the width is saved with the account');

    await page.evaluate(() => localStorage.clear());       // another computer: the account's copy wins
    await page.reload();
    await ready();
    await page.waitForFunction(() => document.querySelector('#side').getBoundingClientRect().width === 336);
    assert.equal(await edge.getAttribute('aria-valuenow'), '336');

    await edge.focus();
    await page.keyboard.press('ArrowRight');
    assert.equal(await sideWidth(), 352);
    await page.keyboard.press('End');
    assert.equal(await sideWidth(), 420, 'the sidebar stops at its widest');

    await edge.dblclick();
    assert.equal(await sideWidth(), 236);
    assert.equal(JSON.parse(await page.evaluate(() => localStorage.getItem('tico.rails'))).left, undefined);

    await page.setViewportSize({width: 390, height: 800});
    assert.equal(await edge.isVisible(), false, 'a phone has no edge');
    assert.deepEqual(errors, []);
    await ctx.close();
  } finally {
    await browser.close();
  }
})().catch(e => { console.error(e); process.exit(1); });
