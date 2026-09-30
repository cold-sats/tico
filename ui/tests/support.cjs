// Offline browser regression: Contact support on the Help page. The form shows exactly what it will send, Send files the
// ticket, "Your requests" lists it, a reply raises a small notice and a dot, and nothing a ticket says is rendered as HTML.
const {chromium} = require('playwright');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const {html, uiFile} = require('./support/page.cjs');
const INSTALL = '6f1c2a9e-3b7d-4c58-9a10-2d4e8b7f5a63';
const HOSTILE = '<img src=x onerror="window.__pwned=1"> <b>bold</b>';

(async () => {
  const browser = await chromium.launch({headless: true, channel: process.env.TICO_BROWSER_CHANNEL === undefined ? 'chrome' : process.env.TICO_BROWSER_CHANNEL || undefined});
  try {
    const visit = async ({enabled = true} = {}) => {
      const ctx = await browser.newContext({viewport: {width: 1440, height: 900}, serviceWorkers: 'block'});
      const page = await ctx.newPage();
      const errors = [], calls = [];
      const hq = {tickets: [], reply: false, read: false};
      const view = () => ({enabled, tickets: hq.tickets.map(t => ({...t, unread: t.messages.filter(m => m.from === 'staff' && !hq.read).length})),
                           unread: hq.tickets.reduce((n, t) => n + t.messages.filter(m => m.from === 'staff' && !hq.read).length, 0)});
      page.on('pageerror', e => errors.push(e.message));
      page.on('dialog', d => d.accept());
      await page.route('**/*', route => {
        const req = route.request(), p = new URL(req.url()).pathname;
        const json = (body, status = 200) => route.fulfill({status, contentType: 'application/json', body: JSON.stringify(body)});
        const ui = p.match(/\/tico\/ui\/((?:app\/|styles\/)?[^/]+\.(?:js|css))$/);
        if (ui && fs.existsSync(uiFile(ui[1])))
          return route.fulfill({contentType: ui[1].endsWith('.css') ? 'text/css' : 'application/javascript', body: fs.readFileSync(uiFile(ui[1]), 'utf8')});
        if (p.endsWith('.js')) return route.fulfill({contentType: 'application/javascript', body: ''});
        if (p === '/') return route.fulfill({contentType: 'text/html', body: html});
        const config = {version: '0.2.17', update: null, app_name: 'Tico', usage_count_notice: false};
        if (p === '/api/me') return json({id: 'ana', role: 'owner', name: 'Ana', email: 'ana@acme.example', cloud: true, registered: true, config});
        if (p === '/api/v2/config') return json(config);
        if (p.startsWith('/api/v2/support/')) {
          const rest = p.slice('/api/v2/support/'.length), body = req.postData() ? JSON.parse(req.postData()) : null;
          calls.push(req.method() + ' ' + rest + (body ? ' ' + JSON.stringify(body) : ''));
          if (rest === 'compose') return json({enabled: true, email: 'ana@acme.example', version: '0.2.17', install_id: INSTALL, to: 'updates.tico.team', max: 4000});
          if (rest === 'tickets' && req.method() === 'GET') return json(view());
          if (rest === 'tickets/refresh') {
            if (hq.reply && hq.tickets[0] && !hq.tickets[0].messages.length)
              Object.assign(hq.tickets[0], {status: 'answered', messages: [{id: 1, created: new Date().toISOString(), from: 'staff', body: 'Try the latest release. ' + HOSTILE}]});
            return json(view());
          }
          if (rest === 'tickets' && req.method() === 'POST') {
            const ticket = {id: 'sup_1', created: new Date().toISOString(), status: 'open', message: body.message, email: body.email,
                            sent: body.include_ids ? {version: '0.2.17', install_id: INSTALL} : {}, messages: [], unread: 0};
            hq.tickets.unshift(ticket);
            return json(ticket);
          }
          if (rest.endsWith('/read')) { hq.read = true; return json({...hq.tickets[0], unread: 0}); }
          if (rest.endsWith('/messages')) { hq.tickets[0].messages.push({id: 2, created: new Date().toISOString(), from: 'person', body: body.message}); return json({...hq.tickets[0], unread: 0}); }
          if (req.method() === 'DELETE') { hq.tickets = []; return json({deleted: true}); }
        }
        if (p === '/api/employees' || p === '/api/issues') return json([]);
        if (p === '/api/people') return json({people: [], teams: {}});
        if (p === '/api/status') return json({cloud: true, active: [], queued: [], recent_runs: [], keeper_alive: true, health_issues: []});
        if (p === '/api/v2/status') return json({bots: []});
        if (p === '/api/v2/needs-you') return json({items: []});
        if (p.endsWith('/watch')) return route.fulfill({contentType: 'text/event-stream', body: ': fixture\n\n'});
        return json({});
      });
      await page.goto('https://tico-ui.test/#/help');
      await page.waitForFunction(() => !document.querySelector('#account .account-email')?.textContent.includes('Signing in'));
      return {page, ctx, errors, calls, hq};
    };

    // The form, what it sends, and the list.
    let v = await visit();
    const {page} = v;
    await page.locator('[data-support-open]').click();
    const dialog = page.locator('dialog.support-modal');
    await dialog.waitFor({state: 'visible'});
    assert.equal(await dialog.locator('[name=email]').inputValue(), 'ana@acme.example', 'the email is prefilled');
    assert.equal(await dialog.locator('[name=ids]').isChecked(), true, 'the version and install ID are on by default');
    const sends = () => dialog.locator('[data-sent]').innerText();
    assert.equal(await sends(), `Sends to updates.tico.team: message, email ana@acme.example, version 0.2.17, install ID ${INSTALL}.`);
    await dialog.locator('[name=ids]').uncheck();
    await dialog.locator('[name=email]').fill('');
    assert.equal(await sends(), 'Sends to updates.tico.team: message.', 'the line follows the form');
    await dialog.locator('[name=email]').fill('ana@acme.example');
    await dialog.locator('[name=ids]').check();
    await dialog.locator('button[type=submit]').click();
    assert.match(await dialog.locator('[data-error]').innerText(), /Write a message/);
    assert.ok(!v.calls.some(c => c.startsWith('POST tickets ')), 'nothing is sent until there is a message');
    await dialog.locator('[name=message]').fill('The board will not load. ' + HOSTILE);
    await dialog.locator('button[type=submit]').click();
    await dialog.waitFor({state: 'detached'});
    const sentCall = v.calls.find(c => c.startsWith('POST tickets {'));
    assert.deepEqual(JSON.parse(sentCall.slice('POST tickets '.length)),
      {message: 'The board will not load. ' + HOSTILE, email: 'ana@acme.example', include_ids: true});
    const ticket = page.locator('details.support-ticket');
    await ticket.waitFor();
    assert.match(await ticket.locator('summary').innerText(), /The board will not load\./);
    assert.match(await ticket.locator('summary .pill').innerText(), /Open/);
    assert.equal(await page.locator('#support-mine h2').innerText(), 'Your requests');

    // Nothing a ticket says is HTML: the text is shown as typed.
    assert.equal(await ticket.evaluate(d => d.open), true, 'the new request opens');
    assert.match(await ticket.locator('.support-msg').first().innerText(), /<img src=x onerror="window.__pwned=1"> <b>bold<\/b>/);
    assert.equal(await page.locator('#support-mine img, #support-mine b').count(), 0);
    assert.equal(await page.evaluate(() => window.__pwned), undefined);

    // A reply: the notice, the dot, the thread, and reading it clears the dot.
    v.hq.reply = true;
    await page.evaluate(() => window.supportPoll());
    await page.waitForFunction(() => [...document.querySelectorAll('.toast')].some(t => /Tico support replied/.test(t.textContent)));
    assert.equal(await page.locator('#help-open').getAttribute('data-support-unread'), '1');
    assert.match(await ticket.locator('summary .pill').innerText(), /Answered/);
    await page.reload();
    await page.waitForFunction(() => document.querySelector('#support-mine details.support-ticket'));
    const again = page.locator('details.support-ticket');
    assert.equal(await again.locator('.support-dot').count(), 1, 'the unread reply is marked in the list');
    await again.locator('summary').click();
    await page.waitForFunction(() => !document.querySelector('.support-dot'));
    assert.ok(v.calls.some(c => c.startsWith('POST tickets/sup_1/read')), 'opening it marks it read');
    assert.equal(await page.locator('#help-open').getAttribute('data-support-unread'), null);
    const staffMessage = again.locator('.support-msg.staff');
    assert.match(await staffMessage.innerText(), /Tico support/);
    assert.match(await staffMessage.innerText(), /Try the latest release\. <img src=x onerror="window.__pwned=1"> <b>bold<\/b>/);
    assert.equal(await page.locator('#support-mine img, #support-mine b').count(), 0);

    // Writing back, and deleting.
    await again.locator('.support-write textarea').fill('It still fails.');
    await again.locator('.support-write button[type=submit]').click();
    await page.waitForFunction(() => document.querySelectorAll('.support-msg').length === 3);
    assert.ok(v.calls.some(c => c.startsWith('POST tickets/sup_1/messages') && c.includes('It still fails.')));
    await page.locator('[data-delete]').first().click();
    await page.waitForFunction(() => document.querySelector('#support-mine')?.hidden);
    assert.ok(v.calls.includes('DELETE tickets/sup_1'));
    assert.deepEqual(v.errors, []);
    await v.ctx.close();

    // Off (demo mode, or TICO_SUPPORT=off): no button, no list.
    v = await visit({enabled: false});
    await v.page.waitForSelector('#help-page');
    assert.equal(await v.page.locator('[data-support-open], #support-mine').count(), 0);
    assert.ok(!v.calls.some(c => c.startsWith('POST')), 'nothing is sent from a page that offers no form');
    assert.deepEqual(v.errors, []);
    await v.ctx.close();
  } finally {
    await browser.close();
  }
})().catch(e => { console.error(e); process.exit(1); });
