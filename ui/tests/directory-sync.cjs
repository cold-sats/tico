// Offline regression for Settings > People > Directory sync: pick a source, save credentials once,
// see a dry-run preview before anything changes, confirm the first sync and a mass-leave sync,
// and create the SCIM token. Fixtures only.
const {chromium} = require('playwright');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const html = fs.readFileSync(path.join(__dirname, '../index.html'), 'utf8');
const CONFIG = {environment_id: 'initech', company_name: 'Initech', app_name: 'Initech Hub', assistant_name: 'Ace',
  assistant_bot: 'coo', public_url: 'https://initech.test', runner_url: 'https://initech.test', github_owner: '',
  local: false, release: '', onboarding_needed: false, providers_configured: true};

(async () => {
  const browser = await chromium.launch({headless: true, channel: process.env.TICO_BROWSER_CHANNEL === undefined ? 'chrome' : process.env.TICO_BROWSER_CHANNEL || undefined});
  try {
    const context = await browser.newContext({viewport: {width: 1200, height: 1000}, serviceWorkers: 'block'});
    const calls = [];
    let revision = 0, source = '', confirmed = false, previewBody;
    const directory = () => ({source, filter: {groups: [], org_units: [], domains: []}, interval_minutes: 360, mass_leave_limit: 1,
      confirmed, revision, last: {}, credentials: {google: {configured: source === 'google', hint: 'tico@proj as admin@acme.example'}, entra: {configured: false, hint: ''}},
      scim: {enabled: false, created: '', url: 'https://initech.test/scim/v2'}});
    const plan = () => ({plan: {hash: 'h1', adds: [{name: 'Kim Lee', email: 'kim@acme.example', title: 'Designer', manager: ''}],
      updates: [], restores: [], leaves: [{id: 'bo', email: 'bo@acme.example', name: 'Bo Gone', reason: 'disabled in the directory'},
        {id: 'cy', email: 'cy@acme.example', name: 'Cy Gone', reason: 'no longer in the directory scope'}],
      protected: [{email: 'ana@acme.example', reason: 'the owner is never marked left by sync'}], skipped: []},
      needs_confirmation: {first: !confirmed, mass_leave: true}, mass_leave_limit: 1});
    await context.route('**/*', async route => {
      const request = route.request(), p = new URL(request.url()).pathname, method = request.method();
      const json = body => route.fulfill({contentType: 'application/json', body: JSON.stringify(body)});
      if (p === '/') return route.fulfill({contentType: 'text/html', body: html});
      const module = p.match(/\/tico\/ui\/([^/]+\.js)$/);
      if (module) {
        const file = path.join(__dirname, '..', module[1]);
        if (fs.existsSync(file)) return route.fulfill({contentType: 'application/javascript', body: fs.readFileSync(file, 'utf8')});
      }
      if (p === '/api/me') return json({id: 'ana', name: 'Ana', role: 'owner', cloud: true, email: 'ana@acme.example', credential_access: false, config: CONFIG});
      if (p === '/api/v2/config') return json(CONFIG);
      if (p === '/api/status') return json({cloud: true, keeper_alive: true, health_issues: [], active: [], recent_runs: []});
      if (p === '/api/employees' || p === '/api/issues') return json([]);
      if (p === '/api/people') return json({people: [{id: 'ana', name: 'Ana'}]});
      if (p === '/api/v2/models') return json({models: [], harnesses: [], enabled_providers: [], default: {}});
      if (p === '/api/v2/operations') return json({machines: [], services: [], issues: [], scheduler_enabled: true});
      if (p === '/api/v2/settings/history') return json({changes: [], transitions: []});
      if (p === '/api/v2/access') return json({owner: {email: 'ana@acme.example', revision: 1, person: 'ana'}, people: [
        {id: 'ana', name: 'Ana', email: 'ana@acme.example', title: '', team: '', left: false, owner: true, bot_admin: false, can_sign_in: true}],
        allowed: [], allowed_domains: [], bot_admins: [], revision: 1, proxy: ''});
      if (p === '/api/v2/directory' && method === 'GET') return json(directory());
      if (p === '/api/v2/directory' && method === 'PUT') { calls.push(['save', request.postDataJSON()]); revision += 1; source = request.postDataJSON().source; return json({revision}); }
      if (p === '/api/v2/directory/preview') return json(plan());
      if (p === '/api/v2/directory/sync') { calls.push(['sync', request.postDataJSON()]); confirmed = true; return json({...plan(), applied: true}); }
      if (p === '/api/v2/directory/scim-token') { calls.push(['token']); return json({token: 'scim_secret_value'}); }
      if (p.endsWith('.js')) return route.fulfill({contentType: 'application/javascript', body: ''});
      if (p.endsWith('/watch')) return route.fulfill({contentType: 'text/event-stream', body: ': fixture\n\n'});
      return json({});
    });
    const page = await context.newPage();
    const errors = [];
    page.on('pageerror', e => errors.push(e.message));
    await page.goto('https://tico-ui.test/#/settings');
    await page.getByRole('tab', {name: 'People'}).click();
    const card = page.locator('#directory-sync');
    await card.locator('select[name=source]').waitFor();
    assert.equal(await card.locator('[data-ds-now]').isHidden(), true, 'no sync before a source is saved');

    await card.locator('select[name=source]').selectOption('google');
    assert.match(await card.locator('[data-ds-help]').innerText(), /admin\.directory\.user\.readonly/);
    await card.locator('textarea[name=service_account_json]').fill('{"client_email":"tico@proj","private_key":"-----BEGIN PRIVATE KEY-----"}');
    await card.locator('input[name=admin_email]').fill('admin@acme.example');
    await card.locator('textarea[name=org_units]').fill('/Sales\n/Eng');
    await card.locator('textarea[name=domains]').fill('acme.example');
    await card.getByRole('button', {name: 'Save'}).click();
    await page.waitForFunction(() => document.querySelector('#directory-sync [data-ds-saved]')?.textContent.includes('Credentials saved'));
    const [, saved] = calls.shift();
    assert.equal(saved.source, 'google');
    assert.deepEqual(saved.filter, {groups: [], org_units: ['/Sales', '/Eng'], domains: ['acme.example']});
    assert.equal(saved.credentials.admin_email, 'admin@acme.example');
    assert.equal(await card.locator('textarea[name=service_account_json]').inputValue(), '', 'the saved key is never shown again');

    // Sync now shows the dry run and applies nothing until the review is confirmed.
    await card.getByRole('button', {name: 'Sync now'}).click();
    const preview = card.locator('[data-ds-plan]');
    await preview.waitFor();
    assert.match(await preview.innerText(), /1 to add.*0 to update.*0 to restore.*2 to mark as left/s);
    assert.match(await preview.innerText(), /Bo Gone/);
    assert.match(await preview.innerText(), /owner is never marked left/);
    assert.match(await preview.innerText(), /first sync/);
    assert.match(await preview.innerText(), /more than 1 people/);
    const apply = preview.locator('[data-ds-apply]');
    assert.equal(await apply.isDisabled(), true);
    assert.equal(calls.length, 0);
    await preview.locator('[data-ds-confirm]').check();
    await apply.click();
    await preview.waitFor({state: 'detached'});      // the card re-renders after an applied sync
    await card.locator('select[name=source]').waitFor();
    assert.deepEqual(calls.shift(), ['sync', {confirm: true, plan_hash: 'h1'}]);

    // SCIM: the token is shown once.
    await card.locator('select[name=source]').selectOption('scim');
    assert.match(await card.innerText(), /https:\/\/initech\.test\/scim\/v2/);
    await card.getByRole('button', {name: 'Create token'}).click();
    await card.locator('[data-ds-token-value]').waitFor();
    assert.equal(await card.locator('[data-ds-token-value]').innerText(), 'scim_secret_value');
    assert.deepEqual(errors, []);
    console.log('PASS: Settings > People > Directory sync previews before applying, confirms risky syncs and creates the SCIM token.');
  } finally { await browser.close(); }
})().catch(error => { console.error(error); process.exitCode = 1; });
