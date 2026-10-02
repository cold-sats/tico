// Offline browser test of a chat's pinned goal and the "/" menu, against a mocked API
// (GET/POST /api/v2/conversations/{id}/goal, the watch stream's `goal` event, and `command: true` on a chat send).
// Sets a goal from the target, checks the 3-line clamp and tap to expand, pauses and clears it, sees a met goal fold
// into one line, filters and picks commands, and repeats the bar and menu at phone width.
const {chromium} = require('playwright');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const {html, uiFile} = require('./support/page.cjs');
const launch = () => chromium.launch({headless: true, channel: process.env.TICO_BROWSER_CHANNEL === undefined ? 'chrome' : process.env.TICO_BROWSER_CHANNEL || undefined});
const LONG = 'Ship the Acme onboarding checklist: write the welcome email, set up the three sample projects, '
  + 'check every link in the help pages, fix any broken ones, then post a short summary in the chat with what changed '
  + 'and what still needs a person. Keep going until all of it is done.';
const COMMANDS = [
  {name: 'goal', args: '<objective>', help: 'Pin a goal the bot works toward', kind: 'tico', sub: ['pause', 'resume', 'clear', 'edit']},
  {name: 'new', help: 'New chat', kind: 'tico'},
  {name: 'task', args: '<title>', help: 'Make a task for this bot', kind: 'tico'},
  {name: 'help', help: 'Show commands', kind: 'tico'},
  {name: 'compact', help: 'Compact the thread', kind: 'harness'},
  {name: 'model', args: '<name>', help: 'Switch model', kind: 'harness'},
];

async function open(browser, viewport, touch = false) {
  const page = await browser.newPage({viewport, serviceWorkers: 'block', ...(touch ? {hasTouch: true, isMobile: true} : {})});
  const api = {errors: [], goalPosts: [], sends: [], goal: null, streamGoal: null, page};
  page.on('pageerror', e => api.errors.push(e.message));
  const now = () => new Date().toISOString();
  await page.route('**/*', async route => {
    const req = route.request(), url = new URL(req.url()), p = url.pathname;
    const json = (body, status = 200) => route.fulfill({status, contentType: 'application/json', body: JSON.stringify(body)});
    const ui = p.match(/\/tico\/ui\/((?:app\/|styles\/)?[^/]+\.(?:js|css))$/);
    if (ui && fs.existsSync(uiFile(ui[1])))
      return route.fulfill({contentType: ui[1].endsWith('.css') ? 'text/css' : 'application/javascript', body: fs.readFileSync(uiFile(ui[1]), 'utf8')});
    if (p.endsWith('.js')) return route.fulfill({contentType: 'application/javascript', body: ''});
    if (p === '/') return route.fulfill({contentType: 'text/html', body: html});
    if (p === '/api/me') return json({id: 'ana', name: 'Ana', role: 'owner', cloud: true});
    if (p === '/api/employees') return json([{name: 'ops', display_name: 'Ops', host: 'keeper', status: 'active', can_chat: true, schedules: [], goal_active: false}]);
    if (p === '/api/issues') return json([]);
    if (p === '/api/v2/conversations')
      return json({conversations: url.searchParams.get('chat_with') ? [{id: 'c1', kind: 'chat', scope: 'personal', participants: ['human:ana', 'bot:ops']}] : []});
    if (p.endsWith('/snapshot')) return json({messages: [{id: 'm0', from_actor: 'bot:ops', body: 'Ready when you are.', created: '2026-10-01T09:00:00Z'}], execution: null});
    if (p.endsWith('/watch')) {
      const g = api.streamGoal; api.streamGoal = null;
      return route.fulfill({contentType: 'text/event-stream', body: 'retry: 200\n\n' + (g ? `event: goal\ndata: ${JSON.stringify({type: 'goal', goal: g})}\n\n` : '')});
    }
    if (p === '/api/v2/conversations/c1/goal') {
      if (req.method() === 'GET') return json({goal: api.goal, supported: true, commands: COMMANDS});
      const body = req.postDataJSON(); api.goalPosts.push(body);
      const status = {set: 'active', edit: api.goal?.status || 'active', pause: 'paused', resume: 'active', clear: 'cleared'}[body.action];
      api.goal = {id: 'g1', conversation_id: 'c1', bot: 'ops', objective: body.objective || api.goal?.objective, status, note: '',
                  set_by: 'human:ana', set_at: api.goal?.set_at || now(), updated_at: now(), ended_at: status === 'cleared' ? now() : null};
      const out = {goal: api.goal};
      if (status === 'cleared') api.goal = null;
      return json(out);
    }
    if (p === '/api/v2/chat/ops') {
      const body = req.postDataJSON(); api.sends.push(body);
      return json({conversation: {id: 'c1'}, message: {id: 'm' + api.sends.length, from_actor: 'human:ana', body: body.text, created: now()}});
    }
    return json({});
  });
  await page.goto('https://tico-ui.test/#/bot/ops');
  await page.locator('#chat-composer textarea').waitFor();
  return api;
}
const clampOf = page => page.locator('#chat-goal .cg-text').evaluate(el => {
  const cs = getComputedStyle(el), line = parseFloat(cs.lineHeight);
  return {clamp: cs.webkitLineClamp, lines: Math.round(el.clientHeight / line), cut: el.scrollHeight > el.clientHeight + 1};
});

async function desktop(browser) {
  const api = await open(browser, {width: 1280, height: 860}), {page} = api;
  const target = page.locator('#chat-composer .p-goal');
  await target.waitFor();                                         // shown: the harness supports goals
  assert.equal(await target.getAttribute('title'), 'Goal');
  assert.equal(await page.locator('#chat-goal').isHidden(), true, 'no goal, no bar');

  // Set a goal from the target.
  await target.click();
  const form = page.locator('#chat-goal textarea');
  assert.equal(await form.getAttribute('placeholder'), 'What should it get done?');
  await form.fill(LONG); await form.press('Enter');
  await page.locator('#chat-goal .cg-bar').waitFor();
  assert.deepEqual(api.goalPosts[0], {action: 'set', objective: LONG});
  assert.equal(await page.locator('#chat-goal .cg-chip').innerText(), 'Working');
  assert.match(await target.getAttribute('class'), /\bon\b/, 'the target is filled');
  await page.locator('#side .tree-goal').waitFor();               // the bot's row has the mark

  // Three lines, then tap to read it all with Edit, Pause and Clear.
  const shut = await clampOf(page);
  assert.equal(shut.clamp, '3'); assert.equal(shut.lines, 3); assert.equal(shut.cut, true, 'a long goal is cut at three lines');
  await page.locator('#chat-goal .cg-bar').click();
  assert.equal((await clampOf(page)).cut, false, 'open shows the whole goal');
  assert.deepEqual(await page.locator('#chat-goal .cg-actions button').allInnerTexts(), ['Edit', 'Pause', 'Clear']);

  await page.getByRole('button', {name: 'Pause'}).click();
  await page.locator('#chat-goal .cg-chip', {hasText: 'Paused'}).waitFor();
  assert.equal(api.goalPosts.at(-1).action, 'pause');
  await page.getByRole('button', {name: 'Resume'}).click();
  await page.locator('#chat-goal .cg-chip', {hasText: 'Working'}).waitFor();
  await page.getByRole('button', {name: 'Clear'}).click();
  await page.locator('#chat-goal').waitFor({state: 'hidden'});
  assert.equal(api.goalPosts.at(-1).action, 'clear');
  assert.doesNotMatch(await target.getAttribute('class'), /\bon\b/);
  assert.equal(await page.locator('#side .tree-goal').count(), 0);

  // The "/" menu: filter, arrows, Return picks; a harness command goes out flagged.
  const box = page.locator('#chat-composer textarea');
  await box.click(); await box.pressSequentially('/');
  const menu = page.locator('#chat-composer .slash-menu');
  await menu.waitFor();
  assert.deepEqual(await menu.locator('.slash-name').allInnerTexts(), ['/goal', '/new', '/task', '/help', '/compact', '/model']);
  await box.pressSequentially('m');
  assert.deepEqual(await menu.locator('.slash-name').allInnerTexts(), ['/model', '/compact']);
  await box.press('ArrowDown'); await box.press('Enter');
  assert.equal(await box.inputValue(), '/compact');
  assert.equal(await menu.isHidden(), true);
  await box.press('Enter');
  await page.waitForFunction(() => !document.querySelector('#chat-composer textarea').value);
  assert.deepEqual(api.sends.at(-1), {text: '/compact', refs: {}, command: true});

  // Esc closes it; an unknown command is ordinary text.
  await box.pressSequentially('/frob');
  await page.waitForTimeout(50);
  assert.equal(await menu.isHidden(), true, 'nothing matches');
  await box.pressSequentially(' the widget'); await box.press('Enter');
  await page.waitForFunction(() => !document.querySelector('#chat-composer textarea').value);
  assert.deepEqual(api.sends.at(-1), {text: '/frob the widget', refs: {}});
  await box.pressSequentially('/'); await menu.waitFor();
  await box.press('Escape');
  assert.equal(await menu.isHidden(), true);
  await box.fill('');

  // /goal <text> sets it; /goal pa + Tab picks a sub-command.
  await box.pressSequentially('/goal Clean up the Acme wiki'); await box.press('Enter');
  await page.locator('#chat-goal .cg-bar').waitFor();
  assert.deepEqual(api.goalPosts.at(-1), {action: 'set', objective: 'Clean up the Acme wiki'});
  await box.pressSequentially('/goal pa');
  assert.deepEqual(await menu.locator('.slash-name').allInnerTexts(), ['/goal pause']);
  await box.press('Tab'); assert.equal(await box.inputValue(), '/goal pause');
  await box.press('Enter');
  await page.locator('#chat-goal .cg-chip', {hasText: 'Paused'}).waitFor();

  // The stream says it was met: the bar folds into one line in the thread.
  api.streamGoal = {...api.goal, status: 'met', note: 'All pages cleaned up', updated_at: new Date(Date.now() + 1000).toISOString(), ended_at: new Date().toISOString()};
  await page.locator('#conv-thread .chat-goal-line').waitFor({timeout: 5000});
  assert.match(await page.locator('#conv-thread .chat-goal-line').innerText(), /Goal met:\s*Clean up the Acme wiki\s*· All pages cleaned up/);
  assert.equal(await page.locator('#chat-goal').isHidden(), true);
  assert.deepEqual(api.errors, []);
  console.log('desktop: ok');
  await page.close();
}

async function phone(browser) {
  const api = await open(browser, {width: 390, height: 844}, true), {page} = api;
  api.goal = null;
  const target = page.locator('#chat-composer .p-goal');
  await target.waitFor();
  const box = page.locator('#chat-composer textarea');
  // Tap a row in the "/" menu.
  await box.tap(); await box.pressSequentially('/go');
  await page.locator('#chat-composer .slash-row', {hasText: '/goal'}).first().tap();
  assert.equal(await box.inputValue(), '/goal ');
  await box.pressSequentially(LONG.slice(0, 200));
  await page.locator('#chat-composer .p-send').tap();
  await page.locator('#chat-goal .cg-bar').waitFor();
  const shut = await clampOf(page);
  assert.equal(shut.clamp, '2'); assert.equal(shut.lines, 2);
  const bar = await page.locator('#chat-goal').boundingBox(), composer = await page.locator('#chat-composer').boundingBox();
  assert.ok(bar.y < composer.y && bar.height < 80, 'a slim bar above the chat');
  assert.ok(bar.x >= 0 && bar.x + bar.width <= 390, 'inside the screen');
  await page.locator('#chat-goal .cg-bar').tap();
  await page.locator('#chat-goal .cg-actions').waitFor();
  assert.deepEqual(api.errors, []);
  console.log('phone: ok');
  await page.close();
}

(async () => {
  const browser = await launch();
  try { await desktop(browser); await phone(browser); }
  finally { await browser.close(); }
})().catch(e => { console.error(e); process.exit(1); });
