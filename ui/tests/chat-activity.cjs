// Synthetic chat activity grouping and top-boundary pagination checks. No provider or team data.
const {chromium} = require('playwright');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const {html, uiFile} = require('./support/page.cjs');

(async () => {
  const browser = await chromium.launch({headless: true, channel: process.env.TICO_BROWSER_CHANNEL === undefined ? 'chrome' : process.env.TICO_BROWSER_CHANNEL || undefined});
  try {
    const page = await browser.newPage({viewport: {width: 1100, height: 760}, serviceWorkers: 'block'}), errors = [], pages = [];
    page.on('pageerror', e => errors.push(e.message));
    const at = n => new Date(Date.UTC(2026, 9, 6, 9, n)).toISOString();
    const activity = [
      {id:'task-created',kind:'notice',from_actor:'keeper',body:'New task from Head of Engineering: Review the next release',created:at(1),refs:{task:'task-1'}},
      {id:'note-one',kind:'say',from_actor:'bot:ops',body:'Cloud transcript shows performance goal. https://example.test/audit',created:at(2),refs:{task:'task-1',note:true}},
      {id:'task-status',kind:'notice',from_actor:'keeper',body:'Open: Review the next release',created:at(3),refs:{task:'task-1'}},
      {id:'note-two',kind:'say',from_actor:'bot:ops',body:'Reviewed the status note.',created:at(4),refs:{task:'task-1',note:true}},
    ];
    // Similar words and even a note ref do not turn human-authored prose into generated activity.
    const latest = [
      ...activity,
      {id:'human-quote',kind:'say',from_actor:'human:ana',body:'New task from Head of Engineering is only a quote here.',created:at(5),refs:{}},
      {id:'human-note',kind:'say',from_actor:'human:ana',body:'Note Cloud transcript shows performance goal.',created:at(6),refs:{task:'task-1',note:true}},
      {id:'bot-prose',kind:'say',from_actor:'bot:ops',body:'Note: I checked the release page.',created:at(7),refs:{task:'task-1'}},
      ...Array.from({length:12}, (_, i) => ({id:`chat-${i}`,kind:'say',from_actor:i % 2 ? 'bot:ops' : 'human:ana',body:`Regular conversation ${i}`,created:at(8+i),refs:{}})),
    ];
    const endedGoal = {id:'goal-ended',conversation_id:'c-ops',bot:'ops',objective:'Ship the finished update',status:'met',note:'Reviewed',ended_at:at(4.5),updated_at:at(4.5)};
    const snapshot = {messages: latest, next_before: 'cursor-1', execution: null, goal: endedGoal};
    await page.route('**/*', route => {
      const url = new URL(route.request().url()), p = url.pathname;
      const json = body => route.fulfill({contentType:'application/json',body:JSON.stringify(body)});
      if (p === '/') return route.fulfill({contentType:'text/html',body:html});
      const ui = p.match(/\/tico\/ui\/((?:app\/|styles\/)?[^/]+\.(?:js|css))$/);
      if (ui && fs.existsSync(uiFile(ui[1]))) return route.fulfill({contentType:ui[1].endsWith('.css')?'text/css':'application/javascript',body:fs.readFileSync(uiFile(ui[1]),'utf8')});
      if (/\/marked\.min\.js$/.test(p)) return route.fulfill({contentType:'application/javascript',body:fs.readFileSync(uiFile('vendor/marked.min.js'),'utf8')});
      if (p === '/api/me') return json({id:'ana',name:'Ana',role:'owner',cloud:true});
      if (p === '/api/employees') return json([{name:'ops',display_name:'Ops',host:'keeper',status:'active',can_chat:true,schedules:[]}]);
      if (p === '/api/issues') return json([]);
      if (p.endsWith('/watch')) return route.fulfill({contentType:'text/event-stream',body:`event: snapshot\ndata: ${JSON.stringify(snapshot)}\n\n`});
      if (p === '/api/v2/conversations') return json({conversations:[{id:'c-ops',kind:'chat',scope:'personal',participants:['human:ana','bot:ops']}]});
      if (p === '/api/v2/conversations/c-ops/snapshot') return json(snapshot);
      if (p === '/api/v2/conversations/c-ops/messages') {
        const cursor = url.searchParams.get('before'); pages.push(cursor);
        return json(cursor === 'cursor-1'
          ? {messages:[{id:'older-a',kind:'say',from_actor:'human:ana',body:'Earlier question',created:at(0),refs:{}}],next_before:'cursor-2'}
          : {messages:[{id:'older-b',kind:'say',from_actor:'bot:ops',body:'Earlier answer',created:at(-1),refs:{}}],next_before:null});
      }
      if (p === '/api/v2/conversations/c-ops/goal') return json({goal:endedGoal,supported:true,commands:[]});
      return json({});
    });
    await page.goto('https://tico-ui.test/#/bot/ops/chat');
    await page.waitForFunction(() => V2C?.rendered && V2C.loaded);

    const thread = page.locator('#conv-thread'), disclosure = page.locator('#conv-thread details.chat-activity'), summary = disclosure.locator('> summary');
    assert.equal(await disclosure.count(), 1, 'consecutive typed task and note records share one row');
    assert.match(await summary.innerText(), /4 task and status updates/);
    assert.equal(await disclosure.evaluate(el => el.open), false, 'activity starts collapsed');
    assert.equal(await thread.locator('.chat-goal-line').count(), 1, 'the ended goal is not absorbed into the activity row');
    const topOrder = await thread.evaluate(el => [...el.children].filter(x => x.matches('.chat-activity,.chat-goal-line'))
      .map(x => x.classList.contains('chat-activity') ? 'activity' : 'goal'));
    assert.deepEqual(topOrder.slice(0,2), ['activity','goal'], 'goal-line insertion stays after grouped activity');
    assert.equal(await thread.locator('.bubble').count(), 15, 'ordinary chat remains in its own messages');
    assert.match(await thread.innerText(), /New task from Head of Engineering is only a quote here/);
    assert.match(await thread.innerText(), /Note Cloud transcript shows performance goal\./);
    assert.match(await thread.innerText(), /Note: I checked the release page\./);

    await summary.focus(); await page.keyboard.press('Enter');
    await page.waitForFunction(() => document.querySelector('#conv-thread details.chat-activity')?.open);
    await page.evaluate(() => v2ChatRender(V2C));
    await page.waitForFunction(() => document.querySelector('#conv-thread details.chat-activity')?.open);
    assert.match(await disclosure.innerText(), /New task from Head of Engineering: Review the next release/);
    assert.match(await disclosure.innerText(), /Cloud transcript shows performance goal\./);
    const note = disclosure.locator('.chat-activity-items > details.chat-fold').first();
    await note.locator('> summary').focus(); await page.keyboard.press('Enter');
    await note.locator('a[href="https://example.test/audit"]').waitFor();
    assert.equal(await disclosure.locator('time').count(), 6, 'summary and all original activity entries retain their timestamps');
    await summary.focus(); await page.keyboard.press('Enter');
    await page.waitForFunction(() => !document.querySelector('#conv-thread details.chat-activity')?.open);

    const older = page.locator('#conv-older'), button = older.locator('[data-cloud-older]');
    assert.equal(await older.isHidden(), true, 'older history control stays away from the latest messages');
    await thread.evaluate(el => { el.scrollTop = 0; });
    await page.waitForFunction(() => !document.querySelector('#conv-older').hidden);
    const anchorBefore = await page.evaluate(() => {
      const t = document.querySelector('#conv-thread'), a = t.querySelector('details.chat-activity').getBoundingClientRect();
      return a.top - t.getBoundingClientRect().top;
    });
    await button.focus(); await page.keyboard.press('Enter');
    await page.waitForFunction(() => V2C.messages.some(m => m.id === 'older-a'));
    assert.deepEqual(pages, ['cursor-1'], 'keyboard activation requests the server cursor');
    const anchorAfter = await page.evaluate(() => {
      const t = document.querySelector('#conv-thread'), a = t.querySelector('details.chat-activity').getBoundingClientRect();
      return a.top - t.getBoundingClientRect().top;
    });
    assert.ok(Math.abs(anchorAfter - anchorBefore) <= 2, 'prepending keeps the previous content anchored');
    assert.equal(await older.isHidden(), true, 'after prepending, control hides while reading away from the top');
    const secondTop = await thread.evaluate(el => { el.scrollTop = 0; return el.scrollTop; });
    assert.equal(secondTop, 0);
    await page.waitForFunction(() => !document.querySelector('#conv-older').hidden);
    await older.locator('[data-cloud-older]').click();
    await page.waitForFunction(() => V2C.messages.some(m => m.id === 'older-b'));
    assert.deepEqual(pages, ['cursor-1','cursor-2']);
    await page.waitForFunction(() => document.querySelector('#conv-older').hidden);
    assert.equal(await page.locator('#conv-older [data-cloud-older]').count(), 0, 'no control remains after history is exhausted');
    assert.deepEqual(errors, []);
    console.log('chat activity grouping and top-only older control: ok');
  } finally { await browser.close(); }
})().catch(e => { console.error(e); process.exit(1); });
