// The Meetings page (ui/app/meetings.js pageNotes, ui/meeting-importers.js): a header with search and one
// "Add notes" button, a strip of source tiles (Granola, Fireflies, Zoom, Google Meet, Close) that each say
// Connect or Connected, an empty state that offers both ways in, filters and rows only once there is a
// meeting, setup in a dialog, and a transcript upload inside Add notes. Light and dark, desktop and phone.
// Fixtures only, no network.
const {chromium} = require('playwright');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const {html, uiFile} = require('./support/page.cjs');

const ago = hours => new Date(Date.now() - hours * 36e5).toISOString();
const meeting = (id, title, source, hours, extra = {}) => ({id, title, source, kind: 'meeting', status: 'done', started: ago(hours),
  created: ago(hours), duration_ms: 1800000, participants: [{name: 'Ana', email: 'ana@acme.example'}, {name: 'Ben'}, {name: 'Cara'}],
  outbox: {doc: [], task: [], feature: []}, ...extra});
const MEETINGS = [
  meeting('m1', 'Weekly ops sync', 'zoom', 30, {outbox: {doc: [{text: 'Update pricing'}], feature: [],
    task: [{text: 'Send Dana the quote', status: 'proposed'}, {text: 'Book the review', status: 'pushed'}, {text: 'Gone', status: 'dismissed'}]}}),
  meeting('m2', 'Renewal call with Dana', 'granola', 80, {outbox: {doc: [], feature: [], task: [{text: 'Follow up', status: 'proposed'}]}}),
  meeting('m3', 'Notes from standup', 'manual', 200),
];
const IMPORTERS = ['granola', 'fireflies', 'zoom', 'google-meet'].map(source => ({source, name: {granola: 'Granola', fireflies: 'Fireflies',
  zoom: 'Zoom', 'google-meet': 'Google Meet'}[source], enabled: false, runner_id: '', status: 'off', last_success: null, last_import: null,
  imported_total: 0, error: '', setup: {file: `secrets/${source}.env`, keys: ['API_KEY'], doc: 'docs/meetings.md'}}));
const NONE = [{id: 'import', name: 'Import', status: 'available'}, {id: 'close', name: 'Close', status: 'needs_setup'}];
const SOME = [{id: 'import', name: 'Import', status: 'available'},
  {id: 'close', name: 'Close', status: 'syncing', last_success: ago(0.1), last_import: ago(3)},
  {id: 'granola', name: 'Granola', status: 'syncing', last_success: ago(0.2), last_import: ago(26)},
  {id: 'fireflies', name: 'Fireflies', status: 'needs_setup'},
  {id: 'zoom', name: 'Zoom', status: 'error', last_success: ago(9)}];

async function open(browser, viewport, world, options = {}) {
  const context = await browser.newContext({viewport, serviceWorkers: 'block', hasTouch: viewport.width < 760, isMobile: viewport.width < 760, ...options});
  const page = await context.newPage();
  const errors = [];
  page.on('pageerror', error => errors.push(error.message));
  await page.route('**/*', route => {
    const url = new URL(route.request().url()), p = url.pathname, method = route.request().method();
    const json = body => route.fulfill({contentType: 'application/json', body: JSON.stringify(body)});
    if (/\/marked\.min\.js$/.test(p)) return route.fulfill({contentType: 'application/javascript', body: 'window.marked={parse:s=>String(s)}'});
    if (url.origin !== 'https://tico-ui.test') return route.abort();
    const ui = p.match(/\/tico\/ui\/((?:app\/|styles\/)?[^/]+\.(?:js|css))$/);
    if (ui && fs.existsSync(uiFile(ui[1]))) return route.fulfill({contentType: ui[1].endsWith('.css') ? 'text/css' : 'application/javascript', body: fs.readFileSync(uiFile(ui[1]), 'utf8')});
    if (p === '/') return route.fulfill({contentType: 'text/html', body: html});
    if (p === '/api/me') return json({id: 'ana', role: world.role || 'owner', name: 'Ana', email: 'ana@example.test', cloud: true});
    if (p === '/api/people') return json({people: [{id: 'ana', name: 'Ana', email: 'ana@acme.example'}, {id: 'ben', name: 'Ben'}]});
    if (p === '/api/employees') return json([]);
    if (p === '/api/status') return json({cloud: true, active: [], queued: [], recent_runs: [], keeper_alive: true, health_issues: [], schedules: []});
    if (p === '/api/v2/status') return json({bots: []});
    if (p === '/api/v2/updates') return json({updates: [], missed: [], unread: 0, next_before: null, today: {}});
    if (p === '/api/v2/tasks') return json({tasks: []});
    if (p === '/api/v2/getting-started') return json({items: [], done: 0, total: 0, complete: true, dismissed: true, tour_seen: true, cards_dismissed: [],
      can_build: true, owner: true, empty: {docs: true, market: true, tasks: true, updates: true, goals: true, meetings: true}});
    if (p === '/api/meetings/sources') return json({sources: world.sources});
    if (p === '/api/meetings') return json(world.meetings);
    if (p === '/api/v2/meeting-importers' && method === 'GET') return json({computers: [{id: 'mac', label: 'Test Mac', platform: 'macos', online: true}], importers: world.importers});
    if (p.startsWith('/api/v2/meeting-importers/') && method === 'POST') {
      const body = JSON.parse(route.request().postData());
      world.saved.push({source: p.split('/').pop(), ...body});
      const i = world.importers.find(x => x.source === p.split('/').pop());
      Object.assign(i, {enabled: body.enabled, runner_id: body.runner_id, status: 'waiting'});
      return json({});
    }
    if (p === '/api/v2/meetings/import' && method === 'POST') { const body = JSON.parse(route.request().postData()); world.imported.push(body); return json({id: 'm9', existing: false}); }
    if (/^\/api\/meetings\/m\d$/.test(p)) return json({...world.meetings.find(m => p.endsWith(m.id)), turns: [], transcript_readable: '', outbox: {doc: [], task: [], feature: []}});
    if (p.endsWith('/watch')) return route.fulfill({contentType: 'text/event-stream', body: ': fixture\n\n'});
    return json({});
  });
  return {page, errors, context};
}
const world = (extra = {}) => ({role: 'owner', sources: NONE, meetings: [], importers: structuredClone(IMPORTERS), saved: [], imported: [], ...extra});
const words = async (page, selector) => (await page.locator(selector).allInnerTexts()).map(t => t.replace(/\s+/g, ' ').trim());

(async () => {
  const browser = await chromium.launch({headless: true, channel: process.env.TICO_BROWSER_CHANNEL === undefined ? 'chrome' : process.env.TICO_BROWSER_CHANNEL || undefined});
  try {
    for (const scheme of ['light', 'dark']) {
      // ---- nothing yet, nothing connected: the empty state offers both ways in
      let w = world();
      let {page, errors, context} = await open(browser, {width: 1280, height: 900}, w, {colorScheme: scheme});
      await page.goto('https://tico-ui.test/#/meetings');
      await page.locator('.meet-blank').waitFor();
      assert.equal((await page.locator('#main h1').innerText()).trim(), 'Meetings');
      assert.equal(await page.locator('#notes-search').getAttribute('placeholder'), 'Search meetings');
      assert.equal(await page.locator('#notes-manual').innerText(), 'Add notes');
      assert.equal(await page.locator('#notes-import').count(), 0, scheme + ': no Import button under the title');
      assert.equal(await page.locator('[data-gs-card=meetings]').count(), 0, scheme + ': no intro banner');
      assert.equal((await page.locator('.meet-blank h2').innerText()).trim(), 'Connect a source or add a note');
      assert.deepEqual(await words(page, '.meet-blank .meet-tile .mt-text'), ['Granola Connect', 'Fireflies Connect', 'Zoom Connect', 'Google Meet Connect', 'Close Connect']);
      assert.equal(await page.locator('.meet-blank [data-add]').innerText(), 'Add notes');
      assert.equal(await page.locator('#meet-sources').isHidden(), true, scheme + ': the large tiles stand in for the strip');
      assert.equal(await page.locator('#notes-filters').isHidden(), true, scheme + ': no filters without a meeting');
      const text = await page.locator('#main').innerText();
      assert(!/Import|transcript/i.test(text.replace('Add notes', '')), scheme + ': no "Import a transcript" wording\n' + text);
      assert.equal(await page.locator('.meet-blank [data-msrc=granola] svg, .meet-blank [data-msrc=granola] .tool-initials').count(), 1);
      assert.equal(await page.locator('.meet-blank [data-msrc=zoom] svg').count(), 1, 'Zoom uses its logo from ui/tool-icons.js');
      const colors = await page.locator('.meet-blank .meet-tile .mt-text').first().evaluate(el => ({ink: getComputedStyle(el).color, bg: getComputedStyle(el).backgroundColor}));
      assert.notEqual(colors.ink, colors.bg, scheme + ': tile contrast');

      // A tile opens that source's setup in a dialog, and saving enables it.
      await page.locator('.meet-blank [data-msrc=granola]').click();
      const dialog = page.locator('dialog[aria-label="Connect Granola"]');
      await dialog.locator('form[data-importer=granola]').waitFor();
      assert.equal(await dialog.locator('form[data-importer]').count(), 1, 'only that importer');
      assert.equal(await dialog.locator('details').getAttribute('open'), '', 'the credential steps are open when it is off');
      await dialog.locator('input[name=enabled]').check();
      await dialog.locator('select[name=runner]').selectOption('mac');
      w.sources = SOME;
      await dialog.locator('button[type=submit]').click();
      await page.waitForFunction(() => document.querySelector('.meet-blank [data-msrc=granola] .mt-status')?.textContent.includes('Connected'));
      assert.deepEqual(w.saved, [{source: 'granola', enabled: true, runner_id: 'mac'}]);
      await page.keyboard.press('Escape');
      await dialog.waitFor({state: 'detached'});

      // Close goes to its integration page.
      assert.equal(await page.locator('.meet-blank a[data-state]').first().getAttribute('href'), '#/integrations/close-crm');

      // Add notes: notes alone are filed as "manual"; a dropped or uploaded transcript files as an upload.
      await page.locator('#notes-manual').click();
      const notes = page.locator('#manual-modal');
      await notes.locator('#manual-form').waitFor();
      assert.equal(await page.locator('#import-modal').count(), 0, 'one dialog for notes and transcripts');
      assert.equal(await notes.locator('#manual-transcript').isHidden(), true);
      await notes.locator('#manual-go').click();
      assert.match(await notes.locator('#manual-msg').innerText(), /Add notes or a transcript/);
      await notes.locator('#manual-file').setInputFiles({name: 'pricing_call.vtt', mimeType: 'text/vtt', buffer: Buffer.from('WEBVTT\n\n00:00:05.000 --> 00:00:08.500\n<v Dana>Can you send pricing?</v>\n')});
      await page.waitForFunction(() => document.querySelector('#manual-text')?.value.startsWith('WEBVTT'));
      assert.equal(await notes.locator('#manual-title').inputValue(), 'pricing call');
      assert.equal(await notes.locator('#manual-source').inputValue(), 'upload');
      await notes.locator('#manual-go').click();
      await page.waitForFunction(() => !document.querySelector('#manual-modal[open]'));
      assert.equal(w.imported.length, 1);
      assert.equal(w.imported[0].source, 'upload');
      assert.equal(w.imported[0].title, 'pricing call');
      assert(w.imported[0].transcript.startsWith('WEBVTT'));
      await page.locator('#notes-manual').click();
      await notes.locator('#manual-title').fill('Standup');
      await notes.locator('#manual-notes').fill('Ship on Friday');
      await notes.locator('#manual-go').click();
      await page.waitForFunction(() => !document.querySelector('#manual-modal[open]'));
      assert.equal(w.imported[1].source, 'manual');
      assert.equal(w.imported[1].notes, 'Ship on Friday');
      assert.equal(w.imported[1].transcript, undefined);
      assert.deepEqual(errors, []);
      await context.close();

      // ---- with meetings: the strip, the filters and one row each
      w = world({sources: SOME, meetings: MEETINGS});
      ({page, errors, context} = await open(browser, {width: 1280, height: 900}, w, {colorScheme: scheme}));
      await page.goto('https://tico-ui.test/#/meetings');
      await page.locator('.meet-row').first().waitFor();
      assert.equal(await page.locator('.meet-blank').count(), 0);
      assert.equal(await page.locator('#notes-import').count(), 0);
      assert.equal(await page.locator('#meet-sources').isVisible(), true);
      assert.deepEqual(await words(page, '#meet-sources .meet-tile .mt-text'), ['Granola Connected 1d ago', 'Fireflies Waiting', 'Zoom Error', 'Google Meet Connect', 'Close Connected 3h ago']);
      assert.equal(await page.locator('#meet-sources [data-state=on] .dot').count(), 2, 'a green dot on each connected source');
      const tops = await page.locator('#meet-sources .meet-tile .mt-text').evaluateAll(els => els.map(el => Math.round(el.getBoundingClientRect().top)));
      assert.equal(new Set(tops).size, 1, scheme + ': the strip is one line on a desktop');
      assert.equal(await page.locator('#notes-filters').isVisible(), true);
      assert.deepEqual(await page.locator('#notes-filters select').evaluateAll(els => els.map(el => el.getAttribute('aria-label'))), ['When', 'Participant', 'Source', 'Status']);
      const filterTops = await page.locator('#notes-filters select').evaluateAll(els => els.map(el => Math.round(el.getBoundingClientRect().top)));
      assert.equal(new Set(filterTops).size, 1, 'the filters are one line');
      assert.deepEqual(await page.locator('.meet-row .note-title').allInnerTexts(), ['Weekly ops sync', 'Renewal call with Dana', 'Notes from standup']);
      assert.deepEqual(await page.locator('.meet-row').evaluateAll(rows => rows.map(r => r.querySelector('.meet-tasks')?.textContent || '')), ['2 tasks', '1 task', '']);
      assert.equal(await page.locator('.meet-row').first().locator('.msrc-logo svg').count(), 1);
      assert.match(await page.locator('.meet-row').first().locator('.meet-meta').innerText(), /Ana, Ben \+1/);
      // Search and the Source filter narrow the list.
      await page.locator('#notes-source').selectOption('granola');
      assert.deepEqual(await page.locator('.meet-row .note-title').allInnerTexts(), ['Renewal call with Dana']);
      await page.locator('#notes-source').selectOption('');
      await page.evaluate(() => { window.opened = []; window.open = url => (window.opened.push(url), {}); });
      await page.locator('.meet-row .note-title').first().click();   // a desktop opens the meeting in its own window
      assert.match(await page.evaluate(() => window.opened[0]), /meeting=m1&window=1/);
      assert.deepEqual(errors, []);
      await context.close();

      // ---- a meeting exists but nothing is connected: the strip still shows, all "Connect"
      w = world({meetings: MEETINGS});
      ({page, context} = await open(browser, {width: 1280, height: 900}, w, {colorScheme: scheme}));
      await page.goto('https://tico-ui.test/#/meetings');
      await page.locator('.meet-row').first().waitFor();
      assert.deepEqual(await words(page, '#meet-sources .meet-tile .mt-text'), ['Granola Connect', 'Fireflies Connect', 'Zoom Connect', 'Google Meet Connect', 'Close Connect']);
      await context.close();

      // ---- not the owner: the tiles show status but do not open setup
      w = world({role: 'member', sources: SOME, meetings: MEETINGS});
      ({page, context} = await open(browser, {width: 1280, height: 900}, w, {colorScheme: scheme}));
      await page.goto('https://tico-ui.test/#/meetings');
      await page.locator('.meet-row').first().waitFor();
      assert.equal(await page.locator('#meet-sources [data-msrc=granola]').isDisabled(), true);
      await context.close();

      // ---- a phone: the strip scrolls sideways, the page does not
      w = world({sources: SOME, meetings: MEETINGS});
      ({page, errors, context} = await open(browser, {width: 390, height: 844}, w, {colorScheme: scheme}));
      await page.goto('https://tico-ui.test/#/meetings');
      await page.locator('.meet-row').first().waitFor();
      const strip = await page.locator('#meet-sources .meet-tiles').evaluate(el => ({scroll: el.scrollWidth, width: el.clientWidth, overflow: getComputedStyle(el).overflowX}));
      assert(strip.scroll > strip.width && strip.overflow === 'auto', scheme + ': the strip scrolls on a phone ' + JSON.stringify(strip));
      assert(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth), scheme + ': no sideways page scroll');
      assert.equal(await page.locator('#notes-manual').isVisible(), true);
      await context.close();

      w = world();
      ({page, context} = await open(browser, {width: 390, height: 844}, w, {colorScheme: scheme}));
      await page.goto('https://tico-ui.test/#/meetings');
      await page.locator('.meet-blank').waitFor();
      assert(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth), scheme + ': the empty state fits a phone');
      await context.close();
    }
    console.log('meetings ok');
  } finally {
    await browser.close();
  }
})().catch(error => { console.error(error); process.exit(1); });
