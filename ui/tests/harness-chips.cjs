// Offline regression for the tools on a computer (Settings > Devices): each model CLI shows its
// version, pin and update state; only the owner gets Update / Pin to this version / Resume updates,
// and only for installs the runner manages. Fixtures only - no server.
// TICO_SCREENSHOT_DIR=<dir> saves the review screenshot.
const {chromium} = require('playwright');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const html = fs.readFileSync(path.join(__dirname, '../index.html'), 'utf8');
const shots = process.env.TICO_SCREENSHOT_DIR;

const harness = (extra = {}) => ({name: 'Codex', runtime: 'codex', installed: true, version: '0.158.0', managed: true, source: 'tools',
  pinned: false, pin: '', authenticated: 'ready', update_available: false, latest: '0.158.0', wanted: true, state: 'idle', detail: '', ...extra});

(async () => {
  const browser = await chromium.launch({channel: process.env.TICO_BROWSER_CHANNEL ?? 'chrome', headless: true});
  try {
    const errors = [];
    const run = async (role, harnesses, actions = []) => {
      const context = await browser.newContext({viewport: {width: 1200, height: 900}, serviceWorkers: 'block'});
      const calls = [];
      const machine = {id: 'r1', label: 'Runner VM', operator: 'ana', last_seen: new Date().toISOString(), revoked_at: null, platform: 'linux',
        version: '0.5.4', bots: [], harness_actions: actions, readiness: {schema_version: 1, runtimes: {}, bots: {}, harnesses}};
      await context.route('**/*', async route => {
        const req = route.request(), url = new URL(req.url()), p = url.pathname;
        const json = (body, status = 200) => route.fulfill({status, contentType: 'application/json', body: JSON.stringify(body)});
        if (url.origin !== 'https://tico-ui.test') return route.abort();
        if (p === '/') return route.fulfill({contentType: 'text/html', body: html});
        const ui = p.match(/\/tico\/ui\/([^/]+\.js)$/);
        if (ui && fs.existsSync(path.join(__dirname, '..', ui[1]))) return route.fulfill({contentType: 'application/javascript', body: fs.readFileSync(path.join(__dirname, '..', ui[1]), 'utf8')});
        if (p.startsWith('/vendor/fonts/') && p.endsWith('.woff2')) return route.fulfill({contentType: 'font/woff2', body: fs.readFileSync(path.join(__dirname, '..', p))});
        if (p === '/api/me') return json({id: 'ana', name: 'Ana', email: 'ana@acme.example', role, cloud: true});
        if (p === '/api/people') return json({people: [{id: 'ana', name: 'Ana'}]});
        if (p === '/api/employees' || p === '/api/issues') return json([]);
        if (p === '/api/status') return json({cloud: true, active: [], queued: [], recent_runs: [], schedules: []});
        if (p === '/api/v2/status') return json({bots: []});
        if (p === '/api/v2/operations') return json({machines: [machine], services: [], agents: []});
        if (p === '/api/v2/models') return json({models: []});
        if (p === '/api/v2/getting-started') return json({items: [], done: 0, total: 0, complete: true, dismissed: true, tour_seen: true, cards_dismissed: [], can_build: true, owner: role === 'owner'});
        if (p === '/api/v2/updates/unread') return json({unread: 0});
        if (p === '/api/v2/runners/r1/harness-actions' && req.method() === 'POST') { calls.push(req.postDataJSON()); return json({id: 'x', state: 'requested'}); }
        if (p.endsWith('/watch')) return route.fulfill({contentType: 'text/event-stream', body: ': fixture\n\n'});
        return json({});
      });
      const page = await context.newPage();
      page.on('pageerror', e => errors.push(e.message));
      await page.goto('https://tico-ui.test/#/settings');
      await page.locator('[data-settings-tab="devices"]').click();
      await page.locator('#set-machines .machine-harness-item').first().waitFor();
      return {page, calls, context};
    };
    const chip = (page, id) => page.locator(`#set-machines [data-harness-chip="${id}"]`);

    // ---- the owner
    const owner = await run('owner', {
      codex: harness({update_available: true, latest: '0.160.0'}),
      'claude-code': harness({name: 'Claude Code', runtime: 'claude', version: '2.1.284', pinned: true, pin: '2.1.284'}),
      'gemini-cli': harness({name: 'Gemini CLI', runtime: 'gemini', version: '0.61.0', managed: false, source: 'path'}),
      grok: harness({name: 'Grok Build', runtime: 'grok', installed: false, version: '', managed: false, source: '', authenticated: 'missing'}),
      pi: harness({name: 'pi (multi-provider)', runtime: 'pi', installed: false, version: '', state: 'installing'}),
      nothing: harness({name: 'Unused', installed: false, wanted: false, version: ''}),
    });
    const page = owner.page;
    assert.match(await chip(page, 'codex').innerText(), /Codex 0\.158\.0 · 0\.160\.0 available\s*Update\s*Pin to this version/);
    assert.match(await chip(page, 'claude-code').innerText(), /Claude Code 2\.1\.284 · pinned\s*Resume updates/);
    assert.equal(await chip(page, 'claude-code').locator('[data-harness-action=pin]').count(), 0);
    assert.equal(await chip(page, 'claude-code').locator('[data-harness-action=update]').count(), 0, 'no update offered when none is available');
    assert.equal(await chip(page, 'gemini-cli').locator('button').count(), 0, 'an install outside Tico is not ours to update');
    assert.match(await chip(page, 'grok').innerText(), /Grok Build not installed/);
    assert.match(await chip(page, 'pi').innerText(), /installing/);
    assert.equal(await chip(page, 'pi').locator('button').count(), 0, 'no buttons while it installs');
    assert.equal(await chip(page, 'nothing').count(), 0, 'a harness nobody needs is not shown');
    assert.equal(await page.locator('#set-machines .machine-harness-item').count(), 5);
    if (shots) await page.screenshot({path: path.join(shots, 'harness-chips.png')});

    await chip(page, 'codex').locator('[data-harness-action=pin]').click();
    await page.waitForFunction(() => document.querySelector('[data-harness-action=update]:not([disabled])'));
    await chip(page, 'codex').locator('[data-harness-action=update]').click();
    await chip(page, 'claude-code').locator('[data-harness-action=unpin]').click();
    await page.waitForTimeout(300);
    assert.deepEqual(owner.calls, [{harness: 'codex', action: 'pin'}, {harness: 'codex', action: 'update'}, {harness: 'claude-code', action: 'unpin'}]);
    await owner.context.close();

    // ---- a request already in flight shows as requested and cannot be sent twice
    const waiting = await run('owner', {codex: harness({update_available: true, latest: '0.160.0'})},
      [{id: 'a1', runner_id: 'r1', harness: 'codex', action: 'update', state: 'running', message: ''}]);
    const button = chip(waiting.page, 'codex').locator('[data-harness-action=update]');
    assert.equal(await button.innerText(), 'Requested');
    assert.equal(await button.isDisabled(), true);
    await waiting.context.close();

    // ---- anyone else sees the state and no controls
    const person = await run('human', {codex: harness({update_available: true, latest: '0.160.0'})});
    assert.match(await chip(person.page, 'codex').innerText(), /Codex 0\.158\.0 · 0\.160\.0 available/);
    assert.equal(await person.page.locator('#set-machines [data-harness-action]').count(), 0);
    await person.context.close();

    assert.deepEqual(errors, []);
    console.log('Device harness chips: versions, pin, owner-only Update / Pin / Resume, unmanaged and pending states passed');
  } finally { await browser.close(); }
})().catch(error => { console.error(error); process.exitCode = 1; });
