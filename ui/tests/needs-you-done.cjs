// Needs you: Done on a bot's request card sends only what the card shows. A comment typed earlier in the task window
// (an unsent draft there) does not go with the card's Done and stays for its task; words in the card's own box do go.
const {chromium} = require('playwright');
const assert = require('node:assert/strict');
const {open} = require('./tasks-page.cjs');
const at = minutes => new Date(Date.now() - minutes * 60000).toISOString();
const request = (id, title) => ({id, kind: 'task', title, body: '', owner: 'human:ana', requester: 'bot:writer', status: 'open',
  version: 1, labels: [], created: at(60), updated: at(60), conversation_id: 'c-' + id, ask: null, open_asks: 0});
const items = [request('t-drafted', 'Approve the launch post'), request('t-boxed', 'Pick the launch date')];
(async () => {
  const browser = await chromium.launch({channel: process.env.TICO_BROWSER_CHANNEL ?? 'chrome', headless: true});
  try {
    const {page, errors, posts} = await open(browser, {hash: '#/tasks', extraTasks: items.map(x => ({...x}))});
    await page.evaluate(items => {
      TASK_DRAFTS.set('t-drafted', 'Half a thought from the task window');
      const host = document.createElement('div');
      host.id = 'needs-you-done';
      host.innerHTML = items.map(it => needsV2Item(it, false)).join('');
      document.querySelector('#main').prepend(host);
      host.querySelectorAll('details').forEach(d => { d.open = true; });
    }, items);
    const done = id => posts.filter(x => x.p === `/api/v2/tasks/${id}`).map(x => x.body);
    const card = id => page.locator(`#needs-you-done details[data-v2-id="${id}"]`);

    await card('t-drafted').locator('[data-v2-status="done"]').click();
    await page.waitForFunction(() => !document.querySelector('#needs-you-done details[data-v2-id="t-drafted"]'));
    assert.deepEqual(done('t-drafted'), [{status: 'done', version: 1}], 'the card box was empty: no note');
    assert.equal(await page.evaluate(() => TASK_DRAFTS.get('t-drafted')), 'Half a thought from the task window',
      'the task window draft stays for its task');

    await card('t-boxed').locator('[data-v2-reply]').click();
    await card('t-boxed').locator('.issue-compose textarea').fill('Tuesday the 20th.');
    await card('t-boxed').locator('[data-v2-status="done"]').click();
    await page.waitForFunction(() => !document.querySelector('#needs-you-done details[data-v2-id="t-boxed"]'));
    assert.deepEqual(done('t-boxed'), [{status: 'done', version: 1, note: 'Tuesday the 20th.'}], 'the card box goes with Done');
    assert.equal(posts.filter(x => x.p.endsWith('/comments')).length, 0, 'nothing is also sent as a comment');
    assert.deepEqual(errors, []);
    console.log("Needs you: a card's Done sends only the card's own box, never a task window draft");
  } finally { await browser.close(); }
})().catch(e => {console.error(e); process.exit(1);});
