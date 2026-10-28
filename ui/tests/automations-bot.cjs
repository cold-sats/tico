// The Automations Bot (ui/app/automations-bot.js) against the fake hub in support/automations-fake.cjs: a message goes
// to the bot's chat naming the open automation (POST /api/v2/chat/automations-bot, refs.automation); its reply comes
// with a proposal, a pending version (GET .../versions?status=pending), as a card: View diff shows the changed lines,
// Turn on restores that version, Discard deletes it. "+ New" opens the bot with no automation. A draft (off, its first
// version pending) shows Pending in the list, and Turn on turns it on. A phone gives the bot its own screen; a computer
// shows it on the right.
const {chromium} = require('playwright');
const assert = require('node:assert/strict');
const {openAutomations, PHONE, DESKTOP, sideways, shot} = require('./support/automations-fake.cjs');

async function ask(page, text) {
  await page.locator('.au-bf .p-text').fill(text);
  await page.locator('.au-bf .p-send').click();
}

(async () => {
  const browser = await chromium.launch();
  try {
    // A phone: the bot's own screen, a proposal, its diff, Turn on, then back to the flow at the new version.
    {
      const {page, errors, writes} = await openAutomations(browser, {viewport: PHONE, hash: '#/automations/au_inbox'});
      await page.waitForSelector('.au-card[data-open="f1"]');
      assert.equal(await page.locator('.au-botp').isVisible(), false);
      await page.locator('.au-botbtn').click();
      await page.waitForFunction(() => document.querySelector('#au-root').dataset.screen === 'bot');
      assert.equal(await page.locator('.au-pane').isVisible(), false);
      assert.equal(await page.locator('.au-botp').isVisible(), true);
      const bar = await page.locator('.au-bf').boundingBox();
      assert.ok(bar.height < 64, 'the composer is one line');
      assert.equal(await page.locator('.au-bf .ask').evaluate(el => getComputedStyle(el).borderTopWidth), '0px', 'one border, the pill’s');
      await ask(page, 'Archive receipts too');
      await page.waitForSelector('.au-prop[data-n="8"]');
      const sent = writes.find(w => w.path === '/api/v2/chat/automations-bot');
      assert.deepEqual(sent.body.refs, {automation: 'au_inbox'});
      assert.equal(sent.body.text, 'Archive receipts too');
      assert.match(await page.locator('.au-msgs').innerText(), /Archive receipts too[\s\S]*receipts are archived first/);
      const card = page.locator('.au-prop[data-n="8"]');
      assert.match(await card.innerText(), /Inbox · dana@acme\.example · v8[\s\S]*Archive receipts before triage/);
      await card.getByRole('button', {name: 'View diff'}).click();
      assert.deepEqual(await card.locator('.au-diff .add').allTextContents(), ['+ filter subject has “receipt” → Archive']);
      assert.equal(await card.locator('.au-diff .del').count(), 0);
      assert.equal(await sideways(page), false);
      await shot(page, 'phone-bot');
      await card.getByRole('button', {name: 'Turn on'}).click();
      await page.waitForSelector('.au-prop[data-n="8"] .pill.ok');
      assert.deepEqual(writes.at(-1), {method: 'POST', path: '/api/v2/automations/au_inbox/versions/8/restore', body: {}});
      assert.equal(await card.getByRole('button', {name: 'Turn on'}).count(), 0);
      await page.locator('.au-botp [data-bot-back]').click();
      await page.waitForFunction(() => document.querySelector('#au-root').dataset.screen === 'detail');
      assert.equal(await page.locator('.au-ver').innerText(), 'v8');
      assert.match(await page.locator('.au-card[data-open="f1"]').innerText(), /2 rules[\s\S]*subject has “receipt”/);
      assert.deepEqual(errors, []);
      await page.close();
    }

    // A computer: the bot beside the flow; Discard; "+ New" opens it with no automation named.
    {
      const {page, errors, writes} = await openAutomations(browser, {viewport: DESKTOP, hash: '#/automations/au_inbox'});
      await page.waitForSelector('.au-card[data-open="f1"]');
      assert.equal(await page.locator('.au-botp').isVisible(), true);
      assert.equal(await page.locator('.au-botbtn').isVisible(), false);
      await ask(page, 'Archive receipts too');
      const card = page.locator('.au-prop[data-n="8"]');
      await card.waitFor();
      await card.getByRole('button', {name: 'View diff'}).click();
      await shot(page, 'desktop-bot');
      await card.getByRole('button', {name: 'Discard'}).click();
      await page.waitForSelector('.au-prop[data-n="8"] .pill:text("Discarded")');
      assert.deepEqual(writes.at(-1), {method: 'DELETE', path: '/api/v2/automations/au_inbox/versions/8', body: {}});
      assert.equal(await page.locator('.au-ver').innerText(), 'v7');

      await page.getByRole('button', {name: '+ New'}).click();
      await page.waitForURL(/#\/automations\/bot$/);
      assert.equal(await page.locator('.au-botp').isVisible(), true);
      await ask(page, 'Watch the sales inbox');
      await page.waitForFunction(() => /What should it watch\?/.test(document.querySelector('.au-msgs').textContent));
      assert.deepEqual(writes.at(-1).body.refs, {});
      assert.equal(await page.locator('.au-prop').count(), 0);
      assert.equal(await sideways(page), false);
      assert.deepEqual(errors, []);
      await page.close();
    }
    // A draft (the bot's: off, version 1 pending): Pending and Off in the list; Turn on enables it and clears Pending.
    {
      const {page, errors, writes} = await openAutomations(browser, {viewport: DESKTOP, hash: '#/automations/au_draft', draft: true});
      await page.waitForSelector('.au-card[data-open="f1"]');
      const row = page.locator('.au-row[data-row="au_draft"]');
      assert.equal(await row.locator('.pill:text-is("Pending")').count(), 1);
      assert.equal(await row.locator('.au-sw').isChecked(), false, 'a draft is off');
      const card = page.locator('.au-prop[data-n="1"]');
      await card.waitFor();
      assert.match(await card.innerText(), /Receipts to archive · v1/);
      await card.getByRole('button', {name: 'Turn on'}).click();
      await page.waitForSelector('.au-prop[data-n="1"] .pill.ok');
      assert.deepEqual(writes.at(-1), {method: 'POST', path: '/api/v2/automations/au_draft/versions/1/restore', body: {}});
      assert.equal(await row.locator('.pill:text-is("Pending")').count(), 0);
      assert.equal(await row.locator('.au-sw').isChecked(), true);
      assert.deepEqual(errors, []);
      await page.close();
    }
    console.log('automations bot ok');
  } finally {
    await browser.close();
  }
})().catch(e => { console.error(e); process.exit(1); });
