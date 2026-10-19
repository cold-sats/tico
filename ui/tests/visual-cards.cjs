// Visuals in replies (Visual replies 2/4): pictures, SVG and visual pages show as cards under a chat message and a
// task comment, from the sign-in-free visual address only; pages run in the agreed sandbox with the server's real
// content policy and height reporter (backend/visuals.py); cap of 4, removed, newer version, failure, Expand, phone.
// Fixtures only.
const {chromium, webkit} = require('playwright');
const assert = require('node:assert/strict');
const path = require('node:path');
const {execFileSync} = require('node:child_process');
const {html, uiFile} = require('./support/page.cjs');
const {unrouted} = require('./support/routes.cjs');
const fs = require('node:fs');

const ROOT = path.resolve(__dirname, '..', '..');
// The server's own page treatment: cleaned, the height reporter added, and its content policy.
const server = JSON.parse(execFileSync('python3', ['-I', '-c', `
import json, sys
sys.path.insert(0, ${JSON.stringify(ROOT)})
from backend import visuals
pages = json.loads(sys.stdin.read())
out = {"policy": visuals.policy("page", ["https://tico-ui.test"]), "svg_policy": visuals.policy("svg", ["https://tico-ui.test"]), "pages": {}}
for name, (raw, clean) in pages.items():
    data = raw.encode()
    if clean:
        data, _ = visuals.clean(data, "page")
    out["pages"][name] = visuals.with_reporter(data).decode()
print(json.dumps(out))
`], {input: JSON.stringify({
  short: ['<!doctype html><html><head><title>Short</title></head><body style="margin:0"><h1 style="margin:0;height:150px">Short page</h1>'
    + '<a id="out" href="https://outside.test/read">Read more</a></body></html>', true],
  tall: ['<!doctype html><html><body style="margin:0"><div style="height:2000px;background:linear-gradient(#0a0,#00a)">Tall page</div></body></html>', true],
  // Sized by the screen, not by their content: one as tall as the frame, one always taller than it (a heading, then
  // min-height 100dvh, inside the default margins).
  vh: ['<!doctype html><html><body style="margin:0"><div style="height:100vh;overflow:hidden;background:#0a0">Full screen</div></body></html>', true],
  dvh: ['<!doctype html><html><body><h1>Report</h1><main style="min-height:100dvh;background:#00a;color:#fff">Fills the screen</main></body></html>', true],
  // Not cleaned on purpose: the frame's sandbox and the content policy alone must stop all of it.
  hostile: ['<!doctype html><html><body style="margin:0"><p style="height:90px">Hostile page</p>'
    + '<script>parent.postMessage({ticoVisualHeight: 5}, "*"); fetch("https://evil.test/fetch"); window.open("https://evil.test/popup");'
    + 'try { document.cookie = "x=1"; localStorage.setItem("x", "1"); parent.document.body.dataset.owned = "yes" } catch (e) {}</script>'
    + '<img src="https://evil.test/pixel.png"><iframe src="https://evil.test/frame"></iframe><img src=x onerror="fetch(\'https://evil.test/onerror\')">'
    + '<form id="f" action="https://evil.test/form"><button id="go">Go</button></form></body></html>', false],
}), encoding: 'utf8'}));

const PNG = Buffer.from('89504e470d0a1a0a0000000d4948445200000001000000010806000000' + '1f15c4890000000d49444154789c6360000002000154a24f5d0000000049454e44ae426082', 'hex');
const SVG = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 200 100"><text x="10" y="60" font-size="40">Hi</text></svg>';
const VIS = 'https://visuals.test/visuals/';
const A = (id, kind, over = {}) => ({id, file_id: id, version: 1, ref: id + '@1', title: 'Title ' + id, kind, name: id + ({image: '.png', svg: '.svg', page: '.html'}[kind] || ''),
  size: 1000, content_type: {image: 'image/png', svg: 'image/svg+xml', page: 'text/html'}[kind], url: `/api/v2/files/${id}?v=1`, removed: false,
  current_version: 1, src: VIS + 'tok-' + id, ...over});

(async () => {
  const browser = process.env.TICO_BROWSER === 'webkit' ? await webkit.launch({headless: true})
    : await chromium.launch({channel: process.env.TICO_BROWSER_CHANNEL === undefined ? 'chrome' : process.env.TICO_BROWSER_CHANNEL || undefined, headless: true});
  const now = new Date().toISOString();
  const MESSAGES = [
    {id: 'm1', from_actor: 'bot:designer', body: 'Here is the chart, the logo and two pages.', created: now, refs: {attachments: [
      A('f-chart', 'image', {width: 800, height: 400}), A('f-logo', 'svg'), A('f-short', 'page'), A('f-tall', 'page')]}},
    {id: 'm2', from_actor: 'bot:designer', body: 'Six pictures.', created: now, refs: {attachments:
      [1, 2, 3, 4, 5, 6].map(i => A('f-six' + i, 'image', {width: 400, height: 200}))}},
    {id: 'm3', from_actor: 'bot:designer', body: 'Older ones.', created: now, refs: {attachments: [
      A('f-moved', 'image', {width: 400, height: 200, current_version: 3}), A('f-gone', 'page', {removed: true, src: undefined, current_version: null}),
      A('f-bad', 'page'), A('f-nosrc', 'image', {src: null, width: 400, height: 200}), A('f-hostile', 'page')]}},
    {id: 'm4', from_actor: 'human:ana', body: 'My photo', created: now, refs: {attachments: [A('f-mine', 'image', {width: 300, height: 300, title: 'Ana photo'})]}},
    {id: 'm5', from_actor: 'bot:designer', body: 'Two full-screen pages.', created: now, refs: {attachments: [A('f-vh', 'page'), A('f-dvh', 'page')]}},
  ];
  const run = async ({viewport, hasTouch = false, label}) => {
    const context = await browser.newContext({viewport, hasTouch, isMobile: hasTouch, serviceWorkers: 'block'});
    await context.addCookies([{name: 'tico_session', value: 'secret', domain: 'tico-ui.test', path: '/', secure: true, httpOnly: true}]);
    const page = await context.newPage();
    const errors = [], outside = [], visualReqs = [], fileReqs = [], held = [];
    // The snapshot as the server sends it: each read signs every visual's address afresh (gen), as on a live update.
    const messages = [...MESSAGES];
    let hold = null, gen = 1;
    const signed = () => gen === 1 ? messages : messages.map(m => ({...m, refs: {...m.refs, attachments: m.refs.attachments.map(a => a.src ? {...a, src: `${a.src}.${gen}`} : a)}}));
    page.on('pageerror', e => { if (!/sandboxed/i.test(e.message)) errors.push(e.message); });
    await context.route('**/*', async route => {
      const req = route.request(), url = new URL(req.url()), p = url.pathname;
      const json = body => route.fulfill({contentType: 'application/json', body: JSON.stringify(body)});
      if (url.hostname === 'evil.test') { outside.push(url.href); return route.fulfill({contentType: 'text/plain', body: 'no'}); }
      if (url.hostname === 'outside.test') return route.fulfill({contentType: 'text/html', body: '<p>Outside</p>'});
      if (url.hostname === 'visuals.test') {
        visualReqs.push({path: p, cookie: req.headers().cookie || ''});
        const id = p.replace('/visuals/tok-', '').replace(/\.\d+$/, '');
        if (hold && id === 'f-chart') await hold;
        const headers = {'Cross-Origin-Resource-Policy': 'cross-origin', 'Referrer-Policy': 'no-referrer', 'X-Content-Type-Options': 'nosniff'};
        if (id === 'f-bad' || id === 'f-gone') return route.fulfill({status: 404, headers: {...headers, 'Content-Security-Policy': "default-src 'none'; sandbox"}, body: ''});
        const page = {'f-short': 'short', 'f-tall': 'tall', 'f-hostile': 'hostile', 'f-vh': 'vh', 'f-dvh': 'dvh', 'f-live-page': 'short'}[id];
        if (page) return route.fulfill({contentType: 'text/html', headers: {...headers, 'Content-Security-Policy': server.policy}, body: server.pages[page]});
        if (id === 'f-logo') return route.fulfill({contentType: 'image/svg+xml', headers: {...headers, 'Content-Security-Policy': server.svg_policy}, body: SVG});
        return route.fulfill({contentType: 'image/png', headers, body: PNG});
      }
      if (p === '/') return route.fulfill({contentType: 'text/html', body: html});
      const ui = p.match(/\/tico\/ui\/((?:app\/|styles\/)?[^/]+\.(?:js|css))$/);
      if (ui && fs.existsSync(uiFile(ui[1]))) return route.fulfill({contentType: ui[1].endsWith('.css') ? 'text/css' : 'application/javascript', body: fs.readFileSync(uiFile(ui[1]), 'utf8')});
      if (p.startsWith('/api/v2/files/')) fileReqs.push(p + url.search);
      if (p === '/api/me') return json({id: 'ana', name: 'Ana', role: 'owner', cloud: true});
      if (p === '/api/employees') return json([{name: 'designer', display_name: 'Designer', host: 'keeper', status: 'active', can_chat: true, schedules: []}]);
      if (p === '/api/issues') return json([]);
      if (p.endsWith('/watch')) return route.fulfill({contentType: 'text/event-stream', body: ': fixture\n\n'});
      if (p === '/api/v2/events') { held.push(route); return; }      // live events (ui/app/live.js), held open
      if (p === '/api/v2/conversations') return json({conversations: url.searchParams.get('chat_with') ? [{id: 'c-designer', kind: 'chat', scope: 'personal', participants: ['human:ana', 'bot:designer']}] : []});
      if (p === '/api/v2/conversations/c-designer/snapshot') return json({messages: signed(), execution: null});
      if (p === '/api/v2/tasks' && req.method() === 'GET') return json({tasks: [task], next_offset: null});
      if (p === '/api/v2/tasks/t1/files') return json({files: taskFiles});
      if (p === '/api/v2/tasks/t1') return json({task, comments: taskComments, events: [], children: [], parent: null, mover: true, messages: [], can_comment: true});
      return json(unrouted(p));
    });
    const task = {id: 't1', title: 'Launch page', owner: 'bot:designer', requester: 'human:ana', status: 'review', lane: 'company', rank: 1, labels: [], links: [],
      parts: {total: 0, done: 0}, version: 1, created: now, updated: now, body: 'Make the page.', attachments: []};
    const tver = (id, mime) => ({n: 1, size: 1000, mime, sha256: 'x', created: now, by: 'bot:designer', comment_id: 'c1', note: null, ask: null, answers: [],
      width: null, height: null, duration_ms: null, media_state: 'none', url: `/api/v2/files/${id}?v=1`, poster_url: null, thumb_url: null});
    const taskFiles = [{id: 'f-chart', name: 'f-chart.png', mime: 'image/png', current_version: 1, archived: false, versions: [tver('f-chart', 'image/png')]},
      {id: 'f-short', name: 'f-short.html', mime: 'text/html', current_version: 1, archived: false, versions: [tver('f-short', 'text/html')]}];
    const taskComments = [{id: 'c1', kind: 'say', from_actor: 'bot:designer', body: 'Chart and page attached.', created: now, answers: [],
      refs: {task: 't1', comment: true, attachments: [A('f-chart', 'image', {width: 800, height: 400}), A('f-short', 'page')]}}];

    const noSideways = async where => {
      const r = await page.evaluate(() => [document.documentElement.scrollWidth, innerWidth]);
      assert(r[0] <= r[1], `${label} ${where}: the page scrolls sideways ${r}`);
    };
    // ---- chat: hold the chart so its held space can be measured before it loads
    let release; hold = new Promise(r => { release = r; });
    await page.goto('https://tico-ui.test/#/bot/designer/chat');
    const m1 = page.locator('[data-message="m1"]');
    await m1.locator('figure.vcard').nth(3).waitFor();
    const chart = m1.locator('figure.vcard[data-kind="image"] .vcard-body');
    const before = await chart.evaluate(el => [el.getBoundingClientRect().width, el.getBoundingClientRect().height]);
    assert(before[1] > 50 && Math.abs(before[1] - before[0] / 2) < 2, `${label}: the chart holds its 2:1 space before it loads ${before}`);
    release(); hold = null;
    await m1.locator('figure.vcard[data-kind="image"] .vcard-body.ready').waitFor();
    const after = await chart.evaluate(el => el.getBoundingClientRect().height);
    assert(Math.abs(after - before[1]) < 1, `${label}: no jump when the chart arrives ${before[1]} -> ${after}`);
    assert.deepEqual(await m1.locator('figure.vcard').evaluateAll(els => els.map(e => e.dataset.kind)), ['image', 'svg', 'page', 'page'], 'in attach order');
    assert.deepEqual(await m1.locator('.vcard-title').allTextContents(), ['Title f-chart', 'Title f-logo', 'Title f-short', 'Title f-tall'], 'caption = title');
    assert.equal(await m1.locator('img.vcard-img').first().getAttribute('alt'), 'Title f-chart', 'the title is the accessible description');
    assert.equal(await m1.locator('iframe.vcard-frame').first().getAttribute('title'), 'Title f-short');
    for (const src of await page.locator('figure.vcard img.vcard-img, figure.vcard iframe').evaluateAll(els => els.map(e => e.getAttribute('src'))))
      assert(src.startsWith(VIS), `${label}: a card shows only from the visual address, not ${src}`);
    // pages: the agreed sandbox; a short page at its own height with no scrollbar; a tall one cut at the cap
    for (const s of await page.locator('iframe.vcard-frame').evaluateAll(els => els.map(e => e.getAttribute('sandbox'))))
      assert.equal(s, 'allow-scripts allow-popups allow-popups-to-escape-sandbox');
    const short = m1.locator('figure.vcard[data-file="f-short"]'), tall = m1.locator('figure.vcard[data-file="f-tall"]');
    await short.locator('.vcard-body.ready').waitFor();
    await tall.locator('.vcard-body.ready').waitFor();
    const sh = await short.evaluate(c => [c.querySelector('.vcard-body').getBoundingClientRect().height, c.querySelector('iframe').getBoundingClientRect().height, c.classList.contains('capped')]);
    assert(sh[0] >= 160 && sh[0] < 260 && Math.abs(sh[0] - sh[1]) < 1 && !sh[2], `${label}: a short page shows at its own height ${sh}`);
    const cap = viewport.width > 760 ? 480 : Math.round(viewport.height * 0.6);
    const th = await tall.evaluate(c => [c.querySelector('.vcard-body').getBoundingClientRect().height, c.querySelector('iframe').getBoundingClientRect().height, c.classList.contains('capped')]);
    assert(Math.abs(th[0] - cap) <= 1 && th[1] >= 2000 && th[2], `${label}: a tall page is cut at the cap ${th} (cap ${cap})`);
    assert(await tall.locator('.vcard-expand').isVisible(), 'Expand on a cut page');
    // a height message from anywhere but the card's own frame is ignored
    await page.evaluate(() => { window.postMessage({ticoVisualHeight: 7}, '*'); for (const f of document.querySelectorAll('iframe')) f.dispatchEvent(new MessageEvent('message', {data: {ticoVisualHeight: 7}})); });
    await page.waitForTimeout(100);
    assert(Math.abs(await short.evaluate(c => c.querySelector('iframe').getBoundingClientRect().height) - sh[1]) < 1, 'only the frame itself sets its height');
    // dark mode: SVG and pages sit on a light card
    await page.evaluate(() => document.documentElement.setAttribute('data-theme', 'dark'));
    await m1.locator('figure.vcard[data-kind="svg"] .vcard-body.ready').waitFor();
    for (const kind of ['svg', 'page']) assert.equal(await m1.locator(`figure.vcard[data-kind="${kind}"] .vcard-body`).first().evaluate(el => getComputedStyle(el).backgroundColor), 'rgb(255, 255, 255)');
    // cap of 4: the other two are chips
    const m2 = page.locator('[data-message="m2"]');
    assert.equal(await m2.locator('figure.vcard').count(), 4);
    assert.equal(await m2.locator('.chat-files > *').count(), 2, 'visuals 5 and 6 are file chips');
    // newer version, removed, failed, no address (chip), hostile page
    const m3 = page.locator('[data-message="m3"]');
    assert(await m3.locator('figure.vcard[data-file="f-moved"] .vcard-newer').isVisible(), 'Newer version link');
    assert.equal((await m3.locator('figure.vcard[data-file="f-gone"] .vcard-body').innerText()).trim(), 'This visual was removed');
    await m3.locator('figure.vcard[data-file="f-bad"][data-state="failed"]').waitFor({timeout: 10000});
    assert.match(await m3.locator('figure.vcard[data-file="f-bad"] .vcard-body').innerText(), /Couldn't show this visual\s+Open in file viewer/);
    assert.equal(await m3.locator('figure.vcard[data-file="f-nosrc"]').count(), 0, 'no visual address: a chip');
    assert.equal(await m3.locator('.chat-files .chat-thumb, .chat-files .pill').count(), 1);
    const hostile = m3.locator('figure.vcard[data-file="f-hostile"]');
    await hostile.locator('.vcard-body.ready').waitFor();
    const hh = await hostile.evaluate(c => c.querySelector('iframe').getBoundingClientRect().height);
    assert(hh >= 90, `${label}: the page's own height message never runs (got ${hh})`);
    // people's attachments too
    assert.equal(await page.locator('[data-message="m4"] figure.vcard img').getAttribute('alt'), 'Ana photo');
    // a page sized by the screen (100vh, 100dvh) settles at the cap with Expand: no sliver, no grow/shrink loop
    // between the reporter and the frame (lead, Oct 19: a known limit; bot builders size pages by content)
    const m5 = page.locator('[data-message="m5"]');
    for (const id of ['f-vh', 'f-dvh']) {
      const card = m5.locator(`figure.vcard[data-file="${id}"]`);
      await m5.locator(`figure.vcard.capped[data-file="${id}"] .vcard-body.ready`).waitFor({timeout: 5000});
      const size = () => card.evaluate(c => [c.querySelector('.vcard-body'), c.querySelector('iframe')].map(e => Math.round(e.getBoundingClientRect().height)));
      const first = await size();
      await page.waitForTimeout(600);
      assert.deepEqual(await size(), first, `${label} ${id}: the height settles`);
      assert(Math.abs(first[0] - cap) <= 1 && Math.abs(first[1] - cap) <= 1, `${label} ${id}: shown at the cap ${first} (cap ${cap})`);
      assert(await card.locator('.vcard-expand').isVisible(), `${label} ${id}: Expand is offered`);
    }
    await noSideways('chat');

    // ---- a link in a page opens a new tab only when clicked; the conversation stays
    if (!hasTouch) {
      const where = page.url();
      const [tab] = await Promise.all([context.waitForEvent('page'), short.frameLocator('iframe').locator('#out').click()]);
      await tab.waitForLoadState();
      assert.equal(tab.url(), 'https://outside.test/read');
      await tab.close();
      assert.equal(page.url(), where, 'the conversation stays');
    }

    // ---- Expand: full screen, zoom, Esc / swipe down back to the same place
    const thread = page.locator('#conv-thread');
    await m1.locator('figure.vcard[data-kind="image"] .vcard-hit').click();
    const full = page.locator('#vcard-full[open]');
    await full.locator('img.vcard-full-img').waitFor();
    const top = await thread.evaluate(el => el.scrollTop);        // where the reader was (the click scrolled to the card)
    assert.equal(await full.locator('img').getAttribute('src'), VIS + 'tok-f-chart');
    if (!hasTouch) {
      await full.locator('img').click();
      assert(await full.evaluate(d => d.classList.contains('zoomed')), 'a click zooms in');
      await page.keyboard.press('Escape');
    } else {
      await full.evaluate(d => {
        const ev = (type, y) => new PointerEvent(type, {bubbles: true, pointerType: 'touch', pointerId: 7, clientX: 100, clientY: y});
        const bar = d.querySelector('.vcard-full-bar');
        bar.dispatchEvent(ev('pointerdown', 100)); bar.dispatchEvent(ev('pointerup', 260));
      });
    }
    await page.locator('#vcard-full').waitFor({state: 'hidden'});
    assert.equal(await thread.evaluate(el => el.scrollTop), top, `${label}: back at the same place`);
    assert(!(await page.evaluate(() => history.state?.vcardFull)), 'its history entry is gone');
    // a page expands into the same sandbox and scrolls there
    await (hasTouch ? tall.locator('.vcard-tap').tap() : tall.locator('.vcard-expand').click());
    await full.locator('iframe.vcard-full-frame').waitFor();
    assert.equal(await full.locator('iframe').getAttribute('sandbox'), 'allow-scripts allow-popups allow-popups-to-escape-sandbox');
    await full.locator('[data-vfull-close]').click();
    await page.locator('#vcard-full').waitFor({state: 'hidden'});

    // ---- a redraw keeps a card's node (and its loaded page); a new version is a new card
    const kept = await page.evaluate(() => {
      const old = document.querySelector('figure.vcard[data-file="f-tall"]');
      V2C.html = ''; v2ChatRender(V2C);
      const a = document.createElement('div'), b = document.createElement('div');
      a.innerHTML = '<figure class="vcard" data-visual-key="m:f@1" data-state="ready" data-fresh-src="old"></figure>';
      b.innerHTML = '<figure class="vcard" data-visual-key="m:f@2" data-state="ready" data-fresh-src="new"></figure><figure class="vcard" data-visual-key="m:f@1" data-state="ready" data-fresh-src="fresh"></figure>';
      const was = a.firstChild; visualKeep(a, b);
      return [old.isConnected, b.children[0] !== was, b.children[1] === was, was.dataset.freshSrc];
    });
    assert.deepEqual(kept, [true, true, true, 'fresh']);

    // ---- live: a new message comes on the event stream; the snapshot read again signs every address afresh. A card
    // already on screen keeps its node and its height and takes the new address; the new message's cards show.
    const was = await tall.evaluate(c => { c.dataset.mark = 'kept'; return c.querySelector('.vcard-body').getBoundingClientRect().height; });
    for (let i = 0; !held.length && i < 100; i++) await page.waitForTimeout(50);
    assert(held.length, `${label}: the page follows the live event stream`);
    gen = 2;
    messages.push({id: 'm6', from_actor: 'bot:designer', body: 'Live one.', created: now, refs: {attachments: [A('f-live', 'image', {width: 400, height: 200}), A('f-live-page', 'page')]}});
    await held.at(-1).fulfill({contentType: 'text/event-stream', body: `id: 9\nevent: messages\ndata: ${JSON.stringify({seq: 9, conversation_id: 'c-designer'})}\n\n`});
    const m6 = page.locator('[data-message="m6"]');
    await m6.locator('figure.vcard[data-kind="page"] .vcard-body.ready').waitFor();
    assert.deepEqual(await m6.locator('img.vcard-img, iframe.vcard-frame').evaluateAll(els => els.map(e => e.getAttribute('src'))),
      [VIS + 'tok-f-live.2', VIS + 'tok-f-live-page.2'], `${label}: a live message's cards show from their visual address`);
    assert.deepEqual(await tall.evaluate(c => [c.dataset.mark, c.dataset.freshSrc, Math.round(c.querySelector('.vcard-body').getBoundingClientRect().height)]),
      ['kept', VIS + 'tok-f-tall.2', Math.round(was)], `${label}: a card on screen is kept through a live update, with the fresh address`);

    // cards never read the signed-in file route (visuals 5 and 6 and the one with no visual address are chips, which still do)
    assert.deepEqual(fileReqs.filter(r => !/f-(six[56]|nosrc)\b/.test(r)), [], `${label}: a card read /api/v2/files`);

    // ---- task comments: the same cards; Open in file viewer opens the task's own file panel at that version
    await page.goto('https://tico-ui.test/#/tasks?view=board');
    await page.waitForFunction(() => typeof TASKS_ST !== 'undefined' && TASKS_ST && !TASKS_ST.loading);
    await page.evaluate(() => taskModalShow(TASKS_ST.tasks.find(t => t.id === 't1')));
    const c1 = page.locator('#task-modal .tcomment', {hasText: 'Chart and page attached.'});
    await c1.locator('figure.vcard').nth(1).waitFor();
    assert.equal(await c1.locator('.tc-thumb, .tc-file').count(), 0, 'a file shown as a card is not also a chip');
    await c1.locator('figure.vcard[data-kind="page"] .vcard-body.ready').waitFor();
    await c1.locator('figure.vcard[data-kind="image"] .vcard-menu > summary').click();
    await c1.locator('figure.vcard[data-kind="image"] [data-vcard-act="open"]').click();
    assert.deepEqual(await page.evaluate(() => [$('#task-modal').tfOpen?.id, $('#task-modal').tfOpen?.n]), ['f-chart', 1]);
    await noSideways('task');

    // ---- nothing reached outside; visuals never carried the app's cookie
    await page.waitForTimeout(300);
    assert.deepEqual(outside, [], `${label}: a page loaded something from outside`);
    assert(visualReqs.length && visualReqs.every(r => !r.cookie), `${label}: a visual request carried a cookie`);
    assert.equal(await page.evaluate(() => document.body.dataset.owned), undefined);
    assert.deepEqual(errors, []);
    await context.close();
  };
  try {
    await run({viewport: {width: 1200, height: 800}, label: 'desktop'});
    await run({viewport: {width: 390, height: 844}, hasTouch: true, label: 'phone'});
    console.log('visual cards ok');
  } finally { await browser.close(); }
})().catch(e => { console.error(e); process.exit(1); });
