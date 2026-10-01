// Run with Playwright available: NODE_PATH=/path/to/node_modules node ui/tests/task-board.cjs
// Every request is intercepted; this test never contacts the hub, Slack, or a bot.
// Labels and PR links, a comment thread
// with the author on every line (not a chat), and mover-only controls.
// The Product lane is retired: no lane switch, no product board, and the page
// only asks the hub for company tasks (the product rows below must never show).
const {chromium} = require('playwright');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const {html, uiFile} = require('./support/page.cjs');
const screenshotDir = process.env.TICO_SCREENSHOT_DIR;
// The icon font is subset (ui/vendor/fonts/icons.txt); a ligature missing from that list renders as a stray glyph.
{
  const subset = require('node:fs').readFileSync(require('node:path').join(__dirname, '../vendor/fonts/icons.txt'), 'utf8').split('\n').filter(Boolean);
  for (const name of ['chevron_right', ...[...html.matchAll(/class="nav-icon" aria-hidden="true">([a-z_]+)</g)].map(m => m[1])])
    assert(subset.includes(name), `icon ${name} is not in ui/vendor/fonts/icons.txt (run scripts/build-icon-font.py)`);
  assert.deepEqual(subset, [...subset].sort(), 'icons.txt must stay alphabetical for Google Fonts');
}
(async () => {
  const browser = await chromium.launch({channel: process.env.TICO_BROWSER_CHANNEL ?? 'chrome', headless: true});
  try {
    const page = await browser.newPage({viewport: {width: 1200, height: 900}, serviceWorkers: 'block'});
    const errors = [];
    page.on('pageerror', e => errors.push(e.message));
    const bots = [['coo', 'COO', 'leadership'], ['cpo', 'AI CPO', 'product'], ['cmo', 'AI CMO', 'marketing'],
      ['cto', 'CTO', 'engineering']].map(([name, display_name, team]) =>
      ({name, display_name, host: 'keeper', status: 'active', can_chat: true, team,
        runtime: {cpo: 'codex', cmo: 'claude'}[name]}));
    const now = new Date().toISOString();
    const task = (id, over) => ({id, title: id, body: 'Details.', owner: 'bot:cmo', requester: 'human:reviewer', status: 'open',
      lane: 'company', rank: 1, labels: [], links: [], parts: {total: 0, done: 0}, version: 3, created: now, updated: now, ...over});
    let me = {id: 'reviewer', name: 'Test Reviewer', email: 'reviewer@example.test', role: 'owner', mover: true, cloud: true};
    let tasks = [
      task('Draft the newsletter', {rank: 2, labels: ['newsletter'], body: 'Review [packet](http://tico-ui.test/api/v2/files/doc).',
        attachments: [{id: 'doc', name: 'review-packet.md'}, {id: 'clip', name: 'first-cut.mp4'}, {id: 'archive', name: 'source.zip'}]}),
      task('Approve the budget', {owner: 'human:reviewer', requester: 'bot:coo', rank: 1, labels: ['finance'], note: 'Waiting on finance approval'}),
      task('Write the copy', {rank: 1, labels: ['newsletter', 'copy']}),
      task('Ship the pricing page', {owner: 'bot:cpo', lane: 'product', status: 'review', rank: 1,
        links: [{id: 'l1', kind: 'pr', url: 'https://github.com/ticoteam/tico/pull/412', title: 'tico#412', state: 'open'}], parts: {total: 2, done: 1}}),
      task('Fix the checkout bug', {owner: 'bot:cpo', lane: 'product', status: 'open', rank: 2, labels: ['bug']}),
    ];
    const comments = [{id: 'm1', kind: 'say', from_actor: 'human:ben', to_actor: 'bot:cmo', body: 'Use the September numbers.', created: now, refs: {task: 'Draft the newsletter', comment: true, attachments: [{id: 'doc', name: 'review-packet.md'}]}}];
    const events = [{id: 'e1', task_id: 'Draft the newsletter', ts: now, actor: 'human:reviewer', field: 'status', old: null, new: 'open', note: ''},
                    {id: 'e2', task_id: 'Draft the newsletter', ts: now, actor: 'bot:cmo', field: 'status', old: 'open', new: 'doing', note: ''}];
    const posted = [];
    const people = [];
    let preferencePending = true, tasksStartedBeforePreference = false;
    await page.route('**/*', async route => {
      const req = route.request(), url = new URL(req.url()), p = url.pathname;
      const json = (body, status = 200) => route.fulfill({status, contentType: 'application/json', body: JSON.stringify(body)});
      if (url.origin !== 'http://tico-ui.test') return route.abort();
      if (p === '/') return route.fulfill({contentType: 'text/html', body: html});
      const ui = p.match(/\/tico\/ui\/((?:app\/|styles\/)?[^/]+\.(?:js|css))$/);
      if (ui) { const file = uiFile(ui[1]); if (fs.existsSync(file)) return route.fulfill({contentType: ui[1].endsWith('.css') ? 'text/css' : 'application/javascript', body: fs.readFileSync(file, 'utf8')}); }
      if (p === '/api/employees') return json(bots);
      if (p === '/api/issues') return json([]);
      if (p === '/api/me') return json(me);
      if (p === '/api/status') return json({active: [], employees: []});
      if (p === '/api/v2/status') return json({bots: []});
      if (p === '/api/v2/routines') return json({routines: [
        {id: 'weekly-review', title: 'Review customer signals', employee: 'cmo', cron: '0 9 * * 1', active: true, enabled: true, next: now},
        {id: 'release-review', title: 'Review release readiness', employee: 'cpo', cron: '0 9 * * 1', active: true, enabled: true, next: now},
        {id: 'build-review', title: 'Review build health', employee: 'cto', cron: '0 9 * * 1', active: true, enabled: true, next: now}]});
      if (p === '/api/humans') return json({people});
      if (p === '/api/v2/tasks/labels') return json({labels: ['newsletter', 'copy', 'bug', 'finance']});
      if (p.startsWith('/api/v2/files/')) {
        const id = p.split('/').at(-1);
        const file = {doc: {name: 'review-packet.md', body: '# Script one\n\nApprove the storyboard. <script>window.previewUnsafe = true</script>'},
          clip: {name: 'first-cut.mp4', body: 'not a real video'}, archive: {name: 'source.zip', body: 'not a real zip'}}[id];
        if (!file) return json({}, 404);
        return route.fulfill({contentType: 'application/octet-stream', headers: {'Content-Disposition': `attachment; filename*=UTF-8''${encodeURIComponent(file.name)}`}, body: file.body});
      }
      if (p.startsWith('/api/v2/preferences/') && req.method() === 'GET') {
        await new Promise(resolve => setTimeout(resolve, 150));
        preferencePending = false;
        return json({key: 'tasks.view', value: null});
      }
      if (p === '/api/v2/tasks' && req.method() === 'GET') {
        if (preferencePending) tasksStartedBeforePreference = true;
        await new Promise(resolve => setTimeout(resolve, 50));
        let rows = tasks.slice();
        const statuses = url.searchParams.get('status');
        if (statuses && statuses !== 'all') {
          const wanted = new Set(statuses.split(','));
          rows = rows.filter(task => wanted.has(task.status));
        }
        const lane = url.searchParams.get('lane');
        if (lane) rows = rows.filter(task => (task.lane || 'company') === lane);
        const owner = url.searchParams.get('owner');
        if (owner) rows = rows.filter(task => task.owner === owner || task.owner === 'bot:' + owner);
        if (url.searchParams.get('sort') === 'finished') rows.sort((a, b) => String(b.closed_at || b.updated).localeCompare(String(a.closed_at || a.updated)));
        const offset = Number(url.searchParams.get('offset') || 0), limit = Number(url.searchParams.get('limit') || 500);
        return json({tasks: rows.slice(offset, offset + limit), next_offset: rows.length > offset + limit ? offset + limit : null});
      }
      const one = p.match(/^\/api\/v2\/tasks\/([^/]+)$/);
      if (one && req.method() === 'GET') {
        const t = tasks.find(x => x.id === decodeURIComponent(one[1]));
        return json({task: t, events: events.filter(e => e.task_id === t.id), comments: comments.filter(c => c.refs.task === t.id), children: [], parent: null, mover: me.mover, messages: []});
      }
      if (one && req.method() === 'POST') {
        const body = req.postDataJSON(); posted.push({path: p, body});
        const t = tasks.find(x => x.id === decodeURIComponent(one[1]));
        Object.assign(t, body, {version: t.version + 1}); delete t.close;
        return json({task: t});
      }
      const cm = p.match(/^\/api\/v2\/tasks\/([^/]+)\/comments$/);
      if (cm && req.method() === 'POST') {
        const body = req.postDataJSON(); posted.push({path: p, body});
        comments.push({id: 'm' + comments.length, kind: 'say', from_actor: 'human:reviewer', to_actor: 'bot:cmo', body: body.text, created: new Date().toISOString(), refs: {task: decodeURIComponent(cm[1]), comment: true}});
        return json({comment: comments.at(-1), comments, woke: true});
      }
      if (p === '/api/v2/conversations') return json({conversations: []});
      if (p.endsWith('/messages')) return json({messages: []});
      return json({});
    });
    await page.goto('http://tico-ui.test/#/tasks');
    await page.getByText('Loading tasks…', {exact: true}).waitFor();
    await page.waitForFunction(() => S.me?.id === 'reviewer' && TASKS_ST && TASKS_ST.tasks.length === 3);
    assert.equal(tasksStartedBeforePreference, true, 'task loading starts before the saved preference returns');
    assert.equal(await page.evaluate(() => TASKS_ST.tasks.some(t => t.lane === 'product')), false, 'product tasks are never loaded');
    assert.equal(await page.locator('#task-lane, [data-lane]').count(), 0, 'no lane switch');
    const checkDesktopToolbar = async width => {
      await page.setViewportSize({width, height: 900});
      const result = await page.evaluate(() => {
        const head = document.querySelector('.tasks-head.find');
        const items = ['h1', '.task-find', '#task-new', '#task-view'].map(s => head.querySelector(s).getBoundingClientRect());
        return {tops: items.map(r => Math.round(r.top)), right: Math.max(...items.map(r => r.right)), edge: head.getBoundingClientRect().right,
          search: items[1].width, overflow: head.scrollWidth > head.clientWidth + 1};
      });
      assert(Math.max(...result.tops) - Math.min(...result.tops) <= 8, `${width}px toolbar wraps: ${JSON.stringify(result)}`);
      assert(result.right <= result.edge + 1 && !result.overflow, `${width}px toolbar overflows: ${JSON.stringify(result)}`);
      assert(result.search >= 60, `${width}px search is too narrow: ${JSON.stringify(result)}`);
    };
    for (const width of [1280, 900, 768]) await checkDesktopToolbar(width);
    await page.setViewportSize({width: 1200, height: 900});
    assert.deepEqual(await page.locator('#task-view button').evaluateAll(buttons => buttons.map(b => [b.getAttribute('aria-label'), b.getAttribute('title'), b.getAttribute('aria-pressed')])),
      [['Needs you', 'Needs you', 'true'], ['List', 'List', 'false'], ['Board', 'Board', 'false'], ['Routines', 'Routines', 'false'], ['Done', 'Done', 'false']]);
    // For you is a person icon, left of List.
    assert.equal(await page.locator('#task-view [data-view="foryou"] .nav-icon').innerText(), 'person');
    await page.locator('#task-q').focus();
    await page.keyboard.press('Tab');
    assert.equal(await page.evaluate(() => document.activeElement.id), 'task-filter');
    await page.keyboard.press('Tab');
    assert.equal(await page.evaluate(() => document.activeElement.id), 'task-new');
    await page.keyboard.press('Tab');
    assert.equal(await page.evaluate(() => document.activeElement.dataset.view), 'foryou');
    if (screenshotDir) await page.screenshot({path: path.join(screenshotDir, 'task-toolbar-desktop.png')});

    // List and Board are every open task again, by column; For you stays who needs me.
    await page.locator('#task-view [data-view="list"]').click();
    await page.waitForFunction(() => document.querySelectorAll('#task-body .trow-btn').length === 3);
    assert.deepEqual(await page.locator('#task-body .v2-group h3').evaluateAll(hs => hs.map(h => h.firstChild.textContent.trim())).then(x => x.length > 0), true);
    await page.locator('#task-view [data-view="board"]').click();
    await page.waitForFunction(() => document.querySelectorAll('#task-body .bcol').length === 4 && document.querySelectorAll('#task-body .bcard').length === 3);
    if (screenshotDir) await page.screenshot({path: path.join(screenshotDir, 'task-board-kanban.png')});
    await page.locator('#task-body .bcard').first().click();
    await page.locator('#task-modal').waitFor();
    await page.locator('#task-modal [data-modal-close]').click();
    // Company is one row per bot/person who needs me and opens that bot's chat.
    await page.locator('#task-view [data-view="foryou"]').click();
    await page.locator('.company-need-actor').waitFor();
    assert.equal(await page.locator('.company-need-actor').count(), 1);
    assert.match(await page.locator('.company-need-name').innerText(), /Assistant\s+1 task/);
    assert.match(await page.locator('.company-need-titles').innerText(), /Approve the budget/);
    assert.equal(await page.locator('.company-need-actor').getAttribute('href'), '#/bot/coo');
    // A bare chevron instead of "Open chat", and no count summary in the header.
    assert.equal((await page.locator('.company-need-go').innerText()).trim(), 'chevron_right');
    assert.doesNotMatch(await page.locator('.company-needs').innerText(), /Open chat|bots and people|bot or person/);
    assert.equal(await page.locator('.company-needs>header .sub').count(), 0);
    if (screenshotDir) { fs.mkdirSync(screenshotDir, {recursive: true}); await page.screenshot({path: path.join(screenshotDir, 'task-board-company.png')}); }

    // Filters: Mine shows only my task; the label filter narrows
    await page.locator('#task-filter').click();
    assert.equal(await page.locator('#task-filter-pop').evaluate(el => el.matches(':popover-open')), true);
    await page.locator('#task-filters [data-filter="mine"]').click();
    await page.waitForFunction(() => document.querySelectorAll('.company-need-actor').length === 1);
    assert.match(await page.locator('.company-need-titles').innerText(), /Approve the budget/);
    assert.equal(await page.locator('#task-filter').innerText(), 'Filter · 1');
    await page.locator('#task-filters [data-filter="all"]').click();
    await page.selectOption('#board-label', 'finance');
    await page.waitForFunction(() => document.querySelectorAll('.company-need-actor').length === 1);
    assert.equal(await page.locator('#task-filter').innerText(), 'Filter · 1');
    await page.selectOption('#board-bot', 'cmo');
    assert.equal(await page.locator('#task-filter').innerText(), 'Filter · 2');
    await page.locator('#task-filter-clear').click();
    assert.equal(await page.locator('#task-filter').innerText(), 'Filter');
    await page.locator('#task-filter').click();

    // Search reaches task titles, requester names, waiting lines and recurring routines, then clears.
    await page.locator('#task-q').fill('  BuDgEt  ');
    await page.waitForFunction(() => document.querySelectorAll('.company-need-actor').length === 1);
    await page.locator('#task-q').fill('COO');
    await page.waitForFunction(() => document.querySelectorAll('.company-need-actor').length === 1);
    await page.locator('#task-q').fill('finance approval');
    await page.waitForFunction(() => document.querySelectorAll('.company-need-actor').length === 1);
    assert.match(await page.locator('.company-need-actor').innerText(), /Approve the budget/);
    await page.locator('#task-q').press('Escape');
    await page.waitForFunction(() => document.querySelectorAll('.company-need-actor').length === 1);
    await page.locator('#task-view [data-view="recurring"]').click();
    await page.waitForFunction(() => document.querySelectorAll('.rrow').length === 3);
    assert.deepEqual((await page.locator('.rrow').allInnerTexts()).map(s => s.match(/Review (?:customer signals|release readiness|build health)/)?.[0]).sort(),
      ['Review build health', 'Review customer signals', 'Review release readiness'], 'every routine shows, whatever its team');
    await page.locator('#task-q').fill('customer signals');
    await page.waitForFunction(() => document.querySelectorAll('.rrow').length === 1);
    await page.locator('#task-q').fill('unmatched phrase');
    await page.waitForFunction(() => document.querySelectorAll('.rrow').length === 0);
    await page.locator('#task-q').fill('AI CMO');
    await page.waitForFunction(() => document.querySelectorAll('.rrow').length === 1);
    await page.locator('#task-q').press('Escape');
    tasks.push({id: 'Closed invoice', title: 'Closed invoice', owner: 'bot:cmo', requester: 'human:reviewer',
      status: 'done', lane: 'company', rank: 3, labels: ['finance'], links: [], parts: {total: 0, done: 0},
      version: 1, closed_at: new Date().toISOString(), updated: new Date().toISOString()});
    // A routine's run (a 30-minute sweep) is not listed under Done; it lives under Recurring.
    tasks.push({id: 'Sweep run', title: 'Worker sweep', owner: 'bot:cmo', requester: 'keeper', routine_id: 'cmo:worker-sweep',
      status: 'done', lane: 'company', rank: 4, labels: [], links: [], parts: {total: 0, done: 0},
      version: 1, done_at: new Date().toISOString(), updated: new Date().toISOString()});
    await page.locator('#task-view [data-view="done"]').click();
    await page.waitForFunction(() => document.querySelector('#task-body')?.textContent.includes('Closed invoice'));
    assert.equal(await page.locator('#task-body').innerText().then(t => t.includes('Worker sweep')), false, 'routine runs stay out of Done');
    await page.locator('#task-q').fill('finance');
    await page.waitForFunction(() => document.querySelector('#task-body')?.textContent.includes('Closed invoice'));
    // When it was done, quietly on the right.
    assert.match(await page.locator('#task-body .trow-btn .tnum').first().getAttribute('title'), /^Done /);
    await page.locator('#task-q').fill('newsletter');
    await page.waitForFunction(() => !document.querySelector('#task-body')?.textContent.includes('Closed invoice'));
    await page.locator('#task-q').press('Escape');
    await page.locator('#task-view [data-view="foryou"]').click();

    await page.locator('#task-filter').click();
    await page.selectOption('#board-label', 'copy');
    await page.locator('#task-filter').click();
    await page.locator('#task-q').fill('Write');
    await page.reload();
    await page.waitForFunction(() => TASKS_ST?.tasks.length === 3);
    assert.equal(await page.locator('#task-q').inputValue(), '', 'search is not remembered');
    assert.equal(await page.locator('#task-filter').innerText(), 'Filter · 1', 'label filter is remembered');
    await page.locator('#task-filter').click();
    await page.locator('#task-filter-clear').click();
    await page.locator('#task-filter').click();

    // The modal: comments with authors, state changes inline, one box; the mover controls are there
    await page.evaluate(() => taskModalShow(TASKS_ST.tasks.find(t => t.id === 'Draft the newsletter')));
    await page.locator('#task-modal .task-comments .tcomment', {hasText: 'Use the September numbers.'}).waitFor();
    assert.match(await page.locator('#task-modal .task-comments').innerText(), /ben/i, 'the author is on the comment');
    assert.match(await page.locator('#task-modal .task-comments').innerText(), /moved it to Doing/);
    assert.equal(await page.getByRole('heading', {name: 'Comments'}).count(), 1);
    assert.equal(await page.locator('#task-modal [data-modal-status]').count(), 1, 'a mover sees the status control');
    assert.equal(await page.locator('#task-modal [data-modal-lane]').count(), 0, 'no lane control');
    await page.locator('#task-modal .tlinks [data-preview-file="doc"]').click();
    await page.getByText(/Script one.*Approve the storyboard/s).waitFor();
    assert.match(await page.locator('#task-modal .task-file-preview').innerText(), /Script one.*Approve the storyboard/s);
    assert.equal(await page.locator('#task-modal .task-file-preview script').count(), 0, 'untrusted Markdown is sanitized');
    assert.equal(await page.locator('#task-modal .task-comments [data-preview-file="doc"]').count(), 1, 'comment attachments are previewable too');
    if (screenshotDir) await page.screenshot({path: path.join(screenshotDir, 'task-attachment-preview.png')});
    await page.locator('#task-modal [data-preview-file="clip"]').click();
    await page.locator('#task-modal .task-file-preview video').waitFor();
    assert.equal(await page.locator('#task-modal .task-file-preview video').getAttribute('controls'), '');
    await page.locator('#task-modal [data-preview-file="archive"]').click();
    await page.getByText('This file cannot be shown here. Download it to open it.').waitFor();
    await page.locator('#task-modal [data-close-file-preview]').click();
    await page.evaluate(() => {
      const link = document.createElement('a');
      link.href = '/api/v2/files/doc'; link.textContent = 'review-packet.md';
      document.querySelector('#task-modal .q').appendChild(link);
    });
    await page.locator('#task-modal .q a[href="/api/v2/files/doc"]').click();
    await page.getByText(/Script one.*Approve the storyboard/s).waitFor();
    await page.getByRole('textbox', {name: 'Add a comment'}).fill('Add the promo line.');
    await page.getByRole('button', {name: 'Comment', exact: true}).click();
    await page.locator('#task-modal .task-comments .tcomment', {hasText: 'Add the promo line.'}).waitFor();
    assert.deepEqual(posted.at(-1), {path: '/api/v2/tasks/Draft%20the%20newsletter/comments', body: {text: 'Add the promo line.'}});
    assert.equal(await page.locator('#task-modal').getByText(/Send to/).count(), 0, 'no chat framing');
    if (screenshotDir) await page.screenshot({path: path.join(screenshotDir, 'task-modal-comments.png')});
    // a label added from the modal posts the new label set with the version
    await page.locator('#task-modal [data-modal-labels] input').fill('promo');
    await page.locator('#task-modal [data-modal-labels] input').press('Enter');
    await page.waitForFunction(() => window.__posted !== 'never');
    const labelPost = posted.find(x => x.body.labels);
    assert.deepEqual(labelPost.body, {version: 3, labels: ['newsletter', 'promo']});
    await page.locator('#task-modal [data-modal-close]').click();
    await page.waitForFunction(() => TASK_CHAT === null);

    // Finishing a request from a bot records a result; cancel leaves the task open.
    await page.evaluate(() => taskModalShow(TASKS_ST.tasks.find(t => t.id === 'Approve the budget')));
    const finishButton = page.locator('#task-modal [data-modal-task="done"]');
    const beforeFinish = posted.length;
    await finishButton.click();
    await page.locator('dialog.task-outcome textarea').waitFor();
    await page.locator('dialog.task-outcome [data-cancel]').click();
    assert.equal(posted.length, beforeFinish, 'cancel does not finish the request');
    assert.equal(await page.locator('#task-modal').evaluate(el => el.open), true, 'the task stays open after cancel');
    await finishButton.click();
    await page.locator('dialog.task-outcome textarea').fill('Keep the budget on hold.');
    await page.locator('dialog.task-outcome button[type="submit"]').click();
    await page.waitForFunction(() => !TASKS_ST.tasks.some(t => t.id === 'Approve the budget'), null,
      {timeout: 30_000});
    const resultPost = posted.find(x => x.path === '/api/v2/tasks/Approve%20the%20budget' && x.body.status === 'done');
    assert.equal(resultPost.body.note, 'Keep the budget on hold.');

    // A non-mover: no status control, but the comment box
    me = {...me, role: 'viewer', mover: false};
    await page.evaluate(() => { S.me = {...S.me, mover: false}; taskModalShow(TASKS_ST.tasks.find(t => t.id === 'Draft the newsletter')); });
    await page.waitForTimeout(50);
    await page.locator('#task-modal .task-comments').waitFor();
    assert.equal(await page.locator('#task-modal [data-modal-status]').count(), 0);
    assert.equal(await page.getByRole('textbox', {name: 'Add a comment'}).count(), 1);
    await page.locator('#task-modal [data-modal-close]').click();
    tasks.find(t => t.id === 'Approve the budget').status = 'open';
    await page.evaluate(() => tasksLoad(TASKS_ST));
    await page.waitForFunction(() => TASKS_ST.tasks.some(t => t.id === 'Approve the budget'));

    await page.setViewportSize({width: 375, height: 844});
    await page.waitForTimeout(250); // allow the sidebar's drawer transition to finish
    await page.locator('#task-view [data-view="foryou"]').click();
    await page.locator('.company-needs').waitFor();
    const mobile = await page.evaluate(() => {
      const head = document.querySelector('.tasks-head.find');
      const rect = s => head.querySelector(s).getBoundingClientRect();
      return {top: [rect('h1').top, rect('.task-find').top, rect('#task-new').top], strip: rect('.task-strip').top,
        right: rect('#task-new').right, edge: head.getBoundingClientRect().right};
    });
    assert(Math.max(...mobile.top) - Math.min(...mobile.top) <= 8, 'phone primary controls share a line');
    assert(mobile.strip > mobile.top[0] && mobile.right <= mobile.edge + 1, 'phone view switch is on its own line');
    await page.locator('#task-filter').click();
    assert.equal(await page.locator('#task-filter-pop').evaluate(el => Math.round(el.getBoundingClientRect().bottom)), 844, 'filter is a bottom sheet');
    await page.keyboard.press('Escape');
    assert.equal(await page.locator('#task-filter-pop').evaluate(el => el.matches(':popover-open')), false);
    await page.locator('#task-filter').click();
    await page.locator('.tasks-head h1').click();
    assert.equal(await page.locator('#task-filter-pop').evaluate(el => el.matches(':popover-open')), false, 'outside tap closes the sheet');
    for (const theme of ['light', 'dark']) {
      await page.evaluate(theme => document.documentElement.dataset.theme = theme, theme);
      if (screenshotDir) await page.screenshot({path: path.join(screenshotDir, `task-toolbar-mobile-${theme}.png`)});
    }
    if (screenshotDir) await page.screenshot({path: path.join(screenshotDir, 'task-board-mobile.png')});
    assert(await page.locator('.company-needs').evaluate(el => el.scrollWidth <= el.clientWidth + 1));
    for (const [route, view] of [['#/board', 'board'], ['#/issues', 'list'], ['#/recurring', 'recurring']]) {
      await page.goto('http://tico-ui.test/' + route);
      const activeCount = tasks.filter(task => task.lane === 'company' && !['done', 'closed'].includes(task.status)).length;
      await page.waitForFunction(({view, activeCount}) => TASKS_ST?.view === view && TASKS_ST.tasks.length === activeCount,
        {view, activeCount});
      assert.equal(await page.locator(`#task-view [data-view="${view}"]`).getAttribute('aria-pressed'), 'true');
    }
    // Links copied into chat or email do not depend on clients preserving a URL fragment.
    await page.goto('http://tico-ui.test/?task=Approve%20the%20budget');
    await page.locator('#task-modal', {hasText: 'Approve the budget'}).waitFor();
    assert.equal(new URL(page.url()).hash, '#/task/Approve%20the%20budget');
    await page.goto('http://tico-ui.test/?bot=cmo&tab=tasks');
    await page.waitForFunction(() => location.hash === '#/bot/cmo/tasks');
    assert.equal(new URL(page.url()).search, '', 'the entry query is removed after routing');
    // The org panel shows a bot's harness as a small mark, not a word; a bot with no harness shows none.
    const rt = name => page.locator(`#tree a.node[href="#/bot/${name}"] .rt`);
    assert.equal(await rt('cpo').getAttribute('aria-label'), 'Runs on Codex');
    assert.equal(await rt('cmo').getAttribute('aria-label'), 'Runs on Claude Code');
    assert.equal(await rt('cpo').locator('svg').count(), 1);
    assert.equal((await rt('cpo').innerText()).trim(), '', 'the mark has no text');
    assert.equal(await rt('cto').count(), 0, 'no harness, no mark');
    const mark = await rt('cpo').boundingBox();
    assert(mark.width >= 12 && mark.width <= 14, 'about 13px: ' + mark.width);
    assert.deepEqual(errors, []);
    console.log('PASS: toolbar layout, search, filter menu, persistence, recurring search, company only, labels, comments, mobile.');
  } finally { await browser.close(); }
})().catch(e => { console.error(e); process.exitCode = 1; });
