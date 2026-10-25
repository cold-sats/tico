// The Strategy section (ui/strategy-page.js) against a stand-in for GET /api/v2/strategy and its writes (fixtures only):
// the owner reads the draft with its choices, each choice's goals and their colours, and the framework's sections,
// edits the summary in place and publishes with a note; a member reads only the published version and cannot write;
// old #/market links land on the Market tab keeping their query; the Goals page shows one Strategy line and the goal
// editor's choice picker saves choice_id.
// TICO_SCREENSHOT_DIR=<dir> saves review screenshots (desktop in both themes, and a phone).
const {chromium} = require('playwright');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const {html, uiFile} = require('./support/page.cjs');
const {unrouted} = require('./support/routes.cjs');
const uiDir = path.join(__dirname, '..');

const shots = process.env.TICO_SCREENSHOT_DIR;
const shot = async (page, name, themes = ['dark', 'light']) => {
  if (!shots) return;
  for (const theme of themes) {
    await page.evaluate(t => { document.documentElement.dataset.theme = t; }, theme);
    await page.screenshot({animations: 'disabled', path: path.join(shots, `strategy-${name}-${theme}.png`)});
  }
  await page.evaluate(() => { document.documentElement.dataset.theme = 'dark'; });
};

const bot = (name, display_name, org_parent, over) => ({name, display_name, org_parent, host: 'keeper', status: 'active', can_chat: true, ...over});
const bots = [bot('coo', 'Assistant', ''), bot('botops', 'BotOps', ''), bot('librarian', 'Librarian', ''),
  bot('goal-manager', 'CEO Bot', 'p:ana', {reports_to: ''}), bot('cmo', 'Head of Marketing', 'b:goal-manager', {reports_to: ''})];
const plain = {id: 'plain', name: 'Plain', choices_label: 'Bets', choice_label: 'Bet', sections: [
  {key: 'serve', title: 'Who we serve', prompt: 'Who buys, and why'}, {key: 'sell', title: 'What we sell', prompt: ''},
  {key: 'win', title: 'How we win', prompt: ''}, {key: 'not', title: "What we won't do", prompt: ''}]};
const kernel = {id: 'kernel', name: "Rumelt's kernel", choices_label: 'Guiding policy', choice_label: 'Guiding policy', sections: [
  {key: 'diagnosis', title: 'Diagnosis', prompt: ''}, {key: 'policy', title: 'Policy', prompt: ''}, {key: 'actions', title: 'Actions', prompt: ''}]};
const choices = [
  {id: 'c-auto', statement: 'Charge as if fully automated, with humans behind it', why: 'Customers pay for the outcome.', rules_out: 'Hourly pricing',
   status: 'active', since_n: 1, until_n: null, rank: 0},
  {id: 'c-cheap', statement: 'Prices low enough to win 100x the customers', why: 'Volume is the moat.', rules_out: '', status: 'active', since_n: 2, until_n: null, rank: 1},
  {id: 'c-api', statement: 'Sell an API to other cleaners', why: '', rules_out: '', status: 'proposed', since_n: null, until_n: null, rank: 2},
  {id: 'c-old', statement: 'Only serve offices', why: '', rules_out: '', status: 'retired', since_n: 1, until_n: 2, rank: 3},
];
const v2 = {n: 2, status: 'published', framework: 'plain', summary: 'Acme cleans homes and offices at half the usual price, with bots doing the booking.',
  vision: 'Every home in town cleaned by Acme.', sections: {serve: 'Busy households and **small offices**.', sell: 'Weekly cleaning.', not: 'No deep-clean contracts.'},
  choices: choices.filter(c => c.id !== 'c-api'), note: 'Lower prices', updated: null, updated_by: null,
  published: new Date(Date.now() - 2 * 864e5).toISOString(), published_by: 'human:ana'};

async function open(browser, {role = 'owner', route = '#/strategy', viewport = {width: 1440, height: 900}, empty = false} = {}) {
  const page = await browser.newPage({viewport, serviceWorkers: 'block'});
  const errors = [], sent = [];
  page.on('pageerror', e => errors.push(e.message));
  const st = empty ? {draft: {n: null, status: 'draft', framework: 'plain', summary: '', vision: '', sections: {}, choices: []}, current: null, choices: []}
    : {draft: {...v2, n: null, status: 'draft', summary: v2.summary + ' Next: offices.', sections: {...v2.sections, win: 'Bots answer in a minute.'},
      updated: new Date(Date.now() - 3600e3).toISOString(), updated_by: 'bot:goal-manager', published: null, published_by: null}, current: v2, choices: choices.map(c => ({...c}))};
  const goals = [
    {id: 'g-top', title: 'Grow rentals 30%', owner: 'company', parent_id: null, status: 'green', status_source: 'auto', rank: 0, kpis: [], why: '', choice_id: 'c-auto'},
    {id: 'g-cmo', title: 'Double organic signups', owner: 'bot:cmo', parent_id: 'g-top', status: 'red', status_source: 'auto', rank: 0, kpis: [], why: '', choice_id: null},
  ];
  const strategy = () => ({...st, label: 'Bets', label_one: 'Bet', may_edit: role === 'owner', frameworks: [plain, kernel],
    goals_by_choice: {'c-auto': [{id: 'g-top', title: 'Grow rentals 30%', colour: 'green'}, {id: 'g-cmo', title: 'Double organic signups', colour: 'red'}]}});
  await page.route('**/*', async route => {
    const req = route.request(), url = new URL(req.url()), p = url.pathname, method = req.method();
    const json = (body, status = 200) => route.fulfill({status, contentType: 'application/json', body: JSON.stringify(body)});
    if (url.origin !== 'http://tico-ui.test') return route.abort();
    if (p === '/') return route.fulfill({contentType: 'text/html', body: html});
    const file = p.startsWith('/tico/ui/') ? uiFile(p.slice(9)) : p.startsWith('/vendor/') ? path.join(uiDir, p) : '';
    if (file && fs.existsSync(file)) return route.fulfill({contentType: file.endsWith('.js') ? 'application/javascript' : file.endsWith('.css') ? 'text/css' : file.endsWith('.woff2') ? 'font/woff2' : 'application/octet-stream', body: fs.readFileSync(file)});
    if (p === '/api/v2/events') return;
    if (p === '/api/v2/config') return json({});
    if (p === '/api/employees') return json(bots);
    if (p === '/api/me') return json({id: role === 'owner' ? 'ana' : 'cara', name: role === 'owner' ? 'Ana Silva' : 'Cara Diaz', email: 'x@example.test',
      role: role === 'owner' ? 'owner' : 'viewer', company_role: role, cloud: true, config: {}});
    if (p === '/api/humans') return json({people: [{id: 'ana', name: 'Ana Silva', org_parent: ''}, {id: 'cara', name: 'Cara Diaz', org_parent: 'p:ana'}]});
    if (p === '/api/status') return json({active: [], employees: []});
    if (p === '/api/v2/status') return json({bots: []});
    if (p === '/api/v2/strategy' && method === 'GET') return json(strategy());
    if (p.startsWith('/api/v2/strategy') && method !== 'GET') {
      const body = req.postDataJSON();
      sent.push([method, p.slice('/api/v2/strategy'.length), body]);
      if (role !== 'owner') return json({error: {code: 'forbidden', detail: 'Only the owner'}}, 403);
      if (p === '/api/v2/strategy/draft') {
        // Merges sections, as the server does; an empty one clears it.
        const sections = {...st.draft.sections, ...(body.sections || {})};
        for (const k of Object.keys(sections)) if (!sections[k]) delete sections[k];
        st.draft = {...st.draft, ...body, sections}; return json(st.draft);
      }
      if (p === '/api/v2/strategy/publish') {
        const n = (st.current?.n || 0) + 1;
        st.current = {...st.draft, n, status: 'published', note: body.note, choices: st.choices.map(c => ({...c})), published: new Date().toISOString(), published_by: 'human:ana'};
        return json(st.current);
      }
      const one = p.match(/^\/api\/v2\/strategy\/choices\/([^/]+)$/);
      if (one) { const c = st.choices.find(x => x.id === one[1]); Object.assign(c, body); return json(c); }
      if (p === '/api/v2/strategy/choices') { const c = {id: 'c-new', since_n: null, until_n: null, rank: st.choices.length, status: 'proposed', why: '', rules_out: '', ...body}; st.choices.push(c); return json(c); }
    }
    if (p === '/api/v2/strategy/versions') return json([{n: 2, note: 'Lower prices', published: v2.published, published_by: 'human:ana'},
      {n: 1, note: 'First', published: new Date(Date.now() - 9 * 864e5).toISOString(), published_by: 'human:ana'}]);
    const version = p.match(/^\/api\/v2\/strategy\/versions\/(\d+)$/);
    if (version) return json(version[1] === '2' ? v2 : {...v2, n: 1, note: 'First', summary: 'Acme cleans offices.', choices: v2.choices.filter(c => c.id !== 'c-cheap').map(c => c.id === 'c-old' ? {...c, status: 'active'} : c)});
    if (p === '/api/v2/goals/tree') return json({goals, owners: {}, other_kpis: [], proposals: []});
    if (p === '/api/v2/goals/needs-you') return json({actor: 'human:ana', items: []});
    if (p === '/api/v2/bots/goal-manager/routines') return json({routines: []});
    const goal = p.match(/^\/api\/v2\/goals\/([^/]+)$/);
    if (goal && method === 'POST') { const body = req.postDataJSON(); sent.push(['POST', '/goals/' + goal[1], body]); Object.assign(goals.find(g => g.id === goal[1]), body); return json({goal: goals.find(g => g.id === goal[1])}); }
    if (p === '/api/v2/market/graph') return json({entities: [], edges: []});
    if (p === '/api/v2/market/entities') return json({entities: [], total: 0});
    if (p === '/api/company-docs') return json({documents: []});
    if (p === '/api/v2/librarian/setup') return json({market: null});
    return json(unrouted(p));
  });
  await page.goto('http://tico-ui.test/' + route);
  return {page, errors, sent, st};
}

(async () => {
  const browser = await chromium.launch({channel: process.env.TICO_BROWSER_CHANNEL ?? 'chrome', headless: true});
  try {
    // The owner reads the draft: summary, the Bets with their goals and colours, the sections in the framework's order.
    {
      const {page, errors, sent} = await open(browser);
      const summary = page.locator('[data-strat-field="summary"]');
      await summary.waitFor();
      assert.equal(await page.locator('#main h1').innerText(), 'Strategy');
      assert.equal(await page.locator('.strat-tabs a.cur').innerText(), 'Strategy');
      assert.equal(await page.locator('#side [data-nav="strategy"]').getAttribute('aria-current'), 'page');
      assert.match(await summary.inputValue(), /Next: offices\.$/, 'the owner reads the draft');
      assert.match(await page.locator('[data-strat-status]').innerText(), /^Draft differs from v2 · CEO Bot/);
      assert.equal(await page.locator('#strat-choices-h').innerText(), 'BETS');
      const first = page.locator('li[data-choice="c-auto"]');
      assert.match(await first.innerText(), /Charge as if fully automated[\s\S]*Why[\s\S]*Customers pay for the outcome\.[\s\S]*Rules out[\s\S]*Hourly pricing/);
      assert.deepEqual(await first.locator('.strat-goals .gdot').evaluateAll(dots => dots.map(d => [...d.classList].find(c => c !== 'gdot'))), ['green', 'red']);
      assert.equal(await first.locator('.strat-goals a').first().getAttribute('href'), '#/goals/g-top');
      assert.equal(await page.locator('li[data-choice="c-api"] .strat-pill').innerText(), 'Proposed');
      assert.equal(await page.locator('.strat-retired li[data-choice="c-old"]').count(), 1, 'retired choices sit apart');
      assert.deepEqual(await page.locator('[data-section] .strat-sec-head .strat-k').allInnerTexts(), ['WHO WE SERVE', 'WHAT WE SELL', 'HOW WE WIN', "WHAT WE WON'T DO"]);
      assert.equal(await page.locator('[data-section="serve"] .strat-md strong').innerText(), 'small offices', 'sections are markdown');
      assert.equal(await page.locator('[data-choice-add]').getAttribute('aria-label'), 'Add Bet');
      await shot(page, 'desktop');
      // The summary saves on Enter, as a partial draft.
      await summary.fill('Acme cleans homes at half the price.');
      await summary.press('Enter');
      await page.waitForFunction(() => document.activeElement?.dataset?.stratField !== 'summary');
      await page.waitForFunction(() => document.querySelector('[data-strat-publish]'));
      assert.deepEqual(sent.find(x => x[1] === '/draft'), ['PUT', '/draft', {summary: 'Acme cleans homes at half the price.'}]);
      // A section saves alone: the server merges sections.
      await page.locator('[data-section="sell"] [data-section-edit]').click();
      await page.locator('[data-section-form] textarea').fill('Weekly and monthly cleaning.');
      await page.locator('[data-section-form] button[type="submit"]').click();
      await page.locator('[data-section="sell"] .strat-md', {hasText: 'monthly'}).waitFor();
      assert.deepEqual(sent.filter(x => x[1] === '/draft').at(-1)[2], {sections: {sell: 'Weekly and monthly cleaning.'}});
      // Publish asks for one line, then posts it.
      await page.locator('[data-strat-publish]').click();
      const form = page.locator('[data-strat-publish-form]');
      await form.locator('input[name="note"]').fill('Homes first');
      await form.locator('button[type="submit"]').click();
      await form.waitFor({state: 'detached'});
      assert.deepEqual(sent.find(x => x[1] === '/publish'), ['POST', '/publish', {note: 'Homes first'}]);
      assert.equal(await page.locator('[data-strat-status]').count(), 0, 'published: the draft no longer differs');
      // Versions: compare v1 with v2.
      await page.locator('[data-strat-versions]').click();
      const drawer = page.locator('#strat-versions[open]');
      await drawer.locator('[data-sv-compare]').waitFor();
      await drawer.locator('[data-sv-compare] button').click();
      await drawer.locator('.strat-diff').first().waitFor();
      const diff = await drawer.innerText();
      assert.match(diff, /Acme cleans offices\.[\s\S]*Acme cleans homes and offices/);
      assert.match(diff, /BETS ADDED\s*Prices low enough/i);
      assert.match(diff, /BETS RETIRED\s*Only serve offices/i);
      assert.deepEqual(errors, []);
      await page.close();
    }
    // A member reads the published version only, with no fields and no Publish.
    {
      const {page, errors} = await open(browser, {role: 'member'});
      await page.locator('.strat-summary .strat-text').waitFor();
      assert.equal(await page.locator('.strat-summary .strat-text').innerText(), v2.summary);
      assert.equal(await page.locator('textarea, [data-strat-publish], [data-choice-edit], [data-section-edit]').count(), 0);
      assert.equal(await page.locator('li[data-choice="c-api"]').count(), 0, 'a proposed choice is not in the published version');
      assert.equal(await page.locator('[data-section="win"]').count(), 0, 'an unwritten section is left out');
      assert.deepEqual(errors, []);
      await page.close();
    }
    // A phone: tabs on top, one column, no sideways scroll.
    {
      const {page, errors} = await open(browser, {viewport: {width: 390, height: 844}});
      await page.locator('li[data-choice="c-auto"]').waitFor();
      assert.equal(await page.locator('.strat-toc').isVisible(), false);
      assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth && $('#main').scrollWidth <= $('#main').clientWidth), 'no horizontal scroll');
      await shot(page, 'phone', ['dark']);
      assert.deepEqual(errors, []);
      await page.close();
    }
    // Old Market links land on the Strategy section's Market tab, keeping the query.
    {
      const {page, errors} = await open(browser, {route: '#/market?note=x'});
      await page.waitForFunction(() => location.hash === '#/strategy/market?note=x');
      await page.locator('.strat-tabs a.cur', {hasText: 'Market'}).waitFor();
      assert.equal(await page.locator('#side [data-nav="strategy"]').getAttribute('aria-current'), 'page');
      assert.deepEqual(errors, []);
      await page.close();
    }
    // Goals: one Strategy line at the top, and the goal editor's choice picker, which saves choice_id.
    {
      const {page, errors, sent} = await open(browser, {route: '#/goals'});
      await page.locator('#goal-tree .gt-row').first().waitFor();
      assert.match(await page.locator('#goal-strategy').innerText(), /^Strategy v2\s*·?\s*Acme cleans homes/);
      assert.equal(await page.locator('#goal-strategy').getAttribute('href'), '#/strategy');
      await page.locator('#goal-tree .gt-row[data-owner="bot:cmo"]').first().click();
      const panel = page.locator('#goal-panel[open]');
      await panel.locator('[data-gp-edit="g-cmo"]').click();
      const picker = panel.locator('select[name="choice"]');
      assert.equal(await panel.locator('.goal-choice-f > span').innerText(), 'Bet', 'one goal serves one choice: the singular');
      assert.deepEqual(await picker.locator('option').allInnerTexts(), ['None', 'Charge as if fully automated, with humans behind it', 'Prices low enough to win 100x the customers']);
      await picker.selectOption('c-cheap');
      await shot(page, 'goals-picker');
      await page.setViewportSize({width: 390, height: 844});
      await shot(page, 'goals-picker-phone', ['dark']);
      await page.setViewportSize({width: 1440, height: 900});
      await panel.locator('button[type="submit"]').click();
      await page.waitForFunction(() => !document.querySelector('#goal-panel [data-goal-form]'));
      assert.deepEqual(sent.find(x => x[1] === '/goals/g-cmo'), ['POST', '/goals/g-cmo', {choice_id: 'c-cheap'}]);
      assert.match(await panel.locator('[data-goal-choice="c-cheap"]').innerText(), /Bet\s+Prices low enough/);
      assert.deepEqual(errors, []);
      await page.close();
    }
    console.log('strategy: ok');
  } finally {
    await browser.close();
  }
})().catch(e => { console.error(e); process.exit(1); });
