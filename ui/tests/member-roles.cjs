// Offline regression for members, bot owners and BotOps' Confirm cards (docs/permissions.md): Settings > Bots
// lists who owns each bot and saves co-owners as a diff; Settings > Devices has an admin-only "Accepts members'
// bots" toggle; a Confirm card BotOps left in a person's chat renders, and only their click confirms it.
const {chromium} = require('playwright');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const html = fs.readFileSync(path.join(__dirname, '../index.html'), 'utf8');

const FULL = {see: true, read: true, write: true};
const ME = {id: 'ana', role: 'owner', name: 'Ana', email: 'ana@example.test', cloud: true, company_role: 'owner',
  bot_admin: true, can_create_bots: true, can_add_people: true};

(async () => {
  const browser = await chromium.launch({channel: process.env.TICO_BROWSER_CHANNEL ?? 'chrome', headless: true});
  try {
    const page = await browser.newPage({viewport: {width: 1300, height: 900}, serviceWorkers: 'block'});
    const errors = [], posts = [];
    let action = {id: 'act1', owner: 'human:ana', status: 'pending', proposer: 'botops', proposed_via: 'botops',
      description: 'Add Sean (sean@example.test) to the roster, and let them sign in', summary: 'Add Sean (sean@example.test) to the roster',
      method: 'POST', path: '/api/v2/access/people', body: {name: 'Sean', email: 'sean@example.test'}, diff: []};
    let accepts = false;
    const bot = (name, display_name, extra = {}) => ({name, display_name, org_parent: '', host: 'keeper', status: 'active',
      state: 'active', can_chat: true, my_access: FULL, users: [{id: 'ana', name: 'Ana'}], operator: 'ana', revision: 1,
      can_manage: true, ...extra});
    const conv = {id: 'botops-chat', kind: 'chat', scope: 'personal', participants: ['human:ana', 'bot:botops']};
    await page.route('**/*', route => {
      const request = route.request(), url = new URL(request.url()), p = url.pathname, method = request.method();
      const json = body => route.fulfill({contentType: 'application/json', body: JSON.stringify(body)});
      if (url.origin !== 'https://tico-ui.test') return route.abort();
      const ui = p.match(/\/tico\/ui\/([^/]+\.js)$/);
      if (ui && fs.existsSync(path.join(__dirname, '..', ui[1])))
        return route.fulfill({contentType: 'application/javascript', body: fs.readFileSync(path.join(__dirname, '..', ui[1]), 'utf8')});
      if (p === '/') return route.fulfill({contentType: 'text/html', body: html});
      if (p === '/api/me') return json(ME);
      if (p === '/api/people') return json({people: [{id: 'ana', name: 'Ana', org_parent: ''}, {id: 'ben', name: 'Ben Cole', org_parent: ''},
        {id: 'cara', name: 'Cara Diaz', org_parent: ''}], org_groups: []});
      if (p === '/api/employees') return json([
        bot('jira-manager', 'Jira Manager', {operator: 'cara', bot_owners: [{id: 'cara', name: 'Cara Diaz'}], access_policy: null}),
        bot('botops', 'BotOps')]);
      if (p === '/api/issues') return json([]);
      if (p === '/api/status') return json({cloud: true, active: [], queued: [], recent_runs: [], keeper_alive: true, health_issues: []});
      if (p === '/api/v2/status') return json({bots: []});
      if (p === '/api/v2/operations') return json({machines: [{id: 'r1', label: 'Shared Mac', operator: 'ana', last_seen: new Date().toISOString(),
        platform: 'darwin', bots: [], readiness: {}, accepts_member_bots: accepts}], agents: [], services: []});
      if (p === '/api/v2/models') return json({models: []});
      if (p === '/api/v2/settings/history') return json({changes: [], transitions: []});
      if (p === '/api/v2/bots/jira-manager/co-owners' && method === 'POST') { posts.push(['co-owners', request.postDataJSON()]); return json({}); }
      if (p === '/api/v2/runners/r1/member-bots' && method === 'POST') {
        posts.push(['member-bots', request.postDataJSON()]); accepts = request.postDataJSON().accepts; return json({});
      }
      if (p === '/api/v2/assistant/actions/act1' && method === 'GET') return json({action});
      if (p === '/api/v2/assistant/actions/act1/confirm' && method === 'POST') {
        posts.push(['confirm', request.postDataJSON()]); action = {...action, status: 'done'}; return json({action});
      }
      if (p === '/api/v2/tasks') return json({tasks: []});
      if (p === '/api/v2/conversations') return json({conversations: [conv]});
      if (p.endsWith('/snapshot') || p.endsWith('/messages')) return json({conversation: conv, messages: [
        {id: 'm1', conversation_id: conv.id, from_actor: 'human:ana', to_actor: 'bot:botops', kind: 'say', body: 'Add sean@example.test please',
         created: new Date().toISOString(), refs: {}},
        {id: 'm2', conversation_id: conv.id, from_actor: 'bot:botops', to_actor: 'human:ana', kind: 'say', body: 'Needs your OK: Add Sean (sean@example.test) to the roster',
         created: new Date().toISOString(), refs: {assistant: true, action: 'act1'}}], execution: null, has_more: false, next_before: null});
      if (p.endsWith('/watch')) return route.fulfill({contentType: 'text/event-stream', body: ': fixture\n\n'});
      return json({});
    });
    page.on('pageerror', e => errors.push(e.message));

    // ---- Settings > Bots: who owns each bot
    await page.goto('https://tico-ui.test/#/settings');
    await page.locator('[data-settings-tab="bots"]').click();
    await page.locator('tr[data-settings-bot=jira-manager]').waitFor();
    const owned = page.locator('tr[data-settings-bot=jira-manager] [data-bot-owners]');
    assert.match(await owned.innerText(), /Owned by[\s\S]*Cara/);
    await page.locator('[data-edit-bot-owners=jira-manager]').click();
    const dialog = page.locator('#bot-owners-editor');
    await dialog.locator('form').waitFor();
    assert.equal(await dialog.locator('input[value=cara]').isChecked(), true);
    assert.equal(await dialog.locator('input[value=cara]').isDisabled(), true, 'its operator is always an owner');
    await dialog.locator('input[value=ben]').check();
    await dialog.locator('[type=submit]').click();
    await page.waitForFunction(() => !document.querySelector('#bot-owners-editor[open]'));
    assert.deepEqual(posts.shift(), ['co-owners', {add: ['ben'], remove: []}]);

    // ---- Settings > Devices: an admin says which computers take members' bots
    await page.locator('[data-settings-tab="devices"]').click();
    const box = page.locator('[data-member-bots=r1]');
    await box.waitFor();
    assert.equal(await box.isChecked(), false);
    await box.check();
    await page.waitForFunction(() => document.querySelector('[data-member-bots=r1]')?.checked === true);
    assert.deepEqual(posts.shift(), ['member-bots', {accepts: true}]);

    // ---- BotOps' chat: a Confirm card, and nothing happens until the person clicks it
    await page.goto('https://tico-ui.test/#/bot/botops');
    const card = page.locator('.asst-card[data-action=act1]');
    await card.waitFor();
    assert.match(await card.innerText(), /Add Sean \(sean@example\.test\) to the roster/);
    assert.match(await card.innerText(), /BotOps says/);
    assert.match(await card.innerText(), /Runs as you, only when you confirm/);
    assert.deepEqual(posts, []);
    await card.locator('[data-confirm]').click();
    await page.waitForFunction(() => /Done\./.test(document.querySelector('.asst-card[data-action=act1]')?.textContent || ''));
    assert.deepEqual(posts.shift(), ['confirm', {}]);
    assert.deepEqual(errors, []);
    console.log('PASS: bot owners, the members\' bots toggle and BotOps\' Confirm cards.');
  } finally { await browser.close(); }
})().catch(error => { console.error(error); process.exitCode = 1; });
