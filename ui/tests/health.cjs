// Offline regression for the Health page: it shows exactly what GET /api/v2/health computed, in four
// states (all good, a computer offline, backups local-only, an update available), with the fix
// buttons the server offered, a dot on the way into Settings only while something needs attention, and a
// reduced view for people who are not administrators. Fixtures only - no server.
// TICO_SCREENSHOT=<file.png> saves the review screenshot of the busy state.
const {chromium} = require('playwright');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const html = fs.readFileSync(path.join(__dirname, '../index.html'), 'utf8');

const check = (id, label, status, summary, fixes = []) => ({id, label, status, summary, fixes});
const devices = {label: 'Open Devices', href: '#/settings', tab: 'devices', click: ''};
const good = () => ({
  audience: 'owner', attention: 0, checked: '2026-10-01T10:00:00Z',
  checks: [
    check('version', 'Version', 'ok', 'Running v0.2.0, the latest we know of.'),
    check('computers', 'Computers', 'ok', '2 computers online.'),
    check('models', 'Models', 'ok', 'codex is signed in.'),
    check('waiting', 'Bots waiting', 'ok', 'Every active bot has a computer that is up.'),
    check('queue', 'Work queueing', 'ok', 'No work is waiting long.'),
    check('github', 'GitHub', 'ok', 'Connected to acme.'),
    check('backups', 'Backups', 'ok', 'Copied to s3.'),
    check('signin', 'Sign-in', 'ok', 'People sign in through OpenID Connect.'),
    check('failed', 'Failed runs', 'ok', 'No failed runs in the last day.'),
  ],
  computers: [
    {id: 'r1', label: 'Studio Mac', online: true, last_seen: new Date().toISOString(), platform: 'darwin', runtimes: [{name: 'codex', installed: true, ready: true, signable: false}]},
    {id: 'r2', label: 'Office mini', online: true, last_seen: new Date().toISOString(), platform: 'darwin', runtimes: [{name: 'claude', installed: true, ready: true, signable: false}]}],
  waiting: [], slow: [], failures: [],
});
const swap = (view, id, next) => ({...view, checks: view.checks.map(row => row.id === id ? next : row)});
const states = {
  good,
  offline: () => {
    const view = swap(swap(good(), 'computers', check('computers', 'Computers', 'warn', '1 of 2 online. Offline: Office mini.', [devices])),
      'waiting', check('waiting', 'Bots waiting', 'warn', '1 bot cannot run because their computer is offline: Helper.', [devices]));
    view.computers[1] = {...view.computers[1], online: false, last_seen: new Date(Date.now() - 3 * 3600e3).toISOString(),
      runtimes: [{name: 'codex', installed: true, ready: false, signable: true}]};
    view.waiting = [{bot: 'helper', name: 'Helper', reason: 'computer_offline', computer: 'Office mini', queued: 2, oldest: new Date().toISOString()}];
    return {...view, attention: 2};
  },
  backups: () => ({...swap(good(), 'backups', check('backups', 'Backups', 'warn',
    'Copies stay on this server only. A lost disk loses everything.', [{label: 'Backup settings', href: '#/settings', tab: 'cloud', click: ''}])), attention: 1}),
  update: () => ({...swap(good(), 'version', check('version', 'Version', 'warn', 'v0.3.0 is available. You are on v0.2.0.',
    [{label: 'Update', href: '', tab: '', click: '#new-version'}, {label: 'What is new', href: '#/changelog', tab: '', click: ''}])), attention: 1,
    update: {current: '0.2.0', latest: '0.3.0', available: true, url: 'https://github.com/ticoteam/tico/releases/tag/v0.3.0', published_at: '', name: 'Tico 0.3.0'}}),
  // GitHub is optional and not set up (info, not ok); a computer lists only the harnesses that matter.
  optional: () => {
    const view = swap(good(), 'github', check('github', 'GitHub', 'info', 'Not connected. Optional: connect it to keep bot work in your GitHub.', [devices]));
    view.computers[0] = {...view.computers[0], runtimes: [
      {name: 'codex', installed: true, ready: true, signable: false, needed: true},
      {name: 'claude', installed: false, ready: false, signable: false, needed: true},
      {name: 'gemini', installed: true, ready: false, signable: false, needed: false}]};
    return view;
  },
};

(async () => {
  const browser = await chromium.launch({channel: process.env.TICO_BROWSER_CHANNEL ?? 'chrome', headless: true});
  try {
    const context = await browser.newContext({viewport: {width: 1200, height: 900}, serviceWorkers: 'block'});
    let current = 'good';
    let audience = null;
    const checks = [];
    await context.route('**/*', async route => {
      const req = route.request(), url = new URL(req.url()), p = url.pathname;
      const json = (body, status = 200) => route.fulfill({status, contentType: 'application/json', body: JSON.stringify(body)});
      if (url.origin !== 'http://tico-ui.test') return route.abort();
      if (p === '/') return route.fulfill({contentType: 'text/html', body: html});
      const ui = p.match(/\/tico\/ui\/([^/]+\.js)$/);
      if (ui) { const file = path.join(__dirname, '..', ui[1]); if (fs.existsSync(file)) return route.fulfill({contentType: 'application/javascript', body: fs.readFileSync(file, 'utf8')}); }
      if (p.startsWith('/vendor/fonts/') && p.endsWith('.woff2')) return route.fulfill({contentType: 'font/woff2', body: fs.readFileSync(path.join(__dirname, '..', p))});
      if (p === '/api/employees') return json([{name: 'helper', display_name: 'Helper', host: 'keeper', status: 'active', can_chat: true, team: '', operator: 'ana'}]);
      if (p === '/api/issues') return json([]);
      if (p === '/api/me') return json({id: 'ana', name: 'Ana', email: 'ana@acme.example', role: audience ? 'human' : 'owner', cloud: true});
      if (p === '/api/status') return json({active: [], employees: []});
      if (p === '/api/v2/status') return json({bots: []});
      if (p === '/api/people') return json({people: [{id: 'ana', name: 'Ana'}]});
      if (p === '/api/v2/updates/unread') return json({unread: 0});
      if (p === '/api/v2/updates') return json({updates: [], missed: [], unread: 0, next_before: null, today: {}});
      if (p === '/api/v2/tasks') return json({tasks: []});
      if (p === '/api/v2/getting-started' && req.method() === 'GET') {
        return json({items: [{id: 'signed_in', label: 'Signed in', done: true, optional: false, skipped: false, why: '', href: '', tab: '', action: ''}],
          done: 1, total: 1, complete: true, dismissed: false, tour_seen: true, cards_dismissed: [], can_build: true, owner: true, empty: {}});
      }
      if (p === '/api/v2/system/update/check' && req.method() === 'POST') {
        checks.push(1);
        if (checks.length > 1) return json({error: {code: 'rate_limited', detail: 'Checked a moment ago. Try again in 60 seconds.'}}, 429);
        current = 'update';
        return json(states.update().update);
      }
      if (p === '/api/v2/health') {
        const view = states[current]();
        if (audience === 'human') return json({audience: 'human', attention: 1, checked: view.checked, computers: [], waiting: [], slow: [], failures: [],
          checks: [check('computers', 'Computers', 'warn', '1 of 2 online.'), check('waiting', 'Bots waiting', 'ok', 'Every active bot has a computer that is up.')]});
        return json(view);
      }
      if (p.endsWith('/watch')) return route.fulfill({contentType: 'text/event-stream', body: ': fixture\n\n'});
      return json({});
    });
    const errors = [];
    const open = async (state, viewport) => {
      current = state;
      const page = await context.newPage();
      page.on('pageerror', e => errors.push(state + ': ' + e.message));
      if (viewport) await page.setViewportSize(viewport);
      await page.goto('http://tico-ui.test/#/health');
      await page.locator('#hl-page [data-hl-check]').first().waitFor();
      return page;
    };
    const statuses = page => page.locator('[data-hl-check]').evaluateAll(els => Object.fromEntries(els.map(el => [el.dataset.hlCheck, el.dataset.status])));

    // ---- all good: nothing to look at, no dot; Health is a Settings tab and never in the main rail
    let page = await open('good');
    assert.equal(await page.locator('#hl-summary').textContent(), 'Everything looks fine.');
    assert.equal(Object.values(await statuses(page)).every(s => s === 'ok'), true);
    assert.equal(await page.evaluate(() => location.hash), '#/settings', '#/health redirects into Settings');
    assert.equal(await page.locator('[data-settings-tab=health]').getAttribute('aria-selected'), 'true');
    assert.equal(await page.locator('.side-scroll [href="#/health"], .side-scroll [data-nav=health], #nav-health').count(), 0, 'no Health in the main rail');
    assert.equal(await page.locator('#nav-getting-started').isHidden(), true, 'a finished checklist leaves no replacement');
    assert.equal(await page.locator('.side-scroll .nav-link:visible').evaluateAll(els => els.some(el => /Health/.test(el.textContent))), false);
    assert.equal(await page.locator('[data-hl-alert]:visible').count(), 0);
    assert.equal(await page.locator('.hl-fixes a, .hl-fixes button:not([data-hl-check-updates])').count(), 0);
    assert.equal(await page.locator('[data-hl-check=version] [data-hl-check-updates]').count(), 1, 'the owner can check for updates');
    assert.equal(await page.locator('.hl-computer').count(), 2);
    await page.close();

    // ---- a computer offline: what it is, when it was last seen, which bots are held, and a way to fix it
    page = await open('offline');
    assert.deepEqual([await page.locator('[data-hl-check=computers]').getAttribute('data-status'), await page.locator('[data-hl-check=waiting]').getAttribute('data-status')], ['warn', 'warn']);
    assert.match(await page.locator('.hl-computer[data-online=false]').textContent(), /Office mini offline, last seen 3h ago/);
    assert.match(await page.locator('.hl-computer[data-online=false]').textContent(), /codex: not signed in/);
    assert.equal(await page.locator('.hl-computer[data-online=false] [data-model-login]').count(), 1);
    assert.match(await page.locator('.hl-bots').textContent(), /Helper Office mini is offline, 2 waiting/);
    assert.equal(await page.locator('#account [data-hl-alert]').isVisible(), true, 'the dot is on the way into Settings');
    assert.equal(await page.locator('[data-settings-tab=health] [data-hl-alert]').isVisible(), true);
    assert.equal(await page.locator('.side-scroll [data-hl-alert]').count(), 0, 'nothing in the main navigation');
    assert.equal(await page.locator('[data-settings-tab=health]').getAttribute('aria-label'), 'Health, 2 to look at');
    await page.locator('#account').click();
    assert.equal(await page.locator('#account-menu [data-nav=settings] [data-hl-alert]').isVisible(), true);
    await page.locator('[data-hl-check=computers] a').click();
    await page.waitForFunction(() => location.hash === '#/settings');
    await page.close();

    // ---- backups that only stay on this server
    page = await open('backups');
    assert.equal((await statuses(page)).backups, 'warn');
    assert.match(await page.locator('[data-hl-check=backups]').textContent(), /Copies stay on this server only/);
    assert.equal(await page.locator('[data-hl-check=backups] a').getAttribute('data-gs-tab'), 'cloud');
    await page.close();

    // ---- an update is available: the fix opens the rail's update popover
    page = await open('update');
    assert.match(await page.locator('[data-hl-check=version]').textContent(), /0\.3\.0 is available/);
    assert.equal(await page.locator('[data-hl-check=version] a').getAttribute('href'), '#/changelog');
    await page.evaluate(() => { window.__clicked = 0; const b = document.querySelector('#new-version'); b.addEventListener('click', () => window.__clicked++); });
    await page.locator('[data-hl-check=version] [data-hl-click]').click();
    await page.waitForFunction(() => window.__clicked === 1);
    // The same click must not close the popup it opened (the page closes popups on outside clicks).
    assert.equal(await page.evaluate(() => document.querySelector('#new-version-pop')?.hidden), false);
    await page.close();

    // ---- optional things that are not set up are neutral, and only needed harnesses are red
    page = await open('optional');
    assert.equal((await statuses(page)).github, 'info');
    assert.equal(await page.locator('[data-hl-check=github] .hl-icon').textContent(), 'radio_button_unchecked');
    assert.equal(await page.locator('[data-hl-alert]:visible').count(), 0, 'info is not something to look at');
    const bad = await page.locator('.hl-computer').first().locator('.hl-models li').evaluateAll(els => els.map(el => [el.textContent.split(':')[0], el.classList.contains('hl-model-bad')]));
    assert.deepEqual(bad, [['codex', false], ['claude', true], ['gemini', false]]);   // gemini is installed, not signed in, and nobody needs it
    await page.close();

    // ---- a visit shows what the server knows now, not what the last visit saw; the sidebar follows
    page = await open('good');
    assert.match(await page.locator('[data-hl-check=version]').textContent(), /Running v0\.2\.0/);
    assert.equal(await page.locator('#new-version-wrap').isHidden(), true);
    current = 'update';                                  // the server learns of 0.3.0 meanwhile
    await page.evaluate(() => { location.hash = '#/goals'; });
    await page.waitForFunction(() => location.hash === '#/goals');
    await page.evaluate(() => { location.hash = '#/health'; });
    await page.waitForFunction(() => /0\.3\.0 is available/.test(document.querySelector('[data-hl-check=version]')?.textContent || ''));
    await page.waitForFunction(() => !document.querySelector('#new-version-wrap').hidden);
    assert.match(await page.locator('#new-version-label').textContent(), /v0\.3\.0/);
    await page.close();

    // ---- the owner can ask the server to look now, and sees the answer beside the Version line
    current = 'good'; checks.length = 0;
    page = await open('good');
    await page.locator('[data-hl-check=version] [data-hl-check-updates]').click();
    await page.waitForFunction(() => /v0\.3\.0 is available\. You are on v0\.2\.0/.test(document.querySelector('[data-hl-check=version]')?.textContent || ''));
    // One line: the Version line says it, and the check adds no second copy of the answer.
    const said = await page.locator('[data-hl-check=version]').textContent();
    assert.equal((said.match(/is available/g) || []).length, 1, said);
    assert.equal(await page.locator('.hl-check-result').count(), 0);
    await page.locator('[data-hl-check=version] [data-hl-check-updates]').click();       // too soon: the server says so
    await page.waitForFunction(() => /Try again in 60 seconds/.test(document.querySelector('.hl-check-result')?.textContent || ''));
    assert.equal(await page.locator('.hl-check-result.err').count(), 1);
    await page.close();
    audience = 'human';
    page = await open('good');
    assert.equal(await page.locator('[data-hl-check-updates]').count(), 0, 'only the owner checks');
    await page.close();
    audience = null;

    // ---- the review screenshot: several things at once
    if (process.env.TICO_SCREENSHOT) {
      states.busy = () => {
        const view = states.offline();
        return {...swap(swap(view, 'backups', states.backups().checks.find(row => row.id === 'backups')), 'version',
          states.update().checks.find(row => row.id === 'version')), attention: 4};
      };
      page = await open('busy');
      await page.screenshot({path: process.env.TICO_SCREENSHOT, fullPage: true});
      await page.close();
    }

    // ---- everyone else: counts only, no fix buttons
    audience = 'human';
    page = await open('offline');
    assert.deepEqual(Object.keys(await statuses(page)), ['computers', 'waiting']);
    assert.equal(await page.locator('.hl-fixes a, .hl-fixes button, .hl-computer').count(), 0);
    await page.close();

    // ---- a phone: nothing spills sideways
    audience = null;
    page = await open('offline', {width: 390, height: 844});
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true);
    await page.close();

    assert.deepEqual(errors, []);
    console.log('PASS: health shows what the server computed, with fixes, a Settings dot only when something needs attention, and a reduced view for others.');
  } finally { await browser.close(); }
})().catch(e => { console.error(e); process.exitCode = 1; });
