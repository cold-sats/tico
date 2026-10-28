// Library › Connections (ui/app/redesign-library.js) against fixtures/redesign-connections.json
// (the Acme example, shaped as GET /api/v2/tools and /api/v2/tools/{service} answer): one row per tool with its kind and
// write level, grouped In use / Available / Removed; a row opens the tool's own page, read only (no credentials, no
// learning added or deleted), as its own screen on a phone and beside the list on a computer; back returns to the list.
// Shown, not live: nothing on the page writes. An empty team reads one line.
// Phone first (390×844), then a computer. TICO_UI_SHOTS=<dir> saves screenshots.
const {chromium} = require('playwright');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const {html, uiFile} = require('./support/page.cjs');
const {unrouted} = require('./support/routes.cjs');
const uiDir = path.join(__dirname, '..');
const fixture = name => JSON.parse(fs.readFileSync(path.join(__dirname, 'fixtures', name), 'utf8'));
const FX = fixture('redesign-connections.json');
const roster = fixture('redesign-roster.json');
const PHONE = {width: 390, height: 844}, DESKTOP = {width: 1440, height: 900};
const LIST = '#/library/connections';

async function open(browser, {viewport = PHONE, hash = LIST, tools = FX.tools.integrations, listGate = null} = {}) {
  const page = await browser.newPage({viewport, serviceWorkers: 'block', hasTouch: viewport === PHONE});
  const errors = [], writes = [];
  page.on('pageerror', e => errors.push(e.message));
  const config = {company_name: 'Acme'};
  await page.route('**/*', async route => {
    const req = route.request(), url = new URL(req.url()), p = url.pathname, method = req.method();
    const json = (body, status = 200) => route.fulfill({status, contentType: 'application/json', body: JSON.stringify(body)});
    if (url.origin !== 'http://tico-ui.test') return route.abort();
    if (p === '/') return route.fulfill({contentType: 'text/html', body: html});
    const file = p.startsWith('/tico/ui/') ? uiFile(p.slice(9)) : p.startsWith('/vendor/') ? path.join(uiDir, p) : '';
    if (file && fs.existsSync(file)) return route.fulfill({contentType: file.endsWith('.js') ? 'application/javascript' : file.endsWith('.css') ? 'text/css' : file.endsWith('.woff2') ? 'font/woff2' : 'application/octet-stream', body: fs.readFileSync(file)});
    if (p === '/api/v2/events') return;
    if (method !== 'GET') writes.push({method, path: p});
    if (p === '/api/v2/config') return json(config);
    if (p === '/api/me') return json({id: 'ana', name: 'Ana Silva', email: 'ana@acme.example', role: 'owner', company_role: 'owner', cloud: true, config});
    if (p === '/api/employees') return json(roster.employees);
    if (p === '/api/humans') return json(roster.humans);
    if (p === '/api/status') return json({active: [], employees: []});
    if (p === '/api/v2/status') return json({bots: []});
    // The tools (backend/integrations.py; /integrations is the old spelling of /tools).
    const m = p.match(/^\/api\/v2\/(?:tools|integrations)(?:\/([^/]+))?$/);
    if (m && !m[1]) { await listGate; return json({label: 'Available tools', integrations: tools}); }
    if (m) {
      const one = FX.pages[decodeURIComponent(m[1])];
      return one ? json(one) : json({error: {code: 'not_found', detail: 'No tool named ' + m[1]}}, 404);
    }
    if (p === '/api/v2/credentials') return json({credentials: [], can_manage: true});
    return json(unrouted(p));
  });
  await page.goto('http://tico-ui.test/' + hash);
  await page.waitForFunction(() => typeof S !== 'undefined' && S.me && (S.emps || []).length);
  return {page, errors, writes};
}
const sideways = page => page.evaluate(() => [document.documentElement, document.querySelector('#main')].some(el => el && el.scrollWidth > el.clientWidth + 1));
const hashSoon = (page, want) => page.waitForFunction(w => location.hash === w, want).then(() => true, () => false);
async function shot(page, name) {
  const dir = process.env.TICO_UI_SHOTS;
  if (!dir) return;
  fs.mkdirSync(dir, {recursive: true});
  await page.screenshot({animations: 'disabled', path: path.join(dir, name + '.png')});
}
const rows = page => page.locator('.lc-row').evaluateAll(els => els.map(el => [el.dataset.service,
  el.querySelector('.nav-icon').textContent, el.querySelector('.lc-nm').innerText.trim(), el.querySelector('.pill').innerText.trim()]));
const ROWS = [
  ['close-crm', 'api', 'Close CRM · API', 'Approval'],
  ['postgres', 'inventory_2', 'Acme Postgres · SQL', 'Read only'],
  ['acme-ops', 'link', 'Acme Ops MCP · MCP', 'Writes'],
  ['aside', 'travel_explore', 'Aside browser · Browser', 'Read only'],
  ['mail', 'mail', 'Mail · Email', 'Approval'],
  ['github', 'code', 'GitHub · CLI', 'Writes'],
  ['old-wiki', 'api', 'old-wiki · API', 'Read only'],
];

// The tool's page as Connections shows it: read only, the learnings counted.
async function readOnlyPage(page, tag, title, learnings) {
  await page.locator('#int-detail h1').filter({hasText: title}).waitFor();
  assert.equal(await page.locator('#int-detail .int-key, #int-learn-text, #int-learn-add, [data-delete-learning]').count(), 0, tag + ': read only');
  assert.equal(await page.locator('[data-learning-count]').innerText(), String(learnings), tag + ': the learnings counted');
  assert.equal(await page.locator('.int-learning').count(), learnings, tag + ': the learnings listed');
}

(async () => {
  const browser = await chromium.launch({channel: process.env.TICO_BROWSER_CHANNEL ?? 'chrome', headless: true});
  try {
    // A phone: the list, a connection's page, a sibling link, back.
    {
      const tag = 'phone on';
      const {page, errors, writes} = await open(browser);
      await page.locator('.lc-row').first().waitFor();
      assert.deepEqual(await rows(page), ROWS, tag + ': one row each, kind and write level');
      assert.deepEqual(await page.locator('.lc-gh').allInnerTexts(), ['IN USE\n3', 'AVAILABLE\n3', 'REMOVED\n1'], tag + ': grouped');
      assert.equal(await page.locator('#lc-root button, #lc-root input, #lc-root textarea').count(), 0, tag + ': nothing to add or edit');
      assert.equal(await page.locator('#side a[data-nav="connections"].cur').count(), 1, tag + ': Connections is current');
      assert.equal(await page.locator('.lc-pane').isVisible(), false, tag + ': the list alone');
      assert.equal(await sideways(page), false, tag + ': no sideways scroll');
      await shot(page, 'phone-connections');

      await page.locator('.lc-row[data-service="close-crm"]').click();
      assert.ok(await hashSoon(page, LIST + '/close-crm'), tag + ': its own address');
      await readOnlyPage(page, tag, 'Close CRM', 2);
      assert.equal(await page.locator('.lc-list').isVisible(), false, tag + ': the page alone');
      assert.equal(await page.getAttribute('#int-body a[href^="#/"]', 'href'), LIST + '/postgres', tag + ': a sibling page stays in Library');
      assert.equal(await sideways(page), false, tag + ': the page fits');
      await shot(page, 'phone-connection-page');

      await page.locator('#int-body a[href="' + LIST + '/postgres"]').click();
      await readOnlyPage(page, tag + ' sibling', 'Acme Postgres', 0);
      assert.equal(await page.locator('#int-queries .int-query').count(), 1, tag + ': its queries');

      await page.locator('.lc-back').click();
      assert.ok(await hashSoon(page, LIST), tag + ': back to the list');
      await page.locator('.lc-list').waitFor();
      assert.equal(await page.locator('.lc-pane').isVisible(), false, tag + ': the list again');
      assert.equal(await page.locator('.lc-row').count(), ROWS.length);
      assert.deepEqual(writes, [], tag + ': nothing written');
      assert.deepEqual(errors, [], tag + ': no page errors');
      await page.close();
    }

    // A phone, a team with no tools: one line.
    {
      const tag = 'phone empty';
      const {page, errors} = await open(browser, {tools: []});
      await page.locator('.lc-scroll .lc-pad').filter({hasText: 'No connections yet.'}).waitFor();
      assert.equal(await page.locator('.lc-row, .lc-gh').count(), 0, tag + ': no rows');
      await shot(page, 'phone-connections-empty');
      assert.deepEqual(errors, [], tag + ': no page errors');
      await page.close();
    }

    // A computer: the first connection opens beside the list; another row swaps the page; the list stays.
    {
      const tag = 'desktop on';
      const {page, errors, writes} = await open(browser, {viewport: DESKTOP});
      assert.ok(await hashSoon(page, LIST + '/close-crm'), tag + ': opens on the first row');
      await readOnlyPage(page, tag, 'Close CRM', 2);
      assert.equal(await page.locator('.lc-back').isVisible(), false, tag + ': no back link beside the list');
      assert.equal(await page.locator('.lc-row.sel').getAttribute('data-service'), 'close-crm', tag + ': the row is selected');
      const list = await page.locator('.lc-list').boundingBox(), pane = await page.locator('.lc-pane').boundingBox();
      assert.ok(list.x + list.width <= pane.x + 1, tag + ': list | page');
      await shot(page, 'desktop-connections');
      await page.locator('.lc-row[data-service="postgres"]').click();
      await readOnlyPage(page, tag, 'Acme Postgres', 0);
      assert.equal(await page.locator('.lc-row.sel').getAttribute('data-service'), 'postgres', tag + ': the selection follows');
      await page.locator('.lc-row[data-service="github"]').click();
      await page.locator('#int-detail .empty').filter({hasText: 'No tool named'}).waitFor();
      assert.ok(await page.locator('.lc-list').isVisible(), tag + ': a page that will not load leaves the list');
      await shot(page, 'desktop-connection-missing');
      assert.deepEqual(writes, [], tag + ': nothing written');
      assert.deepEqual(errors, [], tag + ': no page errors');
      await page.close();
    }

    // The list is slow and the address moves to another connection meanwhile: the later address wins, no errors.
    {
      const tag = 'desktop slow list';
      let release;
      const listGate = new Promise(r => { release = r; });
      const {page, errors} = await open(browser, {viewport: DESKTOP, hash: LIST + '/close-crm', listGate});
      await page.evaluate(h => { location.hash = h; }, LIST + '/postgres');
      await page.waitForFunction(() => location.hash.endsWith('/postgres'));
      release();
      await readOnlyPage(page, tag, 'Acme Postgres', 0);
      assert.equal(await page.locator('.lc-row.sel').getAttribute('data-service'), 'postgres', tag + ': the later address is selected');
      assert.ok(await hashSoon(page, LIST + '/postgres'), tag + ': and stays');
      assert.deepEqual(errors, [], tag + ': no page errors');
      await page.close();
    }

    console.log('library connections ok');
  } finally {
    await browser.close();
  }
})().catch(e => { console.error(e); process.exit(1); });
