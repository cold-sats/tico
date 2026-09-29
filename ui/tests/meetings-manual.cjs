// The Meetings page: "Add meeting notes" files typed notes through POST /api/v2/meetings/import as
// source "manual" (participants from the roster plus free text, optional send-to bot), then opens
// the meeting. Fixtures only.
const {chromium} = require('playwright');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
(async () => {
  const browser = await chromium.launch({headless: true, channel: process.env.TICO_BROWSER_CHANNEL === undefined ? 'chrome' : process.env.TICO_BROWSER_CHANNEL || undefined});
  try {
    const page = await browser.newPage({viewport: {width: 1280, height: 900}, serviceWorkers: 'block'});
    const errors = [];
    page.on('pageerror', e => errors.push(e.message));
    const meetings = [], posts = [];
    const detail = m => ({...m, notes: m.notes || '', transcript_readable: '', meeting_context: '', delivery: null, version: 1, can_edit: true,
      outbox: {doc: [], task: [], feature: []}, outcome: null, attachments: []});
    await page.route('**/*', async route => {
      const req = route.request(), p = new URL(req.url()).pathname;
      const json = (body, status = 200) => route.fulfill({status, contentType: 'application/json', body: JSON.stringify(body)});
      if (p === '/') return route.fulfill({contentType: 'text/html', body: fs.readFileSync(path.join(__dirname, '../index.html'), 'utf8')});
      const ui = p.match(/\/tico\/ui\/([^/]+\.js)$/);
      if (ui) { const file = path.join(__dirname, '..', ui[1]); if (fs.existsSync(file)) return route.fulfill({contentType: 'application/javascript', body: fs.readFileSync(file, 'utf8')}); }
      if (p.endsWith('.js')) return route.fulfill({contentType: 'application/javascript', body: ''});
      if (p === '/api/me') return json({id: 'ana', name: 'Ana', email: 'ana@example.com', role: 'owner', cloud: true});
      if (p === '/api/employees') return json([{name: 'cpo', display_name: 'Product', status: 'active', kind: 'bot'}]);
      if (p === '/api/issues') return json([]);
      if (p === '/api/people') return json({people: [{id: 'ana', name: 'Ana', email: 'ana@example.com'}, {id: 'dana', name: 'Dana Cole', email: 'dana@example.com'}, {id: 'sam', name: 'Sam'}]});
      if (p === '/api/meetings/sources') return json({sources: []});
      if (p === '/api/meetings') return json(meetings);
      if (p === '/api/v2/meetings/import') {
        const body = JSON.parse(req.postData() || '{}'); posts.push(body);
        meetings.unshift({id: 'm1', kind: 'meeting', title: body.title, status: 'done', started: body.started_at, source: 'manual', owner: 'ana@example.com',
          participants: (body.participants || []).map(name => ({name, email: null, person_id: null})), turns: [], speakers: [], notes: body.notes,
          preview: body.notes, can_edit: true, outbox: {doc: [], task: [], feature: []}});
        return json({id: 'm1', title: body.title, kind: 'meeting', status: 'done', turns: 0, existing: false, changed: true, link: '#/meetings?meeting=m1',
          ...(body.send_to ? {sent: {slug: body.send_to, task: 't1'}} : {})});
      }
      const one = p.match(/^\/api\/meetings\/([^/]+)$/);
      if (one) return json(detail(meetings.find(m => m.id === one[1]) || {}));
      if (/^\/api\/meetings\/[^/]+\/items$/.test(p)) return json({id: 'm1', can_push: true, sections: {doc: [], task: [], feature: []}, counts: {proposed: 0}});
      if (/^\/api\/meetings\/[^/]+\/comments$/.test(p)) return json({id: 'm1', comments: []});
      if (p.endsWith('/watch')) return route.fulfill({contentType: 'text/event-stream', body: ': fixture\n\n'});
      return json({people: [], bots: [], models: [], runners: [], config: {}});
    });
    await page.goto('https://tico-ui.test/#/meetings');
    await page.locator('.notes-empty').waitFor();
    await page.getByRole('button', {name: 'Add meeting notes', exact: true}).click();
    const dialog = page.locator('#manual-modal');
    await dialog.waitFor();
    assert.match(await dialog.locator('#manual-when').inputValue(), /^\d{4}-\d\d-\d\dT\d\d:\d\d$/, 'the time defaults to now');

    await dialog.getByRole('button', {name: 'Add notes', exact: true}).click();
    assert.match(await dialog.locator('#manual-msg').innerText(), /Add a title and some notes/);
    assert.equal(posts.length, 0);

    await dialog.locator('#manual-title').fill('Weekly sync');
    await dialog.locator('#manual-when').fill('2026-09-28T16:00');
    await dialog.getByLabel('Dana Cole').check();
    await dialog.getByLabel('Sam', {exact: true}).check();
    await dialog.locator('#manual-others').fill('lee@example.com, Pat');
    await dialog.locator('#manual-notes').fill('## Decisions\n- ship on Friday');
    await dialog.locator('#manual-send').selectOption('cpo');
    await dialog.getByRole('button', {name: 'Add notes', exact: true}).click();

    await page.locator('#notes-modal[open] #meet-heading').waitFor();
    assert.equal(posts.length, 1);
    const body = posts[0];
    assert.equal(body.source, 'manual');
    assert.equal(body.title, 'Weekly sync');
    assert.equal(body.notes, '## Decisions\n- ship on Friday');
    assert.equal(body.transcript, undefined, 'typed notes carry no transcript');
    assert.equal(body.send_to, 'cpo');
    assert.deepEqual(body.participants, ['dana@example.com', 'Sam', 'lee@example.com', 'Pat']);
    assert.match(body.started_at, /^2026-09-28T16:00:00[+-]\d\d:\d\d$/);
    assert.match(await page.locator('#notes-detail').innerText(), /Weekly sync[\s\S]*Typed/);
    await page.getByRole('button', {name: 'Close meeting'}).click();
    assert.match(await page.locator('.notes-table').innerText(), /Weekly sync/);
    assert.deepEqual(errors, []);
    console.log('meetings-manual: ok');
  } finally { await browser.close(); }
})().catch(error => { console.error(error); process.exitCode = 1; });
