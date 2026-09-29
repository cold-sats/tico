// Offline regression for how each computer's version shows on Health and in Settings > Devices
// (backend/runner_versions.py): up to date, updating, needs update, incompatible (bots paused), the
// last update error, and nothing extra for a computer that has not reported a release. Fixtures only.
// TICO_SCREENSHOT=<file.png> saves the review screenshot of the Health page.
const {chromium} = require('playwright');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const html = fs.readFileSync(path.join(__dirname, '../index.html'), 'utf8');

const LABELS = {current: 'Up to date', updating: 'Updating', needs_update: 'Needs update', incompatible: 'Incompatible (bots paused)', unknown: 'Version not reported'};
const update = (state, release, extra = {}) => ({release, kind: 'mac', state, label: LABELS[state], update_state: '', target: '0.3.0', error: '', min_runner: '0.2.0', ...extra});
const now = () => new Date().toISOString();
const fleet = [
  {id: 'r1', label: 'Studio Mac', update: update('current', '0.3.0')},
  {id: 'r2', label: 'Build box', update: update('updating', '0.2.5', {kind: 'docker', update_state: 'updating'})},
  {id: 'r3', label: 'Office mini', update: update('needs_update', '0.2.5', {update_state: 'blocked', error: 'the checkout has 2 changed files; commit or stash them'})},
  {id: 'r4', label: 'Old laptop', update: update('incompatible', '0.1.0')},
  {id: 'r5', label: 'Pinned Mac', update: update('needs_update', '0.2.5', {update_state: 'pinned'})},
  {id: 'r6', label: 'Fresh box', update: update('unknown', '', {kind: ''})},
];
const health = {
  audience: 'owner', attention: 2, checked: now(), waiting: [], slow: [], failures: [],
  checks: [{id: 'runners', label: 'Runner versions', status: 'bad', summary: 'Old laptop cannot work with 0.3.0 and its bots are paused until it updates.',
    fixes: [{label: 'Open Devices', href: '#/settings', tab: 'devices', click: ''}]}],
  computers: fleet.map(m => ({id: m.id, label: m.label, online: true, last_seen: now(), platform: 'darwin', runtimes: [], update: m.update})),
};
const machines = fleet.map(m => ({id: m.id, label: m.label, operator: 'ana', last_seen: now(), revoked_at: null, platform: 'darwin',
  version: '0.5.4', bots: [], readiness: {schema_version: 1, runtimes: {}, bots: {}}, update: m.update}));

(async () => {
  const browser = await chromium.launch({channel: process.env.TICO_BROWSER_CHANNEL ?? 'chrome', headless: true});
  try {
    const context = await browser.newContext({viewport: {width: 1200, height: 1100}, serviceWorkers: 'block'});
    await context.route('**/*', async route => {
      const req = route.request(), url = new URL(req.url()), p = url.pathname;
      const json = (body, status = 200) => route.fulfill({status, contentType: 'application/json', body: JSON.stringify(body)});
      if (url.origin !== 'http://tico-ui.test') return route.abort();
      if (p === '/') return route.fulfill({contentType: 'text/html', body: html});
      const ui = p.match(/\/tico\/ui\/([^/]+\.js)$/);
      if (ui && fs.existsSync(path.join(__dirname, '..', ui[1]))) return route.fulfill({contentType: 'application/javascript', body: fs.readFileSync(path.join(__dirname, '..', ui[1]), 'utf8')});
      if (p.startsWith('/vendor/fonts/') && p.endsWith('.woff2')) return route.fulfill({contentType: 'font/woff2', body: fs.readFileSync(path.join(__dirname, '..', p))});
      if (p === '/api/me') return json({id: 'ana', name: 'Ana', email: 'ana@acme.example', role: 'owner', cloud: true});
      if (p === '/api/people') return json({people: [{id: 'ana', name: 'Ana'}]});
      if (p === '/api/employees' || p === '/api/issues') return json([]);
      if (p === '/api/status') return json({cloud: true, active: [], queued: [], recent_runs: [], schedules: []});
      if (p === '/api/v2/status') return json({bots: []});
      if (p === '/api/v2/operations') return json({machines, services: [], agents: []});
      if (p === '/api/v2/health') return json(health);
      if (p === '/api/v2/getting-started') return json({items: [{id: 'signed_in', label: 'Signed in', done: true, optional: false, skipped: false, why: '', href: '', tab: '', action: ''}],
        done: 1, total: 1, complete: true, dismissed: false, tour_seen: true, cards_dismissed: [], can_build: true, owner: true, empty: {}});
      if (p === '/api/v2/updates/unread') return json({unread: 0});
      if (p.endsWith('/watch')) return route.fulfill({contentType: 'text/event-stream', body: ': fixture\n\n'});
      return json({});
    });
    const errors = [];
    const page = await context.newPage();
    page.on('pageerror', e => errors.push(e.message));
    const shown = (scope, id) => page.locator(`${scope} [data-runner-update]`).evaluateAll((els, want) => els.map(el => el.dataset.runnerUpdate), id);

    // ---- Health: every computer says where it stands
    await page.goto('http://tico-ui.test/#/health');
    await page.locator('.hl-computer').first().waitFor();
    assert.deepEqual(await shown('.hl-computers'), ['current', 'updating', 'needs_update', 'incompatible', 'needs_update', 'unknown']);
    const row = label => page.locator('.hl-computer', {hasText: label});
    assert.match(await row('Studio Mac').innerText(), /Up to date\s+Tico 0\.3\.0 · mac/);
    assert.match(await row('Build box').innerText(), /Updating\s+Tico 0\.2\.5 · docker/);
    assert.match(await row('Office mini').innerText(), /Needs update to 0\.3\.0/);
    assert.match(await row('Office mini').locator('[data-runner-error]').innerText(), /Last update error: the checkout has 2 changed files/);
    assert.match(await row('Old laptop').innerText(), /Incompatible \(bots paused\)/);
    assert.match(await row('Old laptop').locator('[data-runner-paused]').innerText(), /Needs Tico 0\.2\.0 or later; it takes no work/);
    assert.match(await row('Pinned Mac').innerText(), /pinned/);
    assert.match(await row('Fresh box').innerText(), /Version not reported/);
    assert.equal(await page.locator('.hl-computer [data-runner-error]').count(), 1);
    assert.equal(await page.locator('.hl-computer [data-runner-paused]').count(), 1);
    assert.equal(await row('Old laptop').locator('.pill').evaluate(el => el.classList.contains('fail')), true);
    assert.equal(await row('Studio Mac').locator('.pill').evaluate(el => el.classList.contains('ok')), true);
    assert.equal(await page.locator('[data-hl-check=runners]').getAttribute('data-status'), 'bad');
    if (process.env.TICO_SCREENSHOT) await page.screenshot({path: process.env.TICO_SCREENSHOT});

    // ---- Settings > Devices: the same states beside the version each computer reports
    await page.goto('http://tico-ui.test/#/settings');
    await page.locator('[data-settings-tab="devices"]').click();
    await page.locator('#set-machines .machine-card').first().waitFor();
    assert.deepEqual(await shown('#set-machines'), ['current', 'updating', 'needs_update', 'incompatible', 'needs_update', 'unknown']);
    const card = label => page.locator('#set-machines .machine-card', {hasText: label});
    assert.match(await card('Old laptop').innerText(), /Incompatible \(bots paused\)/);
    assert.match(await card('Office mini').locator('[data-runner-error]').innerText(), /commit or stash them/);
    assert.equal(await page.locator('#set-machines [data-runner-error]').count(), 1);

    // ---- a server that reports nothing new (an older one) draws no version line at all
    machines.forEach(m => delete m.update);
    await page.reload();
    await page.locator('[data-settings-tab="devices"]').click();
    await page.locator('#set-machines .machine-card').first().waitFor();
    assert.equal(await page.locator('#set-machines [data-runner-update]').count(), 0);
    assert.deepEqual(errors, []);
  } finally {
    await browser.close();
  }
})().catch(error => { console.error(error); process.exit(1); });
