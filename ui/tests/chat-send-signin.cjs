// A sign-in return must not refill confirmed chat text from its saved restoration snapshot.
// All requests and sign-in pages are synthetic; the real UI, navigation and browser storage run unchanged.
const {chromium, webkit} = require('playwright');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const {html, uiFile} = require('./support/page.cjs');
const {unrouted} = require('./support/routes.cjs');
const engines = (process.env.TICO_UI_ENGINES || 'chromium,webkit').split(',');

async function scenario(browser, mode, edit) {
  const page = await browser.newPage({viewport: {width: 1200, height: 800}, serviceWorkers: 'block'});
  const errors = [], posts = [], delivered = [];
  page.on('pageerror', e => errors.push(e.message));
  let expired = false, hold = null, release;
  await page.route('**/*', async route => {
    const url = new URL(route.request().url()), p = url.pathname;
    const json = (body, status = 200) => route.fulfill({status, contentType: 'application/json', body: JSON.stringify(body)});
    const identity = () => json({error: {code: 'identity', detail: 'Sign in again', sign_in: '/auth/login'}}, 401);
    if (p === '/auth/login') return route.fulfill({contentType: 'text/html',
      body: '<title>Fixture sign-in</title><a id="return" href="' + url.searchParams.get('next') + '">Return after sign-in</a>'});
    const ui = p.match(/\/tico\/ui\/((?:app\/|styles\/)?[^/]+\.(?:js|css))$/);
    if (ui && fs.existsSync(uiFile(ui[1]))) return route.fulfill({
      contentType: ui[1].endsWith('.css') ? 'text/css' : 'application/javascript', body: fs.readFileSync(uiFile(ui[1]), 'utf8')});
    if (p.endsWith('.js')) return route.fulfill({contentType: 'application/javascript', body: ''});
    if (p === '/') return route.fulfill({contentType: 'text/html', body: html});
    if (p === '/api/v2/me' && expired) return identity();
    if (p === '/api/me' || p === '/api/v2/me') return json({id: 'ana', name: 'Ana', role: 'owner', cloud: true});
    if (p === '/api/employees') return json([{name: 'botops', display_name: 'BotOps', host: 'keeper', status: 'active', can_chat: true, schedules: []}]);
    if (p === '/api/issues') return json([]);
    if (p === '/api/v2/conversations') return json({conversations: url.searchParams.get('chat_with')
      ? [{id: 'c1', kind: 'chat', scope: 'personal', participants: ['human:ana', 'bot:botops']}] : []});
    if (p.endsWith('/snapshot')) return json({messages: delivered, execution: null});
    if (p === '/api/v2/events' || p.endsWith('/watch')) return route.fulfill({contentType: 'text/event-stream', body: ': fixture\n\n'});
    if (p === '/api/v2/chat/botops') {
      assert.equal(route.request().method(), 'POST');
      const text = route.request().postDataJSON().text;
      posts.push(text);
      if (posts.length === 1) {
        if (mode === 'timeout') return; // the client must end the unanswered send itself
        expired = true;
        return identity();
      }
      if (hold) await hold;
      const message = {id: 'm' + posts.length, from_actor: 'human:ana', body: text, created: new Date().toISOString()};
      delivered.push(message);
      return json({conversation: {id: 'c1'}, message});
    }
    return json(unrouted(p));
  });
  const box = page.locator('#chat-composer textarea'), send = page.locator('#chat-composer .p-send');
  const stored = () => page.evaluate(() => ({draft: chatDrafts().botops,
    fields: JSON.parse(sessionStorage.getItem(SESSION_RETURN) || 'null')?.fields || []}));
  const frames = () => page.evaluate(() => new Promise(done => requestAnimationFrame(() => requestAnimationFrame(done))));
  const text = '  Keep this draft through sign-in  ';
  try {
    await page.goto('https://tico-ui.test/#/bot/botops');
    await page.waitForFunction(() => typeof V2C !== 'undefined' && V2C?.loaded && SESSION.seen);
    await box.fill(text);
    if (mode !== 'unsent') {
      if (mode === 'timeout') await page.evaluate(() => { CHAT_SEND.timeout = 250; });
      await send.click();
      await page.waitForFunction(() => !BOT_PILL.sending);
      if (mode === 'timeout') {
        await page.locator('.toast.err').waitFor();
        expired = true;
        await page.evaluate(() => get('/v2/me').catch(() => {}));
      }
    } else {
      expired = true;
      await page.evaluate(() => get('/v2/me').catch(() => {}));
    }
    await page.locator('#signed-out:not([hidden])').waitFor();
    assert.equal(await box.inputValue(), text, 'sign-out keeps the unsent text');
    await page.click('#signed-out button');
    await page.waitForURL('**/auth/login**');
    expired = false;
    await page.click('#return');
    await page.waitForURL('https://tico-ui.test/#/bot/botops');
    await page.waitForFunction(() => typeof V2C !== 'undefined' && V2C?.loaded);
    assert.equal(await box.inputValue(), text, 'return restores the draft');
    assert.ok((await stored()).fields.some(f => f.value === text), 'the return snapshot still holds a copy beside the restored local draft');

    if (mode !== 'unsent') {
      if (edit) hold = new Promise(done => release = done);
      await send.click();
      await page.waitForFunction(() => BOT_PILL.sending || !document.querySelector('#chat-composer textarea').value);
      const next = 'Next draft typed while the resend is out';
      if (edit) {
        await box.fill(next);
        release(); hold = null;
      }
      await page.waitForFunction(() => !BOT_PILL.sending);
      await frames(); // let the sign-in return watcher respond to the send's DOM changes
      assert.equal(await box.inputValue(), edit ? next : '', 'confirmed text never comes back; later edits stay');
      const saved = await stored();
      assert.equal(saved.draft, edit ? next : undefined, 'the persistent bot draft agrees with the composer');
      assert.ok(!saved.fields.some(f => f.value === text), 'the saved sign-in snapshot consumed the confirmed text');
      assert.equal(delivered.length, 1, 'one successful delivery');
      if (!edit) {
        assert.equal(await send.evaluate(button => getComputedStyle(button).opacity), '0.45', 'the empty composer dims Send');
        await box.press('Enter');
        await send.evaluate(button => button.click());
        await frames();
      }
      assert.equal(posts.length, 2, 'the interrupted attempt and explicit resend are the only POSTs');
      await page.reload();
      await page.waitForFunction(() => typeof V2C !== 'undefined' && V2C?.loaded);
      await frames();
      assert.equal(await box.inputValue(), edit ? next : '', 'a later reload cannot revive confirmed text');
      assert.equal(posts.length, 2, 'reload sends nothing');
    } else {
      await page.reload();
      await page.waitForFunction(() => typeof V2C !== 'undefined' && V2C?.loaded);
      assert.equal(await box.inputValue(), text, 'an existing draft never sent survives return and another reload');
      assert.equal(posts.length, 0, 'an unsent draft makes no POST');
    }
    assert.deepEqual(errors, [], 'no browser errors');
    console.log('ok -', mode, edit ? 'preserves later edits' : 'sign-in return');
  } finally { release?.(); await page.close(); }
}

(async () => {
  for (const engine of engines) {
    const browser = await ({chromium, webkit}[engine]).launch({headless: true,
      ...(engine === 'chromium' ? {channel: process.env.TICO_BROWSER_CHANNEL === undefined ? 'chrome' : process.env.TICO_BROWSER_CHANNEL || undefined} : {})});
    try {
      await scenario(browser, '401', false);
      await scenario(browser, 'timeout', false);
      await scenario(browser, '401', true);
      await scenario(browser, 'unsent', false);
      console.log('ok - chat send sign-in:', engine);
    } finally { await browser.close(); }
  }
})().catch(error => { console.error(error); process.exit(1); });
