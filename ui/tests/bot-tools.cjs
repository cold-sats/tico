// The Tools row on a bot's page (ui/bot-tools.js, ui/tool-icons.js): a round icon per tool, the logo when
// there is one and the name's first two letters when there is not, a popover with the identity, scope,
// note and status on hover, focus or tap (a sheet on a phone), Escape to close, and "+N" past eight
// tools opening the whole list; in both themes. Fixtures only, no network.
const {chromium} = require('playwright');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const {html, uiFile} = require('./support/page.cjs');

const bots = [{name: 'cmo', display_name: 'AI CMO', org_parent: '', host: 'keeper', status: 'active', can_chat: true,
  users: [{id: 'ana', name: 'Ana'}], schedules: []}];
const tool = (id, service, name, extra) => ({id, service, name, logo_key: null, identity: '', can: [], scope: {}, note: '',
  status: 'ready', ...extra});
const FEW = [
  tool('model', 'codex', 'Codex', {logo_key: 'openai', identity: 'openai/gpt-6-luna', can: ['use'], scope: {effort: 'high'}}),
  tool('repo', 'github', 'GitHub', {logo_key: 'github', identity: 'acme-co/emp-cmo', scope: {repo: 'acme-co/emp-cmo'}, url: 'https://github.com/acme-co/emp-cmo'}),
  tool('posthog', 'posthog', 'PostHog', {logo_key: 'posthog', identity: 'PostHog project 12345 (US), personal key', can: ['read'],
    scope: {project: '12345'}, env: 'POSTHOG_KEY', note: 'funnels only', status: 'problem', problem: 'Credential missing on Test Mac'}),
  tool('slack', 'slack', 'Slack', {logo_key: 'slack', identity: 'Acme workspace', can: ['read', 'post'], scope: {channels: ['#ops', '#launch']}, env: 'SLACK_TOKEN'}),
  tool('meeting-notes', 'meeting-notes', 'Meeting notes', {can: ['use'], status: 'unknown', detail: 'No credential is declared, so there is nothing to check'}),
];
const MANY = FEW.concat(Array.from({length: 6}, (_, n) => tool('extra' + n, 'extra' + n, 'Extra ' + n, {identity: 'account ' + n})));

async function open(browser, viewport, tools, options = {}) {
  const context = await browser.newContext({viewport, serviceWorkers: 'block', hasTouch: viewport.width < 760, isMobile: viewport.width < 760, ...options});
  const page = await context.newPage();
  const errors = [];
  page.on('pageerror', error => errors.push(error.message));
  await page.route('**/*', route => {
    const url = new URL(route.request().url()), p = url.pathname;
    const json = body => route.fulfill({contentType: 'application/json', body: JSON.stringify(body)});
    if (/\/marked\.min\.js$/.test(p)) return route.fulfill({contentType: 'application/javascript', body: 'window.marked={parse:s=>String(s)}'});
    if (url.origin !== 'https://tico-ui.test') return route.abort();
    const ui = p.match(/\/tico\/ui\/((?:app\/|styles\/)?[^/]+\.(?:js|css))$/);
    if (ui && fs.existsSync(uiFile(ui[1]))) return route.fulfill({contentType: ui[1].endsWith('.css') ? 'text/css' : 'application/javascript', body: fs.readFileSync(uiFile(ui[1]), 'utf8')});
    if (p === '/') return route.fulfill({contentType: 'text/html', body: html});
    if (p === '/api/me') return json({id: 'ana', role: 'owner', name: 'Ana', email: 'ana@example.test', cloud: true});
    if (p === '/api/humans') return json({people: [{id: 'ana', name: 'Ana'}]});
    if (p === '/api/employees') return json(bots);
    if (p === '/api/status') return json({cloud: true, active: [], queued: [], recent_runs: [], keeper_alive: true, health_issues: [], schedules: []});
    if (p === '/api/v2/status') return json({bots: [{bot: 'cmo', state: 'idle'}]});
    if (p === '/api/v2/goals') return json({goals: [], chain: [], reports: [], company: []});
    if (p === '/api/v2/updates') return json({updates: [], missed: [], unread: 0, next_before: null, today: {}});
    if (p === '/api/v2/tasks') return json({tasks: []});
    if (p === '/api/v2/conversations') return json({conversations: []});
    if (p === '/api/v2/bots/cmo/tools') return json({bot: 'cmo', tools, computer: 'Test Mac', online: true, reported_at: null});
    if (p === '/api/v2/bots/cmo/files') return json({bot: 'cmo', files: [], total: 0, next_cursor: null, has_more: false, can_manage: true, actors: {}});
    if (p.endsWith('/watch')) return route.fulfill({contentType: 'text/event-stream', body: ': fixture\n\n'});
    return json({});
  });
  return {page, errors, context};
}

const visible = (page, selector) => page.locator(selector).isVisible();

(async () => {
  const browser = await chromium.launch({headless: true, channel: process.env.TICO_BROWSER_CHANNEL === undefined ? 'chrome' : process.env.TICO_BROWSER_CHANNEL || undefined});
  try {
    for (const scheme of ['light', 'dark']) {
      const {page, errors, context} = await open(browser, {width: 1280, height: 900}, FEW, {colorScheme: scheme});
      await page.goto('https://tico-ui.test/#/bot/cmo');
      await page.locator('#bot-tools .bt-icon').first().waitFor();
      const icons = page.locator('#bot-tools .bt-icon');
      assert.equal(await icons.count(), 5, scheme + ': one icon per tool');
      assert.equal(await page.evaluate(() => document.getElementById('bot-tools').parentElement.id), 'pane-tasks', 'the right column holds the row');
      // Logos for the services we bundle, the name's first two letters for the rest.
      for (const id of ['model', 'repo', 'posthog', 'slack']) assert.equal(await page.locator(`[data-tool=${id}] svg`).count(), 1, scheme + ': ' + id + ' logo');
      assert.equal((await page.locator('[data-tool=meeting-notes] .tool-initials').innerText()).trim(), 'Me');
      assert.equal(await page.locator('[data-tool=meeting-notes] svg').count(), 0);
      assert.equal(await page.locator('[data-tool=posthog] .bt-dot').count(), 1, 'a problem shows a dot');
      assert.equal(await page.locator('[data-tool=slack] .bt-dot').count(), 0);
      // A logo is drawn in the theme's ink, never the background's colour.
      const colors = await page.locator('[data-tool=slack]').evaluate(el => ({ink: getComputedStyle(el).color, fill: getComputedStyle(el.querySelector('svg')).color, bg: getComputedStyle(el).backgroundColor}));
      assert.notEqual(colors.ink, colors.bg, scheme + ': contrast');
      assert.equal(colors.fill, colors.ink);
      assert.match(await page.locator('[data-tool=posthog]').getAttribute('aria-label'), /PostHog, PostHog project 12345 \(US\), personal key, Credential missing on Test Mac/);

      // Hover shows the details.
      const pop = page.locator('.bt-pop');
      await page.locator('[data-tool=posthog]').hover();
      await pop.waitFor({state: 'visible'});
      assert.equal(await pop.getAttribute('role'), 'dialog');
      assert.equal(await pop.getAttribute('aria-label'), 'PostHog');
      const text = await pop.innerText();
      for (const expected of ['PostHog project 12345 (US), personal key', 'Project', '12345', 'POSTHOG_KEY', 'funnels only', 'Credential missing on Test Mac', 'read'])
        assert(text.includes(expected), scheme + ': popover says ' + expected + '\n' + text);
      assert.equal(await page.locator('[data-tool=posthog]').getAttribute('aria-expanded'), 'true');
      await page.mouse.move(700, 600);
      await pop.waitFor({state: 'hidden'});

      // Keyboard: Tab to an icon opens it, Escape closes it and keeps focus on the icon.
      await page.locator('[data-tool=repo]').focus();
      await page.keyboard.press('Shift+Tab');
      await page.keyboard.press('Tab');
      await pop.waitFor({state: 'visible'});
      assert.match(await pop.innerText(), /acme-co\/emp-cmo/);
      assert.equal(await page.locator('.bt-pop a').getAttribute('href'), 'https://github.com/acme-co/emp-cmo');
      await page.keyboard.press('Escape');
      await pop.waitFor({state: 'hidden'});
      assert.equal(await page.evaluate(() => document.activeElement.dataset.tool), 'repo');

      // A click pins it: it stays when the pointer leaves, and shows the scope lists and verbs.
      await page.locator('[data-tool=slack]').click();
      await page.mouse.move(700, 600);
      await page.waitForTimeout(400);
      assert(await visible(page, '.bt-pop'), 'a click pins the popover');
      const slack = await pop.innerText();
      for (const expected of ['Acme workspace', 'read', 'post', 'Channels', '#ops, #launch', 'SLACK_TOKEN', 'Ready']) assert(slack.includes(expected), 'slack: ' + expected);
      const box = await pop.boundingBox();
      assert(box.x >= 0 && box.x + box.width <= 1280 && box.y >= 0 && box.y + box.height <= 900, 'the popover stays on screen');
      if (scheme === 'dark') await page.screenshot({path: process.env.TOOLS_SHOT_DARK || path.join(require('node:os').tmpdir(), 'bot-tools-dark.png')});
      else await page.screenshot({path: process.env.TOOLS_SHOT_LIGHT || path.join(require('node:os').tmpdir(), 'bot-tools-light.png')});
      await page.mouse.click(700, 500);
      await pop.waitFor({state: 'hidden'});
      // The unknown tool says so in words.
      await page.locator('[data-tool=meeting-notes]').click();
      assert.match(await pop.innerText(), /Not checked[\s\S]*nothing to check/);
      assert.deepEqual(errors, [], scheme + ': page errors');
      await context.close();
    }

    // More than eight: eight icons and "+N", which opens the whole list.
    {
      const {page, errors, context} = await open(browser, {width: 1280, height: 900}, MANY);
      await page.goto('https://tico-ui.test/#/bot/cmo');
      await page.locator('#bot-tools .bt-icon').first().waitFor();
      assert.equal(await page.locator('#bot-tools .bt-icon').count(), 8);
      assert.equal((await page.locator('#bot-tools .bt-more').innerText()).trim(), '+3');
      assert.equal(await page.locator('#bot-tools .bt-more').getAttribute('aria-label'), 'Show all 11 tools');
      await page.locator('#bot-tools .bt-more').click();
      await page.locator('.bt-pop').waitFor({state: 'visible'});
      assert.equal(await page.locator('.bt-pop .bt-item').count(), 11);
      assert.match(await page.locator('.bt-pop').innerText(), /Extra 5[\s\S]*account 5/);
      await page.keyboard.press('Escape');
      await page.locator('.bt-pop').waitFor({state: 'hidden'});
      assert.deepEqual(errors, []);
      await context.close();
    }

    // A phone: the row sits above the chat, and a tap opens a sheet along the bottom edge.
    for (const url of ['#/bot/cmo', '#/bot/cmo/tasks']) {
      const {page, errors, context} = await open(browser, {width: 390, height: 800}, FEW);
      await page.goto('https://tico-ui.test/' + url);
      await page.locator('#bot-tools .bt-icon').first().waitFor();
      const row = await page.locator('#bot-tools').boundingBox();
      assert(row.y < 220, url + ': the row is near the top (' + row.y + ')');
      assert(row.x + row.width <= 390);
      await page.locator('[data-tool=posthog]').tap();
      await page.locator('.bt-pop').waitFor({state: 'visible'});
      const sheet = await page.locator('.bt-pop').boundingBox();
      assert(Math.abs(sheet.width - 390) < 2 && Math.abs(sheet.y + sheet.height - 800) < 2, url + ': a sheet along the bottom');
      assert.match(await page.locator('.bt-pop').innerText(), /Credential missing on Test Mac/);
      assert(await visible(page, '.bt-scrim'));
      assert(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth), 'no sideways scroll');
      await page.locator('.bt-close').tap();
      await page.locator('.bt-pop').waitFor({state: 'hidden'});
      await page.locator('[data-tool=slack]').tap();
      await page.locator('.bt-pop').waitFor({state: 'visible'});
      await page.locator('.bt-scrim').tap({position: {x: 100, y: 60}});
      await page.locator('.bt-pop').waitFor({state: 'hidden'});
      assert.deepEqual(errors, [], url + ': page errors');
      await context.close();
    }
    console.log('bot tools row: logos and initials, popover on hover, focus and click, Escape, +N list, phone sheet, both themes');
  } finally { await browser.close(); }
})().catch(error => { console.error(error); process.exit(1); });
