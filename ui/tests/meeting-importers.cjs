// Offline regression for Settings > Cloud services > Meeting importers: the owner sees the four
// importers with their status, counts and last error, turns one on for a computer, and finds the
// credential setup. A person who is not the owner never sees the card. Fixtures only.
const {chromium} = require('playwright');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const html = fs.readFileSync(path.join(__dirname, '../index.html'), 'utf8');
const importer = (source, name, keys, extra = {}) => ({source, name, enabled: false, runner_id: '', runner_label: '', status: 'off',
  last_success: null, last_attempt: null, last_import: null, imported_total: 0, error_code: '', error: '',
  setup: {file: 'secrets/' + source + '.env', keys, doc: 'docs/meetings.md#' + source}, ...extra});
(async () => {
  const browser = await chromium.launch({channel: process.env.TICO_BROWSER_CHANNEL ?? 'chrome', headless: true});
  try {
    for (const role of ['owner', 'human']) {
      const page = await browser.newPage({viewport: {width: 1300, height: 900}, serviceWorkers: 'block'});
      const errors = [];
      page.on('pageerror', e => errors.push(e.message));
      let saved = null, listCalls = 0;
      const rows = [importer('fireflies', 'Fireflies', ['FIREFLIES_API_KEY'], {enabled: true, runner_id: 'r1', runner_label: 'Studio Mac',
          status: 'error', error_code: 'auth_failed', error: 'The tool refused the credential.', imported_total: 12,
          last_success: '2026-09-28T10:00:00Z', last_import: '2026-09-28T09:00:00Z'}),
        importer('zoom', 'Zoom', ['ZOOM_ACCOUNT_ID', 'ZOOM_CLIENT_ID', 'ZOOM_CLIENT_SECRET']),
        importer('google-meet', 'Google Meet', ['GOOGLE_MEET_USERS', 'GOOGLE_SERVICE_ACCOUNT_FILE']),
        importer('granola', 'Granola', ['GRANOLA_API_KEY'])];
      await page.route('**/*', route => {
        const url = new URL(route.request().url()), p = url.pathname;
        const json = body => route.fulfill({contentType: 'application/json', body: JSON.stringify(body)});
        if (url.origin !== 'https://tico-ui.test') return route.abort();
        const ui = p.match(/\/tico\/ui\/([^/]+\.js)$/);
        if (ui && fs.existsSync(path.join(__dirname, '..', ui[1])))
          return route.fulfill({contentType: 'application/javascript', body: fs.readFileSync(path.join(__dirname, '..', ui[1]), 'utf8')});
        if (p === '/') return route.fulfill({contentType: 'text/html', body: html});
        if (p === '/api/me') return json({id: 'ana', role, name: 'Ana', email: 'ana@example.test', cloud: true});
        if (p === '/api/v2/meeting-importers') { listCalls++;
          return json({importers: rows, computers: [{id: 'r1', label: 'Studio Mac', platform: 'darwin', online: true}, {id: 'r2', label: 'Cloud box', platform: 'linux', online: false}]}); }
        const set = p.match(/^\/api\/v2\/meeting-importers\/([a-z-]+)$/);
        if (set) { saved = {source: set[1], body: JSON.parse(route.request().postData())};
          const row = rows.find(r => r.source === set[1]); Object.assign(row, {enabled: saved.body.enabled, runner_id: saved.body.runner_id,
            runner_label: 'Cloud box', status: 'waiting', error: ''}); return json({ok: true}); }
        if (p === '/api/people') return json({people: [{id: 'ana', name: 'Ana'}]});
        if (p === '/api/employees' || p === '/api/issues') return json([]);
        if (p === '/api/status') return json({cloud: true, active: [], queued: [], recent_runs: [], schedules: []});
        return json({});
      });
      await page.goto('https://tico-ui.test/#/settings');
      await page.locator('[data-settings-tab="cloud"]').click();
      if (role !== 'owner') {
        assert.equal(await page.locator('#settings-meeting-importers').count(), 0, 'only the owner sees the card');
        assert.equal(listCalls, 0);
        assert.deepEqual(errors, []);
        await page.close();
        continue;
      }
      const card = page.locator('#settings-meeting-importers');
      await card.locator('form[data-importer]').first().waitFor();
      assert.deepEqual(await card.locator('form[data-importer] strong').allInnerTexts(), ['Fireflies', 'Zoom', 'Google Meet', 'Granola']);
      const fireflies = card.locator('form[data-importer="fireflies"]');
      assert.match(await fireflies.innerText(), /Error/);
      assert.match(await fireflies.locator('[data-imp-error]').innerText(), /refused the credential/);
      assert.match(await fireflies.locator('[data-imp-facts]').innerText(), /12 imported/);
      assert.equal(await fireflies.locator('select[name="runner"]').inputValue(), 'r1');
      assert.equal(await fireflies.locator('input[name="enabled"]').isChecked(), true);
      const setup = card.locator('form[data-importer="zoom"] details');
      assert.equal(await setup.evaluate(d => d.open), false);
      await setup.locator('summary').click();
      const text = await setup.innerText();
      assert.match(text, /secrets\/zoom\.env/);
      for (const key of ['ZOOM_ACCOUNT_ID', 'ZOOM_CLIENT_ID', 'ZOOM_CLIENT_SECRET']) assert.match(text, new RegExp(key + '='));
      assert.match(text, /docs\/meetings\.md#zoom/);
      // The card never asks for a secret itself.
      assert.equal(await card.locator('input[type="password"], input[name*="secret" i], input[name*="key" i]').count(), 0);
      const granola = card.locator('form[data-importer="granola"]');
      await granola.locator('input[name="enabled"]').check();
      await granola.locator('select[name="runner"]').selectOption('r2');
      await granola.getByRole('button', {name: 'Save Granola'}).click();
      await page.waitForFunction(() => document.querySelector('form[data-importer="granola"] [data-imp-status]')?.textContent === 'Waiting for the computer');
      assert.deepEqual(saved, {source: 'granola', body: {enabled: true, runner_id: 'r2'}});
      assert.match(await granola.innerText(), /Cloud box/);
      assert.deepEqual(errors, []);
      await page.close();
    }
    console.log('PASS: Settings > Meeting importers lists the four importers, saves a computer, shows status, counts, error and setup, owner only.');
  } finally { await browser.close(); }
})().catch(error => { console.error(error); process.exitCode = 1; });
