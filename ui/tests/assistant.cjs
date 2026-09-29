// The Assistant (ui/assistant.js): its tab is first on your own person page and absent from anyone
// else's, "Ask the Assistant…" in search (⌘K) opens the same chat with your words in the box, a lookup
// answers at once with in-app links, a proposal is a Confirm / Cancel card that only your click runs,
// and it all fits a phone. Fixtures only, no network.
const {chromium} = require('playwright');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const html = fs.readFileSync(path.join(__dirname, '../index.html'), 'utf8');

const now = new Date().toISOString();
const msg = (id, from, body, refs = {}) => ({id, from_actor: from, body, refs, created: now, kind: 'say'});

async function open(browser, viewport, state) {
  const page = await browser.newPage({viewport, serviceWorkers: 'block', hasTouch: viewport.width < 760});
  const errors = [];
  page.on('pageerror', error => errors.push(error.message));
  await page.route('**/*', route => {
    const url = new URL(route.request().url()), p = url.pathname, method = route.request().method();
    const json = body => route.fulfill({contentType: 'application/json', body: JSON.stringify(body)});
    if (/\/marked\.min\.js$/.test(p)) return route.fulfill({contentType: 'application/javascript', body: 'window.marked={parse:s=>String(s)}'});
    if (url.origin !== 'https://tico-ui.test') return route.abort();
    const ui = p.match(/\/tico\/ui\/([^/]+\.js)$/);
    if (ui && fs.existsSync(path.join(__dirname, '..', ui[1]))) return route.fulfill({contentType: 'application/javascript', body: fs.readFileSync(path.join(__dirname, '..', ui[1]), 'utf8')});
    if (p === '/') return route.fulfill({contentType: 'text/html', body: html});
    if (p === '/api/me') return json({id: 'ana', role: 'owner', name: 'Ana', email: 'ana@example.test', cloud: true});
    if (p === '/api/people') return json({people: [{id: 'ana', name: 'Ana'}, {id: 'ben', name: 'Ben'}]});
    if (p === '/api/employees') return json([]);
    if (p === '/api/status') return json({cloud: true, active: [], queued: [], recent_runs: [], keeper_alive: true, health_issues: [], schedules: []});
    if (p === '/api/v2/status') return json({bots: []});
    if (p === '/api/v2/goals') return json({goals: [], chain: [], reports: [], company: []});
    if (p === '/api/v2/updates') return json({updates: [], missed: [], unread: 0, next_before: null, today: {}});
    if (p === '/api/v2/tasks') return json({tasks: []});
    if (p === '/api/v2/conversations') return json({conversations: []});
    if (p === '/api/v2/assistant' && method === 'GET') { state.reads++; return json(state.view()); }
    if (p === '/api/v2/assistant/messages') {
      state.sent.push(JSON.parse(route.request().postData()).text);
      return json(state.reply());
    }
    const act = p.match(/^\/api\/v2\/assistant\/actions\/([^/]+)\/(confirm|cancel)$/);
    if (p === '/api/v2/assistant/turn-on') { state.turnedOn = (state.turnedOn || 0) + 1; return json({bot: 'coo', state: 'active', restored: true, placed: true}); }
    if (act) { state.decided.push([act[1], act[2]]); state.card.status = act[2] === 'confirm' ? 'done' : 'cancelled'; return json({action: state.card}); }
    if (p.endsWith('/watch')) return route.fulfill({contentType: 'text/event-stream', body: ': fixture\n\n'});
    return json({});
  });
  return {page, errors};
}

function fixture() {
  const state = {reads: 0, sent: [], decided: [], messages: [], card: null};
  state.card = {id: 'act1', summary: 'Archive the Ops bot', method: 'POST', path: '/api/v2/bots/ops/archive', status: 'pending', result: null,
    description: 'Archive bot Ops', diff: [], body: {expected_revision: 3, text: 'Long message. '.repeat(30) + 'THE-END'}, proposed_via: 'assistant'};
  state.view = () => ({available: true, state: 'active', bot: 'coo', name: 'Tico', can_turn_on: false, room_id: 'room1',
    messages: state.messages, has_more: false, next_before: null, execution: null, actions: {act1: state.card}, pending: []});
  state.reply = () => {
    const user = msg('u' + state.sent.length, 'human:ana', state.sent.at(-1));
    const bot = msg('b' + state.sent.length, 'bot:coo', '1 thing waiting on you:\n- Task: [Pick a launch date](#/task/t1)', {fast: true});
    state.messages.push(user, bot);
    return {message: user, reply: bot, fast: true, intent: 'waiting'};
  };
  return state;
}

(async () => {
  const browser = await chromium.launch({headless: true, channel: process.env.TICO_BROWSER_CHANNEL === undefined ? 'chrome' : process.env.TICO_BROWSER_CHANNEL || undefined});
  try {
    for (const [tag, viewport] of [['desktop', {width: 1280, height: 900}], ['phone', {width: 390, height: 800}]]) {
      const state = fixture();
      state.messages.push(msg('m0', 'bot:coo', 'I can archive it.'), msg('m1', 'bot:coo', 'Needs your OK: Archive the Ops bot', {action: 'act1'}));
      const {page, errors} = await open(browser, viewport, state);

      // Your own page: Assistant first, before Profile.
      await page.goto('https://tico-ui.test/#/person/ana');
      await page.locator('#ptabs button').first().waitFor();
      assert.deepEqual(await page.locator('#ptabs button').allInnerTexts(), ['Assistant', 'Profile', 'Slack'], tag + ': Assistant is first on your own page');
      // Someone else's page has no Assistant tab.
      await page.goto('https://tico-ui.test/#/person/ben');
      await page.locator('#ptabs button').first().waitFor();
      assert.deepEqual(await page.locator('#ptabs button').allInnerTexts(), ['Profile', 'Slack'], tag + ': no Assistant on another person\'s page');
      assert.equal(await page.locator('#assistant-chat').count(), 0, tag + ': no Assistant pane there');

      // The global entry: search, type, Enter, and the same chat opens with the words in the box.
      await page.keyboard.press('Control+k');
      await page.locator('#search-input').fill('what is waiting on me');
      const ask = page.locator('#search-results li[data-ask]');
      await ask.waitFor();
      assert.match(await ask.innerText(), /Ask the Assistant…/, tag + ': search offers the Assistant');
      await page.keyboard.press('Enter');
      await page.locator('[data-assistant] textarea').waitFor();
      assert.match(page.url(), /#\/person\/ana\/assistant$/, tag + ': it opens your Assistant');
      assert.equal(await page.locator('[data-assistant] textarea').inputValue(), 'what is waiting on me', tag + ': prefilled');

      // The card: only a click runs it.
      const card = page.locator('.asst-card[data-action="act1"]');
      await card.waitFor();
      assert.equal(await card.locator('[data-what]').innerText(), 'Archive bot Ops', tag + ': the server\'s description leads');
      assert.match(await card.locator('.asst-body').innerText(), /expected_revision: 3/, tag + ': the body is shown');
      assert.ok((await card.locator('.asst-long').innerHTML()).includes('THE-END') && await card.locator('.asst-long summary span').innerText() === 'Show more', tag + ': a long value is whole, behind Show more');
      assert.equal(state.decided.length, 0, tag + ': nothing ran before the click');
      await card.locator('[data-confirm]').click();
      await page.locator('.asst-card[data-status="done"]').waitFor();
      assert.deepEqual(state.decided, [['act1', 'confirm']], tag + ': the click confirmed it');

      // Send: a lookup answers at once, with a link that opens in the app.
      await page.locator('[data-assistant] textarea').press('Enter');
      const link = page.locator('.asst-msg.bot a[href="#/task/t1"]');
      await link.waitFor();
      assert.deepEqual(state.sent, ['what is waiting on me'], tag + ': sent once');
      assert.equal(await page.locator('[data-thinking]').count(), 0, tag + ': a fast answer has no thinking state');

      // It fits: no sideways scroll, the box and Send are on screen.
      const box = await page.locator('[data-assistant] textarea').boundingBox();
      assert.ok(box && box.x >= 0 && box.x + box.width <= viewport.width + 1, tag + ': the box fits the width');
      assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth + 1), tag + ': no horizontal scroll');
      const send = await page.locator('[data-assistant] button[type=submit]').boundingBox();
      assert.ok(send && send.x + send.width <= viewport.width + 1, tag + ': Send fits');
      assert.deepEqual(errors, [], tag + ': no page errors');
      await page.close();
    }

    // Off: the tab says so, and only the owner is offered the switch.
    const state = fixture();
    state.view = () => ({available: false, state: 'archived', bot: 'coo', name: 'Tico', can_turn_on: true, room_id: null,
      messages: [], has_more: false, next_before: null, execution: null, actions: {}, pending: []});
    const {page} = await open(browser, {width: 1280, height: 900}, state);
    await page.goto('https://tico-ui.test/#/person/ana/assistant');
    await page.locator('[data-turn-on]').waitFor();
    assert.match(await page.locator('.asst-off').innerText(), /is off/);
    assert.equal(await page.locator('[data-assistant] textarea').count(), 0, 'no chat while it is off');
    // The owner is offered the same switch in Settings > Bots, and one click turns it on.
    await page.goto('https://tico-ui.test/#/settings');
    await page.locator('[data-settings-tab="bots"]').click();
    const strip = page.locator('[data-assistant-off]');
    await strip.waitFor();
    state.view = () => ({available: true, state: 'active', bot: 'coo', name: 'Tico', can_turn_on: false, room_id: 'room1',
      messages: [], has_more: false, next_before: null, execution: null, actions: {}, pending: []});
    await strip.locator('[data-turn-on]').click();
    await page.locator('[data-assistant-off]').waitFor({state: 'detached'});
    assert.equal(state.turnedOn, 1, 'Turn on Assistant asked the server once');
  } finally { await browser.close(); }
})().catch(error => { console.error(error); process.exit(1); });
