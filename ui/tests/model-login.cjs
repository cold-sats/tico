// Offline regression for signing a model in from the browser: the Sign in button on a computer's
// runtime chip and on the Getting started step opens a dialog that shows the link and one-time code
// the computer's CLI printed, takes a pasted code for Claude, reports failure and expiry, cancels,
// and flips the chip to ready when the computer says so. Fixtures only - no server.
// TICO_SCREENSHOT_DIR=<dir> saves the review screenshots.
const {chromium} = require('playwright');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const html = fs.readFileSync(path.join(__dirname, '../index.html'), 'utf8');
const shots = process.env.TICO_SCREENSHOT_DIR;
const shot = (page, name) => shots ? page.screenshot({path: path.join(shots, `model-login-${name}.png`)}) : null;

const login = (extra = {}) => ({id: 'l1', runner_id: 'r1', runtime: 'codex', profile: '', state: 'requested', url: '', code: '',
  lines: [], message: '', accepts_code: false, code_sent: false, created: new Date().toISOString(), updated: '',
  expires_at: '', ...extra});

(async () => {
  const browser = await chromium.launch({channel: process.env.TICO_BROWSER_CHANNEL ?? 'chrome', headless: true});
  try {
    const context = await browser.newContext({viewport: {width: 1200, height: 900}, serviceWorkers: 'block'});
    await context.grantPermissions(['clipboard-read', 'clipboard-write'], {origin: 'https://tico-ui.test'});
    const calls = [];
    let current = login();
    let runtimes = {codex: {installed: true, authenticated: 'missing', detail: 'Codex login required'},
                    claude: {installed: true, authenticated: 'ready', detail: ''},
                    gemini: {installed: false, authenticated: 'missing', detail: ''}};
    const machines = () => [{id: 'r1', label: 'Runner VM', operator: 'ana', last_seen: new Date().toISOString(), revoked_at: null,
      platform: 'linux', version: '0.5.4', bots: [], readiness: {schema_version: 1, runtimes, bots: {}}}];
    const model = {id: 'model', label: 'A model is signed in on it', done: false, optional: false, skipped: false,
      why: 'Sign in to a model on the computer.', href: '#/settings', tab: 'devices', action: '',
      login: {runner_id: 'r1', runtime: 'codex', machine: 'Runner VM'}};
    await context.route('**/*', async route => {
      const req = route.request(), url = new URL(req.url()), p = url.pathname;
      const json = (body, status = 200) => route.fulfill({status, contentType: 'application/json', body: JSON.stringify(body)});
      if (url.origin !== 'https://tico-ui.test') return route.abort();
      if (p === '/') return route.fulfill({contentType: 'text/html', body: html});
      const ui = p.match(/\/tico\/ui\/([^/]+\.js)$/);
      if (ui && fs.existsSync(path.join(__dirname, '..', ui[1]))) return route.fulfill({contentType: 'application/javascript', body: fs.readFileSync(path.join(__dirname, '..', ui[1]), 'utf8')});
      if (p.startsWith('/vendor/fonts/') && p.endsWith('.woff2')) return route.fulfill({contentType: 'font/woff2', body: fs.readFileSync(path.join(__dirname, '..', p))});
      if (p === '/api/me') return json({id: 'ana', name: 'Ana', email: 'ana@acme.example', role: 'owner', cloud: true});
      if (p === '/api/people') return json({people: [{id: 'ana', name: 'Ana'}]});
      if (p === '/api/employees') return json([]);
      if (p === '/api/issues') return json([]);
      if (p === '/api/status') return json({cloud: true, active: [], queued: [], recent_runs: [], schedules: []});
      if (p === '/api/v2/status') return json({bots: []});
      if (p === '/api/v2/operations') return json({machines: machines(), services: [], agents: []});
      if (p === '/api/v2/models') return json({models: []});
      if (p === '/api/v2/getting-started') {
        const items = [{id: 'signed_in', label: 'Signed in', done: true, optional: false, skipped: false, why: '', href: '', tab: '', action: ''}, model];
        return json({items, done: 1, total: 2, complete: false, dismissed: false, tour_seen: true, cards_dismissed: [], can_build: true, owner: true});
      }
      if (p === '/api/v2/updates/unread') return json({unread: 0});
      if (p === '/api/v2/runners/r1/logins' && req.method() === 'POST') {
        const body = req.postDataJSON(); calls.push({p, body});
        current = login({runtime: body.runtime});
        return json(current);
      }
      const one = p.match(/^\/api\/v2\/runners\/r1\/logins\/l1(\/code|\/cancel)?$/);
      if (one) {
        if (req.method() === 'GET') return json(current);
        const body = req.postDataJSON(); calls.push({p, body});
        if (one[1] === '/cancel') current = {...current, state: 'cancelled', url: '', code: ''};
        if (one[1] === '/code') current = {...current, code_sent: true};
        return json(current);
      }
      if (p.endsWith('/watch')) return route.fulfill({contentType: 'text/event-stream', body: ': fixture\n\n'});
      return json({});
    });
    const errors = [];
    const page = await context.newPage();
    page.on('pageerror', e => errors.push(e.message));
    await page.goto('https://tico-ui.test/#/settings');
    await page.locator('[data-settings-tab="devices"]').click();
    const chips = page.locator('#set-machines .machine-runtime-item');
    await chips.first().waitFor();

    // Only a runtime that is installed and not signed in gets a button, and only Codex and Claude do.
    assert.equal(await page.locator('#set-machines [data-model-login]').count(), 1);
    assert.equal(await page.locator('#set-machines [data-model-login]').getAttribute('data-runtime'), 'codex');
    assert.match(await chips.first().innerText(), /codex · missing\s*Sign in/);

    // ---- Codex: a link and a one-time code, then signed in
    await page.locator('#set-machines [data-model-login]').click();
    const dialog = page.locator('dialog.model-login[open]');
    await dialog.waitFor();
    assert.match(await dialog.locator('h2').innerText(), /Sign in to Codex .* on Runner VM/);
    assert.deepEqual(calls.at(-1), {p: '/api/v2/runners/r1/logins', body: {runtime: 'codex'}});
    await page.waitForFunction(() => /Starting the sign-in on Runner VM/.test(document.querySelector('dialog.model-login [data-status]')?.textContent));
    current = login({state: 'waiting', url: 'https://auth.example/codex/device', code: '3U9T-B3TD5',
      lines: ['1. Open this link in your browser', '2. Enter this one-time code']});
    await dialog.locator('[data-code]').waitFor({timeout: 6000});
    assert.equal(await dialog.locator('[data-code]').innerText(), '3U9T-B3TD5');
    assert.equal(await dialog.locator('[data-link]').getAttribute('href'), 'https://auth.example/codex/device');
    assert.equal(await dialog.locator('[data-link]').getAttribute('rel'), 'noopener noreferrer');
    assert.equal(await dialog.locator('[name=code]').count(), 0);              // Codex has no code to paste back
    assert.equal(await dialog.locator('[data-code]').evaluate(el => getComputedStyle(el).fontFamily.includes('mono')), true);
    await dialog.locator('[data-copy]').click();
    assert.equal(await page.evaluate(() => navigator.clipboard.readText()), '3U9T-B3TD5');
    assert.match(await dialog.locator('[data-status]').innerText(), /Waiting for you to finish/);
    await shot(page, 'codex-code');

    runtimes = {...runtimes, codex: {installed: true, authenticated: 'ready', detail: 'Signed in with ChatGPT'}};
    current = login({state: 'signed_in', lines: ['Successfully logged in']});
    await page.waitForFunction(() => document.querySelector('dialog.model-login [data-status]')?.dataset.state === 'signed_in', null, {timeout: 6000});
    assert.match(await dialog.locator('[data-status]').innerText(), /Signed in\. Codex .* is ready/);
    await dialog.locator('[data-close]').last().click();
    await page.locator('dialog.model-login').waitFor({state: 'detached'});
    // The chip flips once the computer reports it, and the button goes with it.
    await page.waitForFunction(() => /codex · ready/.test(document.querySelector('#set-machines').textContent), null, {timeout: 8000});
    assert.equal(await page.locator('#set-machines [data-model-login]').count(), 0);

    // ---- Claude: a link and a field for the code the sign-in page hands back
    runtimes = {...runtimes, claude: {installed: true, authenticated: 'missing', detail: 'Claude login required'}};
    await page.reload();
    await page.locator('#set-machines [data-settings-tab]').first().waitFor().catch(() => {});
    await page.locator('[data-settings-tab="devices"]').click();
    await page.locator('#set-machines [data-model-login][data-runtime=claude]').click();
    current = login({runtime: 'claude', state: 'waiting', accepts_code: true, url: 'https://claude.example/authorize?state=abc',
      lines: ['Paste code here if prompted >']});
    await dialog.locator('[name=code]').waitFor({timeout: 6000});
    assert.equal(await dialog.locator('[data-code]').count(), 0);
    await dialog.locator('[name=code]').fill('good-code#state-1234');
    await dialog.locator('[data-paste] [type=submit]').click();
    await dialog.locator('[name=code]').waitFor({state: 'detached'});
    assert.deepEqual(calls.at(-1), {p: '/api/v2/runners/r1/logins/l1/code', body: {code: 'good-code#state-1234'}});
    assert.match(await dialog.innerText(), /Code sent/);
    await shot(page, 'claude-paste');

    // ---- a failure shows what the CLI said and offers another try
    current = login({runtime: 'claude', state: 'failed', message: 'The sign-in command stopped without signing in',
      lines: ['Login failed: Request failed with status code 400']});
    await page.waitForFunction(() => document.querySelector('dialog.model-login [data-status]')?.dataset.state === 'failed', null, {timeout: 6000});
    assert.match(await dialog.locator('[data-status]').innerText(), /stopped without signing in/);
    assert.match(await dialog.locator('[data-lines]').innerText(), /Login failed: Request failed/);
    await dialog.locator('[data-retry]').click();
    await page.waitForFunction(() => document.querySelector('dialog.model-login [data-status]')?.dataset.state === 'requested');
    assert.deepEqual(calls.at(-1), {p: '/api/v2/runners/r1/logins', body: {runtime: 'claude'}});

    // ---- a CLI whose words this page does not recognise is shown as it is
    current = login({runtime: 'claude', state: 'waiting', lines: ['Please approve this device in the portal.']});
    await dialog.locator('[data-lines]').waitFor({timeout: 6000});
    assert.match(await dialog.locator('[data-lines]').innerText(), /Please approve this device in the portal\./);

    // ---- closing an unfinished sign-in cancels it; a server-side expiry is said plainly
    await dialog.locator('[data-close]').first().click();
    await page.locator('dialog.model-login').waitFor({state: 'detached'});
    assert.equal(calls.at(-1).p, '/api/v2/runners/r1/logins/l1/cancel');
    await page.locator('#set-machines [data-model-login][data-runtime=claude]').click();
    current = login({runtime: 'claude', state: 'expired'});
    await page.waitForFunction(() => document.querySelector('dialog.model-login [data-status]')?.dataset.state === 'expired', null, {timeout: 6000});
    assert.match(await dialog.locator('[data-status]').innerText(), /ran out of time/);
    await dialog.locator('[data-close]').last().click();

    // ---- the same button on the Getting started step
    await page.goto('https://tico-ui.test/#/getting-started');
    await page.locator('[data-gs-item=model] [data-model-login]').waitFor();
    assert.equal(await page.locator('[data-gs-item=model] [data-model-login]').getAttribute('data-runtime'), 'codex');
    await page.locator('[data-gs-item=model] [data-model-login]').click();
    await page.waitForFunction(() => document.querySelector('dialog.model-login [data-status]')?.dataset.state === 'requested');
    current = login({state: 'waiting', url: 'https://auth.example/codex/device', code: 'AB12-CD345'});
    await dialog.locator('[data-code]').waitFor({timeout: 6000});
    assert.equal(await dialog.locator('[data-code]').innerText(), 'AB12-CD345');
    await dialog.locator('[data-cancel]').click();
    await page.waitForFunction(() => document.querySelector('dialog.model-login [data-status]')?.dataset.state === 'cancelled');
    await shot(page, 'checklist');

    assert.deepEqual(errors, []);
    console.log('PASS: model sign-in dialog: link and code, pasted code, failure, expiry, cancel, chip flips ready.');
  } finally { await browser.close(); }
})().catch(error => { console.error(error); process.exitCode = 1; });
