// Offline regression for the pieces around the wizard: the Getting started page shows exactly what
// the server computed and nothing else; the Docs and Market cards file the expected API calls;
// cards close and stay closed (the server holds that per person); the tour is replayable from Help,
// traps focus, closes on Escape and works in the phone drawer. Fixtures only - no server.
// TICO_SCREENSHOT_DIR=<dir> saves the review screenshots.
const {chromium} = require('playwright');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const html = fs.readFileSync(path.join(__dirname, '../index.html'), 'utf8');
const shots = process.env.TICO_SCREENSHOT_DIR;
const shot = (page, name) => shots ? page.screenshot({path: path.join(shots, `onboarding-v2-${name}.png`)}) : null;

const item = (id, label, done, extra = {}) => ({id, label, done, optional: false, skipped: false, why: '', href: '', tab: '', action: '', ...extra});
// What the server computed for a company with a computer online but no model signed in yet.
const checklist = () => [
  item('signed_in', 'Signed in', true),
  item('computer', 'A computer is online', true),
  item('model', 'A model is signed in on it', false, {why: 'Sign in to a model on the computer (run `codex login`).', href: '#/settings', tab: 'devices'}),
  item('github', 'GitHub is connected', false, {optional: true, why: 'Lets bots keep their work in your GitHub.', href: '#/settings', tab: 'cloud'}),
  item('botops', 'BotOps is active', true),
  item('first_bot', 'Create your first bot', false, {why: 'Say what it should do and BotOps builds it.', action: 'create-bot'}),
  item('bot_task', 'Your new bot finished a task', false, {why: 'Give it something small to do from its page.', href: '#/tasks'}),
  item('first_update', 'Your first update arrived', false, {why: 'Each active bot posts a short update every day.', href: '#/updates'}),
];
const bots = [['coo', 'Ace'], ['botops', 'BotOps']].map(([name, display_name]) =>
  ({name, display_name, host: 'keeper', status: 'active', can_chat: true, team: '', operator: 'ana'}));

(async () => {
  const browser = await chromium.launch({channel: process.env.TICO_BROWSER_CHANNEL ?? 'chrome', headless: true});
  try {
    const context = await browser.newContext({viewport: {width: 1200, height: 800}, serviceWorkers: 'block'});
    const calls = [];
    let items = checklist(), empty = {docs: true, market: true, tasks: true, updates: true, goals: true, meetings: true};
    let dismissed = {tour: true, checklist: false, cards: [], skipped: []};
    const view = () => {
      const rows = items.map(row => ({...row, skipped: row.optional && !row.done && dismissed.skipped.includes(row.id)}));
      const done = rows.filter(row => row.done || row.skipped).length;
      return {items: rows, done, total: rows.length, complete: done === rows.length, dismissed: dismissed.checklist,
              tour_seen: dismissed.tour, cards_dismissed: dismissed.cards, can_build: true, owner: true, empty};
    };
    await context.route('**/*', async route => {
      const req = route.request(), url = new URL(req.url()), p = url.pathname;
      const json = (body, status = 200) => route.fulfill({status, contentType: 'application/json', body: JSON.stringify(body)});
      if (url.origin !== 'http://tico-ui.test') return route.abort();
      if (p === '/') return route.fulfill({contentType: 'text/html', body: html});
      const ui = p.match(/\/tico\/ui\/([^/]+\.js)$/);
      if (ui) { const file = path.join(__dirname, '..', ui[1]); if (fs.existsSync(file)) return route.fulfill({contentType: 'application/javascript', body: fs.readFileSync(file, 'utf8')}); }
      if (p.startsWith('/vendor/fonts/') && p.endsWith('.woff2')) return route.fulfill({contentType: 'font/woff2', body: fs.readFileSync(path.join(__dirname, '..', p))});
      if (p === '/api/employees') return json(bots);
      if (p === '/api/issues') return json([]);
      if (p === '/api/me') return json({id: 'ana', name: 'Ana', email: 'ana@acme.example', role: 'owner', cloud: true});
      if (p === '/api/status') return json({active: [], employees: []});
      if (p === '/api/v2/status') return json({bots: []});
      if (p === '/api/people') return json({people: [{id: 'ana', name: 'Ana'}]});
      if (p === '/api/v2/updates/unread') return json({unread: 0});
      if (p === '/api/v2/updates') return json({updates: [], missed: [], unread: 0, next_before: null, today: {}});
      if (p === '/api/v2/tasks') return json({tasks: []});
      if (p === '/api/v2/docs') return json({docs: [], next_cursor: null});
      if (p === '/api/v2/linked-docs') return json({linked: []});
      if (p === '/api/v2/getting-started' && req.method() === 'GET') return json(view());
      if (p === '/api/v2/getting-started/state') {
        const body = req.postDataJSON(); calls.push({p, body});
        if (body.tour !== undefined) dismissed.tour = body.tour;
        if (body.checklist !== undefined) dismissed.checklist = body.checklist;
        if (body.card) dismissed.cards = [...new Set([...dismissed.cards, body.card])];
        if (body.skip) dismissed.skipped = [...new Set([...dismissed.skipped, body.skip])];
        return json({tour: dismissed.tour, checklist: dismissed.checklist, cards: dismissed.cards, skipped: dismissed.skipped});
      }
      if (p === '/api/v2/getting-started/bot') { calls.push({p, body: req.postDataJSON()}); return json({task_id: 't-bot', slug: 'help-desk', name: 'Help Desk'}); }
      if (p === '/api/v2/getting-started/docs') { calls.push({p, body: req.postDataJSON()}); return json({linked: [{id: 'link-1', title: 'github.com/acme/handbook', kind: 'github'}], skipped: []}); }
      if (p === '/api/v2/getting-started/market') {
        const body = req.postDataJSON(); calls.push({p, body});
        if (!body.add_analyst) return json({error: {code: 'confirm_analyst', detail: 'The Market Analyst is not set up yet.', needs_analyst: true}}, 409);
        return json({task_id: 't-market', bot: 'botops', needs_analyst: true});
      }
      if (p.endsWith('/watch')) return route.fulfill({contentType: 'text/event-stream', body: ': fixture\n\n'});
      return json({});
    });
    const errors = [];
    const open = async (hash, viewport) => {
      const page = await context.newPage();
      page.on('pageerror', e => errors.push(hash + ': ' + e.message));
      if (viewport) await page.setViewportSize(viewport);
      await page.goto('http://tico-ui.test/' + hash);
      await page.locator('#nav-getting-started:not([hidden])').waitFor();
      return page;
    };

    // ---- the checklist: what the server said, with the count in the rail
    let page = await open('#/getting-started');
    assert.equal(await page.locator('#gs-count').textContent(), '3/8');
    assert.equal(await page.locator('#gs-progress').textContent(), '3 of 8 done');
    const states = () => page.locator('[data-gs-item]').evaluateAll(els => Object.fromEntries(els.map(el => [el.dataset.gsItem, el.dataset.state])));
    assert.deepEqual(await states(), {signed_in: 'done', computer: 'done', model: 'todo', github: 'todo', botops: 'done',
      first_bot: 'todo', bot_task: 'todo', first_update: 'todo'});
    assert.match(await page.locator('[data-gs-item=model]').textContent(), /run `codex login`/);
    assert.equal(await page.locator('[data-gs-item=computer] .gs-item-actions a').count(), 0);   // a done step asks for nothing
    assert.equal(await page.locator('[data-gs-item=github] [data-gs-skip]').count(), 1);
    assert.equal(await page.locator('[data-gs-item=model] [data-gs-skip]').count(), 0);
    await shot(page, 'checklist');

    // A step fixes itself when the state does: the page has no way to tick it by hand.
    items = items.map(row => row.id === 'model' ? {...row, done: true, why: ''} : row);
    await page.reload();
    await page.locator('#gs-page [data-gs-item]').first().waitFor();
    assert.equal(await page.locator('#gs-progress').textContent(), '4 of 8 done');
    assert.equal(await page.locator('[data-gs-item=model]').getAttribute('data-state'), 'done');

    // The link on a step opens the right Settings tab.
    await page.locator('[data-gs-item=github] a').click();
    await page.waitForFunction(() => location.hash === '#/settings');
    await page.waitForFunction(() => document.querySelector('[data-settings-tab=cloud]')?.getAttribute('aria-selected') === 'true'
      || document.querySelector('[data-settings-tab=cloud].cur, [data-settings-tab=cloud][aria-pressed=true]'));
    await page.goBack();
    await page.locator('[data-gs-item=github]').waitFor();

    // Skipping the optional step counts it, and says so.
    await page.locator('[data-gs-skip=github]').click();
    await page.waitForFunction(() => document.querySelector('[data-gs-item=github]')?.dataset.state === 'skipped');
    assert.deepEqual(calls.at(-1), {p: '/api/v2/getting-started/state', body: {skip: 'github'}});
    assert.equal(await page.locator('#gs-progress').textContent(), '5 of 8 done');

    // "Create a bot" asks what the bot should do and files it for BotOps.
    await page.locator('[data-gs-item=first_bot] [data-gs-build]').click();
    await page.locator('dialog.gs-form[open]').waitFor();
    assert.equal(await page.locator('dialog.gs-form h2').textContent(), 'What should your bot do?');
    await page.locator('dialog.gs-form textarea').fill('Answer the support inbox every morning.');
    await page.locator('dialog.gs-form input[name=name]').fill('Help Desk');
    await page.locator('dialog.gs-form [type=submit]').click();
    await page.locator('dialog.gs-form a[href="#/task/t-bot"]').waitFor();
    assert.deepEqual(calls.at(-1), {p: '/api/v2/getting-started/bot', body: {what: 'Answer the support inbox every morning.', name: 'Help Desk'}});
    // Sent: Cancel becomes Done, and "Build another" starts over with an empty form.
    assert.equal(await page.locator('dialog.gs-form [data-gs-close]').textContent(), 'Done');
    await page.locator('dialog.gs-form [data-gs-another]').click();
    assert.equal(await page.locator('dialog.gs-form textarea').inputValue(), '');
    assert.equal(await page.locator('dialog.gs-form [type=submit]').isVisible(), true);
    assert.equal(await page.locator('dialog.gs-form [data-gs-close]').textContent(), 'Cancel');
    assert.equal(await page.locator('dialog.gs-form [data-gs-another]').isHidden(), true);
    await page.locator('dialog.gs-form textarea').fill('Post the weekly numbers.');
    await page.locator('dialog.gs-form [type=submit]').click();
    await page.locator('dialog.gs-form a[href="#/task/t-bot"]').waitFor();
    await page.locator('dialog.gs-form [data-gs-close]').click();
    await page.waitForFunction(() => !document.querySelector('dialog.gs-form'));

    // The dialog belongs to its page: navigating away closes it.
    await page.locator('[data-gs-item=first_bot] [data-gs-build]').click();
    await page.locator('dialog.gs-form[open]').waitFor();
    await page.evaluate(() => { location.hash = '#/bot/botops'; });
    await page.waitForFunction(() => !document.querySelector('dialog.gs-form'));
    await page.evaluate(() => { location.hash = '#/getting-started'; });

    // Hiding the checklist takes it out of the rail; it stays reachable from its address.
    await page.locator('[data-gs-hide]').click();
    await page.waitForFunction(() => document.querySelector('#nav-getting-started').hidden === false && document.querySelector('[data-gs-hide]').textContent === 'Show in the sidebar');
    await page.goto('http://tico-ui.test/#/updates');
    await page.reload();
    await page.locator('#nav-getting-started').waitFor({state: 'hidden'});
    dismissed.checklist = false;
    await page.close();

    // ---- section cards: an explanation and one first action, closable
    page = await open('#/updates');
    assert.match(await page.locator('#gs-card').textContent(), /Each bot posts a few bullets every day/);
    await page.close();
    page = await open('#/tasks');
    assert.match(await page.locator('#gs-card').textContent(), /Every task has an owner/);
    await page.locator('#gs-card [data-gs-run]').click();
    await page.locator('#task-modal[open], dialog[open]').first().waitFor();
    await page.close();

    // ---- Docs: paste where they live; each link becomes a linked doc
    page = await open('#/docs');
    await page.locator('[data-gs-card=docs]').waitFor();
    assert.match(await page.locator('[data-gs-card=docs]').textContent(), /Where do your current docs live\?/);
    assert.equal(await page.locator('[data-gs-card=docs] a[href="#/docs/new"]').count(), 1);
    assert.equal(await page.locator('[data-gs-card=docs] a[href="#/docs?import=1"]').count(), 1);
    await shot(page, 'docs-card');
    await page.locator('[data-gs-docs] [type=submit]').click();          // nothing pasted yet
    assert.match(await page.locator('[data-gs-docs] [data-gs-error]').textContent(), /Paste at least one link/);
    await page.locator('[data-gs-docs] input[name=url]').fill('https://github.com/acme/handbook');
    assert.match(await page.locator('[data-gs-kind]').textContent(), /GitHub/);
    await page.locator('[data-gs-docs] [type=submit]').click();
    await page.locator('#gs-card [role=status] a[href="#/docs"]').waitFor();
    assert.deepEqual(calls.at(-2), {p: '/api/v2/getting-started/docs', body: {links: [{url: 'https://github.com/acme/handbook', description: ''}]}});
    assert.match(await page.locator('#gs-card [role=status]').textContent(), /Linked 1 doc/);
    // ...and the server now holds it closed for this person.
    await page.waitForFunction(() => document.querySelector('#gs-card [role=status]'));
    assert.deepEqual(calls.at(-1), {p: '/api/v2/getting-started/state', body: {card: 'docs'}});
    await page.reload();
    await page.locator('#nav-getting-started').waitFor();
    await page.waitForFunction(() => document.querySelector('#gs-card').hidden);
    await page.close();

    // ---- Market: four questions, saved, research started
    page = await open('#/market');
    await page.locator('[data-gs-card=market]').waitFor();
    await page.locator('[data-gs-market] [type=submit]').click();        // the two required answers are required
    assert.equal(calls.filter(c => c.p.endsWith('/market')).length, 0);
    await page.locator('[data-gs-market] input[name=sells]').fill('Cleaning for offices');
    await page.locator('[data-gs-market] input[name=customers]').fill('Property managers');
    await page.locator('[data-gs-market] input[name=competitors]').fill('CleanCo');
    await page.locator('[data-gs-market] input[name=channels]').fill('r/propertymanagement');
    await shot(page, 'market-card');
    await page.locator('[data-gs-market] [type=submit]').click();
    // BotOps adding a bot is asked first; nothing is filed until the person says yes.
    await page.locator('#gs-card [data-gs-ask=yes]').waitFor();
    assert.match(await page.locator('#gs-card').textContent(), /Add the Market Analyst\?/);
    assert.equal(await page.locator('#gs-card [role=status]').count(), 0);
    await shot(page, 'market-confirm');
    await page.locator('#gs-card [data-gs-ask=back]').click();
    assert.equal(await page.locator('[data-gs-market] input[name=sells]').inputValue(), 'Cleaning for offices');   // Back keeps the answers
    await page.locator('[data-gs-market] [type=submit]').click();
    await page.locator('#gs-card [data-gs-ask=yes]').click();
    await page.locator('#gs-card [role=status] a[href="#/task/t-market"]').waitFor();
    const filed = calls.filter(c => c.p.endsWith('/market'));
    assert.deepEqual(filed.map(c => c.body.add_analyst), [false, false, true]);
    assert.deepEqual(filed.at(-1).body, {sells: 'Cleaning for offices', customers: 'Property managers',
      competitors: 'CleanCo', channels: 'r/propertymanagement', add_analyst: true});
    assert.match(await page.locator('#gs-card [role=status]').textContent(), /BotOps will add the Market Analyst first/);
    await page.close();

    // ---- the X is "not now": the card comes back in a new session while the section is empty
    page = await open('#/meetings');
    await page.locator('[data-gs-card=meetings]').waitFor();
    const before = calls.length;
    await page.locator('[data-gs-later=meetings]').click();
    await page.waitForFunction(() => document.querySelector('#gs-card').hidden);
    assert.equal(calls.length, before);                     // nothing is saved for a "not now"
    await page.reload();
    await page.locator('#nav-getting-started').waitFor();
    assert.equal(await page.locator('#gs-card').isHidden(), true);   // same session: still put away
    await page.close();
    page = await open('#/meetings');                        // a new page has a new session
    await page.locator('[data-gs-card=meetings]').waitFor();

    // ...and it goes on its own once the section has content.
    empty.meetings = false;
    await page.reload();
    await page.locator('#nav-getting-started').waitFor();
    await page.waitForFunction(() => document.querySelector('#gs-card').hidden);
    empty.meetings = true;
    await page.close();

    // "Don't show again" is the one the server keeps.
    page = await open('#/meetings');
    await page.locator('[data-gs-card=meetings]').waitFor();
    await page.locator('[data-gs-dismiss=meetings]').click();
    await page.waitForFunction(() => document.querySelector('#gs-card').hidden);
    assert.deepEqual(calls.at(-1), {p: '/api/v2/getting-started/state', body: {card: 'meetings'}});
    await page.reload();
    await page.locator('#nav-getting-started').waitFor();
    assert.equal(await page.locator('#gs-card').isHidden(), true);
    await page.close();

    // ---- Bots: the rail offers the two ways in until closed
    page = await open('#/updates');
    assert.equal(await page.locator('#gs-org-card [data-gs-connect]').count(), 1);
    await page.locator('#gs-org-card [data-gs-connect]').click();
    await page.locator('dialog.connect-agent[open]').waitFor();
    await page.locator('dialog.connect-agent [data-close]').click();
    await page.locator('#gs-org-card [data-gs-build]').click();
    await page.locator('dialog.gs-form[open]').waitFor();
    await page.keyboard.press('Escape');
    await page.locator('#gs-org-card [data-gs-dismiss=bots]').click();
    await page.waitForFunction(() => document.querySelector('#gs-org-card').hidden);
    await page.close();

    // ---- the tour: replay from Help, focus stays inside, Escape closes and is remembered
    page = await open('#/help');
    await page.locator('[data-gs-tour]').click();
    const tour = page.locator('.gs-tour[role=dialog][aria-modal=true]');
    await tour.waitFor();
    assert.equal(await tour.locator('.gs-tour-count').textContent(), '1 of 6');
    assert.equal(await tour.locator('#gs-tour-title').textContent(), 'Updates');
    await shot(page, 'tour');
    for (let i = 0; i < 4; i++) {
      await page.keyboard.press('Tab');
      assert.equal(await page.evaluate(() => !!document.activeElement.closest('.gs-tour')), true);
    }
    await page.keyboard.press('Shift+Tab');
    assert.equal(await page.evaluate(() => !!document.activeElement.closest('.gs-tour')), true);
    const titles = [];
    for (let i = 0; i < 5; i++) {
      await tour.locator('[data-tour-next]').click();
      titles.push(await tour.locator('#gs-tour-title').textContent());
    }
    assert.deepEqual(titles, ['Tasks', 'Your bots', 'Docs', 'Market', 'Meetings']);
    assert.equal(await tour.locator('[data-tour-next]').textContent(), 'Done');
    await page.keyboard.press('Escape');
    await tour.waitFor({state: 'detached'});
    assert.equal(await page.evaluate(() => document.body.classList.contains('drawer')), false);
    assert.deepEqual(calls.filter(c => c.body.tour).length >= 1, true);
    await page.close();

    // Someone who joins later gets the tour once, on their first visit, and not again.
    dismissed.tour = false;
    page = await open('#/updates');
    await page.locator('.gs-tour[role=dialog]').waitFor();
    await page.keyboard.press('Escape');
    await page.locator('.gs-tour').waitFor({state: 'detached'});
    await page.reload();
    await page.locator('#nav-getting-started').waitFor();
    await page.waitForTimeout(300);
    assert.equal(await page.locator('.gs-tour').count(), 0);
    await page.close();

    // Skip is the same as closing, and the tour works on a phone, through the drawer.
    page = await open('#/help', {width: 390, height: 844});
    await page.evaluate(() => window.gsStartTour());
    const phoneTour = page.locator('.gs-tour');
    await phoneTour.waitFor();
    assert.equal(await page.evaluate(() => document.body.classList.contains('drawer')), true);
    const fits = async () => page.evaluate(() => {
      const card = document.querySelector('.gs-tour-card').getBoundingClientRect(), hole = document.querySelector('.gs-tour-hole').getBoundingClientRect();
      return card.left >= 0 && card.right <= innerWidth && card.top >= 0 && card.bottom <= innerHeight && hole.width > 0
        && document.documentElement.scrollWidth <= innerWidth;
    });
    for (let i = 0; i < 6; i++) {
      assert.equal(await fits(), true);
      if (i < 5) await phoneTour.locator('[data-tour-next]').click();
    }
    await shot(page, 'tour-phone');
    await page.locator('[data-tour-skip]').click();
    await phoneTour.waitFor({state: 'detached'});
    assert.equal(await page.evaluate(() => document.body.classList.contains('drawer')), false);
    await page.close();

    assert.deepEqual(errors, []);
    console.log('PASS: getting started shows live state, files the docs and market asks, and closed cards stay closed; the tour traps focus.');
  } finally { await browser.close(); }
})().catch(e => { console.error(e); process.exitCode = 1; });
