// Offline browser regression for retiring the Tico chat and Tico Live: there is
// no Chat entry and an old #/chat link lands on Tasks; the org panel, search and the bot pickers
// leave out the assistant (Tico) and Doc Updater, whose reports take their place, so BotOps sits at
// the top; Doc Updater stays one click away from the Docs row; the assistant's own page has no Chat
// tab; and every other bot's chat keeps its per-bot Live voice button. Fixtures only, no network.
const {chromium} = require('playwright');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const html = fs.readFileSync(path.join(__dirname, '../index.html'), 'utf8');

(async () => {
  const browser = await chromium.launch({channel: process.env.TICO_BROWSER_CHANNEL ?? 'chrome', headless: true});
  try {
    const page = await browser.newPage({viewport: {width: 1100, height: 820}, serviceWorkers: 'block'});
    const errors = [], requested = [];
    let updating = false;
    page.on('pageerror', error => errors.push(error.message));
    const bot = (name, display_name, org_parent, extra = {}) => ({name, display_name, org_parent, host: 'keeper',
      status: 'active', can_chat: true, users: [{id: 'ana', name: 'Ana'}], ...extra});
    const bots = [
      bot('coo', 'Tico', ''), bot('botops', 'BotOps', 'b:coo'), bot('bug-triage', 'Bug Triage', 'b:coo'),
      bot('doc-updater', 'Doc Updater', 'b:coo'), bot('cmo', 'AI CMO', ''), bot('seo', 'AI SEO', 'b:cmo'),
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
        {bot: 'bug-triage', state: 'idle', open_tasks: 7}, {bot: 'cmo', state: 'running', open_tasks: 1}],
        updating: updating ? {since: new Date().toISOString(), bots: 3} : null});
      if (p === '/api/v2/needs-you') return json({items: [
        {id: 'n1', kind: 'task', title: 'Pick a label', owner: 'human:ana', requester: 'bot:bug-triage', status: 'open'},
        {id: 'n2', kind: 'question', title: 'Which repo?', owner: 'bot:bug-triage', requester: 'bot:bug-triage', status: 'waiting',
         ask: {from_actor: 'bot:bug-triage', to_actor: 'human:ana'}},
        {id: 'n3', kind: 'approval', title: 'Approve this send', requester: 'bot:cmo'}]});
      if (p === '/api/v2/tasks') return json({tasks: []});
      if (p === '/api/v2/conversations') return json({conversations: [conv]});
      if (p.endsWith('/snapshot')) return json({messages: [
        // a line an old Tico Live session left in a room still reads as a plain message
        {id: 'old-live', from_actor: 'bot:cmo', body: 'Filed the launch task.', created: new Date().toISOString(),
         refs: {live: {kind: 'tool', name: 'task_create', outcome: 'ok'}}}], execution: null});
      if (p.endsWith('/watch')) return route.fulfill({contentType: 'text/event-stream', body: ': fixture\n\n'});
      return json({});
    });

    // The app opens on Updates, and an old Chat link lands on Tasks.
    await page.goto('https://tico-ui.test/');
    await page.waitForFunction(() => location.hash === '#/updates');
    await page.goto('https://tico-ui.test/#/chat');
    await page.waitForFunction(() => location.hash === '#/tasks');
    assert.equal(await page.locator('a[href="#/chat"], [data-nav="chat"]').count(), 0);
    await page.locator('#tree [data-org="b:botops"]').waitFor();

    // The org panel: no Tico, no Doc Updater; their reports sit where Tico sat, at the top.
    const tree = page.locator('#tree');
    assert.equal(await tree.locator('[data-org="b:coo"], [data-org="b:doc-updater"]').count(), 0);
    assert.doesNotMatch(await tree.innerText(), /Tico|Doc Updater/);
    const top = await tree.evaluate(el => [...el.children].map(li => li.querySelector(':scope > .noderow > a')?.dataset.org));
    assert.deepEqual(top.filter(k => k?.startsWith('b:')).sort(), ['b:botops', 'b:bug-triage', 'b:cmo']);
    assert.equal(await tree.locator('[data-org="b:seo"]').count(), 1);          // an ordinary report keeps its parent

    // A working bot shows a spinner, not its open-task count; a bot that needs
    // you shows how many tasks need you. Nothing else gets a number.
    const badge = slug => tree.locator(`[data-org="b:${slug}"]`);
    assert.equal(await badge('botops').locator('.tree-spin').count(), 1);
    assert.equal(await badge('botops').locator('.cnt').count(), 0);
    assert.equal(await badge('bug-triage').locator('.cnt.needs').innerText(), '2');
    assert.equal(await badge('bug-triage').locator('.tree-spin').count(), 0);
    assert.equal(await badge('cmo').locator('.cnt').count(), 0);                // an approval is not a task
    assert.equal(await badge('cmo').locator('.tree-spin').count(), 1);
    // No hover card on the org list's bots; a working bot's count gets a spinning
    // ring around it, and a need that is not a task is a small quiet "!".
    assert.equal(await tree.locator('[data-tip-bot], a.node[data-org^="b:"][title]').count(), 0, 'no hover card or tooltip on bots');
    await badge('bug-triage').hover();
    await page.waitForTimeout(700);
    assert.equal(await page.locator('.bot-tip:visible, #tip:visible, [role="tooltip"]:visible').count(), 0);
    assert.deepEqual(await page.evaluate(() => [treeBadge(2, 'running'), treeBadge(0, 'needs'), treeBadge(0, 'running'), treeBadge(0, 'idle')]
      .map(h => { const d = document.createElement('div'); d.innerHTML = h; const el = d.firstElementChild; return el ? [el.className, el.textContent] : null; })),
      [['cnt needs working', '2'], ['tree-alert', '!'], ['tree-spin', ''], null]);

    // Doc Updater stays reachable from the Docs row in the rail, and opens on its settings.
    const librarian = page.locator('.side-scroll .nav-row #nav-docs-librarian');
    assert.equal(await librarian.isVisible(), true);
    assert.equal(await librarian.getAttribute('href'), '#/bot/doc-updater/more');

    // Search and the task owner picker leave both out.
    const entries = await page.evaluate(() => searchEntries().filter(e => e.kind === 'bot').map(e => e.alias).sort());
    assert.deepEqual(entries, ['botops', 'bug-triage', 'cmo', 'seo']);
    const owners = await page.evaluate(() => taskOwnerOptions());
    assert.doesNotMatch(owners, /value="coo"|value="doc-updater"/);
    assert.match(await page.evaluate(() => taskOwnerOptions('coo')), /value="coo" selected/);   // a task already Tico's keeps its owner

    // Tico's own page has no Chat and opens on Tasks alone; Docs and settings stay behind More.
    await page.goto('https://tico-ui.test/#/bot/coo');
    await page.waitForFunction(() => BOT?.slug === 'coo' && BOT.tab);
    assert.deepEqual(await page.locator('#btabs [data-bt]').evaluateAll(els => els.map(el => el.dataset.bt)), ['tasks', 'history', 'more']);
    assert.equal(await page.evaluate(() => BOT.tab), 'tasks');
    assert.equal(await page.locator('#pane-chat').isVisible(), false);
    assert.equal(await page.locator('#pane-tasks').isVisible(), true);
    // More is a bare vertical three-dot button
    const more = page.locator('#bot-more-btn');
    assert.equal((await more.innerText()).trim(), 'more_vert');
    assert.equal(await more.getAttribute('aria-label'), 'More');

    // Live voice was removed entirely; an old Live line is a plain message.
    await page.goto('https://tico-ui.test/#/bot/cmo');
    await page.waitForFunction(() => BOT?.slug === 'cmo' && V2C?.rendered);
    assert.equal(await page.locator('#chat-composer .p-live, #chat-composer .p-live-dock').count(), 0);
    assert.equal(await page.evaluate(() => typeof LiveConversation), 'undefined');
    assert.equal(await page.evaluate(() => typeof window.TicoLive), 'undefined');
    assert.equal(await page.locator('#conv-thread .live-line').count(), 0);
    assert.match(await page.locator('#conv-thread').innerText(), /Filed the launch task\./);

    // A computer with a Tico update says whether anything would be interrupted
    // and restarts from the panel.
    await page.evaluate(() => {
      S.status.health_issues = [{kind: 'runner_checkout', title: 'Ana Mac has a Tico update', machine: 'r1',
        detail: 'Nothing is running, so nothing will be interrupted.', severity: 'warning', needs_person: true, restart: true}];
      needsYou();
    });
    const panel = page.locator('.needs-you');
    assert.match(await panel.innerText(), /Ana Mac has a Tico update\s+Nothing is running, so nothing will be interrupted\./);
    await panel.getByRole('button', {name: 'Restart'}).click();
    await page.waitForFunction(() => /Restarting now/.test(document.querySelector('.needs-you')?.textContent));
    assert(requested.includes('/api/v2/runners/r1/restart'));

    // Nothing asks the retired endpoints.
    assert.deepEqual(requested.filter(p => /\/voice\/live|live-quality|\/chat\/thread|\/help\b/.test(p)), []);
    // Tico updating itself shows at the top of the sidebar, and goes when it's done.
    assert.equal(await page.locator('#side-update').isVisible(), false);
    updating = true;
    await page.evaluate(() => v2Refresh());
    assert.equal(await page.locator('#side-update').isVisible(), true);
    assert.match(await page.locator('#side-update').innerText(), /Updating/);
    updating = false;
    await page.evaluate(() => v2Refresh());
    assert.equal(await page.locator('#side-update').isVisible(), false);
    assert.deepEqual(errors, []);
    console.log('PASS: no Chat entry, #/chat lands on Tasks, Tico and Doc Updater out of the org panel, search and pickers with BotOps on top, Doc Updater from Docs in the rail, no Chat for Tico, per-bot Live kept.');
  } finally {
    await browser.close();
  }
})().catch(error => { console.error(error); process.exitCode = 1; });
