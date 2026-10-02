// Page layouts after a bot page (ui/app/router.js): the bot page makes #main a two-column grid (bot-split-layout);
// leaving it must leave nothing behind, so Docs, Meetings and Goals each start at the top of the page with their
// own layout, on a desktop and a phone. Goals: the tree is the page and the Goal Manager a full-height right rail.
// The Assistant: the bot page's top line and rail. The bot page: "Set goal" alone when there is no goal, and each
// tool icon's tooltip tells two GitHub repositories apart. Fixtures only, no network.
// TICO_SCREENSHOT_DIR keeps screenshots.
const {chromium} = require('playwright');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const {html, uiFile} = require('./support/page.cjs');
const shots = process.env.TICO_SCREENSHOT_DIR;
if (shots) fs.mkdirSync(shots, {recursive: true});

const now = Date.now(), iso = ms => new Date(now + ms).toISOString(), hour = 3600e3;
const bot = (name, display_name, over) => ({name, display_name, org_parent: '', host: 'keeper', status: 'active', can_chat: true, ...over});
const BOTS = [bot('cmo', 'AI CMO', {org_parent: 'p:ana', runtime: 'codex'}), bot('coo', 'Assistant'), bot('librarian', 'Librarian'),
  bot('goal-manager', 'Goal Manager', {schedules: [{id: 'gm-review', title: 'Checks goals', cron: '0 9 * * *', active: true, next: iso(10 * hour)}]})];
const tool = (id, service, name, extra) => ({id, service, name, logo_key: null, identity: '', can: [], scope: {}, note: '', status: 'ready', ...extra});
const TOOLS = [
  tool('model', 'codex', 'Codex', {logo_key: 'openai', identity: 'openai/gpt-6-luna', can: ['use']}),
  tool('repo', 'github', 'GitHub', {logo_key: 'github', identity: 'acme-co/emp-cmo', can: ['read', 'write', 'issues', 'pull_requests'], scope: {repo: 'acme-co/emp-cmo'},
    url: 'https://github.com/acme-co/emp-cmo', status: 'unknown', detail: 'Own repository: instructions and memory. Token capabilities are separate from declared tool policy.'}),
  tool('github-extra-0', 'github', 'GitHub', {logo_key: 'github', identity: 'acme-co/website', can: ['read'], scope: {repo: 'acme-co/website'},
    url: 'https://github.com/acme-co/website', status: 'unknown', detail: 'Granted repository. Token capabilities are separate from declared tool policy.'}),
  tool('posthog', 'posthog', 'PostHog', {logo_key: 'posthog', identity: 'PostHog project 12345 (US)', can: ['read'], scope: {project: '12345'},
    env: 'POSTHOG_KEY', status: 'problem', problem: 'Credential missing on Test Mac'}),
  tool('pending-1', 'gmail', 'Gmail', {logo_key: 'gmail', identity: 'cmo@acme.example', can: ['read', 'draft'], status: 'pending', pending: 'add'}),
];
const task = (id, title, owner, extra) => ({id, title, status: 'doing', owner: 'bot:' + owner, requester: 'human:ana', created: iso(-30 * hour), updated: iso(-hour), ...extra});
const GOALS = [{id: 'g-top', title: 'Grow revenue 30% this year', owner: 'company', parent_id: null, status: 'green', status_source: 'auto', rank: 0, kpis: []},
  {id: 'g-cmo', title: 'Double organic signups', owner: 'bot:cmo', parent_id: 'g-top', status: 'yellow', status_source: 'auto', rank: 0, kpis: []}];
const DOCS = [['d1', 'support/refund-policy.md', 'Refund policy'], ['d2', 'pricing.md', 'Pricing and plans'], ['d3', '_librarian/index.md', 'Index']]
  .map(([id, p, title]) => ({id, path: p, title, updated: iso(-5 * hour), updated_by: 'human:ana', locked: false, version: 1}));
const meeting = (id, title, ms) => ({id, title, source: 'granola', kind: 'meeting', status: 'done', started: iso(-ms), created: iso(-ms),
  duration_ms: 1800000, participants: [{name: 'Ana'}], outbox: {doc: [], task: [], feature: []}});

async function open(browser, viewport, world = {}) {
  const phone = viewport.width < 760;
  const context = await browser.newContext({viewport, serviceWorkers: 'block', colorScheme: 'dark', hasTouch: phone, isMobile: phone});
  await context.addInitScript(() => { try { localStorage.setItem('tico.theme', 'dark'); } catch {} });
  const page = await context.newPage();
  const errors = [];
  page.on('pageerror', error => errors.push(error.message));
  const goalOf = world.goal ? [{id: 'g-cmo', title: 'Double organic signups', owner: 'bot:cmo', status: 'yellow'}] : [];
  await page.route('**/*', route => {
    const url = new URL(route.request().url()), p = url.pathname, q = url.searchParams, method = route.request().method();
    const json = (body, status = 200) => route.fulfill({status, contentType: 'application/json', body: JSON.stringify(body)});
    if (url.origin !== 'https://tico-ui.test') return route.abort();
    const vendor = p.match(/^\/vendor\/((?:fonts\/)?[\w.-]+)$/);
    if (vendor && fs.existsSync(uiFile('vendor/' + vendor[1]))) return route.fulfill({path: uiFile('vendor/' + vendor[1])});
    const ui = p.match(/\/tico\/ui\/((?:app\/|styles\/)?[^/]+\.(?:js|css))$/);
    if (ui && fs.existsSync(uiFile(ui[1]))) return route.fulfill({contentType: ui[1].endsWith('.css') ? 'text/css' : 'application/javascript', body: fs.readFileSync(uiFile(ui[1]), 'utf8')});
    if (p === '/') return route.fulfill({contentType: 'text/html', body: html});
    if (p === '/api/me') return json({id: 'ana', role: 'owner', name: 'Ana', email: 'ana@acme.example', cloud: true, bot_admin: true});
    if (p === '/api/humans') return json({people: [{id: 'ana', name: 'Ana', org_parent: ''}]});
    if (p === '/api/employees') return json(BOTS);
    if (p === '/api/issues') return json([]);
    if (p === '/api/status') return json({cloud: true, active: [], queued: [], recent_runs: [], keeper_alive: true, health_issues: [], schedules: []});
    if (p === '/api/v2/status') return json({bots: [{bot: 'goal-manager', state: 'idle', last_turn_at: iso(-3 * hour), last_result: 'Updated KPI readings.'}]});
    if (p === '/api/v2/goals') return json({goals: q.get('owner') === 'bot:cmo' ? goalOf : [], chain: [], reports: [], company: []});
    if (p === '/api/v2/goals/tree') return json({goals: GOALS, owners: {}, other_kpis: [], proposals: []});
    if (p === '/api/v2/goals/needs-you') return json({actor: 'human:ana', items: []});
    if (p === '/api/v2/bots/goal-manager/routines') return json({routines: [{id: 'gm-review', title: 'Checks goals', cron: '0 9 * * *', active: true, enabled: true, timezone: 'UTC', next: iso(10 * hour)}]});
    if (p === '/api/v2/routines/gm-review/occurrences') return json({occurrences: [{started: iso(-3 * hour), title: 'Checks goals', exit: 'completed'}]});
    if (p === '/api/v2/updates') return json({updates: q.get('bot') === 'coo' && world.assistantUpdate
      ? [{id: 'u-coo', bot: 'coo', kind: 'daily', read: true, created: iso(-2 * hour), updated: iso(-2 * hour), body: 'Filed two follow-ups from the launch thread.'}] : [],
      missed: [], unread: 0, next_before: null, today: {}});
    if (p === '/api/v2/tasks') return json({tasks: q.get('owner') === 'cmo' ? [task('t1', 'Draft the October pricing page copy', 'cmo')]
      : q.get('owner') === 'coo' && world.assistantTasks ? [task('t9', 'Chase the signed contract from Dana', 'coo')] : []});
    if (p === '/api/v2/conversations') return json({conversations: q.get('chat_with') === 'cmo' ? [{id: 'c-cmo', kind: 'chat', scope: 'personal', participants: ['human:ana', 'bot:cmo']}] : []});
    if (p === '/api/v2/conversations/c-cmo/snapshot') return json({messages: [{id: 'm1', from_actor: 'bot:cmo', body: 'The copy is drafted.', created: iso(-hour)}]});
    if (p === '/api/v2/bots/cmo/tools') return json({bot: 'cmo', tools: TOOLS, computer: 'Test Mac', online: true});
    if (/^\/api\/v2\/bots\/[^/]+\/files$/.test(p)) return json({files: [], total: 0, next_cursor: null, has_more: false, can_manage: true, actors: {}});
    const asked = [{id: 'a1', from_actor: 'human:ana', body: "What's waiting on me?", created: iso(-hour), kind: 'say', refs: {}},
      {id: 'a2', from_actor: 'bot:coo', body: '1 thing waiting on you: approve the pricing page.', created: iso(-hour), kind: 'say', refs: {}}];
    if (p === '/api/v2/assistant') return json({available: true, state: 'active', bot: 'coo', name: 'Assistant', room_id: 'room1', messages: asked,
      has_more: false, next_before: null, execution: null, actions: {}, pending: []});
    if (p === '/api/v2/conversations/room1/snapshot') return json({messages: asked, execution: null, has_more: false, next_before: null});
    if (p === '/api/v2/docs') return json({docs: DOCS, next_cursor: null});
    if (p === '/api/v2/linked-docs') return json({linked: [{id: 'l1', title: 'Help centre', url: 'https://help.acme.example', kind: 'website', host: 'help.acme.example', created: iso(-hour)}]});
    if (p === '/api/v2/librarian/conversations') return json({conversations: []});
    if (p === '/api/meetings/sources') return json({sources: [{id: 'import', name: 'Import', status: 'available'}]});
    if (p === '/api/meetings') return json([meeting('g1', 'Renewal call with Dana', 5 * hour), meeting('g2', 'Pricing review', 26 * hour)]);
    if (p === '/api/v2/meeting-importers') return json({computers: [], importers: []});
    if (p === '/api/v2/meetings/granola') return json({mode: 'off', connected: false, plan_hint: null, last_sync: null, last_error: null, imported_count: 0, skipped: 0, needs_signin: false, syncing: false});
    if (p === '/api/v2/setup/getting-started') return json({items: [], done: 0, total: 0, complete: true, dismissed: true, tour_seen: true, cards_dismissed: []});
    if (p.endsWith('/watch')) return route.fulfill({contentType: 'text/event-stream', body: ': fixture\n\n'});
    return json({});
  });
  return {page, errors, context};
}
const go = (page, hash) => page.evaluate(h => { location.hash = h; }, hash);
const box = (page, selector) => page.locator(selector).first().boundingBox();
const noSideways = page => page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth);
const shot = (page, name, full) => shots ? page.screenshot({path: path.join(shots, name + '.png'), animations: 'disabled', fullPage: !!full}) : null;
const layoutClasses = page => page.evaluate(() => document.querySelector('#main').className);

(async () => {
  const browser = await chromium.launch({headless: true, channel: process.env.TICO_BROWSER_CHANNEL === undefined ? 'chrome' : process.env.TICO_BROWSER_CHANNEL || undefined});
  try {
    // A desktop: the bot page first, then each page in turn.
    {
      const {page, errors, context} = await open(browser, {width: 1440, height: 900});
      await page.goto('https://tico-ui.test/#/bot/cmo');
      await page.locator('#bot-tool-strip .bts-icon').first().waitFor();
      assert.match(await layoutClasses(page), /bot-split-layout/);
      // No goal: "Set goal" alone.
      await page.locator('#bot-goal-set').waitFor();
      assert.equal((await page.locator('#bot-goal').innerText()).trim(), 'Set goal');
      // Tool icons: both GitHub icons are on the strip, and their tooltips tell them apart.
      const strip = page.locator('#bot-tool-strip');
      assert.deepEqual(await strip.locator('.bts-icon').evaluateAll(els => els.map(el => el.dataset.tool)), ['repo', 'github-extra-0', 'posthog']);
      const tipOf = async id => {
        await strip.locator(`[data-tool="${id}"]`).hover();
        const tip = page.locator('#bts-tip');
        await tip.waitFor({state: 'visible'});
        const text = await tip.innerText();
        assert.equal(await strip.locator(`[data-tool="${id}"]`).getAttribute('aria-describedby'), 'bts-tip');
        return text;
      };
      const own = await tipOf('repo');
      assert.match(own, /acme-co\/emp-cmo/);
      assert.match(own, /Own repository/);
      assert.match(own, /Read and write/);
      const granted = await tipOf('github-extra-0');
      assert.match(granted, /acme-co\/website/);
      assert.match(granted, /Read only/);
      assert.doesNotMatch(granted, /Own repository/);
      const posthog = await tipOf('posthog');
      assert.match(posthog, /PostHog project 12345 \(US\)/);
      assert.match(posthog, /Credential missing on Test Mac/);
      assert.match(posthog, /Project\s+12345/);
      await strip.locator('[data-tool="repo"]').hover();
      await page.locator('#bts-tip').waitFor({state: 'visible'});
      await shot(page, 'bot-tool-tooltip-desktop-dark');
      await page.keyboard.press('Escape');
      await page.locator('#bts-tip').waitFor({state: 'hidden'});
      // Keyboard focus shows it too.
      await strip.locator('[data-tool="github-extra-0"]').focus();
      await page.locator('#bts-tip', {hasText: 'acme-co/website'}).waitFor({state: 'visible'});

      // The full Tools list: each GitHub repository with its access.
      await go(page, '#/bot/cmo/tools');
      await page.locator('#bot-tools .bt-item').first().waitFor();
      const repoRow = await page.locator('#bot-tools [data-tool="repo"]').innerText();
      assert.match(repoRow, /Own repository/);
      assert.match(await page.locator('#bot-tools [data-tool="github-extra-0"]').innerText(), /Read only/);
      await go(page, '#/bot/cmo');
      await page.locator('#pane-tasks:not([hidden])').waitFor();
      assert.match(await layoutClasses(page), /bot-split-layout/);

      // Docs: the header at the top, the list and reader in the main column, the Librarian's rail at the right.
      await go(page, '#/docs');
      await page.locator('#docs-browser .docs-tree, #docs-browser [data-doc], #docs-browser a').first().waitFor();
      assert.doesNotMatch(await layoutClasses(page), /bot-split-layout/, 'the bot page leaves no layout behind');
      const head = await box(page, '.docs-heading'), browserBox = await box(page, '#docs-browser'), sidebar = await box(page, '#side');
      assert(head.y < 80, 'the Docs header is at the top: ' + JSON.stringify(head));
      assert(Math.abs(browserBox.x - head.x) <= 2 && browserBox.y > head.y && browserBox.y < head.y + head.height + 60, 'the list sits under the header, at its left: ' + JSON.stringify({head, browserBox}));
      assert(browserBox.x < sidebar.x + sidebar.width + 60, 'the list starts beside the sidebar');
      const rail = await page.locator('.dask').boundingBox();
      if (rail) {
        assert(rail.y <= 1 && Math.abs(rail.x + rail.width - 1440) <= 1, 'the Librarian rail is at the right edge');
        assert(head.x + head.width <= rail.x + 1, 'the header stays left of the Librarian rail');
      }
      await shot(page, 'docs-desktop-dark');

      // Meetings: the header at the top; Granola is a compact row inside the page, above the sources strip.
      await go(page, '#/bot/cmo');
      await page.locator('#pane-tasks:not([hidden])').waitFor();
      await go(page, '#/meetings');
      await page.locator('#mg-row').waitFor();
      const mHead = await box(page, '#main h1'), granola = await box(page, '#meet-granola'), main = await box(page, '#main');
      assert(mHead.y < 80, 'the Meetings header is at the top');
      assert(granola.y > mHead.y && granola.x < mHead.x + 4 && granola.x >= main.x, 'Granola sits in the page under the header: ' + JSON.stringify({mHead, granola}));
      assert(granola.height <= 64, 'one compact row: ' + granola.height);
      const strip2 = await page.locator('#meet-granola ~ *').first().boundingBox();
      if (strip2) assert(strip2.y >= granola.y + granola.height - 1, 'above what follows');
      await shot(page, 'meetings-desktop-dark');

      // Goals: no page title in view; the tree is the page; the Goal Manager is a full-height right rail.
      await go(page, '#/bot/cmo');
      await page.locator('#pane-tasks:not([hidden])').waitFor();
      await go(page, '#/goals');
      await page.locator('#goal-tree').waitFor();
      await page.locator('.gm-routines li b').first().waitFor();
      assert.match(await layoutClasses(page), /goals-layout/);
      assert.doesNotMatch(await layoutClasses(page), /bot-split-layout/);
      assert(((await box(page, '#main h1')).width) <= 1, 'no visible Goals title (screen readers only); the sidebar says where you are');
      const tree = await box(page, '#goal-tree'), gm = await box(page, '#goal-manager-panel');
      assert(tree.y < 80, 'the tree starts at the top: ' + JSON.stringify(tree));
      assert(gm.y <= 1 && Math.abs(gm.y + gm.height - 900) <= 1, 'the Goal Manager runs the full height: ' + JSON.stringify(gm));
      assert(Math.abs(gm.x + gm.width - 1440) <= 1 && gm.width >= 280, 'at the right edge, a proper rail');
      assert(tree.x + tree.width <= gm.x, 'the tree stays left of the rail');
      const form = await box(page, '.gm-form textarea');
      assert(form.width >= 180 && form.x >= gm.x, 'the chat box has room: ' + form.width);
      assert.equal(await page.locator('#goal-manager-panel .rail-sec').count() >= 2, true, 'dense rail sections');
      assert.match(await page.locator('#goal-manager-panel').innerText(), /Checks goals/);
      await shot(page, 'goals-desktop-dark');

      // The Assistant: the bot page's top line, no goal; no rail when it has nothing to show.
      await go(page, '#/assistant');
      await page.locator('#conv-thread', {hasText: 'approve the pricing page'}).waitFor();
      const top = await box(page, '#bot-top');
      assert(top.y < 60, 'the top line is at the top');
      assert.equal(await page.locator('#bot-goal').count(), 0, 'no goal line');
      assert.equal(await page.locator('#pane-tasks').isVisible(), false, 'no rail with nothing in it');
      assert.equal((await page.locator('#bot-top h1').innerText()).trim(), 'Assistant');
      assert.deepEqual(errors, []);
      await context.close();
    }

    // The Assistant with work: the same dense rail as a bot page.
    {
      const {page, errors, context} = await open(browser, {width: 1440, height: 900}, {assistantTasks: true, assistantUpdate: true});
      await page.goto('https://tico-ui.test/#/assistant');
      await page.locator('#pane-tasks .trow, #pane-tasks [data-task]').first().waitFor();
      await page.locator('#asst-latest:not([hidden])').waitFor();
      assert.match(await layoutClasses(page), /bot-split-layout/);
      const rail = await box(page, '#pane-tasks');
      assert(rail.y <= 1 && Math.abs(rail.x + rail.width - 1440) <= 1, 'a full-height rail at the right');
      assert.match(await page.locator('#pane-tasks').innerText(), /Chase the signed contract/);
      await shot(page, 'assistant-desktop-dark');
      // Leaving it leaves nothing behind.
      await go(page, '#/docs');
      await page.locator('.docs-heading').waitFor();
      assert(((await box(page, '.docs-heading')).y) < 80);
      assert.deepEqual(errors, []);
      await context.close();
    }

    // A phone: Docs and Goals after a bot page, one column, no sideways scroll.
    {
      const {page, errors, context} = await open(browser, {width: 390, height: 844});
      await page.goto('https://tico-ui.test/#/bot/cmo');
      await page.locator('#conv').waitFor();
      await go(page, '#/docs');
      await page.locator('.docs-heading').waitFor();
      await page.locator('#docs-browser a, #docs-browser [data-doc]').first().waitFor();
      assert((await box(page, '.docs-heading')).y < 80, 'phone: the Docs header is at the top');
      assert(await noSideways(page), 'phone Docs: no sideways scroll');
      await shot(page, 'docs-phone-dark');
      await go(page, '#/goals');
      await page.locator('#goal-tree').waitFor();
      await page.locator('.gm-routines li b').first().waitFor();
      const tree = await box(page, '#goal-tree'), gm = await box(page, '#goal-manager-panel');
      assert(tree.y < 80, 'phone: the tree leads');
      assert(gm.y >= tree.y + tree.height - 1 && gm.width >= 340, 'phone: the Goal Manager follows the tree, full width');
      assert(await noSideways(page), 'phone Goals: no sideways scroll');
      await shot(page, 'goals-phone-dark', true);
      assert.deepEqual(errors, []);
      await context.close();
    }
  } finally {
    await browser.close();
  }
})().catch(e => { console.error(e); process.exit(1); });
