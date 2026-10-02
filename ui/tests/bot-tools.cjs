// A bot's page: the right rail and the tools (ui/app/bot-page.js, ui/bot-tools.js, ui/tool-icons.js).
// On a desktop the rail runs the page's full height beside the top bar and chat, Active first, then
// Updates (the latest one, no "Latest update" banner over the chat), Files and Recurring, each section
// gone when it has nothing; Assigned to others and Done fold at the foot. Beside the bot's name, after
// its runtime mark: three tool icons at most and "+N", each naming its tool and opening the Tools card
// under More, which lists every tool with its details. A phone keeps one column, Active first. In both
// themes. Fixtures only, no network. TICO_SCREENSHOT_DIR keeps screenshots of the page.
const {chromium} = require('playwright');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const {html, uiFile} = require('./support/page.cjs');
const shots = process.env.TICO_SCREENSHOT_DIR;

const now = Date.now(), iso = ms => new Date(now + ms).toISOString(), hour = 3600e3;
const bots = [{name: 'cmo', display_name: 'AI CMO', org_parent: '', host: 'keeper', status: 'active', can_chat: true, runtime: 'codex',
  users: [{id: 'ana', name: 'Ana'}],
  schedules: [{id: 'r1', title: 'Morning metrics digest', cron: '0 8 * * 1-5', active: true, next: iso(14 * hour)},
    {id: 'r2', title: 'Friday launch review', cron: '0 15 * * 5', active: true, next: iso(50 * hour)}]}];
const tool = (id, service, name, extra) => ({id, service, name, logo_key: null, identity: '', can: [], scope: {}, note: '',
  status: 'ready', ...extra});
const TOOLS = [
  tool('model', 'codex', 'Codex', {logo_key: 'openai', identity: 'openai/gpt-6-luna', can: ['use'], scope: {effort: 'high'}}),
  tool('repo', 'github', 'GitHub', {logo_key: 'github', identity: 'acme-co/emp-cmo', scope: {repo: 'acme-co/emp-cmo'}, url: 'https://github.com/acme-co/emp-cmo'}),
  tool('posthog', 'posthog', 'PostHog', {logo_key: 'posthog', identity: 'PostHog project 12345 (US), personal key', can: ['read'],
    scope: {project: '12345'}, env: 'POSTHOG_KEY', note: 'funnels only', status: 'problem', problem: 'Credential missing on Test Mac'}),
  tool('slack', 'slack', 'Slack', {logo_key: 'slack', identity: 'Acme workspace', can: ['read', 'post'], scope: {channels: ['#ops', '#launch']}, env: 'SLACK_TOKEN'}),
  tool('meeting-notes', 'meeting-notes', 'Meeting notes', {can: ['use'], status: 'unknown', detail: 'No credential is declared, so there is nothing to check'}),
  ...Array.from({length: 4}, (_, n) => tool('extra' + n, 'extra' + n, 'Extra ' + n, {identity: 'account ' + n})),
];
const task = (id, title, extra) => ({id, title, status: 'doing', owner: 'bot:cmo', requester: 'human:ana', created: iso(-30 * hour), updated: iso(-hour), ...extra});
const TASKS = [task('t1', 'Draft the October pricing page copy'), task('t2', 'Pull last week\'s funnel numbers from PostHog', {status: 'open'}),
  task('t3', 'Write the launch email for the new plan', {status: 'waiting'}),
  task('t4', 'Weekly report', {status: 'done', done_at: iso(-20 * hour)}), task('t5', 'Clean up UTM tags', {status: 'done', done_at: iso(-40 * hour)})];
const ASKED = [task('a1', 'Approve the pricing page before Friday', {owner: 'human:ana', requester: 'bot:cmo'})];
const UPDATE = {id: 'u1', bot: 'cmo', kind: 'daily', day: '2026-10-01', read: false, created: iso(-10 * hour), updated: iso(-10 * hour),
  body: '- Drafted the pricing page copy; two headline options are on the task.\n- Funnel: sign-ups up 8% week over week.'};
const said = (n, who, body) => ({id: 'm' + n, from_actor: who, body, created: iso((n - 9) * hour)});
const CHAT = [said(1, 'human:ana', 'Where are we on the pricing page?'),
  said(2, 'bot:cmo', 'The copy is drafted, with two headline options on the task. I am pulling last week\'s funnel numbers to pick between them.'),
  said(3, 'human:ana', 'Go with the shorter headline if the numbers are close.'),
  said(4, 'bot:cmo', 'Will do. The launch email waits on your approval of the page.')];
const file = (n, title) => ({id: 'file-' + n, bot: 'cmo', title, kind: 'document', locator: 'tico_blob', name: title + '.md',
  open: {type: 'tico', url: '/api/v2/files/file-' + n}, last_activity_at: iso(-n * hour)});
const FILES = ['Q4 launch plan', 'Pricing page draft', 'Funnel export', 'Old brief', 'Brand voice notes'].map((t, n) => file(n + 1, t));

async function open(browser, viewport, options = {}, data = {}) {
  const context = await browser.newContext({viewport, serviceWorkers: 'block', hasTouch: viewport.width < 760, isMobile: viewport.width < 760, ...options});
  await context.addInitScript(theme => { try { localStorage.setItem('tico.theme', theme); } catch {} }, options.colorScheme || 'dark');
  const page = await context.newPage();
  const errors = [], read = [];
  page.on('pageerror', error => errors.push(error.message));
  const {updates = [UPDATE], files = FILES} = data;
  await page.route('**/*', route => {
    const url = new URL(route.request().url()), p = url.pathname, q = url.searchParams;
    const json = body => route.fulfill({contentType: 'application/json', body: JSON.stringify(body)});
    if (url.origin !== 'https://tico-ui.test') return route.abort();
    // The vendored Markdown and icon font, so the page reads as it does for real.
    const vendor = p.match(/^\/vendor\/((?:fonts\/)?[\w.-]+)$/);
    if (vendor && fs.existsSync(uiFile('vendor/' + vendor[1]))) return route.fulfill({path: uiFile('vendor/' + vendor[1])});
    const ui = p.match(/\/tico\/ui\/((?:app\/|styles\/)?[^/]+\.(?:js|css))$/);
    if (ui && fs.existsSync(uiFile(ui[1]))) return route.fulfill({contentType: ui[1].endsWith('.css') ? 'text/css' : 'application/javascript', body: fs.readFileSync(uiFile(ui[1]), 'utf8')});
    if (p === '/') return route.fulfill({contentType: 'text/html', body: html});
    if (p === '/api/me') return json({id: 'ana', role: 'owner', name: 'Ana', email: 'ana@example.test', cloud: true});
    if (p === '/api/humans') return json({people: [{id: 'ana', name: 'Ana'}]});
    if (p === '/api/employees') return json(bots);
    if (p === '/api/status') return json({cloud: true, active: [], queued: [], recent_runs: [], keeper_alive: true, health_issues: [], schedules: bots[0].schedules.map(s => ({...s, employee: 'cmo'}))});
    if (p === '/api/v2/status') return json({bots: [{bot: 'cmo', state: 'running', task_id: 't1'}]});
    if (p === '/api/v2/goals') return json({goals: [], chain: [], reports: [], company: []});
    if (p === '/api/v2/updates/read') { read.push(...JSON.parse(route.request().postData()).ids); return json({}); }
    if (p === '/api/v2/updates') return json({updates: q.get('bot') ? updates : [], missed: [], unread: 0, next_before: null, today: {}});
    if (p === '/api/v2/tasks') return json({tasks: q.get('owner') === 'cmo' ? TASKS : q.get('requester') === 'cmo' ? ASKED : []});
    if (p === '/api/v2/conversations') return json({conversations: q.get('chat_with') ? [{id: 'c-cmo', kind: 'chat', scope: 'personal', participants: ['human:ana', 'bot:cmo']}] : []});
    if (p === '/api/v2/conversations/c-cmo/snapshot') return json({messages: CHAT});
    if (p === '/api/v2/bots/cmo/tools') return json({bot: 'cmo', tools: TOOLS, computer: 'Test Mac', online: true, reported_at: null});
    if (p === '/api/v2/bots/cmo/files') {
      const limit = Number(q.get('limit'));
      return json({bot: 'cmo', files: files.slice(0, limit), total: files.length, next_cursor: files.length > limit ? 'next' : null, has_more: files.length > limit, can_manage: true, actors: {}});
    }
    if (p.endsWith('/watch')) return route.fulfill({contentType: 'text/event-stream', body: ': fixture\n\n'});
    return json({});
  });
  return {page, errors, read, context};
}

const box = (page, selector) => page.locator(selector).first().boundingBox();
const railOrder = page => page.evaluate(() => [...document.querySelectorAll('#pane-tasks>section.rail-sec')]
  .filter(el => !el.hidden).map(el => el.querySelector('.rail-h').firstChild.textContent.trim()));

(async () => {
  const browser = await chromium.launch({headless: true, channel: process.env.TICO_BROWSER_CHANNEL === undefined ? 'chrome' : process.env.TICO_BROWSER_CHANNEL || undefined});
  try {
    for (const scheme of ['light', 'dark']) {
      const {page, errors, read, context} = await open(browser, {width: 1440, height: 900}, {colorScheme: scheme});
      await page.goto('https://tico-ui.test/#/bot/cmo');
      await page.locator('#t-open .trow').first().waitFor();
      await page.locator('#bot-files .bf-row').first().waitFor();
      await page.locator('#bot-latest:not([hidden])').waitFor();
      await page.locator('#bot-tool-strip .bts-icon').first().waitFor();

      // The rail: full height at the right edge, beside the top bar, which spans the chat column only.
      const rail = await box(page, '#pane-tasks'), top = await box(page, '#bot-top'), chat = await box(page, '#pane-chat');
      assert(rail.y <= 1 && Math.abs(rail.y + rail.height - 900) <= 1, scheme + ': the rail runs the full height ' + JSON.stringify(rail));
      assert(Math.abs(rail.x + rail.width - 1440) <= 1, scheme + ': at the right edge');
      assert(top.x + top.width <= rail.x && chat.x + chat.width <= rail.x, scheme + ': the top bar and chat stay left of the rail');
      const edge = await box(page, '.rail-edge[data-rail="right"]');
      assert(Math.abs(edge.x + 4 - rail.x) <= 1 && edge.height >= 899, 'the rail can still be dragged by its left edge');
      assert.deepEqual(await railOrder(page), ['Active', 'Updates', 'Files', 'Recurring'], scheme + ': Active leads');
      assert.equal(await page.locator('#pane-tasks .card').count(), 0, 'no cards in the rail');
      assert.equal(await page.locator('#main >> text=Latest update').count(), 0, 'no Latest update banner');
      assert.equal(await page.locator('#bot-history-btn').count(), 0, 'all updates is in the rail now');
      // Updates: its age, and a quiet way to all of them; showing it there reads it.
      assert.match(await page.locator('#bot-latest .rail-age').innerText(), /10h ago/);
      assert.equal(await page.locator('#bot-latest a.rail-ico').getAttribute('href'), '#/bot/cmo/history');
      assert.match(await page.locator('#bot-latest .upd-body').innerText(), /two headline options/);
      for (let i = 0; i < 40 && !read.includes('u1'); i++) await page.waitForTimeout(50);
      assert.deepEqual(read, ['u1'], 'the latest update counts as read once the rail shows it');
      // Files: names only, three of them, and a small "+2" for the rest.
      assert.equal(await page.locator('#bot-files .bf-row').count(), 3);
      assert.equal(await page.locator('#bot-files .nav-icon').count(), 0, 'no icon before a name');
      assert.equal((await page.locator('#bot-files [data-bf-all]').innerText()).trim(), '+2');
      // Recurring: the bot's routines, one line each.
      assert.deepEqual(await page.locator('#bot-recurring .ttl').allInnerTexts(), ['Morning metrics digest', 'Friday launch review']);
      // Assigned to others opens while it waits on a person; Done stays folded.
      assert.equal(await page.locator('#bot-assigned').evaluate(el => el.open), true);
      assert.equal(await page.locator('#pane-tasks .bot-done').evaluate(el => el.open), false);
      // Dense rows: a task row and a file row stay under about 30px.
      assert((await box(page, '#t-open .trow summary')).height <= 30, 'a task row is short');
      assert((await box(page, '#bot-files .bf-row')).height <= 30, 'a file row is short');

      // Tools beside the name: the runtime mark, then three icons (not the model again) and "+5".
      const strip = page.locator('#bot-tool-strip');
      assert.equal(await page.locator('.bot-nameline .rt').count(), 1);
      assert.deepEqual(await strip.locator('.bts-icon').evaluateAll(els => els.map(el => el.dataset.tool)), ['repo', 'posthog', 'slack']);
      assert.equal((await strip.locator('.bts-more').innerText()).trim(), '+5');
      assert.equal(await strip.locator('.bts-more').getAttribute('aria-label'), 'All 9 tools');
      assert.equal(await strip.locator('[data-tool=slack]').getAttribute('title'), 'Slack');
      assert.match(await strip.locator('[data-tool=posthog]').getAttribute('aria-label'), /PostHog, PostHog project 12345 \(US\), personal key, Credential missing on Test Mac/);
      assert.equal(await strip.locator('[data-tool=posthog] .bt-dot').count(), 1, 'a problem shows a dot');
      const rt = await box(page, '.bot-nameline .rt'), first = await box(page, '#bot-tool-strip .bts-icon');
      assert(Math.abs(rt.height - first.height) <= 1 && Math.abs(rt.y - first.y) <= 2, 'the same size and line as the runtime mark');
      // A logo is drawn in the theme's ink, never the background's colour.
      const colors = await strip.locator('[data-tool=slack]').evaluate(el => ({ink: getComputedStyle(el).color, bg: getComputedStyle(document.body).backgroundColor}));
      assert.notEqual(colors.ink, colors.bg, scheme + ': contrast');
      if (shots) await page.screenshot({path: path.join(shots, `bot-page-desktop-${scheme}.png`)});

      // The icons and "+5" open the Tools card under More, every tool with its details.
      await strip.locator('[data-tool=posthog]').focus();
      await page.keyboard.press('Enter');
      await page.waitForFunction(() => location.hash === '#/bot/cmo/tools');
      const list = page.locator('#bot-tools');
      await list.locator('.bt-item').first().waitFor();
      assert.equal(await page.locator('#pane-more').isVisible(), true);
      assert.equal(await list.locator('.bt-item').count(), 9);
      const text = await list.innerText();
      for (const expected of ['openai/gpt-6-luna', 'acme-co/emp-cmo', 'PostHog project 12345 (US), personal key', '12345', 'POSTHOG_KEY',
        'funnels only', 'Credential missing on Test Mac', '#ops, #launch', 'SLACK_TOKEN', 'nothing to check', 'account 3'])
        assert(text.includes(expected), scheme + ': the list says ' + expected + '\n' + text);
      assert.equal(await list.locator('[data-tool=repo] a').getAttribute('href'), 'https://github.com/acme-co/emp-cmo');
      assert.equal(await list.locator('[data-tool=meeting-notes] .tool-initials').innerText(), 'Me');
      if (shots && scheme === 'dark') await page.screenshot({path: path.join(shots, 'bot-page-tools-desktop-dark.png')});
      assert.deepEqual(errors, [], scheme + ': page errors');
      await context.close();
    }

    // Nothing to show: no Updates, Files or Recurring section; Active still says so in one line.
    {
      const saved = bots[0].schedules; bots[0].schedules = [];
      const {page, errors, context} = await open(browser, {width: 1280, height: 800}, {}, {updates: [], files: []});
      await page.route('**/api/v2/tasks*', route => route.fulfill({contentType: 'application/json', body: JSON.stringify({tasks: []})}));
      await page.route('**/api/status', route => route.fulfill({contentType: 'application/json', body: JSON.stringify({cloud: true, active: [], queued: [], recent_runs: [], keeper_alive: true, health_issues: [], schedules: []})}));
      await page.goto('https://tico-ui.test/#/bot/cmo');
      await page.locator('#t-open .rail-empty:text("None")').waitFor();
      await page.waitForTimeout(300);
      assert.deepEqual(await railOrder(page), ['Active']);
      assert.deepEqual(errors, []);
      bots[0].schedules = saved;
      await context.close();
    }

    // A phone: one column; Tasks has Active first and the same sections; the tools are under More.
    for (const scheme of ['light', 'dark']) {
      const {page, errors, context} = await open(browser, {width: 390, height: 844}, {colorScheme: scheme});
      await page.goto('https://tico-ui.test/#/bot/cmo');
      await page.locator('#conv').waitFor();
      assert.equal(await page.locator('#pane-tasks').isVisible(), false, 'chat alone');
      assert.equal(await page.locator('#bot-tool-strip').isVisible(), false, 'no room for the tools beside the name');
      if (shots) await page.screenshot({path: path.join(shots, `bot-page-phone-chat-${scheme}.png`)});
      await page.evaluate(() => { location.hash = '#/bot/cmo/tasks'; });
      await page.locator('#t-open .trow').first().waitFor();
      await page.locator('#bot-files .bf-row').first().waitFor();
      await page.locator('#bot-latest:not([hidden])').waitFor();
      assert.deepEqual(await railOrder(page), ['Active', 'Updates', 'Files', 'Recurring']);
      assert(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth), 'no sideways scroll');
      if (shots) await page.screenshot({path: path.join(shots, `bot-page-phone-tasks-${scheme}.png`), fullPage: true});
      await page.evaluate(() => { location.hash = '#/bot/cmo/more'; });
      await page.locator('#bot-tools .bt-item').first().waitFor();
      assert.equal(await page.locator('#bot-tools .bt-item').count(), 9);
      assert(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth), 'More: no sideways scroll');
      assert.deepEqual(errors, [], scheme + ': phone page errors');
      await context.close();
    }
    console.log('bot page: full-height rail with Active first, Updates, Files, Recurring, empty sections gone; three tool icons and +N by the name open the Tools card under More; phone keeps one column; both themes');
  } finally { await browser.close(); }
})().catch(error => { console.error(error); process.exit(1); });
