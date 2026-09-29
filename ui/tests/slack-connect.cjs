// Offline regression for Settings > Cloud services > Slack: the owner pastes the two tokens once (sent to the
// server, never shown again); a saved connection shows the gateway's state and can be forgotten. Fixtures only.
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
    let saved = null, forgotten = false;
    await page.route('**/*', route => {
      const url = new URL(route.request().url()), p = url.pathname;
      const json = body => route.fulfill({contentType: 'application/json', body: JSON.stringify(body)});
      if (url.origin !== 'https://tico-ui.test') return route.abort();
      const ui = p.match(/\/tico\/ui\/([^/]+\.js)$/);
      if (ui && fs.existsSync(path.join(__dirname, '..', ui[1])))
        return route.fulfill({contentType: 'application/javascript', body: fs.readFileSync(path.join(__dirname, '..', ui[1]), 'utf8')});
      if (p === '/') return route.fulfill({contentType: 'text/html', body: html});
      if (p === '/api/me') return json({id: 'ana', role: 'owner', name: 'Ana', email: 'ana@example.test', cloud: true});
      if (p === '/api/v2/slack/tokens') { saved = JSON.parse(route.request().postData()); return json({ok: true}); }
      if (p === '/api/v2/slack/disconnect') { forgotten = true; saved = null; return json({ok: true}); }
      if (p === '/api/v2/slack/app') return json(saved ? {configured: true, state: 'disconnected', message: 'invalid_auth'} : {configured: false, state: 'off'});
      if (p === '/api/people') return json({people: [{id: 'ana', name: 'Ana'}]});
      if (p === '/api/employees' || p === '/api/issues') return json([]);
      if (p === '/api/status') return json({cloud: true, active: [], queued: [], recent_runs: [], schedules: []});
      return json({});
    });
    await page.goto('https://tico-ui.test/#/settings');
    await page.locator('[data-settings-tab="cloud"]').click();
    const card = page.locator('#set-slack');
    await card.locator('input[name="bot_token"]').fill('xoxb-test-token-1');
    await card.locator('input[name="app_token"]').fill('xapp-test-token-1');
    await card.getByRole('button', {name: 'Connect Slack'}).click();
    await card.getByText('Disconnected').waitFor();
    assert.deepEqual(saved, {bot_token: 'xoxb-test-token-1', app_token: 'xapp-test-token-1'});
    const shown = await card.innerText();
    assert.match(shown, /invalid_auth/);
    assert.ok(!shown.includes('xoxb-') && !shown.includes('xapp-'), 'tokens are never shown back');
    page.once('dialog', d => d.accept());
    await card.getByRole('button', {name: 'Disconnect'}).click();
    await card.locator('input[name="bot_token"]').waitFor();
    assert.ok(forgotten);
    assert.deepEqual(errors, []);
    console.log('PASS: Settings > Slack saves the tokens once, shows only the gateway state, and forgets them.');
  } finally { await browser.close(); }
})().catch(error => { console.error(error); process.exitCode = 1; });
