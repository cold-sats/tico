// Offline browser regression for the quiet runtime label beside each bot's name: the rail shows the
// harness in plain words (Codex, Hermes), a tooltip carries the model and where it came from, and a
// bot with no runtime shows nothing. Fixtures only, no network.
const {chromium} = require('playwright');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const html = fs.readFileSync(path.join(__dirname, '../index.html'), 'utf8');

(async () => {
  const browser = await chromium.launch({channel: process.env.TICO_BROWSER_CHANNEL ?? 'chrome', headless: true});
  try {
    const page = await browser.newPage({viewport: {width: 1100, height: 820}, serviceWorkers: 'block'});
    const errors = [];
    page.on('pageerror', error => errors.push(error.message));
    const bot = (name, display_name, extra = {}) => ({name, display_name, org_parent: '', host: 'keeper',
      status: 'active', can_chat: true, users: [{id: 'ana', name: 'Ana'}], ...extra});
    const bots = [
      bot('planner', 'Planner', {resolved_runtime: 'codex', resolved_model: 'gpt-6-sol', model_source: 'company'}),
      bot('scout', 'Scout', {harness: 'hermes', runtime: 'hermes', resolved_runtime: '', resolved_model: '', model_source: ''}),
      bot('writer', 'Writer', {resolved_runtime: 'claude', resolved_model: 'claude-opus-5', model_source: 'bot'}),
      bot('blank', 'Blank Bot', {resolved_runtime: '', resolved_model: '', model_source: ''}),
    ];
    await page.route('**/*', route => {
      const url = new URL(route.request().url()), p = url.pathname;
      const json = body => route.fulfill({contentType: 'application/json', body: JSON.stringify(body)});
      if (url.origin !== 'https://tico-ui.test') return route.abort();
      const ui = p.match(/\/tico\/ui\/([^/]+\.js)$/);
      if (ui) {
        const file = path.join(__dirname, '..', ui[1]);
        if (fs.existsSync(file)) return route.fulfill({contentType: 'application/javascript', body: fs.readFileSync(file, 'utf8')});
      }
      if (p === '/') return route.fulfill({contentType: 'text/html', body: html});
      if (p === '/api/me') return json({id: 'ana', role: 'owner', name: 'Ana', email: 'ana@example.test', cloud: true});
      if (p === '/api/people') return json({people: [{id: 'ana', name: 'Ana'}]});
      if (p === '/api/employees') return json(bots);
      if (p === '/api/status') return json({cloud: true, active: [], queued: [], recent_runs: [], keeper_alive: true, health_issues: []});
      if (p === '/api/v2/tasks') return json({tasks: []});
      if (p === '/api/v2/conversations') return json({conversations: []});
      if (p.endsWith('/watch')) return route.fulfill({contentType: 'text/event-stream', body: ': fixture\n\n'});
      return json(p === '/api/issues' ? [] : {});
    });

    await page.goto('https://tico-ui.test/');
    await page.locator('#tree .node').first().waitFor();
    const tag = org => page.locator(`#tree .node[data-org="b:${org}"] .rt`);
    assert.equal(await tag('planner').textContent(), 'Codex');
    assert.match(await tag('planner').getAttribute('title'), /^Codex · gpt-6-sol \(company default\)$/);
    assert.equal(await tag('scout').textContent(), 'Hermes');
    assert.equal(await tag('scout').getAttribute('title'), 'Hermes');
    assert.match(await tag('writer').getAttribute('title'), /own choice/);
    assert.equal(await tag('blank').count(), 0, 'nothing for a bot with no runtime');
    assert.equal(await tag('planner').getAttribute('aria-hidden'), 'true', 'not read twice');
    const name = page.locator('#tree .node[data-org="b:planner"] .nm');
    const [n, t] = await Promise.all([name, tag('planner')].map(l => l.boundingBox()));
    assert.ok(t.x >= n.x + n.width - 1, 'the label sits to the right of the name');
    assert.equal(await tag('planner').evaluate(e => getComputedStyle(e).backgroundColor), 'rgba(0, 0, 0, 0)');

    await page.evaluate(() => { location.hash = '#/bot/scout'; });
    await page.locator('.botid h1 .rt').waitFor();
    assert.equal(await page.locator('.botid h1 .rt').textContent(), 'Hermes');

    // A bot that follows the company default says which model that is, instead of "not set".
    await page.evaluate(() => { location.hash = '#/bot/planner'; });
    const setup = page.locator('#pane-more .bot-setup dt:text-is("Model") + dd');
    await setup.waitFor({state: 'attached'});
    assert.match(await setup.textContent(), /^company default \(.*gpt-6-sol.*\)$/);
    await page.evaluate(() => { location.hash = '#/bot/writer'; });
    await page.locator('#pane-more .bot-setup dt:text-is("Model") + dd').waitFor({state: 'attached'});
    assert.match(await page.locator('#pane-more .bot-setup dt:text-is("Model") + dd').textContent(), /not set|opus/);

    if (process.env.RUNTIME_LABELS_SHOT) {
      await page.evaluate(() => { location.hash = '#/bot/planner'; });
      await page.locator('#tree').screenshot({path: process.env.RUNTIME_LABELS_SHOT});
    }
    assert.deepEqual(errors, []);
    console.log('runtime labels ok');
  } finally { await browser.close(); }
})().catch(error => { console.error(error); process.exit(1); });
