// Offline browser regression for Settings -> People: the owner adds and edits people, marks one as
// left, sets the allow list with the revision it read, and transfers ownership through a confirm
// dialog that only enables once the new owner's email is typed. Fixtures only.
const {chromium} = require('playwright');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const html = fs.readFileSync(path.join(__dirname, '../index.html'), 'utf8');

const CONFIG = {environment_id: 'initech', company_name: 'Initech', app_name: 'Initech Hub',
  assistant_name: 'Ace', assistant_bot: 'coo', public_url: 'https://initech.test',
  runner_url: 'https://initech.test', github_owner: '', local: false, release: '',
  onboarding_needed: false, providers_configured: true};

(async () => {
  const browser = await chromium.launch({headless: true, channel: process.env.TICO_BROWSER_CHANNEL === undefined ? 'chrome' : process.env.TICO_BROWSER_CHANNEL || undefined});
  try {
    const context = await browser.newContext({viewport: {width: 1200, height: 900}, serviceWorkers: 'block'});
    const calls = [];
    let owner = 'ana@acme.example', proxy = 'cloudflare', revision = 3;
    let people = [
      {id: 'ana', name: 'Ana Rivera', email: 'ana@acme.example', title: 'CEO', team: 'leadership'},
      {id: 'ben', name: 'Ben Cole', email: 'ben@acme.example', title: '', team: ''}];
    const access = () => ({
      owner: {email: owner, revision: 1, person: 'ana'},
      people: people.map(p => {
        const isOwner = p.email === owner, role = isOwner ? 'owner' : p.admin ? 'admin' : 'member';
        return {...p, left: !!p.left, owner: isOwner, role, bot_admin: role === 'admin', create_bots: p.create_bots !== false,
                add_people: p.add_people === undefined ? true : !!p.add_people, add_people_default: p.add_people === undefined,
                can_sign_in: !p.left && !!p.email};
      }),
      allowed: ['ana@acme.example'], allowed_domains: [], admins: [], bot_admins: [], member_bot_limit: 5,
      company_domains: ['acme.example'], company_domain_source: 'owner', revision, proxy});
    const me = {id: 'ana', name: 'Ana Rivera', role: 'owner', cloud: true, email: 'ana@acme.example', credential_access: false, config: CONFIG};
    await context.route('**/*', async route => {
      const request = route.request(), p = new URL(request.url()).pathname, method = request.method();
      const json = body => route.fulfill({contentType: 'application/json', body: JSON.stringify(body)});
      if (p === '/') return route.fulfill({contentType: 'text/html', body: html});
      const module = p.match(/\/tico\/ui\/([^/]+\.js)$/);
      if (module) {
        const file = path.join(__dirname, '..', module[1]);
        if (fs.existsSync(file)) return route.fulfill({contentType: 'application/javascript', body: fs.readFileSync(file, 'utf8')});
      }
      if (p === '/api/me') return json(me);
      if (p === '/api/v2/config') return json(CONFIG);
      if (p === '/api/status') return json({cloud: true, keeper_alive: true, health_issues: [], active: [], recent_runs: []});
      if (p === '/api/employees' || p === '/api/issues') return json([]);
      if (p === '/api/people') return json({people});
      if (p === '/api/v2/models') return json({models: [], harnesses: [], enabled_providers: [], default: {}});
      if (p === '/api/v2/operations') return json({machines: [], services: [], issues: [], scheduler_enabled: true});
      if (p === '/api/v2/settings/history') return json({changes: [], transitions: []});
      if (p === '/api/v2/access' && method === 'GET') return json(access());
      if (p === '/api/v2/access/people' && method === 'POST') {
        const body = request.postDataJSON(); calls.push(['add', body]);
        people.push({id: body.name.toLowerCase().split(' ')[0], ...body}); return json({person: 'x'});
      }
      let m;
      if ((m = p.match(/^\/api\/v2\/access\/people\/([^/]+)$/))) {
        const body = request.postDataJSON(); calls.push(['edit', m[1], body]);
        const row = people.find(x => x.id === m[1]);
        if ('role' in body) row.admin = body.role === 'admin';
        if ('create_bots' in body) row.create_bots = body.create_bots;
        if ('add_people' in body) row.add_people = body.add_people === 'default' ? undefined : body.add_people;
        if ('left' in body) row.left = body.left;
        Object.assign(row, Object.fromEntries(Object.entries(body).filter(([k]) => ['name', 'title', 'team', 'email'].includes(k))));
        return json({person: m[1]});
      }
      if ((m = p.match(/^\/api\/v2\/people\/([^/]+)$/)) && method === 'POST') {
        const body = request.postDataJSON(); calls.push(['left', m[1], body]);
        people.find(x => x.id === m[1]).left = true; return json({});
      }
      if (p === '/api/v2/access/limits') { calls.push(['limits', request.postDataJSON()]); return json({}); }
      if (p === '/api/v2/access/allow') {
        calls.push(['allow', request.postDataJSON()]); revision += 1; return json({revision});
      }
      if (p === '/api/v2/access/owner') {
        calls.push(['owner', request.postDataJSON()]); owner = people.find(x => x.id === request.postDataJSON().person).email;
        return json({owner});
      }
      if (p.endsWith('.js')) return route.fulfill({contentType: 'application/javascript', body: ''});
      if (p.endsWith('/watch')) return route.fulfill({contentType: 'text/event-stream', body: ': fixture\n\n'});
      return json({});
    });
    const page = await context.newPage();
    const errors = [];
    page.on('pageerror', e => errors.push(e.message));

    await page.goto('https://tico-ui.test/#/settings');
    await page.getByRole('tab', {name: 'People'}).click();
    await page.locator('tr[data-person=ben]').waitFor();
    assert.match(await page.locator('#people-proxy-note').textContent(), /Cloudflare Access/);
    assert.match(await page.locator('tr[data-person=ana]').textContent(), /Owner/);
    assert.equal(await page.locator('tr[data-person=ana] [data-person-act=owner]').count(), 0);

    // Add a person.
    await page.locator('#people-add').click();
    const dialog = page.locator('#people-dialog');
    await dialog.locator('[name=name]').fill('Cy Dunn');
    await dialog.locator('[name=email]').fill('cy@acme.example');
    await dialog.locator('[name=team]').fill('ops');
    await dialog.locator('[type=submit]').click();
    await page.locator('tr[data-person=cy]').waitFor();
    assert.deepEqual(calls.shift(), ['add', {name: 'Cy Dunn', email: 'cy@acme.example', title: '', team: 'ops'}]);

    // Bot admin toggles; a person marked as left goes through the profile endpoint that ends tokens.
    await page.locator('tr[data-person=ben] [data-person-act=admin]').click();
    await page.locator('tr[data-person=ben] [data-role=admin]').waitFor();
    assert.deepEqual(calls.shift(), ['edit', 'ben', {role: 'admin'}]);
    assert.match(await page.locator('tr[data-person=ana]').textContent(), /Owner/);
    assert.match(await page.locator('tr[data-person=ben]').textContent(), /Admin/);
    assert.match(await page.locator('[data-company-domain]').textContent(), /acme\.example/);
    // What a member may do: switched off per person, by an owner or an admin.
    await page.locator('tr[data-person=cy] [data-person-act=edit]').click();
    assert.equal(await dialog.locator('[name=create_bots]').isChecked(), true);
    assert.equal(await dialog.locator('[name=add_people]').inputValue(), 'default');
    await dialog.locator('[name=create_bots]').uncheck();
    await dialog.locator('[name=add_people]').selectOption('no');
    await dialog.locator('[type=submit]').click();
    await page.waitForFunction(() => /adds people/.test(document.querySelector('tr[data-person=cy]').textContent) === false);
    assert.deepEqual(calls.shift(), ['edit', 'cy', {name: 'Cy Dunn', email: 'cy@acme.example', title: '', team: 'ops',
      create_bots: false, add_people: false}]);
    await page.locator('#member-bot-limit').fill('3');
    await page.locator('#member-bot-limit-save').click();
    for (let i = 0; i < 50 && !calls.length; i += 1) await page.waitForTimeout(50);
    assert.deepEqual(calls.shift(), ['limits', {member_bot_limit: 3}]);
    await page.locator('tr[data-person=cy] [data-person-act=left]').click();
    assert.match(await dialog.textContent(), /API tokens stop working/);
    await dialog.locator('[type=submit]').click();
    await page.locator('tr[data-person=cy]', {hasText: 'Left'}).waitFor();
    assert.deepEqual(calls.shift(), ['left', 'cy', {left: true}]);
    await page.locator('tr[data-person=cy] [data-person-act=restore]').click();
    await page.locator('tr[data-person=cy]', {hasText: 'Can sign in'}).waitFor();
    assert.deepEqual(calls.shift(), ['edit', 'cy', {left: false}]);

    // The allow list saves with the revision it was read at.
    await page.locator('#allow-domains').fill('acme.example, partner.example');
    await page.locator('#allow-save').click();
    await page.waitForFunction(() => document.querySelector('#allow-save') && !document.querySelector('#allow-status').textContent.includes('Saving'));
    assert.deepEqual(calls.shift(), ['allow', {allowed: ['ana@acme.example'],
      allowed_domains: ['acme.example', 'partner.example'], expected_revision: 3}]);

    // Ownership moves only after the new owner's email is typed.
    await page.locator('tr[data-person=ben] [data-person-act=owner]').click();
    const go = dialog.locator('[type=submit]');
    assert.equal(await go.isDisabled(), true);
    await dialog.locator('[name=typed]').fill('someone@else.example');
    assert.equal(await go.isDisabled(), true);
    await dialog.locator('[name=typed]').fill('BEN@acme.example');
    await dialog.locator('[name=admin]').check();
    assert.equal(calls.length, 0);
    await go.click();
    for (let i = 0; i < 50 && !calls.length; i += 1) await page.waitForTimeout(50);
    assert.deepEqual(calls.shift(), ['owner', {person: 'ben', previous_owner_bot_admin: true,
      expected_revision: 1, confirm: true}]);
    assert.deepEqual(errors, []);
    console.log('PASS: People tab adds, edits and retires people, saves the allow list and transfers ownership behind a confirm.');
  } finally {
    await browser.close();
  }
})();
