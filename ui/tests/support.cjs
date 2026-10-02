// Offline browser regression: Contact support on the Help page. The form shows exactly what it will send, Send files the
// ticket, "Your requests" lists it, a reply raises a small notice and a dot, and nothing a ticket says is rendered as HTML.
const {chromium} = require('playwright');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const {html, uiFile} = require('./support/page.cjs');
const INSTALL = '6f1c2a9e-3b7d-4c58-9a10-2d4e8b7f5a63';
const DIAGNOSTICS_TEXT = '{\n  "format": 1,\n  "versions": {\n    "tico": "0.2.17"\n  }\n}';
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
          if (rest === 'diagnostics') return json({id: (req.method() === 'POST' ? 'e' : 'd').repeat(64), bytes: 2048, text: body?.text || DIAGNOSTICS_TEXT});
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
        if (p === '/api/humans') return json({people: [], teams: {}});
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

    let v = await visit();
    const {page} = v;
    await page.locator('#support-rail').waitFor();
    const form = page.locator('[data-compose]');
    assert.equal(await form.locator('[name=diag]').isChecked(), true);
    assert.equal(await page.locator('.help-pieces').count(), 0);
    assert.equal(await page.locator('.help-actions .primary').count(), 0);
    assert.match(await page.locator('.help-hero').innerText(), /human and AI teammates/);
    await form.locator('[data-preview]').click();
    const dialog = page.locator('dialog.support-modal');
    await dialog.locator('[data-use]:not([disabled])').waitFor();
    assert.equal(await dialog.locator('textarea').inputValue(), DIAGNOSTICS_TEXT);
    await dialog.locator('textarea').fill('{"format":1}');
    assert.equal(await dialog.locator('[data-use]').isDisabled(), true);
    await dialog.locator('[data-save]').click();
    await dialog.locator('[data-use]:not([disabled])').waitFor();
    await dialog.locator('[data-use]').click();
    await form.locator('[name=message]').fill('The board will not load. ' + HOSTILE);
    await form.locator('[type=submit]').click();
    await page.waitForFunction(() => document.querySelector('[data-requests]')?.value === 'sup_1');
    const sent = JSON.parse(v.calls.find(c => c.startsWith('POST tickets {')).slice('POST tickets '.length));
    assert.equal(sent.diagnostics, 'e'.repeat(64), 'the edited preview is sent');
    assert.equal(sent.message, 'The board will not load. ' + HOSTILE);
    assert.equal(await form.locator('[name=diag]').isChecked(), false, 'follow-up attachments are opt-in');
    assert.match(await page.locator('[data-thread]').innerText(), /<img src=x/);
    assert.equal(await page.locator('[data-thread] img, [data-thread] b').count(), 0);
    assert.equal(await page.evaluate(() => window.__pwned), undefined);

    await form.locator('[name=message]').fill('Draft kept during refresh');
    v.hq.reply = true;
    await page.evaluate(() => window.supportPoll());
    assert.equal(await form.locator('[name=message]').inputValue(), 'Draft kept during refresh');
    assert.match(await page.locator('.support-msg.staff').innerText(), /Try the latest release/);
    assert.equal(await page.locator('#help-open').getAttribute('data-support-unread'), '1');
    await page.locator('[data-read]').click();
    await page.waitForFunction(() => !document.querySelector('#help-open')?.hasAttribute('data-support-unread'));
    await form.locator('[name=diag]').check();
    await form.locator('[type=submit]').click();
    await page.waitForFunction(() => document.querySelectorAll('.support-msg').length === 3);
    assert.ok(v.calls.some(c => c.startsWith('POST tickets/sup_1/messages') && c.includes('"diagnostics":"' + 'd'.repeat(64))));

    await page.screenshot({path: '/tmp/tico-support-desktop.png', fullPage: true});
    await page.setViewportSize({width: 390, height: 844});
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true, 'phone has no horizontal overflow');
    await page.waitForTimeout(250); // finish the existing navigation drawer's resize transition
    await page.locator('#support-rail').scrollIntoViewIfNeeded();
    await page.screenshot({path: '/tmp/tico-support-phone.png', fullPage: false});
    await page.locator('[data-delete]').click();
    await page.waitForFunction(() => document.querySelector('[data-requests]')?.options.length === 1);
    assert.deepEqual(v.errors, []);
    await v.ctx.close();
    v = await visit({enabled: false});
    await v.page.waitForSelector('#help-page');
    assert.equal(await v.page.locator('#support-rail').count(), 0);
    assert.ok(!v.calls.some(c => c.startsWith('POST')));
    assert.deepEqual(v.errors, []);
    await v.ctx.close();
  } finally {
    await browser.close();
  }
})().catch(e => { console.error(e); process.exit(1); });
