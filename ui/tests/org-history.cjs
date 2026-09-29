// Offline browser regression for the desktop Org history toggle: the history
// icon next to Org lists every bot and person with the most recently viewed on top and looks active;
// pressed again, the normal org tree comes back. Fixtures only, no network.
const {chromium} = require('playwright');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const html = fs.readFileSync(path.join(__dirname, '../index.html'), 'utf8');

(async () => {
  const browser = await chromium.launch({channel: process.env.TICO_BROWSER_CHANNEL ?? 'chrome', headless: true});
  try {
    const page = await browser.newPage({viewport: {width: 1100, height: 820}, serviceWorkers: 'block'});
    const errors = [], requested = [], saved = [];
    let server = null;
    page.on('pageerror', error => errors.push(error.message));
    const bot = (name, display_name, org_parent, extra = {}) => ({name, display_name, org_parent, host: 'keeper',
      status: 'active', can_chat: true, users: [{id: 'ana', name: 'Ana'}], ...extra});
    const bots = [
      bot('coo', 'Tico', ''), bot('botops', 'BotOps', 'b:coo'), bot('bug-triage', 'Bug Triage', 'b:coo'),
      bot('librarian', 'Librarian', 'b:coo'), bot('cmo', 'AI CMO', ''), bot('seo', 'AI SEO', 'b:cmo'),
    ];
    const conv = {id: 'cmo-chat', kind: 'chat', scope: 'personal', participants: ['human:ana', 'bot:cmo']};
    await page.route('**/*', route => {
      const url = new URL(route.request().url()), p = url.pathname;
      const json = body => route.fulfill({contentType: 'application/json', body: JSON.stringify(body)});
      if (url.origin !== 'https://tico-ui.test') return route.abort();
      requested.push(p);
      const ui = p.match(/\/tico\/ui\/([^/]+\.js)$/);
      if (ui) {
        const file = path.join(__dirname, '..', ui[1]);
        if (fs.existsSync(file)) return route.fulfill({contentType: 'application/javascript', body: fs.readFileSync(file, 'utf8')});
      }
      if (p === '/') return route.fulfill({contentType: 'text/html', body: html});
      if (p === '/api/me') return json({id: 'ana', role: 'owner', name: 'Ana', email: 'ana@example.test', cloud: true});
      if (p === '/api/people') return json({people: [{id: 'ana', name: 'Ana'}]});
      if (p === '/api/employees') return json(bots);
      if (p === '/api/issues') return json([]);
      if (p === '/api/status') return json({cloud: true, active: [], queued: [], recent_runs: [], keeper_alive: true, health_issues: []});
      // BotOps is working with 4 open tasks, none of them yours; Bug Triage is idle and needs you twice
      if (p === '/api/v2/status') return json({bots: [{bot: 'botops', state: 'running', open_tasks: 4},
        {bot: 'bug-triage', state: 'idle', open_tasks: 7}, {bot: 'cmo', state: 'running', open_tasks: 1}]});
      if (p === '/api/v2/needs-you') return json({items: [
        {id: 'n1', kind: 'task', title: 'Pick a label', owner: 'human:ana', requester: 'bot:bug-triage', status: 'open'},
        {id: 'n2', kind: 'question', title: 'Which repo?', owner: 'bot:bug-triage', requester: 'bot:bug-triage', status: 'waiting',
         ask: {from_actor: 'bot:bug-triage', to_actor: 'human:ana'}},
        {id: 'n3', kind: 'approval', title: 'Approve this send', requester: 'bot:cmo'}]});
      if (p === '/api/v2/preferences/org.history') {
        if (route.request().method() === 'POST') { saved.push(JSON.parse(route.request().postData()).value); return json({}); }
        return json({key: 'org.history', value: server});
      }
      if (p === '/api/v2/tasks') return json({tasks: []});
      if (p === '/api/v2/conversations') return json({conversations: [conv]});
      if (p.endsWith('/snapshot')) return json({messages: [
        // a line an old Tico Live session left in a room still reads as a plain message
        {id: 'old-live', from_actor: 'bot:cmo', body: 'Filed the launch task.', created: new Date().toISOString(),
         refs: {live: {kind: 'tool', name: 'task_create', outcome: 'ok'}}}], execution: null});
      if (p.endsWith('/watch')) return route.fulfill({contentType: 'text/event-stream', body: ': fixture\n\n'});
      return json({});
    });

    await page.goto('https://tico-ui.test/');
    await page.locator('#tree .node').first().waitFor();
    const order = () => page.locator('#tree .node').evaluateAll(ns => ns.map(n => n.dataset.org));
    const toggle = page.locator('#org-history');
    assert.equal(await toggle.getAttribute('aria-pressed'), 'false');
    assert.ok(await page.locator('#tree ul .node').count() > 0, 'the org view nests reports');
    const tree = await order();

    for (const key of ['b:seo', 'p:ana', 'b:bug-triage']) {
      await page.evaluate(k => { location.hash = (k[0] === 'b' ? '#/bot/' : '#/person/') + k.slice(2); }, key);
      await page.waitForFunction(k => JSON.parse(localStorage.getItem('tico.org.history') || '[]')[0] === k, key);
    }
    await toggle.click();
    assert.equal(await toggle.getAttribute('aria-pressed'), 'true');
    assert.notEqual(await toggle.evaluate(b => getComputedStyle(b).boxShadow), 'none', 'on, it glows');
    const flat = await order();
    assert.deepEqual(flat.slice(0, 3), ['b:bug-triage', 'p:ana', 'b:seo'], 'most recently viewed on top');
    assert.equal(await page.locator('#tree ul .node').count(), 0, 'one flat list');
    assert.equal(new Set(flat).size, tree.length, 'the same bots and people as the org view');

    // Opening another bot moves it to the top while history is on; the setting survives a reload.
    await page.evaluate(() => { location.hash = '#/bot/cmo'; });
    await page.waitForFunction(() => document.querySelector('#tree .node')?.dataset.org === 'b:cmo');
    await page.reload();
    await page.locator('#tree .node').first().waitFor();
    assert.equal(await toggle.getAttribute('aria-pressed'), 'true');
    assert.equal((await order())[0], 'b:cmo');

    // Saved with the account: this device's visits went up, and a newer copy from the phone wins.
    await page.waitForTimeout(900);
    assert.equal(saved.at(-1)?.items?.[0], 'b:cmo', 'the list is saved to the server');
    server = {items: ['b:seo', 'b:botops'], at: Date.now() + 60000};
    await page.reload();
    await page.waitForFunction(() => document.querySelector('#tree .node')?.dataset.org === 'b:seo');
    assert.deepEqual((await order()).slice(0, 3), ['b:seo', 'b:botops', 'b:cmo'], 'the newer server list leads, local ones follow');

    await toggle.click();
    assert.equal(await toggle.getAttribute('aria-pressed'), 'false');
    assert.equal(await toggle.evaluate(b => getComputedStyle(b).boxShadow), 'none');
    assert.deepEqual(await order(), tree, 'off, the org view is back');
    assert.deepEqual(errors, []);
    console.log('org-history: ok');
  } finally {
    await browser.close();
  }
})().catch(error => { console.error(error); process.exitCode = 1; });
