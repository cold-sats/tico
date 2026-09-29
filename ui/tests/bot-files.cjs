// The Files card on a bot's page (ui/bot-files.js): three rows and the total, Show all and Show less
// inline, Open for a linked document (the provider, a new tab) and for a stored file (Tico's own
// route, never a storage address), Working from the linked task, "not synced" with no Open link,
// View on GitHub, the owner's Remove; on a computer and on a phone. Fixtures only, no network.
const {chromium} = require('playwright');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const html = fs.readFileSync(path.join(__dirname, '../index.html'), 'utf8');

const now = Date.now(), iso = ms => new Date(now + ms).toISOString(), min = 60e3;
const bots = [{name: 'cmo', display_name: 'AI CMO', org_parent: '', host: 'keeper', status: 'active', can_chat: true,
  users: [{id: 'ana', name: 'Ana'}], schedules: []}];
const GDOC = 'https://docs.google.com/document/d/1AbCdEfGhIjKlMnOp/edit';
const file = (id, extra) => ({id, bot: 'cmo', title: id, kind: 'document', mime: '', locator: 'tico_blob', scope: 'task', version: 1,
  state: 'ready', synced: true, size: 10, name: id + '.md', open: {type: 'tico', url: '/api/v2/files/' + id}, provider: '', provider_label: '',
  note: '', source: '', task_id: null, task_title: null, working: false, github_url: null, actor: 'bot:cmo', actor_name: 'AI CMO',
  action: 'modified', first_activity_at: iso(-90 * min), last_activity_at: iso(-90 * min), archived: false, ...extra});
const files = [
  file('file-000000000000000000000001', {title: 'Q4 launch plan', kind: 'document', locator: 'remote_link', mime: '', open: {type: 'external', url: GDOC},
    provider: 'google', provider_label: 'Google', note: 'Link opens in Google (requires access)', task_id: 't1', task_title: 'Publish the pricing page',
    working: true, last_activity_at: iso(-12 * min)}),
  file('file-000000000000000000000002', {title: 'Weekly report', github_url: 'https://github.com/acme/emp-cmo/blob/abc1234/reports/weekly.md', last_activity_at: iso(-3 * 60 * min)}),
  file('file-000000000000000000000003', {title: 'Budget', kind: 'spreadsheet', state: 'not_synced', synced: false, open: null, last_activity_at: iso(-5 * 60 * min)}),
  file('file-000000000000000000000004', {title: 'Traffic export', kind: 'spreadsheet', source: 's3', last_activity_at: iso(-30 * 60 * min)}),
  file('file-000000000000000000000005', {title: 'Old brief', last_activity_at: iso(-60 * 60 * min)}),
];

async function open(browser, viewport, state) {
  const page = await browser.newPage({viewport, serviceWorkers: 'block', hasTouch: viewport.width < 760});
  const errors = [];
  page.on('pageerror', error => errors.push(error.message));
  await page.route('**/*', route => {
    const url = new URL(route.request().url()), p = url.pathname, q = url.searchParams;
    const json = body => route.fulfill({contentType: 'application/json', body: JSON.stringify(body)});
    if (/\/marked\.min\.js$/.test(p)) return route.fulfill({contentType: 'application/javascript', body: 'window.marked={parse:s=>String(s)}'});
    if (url.origin !== 'https://tico-ui.test') return route.abort();
    const ui = p.match(/\/tico\/ui\/([^/]+\.js)$/);
    if (ui && fs.existsSync(path.join(__dirname, '..', ui[1]))) return route.fulfill({contentType: 'application/javascript', body: fs.readFileSync(path.join(__dirname, '..', ui[1]), 'utf8')});
    if (p === '/') return route.fulfill({contentType: 'text/html', body: html});
    if (p === '/api/me') return json({id: 'ana', role: 'owner', name: 'Ana', email: 'ana@example.test', cloud: true});
    if (p === '/api/people') return json({people: [{id: 'ana', name: 'Ana'}]});
    if (p === '/api/employees') return json(bots);
    if (p === '/api/status') return json({cloud: true, active: [], queued: [], recent_runs: [], keeper_alive: true, health_issues: [], schedules: []});
    if (p === '/api/v2/status') return json({bots: [{bot: 'cmo', state: 'idle'}]});
    if (p === '/api/v2/goals') return json({goals: [], chain: [], reports: [], company: []});
    if (p === '/api/v2/updates') return json({updates: [], missed: [], unread: 0, next_before: null, today: {}});
    if (p === '/api/v2/tasks') return json({tasks: []});
    if (p === '/api/v2/conversations') return json({conversations: []});
    if (p === '/api/v2/bots/cmo/files') {
      state.listed.push(q.get('limit'));
      const limit = Number(q.get('limit')), rows = state.rows;
      return json({bot: 'cmo', files: rows.slice(0, limit), total: rows.length, next_cursor: rows.length > limit ? 'next' : null,
        has_more: rows.length > limit, can_manage: true, actors: {}});
    }
    const patch = p.match(/^\/api\/v2\/files\/([^/]+)$/);
    if (patch && route.request().method() === 'PATCH') {
      state.patched.push([patch[1], JSON.parse(route.request().postData())]);
      state.rows = state.rows.filter(f => f.id !== patch[1]);
      return json({file: {id: patch[1]}});
    }
    if (patch) { state.opened.push(patch[1]); return route.fulfill({contentType: 'application/octet-stream', headers: {'Content-Disposition': "attachment; filename*=UTF-8''weekly.md"}, body: '# Weekly'}); }
    if (p.endsWith('/watch')) return route.fulfill({contentType: 'text/event-stream', body: ': fixture\n\n'});
    return json({});
  });
  return {page, errors};
}

(async () => {
  const browser = await chromium.launch({headless: true, channel: process.env.TICO_BROWSER_CHANNEL === undefined ? 'chrome' : process.env.TICO_BROWSER_CHANNEL || undefined});
  try {
    for (const [tag, viewport, url] of [['desktop', {width: 1280, height: 900}, '#/bot/cmo'], ['phone', {width: 390, height: 800}, '#/bot/cmo/tasks']]) {
      const state = {rows: files.slice(), listed: [], patched: [], opened: []};
      const {page, errors} = await open(browser, viewport, state);
      await page.goto('https://tico-ui.test/' + url);
      const card = page.locator('#bot-files');
      await card.locator('.bf-row').first().waitFor();
      assert.equal(await card.locator('.bf-row').count(), 3, tag + ': three rows');
      assert.equal((await card.locator('[data-bf-total]').innerText()).trim(), '5', tag + ': the total');
      assert.deepEqual(await card.locator('.bf-name').allInnerTexts(), ['Q4 launch plan', 'Weekly report', 'Budget'], tag + ': newest activity first');
      const first = card.locator('.bf-row').nth(0);
      assert.match(await first.locator('.bf-meta').innerText(), /Edited 12 minutes ago by AI CMO · Publish the pricing page/);
      assert.match(await first.locator('.bf-meta').innerText(), /Link opens in Google \(requires access\)/);
      assert.equal(await first.locator('[data-bf-working]').count(), 1, tag + ': Working comes from the linked task');
      const link = first.locator('[data-bf-open=external]');
      assert.equal(await link.getAttribute('href'), 'https://docs.google.com/document/d/1AbCdEfGhIjKlMnOp/edit');
      assert.equal(await link.getAttribute('target'), '_blank');
      assert.match(await link.getAttribute('rel'), /noopener/);
      const stored = card.locator('.bf-row').nth(1);
      assert.equal(await stored.locator('[data-bf-open=tico]').getAttribute('href'), '/api/v2/files/file-000000000000000000000002');
      assert.equal(await stored.locator('.bf-meta a').innerText(), 'View on GitHub');
      const unsynced = card.locator('.bf-row').nth(2);
      assert.equal(await unsynced.locator('[data-bf-unsynced]').count(), 1);
      assert.equal(await unsynced.locator('.bf-open').count(), 0, tag + ': no Open link for a file that did not sync');
      // A stored file opens through Tico (the viewer asks the route for the bytes).
      await stored.locator('.bf-open').click();
      await page.waitForSelector('dialog#doc-viewer[open]');
      await until(() => state.opened.includes('file-000000000000000000000002'));
      await page.keyboard.press('Escape');
      await page.waitForSelector('dialog#doc-viewer:not([open])', {state: 'attached'});
      // Show all opens the rest inline; Show less folds it back.
      await card.locator('[data-bf-all]').click();
      await page.waitForFunction(() => document.querySelectorAll('#bot-files .bf-row').length === 5);
      await card.locator('[data-bf-less]').click();
      await page.waitForFunction(() => document.querySelectorAll('#bot-files .bf-row').length === 3);
      assert.doesNotMatch(await card.innerHTML(), /s3:\/\/|X-Amz|amazonaws/i, tag + ': no storage address');
      // The owner removes one from the list: a PATCH, and the row is gone.
      await card.locator('[data-bf-remove]').first().click();
      await page.waitForFunction(() => document.querySelector('#bot-files [data-bf-total]').textContent.trim() === '4');
      assert.deepEqual(state.patched, [['file-000000000000000000000001', {archived: true}]]);
      if (viewport.width < 760) {
        assert(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth), 'phone: no sideways scroll');
        assert((await card.boundingBox()).width <= 390, 'phone: the card fits');
      }
      assert.deepEqual(errors, [], tag + ': page errors');
      await page.close();
      console.log(`bot files card (${tag}): three rows, Show all, Open for a link and a stored file, not synced, remove`);
    }
  } finally { await browser.close(); }
})().catch(error => { console.error(error); process.exit(1); });
async function until(test, ms = 5000) { for (const end = Date.now() + ms; !test(); ) { if (Date.now() > end) throw new Error('timed out'); await new Promise(r => setTimeout(r, 50)); } }
