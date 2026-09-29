// Ask AI (ui/docs-ask.js): a right-side drawer on a desktop and a full-screen sheet on a phone. Matching docs,
// internal and linked, show at once from the ask response; the Librarian's answer then streams in from the
// conversation watch, with clickable citations; bot text only ever goes through the sanitizing renderer.
// The Librarian being off offers the owner one button. Fixtures only, no network.
const {chromium} = require('playwright');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const html = fs.readFileSync(path.join(__dirname, '../index.html'), 'utf8');

const ANSWER = 'Refunds are issued within **14 days**. [Internal doc · Refund policy](doc:d1) <script>window.pwned=1</script>' +
  ' See [Linked · help.example.com](https://help.example.com/refunds) and [x](javascript:window.pwned=2).';
// A stand-in for marked: enough markdown for links and bold. The page's own safeMd still does the sanitizing.
const markedStub = `window.marked={parse:s=>String(s).replace(/\\*\\*([^*]+)\\*\\*/g,'<strong>$1</strong>').replace(/\\[([^\\]]+)\\]\\(([^)\\s]+)\\)/g,'<a href="$2">$1</a>')}`;

async function open(browser, viewport, state) {
  const page = await browser.newPage({viewport, serviceWorkers: 'block', hasTouch: viewport.width < 760});
  await page.emulateMedia({reducedMotion: 'reduce'});      // the drawer's slide-in would move the box being measured
  const errors = [];
  page.on('pageerror', error => errors.push(error.message));
  await page.route('**/*', route => {
    const url = new URL(route.request().url()), p = url.pathname, method = route.request().method();
    const json = (body, status = 200) => route.fulfill({status, contentType: 'application/json', body: JSON.stringify(body)});
    if (/\/marked\.min\.js$/.test(p)) return route.fulfill({contentType: 'application/javascript', body: markedStub});
    if (url.origin !== 'https://tico-ui.test') return route.abort();
    const ui = p.match(/\/tico\/ui\/([^/]+\.js)$/);
    if (ui && fs.existsSync(path.join(__dirname, '..', ui[1]))) return route.fulfill({contentType: 'application/javascript', body: fs.readFileSync(path.join(__dirname, '..', ui[1]), 'utf8')});
    if (p === '/') return route.fulfill({contentType: 'text/html', body: html});
    if (p === '/api/me') return json({id: 'ana', role: 'owner', name: 'Ana', email: 'ana@example.test', cloud: true});
    if (p === '/api/v2/docs/ask') {
      const body = JSON.parse(route.request().postData());
      state.asked.push(body);
      if (state.off) return json({error: {code: 'librarian_off', detail: 'The Librarian is off'}}, 409);
      return json({conversation_id: 'c1', message_id: 'm' + state.asked.length, results: state.results});
    }
    if (p === '/api/v2/librarian') return json({available: !state.off, state: 'missing', bot: 'librarian', name: 'Librarian', can_turn_on: true});
    if (p === '/api/v2/librarian/turn-on') { state.turnedOn++; state.off = false; return json({bot: 'librarian', state: 'active'}); }
    if (p === '/api/v2/conversations/c1/watch') {
      state.watches++;
      const partial = {messages: [], execution: {state: 'running', text: 'Refunds are issued within 14 days'}};
      const done = {messages: [{id: 'r1', from_actor: 'bot:librarian', in_reply_to: 'm' + state.asked.length, body: ANSWER}], execution: null};
      return route.fulfill({contentType: 'text/event-stream', body: 'retry: 100\nevent: snapshot\ndata: ' + JSON.stringify(state.watches < 2 ? partial : done) + '\n\n'});
    }
    return json({});
  });
  return {page, errors};
}

(async () => {
  const browser = await chromium.launch({headless: true, channel: process.env.TICO_BROWSER_CHANNEL === undefined ? 'chrome' : process.env.TICO_BROWSER_CHANNEL || undefined});
  try {
    for (const [tag, viewport] of [['desktop', {width: 1280, height: 900}], ['phone', {width: 390, height: 800}]]) {
      const state = {asked: [], watches: 0, turnedOn: 0, off: false, results: [
        {type: 'internal', id: 'd1', path: 'finance/refunds.md', title: 'Refund policy', excerpt: 'Refunds within <b>14</b> days', score: 1},
        {type: 'linked', id: 'l1', title: 'Help centre', url: 'https://help.example.com', kind: 'website', description: '', score: 0.4}]};
      const {page, errors} = await open(browser, viewport, state);
      await page.goto('https://tico-ui.test/');
      await page.waitForFunction(() => typeof window.openDocsAsk === 'function');
      await page.evaluate(() => window.openDocsAsk());
      const panel = page.locator('[data-docs-ask]');
      await panel.waitFor();
      assert.equal(await panel.getAttribute('role'), 'dialog', tag + ': it is a dialog');
      assert.ok(await page.locator('.dask-form textarea').evaluate(el => el === document.activeElement), tag + ': the question box has focus');
      const box = await panel.boundingBox();
      if (tag === 'desktop') assert.ok(box.x + box.width >= viewport.width - 1 && box.width <= 461 && box.height >= viewport.height - 1, 'desktop: a right-side drawer');
      else assert.ok(box.x <= 1 && box.width >= viewport.width - 1 && box.height >= viewport.height - 1, 'phone: a full-screen sheet');

      // Ask: the matching docs show at once, before any answer, with type badges and safe text.
      await page.locator('.dask-form textarea').fill('How long do refunds take?');
      await page.keyboard.press('Enter');
      await page.locator('[data-results] li').first().waitFor();
      assert.deepEqual(state.asked, [{question: 'How long do refunds take?', new_conversation: true}], tag + ': asked once, in a fresh conversation');
      assert.deepEqual(await page.locator('.dask-badge').allInnerTexts(), ['Internal doc', 'Linked · Website'], tag + ': type badges');
      assert.equal(await page.locator('[data-results] a').first().getAttribute('href'), '#/docs/d1', tag + ': an internal result opens the doc');
      assert.match(await page.locator('[data-results] li').first().innerText(), /Refunds within 14 days/, tag + ': the excerpt is text, its markup removed');
      const linked = page.locator('[data-results] li[data-type=linked] a');
      assert.equal(await linked.getAttribute('target'), '_blank', tag + ': a linked doc opens at its source');
      assert.match(await linked.getAttribute('rel'), /noopener/);

      // The answer streams in, then is final, with citations as links.
      await page.locator('[data-answer]').filter({hasText: 'Refunds are issued within 14 days'}).first().waitFor();
      await page.locator('a.dask-cite').first().waitFor();
      const cites = page.locator('a.dask-cite');
      assert.equal(await cites.count(), 2, tag + ': two citations');
      assert.equal(await cites.nth(0).getAttribute('href'), '#/docs/d1', tag + ': an internal citation opens the doc in the app');
      assert.equal(await cites.nth(0).getAttribute('target'), null, tag + ': in the same tab');
      assert.equal(await cites.nth(1).getAttribute('href'), 'https://help.example.com/refunds');
      assert.equal(await cites.nth(1).getAttribute('target'), '_blank', tag + ': a linked citation opens at its source');
      assert.equal(await page.locator('[data-answer] script').count(), 0, tag + ': bot text is sanitized');
      assert.equal(await page.evaluate(() => window.pwned), undefined, tag + ': nothing in the answer ran');
      assert.equal(await page.locator('[data-answer] a[href^="javascript"]').count(), 0, tag + ': no script link');
      assert.equal(await page.locator('[data-thinking]').count(), 0, tag + ': done thinking');
      assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth + 1), tag + ': no horizontal scroll');

      // A follow-up stays in the same conversation.
      await page.locator('.dask-form textarea').fill('And for gift cards?');
      await page.keyboard.press('Enter');
      await page.locator('.dask-q').nth(1).waitFor();
      assert.deepEqual(state.asked[1], {question: 'And for gift cards?', conversation_id: 'c1'}, tag + ': same conversation');

      // A citation opens the doc and gets the panel out of the way.
      await page.locator('[data-turn="0"] a.dask-cite').first().click();
      await page.locator('[data-docs-ask]').waitFor({state: 'detached'});
      assert.equal(await page.evaluate(() => location.hash), '#/docs/d1', tag + ': the doc route');
      assert.deepEqual(errors, [], tag + ': no page errors');

      // Escape closes it, and asking with a question from elsewhere asks straight away.
      await page.evaluate(() => window.openDocsAsk('Who signs contracts?'));
      await page.locator('[data-turn]').last().waitFor();
      assert.equal(state.asked.at(-1).question, 'Who signs contracts?', tag + ': openDocsAsk(question) asks it');
      await page.keyboard.press('Escape');
      await page.locator('[data-docs-ask]').waitFor({state: 'detached'});
      await page.close();
    }

    // Off: the owner is told and offered the switch; the switch is asked for once.
    const state = {asked: [], watches: 0, turnedOn: 0, off: true, results: []};
    const {page} = await open(browser, {width: 1280, height: 900}, state);
    await page.goto('https://tico-ui.test/');
    await page.waitForFunction(() => typeof window.openDocsAsk === 'function');
    await page.evaluate(() => window.openDocsAsk('Anyone there?'));
    await page.locator('[data-off] [data-turn-on]').waitFor();
    assert.match(await page.locator('[data-off]').innerText(), /not set up yet/);
    await page.locator('[data-off] [data-turn-on]').click();
    await page.locator('[data-off]').waitFor({state: 'detached'});
    assert.equal(state.turnedOn, 1, 'Turn on the Librarian asked the server once');
  } finally { await browser.close(); }
})().catch(error => { console.error(error); process.exit(1); });
