// Offline browser regression: typing into a bot's composer while its conversation is still loading.
// The bot page redraws (a re-route) and the held snapshot lands after Return; the typed text and the
// cursor survive the redraw, Return sends once, and the late snapshot does not wipe the sent message.
// Second, the way a person meets it: from another page a hash change opens the bot, its stream's snapshots land on
// their own schedule, the box is clicked after a few seconds and 250 characters are typed; a snapshot the server built
// before the send (a lagging stream) arrives afterwards and must not take the message off the page.
const {chromium} = require('playwright');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const {html, uiFile} = require('./support/page.cjs');
const launch = () => chromium.launch({headless: true, channel: process.env.TICO_BROWSER_CHANNEL === undefined ? 'chrome' : process.env.TICO_BROWSER_CHANNEL || undefined});
async function whileLoading(browser) {
    const page = await browser.newPage({viewport: {width: 1200, height: 800}, serviceWorkers: 'block'});
    const errors = [], sends = [];
    page.on('pageerror', e => errors.push(e.message));
    let release; const snapshotHeld = new Promise(done => release = done);
    await page.route('**/*', async route => {
      const url = new URL(route.request().url()), p = url.pathname;
      const json = body => route.fulfill({contentType: 'application/json', body: JSON.stringify(body)});
      const ui = p.match(/\/tico\/ui\/((?:app\/|styles\/)?[^/]+\.(?:js|css))$/);
      if (ui && fs.existsSync(uiFile(ui[1])))
        return route.fulfill({contentType: ui[1].endsWith('.css') ? 'text/css' : 'application/javascript', body: fs.readFileSync(uiFile(ui[1]), 'utf8')});
      if (p.endsWith('.js')) return route.fulfill({contentType: 'application/javascript', body: ''});
      if (p === '/') return route.fulfill({contentType: 'text/html', body: html});
      if (p === '/api/me') return json({id: 'ana', name: 'Ana', role: 'owner', cloud: true});
      if (p === '/api/employees') return json([{name: 'botops', display_name: 'BotOps', host: 'keeper', status: 'active', can_chat: true, schedules: []}]);
      if (p === '/api/issues') return json([]);
      if (p === '/api/v2/conversations')
        return json({conversations: url.searchParams.get('chat_with') ? [{id: 'c1', kind: 'chat', scope: 'personal', participants: ['human:ana', 'bot:botops']}] : []});
      if (p.endsWith('/snapshot')) { await snapshotHeld; return json({messages: [], execution: null}); }   // the slow, empty load
      if (p.endsWith('/watch')) return route.fulfill({contentType: 'text/event-stream', body: ': fixture\n\n'});
      if (p === '/api/v2/chat/botops') {
        sends.push(route.request().postDataJSON().text);
        return json({conversation: {id: 'c1'}, message: {id: 'm1', from_actor: 'human:ana', body: sends[0], created: new Date().toISOString()}});
      }
      return json({});
    });
    await page.goto('https://tico-ui.test/#/bot/botops');
    const box = page.locator('#chat-composer textarea');
    await box.waitFor();
    assert.match(await page.locator('#conv-thread').innerText(), /Loading the thread/, 'still loading');
    const text = 'A long message typed before the conversation finished loading';
    await box.click(); await box.pressSequentially(text);
    // The page redraws under the cursor.
    await page.evaluate(() => { BOT = null; route(); });
    assert.equal(await box.inputValue(), text, 'the text survives the redraw');
    assert.equal(await page.evaluate(() => document.activeElement === document.querySelector('#chat-composer textarea')), true, 'the cursor stays in the box');
    await page.keyboard.press('Enter');
    await page.waitForFunction(() => !document.querySelector('#chat-composer textarea').value);
    assert.deepEqual(sends, [text], 'Return sends it once');
    release();                                       // the load that started before the send finishes
    await page.waitForFunction(() => V2C.loaded);
    const thread = await page.locator('#conv-thread').innerText();
    assert.match(thread, /A long message typed/, 'the sent message stays in the chat');
    assert.doesNotMatch(thread, /Nothing yet/);
    assert.deepEqual(errors, []);
    console.log('typing while loading: ok');
    await page.close();
}
async function afterHashNav(browser) {
  const page = await browser.newPage({viewport: {width: 1200, height: 800}, serviceWorkers: 'block'});
  // Observe real EventSource delivery, and hold the current snapshot until the stale one is checked.
  await page.addInitScript(() => {
    window.fixtureSnapshots = [];
    const NativeEventSource = window.EventSource;
    window.EventSource = class extends NativeEventSource {
      constructor(...args) {
        super(...args);
        this.addEventListener('snapshot', event => window.fixtureSnapshots.push(JSON.parse(event.data).fixture_phase));
      }
    };
  });
  const errors = [], sends = [];
  page.on('pageerror', e => errors.push(e.message));
  const now = () => new Date().toISOString();
  let server = [{id: 'old', from_actor: 'bot:botops', body: 'Welcome back', created: '2026-01-01T00:00:00Z'}], watches = 0, sentAt = 0;
  let releaseCurrent;
  const currentHeld = new Promise(done => releaseCurrent = done);
  let releaseSend, initialWatches = 0;
  const sendHeld = new Promise(done => releaseSend = done);
  await page.route('**/*', async route => {
    const url = new URL(route.request().url()), p = url.pathname;
    const json = body => route.fulfill({contentType: 'application/json', body: JSON.stringify(body)});
    const ui = p.match(/\/tico\/ui\/((?:app\/|styles\/)?[^/]+\.(?:js|css))$/);
    if (ui && fs.existsSync(uiFile(ui[1])))
      return route.fulfill({contentType: ui[1].endsWith('.css') ? 'text/css' : 'application/javascript', body: fs.readFileSync(uiFile(ui[1]), 'utf8')});
    if (p.endsWith('.js')) return route.fulfill({contentType: 'application/javascript', body: ''});
    if (p === '/') return route.fulfill({contentType: 'text/html', body: html});
    if (p === '/api/me') return json({id: 'ana', name: 'Ana', role: 'owner', cloud: true});
    if (p === '/api/employees') return json([{name: 'botops', display_name: 'BotOps', host: 'keeper', status: 'active', can_chat: true, schedules: []}]);
    if (p === '/api/issues') return json([]);
    if (p === '/api/v2/conversations')
      return json({conversations: url.searchParams.get('chat_with') ? [{id: 'c1', kind: 'chat', scope: 'personal', participants: ['human:ana', 'bot:botops']}] : []});
    if (p.endsWith('/snapshot')) return json({messages: server.slice(), execution: null});
    if (p.endsWith('/watch')) {
      // Each connection opens with a snapshot. The first one after the send was built just before it landed.
      if (!sentAt && initialWatches++ >= 2) await sendHeld;
      const lagging = sentAt && !watches++ ;
      const phase = sentAt ? lagging ? 'lagging' : 'current' : 'initial';
      if (phase === 'current') await currentHeld;
      const body = 'retry: 50\nevent: snapshot\ndata: ' + JSON.stringify({messages: lagging ? server.slice(0, 1) : server.slice(),
        execution: null, fixture_phase: phase}) + '\n\n';
      return route.fulfill({contentType: 'text/event-stream', body});
    }
    if (p === '/api/v2/chat/botops') {
      sends.push(route.request().postDataJSON().text);
      const message = {id: 'm1', from_actor: 'human:ana', body: sends[0], created: now()};
      server = [...server, message]; sentAt = Date.now(); watches = 0;
      releaseSend();
      return json({conversation: {id: 'c1'}, message});
    }
    return json({});
  });
  await page.goto('https://tico-ui.test/#/settings');
  await page.locator('#settings-tabs').waitFor();
  await page.evaluate(() => { location.hash = '#/bot/botops'; });
  const box = page.locator('#chat-composer textarea');
  await box.waitFor();
  await page.waitForFunction(() => window.fixtureSnapshots.filter(phase => phase === 'initial').length >= 2);
  const text = 'Please set up a bot for our support inbox. '.repeat(6).slice(0, 250);
  await box.click(); await box.pressSequentially(text);
  assert.equal(await box.inputValue(), text, 'everything typed is in the box');
  await page.keyboard.press('Enter');
  await page.waitForFunction(() => !document.querySelector('#chat-composer textarea').value);
  assert.deepEqual(sends, [text], 'Return sends it once');
  await page.waitForFunction(() => window.fixtureSnapshots.includes('lagging'));
  assert.match(await page.locator('#conv-thread').innerText(), /Please set up a bot/, 'the sent message stays in the chat');
  releaseCurrent();
  await page.waitForFunction(() => window.fixtureSnapshots.includes('current'));
  const thread = await page.locator('#conv-thread').innerText();
  assert.equal((thread.match(/Please set up a bot/g) || []).length > 0, true);
  assert.equal(await page.locator('#conv-thread .bubble.you').count(), 1, 'listed once, not twice');
  assert.deepEqual(errors, []);
  console.log('hash navigation, typing after the snapshots: ok');
  await page.close();
}
(async () => {
  const browser = await launch();
  try { await whileLoading(browser); await afterHashNav(browser); console.log('ok'); }
  finally { await browser.close(); }
})().catch(e => { console.error(e); process.exit(1); });
