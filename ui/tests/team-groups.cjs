// Offline regression for the team chart's groups (docs/org-chart.md). Fixtures only.
//  - the chart shows groups as nested, collapsible sections holding their humans and bots; a group's members hang
//    under whoever they report to when that one is in the same group; the Built-in bots stay outside every group;
//  - owners and admins add a group, rename it, drag a human or a bot into a group (or out, onto "No group") and
//    nest a group in another; a member has none of those handles.
const {chromium} = require('playwright');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const {html, uiFile} = require('./support/page.cjs');

const FULL = {see: true, read: true, write: true};

async function open(browser, me) {
  const page = await browser.newPage({viewport: {width: 1300, height: 900}, serviceWorkers: 'block'});
  const errors = [], calls = [];
  const people = [
    {id: 'ana', name: 'Ana Rivera', org_parent: '', team: ''},
    {id: 'ben', name: 'Ben Cole', org_parent: 'p:ana', team: 'marketing', reports_to: 'ana'},
    {id: 'cara', name: 'Cara Mendes', org_parent: 'p:ana', team: '', reports_to: 'ana'},
  ];
  const groups = [{id: 'marketing', name: 'Marketing', parent: ''}, {id: 'seo', name: 'SEO', parent: 'marketing'},
                  {id: 'sales', name: 'Sales', parent: ''}];
  const bot = (name, display_name, team, org_parent, extra = {}) => ({name, display_name, team, org_parent, host: 'keeper',
    status: 'active', state: 'active', can_chat: true, my_access: FULL, users: [{id: 'ana', name: 'Ana'}], operator: 'ana', revision: 1, ...extra});
  const bots = [
    bot('cmo', 'CMO', 'marketing', 'p:ben', {reports_to: 'human:ben'}),
    bot('writer', 'Writer', 'seo', 'b:cmo', {reports_to: 'cmo'}),
    bot('scout', 'Scout', '', 'p:ana', {reports_to: 'human:ana'}),
    bot('botops', 'BotOps', '', 'p:ana', {reports_to: 'human:ana'}),
  ];
  const groupRows = () => groups.map((g, i) => ({...g, org_parent: g.parent ? 'g:' + g.parent : '', order: i}));
  const apply = (id, body) => {
    const group = groups.find(g => g.id === id);
    if (body.name) group.name = body.name;
    if (body.parent !== undefined) group.parent = body.parent;
    for (const [kind, rows, key] of [['people', people, 'id'], ['bots', bots, 'name']]) {
      for (const one of (body.add || {})[kind] || []) rows.find(r => r[key] === one).team = id;
      for (const one of (body.remove || {})[kind] || []) rows.find(r => r[key] === one).team = '';
    }
  };
  await page.route('**/*', route => {
    const request = route.request(), url = new URL(request.url()), p = url.pathname, method = request.method();
    const json = body => route.fulfill({contentType: 'application/json', body: JSON.stringify(body)});
    if (url.origin !== 'https://tico-ui.test') return route.abort();
    const ui = p.match(/\/tico\/ui\/((?:app\/|styles\/)?[^/]+\.(?:js|css))$/);
    if (ui && fs.existsSync(uiFile(ui[1])))
      return route.fulfill({contentType: ui[1].endsWith('.css') ? 'text/css' : 'application/javascript', body: fs.readFileSync(uiFile(ui[1]), 'utf8')});
    if (p === '/') return route.fulfill({contentType: 'text/html', body: html});
    if (p === '/api/me') return json(me);
    if (p === '/api/humans') return json({people, org_groups: groupRows()});
    if (p === '/api/employees') return json(bots);
    if (p === '/api/issues') return json([]);
    if (p === '/api/status') return json({cloud: true, active: [], queued: [], recent_runs: [], keeper_alive: true, health_issues: []});
    if (p === '/api/v2/status') return json({bots: []});
    if (p === '/api/v2/operations') return json({machines: [], services: [], agents: []});
    if (p === '/api/v2/groups' && method === 'POST') {
      const body = request.postDataJSON(); calls.push(['POST', 'groups', body]);
      const id = body.name.toLowerCase().replace(/[^a-z0-9]+/g, '-');
      groups.push({id, name: body.name, parent: body.parent || ''});
      return json({id});
    }
    let m;
    if ((m = p.match(/^\/api\/v2\/groups\/([^/]+)$/)) && method === 'PATCH') {
      const body = request.postDataJSON(); calls.push(['PATCH', m[1], body]); apply(m[1], body);
      return json({id: m[1]});
    }
    if (p === '/api/v2/tasks') return json({tasks: []});
    if (p === '/api/v2/conversations') return json({conversations: []});
    if (p.endsWith('/watch')) return route.fulfill({contentType: 'text/event-stream', body: ': fixture\n\n'});
    return json({});
  });
  page.on('pageerror', e => errors.push(e.message));
  await page.goto('https://tico-ui.test/#/updates');
  await page.locator('#tree a.node').first().waitFor();
  return {page, errors, calls};
}

// The chart as nested text: a group is {name: [...]}, a human or a bot is its name.
const shape = page => page.evaluate(() => {
  const walk = ul => [...ul.children].filter(li => li.tagName === 'LI' && !li.classList.contains('org-no-group')).map(li => {
    const kids = li.querySelector(':scope > ul'), label = li.querySelector(':scope > .noderow .dept-label, :scope > .noderow .nm, :scope > .noderow .org-name');
    const name = (label?.value ?? label?.textContent ?? '').trim();
    return kids ? {[name]: walk(kids)} : name;
  });
  return walk(document.querySelector('#tree'));
});
const row = (page, name) => page.locator('#tree .noderow[data-org^="g:"]', {has: page.locator('.dept-label', {hasText: new RegExp('^' + name + '$')})});
const node = (page, key) => page.locator(`#tree [data-org="${key}"]`);
// A real drag, with a pause after it starts: the "No group" row only shows once a drag has begun.
async function drag(page, from, to) {
  await from.hover();
  await page.mouse.down();
  await page.mouse.move(40, 40);
  await page.mouse.move(45, 45);
  await to.hover();
  await page.mouse.up();
}

async function owner(browser) {
  const {page, errors, calls} = await open(browser, {id: 'ana', role: 'owner', name: 'Ana', email: 'ana@example.test', cloud: true});
  // Groups nest and hold humans and bots; a member hangs under its manager inside the group; Built-in is outside.
  assert.deepEqual(await shape(page), [
    {Ana: ['Cara', 'Scout']}, {Marketing: [{Ben: ['CMO']}, {SEO: ['Writer']}]}, {Sales: []}, {'Built-in': ['BotOps']}]);
  // A group collapses.
  await page.locator('#tree .dept-label', {hasText: /^Marketing$/}).click();
  assert.equal(await page.locator('#tree a.node[href="#/bot/writer"]').isVisible(), false);
  await page.locator('#tree .dept-label', {hasText: /^Marketing$/}).click();
  assert.equal(await page.locator('#tree a.node[href="#/bot/writer"]').isVisible(), true);
  assert.equal(await node(page, 'b:botops').getAttribute('draggable'), null, 'a built-in bot is not moved');

  // Add a group: the plus beside Team, a field, Enter.
  await page.locator('#org-add-group').click();
  const field = page.locator('#tree .org-name');
  await field.fill('Legal');
  await field.press('Enter');
  await page.locator('#tree .dept-label', {hasText: /^Legal$/}).waitFor();
  assert.deepEqual(calls.shift(), ['POST', 'groups', {name: 'Legal'}]);
  // Escape adds nothing.
  await page.locator('#org-add-group').click();
  await page.locator('#tree .org-name').press('Escape');
  assert.equal(await page.locator('#tree .org-name').count(), 0);
  assert.deepEqual(calls, []);
  // Add one inside a group.
  await row(page, 'Sales').hover();
  await page.locator('[data-group-add=sales]').click();
  await page.locator('#tree .org-name').fill('EMEA');
  await page.locator('#tree .org-name').press('Enter');
  await page.locator('#tree .dept-label', {hasText: /^EMEA$/}).waitFor();
  assert.deepEqual(calls.shift(), ['POST', 'groups', {name: 'EMEA', parent: 'sales'}]);

  // Rename.
  await row(page, 'Sales').hover();
  await page.locator('[data-group-rename=sales]').click();
  assert.equal(await page.locator('#tree .org-name').inputValue(), 'Sales');
  await page.locator('#tree .org-name').fill('Revenue');
  await page.locator('#tree .org-name').press('Enter');
  await page.locator('#tree .dept-label', {hasText: /^Revenue$/}).waitFor();
  assert.deepEqual(calls.shift(), ['PATCH', 'sales', {name: 'Revenue'}]);

  // Drag a human, and a bot, into a group.
  await drag(page, node(page, 'p:cara'), row(page, 'Revenue'));
  await page.waitForFunction(() => document.querySelector('#tree [data-org="g:sales"]')?.closest('li')?.querySelector('a[href="#/person/cara"]'));
  assert.deepEqual(calls.shift(), ['PATCH', 'sales', {add: {people: ['cara']}}]);
  await drag(page, node(page, 'b:scout'), row(page, 'Revenue'));
  await page.waitForFunction(() => document.querySelector('#tree [data-org="g:sales"]')?.closest('li')?.querySelector('a[href="#/bot/scout"]'));
  assert.deepEqual(calls.shift(), ['PATCH', 'sales', {add: {bots: ['scout']}}]);

  // Nest a group in another.
  await drag(page, row(page, 'Legal'), row(page, 'Revenue'));
  await page.waitForFunction(() => [...document.querySelectorAll('#tree li.org-group')].some(li => li.querySelector(':scope > .noderow .dept-label')?.textContent === 'Revenue' && [...li.querySelectorAll(':scope > ul > li.org-group > .noderow .dept-label')].some(l => l.textContent === 'Legal')));
  assert.deepEqual(calls.shift(), ['PATCH', 'legal', {parent: 'sales'}]);
  assert.deepEqual(await shape(page), [
    'Ana', {Marketing: [{Ben: ['CMO']}, {SEO: ['Writer']}]},
    {Revenue: ['Cara', 'Scout', {Legal: []}, {EMEA: []}]}, {'Built-in': ['BotOps']}]);

  // Out of a group: onto "No group", which shows while dragging.
  assert.equal(await page.locator('#tree .org-no-group').isVisible(), false);
  await drag(page, node(page, 'p:cara'), page.locator('#tree .org-no-group'));
  await page.waitForFunction(() => !document.querySelector('#tree [data-org="g:sales"]')?.closest('li')?.querySelector('a[href="#/person/cara"]'));
  assert.deepEqual(calls.shift(), ['PATCH', 'sales', {remove: {people: ['cara']}}]);
  await drag(page, row(page, 'SEO'), page.locator('#tree .org-no-group'));
  await page.waitForFunction(() => [...document.querySelectorAll('#tree > li.org-group > .noderow .dept-label')].some(l => l.textContent === 'SEO'));
  assert.deepEqual(calls.shift(), ['PATCH', 'seo', {parent: ''}]);
  assert.deepEqual(await shape(page), [
    {Ana: ['Cara']}, {Marketing: [{Ben: ['CMO']}]}, {SEO: ['Writer']}, {Revenue: ['Scout', {Legal: []}, {EMEA: []}]}, {'Built-in': ['BotOps']}]);
  assert.deepEqual(errors, []);
  await page.close();
}

async function member(browser) {
  const {page, errors} = await open(browser, {id: 'ben', role: 'viewer', name: 'Ben', email: 'ben@example.test', cloud: true, company_role: 'member'});
  // A member reads the chart: no plus, no rename, nothing to drag, and a group nobody is in is not shown.
  assert.deepEqual(await shape(page), [
    {Ana: ['Cara', 'Scout']}, {Marketing: [{Ben: ['CMO']}, {SEO: ['Writer']}]}, {'Built-in': ['BotOps']}]);
  assert.equal(await page.locator('#org-add-group').isVisible(), false);
  assert.equal(await page.locator('[data-group-rename], [data-group-add], #tree .org-no-group').count(), 0);
  assert.equal(await page.locator('#tree .noderow[data-org^="g:"][draggable="true"]').count(), 0);
  assert.equal(await node(page, 'b:scout').getAttribute('draggable'), null, 'a member moves only what reports up to them');
  assert.deepEqual(errors, []);
  await page.close();
}

(async () => {
  const browser = await chromium.launch({channel: process.env.TICO_BROWSER_CHANNEL ?? 'chrome', headless: true});
  try {
    await owner(browser);
    await member(browser);
    console.log('PASS: groups nest in the team chart; owners add, rename, drag into and nest groups; members read.');
  } finally { await browser.close(); }
})().catch(error => { console.error(error); process.exitCode = 1; });
